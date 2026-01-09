## X1 Fold “halfblank” tooling (Linux)

This repository implements the Lenovo X1 Fold “halfblank” behavior on Linux: when the magnetic keyboard is docked, the system switches into a mode where only the top portion of the internal panel is used (bottom becomes visually blank/unused), and the digitizer mode is toggled to match.

The implementation is split into:

- **A system policy daemon** (`x1fold_halfblankd.py`) that decides whether we should be in `half` or `full` mode (based on dock state), applies the digitizer toggle, and writes a small state file.
- **A per-user session UI helper** (`x1fold_halfblank_ui.py`) that reads the state file and applies the *display geometry* part inside the logged-in desktop session.

This mirrors how the platform behaves under Windows: the “halfblank” effect is a combination of (1) a digitizer-side mode latch and (2) an OS-visible display/policy change.

### What it does

- Detects keyboard dock state (ACPI/EC-backed signal).
- Toggles the Wacom digitizer “half/full” latch (HID-over-I²C device, `056a:52ba`) using the most reliable available backend.
- Applies a “top-only usable area” policy:
  - **X11:** creates a black DOCK/STRUT window over the bottom region, sets `_NET_WM_STRUT_PARTIAL` so WMs reserve that space, and constrains the cursor from entering the blank region.
  - **TTY/DRM (optional):** can clip the primary plane using an atomic commit (requires DRM master).
  - **Orientation (optional):** under X11, can auto-rotate based on iio-sensor-proxy and remap touchscreen coordinates via `xinput map-to-output` (useful when the detachable display is rotated).

### Directory layout

- `tools/`
  - `x1fold_mode.py`: CLI to `set half|full` and `status` (digitizer + display backends).
  - `x1fold_dock.py`: reads/monitors dock state.
  - `x1fold_halfblankd.py`: system daemon that enforces the desired mode and writes `/run/x1fold-halfblank/state.json`.
  - `x1fold_halfblank_ui.py`: user-session helper that applies display geometry based on `state.json`.
  - `x1fold_x11_blank.c`: X11 blank/strut helper (also constrains/clamps the cursor to the active top region).
  - `drm_clip.c`: DRM plane-clip helper (console-safe path; requires DRM master).
- `scripts/`
  - `install_x1fold_halfblank.sh`: installs binaries + systemd units.
  - `halfblank_switch.sh`: wrapper for `half|full|status`.
  - `halfblank_regression.sh`: on-device loop test with logs.
  - `halfblank_collect.sh`: fetch logs from the device.
- `systemd/`
  - `x1fold-halfblankd.service`: system daemon unit.
  - `user/x1fold-halfblank-ui.service`: per-user UI helper unit.

### Install (live system)

Run as root:

```bash
x1fold/scripts/install_x1fold_halfblank.sh --enable-system
```

Enable the per-user UI helper (run as the desktop user):

```bash
systemctl --user enable --now x1fold-halfblank-ui.service
```

### Use

Manual switch:

```bash
sudo halfblank_switch.sh half
sudo halfblank_switch.sh full
sudo halfblank_switch.sh status
```

Regression loop (on-device, as root):

```bash
halfblank_regression.sh -n 10
```

### Documentation

- `docs/ACPI_STATUS.md`: ACPI namespace notes and signal discovery.
- `docs/linux_halfblank_plan.md`: design/architecture (including Wayland direction).
- `docs/WINDOWS_REPORT.md`: Windows-side telemetry relevant to the behavior.
- `sensors.md`: summary of the key signals (dock, digitizer latch, geometry).
