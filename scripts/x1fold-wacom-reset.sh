#!/bin/sh
set -eu

# Best-effort reset for the Wacom I2C HID device on the ThinkPad X1 Fold.
#
# Symptom: After suspend/resume (often triggered by fold/unfold), the kernel may
# log errors like:
#   i2c_hid_acpi i2c-WACF2200:00: failed to get a report from device: -121
# and touch/pen can become flaky until the device is re-bound.
#
# This script is intended to be called from a systemd-sleep hook on "post"
# (resume) first. If needed, we can also add a "pre" (suspend) unbind to reduce
# resume-time errors at the cost of being more invasive.

dev="${X1FOLD_WACOM_I2C_DEV:-i2c-WACF2200:00}"
driver="${X1FOLD_WACOM_I2C_DRIVER:-i2c_hid_acpi}"
sleep_s="${X1FOLD_WACOM_RESET_SLEEP_S:-0.3}"

dev_path="/sys/bus/i2c/devices/${dev}"
driver_path="/sys/bus/i2c/drivers/${driver}"

is_bound() {
  link="$(readlink -f "${dev_path}/driver" 2>/dev/null || true)"
  [ -n "$link" ] && [ "$(basename "$link" 2>/dev/null || true)" = "$driver" ]
}

if [ ! -e "$dev_path" ]; then
  exit 0
fi

if [ ! -d "$driver_path" ]; then
  exit 0
fi

# If it's bound, unbind first.
if is_bound; then
  echo "$dev" >"${driver_path}/unbind" 2>/dev/null || true

  # Give sysfs a moment to reflect the unbind.
  i=0
  while is_bound && [ "$i" -lt 20 ]; do
    i=$((i + 1))
    sleep 0.05
  done
fi

# Give the device a moment to settle.
sleep "$sleep_s" 2>/dev/null || sleep 0.3

# If it's not bound, bind it back.
if ! is_bound; then
  echo "$dev" >"${driver_path}/bind" 2>/dev/null || true
fi

if ! is_bound; then
  echo "x1fold-wacom-reset: warning: ${dev} not bound to ${driver} after reset" >&2
fi

exit 0
