# Sway/wlroots “native halfblank” patch plan (battery-first)

## Why this is needed
Our current Wayland backend (`x1fold_wl_blank` via `zwlr_layer_shell_v1`) can:
- paint the bottom region black, and
- reserve the region (exclusive zone) so tiled layouts avoid it.

But it **cannot fully replicate** the X11 behavior:
- a Wayland *client* can’t install a global pointer barrier / clamp the cursor,
- some “fullscreen” behaviors can still fight the reserved area,
- the output still exists at full height in the compositor, so the semantics are “overlay + work-area hint”, not “screen is shorter”.

Only the compositor (Sway/wlroots) can make the bottom region behave like it’s **not part of the desktop**.

## Target behavior (X1 Fold policy)
- Scope: apply only to the **internal panel** (`eDP-1`). Never crop external monitors.
- **Docked (keyboard attached):**
  - active region = **top** `ACTIVE_PX` (≈`1240` physical px on this panel)
  - bottom region is **black**, **cannot receive pointer focus**, and **no windows** can be placed there
  - rotation forced to **normal** (keep “bottom blanking is always the physical bottom”)
- **Undocked (keyboard removed):**
  - active region = full output
  - rotation may follow the accelerometer (existing policy)

This must be **dynamic**: dock → half, undock → full, without restarting Sway.

Terminology:
- `ACTIVE_PX` is the **physical pixel height** of the usable “top” region while docked.
  - For the X1 Fold internal panel this is currently treated as a constant `1240` (out of `2560`).
  - Keep it configurable so we can correct/calibrate later without rebuilding.

## Approach options
### Option A (recommended): Sway-native “active rect” + pointer clamp (fast path)
Implement the semantics entirely in Sway:
1) Add an internal per-output “active rect” (default = full output).
2) Use that rect for:
   - tiling/layout extents (like bars do via reserved areas),
   - fullscreen sizing rules (never exceed active rect while halfblank),
   - rendering clip/scissor (draw black outside the active rect),
   - **cursor motion clamp** (warp/clamp pointer coordinates so it never enters the blank region).

Pros:
- No extra compositor.
- Full UX semantics (apps + pointer) match what we want.
- Can be toggled live via IPC.

Cons:
- The core `wl_output` “mode” events may still advertise the physical mode size unless we also patch wlroots (often OK; clients don’t position themselves).

### Option B (best long-term): wlroots DRM plane clip + logical crop (slow path)
Add wlroots support for an output “viewport/active rect” which:
- makes wlroots treat the output as `ACTIVE_PX` tall for layout/configure,
- programs the DRM primary plane as `CRTC_H=ACTIVE_PX` at `CRTC_Y=0` (top-anchored),
- leaves the rest uncovered (black).

Pros:
- Closest match to “the screen is shorter” even for output metadata.
- Avoids rendering/compositing the bottom region.

Cons:
- More invasive patch (wlroots + Sway), more update churn risk.

## Implementation sketch (wlroots0.19 + Sway 1.11)
Goal: keep the *real* KMS mode at `2024x2560`, but expose a *logical* mode to clients at `2024xACTIVE_PX`.

wlroots changes (conceptual):
- Add a per-output “logical size override” (or “active region”) to output state.
  - When unset: logical size = current mode size (today’s behavior).
  - When set: logical size = `{mode_w, ACTIVE_PX}`.
- Make `wl_output` events use the logical size (so clients genuinely see a shorter output).
- Ensure the renderer/swapchain uses the logical size for buffer allocation and coordinate mapping.
- In the DRM backend, program the primary plane as:
  - `CRTC_X=0, CRTC_Y=0, CRTC_W=mode_w, CRTC_H=ACTIVE_PX`
  - `SRC_X=0,  SRC_Y=0,  SRC_W=mode_w, SRC_H=ACTIVE_PX` (16.16 fixed-point)
  - This yields “black below” without a client overlay, and avoids rendering pixels we never present.

Sway changes:
- Expose an IPC/config command to toggle the logical crop **only** for `eDP-1`.
- When toggled:
  - recompute workspaces/layout against the new output geometry,
  - clamp cursor motion to the logical region,
  - keep existing rotation policy (force `normal` while halfblank).

## IPC + integration (how it becomes dynamic)
Expose a new Sway command (IPC + config) such as:
- `output <name> x1fold_halfblank enable <active_px>`
- `output <name> x1fold_halfblank disable`

