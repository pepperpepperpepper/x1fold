# X1 Fold 16 (21ETS1JM00) Linux Battery Optimization Plan

Target device (checked over `ssh -p 4444 root@localhost`):
- Model: ThinkPad X1 Fold 16 Gen 1 (`product_name=21ETS1JM00`)
- CPU/GPU: Intel Core i7-1250U + Intel Iris Xe (Alder Lake-UP4)
- Storage: WD PC SN740 NVMe
- Radios: Intel CNVi Wi‑Fi + BT (AX211 BT), MediaTek T700 5G modem present on PCIe
- Power: dual batteries (`BAT0` + `BAT1`), ~64.6 Wh combined at full
- Firmware interface: `platform_profile` available (`low-power`, `balanced`, `performance`)
- Suspend: only `s2idle` advertised (`/sys/power/mem_sleep` shows `[s2idle]`)

## Guiding principles
1. **Measure first**: always compare before/after with the same workload.
2. **Prefer “standard knobs”** (platform profile, EPP, runtime PM) before exotic kernel params.
3. **Make changes reversible**: every tuning should have a clear “off switch”.
4. **Avoid fighting daemons**: pick one main power manager (TLP *or* power-profiles-daemon).

## Measurement (baseline + regression checks)
### Quick “real watts” via Intel RAPL (works even when battery reporting is weird)
Measure platform power (`psys`) and CPU package (`package-0`) with a short script:
```bash
python - <<'PY'
import time
from pathlib import Path
def read_int(p): return int(Path(p).read_text().strip())
pkg = "/sys/class/powercap/intel-rapl:0/energy_uj"
psys = "/sys/class/powercap/intel-rapl:1/energy_uj"
p0,s0,t0 = read_int(pkg), read_int(psys), time.time()
time.sleep(10)
p1,s1,t1 = read_int(pkg), read_int(psys), time.time()
dt=t1-t0
print("pkg_w", (p1-p0)/1e6/dt)
print("psys_w", (s1-s0)/1e6/dt)
PY
```

### Use `powertop` for wakeups + tunables
- Calibrate once (while on battery): `powertop --calibrate`
- Inspect: `powertop` (interactive) or `powertop --html=/tmp/powertop.html`
- Don’t blindly “tune everything”; treat it as a checklist for *persistent* settings (udev/TLP).

## Recommended “Linux flavor”
### If you want **best battery with lowest maintenance**
- **Fedora Workstation (GNOME)** or **Fedora Kinoite/Silverblue**:
  - GNOME integrates tightly with **power-profiles-daemon**, `platform_profile`, suspend policies, and modern Wayland defaults.
  - Fedora generally ships very recent kernel/Mesa, which matters for Intel Xe power features.

### If you want **maximum control + easiest integration with this repo**
- **Arch Linux (what you already run here)**, but treat it as a *purpose-built appliance*:
  - Minimal userland + a single compositor (Wayland) + only required services.
  - Add explicit power tuning (TLP or a small systemd-managed script) so behavior is repeatable.

### Desktop/compositor choice (battery-oriented)
- Prefer **Wayland** over Xorg for modern Intel (better end-to-end power behavior and fewer legacy components).
- Prefer a **lighter compositor** (Sway/river/Wayfire) if you don’t need full GNOME/KDE ergonomics.
- If you want “it just works” + on-screen UI for power profiles, GNOME is the simplest.

## High-impact knobs (do these first)
### 1) Platform profile (ThinkPad firmware power mode)
This machine supports `platform_profile`: `low-power`, `balanced`, `performance`.
- Check: `cat /sys/firmware/acpi/platform_profile`
- Set: `echo low-power > /sys/firmware/acpi/platform_profile`

Plan:
- Default to `low-power` **on battery**.
- Allow quick user override (hotkey / CLI).

### 2) CPU policy: EPP, turbo, and sustained power
Current state observed:
- Governor: `powersave`
- EPP: `balance_performance` (can be made more battery-friendly)

Plan (battery mode):
- Set EPP to `power` (or `balance_power`) via sysfs (`energy_performance_preference`) or via a power manager.
- Consider disabling turbo on battery (`/sys/devices/system/cpu/intel_pstate/no_turbo=1`) *or* cap max perf (`max_perf_pct`).
- Optional: lower RAPL package limits (PL1/PL2) for smoother thermals + better battery efficiency.

RAPL is available at `/sys/class/powercap/intel-rapl:*` (package limits defaulted to ~29W here).

