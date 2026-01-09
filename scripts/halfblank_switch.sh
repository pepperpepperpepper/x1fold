#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  halfblank_switch.sh status [-- <x1fold_mode.py args...>]
  halfblank_switch.sh half   [-- <x1fold_mode.py args...>]
  halfblank_switch.sh full   [-- <x1fold_mode.py args...>]

Notes:
  - This is a thin wrapper around x1fold/tools/x1fold_mode.py.
  - Root privileges are typically required for /dev/hidraw* access.
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

cmd="$1"
shift

extra_args=()
if [[ $# -gt 0 ]]; then
  if [[ "$1" == "--" ]]; then
    shift
    extra_args=("$@")
  else
    extra_args=("$@")
  fi
fi

x1fold_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

tool="${X1FOLD_MODE_TOOL:-}"
if [[ -z "$tool" ]]; then
  tool="$(command -v x1fold_mode.py 2>/dev/null || true)"
fi
if [[ -z "$tool" ]]; then
  tool="$(command -v x1fold_mode 2>/dev/null || true)"
fi
if [[ -z "$tool" ]]; then
  tool="${x1fold_root}/tools/x1fold_mode.py"
fi

if [[ ! -x "$tool" ]]; then
  echo "missing or non-executable: $tool" >&2
  echo "hint: install x1fold/tools/x1fold_mode.py as x1fold_mode.py (or set X1FOLD_MODE_TOOL=...)" >&2
  exit 1
fi

subcmd=()
case "$cmd" in
  status) subcmd=(status) ;;
  half) subcmd=(set half) ;;
  full) subcmd=(set full) ;;
  -h|--help|help) usage; exit 0 ;;
  *)
    echo "unknown command: $cmd" >&2
    usage
    exit 2
    ;;
esac

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  exec sudo -n -- "$tool" "${subcmd[@]}" "${extra_args[@]}"
fi

exec "$tool" "${subcmd[@]}" "${extra_args[@]}"