Then update `x1fold_halfblank_ui.py` to:
- on state change `full↔half`, call `swaymsg` with the command above,
- keep the existing rotation policy (rotate only when undocked/full).

Battery note: keep the UI helper event-driven where possible (state change only; no high-frequency polling).

## Patch files (in this repo)
These are the current WIP patchsets we apply to Arch’s `wlroots0.19` + `sway` sources:
- wlroots: `x1fold/patches/wlroots0.19-x1fold-active-height.patch`
- sway: `x1fold/patches/sway-1.11-x1fold-halfblank.patch`

## Build/deploy workflow (Arch target)
- Create a small patch set:
  - `sway` patch (IPC command + internal “active rect” behavior),
  - optional `wlroots` patch (DRM plane clip + logical crop).
- Package as local `pacman` packages (battery-first, reproducible):
  - build on `:2023` (fastest feedback) or on the controller and copy packages.
  - keep patches in this repo under `x1fold/patches/` (one patch per concern).

Concrete first pass (on `:2023`):
- Record current versions:
  - `pacman -Q sway wlroots`
- Pull Arch packaging sources (choose one):
  - `pkgctl repo clone --protocol=https --repo=extra sway wlroots`
  - or `asp export sway && asp export wlroots`
- Apply our patch(es), then build+install:
  - `makepkg -si`
- Reboot or restart the session to pick up the new compositor binary (first bring-up is easier with a reboot).
  - After it works, ensure dock/undock toggling does **not** require restart.

## Status (2026-09-20)

Implemented and rebased onto **sway 1.12 / wlroots 0.20.2**:
- `patches/sway-1.12-x1fold-halfblank.patch`
- `patches/wlroots0.20-x1fold-active-height.patch`
- built + installed by `scripts/build_x1fold_sway.sh`

The shipped implementation is closest to **Option A**, not Option B: it shrinks
`wlr_output->{width,height}` (the *logical* output size) and lets the DRM primary
plane cover only that region, leaving the rest of the CRTC unlit. It does **not**
explicitly program `CRTC_H`/`CRTC_Y`, and it does not implement a separate pointer
clamp — the pointer is confined as a consequence of the output being shorter.

Rebase notes (0.19 → 0.20), in case this has to be redone:
- `enum wlr_output_state_field` was renumbered; 0.20 already uses `1 << 13` for
  `WLR_OUTPUT_STATE_IMAGE_DESCRIPTION`, so the x1fold bit moved to `1 << 14`.
  **This is the one that silently corrupts state if you get it wrong.**
- `output_compare_state()` gained a `COLOR_TRANSFORM` block; the x1fold block goes
  after it.
- `ext_image_capture_source_v1` now also tests `WLR_OUTPUT_STATE_ENABLED`.
- sway's `queue_output_config()` gained HDR/color-profile handling at the tail;
  the x1fold call goes after `set_hdr()`.

Verified nested (`WLR_BACKENDS=wayland`, eDP guard temporarily relaxed to exercise
the mechanism off-panel):

| step | logical output height | fullscreen window rect |
|---|---|---|
| baseline | 588 | — |
| `x1fold_halfblank enable 360` | 360 | `h=360` (constrained) |
| `x1fold_halfblank disable` | 588 | `h=588` (follows back) |

On stock sway the same fullscreen window reports the full output height — that is
the bug this exists to fix. Invalid arguments and non-`eDP` outputs are rejected.

Not yet verified on the real panel: nested backends have a synthetic mode, so the
DRM behaviour (scanout stays 2024x2560 while the logical output is 2024x1240)
still needs confirming on hardware against the checklist below.

## Validation checklist
Docked (half):
- Pointer cannot enter the bottom region (try touchpad + touchscreen).
- Tiled windows never enter the bottom region.
- Fullscreen (video/browser) never covers the bottom region.
- Bottom region stays black (no transient redraw).
- Rotation stays `normal` even if device is sideways.
Quick sanity checks:
- `swaymsg -t get_workspaces -r | jq -r '.[0].rect'` (height should match the active region if we implement a true logical crop)
- `swaymsg -t get_outputs -r | jq -r '.[].current_mode'`

Undocked (full):
- Full height returns without restarting Sway.
- Rotation works when sideways.
- No lingering pointer clamp.

Regression:
- 20 dock/undock cycles: no Sway crash, no wlroots DRM errors, no “stuck black” on full.
