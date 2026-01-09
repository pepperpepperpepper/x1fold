#!/usr/bin/env bash
# Repo source: x1fold/scripts/halfblank_regression.sh
set -euo pipefail

print_usage() {
  cat <<'USAGE'
Usage: halfblank_regression.sh [options]

Options:
  -n, --loops N           Number of full<->half iterations (default: 10)
  --log PATH              Write a log to PATH (default: /root/logs/halfblank-<ts>.log)
  --keep-daemon           Do not stop x1fold-halfblankd.service during the run
  --display MODE          Pass --display=<MODE> to x1fold_mode.py set (default: auto)
  --digitizer MODE        Pass --digitizer=<MODE> to x1fold_mode.py set (default: auto)
  -h, --help              Show this message

Notes:
  - Intended to run on the X1 Fold host as root.
  - Uses x1fold_mode.py status (I2C query tail) as the ground truth.
USAGE
}

loops=10
log=""
keep_daemon=0
display_mode="auto"
digitizer_mode="auto"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--loops)
      loops=$2
      shift 2
      ;;
    --log)
      log=$2
      shift 2
      ;;
    --keep-daemon)
      keep_daemon=1
      shift
      ;;
    --display)
      display_mode=$2
      shift 2
      ;;
    --digitizer)
      digitizer_mode=$2
      shift 2
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "halfblank_regression: unknown option: $1" >&2
      print_usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "$loops" =~ ^[0-9]+$ ]] || [[ "$loops" -le 0 ]]; then
  echo "halfblank_regression: loops must be a positive integer" >&2
  exit 2
fi

ts="$(date -u +%Y%m%d-%H%M%S)"
if [[ -z "$log" ]]; then
  log="/root/logs/halfblank-${ts}.log"
fi
mkdir -p "$(dirname "$log")"

tool="${X1FOLD_MODE_TOOL:-/usr/local/bin/x1fold_mode.py}"
if [[ ! -x "$tool" ]]; then
  tool="$(command -v x1fold_mode.py 2>/dev/null || true)"
fi
if [[ -z "$tool" ]] || [[ ! -x "$tool" ]]; then
  echo "halfblank_regression: missing x1fold_mode.py (set X1FOLD_MODE_TOOL=...)" >&2
  exit 1
fi

status_line() {
  "$tool" status 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("mode"), (d.get("i2c_query") or {}).get("tail_0x10_0x11"))'
}

echo "halfblank_regression: starting (loops=$loops, log=$log, display=$display_mode, digitizer=$digitizer_mode)" | tee -a "$log"

daemon_was_active=0
if systemctl is-active --quiet x1fold-halfblankd.service; then
  daemon_was_active=1
  if [[ "$keep_daemon" -eq 0 ]]; then
    echo "halfblank_regression: stopping x1fold-halfblankd.service" | tee -a "$log"
    systemctl stop x1fold-halfblankd.service || true
  fi
fi

for i in $(seq 1 "$loops"); do
  echo "== iter $i/$loops: set full ==" | tee -a "$log"
  "$tool" set full --display "$display_mode" --digitizer "$digitizer_mode" 2>&1 | tee -a "$log"
  read -r mode tail < <(status_line || echo "unknown ??")
  echo "status: mode=$mode tail=$tail" | tee -a "$log"
  if [[ "$mode" != "full" ]]; then
    echo "FAIL: expected mode=full" | tee -a "$log"
    exit 1
  fi

  echo "== iter $i/$loops: set half ==" | tee -a "$log"
  "$tool" set half --display "$display_mode" --digitizer "$digitizer_mode" 2>&1 | tee -a "$log"
  read -r mode tail < <(status_line || echo "unknown ??")
  echo "status: mode=$mode tail=$tail" | tee -a "$log"
  if [[ "$mode" != "half" ]]; then
    echo "FAIL: expected mode=half" | tee -a "$log"
    exit 1
  fi
done

echo "halfblank_regression: completed $loops iterations" | tee -a "$log"

if [[ "$keep_daemon" -eq 0 ]] && [[ "$daemon_was_active" -eq 1 ]]; then
  echo "halfblank_regression: restarting x1fold-halfblankd.service" | tee -a "$log"
  systemctl start x1fold-halfblankd.service || true
fi
