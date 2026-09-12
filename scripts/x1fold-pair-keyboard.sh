#!/usr/bin/env bash
# Repo source: x1fold/scripts/x1fold-pair-keyboard.sh
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  x1fold-pair-keyboard.sh [ADDRESS]
  x1fold-pair-keyboard.sh --restore
  x1fold-pair-keyboard.sh --list

Pairs an additional Bluetooth keyboard without stranding you without input.

With no ADDRESS the keyboard currently in pairing mode is auto-detected by HID
keyboard appearance (0x03c1) / BlueZ icon, which avoids picking up the ambient
BLE clutter (lights, wearables, speakers) that a bare scan returns.

The X1 Fold's AX211 holds several peripherals at once, so the first pairing
attempt leaves the existing keyboard connected and you keep working input
throughout. Only if that attempt fails is the existing keyboard disconnected
for a retry, and it is reconnected afterwards either way.

Options:
  --restore   Reconnect the previously connected keyboard and exit.
  --list      List connected/known keyboards and exit.
  -h, --help  Show this help.

Environment:
  X1FOLD_OLD_KBD   Address of the existing keyboard (default: auto-detect the
                   connected one). Needed only if auto-detection picks wrong.
  SCAN_SECS        Discovery window, default 25.
  PAIR_WINDOW      Seconds allowed to type a passkey, default 45.
  X1FOLD_PAIR_LOG  Log path, default ${XDG_CACHE_HOME:-~/.cache}/x1fold-pair-keyboard.log

Notes:
  - No root required; this talks to BlueZ over D-Bus as your user.
  - If the new keyboard asks for a passkey, it is printed to this terminal.
    Type it on the NEW keyboard and press Enter. Run this from a real terminal
    so you can see it.
EOF
}

MODE="pair"
TARGET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --restore) MODE="restore"; shift ;;
    --list) MODE="list"; shift ;;
    -*) echo "unknown option: $1" >&2; usage; exit 2 ;;
    *)
      if [[ -n "$TARGET" ]]; then
        echo "unexpected extra argument: $1" >&2
        usage
        exit 2
      fi
      TARGET="$1"
      shift
      ;;
  esac
done

if [[ -n "$TARGET" && ! "$TARGET" =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]; then
  echo "not a bluetooth address: $TARGET" >&2
  exit 2
fi

SCAN_SECS="${SCAN_SECS:-25}"
PAIR_WINDOW="${PAIR_WINDOW:-45}"
LOG="${X1FOLD_PAIR_LOG:-${XDG_CACHE_HOME:-$HOME/.cache}/x1fold-pair-keyboard.log}"
mkdir -p "$(dirname "$LOG")"

command -v bluetoothctl >/dev/null 2>&1 || {
  echo "bluetoothctl not found (install bluez-utils)" >&2
  exit 1
}

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m!!  %s\033[0m\n' "$*" >&2; }
die() { printf '\n\033[1;31mXX  %s\033[0m\n' "$*" >&2; exit 1; }

info_of() { bluetoothctl info "$1" 2>/dev/null || true; }
alias_of() { info_of "$1" | awk -F': ' '/^\s*Alias:/{print $2; exit}'; }
is_connected() { info_of "$1" | grep -q 'Connected: yes'; }

# HID keyboards report appearance 0x03c1; BlueZ also derives an icon. Either is
# enough to tell a keyboard apart from the ambient BLE noise.
looks_like_keyboard() {
  info_of "$1" | grep -qiE 'Icon: input-keyboard|Appearance: 0x03c1'
}

list_keyboards() {
  local mac
  while read -r _ mac _; do
    [[ -n "$mac" ]] || continue
    if looks_like_keyboard "$mac"; then
      local state="known"
      is_connected "$mac" && state="connected"
      printf '  %s  %-11s %s\n' "$mac" "$state" "$(alias_of "$mac")"
    fi
  done < <(bluetoothctl devices 2>/dev/null || true)
}

# The keyboard to protect: an explicit override, else whichever keyboard is
# connected right now. Empty is fine -- it just means there's nothing to lose.
detect_old_kbd() {
  if [[ -n "${X1FOLD_OLD_KBD:-}" ]]; then
    printf '%s' "$X1FOLD_OLD_KBD"
    return 0
  fi
  local mac
  while read -r _ mac _; do
    [[ -n "$mac" ]] || continue
    if looks_like_keyboard "$mac"; then
      printf '%s' "$mac"
      return 0
    fi
  done < <(bluetoothctl devices Connected 2>/dev/null || true)
  printf ''
}

reconnect_old() {
  local old="$1"
  [[ -n "$old" ]] || return 0
  if is_connected "$old"; then
    return 0
  fi
  say "Reconnecting $old so you have a keyboard again"
  local i
  for i in 1 2 3; do
    bluetoothctl connect "$old" >/dev/null 2>&1 || true
    sleep 3
    if is_connected "$old"; then
      say "Old keyboard is back."
      return 0
    fi
  done
  warn "Could not reconnect $old."
  warn "Use the touchscreen/on-screen keyboard and run:"
  warn "    x1fold-pair-keyboard.sh --restore"
  return 1
}

OLD_KBD="$(detect_old_kbd)"

case "$MODE" in
  list)
    echo "Keyboards known to BlueZ:"
    list_keyboards
    exit 0
    ;;
  restore)
    [[ -n "$OLD_KBD" ]] || die "No keyboard to restore. Pass one via X1FOLD_OLD_KBD, or see --list."
    reconnect_old "$OLD_KBD"
    exit $?
    ;;
