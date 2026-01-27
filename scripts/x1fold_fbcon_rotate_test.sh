#!/usr/bin/env bash
set -euo pipefail

ROTATE_PATH="${X1FOLD_FBCON_ROTATE_PATH:-/sys/class/graphics/fbcon/rotate}"

usage() {
  cat >&2 <<'EOF'
Usage:
  x1fold_fbcon_rotate_test.sh [--rollback SECONDS] [--step SECONDS] [--sequence "0 1 3 2 0"]

Defaults:
  --rollback 30
  --step 2
  --sequence "0 1 3 2 0"

Notes:
  - Run this from a real Linux VT (e.g. Ctrl+Alt+F2).
  - It arms an automatic rollback to the original rotation after --rollback seconds.
EOF
}

rollback_s="30"
step_s="2"
sequence="0 1 3 2 0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rollback) rollback_s="${2:-}"; shift 2 ;;
    --rollback=*) rollback_s="${1#*=}"; shift ;;
    --step) step_s="${2:-}"; shift 2 ;;
    --step=*) step_s="${1#*=}"; shift ;;
    --sequence) sequence="${2:-}"; shift 2 ;;
    --sequence=*) sequence="${1#*=}"; shift ;;
    -h|--help|help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  exec sudo -- "$0" "$@"
fi

if [[ ! -e "$ROTATE_PATH" ]]; then
  echo "missing: $ROTATE_PATH" >&2
  exit 1
fi

orig="$(cat "$ROTATE_PATH" 2>/dev/null || echo 0)"
echo "orig=$orig"

restore() {
  echo "$orig" >"$ROTATE_PATH" 2>/dev/null || true
}
trap restore EXIT

# Auto-rollback in case things go sideways.
setsid bash -c "sleep \"$rollback_s\"; echo \"$orig\" >\"$ROTATE_PATH\"" >/dev/null 2>&1 &
echo "rollback armed (${rollback_s}s)"

for v in $sequence; do
  if [[ ! "$v" =~ ^[0-3]$ ]]; then
    echo "bad rotation in sequence: $v" >&2
    exit 2
  fi
  echo "$v" >"$ROTATE_PATH"
  # Clear screen without relying on `clear`.
  printf '\033[H\033[2J'
  echo "fbcon rotate=$v (current=$(cat "$ROTATE_PATH" 2>/dev/null || echo '?'))"
  echo
  echo "If the console is broken/unreadable, just wait for rollback."
  sleep "$step_s"
done

echo "done (restoring orig=$orig)"
