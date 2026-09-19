# Plan: X1 Fold native Arch setup (SSH-first)

Target: **ThinkPad X1 Fold 16 Gen 1** (`product_name=21ETS1JM00`).

## Working mode (updated 2026-01-18)
- This file is an **ops runbook** for getting the Fold into a usable, battery-friendly state.
- Prefer making changes **directly on the Fold over SSH** and only documenting outcomes here.
- Avoid repo work (templates/repro scripts) unless explicitly needed for fold/dock behavior.

## Context / constraints
- Current access: native Arch over SSH via **`ssh root@localhost -p 2023`**.
- Remote access survives reboot via a **systemd-managed reverse SSH tunnel** (see “Remote access” below). Port `2222` is legacy/deprecated in this setup.
- Primary goal: **battery life**, without breaking the **hi‑res internal display** or fold/dock workflows.
- Secondary goal: get a **graphical session** running (Wayland vs Fluxbox later).

Tunnel housekeeping (server-side):
- Reverse forwards show up as a listening socket owned by `sshd-session` (not by `ssh`).
- Inspect: `sudo ss -ltnp | rg ':(2222|2023)\\b'`
- Kill a stale forward without touching others: `sudo kill -TERM <sshd-session-pid>`
- Hibernate/suspend gotcha:
  - If the Fold disappears abruptly (hibernate), the controller host can keep a dead `sshd-session` around, still holding `:2023`.
  - Symptom: `ssh -p 2023 root@localhost` hangs at “banner exchange” and the Fold cannot re-bind the port on reconnect.
  - Fix: kill the listening `sshd-session` PID on the controller host to free the port (or configure `sshd` `ClientAliveInterval`/`ClientAliveCountMax` to reap dead sessions faster).
  - Optional (controller host): add an sshd keepalive drop-in and reload sshd:
    - Create `/etc/ssh/sshd_config.d/10-client-alive.conf` with:
      - `ClientAliveInterval 15`
      - `ClientAliveCountMax 2`
    - `sudo systemctl reload sshd`

## Current status (as of 2026-01-18)
- ✅ NVMe was wiped and repartitioned:
  - `/dev/nvme0n1p1` ESP 1 GiB (FAT32)
  - `/dev/nvme0n1p2` swap 24 GiB (hibernate)
  - `/dev/nvme0n1p3` `btrfs` root (subvols `@`, `@home`, `@var`)
  - ~64 GiB unallocated at end for future Windows
- ✅ Base Arch installed + `systemd-boot` entries written + `resume=` wired to swap UUID.
- ✅ User `pepper` created (password set out-of-band), sudo wheel enabled, SSH authorized_keys copied.
- ✅ Network bring-up present:
  - `/etc/wpa_supplicant/wpa_supplicant.conf` exists (0600).
  - `x1fold-wifi-autoconnect.service` is enabled and keeps `wpa_supplicant` + `dhcpcd` running (bring-up convenience).
  - Once we’re confident remote access is reliable, consider disabling it to match the “Wi‑Fi off by default” policy.
- ✅ Reverse SSH tunnel is persistent via systemd:
  - `x1fold-reverse-ssh@2023.service` keeps `localhost:2023` reachable after reboot (tunnels to `arch@moviecomp.duckdns.org`).
  - Config: `/etc/x1fold-reverse-ssh.conf`; script: `/usr/local/sbin/x1fold-reverse-ssh.sh`; unit: `/etc/systemd/system/x1fold-reverse-ssh@.service`.
  - Reboot verified: tunnel comes back automatically (tested 2026-01-17).
- ✅ `internet_manager` installed at `/usr/local/bin/internet_manager` (no hardcoded `/dev/wwan0mbim0`; uses `MBIM_DEVICE`/auto-detection).
- ✅ `yay` installed (as `pepper`) for AUR: `yay v12.5.7`.
- ✅ Wayland GUI installed + enabled:
  - Packages: `sway` + `greetd` + `foot` + PipeWire.
  - `greetd.service` enabled and running; default target set to `graphical.target`.
  - Sway config installed to `/home/pepper/.config/sway/config` (OLED black background + HiDPI scale + DPMS-off + brightness/audio keys; **no lockscreen**).
  - Session wrapper installed: `/usr/local/bin/x1fold-sway-session` (ensures sane PATH + Wayland hints; used by `/etc/greetd/config.toml`).
  - No greeter UI: `greetd` launches Sway directly (both `initial_session` + `default_session` use `/usr/local/bin/x1fold-sway-session` as `pepper`).
