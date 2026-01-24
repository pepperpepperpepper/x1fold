#!/usr/bin/env python3
"""
Switch between "full-height" and Lenovo Windows "halfblank" semantics on Linux.

Repo source: x1fold/tools/x1fold_mode.py

Current best-known control primitive is the Wacom HID-over-I2C device (slave 0x0A)
enumerated as ACPI WACF2200. On Linux we prefer a hidraw feature report update
over raw I2C writes so we don't fight i2c-hid/wacom kernel drivers.

This tool implements the "digitizer" half/full toggle via hidraw feature report
0x03, patching bytes [10..15] to either:
  - half: 9c 18 2c 28 33 1a
  - full: 00 00 00 00 00 00
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import fcntl


HALF_BYTES = bytes.fromhex("9c 18 2c 28 33 1a")
FULL_BYTES = b"\x00" * 6


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _safe_read_text(path: Path) -> str | None:
    try:
        return read_text(path).strip()
    except OSError:
        return None


def _safe_read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _hex_bytes(data: bytes) -> str:
    return data.hex(" ")


# --- I2C (for fallback mode switch) -----------------------------------------

I2C_SLAVE = 0x0703
I2C_SLAVE_FORCE = 0x0706
I2C_RDWR = 0x0707
I2C_M_RD = 0x0001


class _I2CMsg(ctypes.Structure):
    _fields_ = [
        ("addr", ctypes.c_uint16),
        ("flags", ctypes.c_uint16),
        ("len", ctypes.c_uint16),
        ("buf", ctypes.c_void_p),
    ]


class _I2CRdwrIoctlData(ctypes.Structure):
    _fields_ = [("msgs", ctypes.POINTER(_I2CMsg)), ("nmsgs", ctypes.c_uint32)]

# LenovoModeSwitcher.exe signature: a single 1034-byte I2C write to slave 0x0A
# with a mostly-zero payload. The only stable delta for HALFBLANK is 6 bytes at
# offsets 0x0c..0x11.
LENOVO_LEN1034_SIZE = 1034
LENOVO_LEN1034_PREFIX = bytes.fromhex("04 00 39 03 05 00 04 04 09 20 00 00")
LENOVO_LEN1034_DELTA_OFFSET = 0x0C


def _write_all(fd: int, buf: bytes) -> None:
    offset = 0
    while offset < len(buf):
        written = os.write(fd, buf[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def build_lenovo_len1034_payload(delta6: bytes) -> bytes:
    if len(delta6) != 6:
        raise ValueError("delta must be exactly 6 bytes")
    buf = bytearray(LENOVO_LEN1034_SIZE)
    buf[0 : len(LENOVO_LEN1034_PREFIX)] = LENOVO_LEN1034_PREFIX
    buf[LENOVO_LEN1034_DELTA_OFFSET : LENOVO_LEN1034_DELTA_OFFSET + 6] = delta6
    return bytes(buf)


def i2c_write_payload(dev: str, addr: int, payload: bytes, *, force: bool = True) -> None:
    fd = os.open(dev, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
    try:
        fcntl.ioctl(fd, I2C_SLAVE_FORCE if force else I2C_SLAVE, addr)
        _write_all(fd, payload)
    finally:
        os.close(fd)


def i2c_wr_rd(dev: str, addr: int, write_buf: bytes, read_len: int, *, force: bool = True) -> bytes:
    """
    Perform a single combined I2C write+read (repeated-start) via I2C_RDWR.
    """

    if read_len <= 0:
        raise ValueError("read_len must be > 0")
    fd = os.open(dev, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
    try:
        fcntl.ioctl(fd, I2C_SLAVE_FORCE if force else I2C_SLAVE, addr)

        w = (ctypes.c_uint8 * len(write_buf)).from_buffer_copy(write_buf)
        r = (ctypes.c_uint8 * read_len)()

        msgs = (_I2CMsg * 2)()
        msgs[0].addr = addr
        msgs[0].flags = 0
        msgs[0].len = len(write_buf)
        msgs[0].buf = ctypes.cast(w, ctypes.c_void_p)
        msgs[1].addr = addr
        msgs[1].flags = I2C_M_RD
        msgs[1].len = read_len
        msgs[1].buf = ctypes.cast(r, ctypes.c_void_p)

        data = _I2CRdwrIoctlData(msgs=ctypes.cast(msgs, ctypes.POINTER(_I2CMsg)), nmsgs=2)
        fcntl.ioctl(fd, I2C_RDWR, data)
        return bytes(r)
    finally:
        os.close(fd)


I2C_QUERY_WRITE = bytes.fromhex("04 00 34 02 05 00")
I2C_QUERY_READ_LEN = 1029
I2C_QUERY_TAIL_OFFSET = 0x10  # bytes [0x10..0x11] toggle 00 00 vs 33 1a


def i2c_query_tail(dev: str, addr: int) -> bytes:
    resp = i2c_wr_rd(dev, addr, I2C_QUERY_WRITE, I2C_QUERY_READ_LEN, force=True)
    if len(resp) < I2C_QUERY_TAIL_OFFSET + 2:
        raise OSError("short I2C query response")
    return resp[I2C_QUERY_TAIL_OFFSET : I2C_QUERY_TAIL_OFFSET + 2]


def i2c_tail_mode(tail2: bytes) -> str:
    if tail2 == b"\x33\x1a":
        return "half"
    if tail2 == b"\x00\x00":
        return "full"
    return "unknown"


# --- hidraw feature ioctls --------------------------------------------------


def _ioc(dir_: int, type_: int, nr: int, size: int) -> int:
    # asm-generic/ioctl.h
    IOC_NRBITS = 8
    IOC_TYPEBITS = 8
    IOC_SIZEBITS = 14
    IOC_NRSHIFT = 0
    IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS
    IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS
    IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS
    return (dir_ << IOC_DIRSHIFT) | (type_ << IOC_TYPESHIFT) | (nr << IOC_NRSHIFT) | (size << IOC_SIZESHIFT)


IOC_WRITE = 1
IOC_READ = 2


def hidiocgfeature(size: int) -> int:
    # HIDIOCGFEATURE(len) = _IOC(_IOC_READ|_IOC_WRITE, 'H', 0x07, len)
    return _ioc(IOC_READ | IOC_WRITE, ord("H"), 0x07, size)


def hidiocsfeature(size: int) -> int:
    # HIDIOCSFEATURE(len) = _IOC(_IOC_READ|_IOC_WRITE, 'H', 0x06, len)
    return _ioc(IOC_READ | IOC_WRITE, ord("H"), 0x06, size)


@dataclass(frozen=True)
class HidrawDevice:
    dev: Path
    sysfs: Path
    hid_name: str | None
    hid_id: str | None
    driver: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "dev": str(self.dev),
            "hid_name": self.hid_name,
            "hid_id": self.hid_id,
            "driver": self.driver,
            "sysfs": str(self.sysfs),
        }


def _parse_uevent_kv(uevent_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in uevent_text.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _hid_id_vendor_product(hid_id: str) -> tuple[int, int] | None:
    # Format typically "0005:0000056A:000052BA" (bus:vendor:product).
    m = re.fullmatch(r"[0-9A-Fa-f]{4}:([0-9A-Fa-f]{8}):([0-9A-Fa-f]{8})", hid_id.strip())
    if not m:
        return None
    vendor = int(m.group(1), 16) & 0xFFFF
    product = int(m.group(2), 16) & 0xFFFF
    return vendor, product


def discover_wacom_hidraw_candidates() -> list[HidrawDevice]:
    out: list[HidrawDevice] = []
    for dev in sorted(Path("/dev").glob("hidraw*")):
        sysfs = Path("/sys/class/hidraw") / dev.name / "device"
        if not sysfs.exists():
            continue
        uevent_path = sysfs / "uevent"
        uevent_text = _safe_read_text(uevent_path) or ""
        kv = _parse_uevent_kv(uevent_text)
        hid_name = kv.get("HID_NAME")
        hid_id = kv.get("HID_ID")
        driver = kv.get("DRIVER")
        out.append(HidrawDevice(dev=dev, sysfs=sysfs, hid_name=hid_name, hid_id=hid_id, driver=driver))
    return out


def select_wacf2200_col02_devices(devices: Iterable[HidrawDevice]) -> list[HidrawDevice]:
    """
    Return the hidraw nodes that look like the Wacom digitizer.

    Primary filter is VID:PID 056a:52ba from HID_ID; fall back to HID_NAME
    substring matches (WACF2200/Wacom) if HID_ID is missing/unparseable.
    """

    selected: list[HidrawDevice] = []
    for dev in devices:
        vp = _hid_id_vendor_product(dev.hid_id) if dev.hid_id else None
        if vp and vp == (0x056A, 0x52BA):
            selected.append(dev)
            continue
        name = dev.hid_name or ""
        if "WACF2200" in name or "Wacom" in name:
            selected.append(dev)
    return selected


def hid_get_feature(dev: HidrawDevice, report_id: int, size: int) -> bytes:
    last_exc: OSError | None = None
    for attempt in range(3):
        fd = os.open(str(dev.dev), os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        try:
            buf = bytearray(size)
            if size > 0:
                buf[0] = report_id & 0xFF
            fcntl.ioctl(fd, hidiocgfeature(size), buf, True)
            return bytes(buf)
        except OSError as exc:
            last_exc = exc
            if exc.errno in (110, 121) and attempt < 2:
                time.sleep(0.15 * (attempt + 1))
                continue
            raise
        finally:
            os.close(fd)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("hid_get_feature failed without exception")


def hid_set_feature(dev: HidrawDevice, report: bytes) -> None:
    last_exc: OSError | None = None
    for attempt in range(3):
        fd = os.open(str(dev.dev), os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        try:
            buf = bytearray(report)
            fcntl.ioctl(fd, hidiocsfeature(len(buf)), buf, True)
            return
        except OSError as exc:
            last_exc = exc
            if exc.errno in (110, 121) and attempt < 2:
                time.sleep(0.15 * (attempt + 1))
                continue
            raise
        finally:
            os.close(fd)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("hid_set_feature failed without exception")


def patch_report(report: bytes, offset: int, patch: bytes) -> bytes:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if offset + len(patch) > len(report):
        raise ValueError("patch out of range for report")
    out = bytearray(report)
    out[offset : offset + len(patch)] = patch
    return bytes(out)


def report_mode(report: bytes, offset: int) -> str:
    field = report[offset : offset + 6]
    if field == HALF_BYTES:
        return "half"
    if field == FULL_BYTES:
        return "full"
    return "unknown"


def read_display_status() -> dict[str, Any]:
    drm_root = Path("/sys/class/drm")
    edp: list[dict[str, Any]] = []
    if drm_root.exists():
        for status_path in sorted(drm_root.glob("card*-eDP-*/status")):
            connector_dir = status_path.parent
            edp.append(
                {
                    "connector": connector_dir.name,
                    "status": _safe_read_text(status_path),
                    "dpms": _safe_read_text(connector_dir / "dpms"),
                    "mode": _safe_read_text(connector_dir / "mode"),
                }
            )

    fb0 = Path("/sys/class/graphics/fb0")
    fb: dict[str, Any] | None = None
    if fb0.exists():
        fb = {
            "virtual_size": _safe_read_text(fb0 / "virtual_size"),
            "stride": _safe_read_text(fb0 / "stride"),
            "name": _safe_read_text(fb0 / "name"),
        }

    return {
        "env": {
            "wayland_display": os.environ.get("WAYLAND_DISPLAY"),
            "display": os.environ.get("DISPLAY"),
            "xdg_session_type": os.environ.get("XDG_SESSION_TYPE"),
        },
        "drm_edp": edp,
        "fb0": fb,
    }


def _detect_x11_display() -> str | None:
    env = os.environ.get("DISPLAY")
    if env:
        return env
    try:
        proc = subprocess.run(["pgrep", "-a", "Xorg"], check=False, capture_output=True, text=True)
    except OSError:
        return None
    for line in proc.stdout.splitlines():
        m = re.search(r"\s(:\d+)\b", line)
        if m:
            return m.group(1)
    return None


def _xrandr(display: str, argv: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["DISPLAY"] = display
    return subprocess.run(["xrandr", *argv], check=False, capture_output=True, text=True, env=env)


def _x11_pick_output(display: str, preferred: str | None) -> str | None:
    if preferred:
        return preferred
    proc = _xrandr(display, ["--query"])
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if " connected" not in line:
            continue
        name = line.split()[0].strip()
        if name.startswith("eDP-"):
            return name
    for line in proc.stdout.splitlines():
        if " connected" in line:
            return line.split()[0].strip()
    return None


def _x11_monitor_geometry(display: str, output: str) -> tuple[int, int, int, int] | None:
    proc = _xrandr(display, ["--listmonitors"])
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if output not in line:
            continue
        m = re.search(r"\s(\d+)/(\d+)x(\d+)/(\d+)\+", line)
        if not m:
            continue
        w_px, w_mm, h_px, h_mm = (int(m.group(i)) for i in range(1, 5))
        return w_px, w_mm, h_px, h_mm
    return None


def _x11_set_monitor(display: str, *, name: str, output: str, target_h: int) -> tuple[bool, str]:
    _x11_del_monitor(display, name=name)
    geom = _x11_monitor_geometry(display, output)
    if not geom:
        return False, "failed to parse xrandr --listmonitors"
    w_px, w_mm, full_h, full_mm = geom
    if target_h <= 0 or target_h > full_h:
        return False, f"target height must be in 1..{full_h}"
    target_mm = max(1, int(round(full_mm * (target_h / full_h))))
    geometry = f"{w_px}/{w_mm}x{target_h}/{target_mm}+0+0"
    proc = _xrandr(display, ["--setmonitor", name, geometry, output])
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip() or f"xrandr failed (rc={proc.returncode})"
        return False, msg
    return True, ""


def _x11_del_monitor(display: str, *, name: str) -> tuple[bool, str]:
    proc = _xrandr(display, ["--delmonitor", name])
    if proc.returncode == 0:
        return True, ""
    msg = (proc.stderr or proc.stdout).strip()
    if "BadName" in msg or "failed request" in msg:
        return True, ""
    return False, msg or f"xrandr failed (rc={proc.returncode})"


def apply_display_mode(args: argparse.Namespace) -> dict[str, Any]:
    display_mode = str(args.display).strip().lower()
    if display_mode not in ("auto", "none", "drm", "x11"):
        raise SystemExit("--display must be one of: auto, none, drm, x11")
    if display_mode == "none":
        return {"requested": display_mode, "used": "none"}

    x11_display = _detect_x11_display()
    if display_mode in ("auto", "x11") and x11_display:
        output = _x11_pick_output(x11_display, args.x11_output)
        if not output:
            return {"requested": display_mode, "used": "x11", "ok": False, "error": "failed to find xrandr output"}
        name = args.x11_monitor_name
        if args.mode == "half":
            ok, err = _x11_set_monitor(x11_display, name=name, output=output, target_h=int(args.display_height))
        else:
            ok, err = _x11_del_monitor(x11_display, name=name)
        out: dict[str, Any] = {
            "requested": display_mode,
            "used": "x11",
            "ok": ok,
            "display": x11_display,
            "output": output,
            "monitor": name,
        }
        if err:
            out["error"] = err
        return out

    if display_mode in ("auto", "drm"):
        drm_tool = args.drm_clip or "drm_clip"
        cmd = [drm_tool]
        if args.mode == "half":
            cmd += ["--height", str(int(args.display_height)), "half"]
        else:
            cmd += ["full"]
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        ok = proc.returncode == 0
        out = {"requested": display_mode, "used": "drm", "ok": ok, "cmd": cmd}
        if not ok:
            out["error"] = (proc.stderr or proc.stdout).strip()
        return out

    return {"requested": display_mode, "used": "none", "ok": False, "error": "no usable display backend detected"}


def cmd_status(args: argparse.Namespace) -> int:
    all_devs = discover_wacom_hidraw_candidates()
    candidates = select_wacf2200_col02_devices(all_devs)

    status: dict[str, Any] = {
        "ts": utc_iso(),
        "mode": None,
        "mode_source": None,
        "report_id": f"0x{args.report_id:02x}",
        "report_len": args.report_len,
        "patch_offset": args.patch_offset,
        "expected_half_bytes": _hex_bytes(HALF_BYTES),
        "expected_full_bytes": _hex_bytes(FULL_BYTES),
        "candidates": [d.to_json() for d in candidates],
        "devices": [],
        "display": read_display_status(),
        "i2c_query": {
            "enabled": bool(args.i2c_query),
            "dev": args.i2c_dev or f"/dev/i2c-{int(args.i2c_bus)}",
            "addr": f"0x{int(args.i2c_addr):02x}",
            "tail_offset": f"0x{I2C_QUERY_TAIL_OFFSET:x}",
            "tail_0x10_0x11": None,
            "mode": None,
        },
    }

    for dev in candidates:
        entry: dict[str, Any] = dev.to_json()
        try:
            r = hid_get_feature(dev, args.report_id, args.report_len)
            entry["report_sha256"] = hashlib.sha256(r).hexdigest()
            entry["mode"] = report_mode(r, args.patch_offset)
            entry["bytes_10_15"] = _hex_bytes(r[args.patch_offset : args.patch_offset + 6])
        except OSError as exc:
            entry["error"] = f"[{exc.errno}] {exc.strerror}"
        status["devices"].append(entry)

    # Prefer the Windows-derived I2C query tail as the mode source.
    if args.i2c_query:
        i2c_dev = status["i2c_query"]["dev"]
        i2c_addr = int(args.i2c_addr)
        try:
            tail = i2c_query_tail(str(i2c_dev), i2c_addr)
            status["i2c_query"]["tail_0x10_0x11"] = _hex_bytes(tail)
            status["i2c_query"]["mode"] = i2c_tail_mode(tail)
            status["mode"] = status["i2c_query"]["mode"]
            status["mode_source"] = "i2c_query"
        except OSError as exc:
            status["i2c_query"]["error"] = f"[{exc.errno}] {exc.strerror}"
        except Exception as exc:
            status["i2c_query"]["error"] = f"{type(exc).__name__}: {exc}"

    if not status.get("mode") and status.get("devices"):
        modes = {d.get("mode") for d in status["devices"] if isinstance(d, dict) and d.get("mode")}
        if len(modes) == 1:
            status["mode"] = next(iter(modes))
            status["mode_source"] = "hidraw"

    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    target = HALF_BYTES if args.mode == "half" else FULL_BYTES

    all_devs = discover_wacom_hidraw_candidates()
    candidates = select_wacf2200_col02_devices(all_devs)
    if not candidates:
        raise SystemExit("no hidraw candidates found (need WACF2200 / 056a:52ba?)")

    digitizer = str(args.digitizer).strip().lower()
    if digitizer not in ("auto", "hidraw", "i2c"):
        raise SystemExit("--digitizer must be one of: auto, hidraw, i2c")

    def _read_before() -> tuple[list[dict[str, Any]], list[str]]:
        failures: list[str] = []
        rows: list[dict[str, Any]] = []
        for dev in candidates:
            row: dict[str, Any] = dev.to_json()
            try:
                before = hid_get_feature(dev, args.report_id, args.report_len)
                row["before_mode"] = report_mode(before, args.patch_offset)
                row["before_bytes_10_15"] = _hex_bytes(before[args.patch_offset : args.patch_offset + 6])
            except OSError as exc:
                failures.append(f"{dev.dev}: [{exc.errno}] {exc.strerror}")
                row["error"] = f"[{exc.errno}] {exc.strerror}"
            rows.append(row)
        return rows, failures

    def _verify(rows: list[dict[str, Any]]) -> list[str]:
        failures: list[str] = []
        for dev, row in zip(candidates, rows, strict=False):
            try:
                verify = hid_get_feature(dev, args.report_id, args.report_len)
                row["verify_mode"] = report_mode(verify, args.patch_offset)
                row["verify_bytes_10_15"] = _hex_bytes(verify[args.patch_offset : args.patch_offset + 6])
                if verify[args.patch_offset : args.patch_offset + 6] != target:
                    failures.append(f"{dev.dev}: verify mismatch (got {row['verify_bytes_10_15']})")
            except OSError as exc:
                failures.append(f"{dev.dev}: verify failed [{exc.errno}] {exc.strerror}")
                row["verify_error"] = f"[{exc.errno}] {exc.strerror}"
        return failures

    def _attempt_hidraw() -> tuple[list[dict[str, Any]], list[str]]:
        failures: list[str] = []
        rows: list[dict[str, Any]] = []
        for dev in candidates:
            row: dict[str, Any] = dev.to_json()
            wrote = False
            try:
                before = hid_get_feature(dev, args.report_id, args.report_len)
                before_bytes = before[args.patch_offset : args.patch_offset + 6]
                row["before_mode"] = report_mode(before, args.patch_offset)
                row["before_bytes_10_15"] = _hex_bytes(before_bytes)

                if before_bytes == target:
                    row["already"] = True
                else:
                    after = patch_report(before, args.patch_offset, target)
                    row["after_bytes_10_15"] = _hex_bytes(after[args.patch_offset : args.patch_offset + 6])
                    if args.dry_run:
                        row["dry_run"] = True
                    else:
                        hid_set_feature(dev, after)
                        wrote = True
            except OSError as exc:
                failures.append(f"{dev.dev}: [{exc.errno}] {exc.strerror}")
                row["error"] = f"[{exc.errno}] {exc.strerror}"
            row["_wrote"] = wrote
            rows.append(row)

        if failures:
            for row in rows:
                row.pop("_wrote", None)
            return rows, failures

        for dev, row in zip(candidates, rows, strict=False):
            if not row.get("_wrote"):
                continue
            try:
                verify = hid_get_feature(dev, args.report_id, args.report_len)
                row["verify_mode"] = report_mode(verify, args.patch_offset)
                row["verify_bytes_10_15"] = _hex_bytes(verify[args.patch_offset : args.patch_offset + 6])
                if verify[args.patch_offset : args.patch_offset + 6] != target:
                    failures.append(f"{dev.dev}: verify mismatch (got {row['verify_bytes_10_15']})")
            except OSError as exc:
                failures.append(f"{dev.dev}: verify failed [{exc.errno}] {exc.strerror}")
                row["verify_error"] = f"[{exc.errno}] {exc.strerror}"

        for row in rows:
            row.pop("_wrote", None)
        return rows, failures

    def _attempt_i2c() -> tuple[list[dict[str, Any]], list[str]]:
        rows, failures = _read_before()
        if not args.dry_run:
            dev = args.i2c_dev or f"/dev/i2c-{int(args.i2c_bus)}"
            addr = int(args.i2c_addr)
            full_payload = build_lenovo_len1034_payload(FULL_BYTES)
            half_payload = build_lenovo_len1034_payload(HALF_BYTES)
            try:
                if args.mode == "half":
                    # Match Windows: an initial "all-zero tail" write followed by the 6-byte delta write.
                    i2c_write_payload(dev, addr, full_payload, force=True)
                    i2c_write_payload(dev, addr, half_payload, force=True)
                else:
                    i2c_write_payload(dev, addr, full_payload, force=True)
            except OSError as exc:
                failures.append(f"i2c write failed: [{exc.errno}] {exc.strerror}")
        for row in rows:
            row["after_bytes_10_15"] = _hex_bytes(target)
        failures.extend(_verify(rows))
        return rows, failures

    backend_used = None
    attempted: list[str] = []
    if digitizer in ("auto", "hidraw"):
        attempted.append("hidraw")
        rows, failures = _attempt_hidraw()
        if not failures:
            backend_used = "hidraw"
            results = rows
        elif digitizer == "hidraw":
            results = rows
        else:
            attempted.append("i2c")
            rows2, failures2 = _attempt_i2c()
            if not failures2:
                backend_used = "i2c"
                results = rows2
                failures = []
            else:
                results = rows2
                failures = failures2
    else:
        attempted.append("i2c")
        rows, failures = _attempt_i2c()
        backend_used = "i2c" if not failures else None
        results = rows

    display_result = apply_display_mode(args)

    out = {
        "ts": utc_iso(),
        "mode": args.mode,
        "digitizer_backend_requested": digitizer,
        "digitizer_backend_used": backend_used,
        "digitizer_attempted": attempted,
        "display": display_result,
        "report_id": f"0x{args.report_id:02x}",
        "report_len": args.report_len,
        "patch_offset": args.patch_offset,
        "patch_bytes": _hex_bytes(target),
        "i2c": {
            "dev": args.i2c_dev or f"/dev/i2c-{int(args.i2c_bus)}",
            "addr": f"0x{int(args.i2c_addr):02x}",
            "payload_len": LENOVO_LEN1034_SIZE,
            "delta_offset": f"0x{LENOVO_LEN1034_DELTA_OFFSET:x}",
        },
        "dry_run": args.dry_run,
        "results": results,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    display_info = out.get("display", {})
    if (
        display_info.get("ok") is False
        and not display_info.get("skipped")
        and str(args.display).strip().lower() != "none"
    ):
        raise SystemExit(display_info.get("error", "display backend failed"))
    if failures:
        raise SystemExit("; ".join(failures))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Switch X1 Fold full-height vs halfblank mode on Linux.")
    parser.add_argument("--report-id", type=lambda s: int(s, 0), default=0x03, help="Feature report ID (default: 0x03)")
    parser.add_argument("--report-len", type=int, default=256, help="Feature report length to get/set (default: 256)")
    parser.add_argument("--patch-offset", type=int, default=10, help="Byte offset in report to patch (default: 10)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Print current mode and device details as JSON.")
    p_status.add_argument(
        "--no-i2c-query",
        dest="i2c_query",
        action="store_false",
        help="Skip the Windows-derived I2C query (w6+r1029).",
    )
    p_status.set_defaults(i2c_query=True)
    p_status.add_argument("--i2c-bus", type=int, default=1, help="I2C bus number for 0x0A query (default: 1).")
    p_status.add_argument(
        "--i2c-addr",
        type=lambda s: int(s, 0),
        default=0x0A,
        help="7-bit I2C address for query (default: 0x0a).",
    )
    p_status.add_argument(
        "--i2c-dev",
        default="",
        help="Override I2C device path for query (default: /dev/i2c-<bus>).",
    )
    p_status.set_defaults(fn=cmd_status)

    p_set = sub.add_parser("set", help="Set digitizer mode (hidraw, with I2C fallback).")
    p_set.add_argument("mode", choices=["half", "full"], help="Target mode.")
    p_set.add_argument(
        "--digitizer",
        choices=["auto", "hidraw", "i2c"],
        default="auto",
        help="Digitizer control backend (default: auto).",
    )
    p_set.add_argument(
        "--display",
        choices=["auto", "none", "drm", "x11"],
        default="auto",
        help="Display geometry backend (default: auto).",
    )
    p_set.add_argument(
        "--display-height",
        type=int,
        default=1240,
        help="Target height in pixels for half mode (default: 1240).",
    )
    p_set.add_argument(
        "--drm-clip",
        default="",
        help="Path to drm_clip helper (default: drm_clip from $PATH).",
    )
    p_set.add_argument(
        "--x11-monitor-name",
        default="X1FOLD_HALF",
        help="XRandR monitor name used for x11 backend (default: X1FOLD_HALF).",
    )
    p_set.add_argument(
        "--x11-output",
        default="",
        help="XRandR output name override for x11 backend (default: auto pick eDP-*).",
    )
    p_set.add_argument("--i2c-bus", type=int, default=1, help="I2C bus number for 0x0A payload (default: 1).")
    p_set.add_argument(
        "--i2c-addr",
        type=lambda s: int(s, 0),
        default=0x0A,
        help="7-bit I2C address for mode payload (default: 0x0a).",
    )
    p_set.add_argument(
        "--i2c-dev",
        default="",
        help="Override I2C device path (default: /dev/i2c-<bus>).",
    )
    p_set.add_argument("--dry-run", action="store_true", help="Compute and verify without writing.")
    p_set.set_defaults(fn=cmd_set)
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.report_len <= 0 or args.report_len > 4096:
        raise SystemExit("--report-len must be in 1..4096")
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main(os.sys.argv[1:]))
