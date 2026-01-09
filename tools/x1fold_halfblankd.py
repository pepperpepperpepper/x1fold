#!/usr/bin/env python3
"""
Daemon/policy loop: apply X1 Fold halfblank/full behavior based on dock state.

Repo source: x1fold/tools/x1fold_halfblankd.py

This is intentionally userspace: it coordinates (A) digitizer mode and (B)
display geometry, which are both OS policy. The dock signal itself should
eventually come from a proper kernel driver, but for now we can poll via
/proc/acpi/call (see x1fold/tools/x1fold_dock.py).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from x1fold_dock import DockState, read_dock_state


def _safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _dmi_info() -> dict[str, str]:
    """
    Best-effort SMBIOS info used to gate auto-start on supported hardware.
    """

    root = Path("/sys/class/dmi/id")
    keys = ("sys_vendor", "product_name", "product_version", "product_sku")
    out: dict[str, str] = {}
    for k in keys:
        v = _safe_read_text(root / k)
        if v:
            out[k] = v
    return out


def _looks_like_x1fold(dmi: dict[str, str]) -> bool:
    vendor = dmi.get("sys_vendor", "")
    if vendor and vendor.upper() != "LENOVO":
        return False
    for k in ("product_version", "product_sku", "product_name"):
        v = dmi.get(k, "")
        if "ThinkPad X1 Fold" in v:
            return True
    # Allow machine-type codes seen on X1 Fold 16 Gen 1 (21ES/21ET).
    pn = dmi.get("product_name", "")
    if pn.startswith(("21ES", "21ET")):
        return True
    return False


def _default_repo_cmd(mode: str) -> list[str]:
    repo_root = Path(__file__).resolve().parents[1]
    wrapper = repo_root / "scripts" / "halfblank_switch.sh"
    if wrapper.exists():
        return [str(wrapper), mode]
    return ["true"]


def _default_cmd(mode: str) -> list[str]:
    for candidate in (
        Path("/usr/local/bin/halfblank_switch.sh"),
        Path("/usr/local/bin/halfblank_switch"),
    ):
        if candidate.exists():
            return [str(candidate), mode]
    return _default_repo_cmd(mode)


@dataclass(frozen=True)
class Commands:
    half: list[str]
    full: list[str]
    status: list[str]


def _parse_cmd(value: str) -> list[str]:
    # Accept a shell-like string for convenience.
    return shlex.split(value)


def run_cmd(cmd: list[str], *, dry_run: bool, timeout_s: float | None) -> int:
    if dry_run:
        print(f"[dry-run] {' '.join(shlex.quote(c) for c in cmd)}")
        return 0
    try:
        proc = subprocess.run(cmd, check=False, timeout=timeout_s)
        return int(proc.returncode)
    except subprocess.TimeoutExpired:
        _log("cmd_timeout", cmd=cmd, timeout_s=timeout_s)
        return 124


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log(event: str, **extra: object) -> None:
    out = {"ts": utc_iso(), "event": event, **extra}
    print(json.dumps(out, sort_keys=True), flush=True)


def _status_mode(status: dict) -> str | None:
    top = status.get("mode")
    if isinstance(top, str) and top:
        return top
    devices = status.get("devices")
    if not isinstance(devices, list) or not devices:
        return None
    modes: set[str] = set()
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        mode = dev.get("mode")
        if isinstance(mode, str) and mode:
            modes.add(mode)
    if len(modes) == 1:
        return next(iter(modes))
    if "half" in modes:
        return "half"
    if "full" in modes:
        return "full"
    return None


def run_status(cmd: list[str], *, dry_run: bool, timeout_s: float | None) -> tuple[dict | None, str | None]:
    if dry_run:
        return None, None
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout_s)
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    except subprocess.TimeoutExpired:
        return None, f"TimeoutExpired: timeout_s={timeout_s}"
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip() or f"rc={proc.returncode}"
        return None, msg
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"JSONDecodeError: {exc}"

def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            tmp_fd = None
            json.dump(data, f, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        # mkstemp() creates 0600; make it readable for the per-user UI helper.
        os.chmod(path, 0o644)
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Auto-apply halfblank/full based on dock (keyboard magnet) state.")
    parser.add_argument(
        "--require-x1fold",
        action="store_true",
        help="Exit successfully if not running on a ThinkPad X1 Fold (DMI gate).",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("/run/x1fold-halfblank/state.json"),
        help="Write current desired/observed state to this JSON file (default: /run/x1fold-halfblank/state.json).",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "acpi_call", "ec_sys"],
        default="auto",
        help="Backend for reading dock state (default: auto).",
    )
    parser.add_argument("--acpi-call", type=Path, default=Path("/proc/acpi/call"), help="Path to /proc/acpi/call.")
    parser.add_argument("--gdst", default=r"\_SB.DEVD.GDST", help="ACPI path for dock getter (default: \\_SB.DEVD.GDST).")
    parser.add_argument(
        "--cmmd",
        default=r"\_SB.PC00.LPCB.EC.CMMD",
        help="ACPI path for raw CMMD field (default: \\_SB.PC00.LPCB.EC.CMMD).",
    )
    parser.add_argument(
        "--ec-io",
        type=Path,
        default=Path("/sys/kernel/debug/ec/ec0/io"),
        help="ec_sys EC io path (default: /sys/kernel/debug/ec/ec0/io).",
    )
    parser.add_argument(
        "--ec-offset",
        type=lambda s: int(s, 0),
        default=0xC1,
        help="EC offset for CMMD (default: 0xc1).",
    )
    parser.add_argument("--interval-s", type=float, default=0.2, help="Polling interval (seconds).")
    parser.add_argument(
        "--cmd-timeout-s",
        type=float,
        default=8.0,
        help="Timeout for helper commands (seconds; default: 8).",
    )
    parser.add_argument(
        "--apply-initial",
        action="store_true",
        help="Apply full/half immediately based on the initial dock state.",
    )
    parser.add_argument(
        "--enforce-every-s",
        type=float,
        default=1.0,
        help="While dock state is stable, re-check and re-apply mode if it drifts (0 disables; default: 1s).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands but do not execute them.")
    parser.add_argument(
        "--digitizer",
        choices=["auto", "hidraw", "i2c"],
        default="auto",
        help="Digitizer backend for x1fold_mode.py set (default: auto).",
    )
    parser.add_argument(
        "--display",
        choices=["auto", "none", "drm", "x11"],
        default="auto",
        help="Display backend for x1fold_mode.py set (default: auto).",
    )
    parser.add_argument(
        "--display-height",
        type=int,
        default=1240,
        help="Target height in pixels for half mode (default: 1240).",
    )
    parser.add_argument(
        "--drm-clip",
        default="",
        help="Path to drm_clip helper to pass to x1fold_mode.py (default: unset).",
    )
    parser.add_argument("--half-cmd", default="", help="Command to run when docked (string; default uses halfblank_switch).")
    parser.add_argument("--full-cmd", default="", help="Command to run when undocked (string; default uses halfblank_switch).")
    parser.add_argument(
        "--status-cmd",
        default="",
        help="Command to query current mode as JSON (string; default uses halfblank_switch status).",
    )
    args = parser.parse_args(argv)

    dmi = _dmi_info()
    if args.require_x1fold and not _looks_like_x1fold(dmi):
        _log("dmi_skip", require_x1fold=True, dmi=dmi)
        return 0

    def _default_tool_cmd(mode: str) -> list[str]:
        for candidate in (
            Path("/usr/local/bin/x1fold_mode.py"),
            Path("/usr/bin/x1fold_mode.py"),
            Path("/usr/bin/x1fold_mode"),
        ):
            if candidate.exists():
                tool = str(candidate)
                break
        else:
            tool = "x1fold_mode.py"

        cmd = [tool, "set", mode, "--digitizer", str(args.digitizer), "--display", str(args.display)]
        if mode == "half":
            cmd += ["--display-height", str(int(args.display_height))]
        if args.drm_clip:
            cmd += ["--drm-clip", str(args.drm_clip)]
        return cmd

    def _default_status_cmd() -> list[str]:
        for candidate in (
            Path("/usr/local/bin/x1fold_mode.py"),
            Path("/usr/bin/x1fold_mode.py"),
            Path("/usr/bin/x1fold_mode"),
        ):
            if candidate.exists():
                return [str(candidate), "status"]
        return ["x1fold_mode.py", "status"]

    cmds = Commands(
        half=_parse_cmd(args.half_cmd) if args.half_cmd else _default_tool_cmd("half"),
        full=_parse_cmd(args.full_cmd) if args.full_cmd else _default_tool_cmd("full"),
        status=_parse_cmd(args.status_cmd) if args.status_cmd else _default_status_cmd(),
    )

    last: DockState | None = None
    last_apply_ts = 0.0
    last_enforce_ts = 0.0
    enforce_every_s = float(args.enforce_every_s or 0.0)

    _log(
        "start",
        backend=args.backend,
        interval_s=args.interval_s,
        apply_initial=bool(args.apply_initial),
        enforce_every_s=enforce_every_s,
        dry_run=bool(args.dry_run),
        cmds={"half": cmds.half, "full": cmds.full, "status": cmds.status},
        state_file=str(args.state_file),
        dmi=dmi,
        hostname=os.uname().nodename if hasattr(os, "uname") else None,
    )

    while True:
        state = read_dock_state(
            backend=args.backend,
            acpi_call_path=args.acpi_call,
            gdst_path=args.gdst,
            cmmd_path=args.cmmd,
            ec_io=args.ec_io,
            ec_offset=args.ec_offset,
        )
        if state.docked not in (0, 1):
            # We can't act without a stable signal; keep polling.
            time.sleep(args.interval_s)
            continue

        if last is None:
            last = state
            if args.apply_initial:
                desired = "half" if state.docked else "full"
                # Write desired state immediately so UI helpers can react even if the
                # mode-switch command itself is slow (I2C timeouts, etc.).
                _write_json_atomic(
                    args.state_file,
                    {
                        "ts": utc_iso(),
                        "event": "apply_initial_pending",
                        "dmi": dmi,
                        "dock": state.__dict__,
                        "desired": desired,
                    },
                )
                rc = run_cmd(cmds.half if state.docked else cmds.full, dry_run=args.dry_run, timeout_s=args.cmd_timeout_s)
                _log("apply_initial", docked=state.docked, modeid=state.modeid, desired=desired, rc=rc)
                _write_json_atomic(
                    args.state_file,
                    {
                        "ts": utc_iso(),
                        "event": "apply_initial",
                        "dmi": dmi,
                        "dock": state.__dict__,
                        "desired": desired,
                        "apply_rc": rc,
                    },
                )
                last_apply_ts = time.monotonic()
            time.sleep(args.interval_s)
            continue

        now = time.monotonic()
        if state.docked == last.docked:
            if enforce_every_s > 0 and (now - last_enforce_ts) >= enforce_every_s:
                last_enforce_ts = now
                desired = "half" if state.docked else "full"
                status, err = run_status(cmds.status, dry_run=args.dry_run, timeout_s=args.cmd_timeout_s)
                current = _status_mode(status) if status else None
                if err:
                    _log("enforce_check_error", docked=state.docked, modeid=state.modeid, desired=desired, error=err)
                    _write_json_atomic(
                        args.state_file,
                        {
                            "ts": utc_iso(),
                            "event": "enforce_check_error",
                            "dmi": dmi,
                            "dock": state.__dict__,
                            "desired": desired,
                            "status_error": err,
                        },
                    )
                elif current != desired:
                    rc = run_cmd(
                        cmds.half if state.docked else cmds.full,
                        dry_run=args.dry_run,
                        timeout_s=args.cmd_timeout_s,
                    )
                    _log(
                        "enforce_apply",
                        docked=state.docked,
                        modeid=state.modeid,
                        desired=desired,
                        observed=current,
                        rc=rc,
                        since_last_apply_s=round(now - last_apply_ts, 3),
                    )
                    _write_json_atomic(
                        args.state_file,
                        {
                            "ts": utc_iso(),
                            "event": "enforce_apply",
                            "dmi": dmi,
                            "dock": state.__dict__,
                            "desired": desired,
                            "observed": current,
                            "apply_rc": rc,
                            "status": status,
                        },
                    )
                    last_apply_ts = now
            time.sleep(args.interval_s)
            continue

        desired = "half" if state.docked else "full"
        # Write desired state immediately so UI helpers can react even if the
        # mode-switch command itself is slow (I2C timeouts, etc.).
        _write_json_atomic(
            args.state_file,
            {
                "ts": utc_iso(),
                "event": "dock_change_pending",
                "dmi": dmi,
                "dock": state.__dict__,
                "from_docked": last.docked,
                "to_docked": state.docked,
                "desired": desired,
            },
        )
        rc = run_cmd(cmds.half if state.docked else cmds.full, dry_run=args.dry_run, timeout_s=args.cmd_timeout_s)
        _log(
            "dock_change",
            from_docked=last.docked,
            to_docked=state.docked,
            modeid=state.modeid,
            desired=desired,
            rc=rc,
        )
        _write_json_atomic(
            args.state_file,
            {
                "ts": utc_iso(),
                "event": "dock_change",
                "dmi": dmi,
                "dock": state.__dict__,
                "from_docked": last.docked,
                "to_docked": state.docked,
                "desired": desired,
                "apply_rc": rc,
            },
        )
        last_apply_ts = now
        last = state
        time.sleep(args.interval_s)


if __name__ == "__main__":
    raise SystemExit(main(list(__import__("sys").argv[1:])))
