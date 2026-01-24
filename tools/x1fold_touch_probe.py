#!/usr/bin/env python3
"""
Minimal evdev probe to measure observed ABS ranges while you touch the screen.

This is intended for diagnosing docked/half-mode touch coordinate mismatches.
It reads from /dev/input/event* directly (no external deps) and prints JSON.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import select
import struct
import time
from pathlib import Path
from typing import Any

# Linux input-event constants (subset)
EV_ABS = 0x03

ABS_X = 0x00
ABS_Y = 0x01
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ioc(dir_: int, type_: str, nr: int, size: int) -> int:
    _IOC_NRBITS = 8
    _IOC_TYPEBITS = 8
    _IOC_SIZEBITS = 14
    _IOC_DIRBITS = 2

    _IOC_NRSHIFT = 0
    _IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
    _IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
    _IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS

    return (
        (dir_ << _IOC_DIRSHIFT)
        | (ord(type_) << _IOC_TYPESHIFT)
        | (nr << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


def _ior(type_: str, nr: int, size: int) -> int:
    _IOC_READ = 2
    return _ioc(_IOC_READ, type_, nr, size)


def _iow(type_: str, nr: int, size: int) -> int:
    _IOC_WRITE = 1
    return _ioc(_IOC_WRITE, type_, nr, size)


def _eviocgname(buflen: int) -> int:
    # EVIOCGNAME(len) _IOC(_IOC_READ, 'E', 0x06, len)
    return _ior("E", 0x06, buflen)


def _eviocgabs(code: int) -> int:
    # EVIOCGABS(abs) _IOR('E', 0x40 + (abs), struct input_absinfo)
    absinfo_sz = struct.calcsize("iiiiii")
    return _ior("E", 0x40 + int(code), absinfo_sz)


def _eviocgrab() -> int:
    # EVIOCGRAB _IOW('E', 0x90, int)
    return _iow("E", 0x90, struct.calcsize("i"))


def _try_ioctl(fd: int, req: int, buf: bytes) -> bytes | None:
    try:
        return fcntl.ioctl(fd, req, buf)
    except OSError:
        return None


def _read_name(fd: int) -> str | None:
    buf = b"\x00" * 256
    out = _try_ioctl(fd, _eviocgname(len(buf)), buf)
    if not out:
        return None
    return out.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip() or None


def _read_absinfo(fd: int, code: int) -> dict[str, int] | None:
    buf = b"\x00" * struct.calcsize("iiiiii")
    out = _try_ioctl(fd, _eviocgabs(code), buf)
    if not out:
        return None
    value, minimum, maximum, fuzz, flat, resolution = struct.unpack("iiiiii", out)
    return {
        "value": int(value),
        "min": int(minimum),
        "max": int(maximum),
        "fuzz": int(fuzz),
        "flat": int(flat),
        "resolution": int(resolution),
    }


def _find_event_by_name(substring: str) -> str | None:
    if not substring:
        return None
    for name_path in sorted(Path("/sys/class/input").glob("event*/device/name")):
        try:
            name = name_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if substring.lower() in name.lower():
            event = name_path.parts[-3]  # .../eventX/device/name
            return f"/dev/input/{event}"
    return None


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Probe touchscreen ABS ranges by reading /dev/input/event*.")
    p.add_argument(
        "--event",
        default="",
        help="Input event device path (e.g. /dev/input/event8). If unset, auto-detect by name.",
    )
    p.add_argument(
        "--name-contains",
        default="Wacom HID 52BA Finger",
        help="Auto-detect event device whose sysfs name contains this substring (default: Wacom HID 52BA Finger).",
    )
    p.add_argument("--seconds", type=float, default=10.0, help="How long to sample for (default: 10).")
    p.add_argument(
        "--grab",
        action="store_true",
        help="EVIOCGRAB the device while sampling so touches don't click around (best effort).",
    )
    args = p.parse_args(argv)

    dev = (args.event or "").strip()
    if not dev:
        dev = _find_event_by_name(str(args.name_contains or "")) or ""
    if not dev:
        print(
            json.dumps(
                {
                    "ts": _utc_iso(),
                    "ok": False,
                    "error": "failed to find event device",
                    "name_contains": str(args.name_contains),
                },
                sort_keys=True,
            )
        )
        return 2

    try:
        fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        print(
            json.dumps(
                {
                    "ts": _utc_iso(),
                    "ok": False,
                    "error": f"open_failed: {type(exc).__name__}: {exc}",
                    "event": dev,
                },
                sort_keys=True,
            )
        )
        return 1

    try:
        name = _read_name(fd)
        grab_ok = False
        if bool(args.grab):
            try:
                fcntl.ioctl(fd, _eviocgrab(), struct.pack("i", 1))
                grab_ok = True
            except OSError:
                grab_ok = False

        codes = {
            "ABS_X": ABS_X,
            "ABS_Y": ABS_Y,
            "ABS_MT_POSITION_X": ABS_MT_POSITION_X,
            "ABS_MT_POSITION_Y": ABS_MT_POSITION_Y,
        }
        absinfo: dict[str, dict[str, int]] = {}
        for k, code in codes.items():
            info = _read_absinfo(fd, code)
            if info:
                absinfo[k] = info

        observed: dict[str, dict[str, int]] = {}
        for k in absinfo.keys():
            observed[k] = {"min": 2**31 - 1, "max": -(2**31)}

        fmt = "llHHi"  # struct input_event (native)
        ev_sz = struct.calcsize(fmt)
        start = time.monotonic()
        deadline = start + float(args.seconds)

        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            timeout = max(0.0, deadline - now)
            r, _, _ = select.select([fd], [], [], min(0.25, timeout))
            if not r:
                continue
            try:
                data = os.read(fd, ev_sz * 64)
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    continue
                raise
            for off in range(0, len(data) - (len(data) % ev_sz), ev_sz):
                _, _, etype, code, value = struct.unpack(fmt, data[off : off + ev_sz])
                if etype != EV_ABS:
                    continue
                for k, want in codes.items():
                    if want != code:
                        continue
                    if k not in observed:
                        continue
                    if value < observed[k]["min"]:
                        observed[k]["min"] = int(value)
                    if value > observed[k]["max"]:
                        observed[k]["max"] = int(value)

        elapsed = round(time.monotonic() - start, 3)

        # Release grab (best effort)
        if grab_ok:
            try:
                fcntl.ioctl(fd, _eviocgrab(), struct.pack("i", 0))
            except OSError:
                pass

        # Normalize observed ranges to 0..1 using evdev min/max where available.
        normalized: dict[str, dict[str, float]] = {}
        for k, info in absinfo.items():
            obs = observed.get(k) or {}
            mn = info.get("min")
            mx = info.get("max")
            if not isinstance(mn, int) or not isinstance(mx, int) or mx <= mn:
                continue
            omin = obs.get("min")
            omax = obs.get("max")
            if not isinstance(omin, int) or not isinstance(omax, int):
                continue
            if omin == 2**31 - 1 or omax == -(2**31):
                continue
            normalized[k] = {
                "min": float(omin - mn) / float(mx - mn),
                "max": float(omax - mn) / float(mx - mn),
            }

        print(
            json.dumps(
                {
                    "ts": _utc_iso(),
                    "ok": True,
                    "event": dev,
                    "name": name,
                    "grab": bool(args.grab),
                    "grab_ok": bool(grab_ok),
                    "seconds": float(args.seconds),
                    "elapsed_s": float(elapsed),
                    "absinfo": absinfo,
                    "observed": observed,
                    "normalized": normalized,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main(os.sys.argv[1:]))

