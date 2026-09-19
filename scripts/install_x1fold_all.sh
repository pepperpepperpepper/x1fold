#!/usr/bin/env bash
# Repo source: x1fold/scripts/install_x1fold_all.sh
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: install_x1fold_all.sh [--webcam] [--no-enable] [--dry-run]

One command to bring up an X1 Fold from this repo. Runs the per-subsystem
installers in order and then prints the steps that cannot be done for you.

Installed by default:
  1. halfblank tooling + systemd units   (install_x1fold_halfblank.sh)
  2. keyboard Fn/Ctrl swap               (install_x1fold_fnctl.sh)
  3. sleep / lid / battery policy        (install_x1fold_sleep.sh)

Not installed by default:
  - webcam (IPU6 / OVTI5675). Builds a DKMS module and blacklists ipu6 bits,
    so it is opt-in: pass --webcam.
  - Sway snippet. User scope, cannot run as root: see the follow-ups printed
    at the end.

Options:
  --webcam      Also run install_x1fold_webcam.sh.
  --no-enable   Do not pass --enable-system to the halfblank installer.
  --dry-run     Print what would run, change nothing.
EOF
}

want_webcam=0
enable_system=1
dry_run=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --webcam) want_webcam=1; shift ;;
    --no-enable) enable_system=0; shift ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "$dry_run" -eq 0 && "${EUID:-$(id -u)}" -ne 0 ]]; then
  exec sudo -- "$0" "$@"
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The user this machine is actually for -- used only for the follow-up hints.
target_user="${SUDO_USER:-${USER:-}}"

step() {
  local label="$1"; shift
  echo
  echo "=== $label"
  if [[ "$dry_run" -eq 1 ]]; then
    echo "would run: $*"
  else
    "$@"
  fi
}

halfblank_args=()
[[ "$enable_system" -eq 1 ]] && halfblank_args+=(--enable-system)

step "halfblank tooling" \
  "$repo_root/scripts/install_x1fold_halfblank.sh" "${halfblank_args[@]}"

step "keyboard Fn/Ctrl swap" \
  "$repo_root/scripts/install_x1fold_fnctl.sh"

step "sleep / lid / battery policy" \
  "$repo_root/scripts/install_x1fold_sleep.sh"

if [[ "$want_webcam" -eq 1 ]]; then
  step "webcam (IPU6 / OVTI5675)" \
    "$repo_root/scripts/install_x1fold_webcam.sh"
fi

# --- follow-ups -------------------------------------------------------------

cat <<EOF

=== done. Remaining steps (these cannot be done from here):

1. Sway snippet -- blanks the panel when the fold closes. User scope, so it
   must run as your desktop user, not under sudo:

     ${target_user:+sudo -u $target_user }$repo_root/scripts/install_x1fold_sway.sh --reload

2. Per-user UI helper:

     systemctl --user enable --now x1fold-halfblank-ui.service

   (or, for every user:  systemctl --global enable x1fold-halfblank-ui.service)

3. REBOOT. install_x1fold_sleep.sh added button.lid_init_state=open to the
   kernel cmdline, and that only takes effect on the next boot. It was also
   applied at runtime, so the current boot is already correct -- but a fresh
   machine is not fixed until it has rebooted once. Verify afterwards:

     grep -o 'button.lid_init_state=[a-z]*' /proc/cmdline

   Without it, closing the lid hibernates and then the machine hibernates
   itself again ~25s after every resume. See README for why.
EOF
