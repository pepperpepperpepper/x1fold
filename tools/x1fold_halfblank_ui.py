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


class X11Blanker:
    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None

    def ensure(self, *, helper: str, display: str, top_height: int, name: str) -> tuple[bool, str]:
        if self.proc and self.proc.poll() is None:
            return True, ""
        try:
            self.proc = subprocess.Popen(
                [helper, "--display", display, "--top-height", str(int(top_height)), "--name", name],
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
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=2.0)
        self.proc = None


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
    top_height: int,
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
        if setmonitor:
            ok, err = _x11_set_monitor(display, name=monitor_name, output=output, target_h=top_height)
            if not ok:
                _log("x11_setmonitor_failed", display=display, output=output, monitor=monitor_name, error=err)
        return blanker.ensure(helper=helper, display=display, top_height=top_height, name=name)
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
        "--x11-monitor-name",
        default="X1FOLD_TOP",
        help="XRandR monitor object name to advertise top-only geometry (default: X1FOLD_TOP).",
    )
    p.add_argument("--top-height", type=int, default=1240, help="Top (active) height for half mode (default: 1240).")
    p.add_argument(
        "--x11-blank-helper",
        default="x1fold_x11_blank",
        help="Helper to create X11 black strut window (default: x1fold_x11_blank in $PATH).",
    )
    p.add_argument("--x11-blank-name", default="X1FOLD_HALFBLANK", help="X11 blank window name (default: X1FOLD_HALFBLANK).")
    p.add_argument("--no-x11-setmonitor", action="store_true", help="Disable xrandr --setmonitor/--delmonitor calls.")
    p.add_argument("--once", action="store_true", help="Apply once and exit (useful with systemd .path units).")
    args = p.parse_args(argv)

    _log("start", state_file=str(args.state_file), interval_s=args.interval_s, once=bool(args.once))

    last_key: tuple[str | None, float | None] = (None, None)  # (desired, mtime)
    blanker = X11Blanker()

    while True:
        st = _read_state(args.state_file)
        if not st:
            if args.once:
                return 0
            time.sleep(args.interval_s)
            continue

        desired = _desired_mode(st)
        try:
            mtime = args.state_file.stat().st_mtime
        except OSError:
            mtime = None

        same_key = (desired, mtime) == last_key
        blanker_running = bool(blanker.proc and blanker.proc.poll() is None)
        if same_key and desired == "half" and not blanker_running:
            # State didn't change, but our helper died (or never started). Re-apply.
            same_key = False
        if same_key and desired == "full" and blanker_running:
            # State didn't change, but helper is still running; clean up.
            same_key = False

        if same_key:
            if args.once:
                return 0
            time.sleep(args.interval_s)
            continue

        last_key = (desired, mtime)

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

        ok, err = _apply_x11(
            desired,
            blanker=blanker,
            display=x11_display,
            output=output,
            helper=str(args.x11_blank_helper),
            top_height=int(args.top_height),
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
                blank_helper=str(args.x11_blank_helper),
            )
        else:
            _log("apply_failed", desired=desired, display=x11_display, output=output, error=err)
            if args.once:
                return 1

        if args.once:
            return 0
        time.sleep(args.interval_s)


if __name__ == "__main__":
    raise SystemExit(main(list(__import__("sys").argv[1:])))