- ✅ Desktop essentials installed:
  - `xdg-desktop-portal` + (`xdg-desktop-portal-wlr` + `xdg-desktop-portal-gtk`), `xdg-user-dirs`, `firefox`, `thunar`, `gvfs`/`gvfs-mtp`, `udisks2`.
  - Fonts: `noto-fonts`, `noto-fonts-emoji`, `ttf-jetbrains-mono`.
- ✅ Shell utilities present on the native install:
  - `/home/pepper/shell-utilities` exists and scripts are installed to `/home/pepper/.local/bin`.
  - Login-shell PATH includes `~/.local/bin` via `/etc/profile.d/10-user-local-bin.sh` (without overriding `/usr/local/bin`).
- ✅ X1 Fold “halfblank” (OLED power win) installed:
  - System daemon enabled: `x1fold-halfblankd.service`
  - Dock sensing uses `ec_sys` (loaded at boot via `/etc/modules-load.d/ec_sys.conf`).
  - UI helper enabled globally (starts on user login): `x1fold-halfblank-ui.service` (Wayland socket auto-detected via `/usr/local/bin/x1fold-halfblank-ui-session`).
- ✅ Webcam policy:
  - IPU6 camera stack disabled by default (blacklisted in `/etc/modprobe.d/99-x1fold-disable-ipu6.conf`).
  - Enable on demand: `sudo x1fold-webcam-on` (loads modules)
  - Disable again: `sudo x1fold-webcam-off` (unloads modules; also runs automatically before sleep/hibernate)
- ✅ Power baseline configured:
  - `tlp.service` enabled; drop-in config at `/etc/tlp.d/10-x1fold.conf` (platform_profile + EPP + turbo-off on battery).
  - WWAN soft-blocked by default: `rfkill block wwan` + `x1fold-radios-defaults.service` (enforces on boot).
  - WWAN tooling installed but disabled by default: `modemmanager` (service stays `disabled/inactive` unless started from CLI).
  - Power button → hibernate: `/etc/systemd/logind.conf.d/10-x1fold-power.conf` (takes effect after reboot or logind restart).
- ✅ Bluetooth service enabled (keyboard/headphones): `bluetooth.service`.
- ⚠️ `x1fold-remote-proxy.service` exists but is currently **disabled/inactive**; previous start attempts timed out connecting to `${CLOUD_PROXY_ENDPOINT}` (re-evaluate if we still need this workflow).

## Workstation bootstrap (dotfiles + tooling)
Goal: make the existing install feel like your “real” machine: full shell environment, aliases, local tools, and day-to-day software.

Source machine for dotfiles: **blonderon** reachable as `ssh pepper@localhost -p 3333`.

### Dotfiles sync (pepper)
Approach: copy from blonderon → Fold over SSH, but preserve Fold-specific bits (Sway stack + IPU6 helper aliases).

What was synced (core):
- Shell: `~/.bashrc`, `~/.bash_profile` (patched on Fold to not start Fluxbox/X11), `~/.bash_aliases` (+ Fold IPU6 webcam helpers appended), `~/.dircolors`
- Dev UX: `~/.gitconfig`, `~/.gitattributes`, `~/.gitignore`, `~/.tmux.conf`, `~/.vimrc`, `~/.vim/`, `~/.config/nvim/`
- User services: `~/.config/systemd/user/`
- Local tools: `~/.local/bin/` and `~/.local/src/` (projects like `opencode`, `qwen-code`, `voicepipe`)
- SSH: `~/.ssh/config`, `~/.ssh/known_hosts*`, and key files referenced by config (e.g. `~/.ssh/lalalizard`, `~/.ssh/claude_key`, `~/.ssh/id_ecdsa`, `~/.ssh/win-fenlo`); `authorized_keys` merged (not replaced)

Backup strategy (Fold):
- Before overwriting, save prior state into: `~/dotfiles-backup/<UTC timestamp>/...` (includes `~/.ssh/` snapshot)
- Latest run (2026-01-19 UTC):
  - Dotfiles backup: `~/dotfiles-backup/20260119-024838`
  - SSH backup: `~/dotfiles-backup/20260119-044105/ssh-x1fold-before`