### 3) Radios: WWAN and Bluetooth are often “free watts”
This unit exposes a 5G modem and BT; disable them when unused:
- WWAN: `rfkill block wwan` (or disable ModemManager entirely if installed)
- Bluetooth: `rfkill block bluetooth`

Wi‑Fi:
- Keep power save enabled (already observed `Power save: on` via `iw`).

### 4) Display (biggest real-world factor on a foldable OLED)
Plan:
- Default brightness target on battery (e.g., 20–35%).
- Prefer dark/true-black UI themes/wallpaper (OLED makes this materially valuable).
- Make “halfblank” actually black (your existing work) — that’s a *display power* win on OLED, not just UX.

Intel panel features to explore (test carefully; regressions can be visible as flicker):
- PSR (Panel Self Refresh): currently reports `PSR mode: disabled` in `i915_edp_psr_status`.
- FBC (Frame Buffer Compression): check `i915_fbc_status` when the panel is actively scanning out.

If you decide to test forcing these:
- Kernel/module params: `i915.enable_psr=1` (or `2`), `i915.enable_fbc=1`, `i915.enable_dc=4`
- Verify via:
  - `/sys/kernel/debug/dri/*/i915_edp_psr_status`
  - `/sys/kernel/debug/dri/*/i915_fbc_status`
  - Visual stability (no flicker/blanking artifacts)

## Medium-impact knobs (usually safe, but validate)
### NVMe power management
Observed: NVMe runtime PM was `on` (not autosuspending).

Plan:
- Set NVMe runtime PM to `auto` (persistent via udev rule).
- Consider tuning NVMe APST latency (`nvme_core.default_ps_max_latency_us=...`) only if stable.

Validation:
- `cat /sys/class/nvme/nvme0/device/power/control`
- Watch for dmesg timeouts/resets after suspend/resume.

### PCIe ASPM policy
ASPM policy currently shows `[default] performance powersave powersupersave`.

Plan:
- Prefer `powersave`/`powersupersave` if it doesn’t break devices.
- Don’t use `pcie_aspm=force` unless you know a device is incorrectly reporting ASPM capability.

### USB autosuspend + wake sources
Plan:
- Enable autosuspend for non-critical USB devices (keyboard dock, storage, etc.) where safe.
- Disable unwanted wakeup sources while suspended (`/proc/acpi/wakeup`, per-device `/power/wakeup`).

## Suspend (s2idle) battery drain plan
Because only `s2idle` is available, “sleep drain” is mostly about wake sources and keeping SoC in low power:
- Ensure radios are in low-power state or blocked during suspend (especially WWAN).
- Audit wake sources:
  - `cat /proc/acpi/wakeup`
  - `grep . /sys/bus/*/devices/*/power/wakeup 2>/dev/null | rg enabled`
- Consider a `systemd-sleep` hook that:
  - blocks WWAN/BT on suspend,
  - restores on resume (optional).

## What to install / enable (Arch-centric)
Pick **one** of these strategies:

### Strategy A (simple): `power-profiles-daemon`
- Pros: integrates with `platform_profile`; GNOME UI support.
- Cons: limited tuning scope (doesn’t cover everything TLP does).

### Strategy B (max battery): `tlp`
- Pros: broad device coverage (USB autosuspend, PCIe runtime PM policies, radio toggles, etc.).
- Cons: needs careful config; don’t run alongside `power-profiles-daemon`.

Additional “usually worth it” on Intel laptops:
- `thermald` (smoother thermal/power behavior)
- `powertop` (already present here) for auditing
- `intel-ucode` (microcode updates)
- `irqbalance` (sometimes helps, sometimes hurts; measure)

## Making it reproducible in this repo (suggested deliverables)
1. A single script with conservative tunings (battery/AC modes), e.g. `tools/x1fold_power.sh`.
2. systemd units:
   - `x1fold-power-apply.service` (apply at boot)
   - `x1fold-power-apply-resume.service` (apply after resume)
3. Optional config file:
   - `/etc/x1fold-power.conf` to toggle risky features (PSR/FBC, turbo off, NVMe APST, etc.)

## Suggested rollout order
1. **Brightness + OLED-black UI** + `platform_profile=low-power` on battery.
2. CPU EPP to `power` and (optionally) turbo off on battery.
3. Disable WWAN/BT when unused.
4. NVMe runtime PM (`auto`) + USB autosuspend.
5. Optimize s2idle wake sources and suspend hooks.
6. Only then experiment with i915 PSR/FBC/DC params (validate for flicker).

