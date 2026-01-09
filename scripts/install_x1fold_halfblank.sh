#!/usr/bin/env bash
# Repo source: x1fold/scripts/install_x1fold_halfblank.sh
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: install_x1fold_halfblank.sh [--enable-system]

Installs the X1 Fold halfblank tooling into a live system:
  - /usr/local/bin/{x1fold_mode.py,x1fold_dock.py,x1fold_halfblankd.py,x1fold_halfblank_ui.py}
  - /usr/local/bin/{halfblank_switch.sh,halfblank_regression.sh,halfblank_collect.sh}
  - /etc/systemd/system/x1fold-halfblankd.service
  - /usr/lib/systemd/user/x1fold-halfblank-ui.service

Options:
  --enable-system   Enable + start x1fold-halfblankd.service (system daemon).

Notes:
  - The UI unit is a *user* service. Enable it per-user:
      systemctl --user enable --now x1fold-halfblank-ui.service
EOF
}

enable_system=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable-system) enable_system=1; shift ;;
    -h|--help) usage; exit 0 ;;
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
x1fold_root="$repo_root"

install -Dm0755 "$x1fold_root/tools/x1fold_mode.py" /usr/local/bin/x1fold_mode.py
install -Dm0755 "$x1fold_root/tools/x1fold_dock.py" /usr/local/bin/x1fold_dock.py
install -Dm0755 "$x1fold_root/tools/x1fold_halfblankd.py" /usr/local/bin/x1fold_halfblankd.py
install -Dm0755 "$x1fold_root/tools/x1fold_halfblank_ui.py" /usr/local/bin/x1fold_halfblank_ui.py

if [[ -f "$x1fold_root/tools/x1fold_x11_blank.c" ]]; then
  if command -v cc >/dev/null 2>&1 && command -v pkg-config >/dev/null 2>&1 && pkg-config --exists x11 xfixes; then
    tmp_bin="$(mktemp -t x1fold_x11_blank.XXXXXX)"
    cc -O2 -Wall -Wextra "$x1fold_root/tools/x1fold_x11_blank.c" -o "$tmp_bin" $(pkg-config --cflags --libs x11 xfixes)
    install -Dm0755 "$tmp_bin" /usr/local/bin/x1fold_x11_blank
    rm -f "$tmp_bin"
  else
    echo "warning: tools/x1fold_x11_blank.c present but missing build deps (need cc + pkg-config x11 xfixes); skipping x1fold_x11_blank install" >&2
  fi
fi

install -Dm0755 "$x1fold_root/scripts/halfblank_switch.sh" /usr/local/bin/halfblank_switch.sh
install -Dm0755 "$x1fold_root/scripts/halfblank_regression.sh" /usr/local/bin/halfblank_regression.sh
install -Dm0755 "$x1fold_root/scripts/halfblank_collect.sh" /usr/local/bin/halfblank_collect.sh

install -Dm0644 "$x1fold_root/systemd/x1fold-halfblankd.service" /etc/systemd/system/x1fold-halfblankd.service
install -Dm0644 "$x1fold_root/systemd/user/x1fold-halfblank-ui.service" /usr/lib/systemd/user/x1fold-halfblank-ui.service

systemctl daemon-reload

if [[ "$enable_system" -eq 1 ]]; then
  systemctl enable x1fold-halfblankd.service
  systemctl restart x1fold-halfblankd.service
fi

echo "installed: x1fold halfblank tooling"