### Packages installed (Fold)
Pacman (baseline):
- `yadm`, `git-crypt`, `rsync`, `bash-completion`, `direnv`, `xclip`
- `fzf`, `bat`, `eza`, `jq`, `tree`, `btop`, `htop`, `unzip`, `zip`
- `nodejs`, `npm`, `bun`
- `github-cli` (`gh`), `git-lfs`
- OCR/media deps: `tesseract`, `ghostscript`, `qpdf`, `unpaper`, `pngquant`, `ffmpeg`, `yt-dlp`

AUR (built by `yay`, installed via `pacman -U` as root):
- `tmux-resurrect` (required by `~/.tmux.conf`)
- `vim-plug` (required by `~/.config/nvim/init.vim`)

Python tooling:
- Neovim python host venv: `~/.venvs/neovim` + `pynvim`
- `pipx` installs: `ocrmypdf`, `etl-parser` (restores `ocrmypdf`, `etl2pcap`, `etl2xml` under `~/.local/bin`)

Hardware quick facts:
- CPU: 12th Gen Intel Core i7-1250U (Alder Lake-U)
- RAM: ~16 GiB (`MemTotal: 16061896 kB`)
- iGPU: Intel Iris Xe (i915)
- Wi‑Fi: Intel CNVi (iwlwifi)
- Internal display mode: `2024x2560` (OLED)

Remote-access note:
- If `localhost:2023` is listening but SSH banner exchange **hangs** or resets, the reverse tunnel may be:
  - missing on the device (Wi‑Fi down / service not running), or
  - pointed at the wrong local port, or
  - the controller host port already being held by an older reverse-forward listener.
  - Recovery: boot the live USB, connect Wi‑Fi, then inspect `x1fold-reverse-ssh@2023.service` + `x1fold-wifi-autoconnect.service` logs in the native install (see “Remote-access validation” below).

## Guiding principles
1. **Measure first**: record baseline watts + wakeups before tuning.
2. **Prefer standard knobs**: `platform_profile`, CPU EPP, runtime PM, brightness.
3. **Keep changes reversible**: every tweak has a quick “off switch”.
4. **Pick one power manager**: don’t run multiple daemons that fight each other.

## Decisions (make once; document in the repo)
These drive nearly every later step:
- Disk: `btrfs` (chosen for the current install)
- Encryption: none for the current install (revisit LUKS2 later if needed)
- UI stack: **Wayland compositor** (recommended) vs **Xorg + Fluxbox**
- Power manager: **TLP** (installed/enabled; minimal + tunable) vs `power-profiles-daemon` (best if we later choose GNOME)
- Networking policy:
  - Wi‑Fi: **off by default** (manual connect via `internet_manager`; optional low-power disconnect watchdog)
  - WWAN: **deep-off by default** (enable only via CLI)
  - Keyboard: Bluetooth (treat as “usually on”, but do not allow BT to wake the machine from sleep)
- Sleep policy: plan for **hibernate** (swap partition) since this platform is `s2idle`‑only and may sit asleep for long periods
  - Prefer using the **power button** to trigger hibernate (minimizes long-idle drain vs staying in `s2idle`)

## Open issues / TODO (reported 2026-01-18)
- [ ] Power button: confirm desired policy is **hibernate** (note: hibernate fully powers off; resume requires a power button press).
- [ ] Hibernate UX: decide between **hibernate** vs **suspend-then-hibernate** (better UX; slightly more drain).
- [ ] Hibernate resume: confirm it reliably resumes the prior session (no “bad magic number”, no greeter, no lock).
- [ ] No-lock UX: ensure there is **no** `swaylock` usage (no lock on idle, no lock before sleep/hibernate).
- [ ] IPU6 policy: confirm IPU6 stays unloaded by default; webcam works only after `sudo x1fold-webcam-on`.
- [ ] Halfblank on boot: reboot with keyboard docked; confirm halfblank is active immediately after Sway starts.
- [ ] Halfblank toggling: dock/undock while logged in; confirm `/run/x1fold-halfblank/state.json` flips and `x1fold_wl_blank` runs/stops.
- [ ] “Big red background” event: if it happens again, capture a photo + logs (steps in the runbook below).

## Structured test (runbook)
Goal: confirm “daily-driver” UX: **no lockscreen**, **IPU6 off-by-default**, **halfblank works**, **hibernate works**, and **remote access returns**.

