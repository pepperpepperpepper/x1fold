# Sustainable Linux “Halfblank” Package Plan (X1 Fold)

## What we’re packaging (mental model)
“Halfblank” on the X1 Fold is best treated as **policy**, not panel power:
- **Digitizer mode** changes (Wacom HID-over-I²C @ `0x0A` on `i2c-1`) so touch/pen mapping matches the “top-only” desktop.
- **Display geometry / blanking** changes so only the top region is usable *and the bottom region is actually black*:
  - X11: black DOCK/STRUT window (`x1fold_x11_blank`) so it works while Xorg owns DRM master.
  - Wayland: compositor-native crop (preferred; wlroots/Sway patch) or layer-shell overlay client (fallback) when supported.
  - DRM clip: console-only fallback when nothing else can own DRM master.
- **Dock/magnet state** (keyboard attached) is the trigger (ACPI `EC.CMMD` / `DEVD.GDST`).

## Architecture (driver-like, but layered correctly)
We should split this into **three layers** so it’s installable, debuggable, and safe:

1) **Event source (dock state)**
   - **Long-term (best):** a small kernel ACPI driver for `LEN009E` / `\_SB.DEVD` that emits a standard Linux event (`SW_DOCK`) when `Notify(DEVD, 1)` fires.
   - **Short-term (works now):** userspace reads the dock bit via `ec_sys` (`/sys/kernel/debug/ec/ec0/io` offset `0xC1`, bit7) with a low-frequency poll + debounce.

2) **Privileged hardware control (digitizer)**
   - A tiny “mode control” component that can:
     - **set** half/full (hidraw feature report when stable; I²C replay fallback),
     - **verify** current mode via the **I²C query tail** (the most stable readback we have).
   - This part needs privileged access to `/dev/i2c-*` and/or `/dev/hidraw*`.

3) **Session/UI integration (display geometry)**
   - This should run in the **user session**, because X11/Wayland compositor control is inherently per-session.
   - The UI layer consumes “desired mode” + “current mode” and applies geometry using:
     - X11: `x1fold_x11_blank` (black DOCK/STRUT window + reserved work area) — works today.
     - Wayland: layer-shell overlay client (planned; wlroots/KWin), or compositor-specific integration.
     - DRM clip: console-only fallback when no compositor owns DRM master.

The “Lenovo behavior” (when docked → half, undocked → full) lives in a **policy daemon** that ties (1)(2)(3) together.

## Wayland plan (UI layer)
Goal: reproduce the Windows semantics under Wayland:
- **Bottom region visually black** (not just a logical desktop height hint).
- **Work area shrinks** so apps/compositor don’t place windows under the keyboard.

### Preferred approach (wlroots/Sway): compositor-native crop (planned)
Implement “halfblank” inside the compositor so it behaves like the screen is shorter:
- windows/fullscreen never use the bottom region,
- pointer cannot enter the bottom region (compositor-level clamp),
- compositor renders black outside the active region,
- (optional) wlroots DRM backend applies a primary-plane clip (extra efficiency).

This avoids relying on a client-side overlay and best matches the X11/Windows UX.
See `docs/sway_wlroots_halfblank_patch_plan.md`.

### Interim/fallback approach: `wlr-layer-shell` overlay client
Implement a small helper (likely C) that uses `zwlr_layer_shell_v1`:
- Create a layer-surface anchored to **bottom** with size `width=output_width`, `height=blank_h` (`screen_h - top_h`).
- Fill with an opaque black `wl_shm` buffer.
- Set **exclusive zone** to `blank_h` so the compositor reserves that region (Wayland analogue of X11 struts).
- Keep the surface alive until the UI service tells it to exit.

This gives “real black bottom” without DRM master and should work on wlroots compositors (Sway/River/Wayfire/Hyprland) and any compositor that implements layer-shell (often KWin; GNOME typically does not).

### Fallbacks when layer-shell is unavailable
1. If `DISPLAY` is set (XWayland present), fall back to the X11 blank helper.
2. If no GUI backend can cover the bottom region, use `drm_clip` only in console/TTY sessions (stop compositor) as a lab tool.

### Backend selection logic (for the UI service)
- If `WAYLAND_DISPLAY` is set, attempt to bind `zwlr_layer_shell_v1`; if successful → Wayland overlay.
- Else if `DISPLAY` is set (or Xorg detected) → X11 overlay.
- Else → no-op display backend (digitizer-only) or DRM clip (explicit opt-in).

### Compositor-specific “later” items
- GNOME/Mutter: likely needs a GNOME Shell extension (or Mutter DBus integration) to create an overlay/work-area reservation; treat as a separate project once wlroots path is solid.
- KDE/KWin: if layer-shell isn’t reliable, consider KWin scripting/DBus as an alternative backend.

## Should this be a service?
Yes, but likely **two services**:
- `x1fold-halfblankd.service` (system): reads dock state + drives digitizer mode + writes a small state file (e.g., `/run/x1fold-halfblank/state.json`).
- `x1fold-halfblank-ui.service` (user): watches that state and applies display geometry in the active session.

If we keep it as one root service, X11/Wayland auth becomes messy and brittle (DISPLAY/XAUTHORITY, seat selection).

## Is Python “the right” implementation?
Python is fine for now **if we keep the interface stable and the dependencies minimal**:
- Pros: fastest iteration while we’re still reversing/validating; good for JSON status + glue logic.
- Cons: long-term distro integration, startup latency, and “root + GUI session” boundary are easier with a small compiled helper.

Pragmatic path:
- Keep the orchestration/policy in Python for now.
- Move the privileged “set/query digitizer mode” part to a tiny compiled helper later (C/Rust), exposing a narrow CLI/API, so we can drop `sudo`/udev hacks cleanly.

## Why is the mode “drifting” back?
We don’t have proof of the exact writer yet, but the observed symptom is consistent with one of:
- The digitizer/firmware periodically reasserting its default state unless “kept alive”.
- The Linux HID/I²C stack reinitializing the device (runtime PM, suspend/resume, driver probe) and overwriting the mode.
- Another component (compositor modeset, input stack) triggering a reset path that reverts the digitizer state.

This is why the daemon currently has an **enforcement loop**: it re-reads the I²C query tail and reapplies the desired mode if it flips.
Long-term we should replace “poll every N seconds” with event-driven reapply (udev change, resume hook, dock event) and keep periodic enforcement as a safety net.

## Packaging plan (what makes it installable)
- Install binaries/scripts into standard paths (`/usr/bin` or `/usr/libexec/x1fold-halfblank/`).
- Ship systemd units + udev rules:
  - udev: set group ownership for the relevant `/dev/i2c-1` and `/dev/hidraw*` nodes (or gate via `CAP_SYS_ADMIN` helper).
  - systemd: only start on supported hardware (DMI check via `ExecStartPre` guard).
- Provide config (`/etc/x1fold-halfblank/config.toml` or `.json`) for:
  - “half height” pixels,
  - enforcement interval,
  - backend selection (x11/wayland/drm),
  - logging verbosity.

Implementation details and current working commands live in `docs/linux_halfblank_plan.md`; this file describes the sustainable architecture and packaging direction.
