#!/usr/bin/env bash
# Repo source: x1fold/scripts/build_x1fold_sway.sh
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: build_x1fold_sway.sh [--workdir DIR] [--no-install] [--uninstall]

Builds a patched Sway with compositor-native halfblank support and installs it
to /usr/local/bin/sway, shadowing the distro package without replacing it.

Why this exists:
  The layer-shell fallback (x1fold_wl_blank) reserves the bottom region with an
  exclusive zone. Exclusive zones constrain tiled and floating windows, but
  fullscreen deliberately ignores them -- covering the whole output is the point
  of fullscreen. So a fullscreen video spans the full 2560px panel and half of it
  ends up under the keyboard. Only the compositor can make the bottom region
  genuinely not part of the desktop.

What gets built:
  - wlroots, patched to add WLR_OUTPUT_STATE_X1FOLD_ACTIVE_HEIGHT: shrinks the
    output's logical height while leaving the scanout mode alone.
  - sway, patched to add `output <name> x1fold_halfblank enable <px> | disable`,
    which drives that state. Restricted to the internal panel (eDP*).

  wlroots is built as a STATIC meson subproject, so the result is one
  self-contained binary. Nothing system-wide is replaced: the distro sway stays
  at /usr/bin/sway and the distro wlroots is untouched, so other wlroots-based
  programs are unaffected.

  x1fold-sway-session sets PATH=/usr/local/sbin:/usr/local/bin:/usr/bin before
  `exec sway`, so /usr/local/bin/sway wins on next login.

  x1fold_halfblank_ui.py in `auto` mode probes for the command and picks
  sway_crop when present, layer_shell when not -- no config change needed.

Options:
  --workdir DIR   Build tree (default: ~/build/x1fold-sway).
  --no-install    Build only; do not touch /usr/local/bin.
  --uninstall     Remove /usr/local/bin/sway and exit (reverts to the distro
                  package on next login).

Requires: meson, ninja, and the build deps for sway + wlroots.
EOF
}

SWAY_TAG=1.12
WLROOTS_TAG=0.20.2
workdir="${HOME}/build/x1fold-sway"
do_install=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir) workdir="$2"; shift 2 ;;
    --no-install) do_install=0; shift ;;
    --uninstall)
      if [[ -e /usr/local/bin/sway ]]; then
        sudo rm -f /usr/local/bin/sway
        echo "removed /usr/local/bin/sway; distro sway ($( /usr/bin/sway --version 2>/dev/null )) applies on next login"
      else
        echo "/usr/local/bin/sway not present; nothing to do"
      fi
      exit 0
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sway_patch="$repo_root/patches/sway-${SWAY_TAG}-x1fold-halfblank.patch"
wlroots_patch="$repo_root/patches/wlroots${WLROOTS_TAG%.*}-x1fold-active-height.patch"

for p in "$sway_patch" "$wlroots_patch"; do
  [[ -f "$p" ]] || { echo "missing patch: $p" >&2; exit 1; }
done

for t in meson ninja git; do
  command -v "$t" >/dev/null 2>&1 || { echo "missing build tool: $t" >&2; exit 1; }
done

mkdir -p "$workdir"
cd "$workdir"

fetch() { # <dir> <url> <tag>
  if [[ -d "$1/.git" ]]; then
    echo "== $1 already present, reusing"
  else
    echo "== cloning $1 @ $3"
    git clone -q --depth 1 --branch "$3" "$2" "$1"
  fi
}

fetch sway     https://github.com/swaywm/sway.git                       "v${SWAY_TAG}"
fetch wlroots  https://gitlab.freedesktop.org/wlroots/wlroots.git       "${WLROOTS_TAG}"

apply_once() { # <dir> <patch>
  if git -C "$1" apply --check --reverse "$2" >/dev/null 2>&1; then
    echo "== $1 already patched"
  else
    echo "== patching $1"
    git -C "$1" apply "$2"
  fi
}

apply_once sway    "$sway_patch"
apply_once wlroots "$wlroots_patch"

# wlroots as a static subproject -> one self-contained sway binary.
mkdir -p sway/subprojects
ln -sfn ../../wlroots sway/subprojects/wlroots

cd sway
if [[ -d build ]]; then
  meson setup build --reconfigure --prefix=/usr/local --force-fallback-for=wlroots \
    -Dwerror=false -Dwlroots:default_library=static
else
  meson setup build --prefix=/usr/local --force-fallback-for=wlroots \
    -Dwerror=false -Dwlroots:default_library=static
fi
ninja -C build

if ldd build/sway/sway 2>/dev/null | grep -qi wlroots; then
  echo "ERROR: sway still links a shared wlroots; the static subproject did not take." >&2
  exit 1
fi

echo
echo "built: $(pwd)/build/sway/sway"
./build/sway/sway --version

if [[ "$do_install" -eq 1 ]]; then
  sudo install -Dm0755 build/sway/sway /usr/local/bin/sway
  echo "installed: /usr/local/bin/sway"
  echo
  echo "Log out and back in to pick it up. Verify with:"
  echo "  sway --version                      # expect 'branch x1fold'"
  echo "  swaymsg output eDP-1 x1fold_halfblank enable 1240"
  echo "Roll back at any time with:  $0 --uninstall"
fi