### 0) Pre-test (remote access safety)
From the controller host:
- Confirm the reverse-tunnel port is not stuck:
  - `sudo ss -ltnp | rg ':(2023)\\b' || echo 'no listener (ok)'`
  - If `:2023` is held by a dead `sshd-session` and `ssh -p 2023 root@localhost` hangs at banner exchange, kill that PID to free the port.

### 1) Cold boot UX (keyboard docked)
On the Fold:
- Dock the keyboard (magnet attached), then power on using the side button.

Expected:
- **No login prompt** (autologin via `greetd initial_session`).
- Sway starts (black background).
- If keyboard is docked: **halfblank is active** (bottom region is truly black).

If you see a “big red background” at any point:
- Take a photo + note whether there is any text.
- Capture logs over SSH:
  - `journalctl -b -u greetd -n 200 --no-pager`
  - `journalctl -b -u x1fold-halfblankd.service -n 200 --no-pager`
  - `sudo -u pepper XDG_RUNTIME_DIR=/run/user/1000 journalctl --user -u x1fold-halfblank-ui.service -n 200 --no-pager`

### 2) Halfblank live toggling (while logged in)
On the Fold (in a terminal):
- Watch dock state while attaching/detaching the keyboard:
  - `x1fold_dock.py watch --print-initial --interval-s 0.2`
- Confirm the daemon is writing the state file:
  - `cat /run/x1fold-halfblank/state.json`
- Confirm the Wayland blanker helper runs when docked:
  - `pgrep -af x1fold_wl_blank || true`

Expected:
- Dock → bottom region goes black and stays black.
- Undock → bottom region returns to full screen.

### 3) No lockscreen (only DPMS off)
On the Fold:
- Confirm there is no lock process:
  - `pgrep -af swaylock || echo 'no swaylock (ok)'`
- Wait 10+ minutes idle (DPMS timeout) then tap a key / touch the screen.

Expected:
- Screen turns off (DPMS), then comes back **directly to the session** (no password prompt, no greeter).

### 4) IPU6 webcam policy (off-by-default; on-demand)
On the Fold:
- Confirm IPU6 is not loaded by default:
  - `lsmod | rg -n 'intel_ipu6|ipu_bridge|ov5675' || echo 'ipu6 not loaded (ok)'`
- Enable webcam stack only when needed:
  - `sudo x1fold-webcam-on`
  - (Optional) `v4l2-ctl --list-devices`
- Disable again:
  - `sudo x1fold-webcam-off`
  - `lsmod | rg -n 'intel_ipu6|ipu_bridge|ov5675' || echo 'ipu6 not loaded (ok)'`

### 5) Hibernate/resume (battery-first sleep)
Important constraints:
- Hibernate powers off the machine; wake requires a **physical power button press**.
- The reverse SSH bind port on the controller host (`:2023`) can get “stuck” if a dead session keeps listening.

Test:
- Initiate hibernate by pressing the power button (logind policy) or:
  - `sudo systemctl hibernate`
- Wait for power-off.
- Press the power button to resume.

Expected:
- Returns to the same Sway session (no greeter, no lock).
- Halfblank matches the dock state.
- No IPU6 “unexpected magic number” spam on resume (since IPU6 is disabled by default).

Remote validation (controller host):
- `ssh -p 2023 root@localhost 'echo OK; uptime; systemctl is-active x1fold-reverse-ssh@2023.service'`

## Phase 0 — Preflight + data capture (non-destructive)
Goal: confirm hardware and capture “before” measurements.

On the live target:
- Record identity:
  - `cat /sys/class/dmi/id/product_name /sys/class/dmi/id/product_version`
  - `uname -a`
- Record power + suspend capabilities:
  - `cat /sys/firmware/acpi/platform_profile`
  - `cat /sys/power/mem_sleep`
  - `ls -l /sys/class/power_supply/BAT*`
- Baseline “real watts” via Intel RAPL (10s sample):
  - Follow the `power_plan.md` “Quick real watts” snippet.
- Save everything to `/root/logs/arch_native_preflight.txt` and fetch it back with `baremetal_fetch`.

Preflight notes (captured 2026-01-17):
- RAM: ~16 GiB (`MemTotal: 16000616 kB`)
- NVMe (before wipe): `nvme0n1` 476.9G WD PC SN740, Windows GPT layout (ESP + MSR + NTFS + WinRE).
- Suspend: `s2idle` only (`/sys/power/mem_sleep` shows `[s2idle]`)
- Baseline watts on the live ISO (Wi‑Fi connected): `pkg_w ~1.89`, `psys_w ~3.56` (Intel RAPL 10s sample)

