#!/usr/bin/env bash
set -euo pipefail

# Run the halfblank UI helper inside the active Wayland session.
#
# Motivation:
# - systemd --user services do not automatically inherit WAYLAND_DISPLAY/SWAYSOCK,
#   so the helper may incorrectly fall back to X11 or try wayland-0 when the real
#   socket is wayland-1 (etc).
# - We reliably grab the Wayland env from the running sway process.

uid="${UID:-$(id -u)}"

if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
  export XDG_RUNTIME_DIR="/run/user/${uid}"
fi

export XDG_SESSION_TYPE=wayland

# Wait for a usable Wayland socket (or sway), then export WAYLAND_DISPLAY.
#
# If we exec the helper without WAYLAND_DISPLAY, libwayland will default to
# wayland-0; on this device we commonly end up with wayland-1, so we'd loop
# forever failing to connect.
for _ in $(seq 1 150); do # ~30s @ 0.2s
  if [[ -n "${WAYLAND_DISPLAY:-}" && -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]]; then
    break
  fi

  sway_pid="$(pgrep -u "${uid}" -x sway | head -n 1 || true)"
  if [[ -n "${sway_pid}" && -r "/proc/${sway_pid}/environ" ]]; then
    while IFS= read -r kv; do
      case "$kv" in
        WAYLAND_DISPLAY=*) export WAYLAND_DISPLAY="${kv#WAYLAND_DISPLAY=}" ;;
        XDG_RUNTIME_DIR=*) export XDG_RUNTIME_DIR="${kv#XDG_RUNTIME_DIR=}" ;;
        SWAYSOCK=*) export SWAYSOCK="${kv#SWAYSOCK=}" ;;
      esac
    done < <(tr '\0' '\n' <"/proc/${sway_pid}/environ")

    if [[ -n "${WAYLAND_DISPLAY:-}" && -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]]; then
      break
    fi
  fi

  sock="$(find "${XDG_RUNTIME_DIR}" -maxdepth 1 -type s -name 'wayland-*' -printf '%f\n' 2>/dev/null | head -n 1 || true)"
  if [[ -n "$sock" && -S "${XDG_RUNTIME_DIR}/${sock}" ]]; then
    export WAYLAND_DISPLAY="$sock"
    break
  fi

  sleep 0.2
done

if [[ -z "${WAYLAND_DISPLAY:-}" || ! -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]]; then
  echo "x1fold-halfblank-ui-session: no Wayland socket found in ${XDG_RUNTIME_DIR}" >&2
  exit 1
fi

if [[ -z "${SWAYSOCK:-}" || ! -S "${SWAYSOCK}" ]]; then
  sock="$(find "${XDG_RUNTIME_DIR}" -maxdepth 1 -type s -name 'sway-ipc.*.sock' -print 2>/dev/null | head -n 1 || true)"
  if [[ -n "$sock" && -S "$sock" ]]; then
    export SWAYSOCK="$sock"
  fi
fi

exec /usr/local/bin/x1fold_halfblank_ui.py "$@"
