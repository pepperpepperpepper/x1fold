#!/usr/bin/env python3
"""
User-session UI helper for X1 Fold "halfblank" behavior.

Repo source: x1fold/tools/x1fold_halfblank_ui.py

This tool reads a small state file written by x1fold_halfblankd.py (system daemon)
and applies the *display geometry* part in the active user session.

Today we implement X11 by creating a black "_NET_WM_WINDOW_TYPE_DOCK" window that
covers the bottom part of the screen and reserves that space via
_NET_WM_STRUT(_PARTIAL). This avoids needing DRM master while still producing a
real "bottom half goes black" visual effect.

Wayland integration is intentionally left for later (compositor-specific).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log(event: str, **extra: object) -> None:
    out = {"ts": utc_iso(), "event": event, **extra}
    print(json.dumps(out, sort_keys=True), flush=True)


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

def _x11_output_rotation(display: str, output: str) -> str | None:
    proc = _xrandr(display, ["--query"])
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if not line.startswith(output + " "):
            continue
        if " connected" not in line:
            continue
        # Example: "(normal left inverted right x axis y axis)"
        m = re.search(r"\((normal|left|right|inverted)\b", line)
        if not m:
            return None
        return m.group(1)
    return None


def _x11_set_rotation(display: str, output: str, rotation: str) -> tuple[bool, str]:
    if rotation not in {"normal", "left", "right", "inverted"}:
        return False, f"invalid rotation: {rotation}"
    proc = _xrandr(display, ["--output", output, "--rotate", rotation])
    if proc.returncode == 0:
        return True, ""
    msg = (proc.stderr or proc.stdout).strip() or f"xrandr failed (rc={proc.returncode})"
    return False, msg


def _sensorproxy_claim() -> None:
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
        )
    except OSError:
        return


def _sensorproxy_orientation() -> str | None:
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
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    m = re.search(r"\"([^\"]*)\"", proc.stdout)
    if not m:
        return None
    s = m.group(1).strip()
    return s or None


def _sensorproxy_to_xrandr_rotation(orientation: str) -> str | None:
    # iio-sensor-proxy -> XRandR rotation mapping:
    # - "left-up"  means the device left edge is up -> rotate output left
    # - "right-up" means the device right edge is up -> rotate output right
    # - "bottom-up" means device is upside down -> inverted
    mapping = {"normal": "normal", "left-up": "left", "right-up": "right", "bottom-up": "inverted"}
    return mapping.get(orientation)

def _xinput_list(display: str) -> list[tuple[int, str]]:
    env = dict(os.environ)
    env["DISPLAY"] = display
    try:
        proc = subprocess.run(["xinput", "list", "--short"], check=False, capture_output=True, text=True, env=env)
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    out: list[tuple[int, str]] = []
    for line in proc.stdout.splitlines():
        m = re.search(r"\bid=(\d+)\b", line)
        if not m:
            continue
        try:
            dev_id = int(m.group(1))
        except ValueError:
            continue
        name = line.split("\t")[0].strip()
        if name:
            out.append((dev_id, name))
    return out


def _xinput_map_to_output(display: str, dev_id: int, output: str) -> tuple[bool, str]:
    env = dict(os.environ)
    env["DISPLAY"] = display
    try:
        proc = subprocess.run(
            ["xinput", "map-to-output", str(int(dev_id)), str(output)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if proc.returncode == 0:
        return True, ""
    msg = (proc.stderr or proc.stdout).strip() or f"xinput failed (rc={proc.returncode})"
    return False, msg


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


def _x11_current_mode(display: str, output: str) -> tuple[int, int] | None:
    proc = _xrandr(display, ["--query"])
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if not line.startswith(output + " "):
            continue
        if " connected" not in line:
            continue
        # Example: "eDP-1 connected primary 2024x2560+0+0 ..."
        m = re.search(r"\bconnected\b.*?(\d+)x(\d+)\+", line)
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))
    return None


def _x11_set_fb(display: str, w: int, h: int) -> tuple[bool, str]:
    proc = _xrandr(display, ["--fb", f"{int(w)}x{int(h)}"])
    if proc.returncode == 0:
        return True, ""
    msg = (proc.stderr or proc.stdout).strip() or f"xrandr failed (rc={proc.returncode})"
    return False, msg


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


def _x11_del_monitor(display: str, *, name: str) -> tuple[bool, str]:
    proc = _xrandr(display, ["--delmonitor", name])
    if proc.returncode == 0:
        return True, ""
    msg = (proc.stderr or proc.stdout).strip()
    if "BadName" in msg or "failed request" in msg:
        return True, ""
    return False, msg or f"xrandr failed (rc={proc.returncode})"


def _x11_set_monitor_rect(
    display: str,
    *,
    name: str,
    output: str,
    x: int,
    y: int,
    w: int,
    h: int,
) -> tuple[bool, str]:
    _x11_del_monitor(display, name=name)
    geom = _x11_monitor_geometry(display, output)
    if not geom:
        return False, "failed to parse xrandr --listmonitors"
    w_px, w_mm, full_h, full_mm = geom
    full_w = w_px
    full_h_px = full_h

    if w <= 0 or h <= 0:
        return False, "rect width/height must be > 0"
    if x < 0 or y < 0:
        return False, "rect x/y must be >= 0"
    if x + w > full_w or y + h > full_h_px:
        return False, f"rect out of range (full={full_w}x{full_h_px})"

    target_w_mm = max(1, int(round(w_mm * (w / full_w))))
    target_h_mm = max(1, int(round(full_mm * (h / full_h_px))))
    geometry = f"{w}/{target_w_mm}x{h}/{target_h_mm}+{x}+{y}"
    proc = _xrandr(display, ["--setmonitor", name, geometry, output])
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip() or f"xrandr failed (rc={proc.returncode})"
        return False, msg
    return True, ""


class X11Blanker:
    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None
        self.key: tuple[str, str, int, str] | None = None  # (helper, display, active_size, side)

    def ensure(self, *, helper: str, display: str, active_size: int, side: str, name: str) -> tuple[bool, str]:
        key = (helper, display, int(active_size), str(side))
        if self.proc and self.proc.poll() is None and self.key == key:
            return True, ""
        self.stop()
        self.key = key
        try:
            self.proc = subprocess.Popen(
                [
                    helper,
                    "--display",
                    display,
                    "--side",
                    str(side),
                    "--active-size",
                    str(int(active_size)),
                    "--name",
                    name,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            return False, f"{type(exc).__name__}: {exc}"

        # Give it a moment to fail fast if DISPLAY/auth is wrong.
        time.sleep(0.2)
        if self.proc.poll() is None:
            return True, ""
        err = (self.proc.stderr.read() if self.proc.stderr else "").strip()
        return False, err or f"blank helper exited rc={self.proc.returncode}"

    def stop(self) -> None:
        if not self.proc:
            return
        if self.proc.poll() is not None:
            self.proc = None
            self.key = None
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=2.0)
        self.proc = None
        self.key = None


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


def _apply_x11(
    desired: str,
    *,
    blanker: X11Blanker,
    display: str,
    output: str,
    helper: str,
    active_size: int,
    name: str,
    monitor_name: str,
    setmonitor: bool,
) -> tuple[bool, str]:
    mode = _x11_current_mode(display, output)
    if mode:
        w, h = mode
        ok, err = _x11_set_fb(display, w, h)
        if not ok:
            _log("x11_fb_set_failed", display=display, output=output, error=err)

    if desired == "half":
        if not mode:
            return False, "failed to read current mode"
        w, h = mode
        # Halfblank is defined as "top region active, bottom region unused".
        if int(active_size) <= 0 or int(active_size) >= int(h):
            return False, "active_size must be in 1..(screen_height-1)"
        ax, ay, aw, ah = (0, 0, int(w), int(active_size))
        if setmonitor:
            ok, err = _x11_set_monitor_rect(display, name=monitor_name, output=output, x=ax, y=ay, w=aw, h=ah)
            if not ok:
                _log("x11_setmonitor_failed", display=display, output=output, monitor=monitor_name, error=err)
        return blanker.ensure(helper=helper, display=display, active_size=active_size, side="bottom", name=name)
    if setmonitor:
        ok, err = _x11_del_monitor(display, name=monitor_name)
        if not ok:
            _log("x11_delmonitor_failed", display=display, output=output, monitor=monitor_name, error=err)
    blanker.stop()
    return True, ""


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Apply X1 Fold halfblank UI geometry from state.json (user session).")
    p.add_argument(
        "--state-file",
        type=Path,
        default=Path("/run/x1fold-halfblank/state.json"),
        help="Path to x1fold_halfblankd state file (default: /run/x1fold-halfblank/state.json).",
    )
    p.add_argument("--interval-s", type=float, default=0.2, help="Poll interval for state changes (default: 0.2).")
    p.add_argument("--x11-output", default="", help="XRandR output override (default: auto pick eDP-*).")
    p.add_argument(
        "--x11-auto-rotate",
        action="store_true",
        help="Auto-rotate XRandR output based on iio-sensor-proxy (default: off).",
    )
    p.add_argument(
        "--x11-auto-rotate-interval-s",
        type=float,
        default=0.5,
        help="Polling interval for iio-sensor-proxy orientation (default: 0.5).",
    )
    p.add_argument(
        "--x11-force-normal-when-half",
        action="store_true",
        help="Force XRandR rotation to 'normal' while halfblank is active (default: off).",
    )
    p.add_argument(
        "--x11-xinput-regex",
        default=r"WACF2200|Wacom|Touchscreen",
        help="Regex for xinput devices to map after rotation (default: WACF2200|Wacom|Touchscreen).",
    )
    p.add_argument(
        "--no-x11-xinput-map",
        dest="x11_xinput_map",
        action="store_false",
        help="Disable xinput map-to-output after rotation.",
    )
    p.set_defaults(x11_xinput_map=True)
    p.add_argument(
        "--x11-monitor-name",
        default="X1FOLD_TOP",
        help="XRandR monitor object name to advertise top-only geometry (default: X1FOLD_TOP).",
    )
    p.add_argument(
        "--active-size",
        "--top-height",
        dest="active_size",
        type=int,
        default=1240,
        help="Active size in pixels for half mode (default: 1240). For sideways/rotated use, this becomes active width.",
    )
    p.add_argument(
        "--x11-blank-helper",
        default="x1fold_x11_blank",
        help="Helper to create X11 black strut window (default: x1fold_x11_blank in $PATH).",
    )
    p.add_argument("--x11-blank-name", default="X1FOLD_HALFBLANK", help="X11 blank window name (default: X1FOLD_HALFBLANK).")
    p.add_argument("--no-x11-setmonitor", action="store_true", help="Disable xrandr --setmonitor/--delmonitor calls.")
    p.add_argument("--once", action="store_true", help="Apply once and exit (useful with systemd .path units).")
    args = p.parse_args(argv)

    _log(
        "start",
        state_file=str(args.state_file),
        interval_s=args.interval_s,
        once=bool(args.once),
        x11_auto_rotate=bool(args.x11_auto_rotate),
    )

    last_key: tuple[str | None, float | None, str | None] = (None, None, None)  # (desired, mtime, rotation_applied)
    blanker = X11Blanker()
    last_sensor_check = 0.0
    last_sensor_orientation: str | None = None
    if args.x11_auto_rotate:
        _sensorproxy_claim()

    while True:
        st = _read_state(args.state_file)
        desired = _desired_mode(st) if st else "full"
        docked: int | None = None
        if st and isinstance(st.get("dock"), dict):
            d = st.get("dock") or {}
            if isinstance(d.get("docked"), int):
                docked = int(d.get("docked"))

        try:
            mtime = args.state_file.stat().st_mtime
        except OSError:
            mtime = None

        blanker_running = bool(blanker.proc and blanker.proc.poll() is None)

        if desired not in {"half", "full"}:
            _log("no_desired_mode", desired=desired)
            if args.once:
                return 0
            time.sleep(args.interval_s)
            continue

        x11_display = _detect_x11_display()
        if not x11_display:
            _log("no_x11_display", desired=desired)
            if args.once:
                return 0
            time.sleep(args.interval_s)
            continue

        output = _x11_pick_output(x11_display, args.x11_output or None)
        if not output:
            _log("x11_no_output", desired=desired, display=x11_display)
            if args.once:
                return 1
            time.sleep(args.interval_s)
            continue

        rotation = _x11_output_rotation(x11_display, output) or (last_key[2] or "normal")
        now = time.monotonic()
        target_rot: str | None = None
        if desired == "half" and args.x11_force_normal_when_half:
            target_rot = "normal"
        elif args.x11_auto_rotate and desired == "full" and (docked in (0, None)):
            if (now - last_sensor_check) >= float(args.x11_auto_rotate_interval_s):
                last_sensor_check = now
                ori = _sensorproxy_orientation()
                if ori:
                    last_sensor_orientation = ori
                target_rot = _sensorproxy_to_xrandr_rotation(ori) if ori else None
        rotated = False
        if target_rot and target_rot != rotation:
            ok, err = _x11_set_rotation(x11_display, output, target_rot)
            if ok:
                _log(
                    "x11_rotated",
                    display=x11_display,
                    output=output,
                    from_rotation=rotation,
                    rotation=target_rot,
                    sensor_orientation=last_sensor_orientation,
                    docked=docked,
                    desired=desired,
                )
                rotation = target_rot
                rotated = True
            else:
                _log(
                    "x11_rotate_failed",
                    display=x11_display,
                    output=output,
                    from_rotation=rotation,
                    desired_rotation=target_rot,
                    sensor_orientation=last_sensor_orientation,
                    docked=docked,
                    desired=desired,
                    error=err,
                )

        # After rotation, map the touchscreen/pen devices to the output so the
        # digitizer coordinates track the new orientation.
        if rotated and args.x11_xinput_map:
            try:
                rx = re.compile(str(args.x11_xinput_regex))
            except re.error as exc:
                _log("x11_xinput_regex_error", error=str(exc), regex=str(args.x11_xinput_regex))
                rx = None
            devices = _xinput_list(x11_display)
            matched = 0
            mapped = 0
            for dev_id, dev_name in devices:
                if rx and not rx.search(dev_name):
                    continue
                matched += 1
                ok, err = _xinput_map_to_output(x11_display, dev_id, output)
                if ok:
                    mapped += 1
                else:
                    _log("x11_xinput_map_failed", display=x11_display, dev_id=dev_id, dev_name=dev_name, error=err)
            if matched:
                _log(
                    "x11_xinput_mapped",
                    display=x11_display,
                    output=output,
                    matched=matched,
                    mapped=mapped,
                    regex=str(args.x11_xinput_regex),
                )

        key = (desired, mtime, rotation)
        same_key = key == last_key
        if same_key and desired == "half" and not blanker_running:
            same_key = False
        if same_key and desired == "full" and blanker_running:
            same_key = False
        if same_key:
            if args.once:
                return 0
            time.sleep(args.interval_s)
            continue
        last_key = key

        ok, err = _apply_x11(
            desired,
            blanker=blanker,
            display=x11_display,
            output=output,
            helper=str(args.x11_blank_helper),
            active_size=int(args.active_size),
            name=str(args.x11_blank_name),
            monitor_name=str(args.x11_monitor_name),
            setmonitor=not bool(args.no_x11_setmonitor),
        )
        if ok:
            _log(
                "applied",
                desired=desired,
                display=x11_display,
                output=output,
                rotation=rotation,
                docked=docked,
                sensor_orientation=last_sensor_orientation,
                blank_helper=str(args.x11_blank_helper),
            )
        else:
            _log(
                "apply_failed",
                desired=desired,
                display=x11_display,
                output=output,
                rotation=rotation,
                docked=docked,
                sensor_orientation=last_sensor_orientation,
                error=err,
            )
            if args.once:
                return 1

        if args.once:
            return 0
        time.sleep(args.interval_s)


if __name__ == "__main__":
    raise SystemExit(main(list(__import__("sys").argv[1:])))