## Phase 1 — Disk layout + mount (destructive)
Goal: stable UEFI boot + a clean layout we can maintain.

⚠️ Current state (from preflight): the internal NVMe is a Windows GPT install (ESP+MSR+NTFS+WinRE) and the NTFS volume had ~206 GiB used at the time of capture. Decide whether to **wipe** or **shrink/dual‑boot** before proceeding.

Recommended layout:
- EFI system partition: 512 MiB FAT32 at `/boot`
- Root: the rest (LUKS2 + `btrfs` subvolumes recommended)
- Reserve space for a **small Windows partition** (firmware/update fallback):
  - Leave **~64 GiB unallocated** at the end of the disk (Windows 11 minimum storage), or create an NTFS partition labeled `WIN`.

Chosen layout for first native Arch bring-up (so we can proceed reproducibly):
- ESP: **1 GiB** FAT32 (room for kernel + initramfs + ucode on systemd-boot)
- Swap: **24 GiB** (hibernate on ~16 GiB RAM with headroom)
- Root: `btrfs` (subvols `@`, `@home`, `@var`)
- Leave tail: **64 GiB unallocated** for future Windows

Notes:
- Keep it simple: no LVM at first; add later only if needed.
- Plan a **swap partition sized for hibernate** (this machine is ~16 GiB RAM; size swap accordingly, with a little headroom).

## Phase 2 — Base Arch install (native)
Goal: bootable, networked, remotely reachable system on NVMe.

Install essentials:
- `base`, `base-devel` (for AUR builds), `linux`, `linux-firmware`, `intel-ucode`
- Core tooling: `openssh`, `sudo`, `vim`, `git`, `python`, `i2c-tools`
- Networking (manual, Wi‑Fi off-by-default): `wpa_supplicant`, `dhcpcd`, `iw`, `rfkill`, `curl`
- Optional (later): `networkmanager` (only if we decide we want auto-connect)

Boot:
- Use `systemd-boot` (UEFI native) unless you have a reason to prefer GRUB.
- If using LUKS2, wire `mkinitcpio` + kernel cmdline (`cryptdevice=...`).
- Enable at least: `sshd`, `systemd-timesyncd`.
- Leave Wi‑Fi “off-by-default” by not enabling a network manager daemon unless explicitly desired.

Remote access (critical for this workflow):
- The native install uses a **systemd-managed reverse SSH tunnel**:
  - Unit: `/etc/systemd/system/x1fold-reverse-ssh@.service` (instance: `x1fold-reverse-ssh@2023.service`)
  - Script: `/usr/local/sbin/x1fold-reverse-ssh.sh`
  - Config: `/etc/x1fold-reverse-ssh.conf`
  - Access path (from controller host): `ssh root@localhost -p 2023`
- Required carry-over into the native install:
  - `/etc/pepper-runtime-settings.sh`
  - `/etc/profile.d/pepper-testing-tools.sh`
  - `/root/.ssh/authorized_keys` (inbound admin)
  - `/root/.ssh/id_ed25519` (outbound tunnel identity) or set `SSH_IDENTITY_FILE=...` in `/etc/x1fold-reverse-ssh.conf`.
- Legacy: `x1fold-remote-proxy.service` (cloud proxy / port 2222) is **disabled** and should stay that way unless we explicitly switch back to that workflow.

Post-install (while booted to the live USB):
- Legacy: enabling the old port-2222 cloud proxy service is deprecated; avoid unless needed.
- Copy `scripts/internet_manager` → `/usr/local/bin/internet_manager` inside the native install.
- Copy + install `shell-utilities` into the native install (user `pepper`) and ensure `~/.local/bin` is on PATH.

Network config carry-over (bring-up convenience; revisit for “Wi‑Fi off by default” later):
- Copy `/etc/wpa_supplicant/wpa_supplicant.conf` from the live ISO into the installed system (mode `0600`).
- Optional for first boot only: enable a lightweight Wi‑Fi bring-up unit (then disable once the reverse proxy is reliable).

Shell utilities (install into the native OS):
- Install `internet_manager` into the native OS (use the updated one in this repo):
  - Copy `scripts/internet_manager` → `/usr/local/bin/internet_manager` and `chmod 0755`.
