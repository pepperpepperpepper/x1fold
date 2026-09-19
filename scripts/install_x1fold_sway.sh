#!/usr/bin/env bash
# Repo source: x1fold/scripts/install_x1fold_sway.sh
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: install_x1fold_sway.sh [--dry-run] [--reload]

Installs the X1 Fold Sway snippet into the *current user's* config:
  - ~/.config/sway/x1fold.conf          (repo-managed; overwritten on reinstall)
  - adds `include ~/.config/sway/x1fold.conf` to ~/.config/sway/config

What the snippet does: blanks the internal panel (eDP-1) when the fold closes
and restores it when it opens, via `bindswitch`.

Run this as your desktop user, NOT as root -- it writes into $HOME.
Hand edits belong in ~/.config/sway/config.user, which this never touches.

Options:
  --dry-run   Show what would change, write nothing.
  --reload    Run `swaymsg reload` afterwards (needs a live Sway session).
EOF
}

dry_run=0
do_reload=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) dry_run=1; shift ;;
    --reload) do_reload=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

# This installs into $HOME. Running it under sudo would create root-owned
# dotfiles in the invoking user's home, which is a mess to unpick later.
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "install_x1fold_sway.sh: do not run as root -- this writes into \$HOME." >&2
  if [[ -n "${SUDO_USER:-}" ]]; then
    echo "Re-run as your desktop user:  $0 $*" >&2
  fi
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$repo_root/sway/x1fold.conf"
sway_dir="${XDG_CONFIG_HOME:-$HOME/.config}/sway"
dest="$sway_dir/x1fold.conf"
main_config="$sway_dir/config"
include_line="include $dest"

if [[ ! -f "$src" ]]; then
  echo "missing repo file: $src" >&2
  exit 1
fi

if [[ ! -f "$main_config" ]]; then
  echo "no Sway config at $main_config -- is Sway set up for this user?" >&2
  exit 1
fi

# --- the snippet ------------------------------------------------------------

if [[ "$dry_run" -eq 1 ]]; then
  echo "would install: $src -> $dest"
else
  install -Dm0644 "$src" "$dest"
  echo "installed: $dest"
fi

# --- the include ------------------------------------------------------------

# Match the include whether it was written with $HOME expanded or as a literal
# ~, and ignore commented-out lines.
if grep -vE '^[[:space:]]*#' "$main_config" \
  | grep -qE '^[[:space:]]*include[[:space:]]+\S*/\.config/sway/x1fold\.conf[[:space:]]*$'; then
  echo "include already present in $main_config"
else
  if [[ "$dry_run" -eq 1 ]]; then
    echo "would append to $main_config: $include_line"
  else
    cp -a "$main_config" "$main_config.bak-x1fold-sway"
    {
      printf '\n# x1fold (managed by scripts/install_x1fold_sway.sh)\n'
      printf '%s\n' "$include_line"
    } >>"$main_config"
    echo "appended include to $main_config (backup: $main_config.bak-x1fold-sway)"
  fi
fi

# --- reload -----------------------------------------------------------------

if [[ "$do_reload" -eq 1 && "$dry_run" -eq 0 ]]; then
  if command -v swaymsg >/dev/null 2>&1 && swaymsg -t get_version >/dev/null 2>&1; then
    swaymsg reload >/dev/null && echo "sway reloaded"
  else
    echo "note: no live Sway session found; reload skipped" >&2
  fi
elif [[ "$dry_run" -eq 0 ]]; then
  echo "note: run 'swaymsg reload' (or re-login) to pick this up"
fi

echo "installed: x1fold sway snippet"
