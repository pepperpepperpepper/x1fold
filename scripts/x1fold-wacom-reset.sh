#!/bin/sh
set -eu

# Best-effort reset for the Wacom I2C HID device on the ThinkPad X1 Fold.
#
# Symptom: After suspend/resume (often triggered by fold/unfold), the kernel may
# log errors like:
#   i2c_hid_acpi i2c-WACF2200:00: failed to get a report from device: -121
# and touch/pen can become flaky until the device is re-bound.
#
# This script is intended to be called from a systemd-sleep hook.
#
# Start with "post" (resume) only, but if the device wedges frequently,
# switching to:
#   pre:  unbind
#   post: bind
# is more reliable at the cost of being more invasive.

dev="${X1FOLD_WACOM_I2C_DEV:-i2c-WACF2200:00}"
driver="${X1FOLD_WACOM_I2C_DRIVER:-i2c_hid_acpi}"
sleep_s="${X1FOLD_WACOM_RESET_SLEEP_S:-0.3}"
bind_wait_ticks="${X1FOLD_WACOM_BIND_WAIT_TICKS:-40}" # 40 * 50ms = 2s

# If a simple i2c_hid_acpi rebind doesn't bring the device back, prefer
# rebinding the i2c_designware platform controller before escalating further.
#
# This remains opt-in because recent kernels can still mis-handle controller
# re-enumeration on this platform and leave duplicate software-node state
# behind. Prefer a plain i2c_hid_acpi rebind by default.
controller_recover="${X1FOLD_WACOM_CONTROLLER_RECOVER_ON_FAIL:-0}"
controller_driver="${X1FOLD_WACOM_CONTROLLER_DRIVER:-i2c_designware}"

# PCI remove/rescan remains available as an opt-in last resort, but it is
# disabled by default because it has been observed to leave the controller in a
# worse state on newer kernels.
pci_recover="${X1FOLD_WACOM_PCI_RECOVER_ON_FAIL:-0}"
pci_bdf_override="${X1FOLD_WACOM_PCI_BDF:-}"
node_wait_ticks="${X1FOLD_WACOM_NODE_WAIT_TICKS:-60}" # 60 * 50ms = 3s

case "$bind_wait_ticks" in
  ''|*[!0-9]*)
    bind_wait_ticks=40
    ;;
esac

case "$node_wait_ticks" in
  ''|*[!0-9]*)
    node_wait_ticks=60
    ;;
esac

dev_path="/sys/bus/i2c/devices/${dev}"
driver_path="/sys/bus/i2c/drivers/${driver}"

action="${1:-reset}"
case "$action" in
  reset|unbind|bind|pre|post) ;;
  *)
    echo "usage: $(basename "$0") [reset|unbind|bind|pre|post]" >&2
    exit 2
    ;;
esac

do_unbind=0
do_bind=0
case "$action" in
  unbind|pre) do_unbind=1 ;;
  bind|post) do_bind=1 ;;
  reset) do_unbind=1; do_bind=1 ;;
esac

is_bound() {
  link="$(readlink -f "${dev_path}/driver" 2>/dev/null || true)"
  [ -n "$link" ] && [ "$(basename "$link" 2>/dev/null || true)" = "$driver" ]
}

wait_for_bind() {
  # Wait until the device is bound (or until timeout).
  i=0
  while ! is_bound && [ "$i" -lt "$bind_wait_ticks" ]; do
    i=$((i + 1))
    sleep 0.05
  done
}

wait_for_dev_path() {
  i=0
  while [ ! -e "$dev_path" ] && [ "$i" -lt "$bind_wait_ticks" ]; do
    i=$((i + 1))
    sleep 0.05
  done
}

wait_for_user_nodes() {
  p="$(readlink -f "$dev_path" 2>/dev/null || true)"
  [ -n "$p" ] || return 1
  i=0
  while [ "$i" -lt "$node_wait_ticks" ]; do
    if find "$p" -maxdepth 3 \( -name 'hidraw*' -o -name 'event*' \) | grep -q .; then
      return 0
    fi
    i=$((i + 1))
    sleep 0.05
  done
  return 1
}

