# X1 Fold sensors / signals (halfblank)

This document lists the *signals we can observe* (and the minimal ways to read them) that are relevant to reproducing Lenovo’s “halfblank when keyboard is docked” behavior on Linux.

## 1) Keyboard dock (magnet) state

Primary truth (as seen in our ACPI analysis):

- `\_SB.PC00.LPCB.EC.CMMD` **bit 7**: `1 = docked`, `0 = undocked`
- `\_SB.DEVD.GDST` appears to be a wrapper that returns the same dock bit.

### Read via ACPI (requires `acpi_call`)

```bash
modprobe acpi_call
echo '\\_SB.DEVD.GDST' > /proc/acpi/call
cat /proc/acpi/call

echo '\\_SB.PC00.LPCB.EC.CMMD' > /proc/acpi/call
cat /proc/acpi/call
```

### Read via EC debugfs (if enabled)

If the kernel exposes the EC in debugfs, you can read raw EC bytes and interpret the `CMMD` field. This is more sustainable than `acpi_call` long-term, but depends on kernel config/debugfs availability.

## 2) Digitizer “half/full” mode latch (Wacom over I²C)

We have a stable “half/full” latch in the Wacom HID-over-I²C device:

- Wacom device: `WACF2200:00` (HID VID:PID `056a:52ba`)
- Linux side: `/dev/hidraw*` device(s), plus I²C slave `0x0A` on `/dev/i2c-1`

### Read via `x1fold_mode.py` (recommended)

```bash
sudo x1fold_mode.py status
```

On b045 we treat the **I²C query tail** as the ground truth:

- Query write: `04 00 34 02 05 00`
- Query read tail: bytes `[0x10..0x11]`
  - `33 1a` → `half`
  - `00 00` → `full`

For debugging, the HID feature report `0x03` also encodes the state in bytes `[10..15]`:

- `half`: `9c 18 2c 28 33 1a`
- `full`: `00 00 00 00 00 00`

## 3) Display “halfblank” geometry state (software policy)

This is not a hardware panel-rail cut on our units; it’s an *OS-visible display composition/geometry change*.

Linux implementations:

- X11: `x1fold_x11_blank` draws a black region + sets `_NET_WM_STRUT_PARTIAL` and installs an XFixes pointer barrier. It also clamps the cursor back into the top region to avoid “cursor stuck in blank” UX.
- TTY/DRM: `drm_clip` can clip the primary plane to the top region (requires DRM master).

Quick check under X11:

```bash
DISPLAY=:1 xrandr --listmonitors
```

## References

- `docs/ACPI_STATUS.md` (signal discovery + validation notes)
- `docs/linux_halfblank_plan.md` (overall Linux architecture / policy)
