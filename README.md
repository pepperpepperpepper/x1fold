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
  - `install_x1fold_fnctl.sh`: installs `x1fold-fnctl` and its persistence hooks for the keyboard-side Fn/Ctrl swap.
  - `install_x1fold_webcam.sh`: installs webcam helpers + optional OVTI5675 `ipu_bridge` DKMS override.
  - `install_x1fold_all.sh`: runs the per-subsystem installers in order (start here on a fresh machine).
  - `install_x1fold_sleep.sh`: installs the lid/power sleep policy + the `button.lid_init_state=open` cmdline fix (see below).
  - `install_x1fold_sway.sh`: installs the Sway lid snippet into `~/.config/sway/` (run as your user, not root).
  - `build_x1fold_sway.sh`: builds + installs the patched Sway that makes fullscreen respect halfblank (see below).
  - `x1fold-stay-awake`: hold a `handle-lid-switch` inhibitor so the Fold stays up while folded shut.
  - `x1fold-halfblank-ui-session.sh`: wrapper to run the UI helper inside the active Wayland session (exports `WAYLAND_DISPLAY`/`SWAYSOCK`).
  - `halfblank_switch.sh`: wrapper for `half|full|status`.
  - `halfblank_regression.sh`: on-device loop test with logs.
  - `halfblank_collect.sh`: fetch logs from the device.
  - `x1fold-pair-keyboard.sh`: pair an additional Bluetooth keyboard without losing input mid-way (see below).
- `systemd/`
  - `x1fold-halfblankd.service`: system daemon unit.
  - `x1fold-tty-rotate.service`: system daemon unit for fbcon auto-rotate.
  - `user/x1fold-halfblank-ui.service`: per-user UI helper unit.
  - `logind.conf.d/`: lid + power-key sleep policy (hibernate on both).
- `upower/UPower.conf.d/`: critical-battery thresholds (drop-in, not an edit of `UPower.conf`).
- `sway/x1fold.conf`: Sway snippet — blanks the internal panel when the fold closes.

### Install (live system)

On a fresh machine, start here:

```bash
x1fold/scripts/install_x1fold_all.sh
```

That runs the halfblank, Fn/Ctrl and sleep installers in order, then prints the
three things it cannot do for you: the Sway snippet (user scope), the per-user
UI unit, and a reboot to pick up the kernel cmdline. Add `--webcam` to include
the IPU6 stack (opt-in — it builds a DKMS module). `--dry-run` to preview.

The per-subsystem installers below remain usable on their own for updates.

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

### Sleep / lid policy install

Run as root:

```bash
x1fold/scripts/install_x1fold_sleep.sh
```

This installs the logind drop-ins (`HandleLidSwitch=hibernate`,
`HandlePowerKey=hibernate` — the X1 Fold is s2idle-only, so S4 is the only cold
sleep available) and appends `button.lid_init_state=open` to the systemd-boot
kernel cmdline. Use `--dry-run` to preview, `--no-cmdline` to skip the
bootloader.

**The cmdline argument is not optional.** `button.lid_init_state` defaults to
`method`, which makes the ACPI button driver re-evaluate `_LID` on resume; on
this machine it returns *closed*. logind ignores lid input for
`HoldoffTimeoutSec` (30s) after resume, then re-reads the switch state directly,
sees "closed", and applies `HandleLidSwitch` again. The result is that the
machine hibernates itself roughly 23–26s after you open the lid, with no
`Lid closed.` line in the journal — right as resume finishes, so it reads as
"it woke up and then died again". Setting `open` only changes the synthetic
state reported at driver init/resume; real fold/unfold notifications still work.

To check for the symptom in your own journal:

```bash
journalctl -o short-unix | grep -E "hibernation (entry|exit)" | awk \
  '{ts=$1; sub(/\..*/,"",ts);
     if ($0 ~ /exit/) e=ts;
     else if (e && ts-e < 120) print "re-slept " (ts-e) "s after resume at " strftime("%F %T", e) }'
```