find_platform_controller() {
  p="$(readlink -f "$dev_path" 2>/dev/null || true)"
  [ -n "$p" ] || return 1
  echo "$p" | awk -F'/' '{for (i=1; i<=NF; i++) if ($i ~ /^i2c_designware(\.[0-9]+)?$/) {print $i; exit}}'
}

controller_recover_if_needed() {
  [ "$controller_recover" = "1" ] || return 0
  [ "$do_bind" -eq 1 ] || return 0
  if is_bound && wait_for_user_nodes; then
    return 0
  fi

  controller="$(find_platform_controller 2>/dev/null || true)"
  [ -n "$controller" ] || return 0

  controller_path="/sys/bus/platform/devices/${controller}"
  controller_driver_path="/sys/bus/platform/drivers/${controller_driver}"
  [ -e "$controller_path" ] || return 0
  [ -d "$controller_driver_path" ] || return 0

  echo "x1fold-wacom-reset: ${dev} still not ready; rebinding platform controller ${controller}" >&2

  echo "$controller" >"${controller_driver_path}/unbind" 2>/dev/null || true
  sleep 0.2
  echo "$controller" >"${controller_driver_path}/bind" 2>/dev/null || true

  wait_for_dev_path

  if [ -e "$dev_path" ] && [ -d "$driver_path" ] && ! is_bound; then
    echo "$dev" >"${driver_path}/bind" 2>/dev/null || true
    wait_for_bind
  fi

  wait_for_user_nodes || true
}

find_pci_bdf() {
  # Derive PCI BDF from the sysfs path for the ACPI I2C device.
  #
  # Example:
  #   /sys/devices/pci0000:00/0000:00:15.1/i2c_designware.1/i2c-1/i2c-WACF2200:00
  p="$(readlink -f "$dev_path" 2>/dev/null || true)"
  [ -n "$p" ] || return 1
  echo "$p" | awk -F'/' '{for (i=1; i<=NF; i++) if ($i ~ /^0000:/) {print $i; exit}}'
}

pci_recover_if_needed() {
  [ "$pci_recover" = "1" ] || return 0
  [ "$do_bind" -eq 1 ] || return 0
  is_bound && return 0

  pci_bdf="$pci_bdf_override"
  if [ -z "$pci_bdf" ]; then
    pci_bdf="$(find_pci_bdf 2>/dev/null || true)"
  fi
  [ -n "$pci_bdf" ] || return 0

  pci_path="/sys/bus/pci/devices/${pci_bdf}"
  [ -e "${pci_path}/remove" ] || return 0

  echo "x1fold-wacom-reset: ${dev} still unbound; resetting PCI ${pci_bdf} (I2C controller)" >&2

  # Remove + rescan is the most reliable "controller reset" we have from userspace.
  echo 1 >"${pci_path}/remove" 2>/dev/null || true
  sleep 0.2
  echo 1 >/sys/bus/pci/rescan 2>/dev/null || true

  # Give udev/kernel a moment to re-enumerate and bind i2c_hid_acpi.
  i=0
  while [ "$i" -lt 60 ]; do
    if is_bound; then
      return 0
    fi
    i=$((i + 1))
    sleep 0.1
  done

  # If the device came back but still isn't bound, try one more explicit bind.
  if [ -e "$dev_path" ] && [ -d "$driver_path" ] && ! is_bound; then
    echo "$dev" >"${driver_path}/bind" 2>/dev/null || true
    wait_for_bind
  fi
}

if [ ! -e "$dev_path" ]; then
  exit 0
fi

if [ ! -d "$driver_path" ]; then
  exit 0
fi

if [ "$do_unbind" -eq 1 ]; then
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
fi

if [ "$do_bind" -eq 1 ]; then
  # Give the device a moment to settle.
  sleep "$sleep_s" 2>/dev/null || sleep 0.3

  # If it's not bound, bind it back.
  if ! is_bound; then
    echo "$dev" >"${driver_path}/bind" 2>/dev/null || true
    wait_for_bind
  fi
fi

controller_recover_if_needed
pci_recover_if_needed

if ! is_bound; then
  echo "x1fold-wacom-reset: warning: ${dev} not bound to ${driver} after reset" >&2
elif ! wait_for_user_nodes; then
  echo "x1fold-wacom-reset: warning: ${dev} bound but hidraw/input nodes did not appear in time" >&2
fi

exit 0
