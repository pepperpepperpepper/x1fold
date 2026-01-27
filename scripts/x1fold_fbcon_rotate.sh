#!/usr/bin/env bash
set -euo pipefail

ROTATE_PATH="${X1FOLD_FBCON_ROTATE_PATH:-/sys/class/graphics/fbcon/rotate}"
ROTATE_ALL_PATH="${X1FOLD_FBCON_ROTATE_ALL_PATH:-/sys/class/graphics/fbcon/rotate_all}"
PIDFILE="${X1FOLD_FBCON_ROTATE_PIDFILE:-/run/x1fold-fbcon-rotate.rollback.pid}"

usage() {
  cat >&2 <<'EOF'
Usage:
  x1fold_fbcon_rotate.sh status
  x1fold_fbcon_rotate.sh set <0|1|2|3> [--rollback SECONDS] [--all]
  x1fold_fbcon_rotate.sh cancel

Notes:
  - Rotation values: 0=normal, 1=90deg, 2=180deg, 3=270deg.
  - --rollback restores the previous value after SECONDS (best-effort).
  - --all writes to /sys/class/graphics/fbcon/rotate_all instead of rotate.
EOF
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  -h|--help|help)
    usage
    exit 0
    ;;
esac

need_root=0
case "$cmd" in
  status) need_root=0 ;;
  *) need_root=1 ;;
esac
if [[ "$need_root" -eq 1 && "${EUID:-$(id -u)}" -ne 0 ]]; then
  exec sudo -- "$0" "$cmd" "$@"
fi

rotate_file="$ROTATE_PATH"
rollback_s=""
use_all=0

case "$cmd" in
  status)
    if [[ ! -r "$rotate_file" ]]; then
      echo "missing: $rotate_file" >&2
      exit 1
    fi
    cat "$rotate_file"
    ;;

  cancel)
    if [[ -f "$PIDFILE" ]]; then
      pid="$(cat "$PIDFILE" 2>/dev/null || true)"
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
      fi
      rm -f "$PIDFILE" 2>/dev/null || true
      echo "ok"
      exit 0
    fi
    echo "no_rollback"
    ;;

  set)
    if [[ $# -lt 1 ]]; then
      usage
      exit 2
    fi
    val="$1"
    shift
    if [[ ! "$val" =~ ^[0-3]$ ]]; then
      echo "error: rotation must be 0..3 (got: $val)" >&2
      exit 2
    fi
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --rollback)
          rollback_s="${2:-}"
          shift 2
          ;;
        --rollback=*)
          rollback_s="${1#*=}"
          shift
          ;;
        --all)
          use_all=1
          shift
          ;;
        -h|--help|help)
          usage
          exit 0
          ;;
        *)
          echo "unknown option: $1" >&2
          usage
          exit 2
          ;;
      esac
    done

    if [[ "$use_all" -eq 1 ]]; then
      rotate_file="$ROTATE_ALL_PATH"
    fi

    if [[ ! -e "$rotate_file" ]]; then
      echo "missing: $rotate_file" >&2
      exit 1
    fi

    # Cancel any prior rollback we started.
    if [[ -f "$PIDFILE" ]]; then
      "$0" cancel >/dev/null 2>&1 || true
    fi

    orig="0"
    if [[ -r "$ROTATE_PATH" ]]; then
      orig="$(cat "$ROTATE_PATH" 2>/dev/null || echo 0)"
    fi

    echo "$val" >"$rotate_file"

    if [[ -n "$rollback_s" ]]; then
      if ! [[ "$rollback_s" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        echo "warning: ignoring invalid rollback seconds: $rollback_s" >&2
      elif [[ "$rollback_s" != "0" ]]; then
        rm -f "$PIDFILE" 2>/dev/null || true
        setsid bash -c "sleep \"$rollback_s\"; echo \"$orig\" >\"$ROTATE_PATH\"" >/dev/null 2>&1 &
        echo $! >"$PIDFILE" 2>/dev/null || true
        echo "rollback_armed"
      fi
    fi
    ;;

  *)
    echo "unknown command: $cmd" >&2
    usage
    exit 2
    ;;
esac
