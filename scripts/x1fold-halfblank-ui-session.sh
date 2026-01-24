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

# systemd --user services may inherit a stale WAYLAND_DISPLAY; always resolve
# it from the active session.
unset WAYLAND_DISPLAY

# Prefer a sway instance with a controlling TTY (the interactive session).
best_sway_pid=""
for pid in $(pgrep -u "${uid}" -x sway 2>/dev/null | sort -n); do
  tty="$(ps -o tty= -p "${pid}" 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ -z "$tty" || "$tty" == "?" ]]; then
    continue
  fi
  best_sway_pid="$pid"
  break
done

# Fall back to "any sway PID".
if [[ -z "$best_sway_pid" ]]; then
  best_sway_pid="$(pgrep -u "${uid}" -x sway 2>/dev/null | sort -n | head -n 1 || true)"
fi

# Wait for a usable Wayland socket (or sway), then export WAYLAND_DISPLAY.
#
# If we exec the helper without WAYLAND_DISPLAY, libwayland will default to
# wayland-0; on this device we commonly end up with wayland-1, so we'd loop
# forever failing to connect.
for _ in $(seq 1 150); do # ~30s @ 0.2s
  if [[ -n "${WAYLAND_DISPLAY:-}" && -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]]; then
    break
  fi

  if [[ -n "${best_sway_pid}" && -r "/proc/${best_sway_pid}/environ" ]]; then
    while IFS= read -r kv; do
      case "$kv" in
        WAYLAND_DISPLAY=*) export WAYLAND_DISPLAY="${kv#WAYLAND_DISPLAY=}" ;;
        XDG_RUNTIME_DIR=*) export XDG_RUNTIME_DIR="${kv#XDG_RUNTIME_DIR=}" ;;
        SWAYSOCK=*) export SWAYSOCK="${kv#SWAYSOCK=}" ;;
      esac
    done < <(tr '\0' '\n' <"/proc/${best_sway_pid}/environ")

    if [[ -n "${WAYLAND_DISPLAY:-}" && -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]]; then
      break
    fi

    # If sway didn't export WAYLAND_DISPLAY in its environment (can happen with
    # nested compositor setups), resolve the socket name by matching the sway
    # PID to the listening unix socket path.
    sock_path="$(
      ss -xlpn 2>/dev/null |
        rg "/run/user/${uid}/wayland-[0-9]+" |
        rg "pid=${best_sway_pid}," |
        rg -o "/run/user/${uid}/wayland-[0-9]+" |
        head -n 1 || true
    )"
    if [[ -n "${sock_path}" && -S "${sock_path}" ]]; then
      export WAYLAND_DISPLAY="$(basename "${sock_path}")"
      break
    fi
  fi

  # Fall back to the lowest-numbered wayland-* socket (stable).
  sock="$(ls -1 "${XDG_RUNTIME_DIR}"/wayland-* 2>/dev/null | rg -o 'wayland-[0-9]+' | sort -V | head -n 1 || true)"
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

# Always pick a SWAYSOCK rather than trusting the inherited environment.
#
# Reason: sway configs commonly run `dbus-update-activation-environment --systemd
# SWAYSOCK`, and if multiple sway instances exist the exported SWAYSOCK can be
# wrong/stale. That can cause swaymsg calls to hang forever.
best_sock=""

# Prefer a sway instance with a controlling TTY (the interactive session).
for pid in $(pgrep -u "${uid}" -x sway 2>/dev/null | sort -n); do
  tty="$(ps -o tty= -p "${pid}" 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ -z "$tty" || "$tty" == "?" ]]; then
    continue
  fi
  candidate="${XDG_RUNTIME_DIR}/sway-ipc.${uid}.${pid}.sock"
  if [[ -S "$candidate" ]]; then
    best_sock="$candidate"
    break
  fi
done

# Fall back to "any sway PID" socket.
if [[ -z "$best_sock" ]]; then
  for pid in $(pgrep -u "${uid}" -x sway 2>/dev/null | sort -n); do
    candidate="${XDG_RUNTIME_DIR}/sway-ipc.${uid}.${pid}.sock"
    if [[ -S "$candidate" ]]; then
      best_sock="$candidate"
      break
    fi
  done
fi

# Fall back to newest socket by mtime.
if [[ -z "$best_sock" ]]; then
  sock="$(ls -t "${XDG_RUNTIME_DIR}"/sway-ipc.*.sock 2>/dev/null | head -n 1 || true)"
  if [[ -n "$sock" && -S "$sock" ]]; then
    best_sock="$sock"
  fi
fi

if [[ -n "$best_sock" ]]; then
  export SWAYSOCK="$best_sock"
fi

exec /usr/local/bin/x1fold_halfblank_ui.py "$@"
