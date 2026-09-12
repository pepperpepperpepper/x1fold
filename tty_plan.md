# TTY auto-rotation plan (fbcon) for X1 Fold

Goal: add **bare VT/TTY rotation** that behaves like the existing graphical auto-rotate logic (X11/Wayland),
while respecting the dock/halfblank policy:

- **Docked / halfblank**: force orientation to **normal** (laptop-like).
- **Undocked / full**: auto-rotate based on **device orientation**.

## Constraints / facts

- KMS plane rotation on this i915 setup only supports `rotate-0`/`rotate-180`; no 90/270. So use **fbcon** rotation.
- fbcon rotation control:
  - `/sys/class/graphics/fbcon/rotate`
  - values: `0=normal`, `1=90°`, `2=180°`, `3=270°`
- Halfblank-on-TTY uses `drm_clip` (panel coordinates) + tty resize via `x1fold_tty.py`. fbcon rotate only changes how
  the console is drawn; it does **not** change the scanout geometry. (So clip direction may feel “wrong” for 90/270.)

## Implementation plan

### 1) New helper: `x1fold/tools/x1fold_tty_rotate.py` (system/root)

Responsibilities:
- Poll `/run/x1fold-halfblank/state.json` (written by `x1fold_halfblankd.py`) to learn `desired: half|full`.
- Poll orientation via **iio-sensor-proxy**:
  - `busctl --system get-property net.hadess.SensorProxy /net/hadess/SensorProxy net.hadess.SensorProxy AccelerometerOrientation`
  - optional: `ClaimAccelerometer` at startup (best-effort), like the X11 helper.
- Apply fbcon rotation by writing an integer to `/sys/class/graphics/fbcon/rotate`.

Behavior:
- If `desired == "half"` (keyboard docked): force `rotate=0` (normal).
- If `desired == "full"`: map orientation → fbcon rotation and apply **only on change**:
  - debounce sensor churn (`--stable-s 0.8`)
  - rate-limit changes (`--min-apply-s 1.0`)
  - power-friendly poll (`--interval-s 1.5`)
- Log JSON lines (similar to the other tools) for journald visibility.

CLI sketch:
- `--state-file` default `/run/x1fold-halfblank/state.json`
- `--interval-s` default `1.5`
- `--stable-s` default `0.8`
- `--min-apply-s` default `1.0`
- `--force-normal-when-half` (default on)
- `--once` for debugging
- (later) `--fallback-iio` to support raw `/sys/bus/iio/devices/*/in_accel_*_raw` if sensor-proxy is missing

### 2) Orientation → fbcon mapping (calibrate once)

We already have a working manual test script (`x1fold_fbcon_rotate_test.sh`), but we need to confirm which fbcon
value corresponds to “left/right” for this device/kernel.

Approach:
- Add a small calibration note (or mode) to `x1fold_tty_rotate.py`:
  - “Set rotate=1, confirm which direction is ‘left-up’ on this system”
  - Use rollback safety (reuse `x1fold_fbcon_rotate.sh set … --rollback 30`)
- Once confirmed, bake the mapping:
  - `normal -> 0`
  - `bottom-up -> 2`
  - `left-up/right-up -> 1/3` (exact assignment depends on observed behavior)

### 3) systemd unit: `x1fold/systemd/x1fold-tty-rotate.service`

System service (needs root to write fbcon sysfs):
- `After=` / `Wants=` `x1fold-halfblankd.service`
- `ConditionPathExists=/sys/class/graphics/fbcon/rotate`
- `ExecStart=/usr/local/bin/x1fold_tty_rotate.py --state-file /run/x1fold-halfblank/state.json --interval-s 1.5 --stable-s 0.8 --min-apply-s 1.0 --force-normal-when-half`
- `Restart=on-failure`

### 4) Installer integration

Update `x1fold/scripts/install_x1fold_halfblank.sh` to:
- install `x1fold_tty_rotate.py` into `/usr/local/bin/`
- install `x1fold-tty-rotate.service` into `/etc/systemd/system/`
- add optional flag `--enable-tty-rotate` to enable+start it (like `--enable-system`, `--enable-ui`)

## Testing checklist (on-device)

- Manual: from a real VT, verify writing `0..3` to `/sys/class/graphics/fbcon/rotate` works and restores (already OK).
- Service sanity:
  - `systemctl status x1fold-tty-rotate.service`
  - `journalctl -u x1fold-tty-rotate.service -f`
- Behavior:
  - Undocked/full: rotate follows device orientation changes.
  - Docked/half: rotation snaps to normal and stays there.
- Interaction with halfblank:
  - Confirm `drm_clip` halfblank remains correct in default (normal) orientation.
  - Decide whether to *disable 90/270 in full mode* when tty halfblank is active, or accept that clip direction is odd.

