#!/usr/bin/env python3
"""
Console/TTY helper for X1 Fold "halfblank" behavior.

Repo source: x1fold/tools/x1fold_tty.py

This is the "bare terminal" counterpart to the X11/Wayland UI helper:
  - clips the primary DRM plane via drm_clip (so the bottom becomes invisible)
  - resizes the active Linux virtual terminal (winsize + scroll region) so text
    output stays within the visible top region
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fcntl
import termios


KDGETMODE = 0x4B3B
KD_TEXT = 0x00
KD_GRAPHICS = 0x01


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log(event: str, **extra: object) -> None:
    out = {"ts": utc_iso(), "event": event, **extra}
    print(json.dumps(out, sort_keys=True), flush=True)


def _safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _safe_write_text(path: Path, data: str) -> bool:
    try:
        path.write_text(data, encoding="utf-8")
        return True
    except OSError:
        return False


def _safe_read_int(path: Path) -> int | None:
    s = _safe_read_text(path)
    if s is None:
        return None
    try:
        return int(s.strip(), 10)
    except ValueError:
        return None


def _force_fbcon_rotate_zero(*, best_effort: bool) -> None:
    """
    The kernel console can end up rotated (e.g. upside-down) via fbcon rotation.
    We want a stable, always-upright TTY on the Fold.
    """
    fbcon_rotate = Path("/sys/class/graphics/fbcon/rotate")
    fbcon_rotate_all = Path("/sys/class/graphics/fbcon/rotate_all")
    fb0_rotate = Path("/sys/class/graphics/fb0/rotate")

    before_fbcon = _safe_read_int(fbcon_rotate)
    before_fb0 = _safe_read_int(fb0_rotate)

    # Don't fight intentional 90/270 rotations. The "sometimes upside-down"
    # failure mode we want to correct is typically 180° (value 2).
    #
    # If you want to rotate the console intentionally, write 1 or 3; this
    # helper should not immediately undo that.
    if before_fbcon != 2 and before_fb0 != 2:
        return

    ok_any = False
    ok_any |= _safe_write_text(fbcon_rotate_all, "0\n")
    ok_any |= _safe_write_text(fbcon_rotate, "0\n")
    ok_any |= _safe_write_text(fb0_rotate, "0\n")

    after_fbcon = _safe_read_int(fbcon_rotate)
    after_fb0 = _safe_read_int(fb0_rotate)

    if ok_any:
        _log("tty_fbcon_rotate_forced", fbcon_before=before_fbcon, fb0_before=before_fb0, fbcon_after=after_fbcon, fb0_after=after_fb0)
    elif not best_effort:
        raise SystemExit("failed to reset fbcon rotate to 0")


def _default_state_file() -> Path:
    if os.geteuid() == 0:
        return Path("/run/x1fold-halfblank/tty_state.json")
    xdg = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if xdg:
        return Path(xdg) / "x1fold-halfblank" / "tty_state.json"
    return Path("/tmp/x1fold-halfblank-tty_state.json")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}
    except json.JSONDecodeError:
        return {}


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _active_tty_name() -> str | None:
    active = _safe_read_text(Path("/sys/class/tty/tty0/active"))
    if not active:
        return None
    active = active.strip()
    if active.startswith("tty") and active[3:].isdigit():
        return active
    return None


def _resolve_tty(arg: str | None) -> Path:
    if arg:
        v = arg.strip()
        if v == "active":
            name = _active_tty_name()
            if name:
                return Path("/dev") / name
            return Path("/dev/tty")
        if v.startswith("/dev/"):
            return Path(v)
        if v.startswith("tty") and v[3:].isdigit():
            return Path("/dev") / v
        raise SystemExit(f"--tty must be like tty3, /dev/tty3, or 'active' (got: {arg})")

    name = _active_tty_name()
    if name:
        return Path("/dev") / name
    return Path("/dev/tty")


def _kd_mode(fd: int) -> int | None:
    buf = bytearray(struct.pack("i", 0))
    try:
        fcntl.ioctl(fd, KDGETMODE, buf, True)
        return int(struct.unpack("i", buf)[0])
    except OSError:
        return None


def _get_winsize(fd: int) -> tuple[int, int]:
    buf = bytearray(8)
    fcntl.ioctl(fd, termios.TIOCGWINSZ, buf, True)
    rows, cols, _, _ = struct.unpack("HHHH", buf)
    return int(rows), int(cols)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    if rows <= 0 or cols <= 0:
        raise ValueError("rows/cols must be positive")
    buf = struct.pack("HHHH", int(rows), int(cols), 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, buf)


def _write_tty(fd: int, s: str) -> None:
    os.write(fd, s.encode("utf-8", errors="ignore"))


def _pick_drm_clip(path_arg: str) -> str:
    if path_arg:
        return path_arg
    found = shutil.which("drm_clip")
    if found:
        return found
    return "drm_clip"


@dataclass(frozen=True)
class DrmStatus:
    mode_w: int
    mode_h: int
    clip_h: int


def _drm_status(drm_clip: str, *, card: str, connector: str) -> DrmStatus:
    cmd = [drm_clip]
    if card:
        cmd += ["--card", card]
    if connector:
        cmd += ["--connector", connector]
    cmd += ["status"]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip() or f"rc={proc.returncode}"
        raise RuntimeError(f"drm_clip status failed: {msg}")
    data = json.loads(proc.stdout)
    mode = str((data.get("crtc") or {}).get("mode") or "")
    if "x" not in mode:
        raise RuntimeError(f"unexpected drm_clip mode: {mode!r}")
    w_s, h_s = mode.split("x", 1)
    clip_h = int(((data.get("plane_rect") or {}).get("crtc") or {}).get("h") or 0)
    return DrmStatus(mode_w=int(w_s), mode_h=int(h_s), clip_h=clip_h)


def _run_drm_clip(
    drm_clip: str,
    *,
    card: str,
    connector: str,
    height: int,
    mode: str,
    best_effort: bool,
) -> tuple[int, str]:
    cmd = [drm_clip]
    if card:
        cmd += ["--card", card]
    if connector:
        cmd += ["--connector", connector]
    if mode == "half":
        cmd += ["--height", str(int(height)), "half"]
    else:
        cmd += ["full"]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode == 0:
        return 0, ""
    msg = (proc.stderr or proc.stdout).strip() or f"rc={proc.returncode}"
    if best_effort:
        _log("drm_clip_skipped", cmd=cmd, error=msg)
        return 0, msg
    return int(proc.returncode), msg


def _ensure_state_entry(state: dict[str, Any], tty_key: str) -> dict[str, Any]:
    ttys = state.setdefault("ttys", {})
    if not isinstance(ttys, dict):
        state["ttys"] = {}
        ttys = state["ttys"]
    entry = ttys.setdefault(tty_key, {})
    if not isinstance(entry, dict):
        ttys[tty_key] = {}
        entry = ttys[tty_key]
    return entry


def cmd_status(args: argparse.Namespace) -> int:
    tty_path = _resolve_tty(args.tty)
    out: dict[str, Any] = {"ts": utc_iso(), "tty": str(tty_path), "active_tty": _active_tty_name()}
    try:
        fd = os.open(str(tty_path), os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        out["tty_error"] = f"[{exc.errno}] {exc.strerror}"
        print(json.dumps(out, indent=2, sort_keys=True))
        return 1
    try:
        kd = _kd_mode(fd)
        out["kd_mode"] = {KD_TEXT: "text", KD_GRAPHICS: "graphics"}.get(kd, str(kd))
        rows, cols = _get_winsize(fd)
        out["winsize"] = {"rows": rows, "cols": cols}
    finally:
        os.close(fd)

    drm_clip = _pick_drm_clip(args.drm_clip)
    try:
        ds = _drm_status(drm_clip, card=args.card, connector=args.connector)
        out["drm"] = {"mode": f"{ds.mode_w}x{ds.mode_h}", "clip_h": ds.clip_h}
    except Exception as exc:
        out["drm_error"] = f"{type(exc).__name__}: {exc}"

    out["fbcon"] = {
        "rotate": _safe_read_int(Path("/sys/class/graphics/fbcon/rotate")),
        "fb0_rotate": _safe_read_int(Path("/sys/class/graphics/fb0/rotate")),
    }

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    target = str(args.mode).strip().lower()
    if target not in ("half", "full"):
        raise SystemExit("mode must be half|full")

    tty_path = _resolve_tty(args.tty)
    tty_key = tty_path.name
    state_path: Path = args.state_file
    state = _read_json(state_path)

    drm_clip = _pick_drm_clip(args.drm_clip)

    # Capture current tty geometry/mode before we touch anything.
    try:
        fd = os.open(str(tty_path), os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        if args.best_effort:
            fd = -1
        else:
            raise SystemExit(f"failed to open {tty_path}: [{exc.errno}] {exc.strerror}")

    kd = None
    rows = cols = 0
    try:
        if fd >= 0:
            kd = _kd_mode(fd)
            rows, cols = _get_winsize(fd)
    finally:
        if fd >= 0:
            os.close(fd)

    # This helper is intended for Linux text consoles only. In a graphical VT
    # (KD_GRAPHICS), do nothing unless explicitly requested otherwise.
    if kd != KD_TEXT or rows <= 0 or cols <= 0:
        if args.best_effort:
            return 0
        raise SystemExit(f"{tty_path} is not a text console (kd_mode={kd}, rows={rows}, cols={cols})")

    _force_fbcon_rotate_zero(best_effort=bool(args.best_effort))

    entry = _ensure_state_entry(state, tty_key)
    if isinstance(rows, int) and rows > 0 and isinstance(cols, int) and cols > 0:
        entry.setdefault("last_rows", rows)
        entry.setdefault("last_cols", cols)
        if target == "half":
            entry.setdefault("full_rows", rows)
            entry.setdefault("full_cols", cols)

    # Snapshot DRM status before switching to full so we can infer the old clip height if needed.
    before: DrmStatus | None = None
    try:
        before = _drm_status(drm_clip, card=args.card, connector=args.connector)
    except Exception as exc:
        if not args.best_effort:
            raise SystemExit(str(exc))
        _log("drm_status_skipped", error=f"{type(exc).__name__}: {exc}")

    if target == "half":
        rc, err = _run_drm_clip(
            drm_clip,
            card=args.card,
            connector=args.connector,
            height=int(args.height),
            mode="half",
            best_effort=bool(args.best_effort),
        )
        if rc != 0:
            raise SystemExit(err or f"drm_clip failed (rc={rc})")
    else:
        rc, err = _run_drm_clip(
            drm_clip,
            card=args.card,
            connector=args.connector,
            height=int(args.height),
            mode="full",
            best_effort=bool(args.best_effort),
        )
        if rc != 0:
            raise SystemExit(err or f"drm_clip failed (rc={rc})")

    # Re-check DRM status after the clip so we can compute row scaling.
    try:
        after = _drm_status(drm_clip, card=args.card, connector=args.connector)
    except Exception as exc:
        if not args.best_effort:
            raise SystemExit(str(exc))
        _log("drm_status_after_skipped", error=f"{type(exc).__name__}: {exc}")
        after = before or DrmStatus(mode_w=0, mode_h=0, clip_h=0)

    # Avoid resizing the console unless the clip is actually in effect.
    if target == "half":
        want_h = int(args.height)
        if after.clip_h != want_h:
            msg = f"drm_clip verification failed (wanted clip_h={want_h}, got clip_h={after.clip_h})"
            if args.best_effort:
                _log("drm_clip_verify_failed", tty=str(tty_path), mode="half", wanted_clip_h=want_h, got_clip_h=after.clip_h)
                return 0
            raise SystemExit(msg)
    else:
        if after.clip_h != after.mode_h:
            msg = f"drm_clip verification failed (wanted clip_h={after.mode_h}, got clip_h={after.clip_h})"
            if args.best_effort:
                _log(
                    "drm_clip_verify_failed",
                    tty=str(tty_path),
                    mode="full",
                    wanted_clip_h=after.mode_h,
                    got_clip_h=after.clip_h,
                )
                return 0
            raise SystemExit(msg)

    mode_h = int(after.mode_h or 0)
    if mode_h <= 0:
        if args.best_effort:
            _log("tty_resize_skipped", reason="missing_mode_h", tty=str(tty_path))
            return 0
        raise SystemExit("failed to determine DRM mode height")

    if target == "half":
        full_rows = int(entry.get("full_rows") or 0)
        full_cols = int(entry.get("full_cols") or 0)
        if full_rows <= 0 or full_cols <= 0:
            full_rows, full_cols = rows, cols
            entry["full_rows"] = full_rows
            entry["full_cols"] = full_cols

        desired_rows = max(1, min(full_rows, int(math.floor(full_rows * (int(args.height) / mode_h)))))

        try:
            fd2 = os.open(str(tty_path), os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
            try:
                current_rows, current_cols = _get_winsize(fd2)
                if current_rows != desired_rows or current_cols != full_cols:
                    if args.clear:
                        _write_tty(fd2, f"\x1b[1;{desired_rows}r\x1b[H\x1b[2J")
                    else:
                        _write_tty(fd2, f"\x1b[1;{desired_rows}r\x1b[H")
                    _set_winsize(fd2, desired_rows, full_cols)
            finally:
                os.close(fd2)
        except OSError as exc:
            if not args.best_effort:
                raise SystemExit(f"failed to resize {tty_path}: [{exc.errno}] {exc.strerror}")
            _log("tty_resize_error", tty=str(tty_path), error=f"[{exc.errno}] {exc.strerror}")
            return 0

        entry["half_rows"] = desired_rows
        entry["last_half_height"] = int(args.height)
        entry["last_mode_h"] = mode_h

        state["ts"] = utc_iso()
        state["last_event"] = "set_half"
        state["last_tty"] = tty_key
        state["last_height"] = int(args.height)
        _write_json_atomic(state_path, state)
        _log("tty_half_applied", tty=str(tty_path), rows=desired_rows, cols=full_cols, mode_h=mode_h, height=int(args.height))
        return 0

    # full restore
    full_rows = int(entry.get("full_rows") or 0)
    full_cols = int(entry.get("full_cols") or 0)
    if full_rows <= 0 or full_cols <= 0:
        # Try to infer full size if we don't have a baseline.
        inferred = 0
        if before and before.clip_h and before.clip_h < before.mode_h and rows:
            inferred = int(math.ceil(rows * (before.mode_h / before.clip_h)))
        if not inferred:
            last_half_h = int(entry.get("last_half_height") or int(args.height))
            inferred = int(math.ceil(rows * (mode_h / max(1, last_half_h))))
        full_rows = inferred
        full_cols = cols

    try:
        fd3 = os.open(str(tty_path), os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        try:
            _write_tty(fd3, "\x1b[r\x1b[H")
            _set_winsize(fd3, full_rows, full_cols)
        finally:
            os.close(fd3)
    except OSError as exc:
        if not args.best_effort:
            raise SystemExit(f"failed to restore {tty_path}: [{exc.errno}] {exc.strerror}")
        _log("tty_restore_error", tty=str(tty_path), error=f"[{exc.errno}] {exc.strerror}")
        return 0

    entry["last_mode_h"] = mode_h
    state["ts"] = utc_iso()
    state["last_event"] = "set_full"
    state["last_tty"] = tty_key
    _write_json_atomic(state_path, state)
    _log("tty_full_restored", tty=str(tty_path), rows=full_rows, cols=full_cols)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply X1 Fold halfblank behavior on a Linux text console.")
    parser.add_argument(
        "--tty",
        default="",
        help="Target tty device (e.g. tty3, /dev/tty3, or 'active'; default: active).",
    )
    parser.add_argument("--drm-clip", default="", help="Path to drm_clip (default: find in $PATH).")
    parser.add_argument("--card", default="", help="Pass --card to drm_clip (default: drm_clip default).")
    parser.add_argument("--connector", default="", help="Pass --connector to drm_clip (default: drm_clip default).")
    parser.add_argument("--state-file", type=Path, default=_default_state_file(), help="State file path.")

    sub = parser.add_subparsers(dest="cmd", required=True)
    p_status = sub.add_parser("status", help="Print tty + drm status as JSON.")
    p_status.set_defaults(fn=cmd_status)

    p_set = sub.add_parser("set", help="Set half/full on the console.")
    p_set.add_argument("mode", choices=["half", "full"], help="Target mode.")
    p_set.add_argument("--height", type=int, default=1240, help="Half height in pixels (default: 1240).")
    p_set.add_argument(
        "--clear",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Clear the tty when entering half mode (default: true).",
    )
    p_set.add_argument(
        "--best-effort",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Return success even if drm_clip/tty resize can't be applied.",
    )
    p_set.set_defaults(fn=cmd_set)
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main(list(__import__("sys").argv[1:])))