A cluster of re-sleeps at +22–26s is this bug.

The installer also drops in `upower/UPower.conf.d/10-x1fold-battery-action.conf`,
which moves the critical-battery thresholds off the stock
`PercentageCritical=5` / `PercentageAction=2`. Two percent is thin on this
machine, and it matters more once you start holding the lid inhibitor below.

### Staying awake with the lid closed

To leave something running while the Fold is shut — a server, a long build:

```bash
x1fold-stay-awake -- ./my-server      # lock lives as long as the command
x1fold-stay-awake                     # hold until Ctrl-C
```

For a systemd unit, wrap `ExecStart` the same way:

```ini
ExecStart=/usr/local/bin/x1fold-stay-awake -- /usr/local/bin/my-server
```

**Do not reach for `systemd-inhibit --what=sleep` here — it silently does
nothing.** `20-x1fold-lid-hibernate.conf` sets `LidSwitchIgnoreInhibited=yes`
(also the systemd default), and per `logind.conf(5)` that makes lid handling
ignore the high-level locks (`shutdown`, `reboot`, `sleep`, `idle`). The lock
registers, `systemd-inhibit --list` shows it, and the machine hibernates on lid
close anyway. `handle-lid-switch` is a *low-level* lock, and those are "always
honored, irrespective of this setting." That's the whole reason
`x1fold-stay-awake` exists rather than a shell alias.

Two things to know:

- It suppresses logind's lid handling **entirely**, not just the hibernate
  action — while held, lid close does nothing at all. The machine stays up
  until the command exits; the backstop is UPower's critical-battery action.
- The screen still blanks, because `sway/x1fold.conf` binds the switch in the
  compositor via `bindswitch`, which reads libinput directly and is unaffected
  by the inhibitor.

Install the Sway side as your desktop user (**not** under sudo — it writes into
`$HOME`, and the script refuses root):

```bash
x1fold/scripts/install_x1fold_sway.sh --reload
```

It writes `~/.config/sway/x1fold.conf` and adds one `include` to your config.
That file is repo-managed and overwritten on reinstall; hand edits belong in
`~/.config/sway/config.user`, which this repo never touches.

### Webcam install (IPU6 / OVTI5675)

Run as root:

```bash
x1fold/scripts/install_x1fold_webcam.sh
```

Details and troubleshooting are documented in `x1fold/webcam/README.md`.

### Wayland “true shorter output” (recommended for wlroots/Sway)

Without this, **fullscreen breaks halfblank**: the layer-shell fallback
(`x1fold_wl_blank`) reserves the bottom region with an *exclusive zone*, which
constrains tiled and floating windows — but fullscreen deliberately ignores
exclusive zones, since covering the whole output is the entire point of
fullscreen. So a fullscreen video spans the full 2560px panel and half of it
lands under the keyboard. Only the compositor can make the bottom region
genuinely not part of the desktop.

Build and install a patched Sway:

```bash
x1fold/scripts/build_x1fold_sway.sh
```

This clones Sway 1.12 and wlroots 0.20.2, applies:
- `patches/wlroots0.20-x1fold-active-height.patch` — adds
  `WLR_OUTPUT_STATE_X1FOLD_ACTIVE_HEIGHT`, which shrinks the output's *logical*
  height while leaving the scanout mode alone
- `patches/sway-1.12-x1fold-halfblank.patch` — adds
  `output <name> x1fold_halfblank enable <px> | disable`, restricted to the
  internal panel (`eDP*`)

and builds wlroots as a **static** meson subproject, so the result is a single
self-contained binary at `/usr/local/bin/sway`. Nothing system-wide is replaced:
the distro `sway` stays at `/usr/bin/sway` and the distro `wlroots` is untouched,
so other wlroots-based programs are unaffected. `x1fold-sway-session` sets
`PATH=/usr/local/sbin:/usr/local/bin:/usr/bin` before `exec sway`, so the patched
build wins on next login.