- Install your `shell-utilities` bundle (older notes called this `shell_utitlities`) into the native OS:
  - Place it at `/home/pepper/shell-utilities` and run `/home/pepper/shell-utilities/install` to populate `/home/pepper/.local/bin`.
  - Keep `/usr/local/bin` earlier in `PATH` so our system-managed `internet_manager` stays authoritative.

Users:
- Create a regular user: `pepper`
- Password: set out-of-band with `passwd` during bring-up; do not record it here.
- Add `pepper` to `wheel` and enable sudo for wheel users.

AUR helper:
- Install `yay` (as user `pepper`) so we can pull small extras cleanly:
  - `git clone https://aur.archlinux.org/yay.git && cd yay && makepkg -si`

## Phase 3 — Graphical session (hi‑res display first)
Goal: working GUI that’s **fast** and **low idle power**.

Recommended default: **Wayland** (best fit for touch + Hi‑DPI + low idle power)
- Compositor (pick one): `sway` (wlroots) or another minimal Wayland compositor.
- Login: `greetd` (autologin; no greeter UI).
- Graphics/media:
  - `mesa`, `vulkan-intel`, `intel-media-driver` (hardware decode saves power)
- Hi‑DPI:
  - Use compositor scaling; keep a single source of truth for scale factors.
- Halfblank integration:
  - Prefer a compositor that supports `wlr-layer-shell` (so `x1fold_wl_blank` can reserve/black the bottom region).

Optional (later): **Xorg + Fluxbox**
- Add `xorg-server` + `fluxbox`, and use `greetd` to offer both sessions.
- Handle Hi‑DPI via Xft DPI and/or `xrandr` scaling.

## Phase 3.5 — Desktop essentials (make it usable day-to-day)
Goal: a complete “daily driver” baseline while staying power-friendly (no heavy background daemons).

Install (native):
- Wayland plumbing: `xdg-desktop-portal`, `xdg-desktop-portal-wlr`, `xdg-desktop-portal-gtk`, `xdg-user-dirs`, `xdg-utils`
- Audio controls: `alsa-utils`, `pavucontrol`
- Files + removable media (optional): `thunar`, `gvfs`, `gvfs-mtp`, `udisks2`
- Browser (for captive portals): `firefox`
- Fonts (HiDPI): `noto-fonts`, `noto-fonts-emoji`, `ttf-jetbrains-mono` (optional)

Then:
- As user `pepper`: run `xdg-user-dirs-update` once.
- Verify portals start in the Sway session: `systemctl --user status xdg-desktop-portal xdg-desktop-portal-wlr`.

## Phase 4 — Battery optimization (do in layers, with measurements)
Goal: low idle watts, low suspend drain, no flicker/instability.

Baseline + regression loop:
- Use `powertop` to identify wakeups and confirm tunables.
- Re-run RAPL “watts” after every significant change.

High-impact knobs (do these first):
- Firmware power mode: `platform_profile=low-power` on battery.
- CPU policy: EPP → `power`/`balance_power` on battery; consider turbo off on battery (optional).
- Radios:
  - Default `rfkill block wwan` unless actively using the modem.
  - Block Bluetooth when unused.
- Display:
  - Default to a conservative brightness on battery (OLED dominates power).
  - Prefer true-black/dark UI themes/wallpapers.

Medium-impact knobs (validate carefully):
- NVMe runtime PM → `auto` (persistent via udev/TLP).
- USB autosuspend for non-critical devices.
- Audit wake sources for `s2idle` drain (`/proc/acpi/wakeup`, per-device `/power/wakeup`).

Intel iGPU power features (test for flicker, keep easy rollback):
- Consider enabling PSR/FBC/DC and confirm via i915 debugfs (`i915_edp_psr_status`, `i915_fbc_status`).

Reference: `power_plan.md` contains the detailed, measured tuning notes for this exact platform.

## Phase 5 — X1 Fold specifics (halfblank + fold UX)
Goal: keep fold/dock behavior, and use OLED-black regions to save watts.

After the native install is booted:
- Install everything from this repo in one go:
  - `x1fold/scripts/install_x1fold_all.sh`
  - This runs the halfblank, Fn/Ctrl and sleep/lid installers, then prints the
    follow-ups below. Add `--webcam` for the IPU6 stack (opt-in: builds DKMS).
  - (The per-subsystem installers still work on their own — see the README.)