esac

# ------------------------------------------------------------------ discovery --
if [[ -z "$TARGET" ]]; then
  say "Snapshotting devices already known to BlueZ"
  mapfile -t KNOWN < <(bluetoothctl devices 2>/dev/null | awk '{print $2}' || true)

  say "Scanning ${SCAN_SECS}s for a keyboard in pairing mode"
  say "(the new keyboard's pairing LED should be blinking NOW)"
  timeout $((SCAN_SECS + 5)) bluetoothctl --timeout "$SCAN_SECS" scan on >/dev/null 2>&1 || true

  CANDIDATES=()
  while read -r _ mac _; do
    [[ -n "$mac" ]] || continue
    [[ "$mac" == "$OLD_KBD" ]] && continue
    for k in "${KNOWN[@]:-}"; do
      [[ "$mac" == "$k" ]] && continue 2
    done
    looks_like_keyboard "$mac" && CANDIDATES+=("$mac")
  done < <(bluetoothctl devices 2>/dev/null || true)

  # Nothing newly discovered: fall back to any keyboard that isn't the one we're
  # protecting, in case an earlier scan already cached it.
  if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    while read -r _ mac _; do
      [[ -n "$mac" ]] || continue
      [[ "$mac" == "$OLD_KBD" ]] && continue
      looks_like_keyboard "$mac" && CANDIDATES+=("$mac")
    done < <(bluetoothctl devices 2>/dev/null || true)
  fi

  if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    die "No keyboard found in pairing mode. Nothing was disconnected, so your current keyboard still works. Put the new one in pairing mode and rerun."
  fi
  if [[ ${#CANDIDATES[@]} -gt 1 ]]; then
    warn "More than one keyboard is advertising:"
    for c in "${CANDIDATES[@]}"; do
      printf '    %s  %s\n' "$c" "$(alias_of "$c")" >&2
    done
    die "Rerun with the address you want: x1fold-pair-keyboard.sh <ADDRESS>"
  fi
  TARGET="${CANDIDATES[0]}"
fi

if [[ -n "$OLD_KBD" && "$TARGET" == "$OLD_KBD" ]]; then
  die "Target $TARGET is the keyboard that's already connected. Nothing to do."
fi

NAME="$(alias_of "$TARGET")"
say "Target:   $TARGET ${NAME:+($NAME)}"
if [[ -n "$OLD_KBD" ]]; then
  say "Existing: $OLD_KBD ($(alias_of "$OLD_KBD"))"
else
  say "Existing: none connected -- nothing to protect"
fi

# -------------------------------------------------------------------- pairing --
attempt_pair() {
  local drop_old="$1"
  {
    echo "power on"
    echo "agent KeyboardDisplay"
    echo "default-agent"
    if [[ "$drop_old" == "yes" && -n "$OLD_KBD" ]]; then
      echo "disconnect $OLD_KBD"
      sleep 4
    fi
    echo "scan on"
    sleep 6
    echo "pair $TARGET"
    # A passkey, if any, is printed by the agent above. Type it on the NEW
    # keyboard and press Enter inside this window.
    sleep "$PAIR_WINDOW"
    echo "scan off"
    echo "trust $TARGET"
    sleep 1
    echo "connect $TARGET"
    sleep 6
    echo "quit"
  } | bluetoothctl 2>&1 | tee -a "$LOG" || true

  is_connected "$TARGET"
}

: > "$LOG"

say "Attempt 1: pairing with the existing keyboard left connected"
if attempt_pair no; then
  say "Paired and connected: $TARGET ${NAME:+($NAME)}"
  if [[ -n "$OLD_KBD" ]]; then
    if is_connected "$OLD_KBD"; then
      say "Both keyboards are connected."
    else
      reconnect_old "$OLD_KBD" || true
    fi
  fi
  say "Log: $LOG"
  exit 0
fi

warn "That didn't take. Retrying with the existing keyboard disconnected."
[[ -n "$OLD_KBD" ]] && warn "You'll lose input until this finishes -- about a minute."
sleep 3

if attempt_pair yes; then
  say "Paired and connected: $TARGET ${NAME:+($NAME)}"
  reconnect_old "$OLD_KBD" || true
  say "Log: $LOG"
  exit 0
fi

warn "New keyboard did not pair."
reconnect_old "$OLD_KBD" || true
warn "Full log: $LOG"
exit 1
