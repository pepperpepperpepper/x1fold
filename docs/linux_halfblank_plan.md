# Linux Plan: Full-Height ↔ Half-Blank Mode Switch

## Current evidence (source of truth)
- Windows HALFBLANK/UNBLANK is **not** a simple iGPU PPS transition: Windows `PP_STATUS/PP_CONTROL` snapshots (BAR0 + `0xC7200/0xC7204`) stayed constant across the action (see `docs/ACPI_STATUS.md` 2026‑01‑07).
- The Lenovo “intended trigger” for HALFBLANK is the **magnetic keyboard dock state**, exposed in ACPI as:
  - `\_SB.PC00.LPCB.EC.CMMD` bit 7 (`1` docked / `0` undocked), and
  - `\_SB.DEVD.GDST` (wrapper that returns the dock bit). See `docs/ACPI_STATUS.md` 2026‑01‑08.
- The stable, reproducible control primitive we *do* have is the **Wacom HID-over-I²C device at slave `0x0A`** on `I2C1` (`00:15.1`):
  - Windows ETW: `LenovoModeSwitcher.exe` issues a `len=1034` write whose only stable delta for HALFBLANK is bytes at offsets `0x0c..0x11` = `9c 18 2c 28 33 1a` vs zeros for UNBLANK.
  - Linux: we can replay the same `len=1034` payload on `i2c-1` and observe a query-state flip (`0x10..0x11` becomes `33 1a`) and HID feature report changes (see `docs/ACPI_STATUS.md` 2026‑01‑02/03/07).
- Windows additionally applies an **OS-visible display geometry change** (virtual screen height becomes ~`2024x1240`), and we can force full height immediately with `ChangeDisplaySettingsEx` even while the keyboard is attached (see `docs/WINDOWS_REPORT.md` 2026‑01‑07). That implies HALFBLANK is at least partly “software policy + display pipeline config”, not a hard rail cut.

## Goal
Provide a **reliable, installable Linux switch**:
- `full`  → usable desktop/content across the whole panel.
- `half`  → usable desktop/content only in the top region (bottom region “blank”/unused), with input mapping that matches.

## Approach (two coupled primitives)
We treat HALFBLANK as **(A) digitizer mode + (B) display composition geometry**.

### A) Digitizer mode (required)
Preferred interface: **hidraw feature report** when it works, but on b045 we treat the
Windows-derived **I²C query tail** as the ground truth because the hidraw bytes can
drift into “unknown” values over time.

Implementation:
1. Discover the correct hidraw node for **`WACF2200&COL02`** (USB VID:PID `056a:52ba`).
2. Read feature report `0x03` (256B), patch bytes `[10..15]`:
   - `half`: `9c 18 2c 28 33 1a`
   - `full`: `00 00 00 00 00 00`
3. Write it back via `HIDIOCSFEATURE`, then re-read to confirm.

Fallback (already proven): raw I²C replay using the known `len=1034` payloads, then
confirm via the Windows-derived query (`w6` + `r1029`):
- Query write: `04 00 34 02 05 00`
- Query read tail: bytes `[0x10..0x11]` should be `33 1a` for `half`, `00 00` for `full`.

### B) Display geometry (required for “usable desktop” semantics)
We need Linux to behave like Windows: “desktop height becomes ~1240” or at least “bottom region becomes black/unusable”.

Implementation options (pick the first that works on b0xx):
1. **DRM atomic plane clip (console-safe):** keep mode at `2024x2560` but set the primary plane’s CRTC dst rect to `H=1240` (no scaling) so nothing covers the bottom region. This matches the DxgKrnl “clip bottom=1240” observation.
2. **Actual modeset + no-scaling (desktop-friendly):** if i915 accepts a `2024x1240` mode without scaling, set it and pin it to the “top” (may require a panning/viewport trick).
3. **X11 integration (works today on b045):** create a **black DOCK/STRUT window** that covers the bottom region.
   - half: run `x1fold_x11_blank --side bottom --active-size 1240` (creates `_NET_WM_WINDOW_TYPE_DOCK`, sets `_NET_WM_STRUT_PARTIAL` so the WM treats the blank region as reserved, and installs an XFixes pointer barrier so the cursor can’t enter the blank region)
   - full: stop/kill the helper
   - note: `x1fold_x11_blank` also clamps (warps) the cursor back into the active region if anything places it into the blank area, to avoid “cursor stuck in the blank part” UX.
   This doesn’t require DRM master (Xorg remains DRM master), yet produces a real “bottom half goes black” visual effect and a WM-usable work area that matches Windows semantics.
   - orientation: when the detachable display is rotated “on its side”, rotate the output (and remap touchscreen coordinates) based on iio-sensor-proxy. This is separate from halfblank and should generally be active when undocked/full.
     - note (2026‑01‑09): if rotation feels “sluggish” with several seconds of black screen, check `journalctl _SYSTEMD_USER_UNIT=x1fold-halfblank-ui.service` for repeated `x11_rotated` events (e.g., “from_rotation=normal → rotation=left” looping). That symptom was caused by a bug parsing `xrandr --query` (reading the capability list `(normal left …)` instead of the current rotation token); ensure `/usr/local/bin/x1fold_halfblank_ui.py` matches the repo version.
