#!/usr/bin/env bash
# Repo source: x1fold/scripts/install_x1fold_fnctl.sh
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: install_x1fold_fnctl.sh

Installs the X1 Fold keyboard Fn/Ctrl helper into a live system:
  - /usr/local/bin/x1fold-fnctl

This helper replays the Lenovo keyboard HID output report that toggles the
keyboard-side Fn/Ctrl swap on supported ThinkPad X1 Fold keyboards.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
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

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  exec sudo -- "$0" "$@"
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

install -Dm0755 "$repo_root/scripts/x1fold-fnctl" /usr/local/bin/x1fold-fnctl

echo "installed: x1fold-fnctl"
