#!/usr/bin/env bash
# Repo source: x1fold/scripts/x1fold-pair-keyboard.sh
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  x1fold-pair-keyboard.sh --watch            <-- use this one
  x1fold-pair-keyboard.sh --check [ADDRESS]
  x1fold-pair-keyboard.sh [ADDRESS]
  x1fold-pair-keyboard.sh --restore
  x1fold-pair-keyboard.sh --list

Pairs an additional Bluetooth keyboard without stranding you without input.

START HERE: run --watch, then hold the keyboard's Bluetooth button. It pairs
by itself. You do not have to synchronize anything.

Why --watch exists: these keyboards advertise in pairing mode for well under a
minute, and a scan-then-pair chain loses that race -- BlueZ is still building
the device object when the keyboard goes quiet, so `bluetoothctl` reports
"Device ... not available" even while the keyboard is plainly discoverable.
--watch runs a continuous raw-HCI monitor and pairs via the kernel management
interface the moment a keyboard advertises, which needs no scan cycle.

See docs/BLUETOOTH_KEYBOARD_PAIRING.md for the full explanation, including why
the GUI and every bluetoothctl recipe fail on this hardware.

Options:
  --watch     Watch continuously and auto-pair any keyboard that enters
              pairing mode. Needs sudo (raw HCI). Ctrl-C to stop.
  --check     Report whether a keyboard is advertising and whether it is in
              real pairing mode or only reconnect mode. Needs sudo.
  --restore   Reconnect the previously connected keyboard and exit.
  --list      List connected/known keyboards and exit.
  -h, --help  Show this help.

Environment:
  X1FOLD_OLD_KBD   Address of the existing keyboard (default: auto-detect the
                   connected one). Needed only if auto-detection picks wrong.
  SCAN_SECS        Discovery window, default 25.
  PAIR_WINDOW      Seconds allowed to type a passkey, default 45.
  WATCH_SECS       How long --watch runs before giving up, default 600.
  X1FOLD_PAIR_LOG  Log path, default ${XDG_CACHE_HOME:-~/.cache}/x1fold-pair-keyboard.log

Notes:
  - --watch and --check need sudo; the other modes do not.
  - Nothing here ever disconnects a keyboard that is already connected.
  - If the new keyboard asks for a passkey, it is printed to this terminal.
    Type it on the NEW keyboard and press Enter.
EOF
}

MODE="pair"
TARGET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --watch) MODE="watch"; shift ;;
    --check) MODE="check"; shift ;;
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
WATCH_SECS="${WATCH_SECS:-600}"
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

rssi_of() { info_of "$1" | awk -F': ' '/^\s*RSSI:/{print $2; exit}'; }

# HID keyboards report appearance 0x03c1 and BlueZ derives an icon from it, but
# neither is guaranteed to be populated for a device that has only ever been
# seen in an advertisement. Fall back to the name, which is reliable for the
# devices we care about here.
looks_like_keyboard() {
  local info
  info="$(info_of "$1")"
  grep -qiE 'Icon: input-keyboard|Appearance: 0x03c1' <<<"$info" && return 0
  grep -qiE '^[[:space:]]*(Name|Alias):.*(keyboard|kbd)' <<<"$info"
}

# Which input nodes belong to which keyboard. With two units of the same model
# every node has an identical name, and Phys is the *adapter* address, so uniq
# (the keyboard's own address) is the only discriminator. Event numbers are not
# stable across reconnects either.
input_nodes_for() {
  local mac="${1,,}" e uniq name
  for e in /sys/class/input/event*; do
    [[ -e "$e/device/uniq" ]] || continue
    uniq="$(cat "$e/device/uniq" 2>/dev/null || true)"
    [[ "${uniq,,}" == "$mac" ]] || continue
    name="$(cat "$e/device/name" 2>/dev/null || true)"
    printf '      /dev/input/%s  %s\n' "$(basename "$e")" "$name"
  done
}