Roll back at any time — the distro package applies again on next login:

```bash
x1fold/scripts/build_x1fold_sway.sh --uninstall
```

No configuration change is needed: `x1fold_halfblank_ui.py` in `auto` mode probes
for the command and selects `sway_crop` when it is present, `layer_shell` when it
is not.

Verify:

```bash
sway --version                                    # expect "branch 'x1fold'"
swaymsg -t get_outputs | jq '.[].rect.height'     # 1240 docked, 2560 undocked
```

The older `sway-1.11` / `wlroots0.19` patches are kept for reference.

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

### Pairing an additional Bluetooth keyboard

The magnetic keyboard is what drives the halfblank dock signal, but a Bluetooth
keyboard can be used alongside it. The X1 Fold's Intel AX211 holds several
peripherals at once, so both keyboards can stay connected and both feed the
same seat — there is no need to unpair one to use the other.

```bash
scripts/x1fold-pair-keyboard.sh --watch    # start here: hold the keyboard's BT button
scripts/x1fold-pair-keyboard.sh --check    # is it advertising? in which mode?
scripts/x1fold-pair-keyboard.sh --list     # show keyboards known to BlueZ + input nodes
scripts/x1fold-pair-keyboard.sh --restore  # reconnect the previous keyboard
```

**Reinstalling this machine? Don't pair again — keep the keys:**

```bash
x1fold-pair-keyboard --backup-bonds ~/kbd-bonds.tar.gz    # before wiping
x1fold-pair-keyboard --restore-bonds ~/kbd-bonds.tar.gz   # after reimaging
```

Same adapter only (the keys are bound to its address; a mismatch is refused
rather than silently restored). The backup contains Bluetooth link keys — it is
written mode `0600`, keep it private, and never commit it.

**The step that wastes hours: pairing completes only when you press Enter on
the keyboard being paired.** The kernel reports `User Confirm 000000 hint 1`,
which looks like a dialog on the computer waiting to be clicked. Nothing on the
computer can answer it — not `bluetoothctl`'s agent, not the desktop applet
(under Sway it flashes a notification that vanishes), not `btmgmt`. The
keyboard is waiting for a keystroke, and hangs up if none arrives.

**These keyboards also do not pair through the normal Linux path.** The
Bluetooth GUI won't show them, and `bluetoothctl pair` reports `Device ... not
available` while the keyboard is actively advertising a few inches away. That
is not a fault in the machine: the keyboard advertises with no discoverable bit
set when it is already bonded to another host, and BlueZ drops such
advertisements before they become device objects. A five-minute scan here
catalogued 195 devices without listing the keyboard, while raw HCI showed it
the entire time.

`--watch` sidesteps this by monitoring raw HCI and pairing through the kernel
management interface, which needs no scan cycle and no D-Bus device object. It
also removes the timing problem — pairing mode lasts under a minute, which a
scan-then-pair sequence routinely loses. Start the watcher, then press the
button whenever you like.

**Read `docs/BLUETOOTH_KEYBOARD_PAIRING.md` before fighting this by hand.** It
covers the flags, the per-host-slot addresses, and the diagnostic commands.

Nothing in the script disconnects a keyboard that is already connected — the
AX211 holds both at once, verified. `--watch` only auto-pairs devices whose
advertised name and signal strength match this hardware, so a neighbour's
keyboard in pairing mode is ignored; pass an explicit address to override.

Note that `install_x1fold_fnctl.sh` is specific to the Lenovo keyboard's own HID
report and does **not** apply to third-party Bluetooth keyboards; use `keyd` or
a udev hwdb entry for those.

### Documentation

- `docs/BLUETOOTH_KEYBOARD_PAIRING.md`: why these keyboards don't pair through
  the normal Linux path, and how to pair them anyway.
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