4. **Wayland (wlroots) integration (implemented):** create a layer-shell surface over the blank region and set `exclusive_zone` so normal windows avoid it (`x1fold_wl_blank`, requires compositor support for `zwlr_layer_shell_v1`).

## Deliverables (sustainable + installable)
1. `x1fold/tools/x1fold_mode.py`
   - Subcommands: `set half|full`, `status`.
   - Backends:
     - `--digitizer=hidraw` (default) with `--digitizer=i2c` fallback.
     - `--display=x11|drm|none` (`auto` chooses X11 when Xorg is running; DRM clip is TTY-only).
   - Produces a single JSON status blob: **top-level mode from I²C query**, plus hidraw bytes for debugging.
2. `x1fold/tools/drm_clip.c` (or small Python+ctypes if we keep it tight)
   - Applies the “clip to top N pixels” atomic commit on the eDP CRTC.
3. `x1fold/tools/x1fold_x11_blank.c`
   - X11-only: creates a black DOCK/STRUT window to reserve/blank the bottom region while Xorg owns DRM master.
4. `x1fold/scripts/halfblank_switch.sh` (thin wrapper)
   - Detects environment (TTY vs Wayland vs X11) and calls `x1fold/tools/x1fold_mode.py`.
5. `x1fold/tools/x1fold_dock.py` + `x1fold/tools/x1fold_halfblankd.py`
   - `x1fold_dock.py` reads/monitors the dock signal via `ec_sys` (`/sys/kernel/debug/ec/ec0/io`) or `acpi_call` when present.
   - `x1fold_halfblankd.py` applies `half`/`full` on dock transitions and **enforces the desired mode** periodically
     (because the Wacom state can drift back to `full` on this unit).
6. Regression harness:
   - `x1fold/scripts/halfblank_regression.sh` (on-host loop + logging)
   - `x1fold/scripts/halfblank_collect.sh` (fetch logs via `funcs`)
   - Opt-in pytest: `userland_tests/test_x1fold_halfblank_regression.py` (`X1FOLD_HALFBLANK_REGRESSION=1`)
7. **Optional automation** (separate phase):
   - A “dock driver” source (kernel or userspace) that turns Lenovo’s ACPI dock signal into a stable Linux event.
   - `x1fold/systemd/x1fold-halfblankd.service` that listens for dock attach/detach and calls the switch.

## Dock-trigger design (what makes this “driver-like” on Linux)
We want to stop depending on `acpi_call` and polling. Best-practice layering:

1. **Kernel driver (preferred, sustainable):**
   - Implement an ACPI driver for `LEN009E` (`\_SB.DEVD`) that:
     - reads `GDST`/`CMMD` to get dock state,
     - registers an **input switch** (`SW_DOCK`) and/or a sysfs attribute (`docked`),
     - handles `Notify(DEVD, 1)` from `EC._Q2E` to emit dock-state changes without polling.
   - Userland then gets a normal Linux event stream (udev/input) and can attach policy.

2. **Userspace fallback (good for bring-up / live images):**
   - Poll `\_SB.DEVD.GDST` (or `EC.CMMD`) via `/proc/acpi/call` and trigger the switch only on transitions.
   - This is acceptable for prototyping but not ideal long-term (requires `acpi_call`, root, polling).

## Policy daemon (where the “Lenovo behavior” actually lives)
Even with a kernel dock signal, switching still needs userspace because it touches HID and display config.

- `x1fold-halfblankd` responsibilities:
  - Debounce dock transitions (avoid flapping when magnets hover).
  - Apply **digitizer mode** (`x1fold_mode.py set half|full`).
  - Apply **display geometry** (DRM clip or compositor backend).
  - Detect and correct **mode drift** while docked (I²C query tail flips back to `00 00`).
  - Provide an override (“force full”) and status logging for debugging.

## Concrete validation (what “works” means)
- `x1fold_mode.py set half`:
  - **I²C query tail** `0x10..0x11 == 33 1a` (primary truth on b045)
  - hidraw bytes `[10..15] == 9c 18 2c 28 33 1a` when stable (debug only; may show `unknown`)
  - display shows only the top region is active/used (either by a KMS clip or by a real modeset)
- `x1fold_mode.py set full` restores both.
- Regression: loop 20× without wedging i915 (log `dmesg` and state readback each cycle).

## Open questions (track as we implement)
- Is the target “half height” exactly `1240` on Linux as well, or does it need a runtime-calibrated value from the Wacom reports (preferred)?
- Is the most stable dock event stream `Notify(DEVD, 1)` (ACPI driver) or a Lenovo hotkey code via `HKEY.MHKQ(0x60C0)` (acpid/input), on the kernels we ship?
