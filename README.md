## X1 Fold “halfblank” tooling (Linux)

This repository implements the Lenovo X1 Fold “halfblank” behavior on Linux: when the magnetic keyboard is docked, the system switches into a mode where only the top portion of the internal panel is used (bottom becomes visually blank/unused), and the digitizer mode is toggled to match.

The implementation is split into:

- **A system policy daemon** (`x1fold_halfblankd.py`) that decides whether we should be in `half` or `full` mode (based on dock state), applies the digitizer toggle, and writes a small state file.
- **A per-user session UI helper** (`x1fold_halfblank_ui.py`) that reads the state file and applies the *display geometry* part inside the logged-in desktop session (and can optionally do X11 auto-rotation + touchscreen remapping, plus Sway output rotation under Wayland).

This mirrors how the platform behaves under Windows: the “halfblank” effect is a combination of (1) a digitizer-side mode latch and (2) an OS-visible display/policy change.

### What it does

- Detects keyboard dock state (ACPI/EC-backed signal).
- Toggles the Wacom digitizer “half/full” latch (HID-over-I²C device, `056a:52ba`) using the most reliable available backend.
- Applies a “top-only usable area” policy:
  - **X11:** creates a black DOCK/STRUT window over the bottom region, sets `_NET_WM_STRUT_PARTIAL` so WMs reserve that space, and constrains the cursor from entering the blank region.
  - **Wayland (wlroots/Sway):**
    - **Preferred:** compositor-native “true shorter output” (bottom region is not part of the desktop: no pointer, no windows) via the patch files in `patches/` (this repo does **not** ship Sway/wlroots).
    - **Fallback:** layer-shell surface over the blank region + `exclusive_zone` reservation (`zwlr_layer_shell_v1` support required).
  - **TTY/DRM (optional):** can clip the primary plane using an atomic commit (requires DRM master) and optionally resize the active Linux VT to match via `x1fold_tty.py` (also forces fbcon rotation back to normal if the console ends up upside-down).
  - **Orientation (optional):** can auto-rotate based on iio-sensor-proxy:
    - X11: XRandR rotation + `xinput map-to-output`
    - Sway: `swaymsg output <output> transform <...>` (recommended policy: only when undocked/full)
    - TTY: fbcon rotate (`/sys/class/graphics/fbcon/rotate`) via `x1fold_tty_rotate.py` / `x1fold-tty-rotate.service` (recommended policy: only when undocked/full)

### Directory layout

- `tools/`
  - `x1fold_mode.py`: CLI to `set half|full` and `status` (digitizer + display backends).
  - `x1fold_dock.py`: reads/monitors dock state.
  - `x1fold_halfblankd.py`: system daemon that enforces the desired mode and writes `/run/x1fold-halfblank/state.json`.
  - `x1fold_halfblank_ui.py`: user-session helper that applies display geometry based on `state.json`.
  - `x1fold_tty.py`: TTY helper (drm_clip + tty resize/restore).
  - `x1fold_tty_rotate.py`: TTY auto-rotate helper (fbcon rotate via iio-sensor-proxy + dock policy).
  - `x1fold_x11_blank.c`: X11 blank/strut helper (also constrains/clamps the cursor to the active top region).
  - `drm_clip.c`: DRM plane-clip helper (console-safe path; requires DRM master).
- `scripts/`
  - `install_x1fold_halfblank.sh`: installs binaries + systemd units.
  - `x1fold-halfblank-ui-session.sh`: wrapper to run the UI helper inside the active Wayland session (exports `WAYLAND_DISPLAY`/`SWAYSOCK`).
  - `halfblank_switch.sh`: wrapper for `half|full|status`.
  - `halfblank_regression.sh`: on-device loop test with logs.
  - `halfblank_collect.sh`: fetch logs from the device.
- `systemd/`
  - `x1fold-halfblankd.service`: system daemon unit.
  - `x1fold-tty-rotate.service`: system daemon unit for fbcon auto-rotate.
  - `user/x1fold-halfblank-ui.service`: per-user UI helper unit.

### Install (live system)

Run as root:

```bash
x1fold/scripts/install_x1fold_halfblank.sh --enable-system
```

This will compile and install optional helpers if build deps are present:
- `x1fold_x11_blank` (needs `cc` + `pkg-config x11 xfixes`)
- `x1fold_wl_blank` (needs `cc` + `pkg-config wayland-client`)
- `drm_clip` (needs `cc` + `pkg-config libdrm`)

Enable the per-user UI helper (run as the desktop user):

```bash
systemctl --user enable --now x1fold-halfblank-ui.service
```

### Wayland “true shorter output” (optional, recommended for wlroots/Sway)

If you want the bottom region to be *completely absent* from the Wayland desktop (no pointer, no window placement, no fullscreen fighting), apply the compositor-native crop patches:
- `patches/wlroots0.19-x1fold-active-height.patch`
- `patches/sway-1.11-x1fold-halfblank.patch`

See: `docs/sway_wlroots_halfblank_patch_plan.md`.

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

### Power note (OLED)

This project is about **blanking** / “making unused pixels black” (and cropping the desktop) — not physically power-gating part of the panel.

Windows parity (why we believe this matches Lenovo’s behavior):
- `docs/ACPI_STATUS.md` shows the half/full toggle propagates into Wacom HID feature reports:
  - feature reports `0x03` and `0x04` flip a 2-byte field `00 00 ↔ 33 1a`, and
  - other feature reports also change substantially, consistent with **digitizer / active-area geometry** updates (not direct panel power).
- Windows ETW analysis (see `docs/WINDOWS_REPORT.md` and the notes in `docs/ACPI_STATUS.md`) did not show evidence of a dedicated “plane crop” transition, which is consistent with the folded region being blanked in compositor/GPU (black) based on the mode signal.

On OLED, black pixels still save power, so “blanked + cropped” delivers the same practical UX/power intent even if the panel isn’t physically half-disabled.
