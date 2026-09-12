# TTY rotation (fbcon) on X1 Fold

This note captures what we learned about rotating the **Linux text console** (bare VT/TTY) on the ThinkPad X1 Fold.

## Summary / findings

- **DRM/KMS plane rotation is limited** on this platform: the active primary plane only advertises `rotate-0` and `rotate-180` (no 90/270) when inspected via `modetest -M i915 -p`.
- **fbcon rotation works** via the kernel console sysfs knob:
  - `/sys/class/graphics/fbcon/rotate`
  - Values: `0=normal`, `1=90°`, `2=180°`, `3=270°`
- **On-device test result:** `x1fold_fbcon_rotate_test.sh` successfully cycled rotations and restored cleanly (user report: “worked perfectly”, with the expected “text dancing” during redraw).

## Why fbcon rotation matters

Rotating a *TTY* is fundamentally different from rotating a compositor-managed display:
- A TTY uses the kernel console (fbcon/DRM fbdev emulation).
- If the KMS plane can’t do 90/270, **fbcon rotate** is the pragmatic way to get portrait/landscape in a text VT.

## Scripts added

These are intended to be run **from a real VT** (e.g. `Ctrl`+`Alt`+`F2`).

### `x1fold_fbcon_rotate.sh`

- `x1fold_fbcon_rotate.sh status` → prints current rotation.
- `x1fold_fbcon_rotate.sh set <0|1|2|3> --rollback 30` → sets rotation and restores prior value after 30s.
- `x1fold_fbcon_rotate.sh cancel` → cancels a pending rollback started by this script.

### `x1fold_fbcon_rotate_test.sh`

Safe “does this work?” loop with rollback:

```bash
sudo x1fold_fbcon_rotate_test.sh --rollback 30 --step 2
```

If the console becomes unusable, just **wait for rollback**.

## Orientation detection (TTY)

Orientation detection does **not** require X11/Wayland:
- If available, `iio-sensor-proxy` provides a high-level `AccelerometerOrientation` over **system D‑Bus**.
- Even without it, accelerometer raw data is available under `/sys/bus/iio/devices/iio:device*/in_accel_{x,y,z}_raw` and can be mapped to an orientation by looking at the dominant gravity axis.

At the time of inspection on this system:
- `iio-sensor-proxy.service` was not active/activatable.
- IIO accelerometer devices existed (e.g. `name=accel_3d` with `in_accel_*_raw`).

## Integration considerations (halfblank + rotated TTY)

- fbcon rotation **does not change** the DRM mode/scanout geometry; it changes how the console is drawn.
- If we keep using `drm_clip` for “halfblank” on TTY, clipping stays in **panel coordinates** (e.g. “top 1240 pixels” of the unrotated 2024×2560 mode).
  - If you rotate the console 90/270, the “active region” you want may need to become “left/right” instead of “top/bottom”, which would require a different clip strategy (or a rotated KMS path, if available).

## Quick diagnostics

```bash
cat /sys/class/graphics/fbcon/rotate
ls -l /sys/class/graphics/fbcon/rotate /sys/class/graphics/fbcon/rotate_all
modetest -M i915 -p | rg -n 'Planes:|rotation:'
```

