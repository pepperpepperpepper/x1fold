#!/usr/bin/env bash
# Repo source: x1fold/scripts/install_x1fold_sleep.sh
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: install_x1fold_sleep.sh [--no-cmdline] [--dry-run]

Installs the X1 Fold sleep/lid policy into a live system:
  - /etc/systemd/logind.conf.d/10-x1fold-power.conf   (power key -> hibernate)
  - /etc/systemd/logind.conf.d/20-x1fold-lid-hibernate.conf (lid close -> hibernate)
  - /etc/UPower/UPower.conf.d/10-x1fold-battery-action.conf (critical thresholds)
  - /usr/local/bin/x1fold-stay-awake  (hold the lid-switch inhibitor)
  - kernel cmdline: button.lid_init_state=open  (systemd-boot entries)

All of it answers one question -- "when does this machine power itself down" --
so it lives in one installer even though it spans four mechanisms.

Why the cmdline argument is not optional:
  The ACPI button driver defaults to `lid_init_state=method`, which re-evaluates
  `_LID` on resume. On the X1 Fold that returns "closed". logind ignores lid
  input for HoldoffTimeoutSec (30s) after resume, then re-reads the switch state
  directly, sees "closed", and hibernates again -- ~23-26s after you opened it,
  with no `Lid closed.` in the journal. Lid-close hibernate is unusable without
  this. `open` only changes the synthetic state reported at driver init/resume;
  real fold/unfold notifications are unaffected.

Options:
  --no-cmdline   Only install the logind drop-ins; leave the bootloader alone.
  --dry-run      Show what would change, write nothing.

Notes:
  The suspend-time wake guard (/usr/local/bin/x1fold-wakeup-guard and the
  52-x1fold-wakeup-guard sleep hook) is installed by install_x1fold_halfblank.sh.

  The Sway-side lid handling (blank the panel on fold) is user scope, so it is
  a separate script: run scripts/install_x1fold_sway.sh as your desktop user.
EOF
}

do_cmdline=1
dry_run=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-cmdline) do_cmdline=0; shift ;;
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

run() {
  if [[ "$dry_run" -eq 1 ]]; then
    echo "would run: $*"
  else
    "$@"
  fi
}

# --- logind drop-ins -------------------------------------------------------

for f in 10-x1fold-power.conf 20-x1fold-lid-hibernate.conf; do
  src="$repo_root/systemd/logind.conf.d/$f"
  if [[ ! -f "$src" ]]; then
    echo "missing repo file: $src" >&2
    exit 1
  fi
  run install -Dm0644 "$src" "/etc/systemd/logind.conf.d/$f"
done

# --- UPower critical-battery thresholds ------------------------------------

# UPower ships /etc/UPower/UPower.conf.d/, so this is a drop-in rather than an
# in-place edit of UPower.conf. Filename must match UPower's own regex:
#   ^([0-9][0-9])-([a-zA-Z0-9-_])*\.conf$
upower_src="$repo_root/upower/UPower.conf.d/10-x1fold-battery-action.conf"
if [[ -f "$upower_src" ]]; then
  if [[ -d /etc/UPower/UPower.conf.d ]]; then
    run install -Dm0644 "$upower_src" \
      /etc/UPower/UPower.conf.d/10-x1fold-battery-action.conf
    if [[ "$dry_run" -eq 0 ]]; then
      systemctl try-restart upower.service 2>/dev/null || true
    fi
  else
    echo "warning: /etc/UPower/UPower.conf.d missing; skipping battery thresholds." >&2
    echo "         (UPower older than 1.90.3 has no drop-in support -- edit" >&2
    echo "         /etc/UPower/UPower.conf by hand instead.)" >&2
  fi
fi

# --- stay-awake helper ------------------------------------------------------

if [[ -f "$repo_root/scripts/x1fold-stay-awake" ]]; then
  run install -Dm0755 "$repo_root/scripts/x1fold-stay-awake" \
    /usr/local/bin/x1fold-stay-awake
fi

# --- kernel cmdline: button.lid_init_state=open ----------------------------

CMDLINE_ARG="button.lid_init_state=open"

patch_cmdline() {
  local esp entries found=0 patched=0 f

  esp=""
  if command -v bootctl >/dev/null 2>&1; then
    esp="$(bootctl --print-boot-path 2>/dev/null || bootctl --print-esp-path 2>/dev/null || true)"
  fi
  for candidate in "$esp" /boot /efi /boot/efi; do
    [[ -n "$candidate" ]] || continue
    if [[ -d "$candidate/loader/entries" ]]; then
      entries="$candidate/loader/entries"
      found=1
      break
    fi
  done

  if [[ "$found" -eq 0 ]]; then
    cat >&2 <<EOF
warning: no systemd-boot entries directory found.
         Add '$CMDLINE_ARG' to your kernel cmdline by hand (GRUB:
         GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub, then regenerate; UKI:
         your .cmdline file, then rebuild). Lid-close hibernate will re-sleep
         ~25s after every resume until you do.
EOF
    return 0
  fi

  shopt -s nullglob
  for f in "$entries"/*.conf; do
    if grep -q 'button\.lid_init_state=' "$f"; then
      echo "cmdline already set: $f"
      continue
    fi
    if ! grep -q '^options ' "$f"; then
      echo "no options line, skipping: $f"
      continue
    fi
    if [[ "$dry_run" -eq 1 ]]; then
      echo "would patch: $f (append $CMDLINE_ARG)"
    else
      cp -a "$f" "$f.bak-x1fold-sleep"
      sed -i "/^options /s/\$/ $CMDLINE_ARG/" "$f"
      echo "patched: $f"
    fi
    patched=$((patched + 1))
  done
  shopt -u nullglob

  if [[ "$patched" -gt 0 && "$dry_run" -eq 0 ]]; then
    echo "note: cmdline change takes effect on next boot (backups: *.bak-x1fold-sleep)"
  fi
}

if [[ "$do_cmdline" -eq 1 ]]; then
  patch_cmdline
fi

# Apply the lid_init_state now too: the ACPI button driver re-reads this
# parameter on every resume, so this fixes the current boot without rebooting.
if [[ -w /sys/module/button/parameters/lid_init_state || "$dry_run" -eq 1 ]]; then
  if [[ "$dry_run" -eq 1 ]]; then
    echo "would write: open > /sys/module/button/parameters/lid_init_state"
  else
    echo open >/sys/module/button/parameters/lid_init_state 2>/dev/null \
      && echo "runtime lid_init_state: $(cat /sys/module/button/parameters/lid_init_state)" \
      || echo "warning: could not set lid_init_state at runtime" >&2
  fi
fi

# --- reload ----------------------------------------------------------------

if [[ "$dry_run" -eq 0 ]]; then
  # logind is Type=notify-reload, so this reloads its config without dropping
  # sessions. (SIGHUP is the fallback for older systemd without CanReload.)
  systemctl reload systemd-logind.service 2>/dev/null \
    || systemctl kill -s HUP --kill-whom=main systemd-logind.service 2>/dev/null \
    || echo "note: reload systemd-logind (or reboot) to apply the lid policy" >&2
fi

echo "installed: x1fold sleep/lid policy"