- Follow-ups it cannot do for you:
  - Sway lid snippet, as your desktop user (**not** root):
    - `x1fold/scripts/install_x1fold_sway.sh --reload`
  - Enable UI helper (starts on user login):
    - Global: `systemctl --global enable x1fold-halfblank-ui.service`
    - (Alternative) Per-user: `systemctl --user enable --now x1fold-halfblank-ui.service`
  - **Reboot**, then confirm the kernel cmdline took:
    - `grep -o 'button.lid_init_state=[a-z]*' /proc/cmdline` → `open`
    - Without it, lid-close hibernate re-sleeps ~25s after every resume.
- Validate:
  - Dock → switches to half mode.
  - Bottom region is **actually black** (OLED power win).
  - Close lid → hibernates; open → stays awake past the first minute.
  - `x1fold-stay-awake -- sleep 60` → lid close does nothing while it runs.

Docs:
- Halfblank design/architecture: `docs/linux_halfblank_plan.md`
- Package notes: `x1fold/docs/halfblank_packaging_plan.md`

## Phase 6 — Validation checklist (acceptance criteria)
- Boots from NVMe without the live USB.
- Graphics: correct resolution + scaling; backlight control works.
- Input: touch/pen + dock keyboard behave correctly.
- Suspend/resume: no rapid drain, no “random wake” storms.
- Power: idle watts improved vs baseline; no regressions in usability.

Remote-access validation (must pass before doing big changes):
- After booting the native NVMe install, confirm we are **not** on archiso:
  - `cat /proc/cmdline` should NOT contain `archisobasedir=arch`
  - `uname -a` should show the installed kernel (e.g. `6.18.x arch1-1`), not the live ISO’s `*-custom`
- Confirm services:
  - `systemctl status sshd x1fold-wifi-autoconnect x1fold-reverse-ssh@2023`
  - If `localhost:2023` does not come back within a few minutes:
  - Boot the live USB again, mount the native install, and inspect logs:
    - `journalctl --directory=/mnt/var/log/journal -b -1 -u x1fold-reverse-ssh@2023`
    - `journalctl --directory=/mnt/var/log/journal -b -1 -u x1fold-wifi-autoconnect`
  - Also confirm the controller host has no stale listener blocking the bind port:
    - On the controller host: `sudo ss -ltnp | rg ':(2023)\\b'`
    - If port 2023 is held by an old `sshd-session`, terminate that session (or pick a different bind port and enable `x1fold-reverse-ssh@<port>.service`).

## Phase 2.5 — Recovery/debug: Wi‑Fi didn’t start on native boot
Goal: make the installed system bring up Wi‑Fi (for bring-up only) so the reverse tunnel is available after reboot.

From the live USB (opcode sniffer), mount + chroot:
- `mount -o subvol=@ /dev/nvme0n1p3 /mnt && mount /dev/nvme0n1p1 /mnt/boot`
- `arch-chroot /mnt`

Inside the chroot (native install):
- Confirm packages exist: `pacman -Q linux linux-firmware wpa_supplicant dhcpcd iw rfkill openssh`
- Confirm the Wi‑Fi interface/driver appears: `iw dev` and `ip link` (and, if needed, `lspci -k | rg -i '(network|wireless|wifi|iwl|ath|mt76)' -n`)
- Confirm `wpa_supplicant` config exists and is `0600`: `/etc/wpa_supplicant/wpa_supplicant.conf`
- Confirm services enabled:
  - `systemctl is-enabled x1fold-wifi-autoconnect.service || true`
  - `systemctl is-enabled x1fold-reverse-ssh@2023.service || true`
  - `systemctl is-enabled sshd.service`
- Check why autoconnect failed on the previous NVMe boot:
  - If persistent journal exists: `journalctl -b -1 -u x1fold-wifi-autoconnect -u x1fold-reverse-ssh@2023`
  - Otherwise: enable persistence (`mkdir -p /var/log/journal`) and rely on the next boot’s logs.
- If logs show `dhcpcd` (or `wpa_supplicant`) getting SIGTERM right after acquiring a lease, ensure the unit keeps its cgroup alive: set `RemainAfterExit=yes` on `x1fold-wifi-autoconnect.service`.
- If the oneshot Wi‑Fi unit is too brittle (driver comes up late / rfkill), update it to retry for a few minutes (or add a timer) until we have reliable remote access.
- Reboot and re-test that `localhost:2023` comes back while booted from NVMe.

## Phase 7 — Deferred: make it reproducible
Not a focus right now. Priority is making the existing install usable via SSH; document changes here instead of building/polishing repo automation.
