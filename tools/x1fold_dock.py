#!/usr/bin/env python3
"""
Read/watch the Lenovo X1 Fold magnetic keyboard "dock" state.

Repo source: x1fold/tools/x1fold_dock.py

Best-known ACPI sources (see docs/ACPI_STATUS.md 2026-01-08):
  - \\_SB.PC00.LPCB.EC.CMMD (bit7 = dock, low 7 bits = MODEID)
  - \\_SB.DEVD.GDST        (returns dock bit; also stores into \\_SB.DEVD.DOST)

This tool is intentionally conservative: it supports /proc/acpi/call (acpi_call
kernel module) for bring-up, and can also read the EC byte directly via ec_sys
debugfs. Long-term we want a proper in-kernel ACPI driver for LEN009E that
exposes a normal Linux event stream (SW_DOCK) and/or a sysfs attribute.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_GDST = r"\_SB.DEVD.GDST"
DEFAULT_CMMD = r"\_SB.PC00.LPCB.EC.CMMD"
DEFAULT_ACPI_CALL = Path("/proc/acpi/call")
DEFAULT_EC_IO = Path("/sys/kernel/debug/ec/ec0/io")
DEFAULT_EC_OFFSET = 0xC1
DEFAULT_DOCK_SYSFS = Path("/sys/devices/platform/dock.0/docked")


def _read_int_file(path: Path) -> int | None:
    try:
        s = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    try:
        return int(s, 0)
    except ValueError:
        return None


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_acpi_call_int(output: str) -> int | None:
    """
    acpi_call output is typically "0x0" / "0x1" or an error string.
    """
    s = output.strip()
    if not s:
        return None
    if s.startswith("Error:") or "AE_" in s:
        return None
    if re.fullmatch(r"0x[0-9a-fA-F]+", s) or re.fullmatch(r"[0-9]+", s):
        try:
            return int(s, 0)
        except ValueError:
            return None
    return None


def acpi_call(expr: str, path: Path = DEFAULT_ACPI_CALL) -> str:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing (need acpi_call kernel module?)")
    path.write_text(f"{expr}\n", encoding="utf-8")
    return path.read_text(encoding="utf-8", errors="replace").strip()


def ec_sys_read_u8(io_path: Path, offset: int) -> int:
    if not io_path.exists():
        raise FileNotFoundError(f"{io_path} missing (need ec_sys + mounted debugfs?)")
    if offset < 0 or offset > 0xFFFF:
        raise ValueError("EC offset out of range")
    with io_path.open("rb") as f:
        f.seek(offset)
        b = f.read(1)
    if len(b) != 1:
        raise OSError("short read from EC io")
    return int(b[0])


@dataclass(frozen=True)
class DockState:
    docked: int | None
    modeid: int | None
    cmmd: int | None
    gdst: int | None
    dock_sysfs: int | None
    errors: dict[str, str]

    def to_json(self) -> dict[str, Any]:
        return {
            "docked": self.docked,
            "modeid": self.modeid,
            "cmmd": self.cmmd,
            "gdst": self.gdst,
            "dock_sysfs": self.dock_sysfs,
            "errors": dict(self.errors),
        }


def read_dock_state(
    *,
    backend: str,
    acpi_call_path: Path,
    gdst_path: str,
    cmmd_path: str,
    ec_io: Path,
    ec_offset: int,
    dock_sysfs: Path,
) -> DockState:
    errors: dict[str, str] = {}

    gdst_out: str | None = None
    cmmd_out: str | None = None
    gdst: int | None = None
    cmmd: int | None = None
    dock_sysfs_val: int | None = None

    backend = backend.strip().lower()
    if backend not in ("auto", "acpi_call", "ec_sys"):
        raise ValueError("backend must be one of: auto, acpi_call, ec_sys")
    if backend == "acpi_call" and not acpi_call_path.exists():
        errors["acpi_call"] = f"{acpi_call_path} missing (need acpi_call kernel module?)"

    if dock_sysfs.exists():
        dock_sysfs_val = _read_int_file(dock_sysfs)
        if dock_sysfs_val not in (0, 1):
            errors["dock_sysfs"] = f"invalid dock sysfs value: {dock_sysfs_val!r}"
            dock_sysfs_val = None

    if backend in ("auto", "acpi_call") and acpi_call_path.exists():
        try:
            gdst_out = acpi_call(gdst_path, acpi_call_path)
            gdst = _parse_acpi_call_int(gdst_out)
            if gdst is None:
                errors["gdst"] = gdst_out
        except OSError as exc:
            errors["gdst"] = f"{type(exc).__name__}: {exc}"

        try:
            cmmd_out = acpi_call(cmmd_path, acpi_call_path)
            cmmd = _parse_acpi_call_int(cmmd_out)
            if cmmd is None:
                errors["cmmd"] = cmmd_out
        except OSError as exc:
            errors["cmmd"] = f"{type(exc).__name__}: {exc}"

    if (backend in ("auto", "ec_sys")) and cmmd is None:
        try:
            cmmd = ec_sys_read_u8(ec_io, ec_offset)
        except OSError as exc:
            errors["ec_sys"] = f"{type(exc).__name__}: {exc}"

    docked: int | None = None
    modeid: int | None = None

    if cmmd is not None:
        docked = (cmmd >> 7) & 0x1
        modeid = cmmd & 0x7F
    if gdst in (0, 1):
        docked = gdst
    # sysfs dock state is a best-effort fallback only. Some platforms expose a
    # generic ACPI dock device that may not track the X1 Fold keyboard magnet.
    if docked is None and dock_sysfs_val in (0, 1):
        docked = dock_sysfs_val

    return DockState(
        docked=docked,
        modeid=modeid,
        cmmd=cmmd,
        gdst=gdst,
        dock_sysfs=dock_sysfs_val,
        errors=errors,
    )


def cmd_status(args: argparse.Namespace) -> int:
    state = read_dock_state(
        backend=args.backend,
        acpi_call_path=args.acpi_call,
        gdst_path=args.gdst,
        cmmd_path=args.cmmd,
        ec_io=args.ec_io,
        ec_offset=args.ec_offset,
        dock_sysfs=args.dock_sysfs,
    )
    out = {
        "ts": utc_iso(),
        "backend": args.backend,
        "acpi_call": str(args.acpi_call),
        "ec_io": str(args.ec_io),
        "ec_offset": f"0x{args.ec_offset:x}",
        "paths": {"dock_sysfs": str(args.dock_sysfs), "gdst": args.gdst, "cmmd": args.cmmd},
        "state": state.to_json(),
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    last: DockState | None = None
    count = 0
    while True:
        state = read_dock_state(
            backend=args.backend,
            acpi_call_path=args.acpi_call,
            gdst_path=args.gdst,
            cmmd_path=args.cmmd,
            ec_io=args.ec_io,
            ec_offset=args.ec_offset,
            dock_sysfs=args.dock_sysfs,
        )
        if last is None and args.print_initial:
            print(json.dumps({"ts": utc_iso(), "event": "initial", "state": state.to_json()}, sort_keys=True))
            last = state
            continue
        if last is not None and state.docked == last.docked and state.modeid == last.modeid:
            time.sleep(args.interval_s)
            continue
        print(json.dumps({"ts": utc_iso(), "event": "change", "state": state.to_json()}, sort_keys=True))
        last = state
        count += 1
        if args.max_events and count >= args.max_events:
            return 0
        time.sleep(args.interval_s)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read/watch the Lenovo X1 Fold dock (magnet keyboard) state.")
    parser.add_argument(
        "--backend",
        choices=["auto", "acpi_call", "ec_sys"],
        default="auto",
        help="Backend for reading dock state (default: auto).",
    )
    parser.add_argument(
        "--dock-sysfs",
        type=Path,
        default=DEFAULT_DOCK_SYSFS,
        help="Optional sysfs dock state file (default: /sys/devices/platform/dock.0/docked).",
    )
    parser.add_argument(
        "--acpi-call",
        type=Path,
        default=DEFAULT_ACPI_CALL,
        help="Path to acpi_call proc node (default: /proc/acpi/call).",
    )
    parser.add_argument("--gdst", default=DEFAULT_GDST, help="ACPI path for GDST (default: \\_SB.DEVD.GDST).")
    parser.add_argument("--cmmd", default=DEFAULT_CMMD, help="ACPI path for CMMD (default: \\_SB.PC00.LPCB.EC.CMMD).")
    parser.add_argument(
        "--ec-io",
        type=Path,
        default=DEFAULT_EC_IO,
        help="ec_sys EC io path (default: /sys/kernel/debug/ec/ec0/io).",
    )
    parser.add_argument(
        "--ec-offset",
        type=lambda s: int(s, 0),
        default=DEFAULT_EC_OFFSET,
        help="EC offset for CMMD (default: 0xc1).",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Print current dock/mode state as JSON.")
    p_status.set_defaults(fn=cmd_status)

    p_watch = sub.add_parser("watch", help="Poll and print JSON lines on changes.")
    p_watch.add_argument("--interval-s", type=float, default=0.2, help="Polling interval in seconds (default: 0.2).")
    p_watch.add_argument("--print-initial", action="store_true", help="Emit an initial state event immediately.")
    p_watch.add_argument("--max-events", type=int, default=0, help="Stop after N change events (0 = infinite).")
    p_watch.set_defaults(fn=cmd_watch)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(args, "max_events"):
        args.max_events = int(args.max_events or 0)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main(list(__import__("sys").argv[1:])))
