#!/bin/sh
set -eu

# Prevent spurious wakeups on the ThinkPad X1 Fold while suspended.
#
# Symptom:
#   System suspends (s2idle) correctly, but tilting/moving the machine wakes it
#   up again (likely from accelerometer / Intel HID events).
#
# Fix:
#   Disable wakeup on the Intel HID events platform device (INTC1070:00) before
#   entering sleep. This does *not* disable the device while awake; it only
#   prevents it from waking the system.
#
# Scope:
# - This matters for s2idle only. Lid close is policy-bound to *hibernate* (see
#   systemd/logind.conf.d/20-x1fold-lid-hibernate.conf), and in S4 the platform
#   is powered off, so INTC1070 wakeup is irrelevant there. The guard still
#   covers non-lid suspends (idle, `systemctl suspend`).
# - The guard is one-way by design: `post` re-disables rather than restoring,
#   in case the driver re-enabled wakeup during resume. INTC1070 wake therefore
#   stays disabled for the rest of the boot once the machine has slept once.
#   Run `... enable` to put it back, `... status` to check.
#
# Notes:
# - Keep this conservative: we only touch INTC1070 by default. If you also want
#   to disable wake from other devices, add their `.../power/wakeup` sysfs files
#   via X1FOLD_WAKEUP_GUARD_EXTRA (space-separated).

default_paths="/sys/bus/platform/devices/INTC1070:00/power/wakeup"
extra_paths="${X1FOLD_WAKEUP_GUARD_EXTRA:-}"

log() {
  if command -v logger >/dev/null 2>&1; then
    logger -t x1fold-wakeup-guard -- "$@"
  fi
}

set_wakeup() {
  path="$1"
  val="$2"
  if [ -e "$path" ]; then
    echo "$val" >"$path" 2>/dev/null || true
  fi
}

dump_wakeup_irq() {
  irq="$(cat /sys/power/pm_wakeup_irq 2>/dev/null || true)"
  if [ -z "$irq" ]; then
    return 0
  fi
  name="$(cat "/sys/kernel/irq/${irq}/name" 2>/dev/null || true)"
  actions="$(cat "/sys/kernel/irq/${irq}/actions" 2>/dev/null || true)"
  log "pm_wakeup_irq=${irq} name=${name:-?} actions=${actions:-?}"
}

action="${1:-pre}"
case "$action" in
  pre|disable)
    for p in $default_paths $extra_paths; do
      set_wakeup "$p" disabled
    done
    ;;
  post)
    # Log wake reason for debugging (best-effort), then re-apply the wake guard
    # in case the driver re-enabled wakeup during resume.
    dump_wakeup_irq || true
    for p in $default_paths $extra_paths; do
      set_wakeup "$p" disabled
    done
    ;;
  enable)
    for p in $default_paths $extra_paths; do
      set_wakeup "$p" enabled
    done
    ;;
  status)
    for p in $default_paths $extra_paths; do
      if [ -e "$p" ]; then
        printf '%s=%s\n' "$p" "$(cat "$p" 2>/dev/null || echo '?')"
      else
        printf '%s=(missing)\n' "$p"
      fi
    done
    ;;
  *)
    echo "usage: $(basename "$0") [pre|post|disable|enable|status]" >&2
    exit 2
    ;;
esac

exit 0