# Two units of the same model produce identically-named input nodes, so show
# which belongs to which -- this is what you need for per-keyboard keyd/hwdb
# rules, and the mapping is not discoverable from the node names alone.
report_input_nodes() {
  local mac nodes
  for mac in "${TARGET:-}" "${OLD_KBD:-}"; do
    [[ -n "$mac" ]] || continue
    is_connected "$mac" || continue
    nodes="$(input_nodes_for "$mac")"
    [[ -n "$nodes" ]] || continue
    printf '    %s  %s\n' "$mac" "$(alias_of "$mac")"
    printf '%s\n' "$nodes"
  done
}

list_keyboards() {
  local mac
  while read -r _ mac _; do
    [[ -n "$mac" ]] || continue
    if looks_like_keyboard "$mac"; then
      local state="known" rssi
      is_connected "$mac" && state="connected"
      rssi="$(rssi_of "$mac")"
      printf '  %s  %-11s %s%s\n' "$mac" "$state" "$(alias_of "$mac")" \
        "${rssi:+  (RSSI ${rssi})}"
      [[ "$state" == "connected" ]] && input_nodes_for "$mac"
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

# --- raw HCI: the only view that shows these keyboards --------------------- #
#
# BlueZ discards advertisements whose Flags byte lacks a discoverable bit, so a
# keyboard advertising to reconnect to an existing bond never becomes a device
# object and `bluetoothctl pair` answers "not available". btmon sees every
# packet the controller receives, before any of that filtering.
#
# Flags bits:  0x01 LE Limited Discoverable
#              0x02 LE General Discoverable   <-- real pairing mode
#              0x04 BR/EDR Not Supported
# 0x06 = pairing mode.  0x04 = reconnect only, it will drop our link.

need_hci_tools() {
  command -v btmon >/dev/null 2>&1 || die "btmon not found (install bluez-utils)"
  command -v btmgmt >/dev/null 2>&1 || die "btmgmt not found (install bluez-utils)"
  sudo -n true 2>/dev/null || die "--$MODE needs sudo: btmon and btmgmt talk to the kernel directly"
}

# btmon prints a multi-line block per advertising report, and the fields we
# need are spread across it (Address early, Name last), so accumulate and emit
# when the next block starts. Emits: "ADDR FLAGS RSSI NAME" -- name last so a
# plain `read` captures names containing spaces.
ADV_FILTER='
  function flush_rec() {
      if (kbd && addr != "") {
          print addr, (flags == "" ? "0x00" : flags), rssi, (name == "" ? "-" : name)
          # awk block-buffers when stdout is a pipe, so without this the reader
          # sees nothing until 4KB accumulates -- which never happens here, and
          # made --watch silently useless.
          fflush()
      }
      kbd=0; addr=""; flags=""; rssi="?"; name=""
  }
  /^[<>@=]/                             { flush_rec() }
  /^[[:space:]]*Address: [0-9A-F:]{17}/ { addr=$2 }
  /^[[:space:]]*RSSI: /                 { rssi=$2 }
  /Appearance: Keyboard/                { kbd=1 }
  /^[[:space:]]*Flags: 0x/              { flags=$2 }
  /^[[:space:]]*Name \(/ {
      line=$0
      sub(/^[[:space:]]*Name \([^)]*\): /, "", line)
      name=line
  }
  END { flush_rec() }
'

# A neighbour'\''s keyboard can sit in pairing mode at the same time as yours --
# that has been observed here, at a stronger RSSI than some of our own traffic.
# Auto-pairing is therefore restricted to devices whose advertised name looks
# like this hardware and whose signal is close. Pass an explicit ADDRESS to
# --watch to bypass both checks.
KBD_NAME_RE="${X1FOLD_KBD_NAME_RE:-ThinkPad|TrackPoint|X1F}"
KBD_MIN_RSSI="${X1FOLD_KBD_MIN_RSSI:--75}"

is_our_keyboard() {
  local addr="$1" rssi="$2" name="$3"
  # An explicitly requested address always wins.
  if [[ -n "${TARGET:-}" ]]; then
    [[ "${addr^^}" == "${TARGET^^}" ]]
    return $?
  fi
  if [[ ! "$name" =~ $KBD_NAME_RE ]]; then
    return 1
  fi
  if [[ "$rssi" =~ ^-?[0-9]+$ ]] && (( rssi < KBD_MIN_RSSI )); then
    return 1
  fi
  return 0
}

is_discoverable_flags() {
  local f=$(( $1 ))
  (( (f & 0x03) != 0 ))
}

# An LE scan has to be running for advertising reports to reach the host at
# all; btmon only observes what the controller already receives.
#
# Run it as repeated bounded bursts rather than one unbroken scan. A single
# multi-minute scan keeps the CNVi radio saturated (it is shared with Wi-Fi),
# and this machine hard-locked once with a 15-minute scan in flight. Nothing in
# the logs tied the lockup to Bluetooth, but there is no reason to hold the
# radio down continuously when short bursts detect an advertisement just as
# well -- the keyboard advertises for tens of seconds.
SCAN_BURST="${SCAN_BURST:-30}"
SCAN_GAP="${SCAN_GAP:-2}"

start_background_scan() {
  local total="$1"
  (
    local spent=0
    while (( spent < total )); do
      local burst=$(( total - spent < SCAN_BURST ? total - spent : SCAN_BURST ))
      timeout "$burst" bluetoothctl --timeout "$burst" scan on >/dev/null 2>&1 || true
      sleep "$SCAN_GAP"
      spent=$(( spent + burst + SCAN_GAP ))
    done
  ) &
  printf '%s' "$!"
}

# Capability matters here. With KeyboardDisplay (-c 4) this keyboard answers
# with "User Confirm 000000 hint 1" and waits for an acknowledgement; btmgmt
# run non-interactively has no way to give one, so the link drops and pairing
# fails with status 0x03. NoInputNoOutput (-c 3) selects Just Works, which
# needs no confirmation. Try that first and keep -c 4 as a fallback.
pair_now() {
  local addr="$1" cap
  # Clear anything pending, or the kernel answers Busy (0x0a).
  sudo -n btmgmt --index 0 cancelpair -t 2 "$addr" </dev/null >/dev/null 2>&1 || true
  sleep 1
  for cap in 3 4; do
    say "Pairing with $addr (io-capability $cap)"
    sudo -n timeout 60 btmgmt --index 0 pair -t 2 -c "$cap" "$addr" </dev/null 2>&1 \
      | tee -a "$LOG"
    if is_paired "$addr"; then
      return 0
    fi
    sudo -n btmgmt --index 0 cancelpair -t 2 "$addr" </dev/null >/dev/null 2>&1 || true
    sleep 1
  done
  return 1
}

is_paired() {
  bluetoothctl devices Paired 2>/dev/null | grep -qi "${1}"
}

cmd_check() {
  need_hci_tools
  local want="${1:-}"
  local tmp
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN

  say "Listening ${SCAN_SECS}s for keyboard advertisements"
  sudo -n timeout $((SCAN_SECS + 3)) btmon > "$tmp" 2>&1 &
  local mon=$!
  sleep 1
  local sp; sp="$(start_background_scan "$SCAN_SECS")"
  wait "$mon" 2>/dev/null || true
  kill "$sp" 2>/dev/null || true

  local found=0 rc=2 addr flags rssi name
  while read -r addr flags rssi name; do
    [[ -n "$want" && "${addr^^}" != "${want^^}" ]] && continue
    found=1
    if is_discoverable_flags "$flags"; then
      printf '  %s  %-14s flags=%s RSSI=%-4s ==> PAIRING MODE, ready to pair\n' \
        "$addr" "$name" "$flags" "$rssi"
      rc=0
    else
      printf '  %s  %-14s flags=%s RSSI=%-4s ==> reconnect only (bonded elsewhere)\n' \
        "$addr" "$name" "$flags" "$rssi"
      [[ $rc -eq 0 ]] || rc=3
    fi
  done < <(awk "$ADV_FILTER" "$tmp" | sort -u)

  if [[ $found -eq 0 ]]; then
    echo "  no keyboard advertisements heard -- turn it on / hold its Bluetooth button"
    return 2
  fi
  return $rc
}

cmd_watch() {
  need_hci_tools
  say "Watching up to ${WATCH_SECS}s for a keyboard to enter pairing mode."
  say "Hold the new keyboard's Bluetooth button now -- pairing is automatic."
  say "Your existing keyboard stays connected. Ctrl-C to stop."

  local sp; sp="$(start_background_scan "$WATCH_SECS")"
  # Re-arm the scan periodically; bluetoothctl's --timeout ends it.
  trap 'kill "$sp" 2>/dev/null || true' EXIT

  local addr flags rssi name
  local -A tried=()
  while read -r addr flags rssi name; do
    [[ -n "$OLD_KBD" && "${addr^^}" == "${OLD_KBD^^}" ]] && continue
    is_paired "$addr" && continue

    if ! is_our_keyboard "$addr" "$rssi" "$name"; then
      if [[ -z "${tried[$addr]:-}" ]]; then
        tried[$addr]="foreign"
        warn "Ignoring $addr ('$name', RSSI $rssi) -- not this hardware, or too far."
        warn "If it IS yours: x1fold-pair-keyboard.sh --watch $addr"
      fi
      continue
    fi

    if ! is_discoverable_flags "$flags"; then
      if [[ "${tried[$addr]:-}" != "seen" ]]; then
        tried[$addr]="seen"
        warn "$addr ('$name') is advertising to reconnect (flags=$flags), not pairing."
        warn "Hold its Bluetooth button longer to clear the old bond."
      fi
      continue
    fi

    if [[ "${tried[$addr]:-}" == "pairing" ]]; then
      continue
    fi
    tried[$addr]="pairing"

    say "Keyboard in PAIRING MODE: $addr '$name' (flags=$flags, RSSI=$rssi)"
    if pair_now "$addr"; then
      say "Paired: $addr"
      sudo -n btmgmt --index 0 pairable on </dev/null >/dev/null 2>&1 || true
      bluetoothctl trust "$addr" >/dev/null 2>&1 || true
      bluetoothctl connect "$addr" >/dev/null 2>&1 || true
      sleep 3
      say "Input nodes (matched by address -- the names are identical):"
      TARGET="$addr"
      report_input_nodes
      say "Log: $LOG"
      return 0
    fi
    warn "Pairing $addr failed; still watching."
    tried[$addr]=""
  done < <(sudo -n timeout "$WATCH_SECS" btmon 2>/dev/null | awk "$ADV_FILTER")

  warn "Gave up after ${WATCH_SECS}s without a keyboard entering pairing mode."
  return 1
}

OLD_KBD="$(detect_old_kbd)"

case "$MODE" in
  watch)
    cmd_watch
    exit $?
    ;;
  check)
    cmd_check "$TARGET"
    exit $?
    ;;
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
      printf '    %s  %s%s\n' "$c" "$(alias_of "$c")" \
        "$(r="$(rssi_of "$c")"; [[ -n "$r" ]] && printf '  (RSSI %s)' "$r")" >&2
    done
    warn "Two units of the same model advertise identical names -- the"
    warn "strongest RSSI is the one nearest to you."
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
  say "Input nodes (matched by device address, since the names are identical):"
  report_input_nodes
  say "Log: $LOG"
  exit 0
fi

warn "That didn't take. Retrying with the existing keyboard disconnected."
[[ -n "$OLD_KBD" ]] && warn "You'll lose input until this finishes -- about a minute."
sleep 3

if attempt_pair yes; then
  say "Paired and connected: $TARGET ${NAME:+($NAME)}"
  reconnect_old "$OLD_KBD" || true
  say "Input nodes (matched by device address, since the names are identical):"
  report_input_nodes
  say "Log: $LOG"
  exit 0
fi

warn "New keyboard did not pair."
reconnect_old "$OLD_KBD" || true
warn "Full log: $LOG"
exit 1
