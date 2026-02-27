#!/usr/bin/env python3
"""
TTY/fbcon auto-rotation helper for X1 Fold.

Repo source: x1fold/tools/x1fold_tty_rotate.py

This is the "bare console" counterpart to x1fold_halfblank_ui.py's auto-rotate:
  - reads /run/x1fold-halfblank/state.json (written by x1fold_halfblankd.py)
  - reads orientation from iio-sensor-proxy over the *system* D-Bus
  - writes rotation to /sys/class/graphics/fbcon/rotate

Policy:
  - desired == "half" (keyboard docked): force rotate=0 (normal), by default.
  - desired == "full": map orientation -> fbcon rotate and apply on change.

Notes:
  - On the X1 Fold, the fbcon 90/270 direction is typically the reverse of what
    you expect if you map directly from iio-sensor-proxy. Defaults reflect the
    calibrated values; override with --left-up-rotate/--right-up-rotate if needed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log(event: str, **extra: object) -> None:
    out = {"ts": utc_iso(), "event": event, **extra}
    print(json.dumps(out, sort_keys=True), flush=True)


def _read_state(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        _log("state_parse_error", path=str(path), error=f"JSONDecodeError: {exc}")
        return None
    except OSError as exc:
        _log("state_read_error", path=str(path), error=f"{type(exc).__name__}: {exc}")
        return None


def _desired_mode(state: dict[str, Any]) -> str | None:
    desired = state.get("desired")
    if isinstance(desired, str) and desired in {"half", "full"}:
        return desired
    return None


def _sensorproxy_claim(*, timeout_s: float = 1.0) -> bool:
    try:
        subprocess.run(
            [
                "busctl",
                "--system",
                "call",
                "net.hadess.SensorProxy",
                "/net/hadess/SensorProxy",
                "net.hadess.SensorProxy",
                "ClaimAccelerometer",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=float(timeout_s),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def _sensorproxy_orientation(*, timeout_s: float = 1.0) -> str | None:
    """
    Read iio-sensor-proxy's AccelerometerOrientation, e.g. "normal", "left-up".

    Returns None on failure or if no orientation is available.
    """

    try:
        proc = subprocess.run(
            [
                "busctl",
                "--system",
                "get-property",
                "net.hadess.SensorProxy",
                "/net/hadess/SensorProxy",
                "net.hadess.SensorProxy",
                "AccelerometerOrientation",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=float(timeout_s),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    m = re.search(r"\"([^\"]*)\"", proc.stdout)
    if not m:
        return None
    s = m.group(1).strip()
    return s or None


_MONITOR_SENSOR_ORI_RE = re.compile(r"\b(normal|left-up|right-up|bottom-up)\b", re.IGNORECASE)


def _parse_monitor_sensor_orientation(line: str) -> str | None:
    s = (line or "").strip()
    if not s:
        return None
    m = _MONITOR_SENSOR_ORI_RE.search(s)
    if not m:
        return None
    return str(m.group(1)).strip().lower() or None


class SensorClaim:
    """
    Keep iio-sensor-proxy's accelerometer "claimed" while auto-rotate is needed.

    iio-sensor-proxy may power down sensors when no clients claim them. A one-shot
    ClaimAccelerometer call is typically not enough because the claim is tied to
    the D-Bus connection lifetime.
    """

    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None
        self.available: bool | None = None
        self.last_orientation: str | None = None

    def _have_monitor_sensor(self) -> bool:
        if self.available is not None:
            return bool(self.available)
        self.available = bool(shutil.which("monitor-sensor"))
        return bool(self.available)

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def orientation(self) -> str | None:
        return self.last_orientation

    def _reader(self, proc: subprocess.Popen[str]) -> None:
        if not proc.stdout:
            return
        try:
            for line in proc.stdout:
                ori = _parse_monitor_sensor_orientation(line)
                if ori:
                    self.last_orientation = ori
        except Exception:
            return

    def start(self) -> bool:
        if self.running():
            return False
        if not self._have_monitor_sensor():
            return False
        self.last_orientation = None
        cmd = ["monitor-sensor", "--accel"]
        if shutil.which("stdbuf"):
            cmd = ["stdbuf", "-oL", "-eL", *cmd]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
            )
        except OSError as exc:
            _log("sensor_claim_start_failed", error=f"{type(exc).__name__}: {exc}")
            self.proc = None
            self.available = False
            return False
        self.thread = threading.Thread(target=self._reader, args=(self.proc,), daemon=True)
        self.thread.start()
        return True

    def stop(self) -> bool:
        if not self.proc:
            return False
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=1.0)
        finally:
            self.proc = None
            self.thread = None
            self.last_orientation = None
        return True


def _read_fbcon_rotate(path: Path) -> int | None:
    try:
        s = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _write_fbcon_rotate(path: Path, rotate: int) -> tuple[bool, str]:
    if rotate not in (0, 1, 2, 3):
        return False, f"rotate must be 0..3 (got: {rotate})"
    try:
        path.write_text(str(int(rotate)) + "\n", encoding="utf-8")
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _orientation_to_fbcon_rotate(
    orientation: str,
    *,
    left_up: int,
    right_up: int,
) -> int | None:
    """
    Map iio-sensor-proxy orientation strings to fbcon rotate values.

    Note: on some kernels/devices, the 90/270 mapping may appear swapped. Use
    --left-up-rotate/--right-up-rotate to calibrate.
    """

    mapping = {
        "normal": 0,
        "bottom-up": 2,
        "left-up": int(left_up),
        "right-up": int(right_up),
    }
    return mapping.get(orientation)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Auto-rotate Linux VT/TTY using fbcon based on dock state + sensors.")
    p.add_argument(
        "--state-file",
        type=Path,
        default=Path("/run/x1fold-halfblank/state.json"),
        help="Path to x1fold_halfblankd state file (default: /run/x1fold-halfblank/state.json).",
    )
    p.add_argument(
        "--rotate-path",
        type=Path,
        default=Path(os.environ.get("X1FOLD_FBCON_ROTATE_PATH", "/sys/class/graphics/fbcon/rotate")),
        help="fbcon rotate sysfs path (default: /sys/class/graphics/fbcon/rotate).",
    )
    p.add_argument("--interval-s", type=float, default=1.5, help="Polling interval (default: 1.5).")
    p.add_argument("--stable-s", type=float, default=0.8, help="Require sensor orientation stable for this long (default: 0.8).")
    p.add_argument("--min-apply-s", type=float, default=1.0, help="Minimum time between applying rotations (default: 1.0).")
    p.add_argument(
        "--no-force-normal-when-half",
        dest="force_normal_when_half",
        action="store_false",
        help="Do not force rotate=0 while desired==half.",
    )
    p.set_defaults(force_normal_when_half=True)
    p.add_argument(
        "--left-up-rotate",
        type=int,
        default=3,
        choices=(1, 3),
        help="fbcon rotate value to use for sensor 'left-up' (default: 3).",
    )
    p.add_argument(
        "--right-up-rotate",
        type=int,
        default=1,
        choices=(1, 3),
        help="fbcon rotate value to use for sensor 'right-up' (default: 1).",
    )
    p.add_argument("--once", action="store_true", help="Evaluate/apply once and exit.")
    args = p.parse_args(argv)

    if args.left_up_rotate == args.right_up_rotate:
        raise SystemExit("--left-up-rotate and --right-up-rotate must differ (use 1 and 3)")

    _log(
        "start",
        state_file=str(args.state_file),
        rotate_path=str(args.rotate_path),
        interval_s=float(args.interval_s),
        stable_s=float(args.stable_s),
        min_apply_s=float(args.min_apply_s),
        force_normal_when_half=bool(args.force_normal_when_half),
        left_up_rotate=int(args.left_up_rotate),
        right_up_rotate=int(args.right_up_rotate),
        once=bool(args.once),
        euid=int(os.geteuid()) if hasattr(os, "geteuid") else None,
    )

    if not args.rotate_path.exists():
        _log("rotate_path_missing", path=str(args.rotate_path))
        return 1

    sensor_claim = SensorClaim()
    sensor_claim_enabled = False

    last_sensor_orientation: str | None = None
    last_sensor_orientation_change = 0.0
    last_apply_ts = 0.0

    try:
        while True:
            st = _read_state(args.state_file)
            desired = _desired_mode(st) if st else None
            desired = desired or "full"

            docked: int | None = None
            if st and isinstance(st.get("dock"), dict):
                d = st.get("dock") or {}
                if isinstance(d.get("docked"), int):
                    docked = int(d.get("docked"))

            now = time.monotonic()
            target: int | None = None
            reason: str | None = None
            sensor_orientation: str | None = None

            want_sensor = desired == "full"
            if want_sensor:
                if not sensor_claim_enabled:
                    sensor_claim_enabled = True
                    started = sensor_claim.start()
                    _log("sensor_claim_enabled", started=bool(started), running=bool(sensor_claim.running()))
                elif not sensor_claim.running():
                    started = sensor_claim.start()
                    if started:
                        _log("sensor_claim_restarted", running=bool(sensor_claim.running()))
            elif sensor_claim_enabled:
                sensor_claim_enabled = False
                stopped = sensor_claim.stop()
                _log("sensor_claim_disabled", stopped=bool(stopped))

            if desired == "half" and args.force_normal_when_half:
                target = 0
                reason = "force_normal_when_half"
            elif desired == "full":
                if sensor_claim.running():
                    sensor_orientation = sensor_claim.orientation()
                else:
                    sensor_orientation = _sensorproxy_orientation(timeout_s=0.5)
                if sensor_orientation:
                    if sensor_orientation != last_sensor_orientation:
                        last_sensor_orientation = sensor_orientation
                        stable_s = float(args.stable_s or 0.0)
                        if last_sensor_orientation_change == 0.0 and stable_s > 0:
                            last_sensor_orientation_change = now - stable_s
                        else:
                            last_sensor_orientation_change = now
                    target = _orientation_to_fbcon_rotate(
                        sensor_orientation,
                        left_up=int(args.left_up_rotate),
                        right_up=int(args.right_up_rotate),
                    )
                    reason = "sensor"

            cur = _read_fbcon_rotate(args.rotate_path)
            if cur is None:
                _log("rotate_read_error", path=str(args.rotate_path))
                if args.once:
                    return 1
                time.sleep(float(args.interval_s))
                continue

            if target is not None and target != cur:
                if reason == "sensor":
                    min_apply_s = float(args.min_apply_s or 0.0)
                    if min_apply_s > 0 and (now - last_apply_ts) < min_apply_s:
                        _log(
                            "rotate_rate_limited",
                            from_rotate=cur,
                            desired_rotate=target,
                            desired=desired,
                            docked=docked,
                            sensor_orientation=last_sensor_orientation,
                            since_last_apply_s=round(now - last_apply_ts, 3),
                            min_apply_s=min_apply_s,
                        )
                    else:
                        stable_s = float(args.stable_s or 0.0)
                        if stable_s > 0 and (now - last_sensor_orientation_change) < stable_s:
                            _log(
                                "rotate_debounced",
                                from_rotate=cur,
                                desired_rotate=target,
                                desired=desired,
                                docked=docked,
                                sensor_orientation=last_sensor_orientation,
                                since_change_s=round(now - last_sensor_orientation_change, 3),
                                stable_s=stable_s,
                            )
                        else:
                            start = time.monotonic()
                            ok, err = _write_fbcon_rotate(args.rotate_path, target)
                            elapsed_s = round(time.monotonic() - start, 3)
                            if ok:
                                _log(
                                    "rotated",
                                    from_rotate=cur,
                                    rotate=target,
                                    desired=desired,
                                    docked=docked,
                                    sensor_orientation=last_sensor_orientation,
                                    elapsed_s=elapsed_s,
                                    reason=reason,
                                )
                                last_apply_ts = time.monotonic()
                            else:
                                _log(
                                    "rotate_failed",
                                    from_rotate=cur,
                                    desired_rotate=target,
                                    desired=desired,
                                    docked=docked,
                                    sensor_orientation=last_sensor_orientation,
                                    elapsed_s=elapsed_s,
                                    error=err,
                                    reason=reason,
                                )
                else:
                    start = time.monotonic()
                    ok, err = _write_fbcon_rotate(args.rotate_path, target)
                    elapsed_s = round(time.monotonic() - start, 3)
                    if ok:
                        _log(
                            "rotated",
                            from_rotate=cur,
                            rotate=target,
                            desired=desired,
                            docked=docked,
                            sensor_orientation=sensor_orientation,
                            elapsed_s=elapsed_s,
                            reason=reason,
                        )
                        last_apply_ts = time.monotonic()
                    else:
                        _log(
                            "rotate_failed",
                            from_rotate=cur,
                            desired_rotate=target,
                            desired=desired,
                            docked=docked,
                            sensor_orientation=sensor_orientation,
                            elapsed_s=elapsed_s,
                            error=err,
                            reason=reason,
                        )

            if args.once:
                return 0
            time.sleep(float(args.interval_s))
    finally:
        sensor_claim.stop()


if __name__ == "__main__":
    raise SystemExit(main(list(__import__("sys").argv[1:])))
