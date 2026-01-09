[Last updated: 2026-01-08 @ 01:35 UTC]

### 2026-01-08 @ 01:35 UTC — Magnet/keyboard “dock” signal is ACPI `EC.CMMD` bit7; `\_SB.DEVD.GDST` returns it (relevant to HALFBLANK trigger)
- **Why we care:** on Lenovo’s intended Windows flow for X1 Fold, **docking the magnetic keyboard** is the user-visible trigger for the **HALFBLANK / UNBLANK** behavior (desktop height change + digitizer mode flip). On Linux, this gives us a clean **attach/detach signal** to drive the halfblank switch logic.
- **Raw source field:** `\_SB.PC00.LPCB.EC.CMMD` (EC field at offset `0xC1`, 8-bit) encodes:
  - `DOCK = CMMD >> 7` (bit 7): `1` = docked, `0` = undocked
  - `MODEID = CMMD & 0x7f` (bits 0–6): Lenovo mode identifier used by `_Q2E` (see below)
- **Convenience getter:** `\_SB.DEVD.GDST` (in `acpi_extract_baremetal/ssdt15.dsl`) reads `EC.CMMD`, extracts `DOCK`, stores it into `\_SB.DEVD.DOST`, and returns `DOST` (`0/1` dock state).
- **Event path:** EC query `\_SB.PC00.LPCB.EC._Q2E` (“Convertible Button”, in `acpi_extract_baremetal/dsdt.dsl`) reads `EC.CMMD`, updates `PMMD`/`LVMD`, then fires Lenovo hotkey notifications:
  - `HKEY.MHKQ(0x60C0)` when dock state changes (`PMMD`)
  - `HKEY.MHKQ(0x60F0)` when mode changes (`LVMD`)
  - `Notify(DEVD, 1)` to signal a device-check on `\_SB.DEVD`
- **Linux evaluation (ACPI namespace paths, not filesystem paths):**
  - `echo '\\_SB.DEVD.GDST' | sudo tee /proc/acpi/call; cat /proc/acpi/call`
  - `echo '\\_SB.PC00.LPCB.EC.CMMD' | sudo tee /proc/acpi/call; cat /proc/acpi/call`
  If these return `AE_NOT_FOUND`, we must re-derive the correct path from the live ACPI tables on that specific unit (but the extracted DSDT/SSDT on b0xx includes these exact names).

### 2026-01-07 @ 04:40 UTC — Windows screenshots + Wacom HID dumps: HALFBLANK includes a desktop/display config change; `0x0A` is a digitizer mode field
- **New Windows captures pulled into repo (portable, via `ssh -p 4400 Administrator@localhost`):**
  - Screenshot classifier: `traces/windows_etl_exports/halfblank_screens_20260106-222645_focus/` and `traces/windows_etl_exports/unblank_screens_20260106-222717_focus/`
  - Marked WPR (with screenshots): `traces/windows_etl_exports/halfblank_20260106-222748_focus/` and `traces/windows_etl_exports/unblank_20260106-223930_focus/`
  - Wacom HID feature dumps: `traces/windows_etl_exports/wacom_halfblank_20260106-231916_focus/` and `traces/windows_etl_exports/wacom_unblank_20260106-231936_focus/`
- **Screenshots show HALFBLANK includes an OS-visible desktop height change:** the captured virtual screen size toggles between:
  - normal: `1012x1280` (≈ `2024x2560` at 200% scaling)
  - halfblank: `1012x620` (≈ `2024x1240` at 200% scaling)
  So the “blanked” region is **outside the desktop** (a display config/desktop resize), not black pixels rendered into an unchanged frame. This does **not** by itself prove whether panel rails/pixels were powered down; rail proof requires PP telemetry (PP_STATUS/PP_CONTROL or equivalent).
- **Wacom HID feature reports confirm the `0x0A` delta is a digitizer mode field, not a hidden panel rail control:**
  - Only `WACF2200&COL02` changes across HALFBLANK/UNBLANK; `COL03/COL05/COL07` remain stable.
  - `ReportId=0x03`: bytes **[10..15]** toggle exactly with the Lenovo SPB `len=1034` write delta:
    - normal/unblank: `00 00 00 00 00 00`
    - halfblank: `9c 18 2c 28 33 1a`
  - `ReportId=0x04`: bytes **[14..15]** toggle `00 00 ↔ 33 1a` (matching the query/read signature).
- **Implication / corrected mental model:** yes, we can write to I²C (`00:15.1` → slave `0x0A`) and toggle the same mode field Windows uses, but the “halfblank” effect on Windows is implemented as a **display configuration change** that likely reacts to this digitizer/mode signal. This is separate from the earlier PPS/`PP_CONTROL` work (blocked by ACPICA >4 GiB SystemMemory writes) and separate from the still-missing `00:15.3` (I2C3).
- **New “rail” telemetry capability (Windows):** `C:\trace\halfblank\pp_regs_snapshot.ps1` reads IGD BAR0 (`00:02.0` @ `0x10/0x14`) and snapshots `PP_STATUS/PP_CONTROL` at offsets `0xC7200/0xC7204` via CHIPSEC.
  - Integrated into `C:\trace\halfblank\capture_halfblank_marked.ps1` behind `-CapturePpRegs` (writes `before_pp_regs.json` / `after_pp_regs.json` into the focus dir).
  - Baseline on `portable` (via `ssh -p 4400 Administrator@localhost`): `IGD BAR0=0x603D000000`, `PP_STATUS=0x80000008`, `PP_CONTROL=0x00000067` (see `traces/windows_etl_exports/unblank_20260107-004749_focus/before_pp_regs.json`).

### 2026-01-07 @ 16:47 UTC — Marked HALFBLANK/UNBLANK w/ PP snapshots: iGPU `PP_STATUS/PP_CONTROL` unchanged; I²C `len=1034` payload delta persists
- **New marked captures pulled into repo (portable):**
  - `traces/windows_etl_exports/halfblank_20260107-074913_focus/` (markers: 2026-01-07T07:49:25-05:00 → 07:49:43-05:00)
  - `traces/windows_etl_exports/unblank_20260107-084645_focus/` (markers: 2026-01-07T08:46:50-05:00 → 08:47:10-05:00)
- **Screenshots (ground truth for what the OS sees):** these runs reproduce the desktop-height toggle:
  - HALFBLANK: `1012x1280` → `1012x620` (≈ `2024x2560` → `2024x1240` at 200% scaling)
  - UNBLANK: `1012x620` → `1012x1280`
- **PP telemetry (Windows, via CHIPSEC):** `PP_STATUS/PP_CONTROL` stayed constant across the action:
  - HALFBLANK: `0x80000008 / 0x00000067` before → `0x80000008 / 0x00000067` after (`*_pp_regs.json`)
  - UNBLANK: `0x80000008 / 0x00000067` before → `0x80000008 / 0x00000067` after
  This means the **standard iGPU eDP PPS pair** did not transition for HALFBLANK/UNBLANK on this unit; if pixels/rails are changing, it is not via this `PP_*` pair.
- **Vendor ETW confirms the concrete “halfblank” control primitive remains the I²C `0x0A` 1034-byte write:**
  - HALFBLANK write includes the 6-byte delta `9c 18 2c 28 33 1a` at offsets `0x0c..0x11` of the 1034-byte payload (`vendor_focus.txt` timestamp ~`24299329`).
  - UNBLANK uses the same 1034-byte payload header but zeros at offsets `0x0c..0x11` (`vendor_focus.txt` timestamp ~`13126545`).
- **DxgKrnl shows an explicit composition-path clip to the half-height region during HALFBLANK:** in `dxg_focus.txt` near the same I²C write, there are:
  - `FlipMultiPlaneOverlay` rows for plane index `2` with `SrcRect/DstRect` height `2464` but `ClipRect.bottom=1240` (≈ half-height), and
  - matching `DisplayConfigPlaneChange` rows with `PlaneIndex=2` and `ClipRect.bottom=1240` (timestamp ~`24297451`).
  This is consistent with the OS/DWM clipping the scanout content to the top-half region (and leaving the remainder blank/black in composition). It still does **not** prove anything about panel-internal pixel power; it only proves a GPU/display pipeline change is part of the halfblank implementation on this unit.
- **Kernel-Acpi trace still shows no AML hook involvement** (no `_DSM/_DOS/_DSS/IMMC/GGOV/SGOV` in the focus window), matching the model that LenovoModeSwitcher + HIDI2C is driving the change.

### 2025-11-29 @ 04:20 UTC — Kprobe proves ACPICA drops >4 GiB writes before the handler
- Added `drivers/acpi_mem_logger/` (a tiny kprobe module) to watch `acpi_ex_system_memory_space_handler`. Built it on b041 (`make -C /usr/lib/modules/$(uname -r)/build M=/root/acpi_mem_logger/acpi_mem_logger modules`) and inserted with `addr_min=0x603d000000` so only the PP register window is logged.
- With `TABLE_NAME=GFXPPS` still loaded, ran `/root/panel_power_cycle.sh` and tailed `journalctl -k | grep acpi_mem_logger | tail -n 30`. Every event was `fn=0 addr=0x603d0c7200 width=32 value=0x0`; there were **no** `fn=1` entries, meaning ACPICA only polled `PP_STATUS` and never issued the corresponding write to `PP_CONTROL` (`0x603d0c7204`) even though the AML returned `0x66/0x67`.
- `PP_STATUS`/`PP_CONTROL` stayed pegged at `0x80000008 / 0x00000067` during the trace, but a manual `intel_reg write 0x000c7204 0x66` still drops the rail immediately, so the hardware path works—it’s the interpreter that refuses to touch >4 GiB SystemMemory regions.
- Next: either inject a kernel helper/pseudo OpRegion that performs the MMIO write on behalf of AML, or spoof `EDMX` via GNVS so Lenovo’s IMMC path can run prior to these high-address accesses. Until one of those exists, Option C remains telemetry-only; PPOF/PPON can’t toggle PPS because ACPICA never forwards the write.

### 2025-11-29 @ 02:31 UTC — Option C overlay loads, but AML writes never hit the PCH PP registers
- Compiled `acpi/SSDT-GFX0-PPS.dsl` with the live GTTMMADR (`0x603d000000`) and the PCH panel offsets (`PP_STATUS @ 0xC7200`, `PP_CONTROL @ 0xC7204`), exposing mutex-guarded helper methods `PPOF/PPON`, a synthetic power resource `VPPS`, and aliases `PP3/PP0`. Deployed the AML to b041 via `/root/panel_power_overlay.sh` (`TABLE_NAME=GFXPPS`) after unloading the earlier IMMC overlay so there are no `_PSx` collisions lingering in the namespace.
- Refreshed `/root/panel_power_cycle.sh` to prefer the new methods (falls back to `VPPS._OFF/_ON`, `V0PR._OFF/_ON`, and `_PS3/_PS0` if present) and to log the actual PCH registers plus `/sys/class/drm/card1-eDP-1/status`. Each run now prints:  
  ```
  -- Before power-off --  PP_STATUS=0x80000008  PP_CONTROL=0x00000067
  -- After power-off --   PP_STATUS=0x80000008  PP_CONTROL=0x00000067
  -- After power-on --    PP_STATUS=0x80000008  PP_CONTROL=0x00000067
  ```  
  i.e., the rail never drops even though ACPI reports success for `PPOF/PPON`.
- Instrumentation shows the AML methods return the values we write (`PPOF -> 0x66`, `PPON -> 0x67`), but `intel_reg read 0x000c7200/0x000c7204` and `devmem 0x603d0c7204` confirm the hardware stays at `0x80000008 / 0x00000067`. Manually writing the same register via `intel_reg write` or `devmem` toggles PP_STATUS immediately, proving the sequencer responds when MMIO is touched from the OS. Conclusion: Linux’s ACPI `SystemMemory` handler is ignoring (or silently dropping) these >4 GiB writes, so Option C cannot prove the rail drop until we either patch the interpreter or poke the registers from kernel/user space instead of AML.
- With GFXPPS loaded, `\EDMX` still reads `0x0` and `\_SB.GGOV(\EDMX)` reports `0x0`, matching the earlier finding that Lenovo’s governor bit never latches even when we bypass IMMC. This reinforces that we’ll need either a GNVS override for EDMX or a kernel helper that programs PP_CONTROL directly while the AML shim sticks to telemetry.
- Next steps: investigate why `acpi_ex_system_memory_space_handler` ignores these writes (trace the handler, test with a minimal SSDT writing to another high MMIO window, or temporarily allow AML to call a tiny OpRegion that proxy-writes via an EC field). In parallel, keep the `devmem`/`intel_reg` commands handy—they demonstrate the PPS can be forced off/on today even though the AML path remains inert.

### 2025-11-28 @ 13:45 UTC — IMMC overlay runs, but PPS never drops
- ISO build 041 is now running on b041 with the rebuilt `6.16.10-custom` kernel (`CONFIG_DRM_I915_DEBUG{,_MMIO}=y`, `mmio_debug=-1` by default), so `intel_reg` can finally read the PCH panel registers at `0x000c7200/0x000c7204` (`PP_STATUS=0x80000008`, `PP_CONTROL=0x00000067`).
- Loading `SSDT-GFX0-IMMC-PSx.aml` via `/root/panel_power_overlay.sh` still emits Lenovo’s IMMC mailbox traces (`Set IMMC Command 0x30003/0x30006`, `Arg2 is Port Number :: 0x300`), yet calling `_SB.PC00.GFX0._PS3/_PS0` leaves the PP registers unchanged—rail never actually powers down.
- `panel_power_cycle.sh` needs an update to read the PCH offsets (0xC7200/0xC7204) instead of the legacy GTT window; for now it reports “unavailable” even though `intel_reg` works.
- Next focus: re-extract the exact IMMC tuples from `dsdt.dsl`/`ssdt18.dsl` and verify whether GGOV/SGOV/EDMX gating prevents those writes from toggling the rail. If the tuples look right but PPS still sticks high, fall back to Option C (`SSDT-GFX0-PPS.dsl`) to prove the sequencer can be forced off, then replicate Lenovo’s gating path.
- Updated `/root/panel_power_cycle.sh` to read the live PCH PP registers (`0x000c7200/0x000c7204`). Running it on b041 still shows `PP_STATUS=0x80000008` / `PP_CONTROL=0x00000067` before/after `_PS3/_PS0` with `/sys/class/drm/card1-eDP-1/status` stuck at `connected`, confirming again that the IMMC tuple doesn’t drop the rail.
- Instrumented Lenovo’s governor bits: `\EDMX` currently evaluates to `0x0`, `\_SB.GGOV(\EDMX)` returns `0x0`, and neither `\_SB.SGOV(\EDMX, One)` nor `_DSM(...,0x15,...)` with `Arg3={0x01}` / `{0x03}` changes that value. The guard bit therefore remains locked even when we call the published DSM function, which explains why the IMMC path does no work.

### 2025-11-28 @ 15:20 UTC — Located the EDMX storage + correct `_DSM` call signature
- `EDMX` is a 32-bit `FieldUnit` inside `GNVS` (`OperationRegion (GNVS, SystemMemory, 0x936A4000, 0x0CE1)`; see `dsdt-baremetal.dsl:1320-3238`). Lenovo’s helper methods `GGOV/SGOV` take a *descriptor* pointing at that field: `_DSM` case `0x15` calls `\_SB.SGOV (EDMX, value)` where `value` is derived from `Arg3[0]` (bit0 selects “query vs set”, bit1 selects ON vs OFF). The method then re-reads the same descriptor via `GGOV` to populate the return buffer.
- Correct `_DSM` invocation requires **buffer arguments**, not packages. The working syntax (via `/proc/acpi/call`) is:  
  ```bash
  GUID=bc6415b3e1deb60429d15c71fbadae414   # 3e5b41c6-eb1d-4260-9d15-c71fbadae414
  echo "\\_SB.PC00.GFX0._DSM $GUID 0x1 0x0 b00" | sudo tee /proc/acpi/call  # caps bitmap -> 0x002DE7FF
  ```
  The last argument (`bXX…`) is a hex string with two digits per byte. Passing `b01` drives `_DSM` case 0x15’s “set 0” branch, `b03` picks the “set 1” branch, and `b00` just queries.
- Even with the correct buffer form, `_DSM(...,0x15, b03)` still leaves both `\EDMX` and `\_SB.GGOV(\EDMX)` at `0x0` on b041. That confirms firmware never latches the request—`SGOV` writes to the governor register but the platform (likely PMC/SMM) forces it low immediately. Conclusion: the IMMC tuples can only work once we either spoof the governor bit in GNVS or drive the underlying GPIO/PSF path directly (Option C).

### 2025-11-21 @ 19:25 UTC — Initramfs hook to preload i915 with `mmio_debug=1`
- Added a dedicated mkinitcpio hook (`/usr/lib/initcpio/hooks/mmio_debug` + install stub) that runs immediately after the `base` hook, before `udev` autoloads GPUs. It unloads any preloaded `i915` instance and re-modprobes it with `mmio_debug=1`, logging to `/run/initramfs/mmio_debug.log`. Kernel command line token `mmio_debug=off` skips the hook.
- Updated `airootfs/etc/mkinitcpio.conf.d/archiso.conf` so `HOOKS=(base mmio_debug udev psf_fix …)`; new builds will embed the hook automatically, guaranteeing `intel_reg` access to `PP_STATUS/PP_CONTROL` as soon as we reboot into a rebuilt initramfs.
- Mirrored the hook onto b037 (`/usr/lib/initcpio/{install,hooks}/mmio_debug`) and updated `/etc/mkinitcpio.conf.d/archiso.conf`, but `mkinitcpio -k 6.16.10-custom -c … -g /boot/initramfs-linux-custom.img` still fails with “No space left on device” because `/boot` (103 MiB) is full (`/boot/arch` already consumes ~96 MiB). The previous initramfs has been restored to keep the host bootable; to activate the new hook we must free space (or stage the image elsewhere), rerun `mkinitcpio`, and reboot so the hook can preload i915 before telemetry tests.

### 2025-11-28 @ 12:15 UTC — Kernel rebuilt with i915 MMIO debug enabled by default
- Tweaked `build.sh`/`custom-kernel/base-config` so `CONFIG_EXPERT=y` and `CONFIG_DRM_I915_DEBUG=y`/`CONFIG_DRM_I915_DEBUG_MMIO=y` land in the custom kernel. After flashing ISO build 041 to b041, `cat /sys/module/i915/parameters/mmio_debug` now returns `-1` immediately; the initramfs hook still logs “modprobe … failed”, but that’s benign because the driver already exposes MMIO debug.
- Verified `intel_reg` access works again (e.g., `intel_reg read 0x000c7200` → `0x80000008`, `intel_reg read 0x000c7204` → `0x00000067`). Re-ran the IMMC overlay: `_SB.PC00.GFX0._PS3/_PS0` execute via `/proc/acpi/call` with no errors, yet the PCH PP registers stayed fixed at `0x80000008/0x00000067`, proving the rail never dropped.
- Next actions: update `panel_power_cycle.sh` to read the PCH PP registers so the telemetry script shows real values, and keep investigating the IMMC tuples/GGOV bits—right now `_PS3` remains a no-op even though we can finally observe PPS directly.

### 2025-11-08 @ 02:26 UTC — IMMC-backed overlay live on b037
- Built and pushed `acpi_overlays/SSDT-GFX0-IMMC-PR.dsl` (Option A) with Lenovo's own mailbox tuples `IMMC(0x03, 0x03E8, port, 0, 0)` and `IMMC(0x06, 0x03E8, port, 0, 0)`; exposes helper methods `\_SB.PC00.GFX0.IMOF` / `\_SB.PC00.GFX0.IMON`, synthetic `V0PR`, and advertises it through `_PR0/_PR3`.
- Loaded the table via configfs (`/sys/kernel/config/acpi/table/GFXPR/aml`) on `archlinux-opcode-sniffer-b037`; `acpi_call` now resolves `\_SB.PC00.GFX0.IMOF`, `\_SB.PC00.GFX0.IMON`, and `\_SB.PC00.GFX0.V0PR._OFF` / `_ON` without `AE_NOT_FOUND`.
- Calling `\_SB.PC00.GFX0.V0PR._OFF` / `_ON` emits the expected ACPI debug traces from firmware's IMMC handler:
  - `Set IMMC Command 0x30003` / `BIOS_MBX_DEC_HPD_COUNT`, `Arg2 is Port Number :: 0x300` (matches `DD02._ADR()`), proving Lenovo's mailbox path executes.
- Snapshot around the OFF/ON cycle (intel_reg still gated):
  ```text
  -- BEFORE: 2025-11-08T02:26:12.801383341+00:00
  /sys/class/drm/card1-eDP-1/status: connected
  PP_STATUS unavailable (intel_reg gated)
  00:15.3 absent (expected)
  -- AFTER OFF: 2025-11-08T02:26:13.829349645+00:00
  /sys/class/drm/card1-eDP-1/status: connected
  PP_STATUS unavailable (intel_reg gated)
  00:15.3 absent (expected)
  -- DONE: 2025-11-08T02:26:14.856532112+00:00
  ```
- `intel_reg read PP_STATUS/PP_CONTROL` remains blank because the platform's MMIO guard is still enabled; need a workaround (e.g., disable guard or use i915 debugfs) to capture PPS transitions explicitly.
- Added `scripts/panel_power_overlay.sh` to load/unload the AML via configfs; `AML_PATH=/root/SSDT-GFX0-IMMC-PSx.aml /root/panel_power_overlay.sh load` is the current working sequence.
- Added `scripts/panel_power_cycle.sh`; on b037 it reports `PP_STATUS=(unavailable)` / `PP_CONTROL=(unavailable)` because the MMIO guard still suppresses `intel_reg`, but each _PS3/_PS0 invocation shows the IMMC trace (`Set IMMC Command 0x30003` / `0x30006`, `Arg2 is Port Number :: 0x300`) in `dmesg`, confirming the mailbox path executes.
- Staged Option B (`acpi/SSDT-GFX0-DSM-IMMC.dsl`) and Option C (`acpi/SSDT-GFX0-PPS.dsl`). Option B compiles but attempting to load it alongside the firmware `_DSM` still returns `{0x00}` via `/proc/acpi/call`, so we may need a DSDT rename (e.g., move the original `_DSM` to `ODSM`). Option C ships as a lab-only skeleton; remember to replace `GTTB` with the live BAR0 value before use.

### 2025-11-07 @ 07:55 UTC — Working plan to bypass Lenovo’s panel power guards
- Locked-in observations:
  - `STD3`/`RTD3` stay at `0x1`, so Lenovo never instantiates `\_SB.PC00.GFX0.VxPR`; any attempt to call those PowerResources fails with `AE_NOT_FOUND`.
  - `\_SB.PC00.GFX0._DSM` responds to GUID `3e5b41c6-eb1d-4260-9d15-c71fbadae414` and advertises bit 0x15, but the firmware’s implementation is inert (`Arg3={0x01,...}` or `{0x03,...}` always returns `{0x00,...}` and leaves `PP_STATUS`/`PP_CONTROL` unchanged).
  - DRM DPMS (`modetest`) and `bl_power` only dim; PPS never drops, so they cannot be used as a proof of “panel power off”.
  - `_SB.PC00.GFX0._PS3/_PS0` remain stubs (no AML body), matching the no-op behaviour we see at runtime.
- Three escalation options that avoid chasing Lenovo’s guarded `VxPR` path:
  1. **Option A — SSDT overlay with IMMC-backed `_PS3/_PS0`:** add `_PS3/_PS0` methods under `\_SB.PC00.GFX0` that invoke Lenovo’s own `\_SB.IMMC(0x12,...)` / `(0x13,...)` tuples (taken from the guarded DSM blocks) and publish a synthetic `V0PR` PowerResource whose `_OFF/_ON` wrap those methods. Load via configfs so the kernel immediately has callable `_PSx` hooks without requiring `STD3==0x2`.
  2. **Option B — Override only `_DSM(...,0x15,...)`:** supply an SSDT that intercepts the i915 GUID, proxies function 0 responses, but routes function 0x15 to the same `\_SB.IMMC` calls. Userspace can keep issuing the existing `_DSM` commands while the shim performs the real work.
  3. **Option C — Direct PPS control from AML:** as a last resort, create a dynamic `OperationRegion` over IGD’s GTTMMADR and flip `PP_CONTROL[0]` inside AML `_PS3/_PS0`. This bypasses firmware entirely; treat it as lab-only because bad timing can wedge the eDP link until the next reset.
- Guard rails and instrumentation:
  - Re-use the `intel_reg read PP_CONTROL PP_STATUS` snapshots and `/sys/class/drm/card?-eDP-?/status` checks before/after each call to prove a real panel power cycle.
  - Keep the kprobe on `acpi_ex_system_memory_space_handler` handy to confirm any IMMC-based solution writes the same GNVS/PMC regions Lenovo uses.
  - Maintain an SSH session while testing Option C; if the link wedges, `echo 1 > /sys/kernel/debug/dri/0/i915_display_reset` or a reboot will recover.
- Next actions: extract the exact IMMC argument tuples from `dsdt.dsl`/`ssdt18.dsl`, prototype Option A in `SSDT-GFX0-IMMC-PSx.dsl`, and validate that `_PS3/_PS0` finally drop/re-raise PPS. If IMMC is also inert, fall back to Option C to prove end-to-end control while we analyse `GGOV/SGOV/EDMX` further.

### 2025-11-07 @ 08:10 UTC — Connector `_DOS/_DSS` test harness in place
- Added `scripts/panel_dss_test.sh`: exercises the ACPI Video path (`\_SB.PC00.GFX0._DOS` + `DDxx._DSS`) and captures `PP_STATUS` / `PP_CONTROL` along with DRM connector/backlight state. Default target is `DD02` with `_DSS 0 → 1`, but the script supports `standby`, `suspend`, and raw `state` values plus optional restore codes.
- Usage:
  - Ensure `acpi_call` is loaded (`/proc/acpi/call` writable) and `intel-gpu-tools` present.
  - Run as root, e.g. `sudo scripts/panel_dss_test.sh off-on` or `sudo scripts/panel_dss_test.sh standby`.
- The helper prints `_DCS/_DGS` before toggling, runs `_DOS` with the requested value (default `0x1`), applies `_DSS`, waits ~1 s, dumps PPS/connector telemetry, and restores the panel. Adjust `--target` to aim at other connectors if needed.
- Next: execute the script on b037 while logging PPS to see whether `_DSS` actually drops the panel rail; if not, try `modetest -s <conn>@<crtc>:0` immediately afterwards to compare behaviour.

### 2025-11-07 @ 22:08 UTC — `_DOS/_DSS` attempts and DPMS toggle on b037 show no panel power drop
- Connected to `archlinux-opcode-sniffer-b037` (`ssh -p 2222 root@localhost`), loaded `acpi_call`, and confirmed Lenovo’s global gating bits remain set: `\STD3 -> 0x1`, `\RTD3 -> 0x1`.
- Issued connector-level ACPI video calls on the eDP node (`\_SB.PC00.GFX0.DD02`):
  - `_DOS 0x1` returned `0x0`.
  - `_DSS 0x0`, `_DSS 0x2`, `_DSS 0x3`, and `_DSS 0x1` each returned `0x0`, but `_DCS` stayed `0x0` before and after every invocation. No i915 panel messages appeared in `dmesg`, and the console stayed lit.
- Toggled the DRM DPMS property (`modetest -M i915 -w 262:DPMS:3` followed by `...:0`): the interface accepted the property but `/sys/class/drm/card1-eDP-1/dpms` remained “On”, and there were no PPS/telemetry changes (intel_reg still blocked by the MMIO guard, yielding empty output).
- `lspci -nn` continues to show only `00:15.0`/`.1` (I²C0/1); `00:15.3` is still absent, so none of these steps touched the PSF/IOSF lane.
- Conclusion: Lenovo’s ACPI Video hooks behave like stubs on this platform—just like `_PSx` and `_DSM 0x15`—so neither `_DSS` nor DPMS gives us a callable path to cut panel power. Need to proceed with the IMMC-backed overlay (Option A/B) or, as a fallback, the direct PPS AML shim.

### 2025-11-07 @ 07:25 UTC — GFX0 panel power still gate-kept by firmware
- Booted b037 with `acpi_osi="Windows 2020" acpi_osi=!Linux` appended to `00-archiso-linux-custom.conf`, but runtime probes (`\STD3`/`\RTD3` via `acpi_call`) still report `0x1`. Lenovo’s guarded `VxPR` PowerResources are therefore not instantiated; calling `\_SB.PC00.GFX0.V0PR._OFF` continues to return `AE_NOT_FOUND`.
- Refreshed `/tmp/dsdt.dsl` and `/tmp/ssdt18.dsl` after the reboot. Installed `acpi_call-dkms` post-boot (prior initcpio rebuild failed again due to low ESP space, but the DKMS module itself loads) and reinstalled `intel-gpu-tools` for PPS telemetry.
- Evaluated `\_SB.PC00.GFX0._DSM` using the i915 GUID `3e5b41c6-eb1d-4260-9d15-c71fbadae414`. Function 0 now returns the expected bitmap `0x002DE7FF`, confirming that bit 0x15 is advertised. However, both control attempts—`Arg3={0x01,0,0,0,0}` (clear) and `Arg3={0x03,0,0,0,0}` (set)—return `{0x00,...}` and leave `PP_STATUS` (`0x00000067`), `PP_CONTROL` (`0x125c0001`), `/sys/class/drm/card1-eDP-1/status`, and the backlight unchanged, so function 0x15 is effectively a no-op on this platform.
- Revalidated that panel-level DPMS via DRM (`modetest -M i915 -w 262:DPMS:3`) and `bl_power=4` only cut the backlight; PPS never drops, so those paths do not trigger a true panel power cycle. `_SB.PC00.GFX0._PS3/_PS0` remain empty stubs and likewise leave telemetry unchanged.
- Next up: inspect the GGOV/SGOV path guarding `EDMX` and neighbouring DSM functions (0x12/0x13 via `IMMC`); consider an SSDT overlay to supply our own PowerResource if firmware never exposes `STD3==0x02`.

### 2025-10-28 @ 04:45 UTC — EFI-stub breadcrumbs + runtime fixups staged
- Added `custom-kernel/patches/0007-efi-x86-stub-psf-replay-and-breadcrumbs.patch.enabled`: the stub now writes progress into the `PsfStubStatus-51c1bf6e-...` EFI variable, keeps P2SB exposed until an ExitBootServices callback replays the PSF clears, and only re-hides once the second pass completes. Expect new stages (70/80/90) once the kernel is rebuilt.
- Device ID sanity: I²C3 should enumerate as `8086:51EA` on Alder Lake-LP, but older logs referenced `8086:7A13`; all greps now match both to avoid missing either.
- Added `custom-kernel/patches/0008-platform-x86-p2sb-runtime-psf-fixups.patch.enabled`: registers a PCI header fixup and resume hook for `8086:(51ea|7a13)` that reissues the IOSF clears and forces the Serial-IO rail via PMC on every boot/resume. (No build yet — needs the next kernel/ISO spin.)
- Pending validation: rebuild the kernel/UKI, run `./build.sh`, flash the image, and confirm (a) `PsfStubStatus` captures the new stages, (b) dmesg/dev_info logs show “p2sb runtime: cleared SerialIO PSF (fixup/resume)”, and (c) Chipsec/lspci finally show `00:15.3`.

### 2025-10-28 @ 04:13 UTC — Build 025 smoke test on b025
- `uname -a` on the host reports `6.16.10-custom #1 Tue Oct 28 03:32:37 UTC 2025`, confirming the latest kernel + EFI stub are live.
- Boot shims advanced but PSF still latched: `hexdump -Cv /sys/firmware/efi/efivars/PsfBootChainStatus-e6d56d8a-65f8-4c45-ae7c-534c87649b13` → `version=1, stage=2, status=EFI_SUCCESS`; `PsfPatchStatus-51c1bf6e-821e-4f72-9f7a-84f41f8b8827` → `version=1, stage=60, status=EFI_SUCCESS`.
- Re-enabled `mmio_rw` and probed SBREG: `/usr/local/bin/mmio_rw r32 0xFD000000` still returns `0xffffffff`, so the window is hidden by the time Linux boots.
- `CHIPSEC_CFG_PATH=/opt/chipsec/chipsec/cfg/8086/cht.xml PYTHONPATH=/opt/chipsec python /root/psf_enable_i2c3.py` injects the missing message-bus register defs and shows the instant relatch: `PCIEN 0x007C 0x00000400 → 0x00000403` (IOEN/MEMEN set) but reading again immediately reports `0x00000400`; `CFGDIS 0x0098` never drops (stays `0x00000400`).
- `lspci -nn | grep -E '8086:(51ea|7a13)|00:15\.3'` still returns nothing and `setpci -s 00:15.3 10.l` warns that the device is absent.
- `chipsec_util msgbus read 0xA9 0x0930` continues to abort with `KeyError: 'MSG_CTRL_REG'`; use the helper script above (or reapply the patched XML) before rerunning the stock utility.

### 2025-10-28 @ 02:32 UTC — BootChain now probes SMM Base2, still no public loader
- Rebuilt `BootChain.efi` (edk2) so the SMM helper load path first resolves `EFI_SMM_BASE2_PROTOCOL`. We now log the absence of a public `SmmLoadImage`/`SmmStartImage` hook instead of blindly `StartImage`-ing the DXE_SMM binary.
- The shim no longer triggers `#UD` in QEMU; it records `EFI_UNSUPPORTED` with the new “no public SMM load entrypoint” message in `bootchain.log` (on writable media) and bumps `PsfBootChainStatus` stage → last-status accordingly.
- Action item: either surface a callable loader (firmware/SMM patch) or refactor `PsfUnhideSmm` into a combination DXE/SMM driver that registers itself once inside SMRAM. Until then, the helper will be skipped gracefully and FUNDIS remains latched post-boot.

### 2025-10-28 @ 01:36 UTC — SMM helper image loads but hits #UD under OVMF
- Authored `PsfUnhideSmm.efi` (DXE_SMM_DRIVER) to clear PSF FUNDIS via periodic SMM timer; binary lands in `firmware/psf_patch/PsfUnhideSmm.efi`.
- BootChain now tries to start the helper ahead of the loader, but the sandbox QEMU run (`qemu-system-x86_64 … -drive if=pflash,format=raw,file=esp.img`) immediately trips `#UD` inside `PsfUnhideSmm`’s entry point (`GenFw` reports the fault at `_ModuleEntryPoint`). Starting an SMM image through `gBS->StartImage` doesn’t work—need a proper `SmmLoadImage`/`SmmStartImage` call path.
- Next step: teach BootChain to hand the image to the SMM core (or repackage the helper as a DXE driver that registers with SmmAccess); until then, the new image cannot execute without crashing.

### 2025-10-28 @ 00:18 UTC — DXE reaches ExitBootServices; PSF shadow still locked
- Refreshed `/opt/chipsec/chipsec/cfg/8086/pch_6xxP.xml` on b024 to restore `MSG_CTRL_REG`/`MSG_DATA_REG`/`MSG_CTRL_REG_EXT`, so `chipsec_util msgbus` no longer throws `KeyError: 'MSG_CTRL_REG'`.
- EFI status variable now advances through the replay path: `hexdump -Cv /sys/firmware/efi/efivars/PsfPatchStatus-51c1bf6e-821e-4f72-9f7a-84f41f8b8827` → `… 01 00 00 00 | 00 … | 3c 00 00 00`, i.e. version 1, stage 60, `EFI_SUCCESS`.
- Despite the stage 60 hand-off, PSF shadow reads via Chipsec remain `0x00000400` for all SerialIO child slots (`PYTHONPATH=/opt/chipsec python -m chipsec_util msgbus read 0xA9 0x0900/0x0910/0x0920/0x0930/0x0934/0x0938`).
- `/usr/local/bin/mmio_rw read 0xFD000000` still returns `0xffffffff`, so the SBREG window is closed again by the time Linux boots; `lspci -nn | grep -E '8086:(51ea|7a13)'` continues to produce no output.
- Conclusion: the DXE replay now survives through ExitBootServices, but firmware (or SMM) is reasserting FUNDIS immediately afterward. Need an even earlier hook or an SMM rider before re-testing enumeration.

### 2025-10-27 @ 18:48 UTC — DXE fallback verified in sandbox
- Rebuilt `PsfPatchDxe.efi` to program SBREG=0xFD000000 when the BAR reads `0xffffffff`/`0x0`, leave P2SB visible while PSF/PMC writes run, and arm both ReadyToBoot and ExitBootServices replays.
- QEMU sanity (`timeout 20s qemu-system-x86_64 ... esp.img`) shows BootChain loading the driver; `psfpatch.log` on the writable ESP records the fallback plus “Replay stage … armed” lines.
- EFI var dump from the run: `PsfPatchStatus → version=1, stage=42, status=EFI_SUCCESS` (exit-boot replay armed; ReadyToBoot path still not observed because the sandbox shell never exits Boot Services).
- Next action once the ISO is redeployed: boot b023, expect `PsfPatchStatus` stage 60 after Linux exits Boot Services, then confirm PSF FUNDIS stays clear via Chipsec (`msgbus read 0xA9 0x0930/0x0938`) and check for `8086:(51ea|7a13)` in `lspci`.

### 2025-10-27 @ 18:35 UTC — Chipsec msgbus tests confirm FUNDIS still asserted
- Patched `pch_6xxP.xml` on b023 so Chipsec exposes the message-bus control/data registers for the Alder Lake PCH; `chipsec_util msgbus read` now works for Serial IO port `0xA9` and the parent ports (`0xAD/0xAB/0xA1/0xA3`).
- Collected fresh reads for the 00:15.x shadows: `0xA9:0x0900/0x0910/0x0920/0x0930` and the parent equivalents all return `0x00000400`, and `0xA9:0x0938` likewise reports `0x00000400`.
- Attempted to clear the child slot via `chipsec_util msgbus write 0xA9 0x0934 0xFFFFFBFE`; the immediate re-read still shows `0x00000400`, and a follow-up PCI rescan (`echo 1 > /sys/bus/pci/rescan`) leaves `lspci -nn | grep -E '8086:(51ea|7a13)'` empty. So the guard reasserts just as before.
- These runs align with the earlier observation that alias writes don’t stick: even with Chipsec issuing proper IOSF MB transactions, the platform restores FUNDIS/CFGDIS instantaneously, so the pre-OS driver still needs to hold the gate open before Linux boots.

### 2025-10-27 @ 18:10 UTC — BootChain runs but PSF still closed post-boot
- Verified the shim executed: `/sys/firmware/efi/efivars/PsfBootChainStatus-e6d56d8a-65f8-4c45-ae7c-534c87649b13` now exists with payload `07 00 00 00 | 01 00 00 00 | 02 00 00 00 | 00 …`, i.e. version 1, stage 2, last-status `EFI_SUCCESS`. The static `bootchain.log` on the ISO remains unchanged (write-protected media), which matches the expectation from QEMU runs.
- `PsfPatchDxe` left a status variable as well, but it reports version 1 / stage 0 with last-status `0x0000000A` (`/sys/firmware/efi/efivars/PsfPatchStatus-51c1bf6e-821e-4f72-9f7a-84f41f8b8827` → hex stream `07 00 00 00 | 01 00 00 00 | 00 00 00 00 | 00 … | 0A 00 00 00`). Need to decode what stage 0 + code 0x0A map to in the driver.
- Kernel log still lacks any `p2sb early:` breadcrumbs (`dmesg | grep -i 'p2sb early'` → empty), confirming none of the in-kernel quirks ran on this boot.
- SBREG window remains inaccessible after Linux is up: `/usr/local/bin/mmio_rw read 0xFD000000` returns `0xffffffff` even after re-enabling execute perms on `mmio_rw`.
- Triggering `echo 1 > /sys/bus/pci/rescan` does not surface `00:15.3`; `lspci -nn | grep -E '8086:(51ea|7a13)'` stays empty.
- Attempted to sample the PSF shadow via Chipsec (`python -m chipsec_util msgbus read 0xA9 0x0900`); helper module loads, but the utility aborts with `KeyError: 'MSG_CTRL_REG'`, so we still need a patched register definition (or a custom helper) before we can confirm FUNDIS/CFG_DIS from userspace.

### 2025-10-27 @ 03:35 UTC — DXE binary present on ESP but still not executed

### 2025-10-27 @ 03:35 UTC — DXE binary present on ESP but still not executed
- Verified on b023 that `/boot/EFI/systemd/drivers/PsfPatchDxe.efi` is in place after the last reboot; no additional files were staged under `EFI/systemd`.
- Post-boot inspection still shows **no evidence that the driver ran**: `psfpatch.log` is absent from `/boot/EFI/systemd/` and the expected NVRAM variable (`PsfPatchStatus-51c1bf6e-821e-4f72-9f7a-84f41f8b8827`) cannot be queried because the host lacks the `efivar` tool (need to install `efivar` or use `efibootmgr`/`dmesg` as a proxy).
- Conclusion unchanged: systemd-boot continues to ignore the `driver  \EFI\systemd\drivers\PsfPatchDxe.efi` stanza, so we still need an alternate preload path (e.g., `startup.nsh` chainload, BOOTX64 shim, or copying the DXE into a driver directory the firmware actually scans) before pursuing further PSF tests.

### 2025-10-27 @ 03:30 UTC — DXE driver still not executing (no log, no status variable)
- Rebuilt `PsfPatchDxe.efi` with an EFI variable (`PsfPatchStatus`) and file logging at `\EFI\systemd\drivers\psfpatch.log`. Dropped the binary on the ESP and rewrote systemd-boot entries to use backslashes in the `driver` stanza (`driver  \EFI\systemd\drivers\PsfPatchDxe.efi`).
- After reboot, neither the log file nor the NVRAM variable appears: `/boot/EFI/systemd/drivers/psfpatch.log` is missing and `efivar -p` shows no `PsfPatchStatus-51c1bf6e-821e-4f72-9f7a-84f41f8b8827`. Conclusion: systemd-boot is still not loading our driver, so the DXE code never runs.
- `psf_fix` initramfs hook continues to run (`SBREG base 0xFD000000` in `/run/initramfs/psf_fix.log`), but `mmio_rw 0xFD000000 -> 0xffffffff`, Chipsec PCR writes still revert to `0x00000400`, and `lspci` lacks `8086:(51ea|7a13)`.
- Next step: chainload the driver explicitly before systemd-boot (e.g., create `startup.nsh` that runs `\EFI\systemd\drivers\PsfPatchDxe.efi` and then launches `\EFI\BOOT\BOOTX64.EFI`), or copy the driver into `EFI/BOOT` and wrap it with a shim so firmware executes it prior to the loader.

### 2025-10-27 @ 02:02 UTC — DXE helper staged on ESP, ready for pre-OS PSF clears
- Built the `PsfPatchDxe.efi` driver locally with edk2 (GCC5 toolchain) using the iosf_mbi/SBI logic from our refreshed kernel patch. The payload unhides P2SB, programs SBREG to 0xFD000000 if empty, clears Serial IO parent/child FUNDIS & CFG_DIS via SBI, forces RPD3 bit20, then restores hide unless `keep_unhidden` is desired.
- Copied the resulting binary into the repository (`firmware/psf_patch/PsfPatchDxe.efi`) and deployed it to the live ISO’s ESP at `/boot/EFI/systemd/drivers/PsfPatchDxe.efi` via `baremetal_scp`. Directory is owned by root; file perms `-rwxr-xr-x`.
- Next reboot will let us chainload it via systemd-boot (ensure the loader entry references the driver or fallback `drivers/` autoload); post-boot we must inspect `/run/initramfs/psf_fix.log`, `dmesg` for new breadcrumbs, and verify SBREG/PSF state + `lspci` for `00:15.3`.
- Remaining TODO: Flash new ISO only if ESP approach fails; otherwise iterate on DXE logging and confirm enumeration before reintroducing kernel-side patches.

### 2025-10-26 @ 20:10 UTC — Build 023 still missing iosf_mbi quirk at runtime
- Booted b023 (build 23) and confirmed the new initramfs hook ran (`psf_fix:` lines in `dmesg` plus `/run/initramfs/psf_fix.log`), but `dmesg` contained **no** `p2sb early:` breadcrumbs. Grepping `/proc/kallsyms` also shows none of the helper symbols we added in the refreshed quirk (`p2sb_iosf_update`, `p2sb_program_serialio_psf`), indicating the running kernel fell back to the older driver that bails out when the DMI override is present.
- Verified the absence directly via the shipped image: `grep -oba 'p2sb early' /usr/lib/modules/6.16.10-custom/vmlinux` returns empty, while the file does include the old `p2sb_sbreg_override` strings. Conclusion: the iso on b023 never picked up the latest 0004 patch; we’re still on the pre-iosf_mbi version, so the quirk stops before the PSF writes exactly as before.
- Reinstalled Chipsec with `/usr/local/bin/install_chipsec` (run-after-boot left the toolchain in place) and uploaded the current `tools/psf_clear_cfg.py`. With executable bits restored on `/usr/local/bin/mmio_rw`/`devmem{,2}`, the helper executes but every parent/child shadow remains `0x00000400` after the AND burst, and `lspci` still lacks `8086:(51ea|7a13)`. This matches earlier behavior—firmware reasserts FUNDIS immediately because the kernel never touched it pre-scan.
- Also replayed the Windows GNVS SMI from Linux using `smi_mailbox_seq2.py`. The primary call times out exactly like Windows (`CMD=0x14` hangs, forcing a zero-payload follow-up and manual idle write), but even after forcing `{CMD=0x0A, PAR1=0x12}` the subsequent `psf_clear_cfg.py` sweep shows all PSF shadows back at `0x00000400`. So the SMI alone doesn’t open the bridge on this boot either; without the kernel quirk running beforehand, firmware still recloses the gate before we can rescan PCI.
- Tried to replay Lenovo’s OEM PAD writes over `/dev/mem` (`mmio_rw`, `devmem`) but every GNVS touch (`0x936C217A`) now returns “mmap: Resource temporarily unavailable” despite `iomem=relaxed`. We can still access SBREG, so GNVS must have been moved into a protected range; Chipsec’s physical memory helper still writes it (used by the SMI script).
- Cold-boot sanity snapshot (build 23):
  * `dmesg | grep 'p2sb early'` → *no matches* (the patched quirk still never runs).
  * `/usr/local/bin/mmio_rw read 0xFD000000` → `0xffffffff`, confirming the SBREG window isn’t mapped once P2SB is hidden.
  * `echo 1 > /sys/bus/pci/rescan && lspci -nn | grep -E '8086:(51ea|7a13)'` → no output; 00:15.3 remains absent even after rescan.
- Added `tools/psf_monitor.py` to poll parent/child shadows immediately after issuing msgbus AND writes via Chipsec. On b023 both parent (`0xA9:0x0900`) and child (`0xA9:0x0930`) stay at `0x00000400` for 200 samples (1 ms each). That means either the msgbus write is being ignored outright or firmware/SMM is reflipping FUNDIS faster than 1 ms even while P2SB stays unhidden.
- **Next steps:**
  1. Inspect the build artifacts for 0004 (e.g., `custom-kernel/patches/0004-…`) and the packaging logs to confirm why the refreshed patch was dropped before build 23. Rebuild only after we see the new symbols (or strings) present in `vmlinux`.
  2. Once the kernel actually carries the iosf_mbi helpers, rerun the same boot + `psf_clear_cfg.py` check to verify parent/child clears finally stick and `00:15.3` enumerates.
  3. In parallel, prototype the GNVS SMI + PCR sequence entirely from userspace so we have a working register script to port into the quirk as soon as the binary issue is resolved.

### 2025-10-25 @ 12:35 UTC — Kernel quirk now drives PSF via iosf_mbi
- Reworked `custom-kernel/patches/0004-x86-p2sb-early-quirk-cache.patch` so the early p2sb quirk clears FUNDIS/CFGDIS through `iosf_mbi_modify()` rather than MMIO. Every parent port (0xAD/0xAB/0xA1/0xA3) and the 0xA9 child now prints `pr_info` breadcrumbs for each slot (00:15.{0–3}).
- Added helper scaffolding (`p2sb_iosf_update()` + `p2sb_program_serialio_psf()`) that logs the LPC device ID, selects the correct PSF base (0x0900 vs 0x0500), and honours the existing `p2sb_keep_unhidden` boot knob for diagnostics.
- Child PCIEN programming now masks off BAR disable bits and forces IO/MEM enable via msgbus; this replaces the brittle SBREG `writel()` path that previously risked hangs above the safe window.
- **Next steps:**
  1. Rebuild the custom kernel, deploy to b021, and capture early `dmesg` output for the new “parent FUNDIS” / “child PCIEN” breadcrumbs.
  2. Boot once with `p2sb_keep_unhidden=1` to confirm the diagnostic path, then re-run `tools/psf_clear_cfg.py` to ensure runtime PCR reads match the early log.
  3. After the rebuild, validate that `00:15.3` enumerates (`lspci -nn`, `setpci -s 00:15.3 10.l`) and update this log with the BAR value.

### 2025-10-25 @ 11:51 UTC — Build 022 staged with refreshed quirk
- `scripts/build_and_flash.sh` completed successfully (see `build-run.log` @ 11:51 UTC). New ISO `build/out/archlinux-opcode-sniffer--x86_64.iso` (build 022) bundles the iosf_mbi p2sb quirk and updated header exports from 0004.
- Kernel compilation finished cleanly under the relaxed objtool/IBT configuration, so the image is ready to deploy to b021 for PSF validation.
- Follow-up: flash b021, capture the new `p2sb early:` breadcrumbs during boot, then run `tools/psf_clear_cfg.py` to compare runtime PCR state before moving on to bare-metal diagnostics.

### 2025-10-25 @ 09:55 UTC — SMI handshake forced idle; PSF still reasserts FUNDIS
- Added `tools/smi_mailbox_seq2.py`, a helper that issues the Windows `{CMD=0x14, PAR0=0x70, PAR1=0x03, PAR2=0x02}` SMI, retries with the zero-payload follow-up, and forces the mailbox back to `{CMD=0x0A, PAR1=0x12}` when firmware leaves it latched.
- Ran the helper on build 21 (b021) so the GNVS mailbox now matches the Windows completion snapshot before PSF manipulation.
- Immediately reran `/root/psf_clear_cfg.py`; every parent/child slot still reports `0x00000400` after the AND-alias writes, `00:15.{0,1}` remain the only enumerated Serial-IO functions, and `setpci -s 00:15.3 10.l` still fails. P2SB unhide, rail latch, and the PCIEN MMIO alias all execute, so FUNDIS is being reasserted even with the SMI sequence in place.
- **Kernel-side next steps:** instrument the early quirk (`0004-x86-p2sb-early-quirk-cache.patch`) with printk breadcrumbs around the PSF writes, add a diagnostic `p2sb_keep_unhidden` boot so the bridge stays exposed through PCI scan, and build a temporary variant that logs the parent/child BASE values before and after the quirk. Once we know where FUNDIS is restored we can fold the working sequence (including the GNVS SMI) into the kernel path and retire the userspace helper.

### 2025-10-25 @ 07:22 UTC — Windows GNVS mailbox trace confirms SMI handshake
- Captured GNVS mailbox activity from Windows using Chipsec memory reads (`C:\psf\gnvs_trace.py`). The CSV (`gnvs_trace.csv`, copied to the repo root) samples every 10 ms for 10 s while the keyboard base was reattached.
- Observed a single state transition at ~5.916 s after capture start:
  * **Before attach:** `CMD=0x14`, `ERR=0x00000000`, `PAR0=0x00000070`, `PAR1=0x00000003`, `PAR2=0x00000002`, `PAR3=0x00000000`.
  * **After firmware completes:** `CMD=0x0A`, `ERR=0x00000000`, `PAR0=0x00000000`, `PAR1=0x00000012`, `PAR2=0x00000000`, `PAR3=0x00000000`.
- This matches the expected SMI flow (command `0x14` during execution, firmware restores idle value `0x0A` afterward) and refines the parameters we need to mirror from Linux / AML. The previous assumption that `PAR0` returned `0x00001200` was inaccurate—the data is split across `PAR0`/`PAR1` with low word `0x12`.
- Saved artifacts:
  * Windows-side scripts: `C:\psf\gnvs_trace.py` and CSV log `C:\psf\gnvs_trace.csv`.
  * Local copy: `gnvs_trace.csv` (same directory as this repo).
- Next: incorporate these exact values into the Linux initramfs hook / AML SMI call so the firmware sees the same `{CMD,PAR}` sequence before we clear PSF, then proceed with the Linux-side PSF writes immediately after reboot.

### 2025-10-25 @ 02:12 UTC — SMI window + full parent sweep still reverts instantly
- Rebuilt `psf_clear_cfg.py` to follow the new plan: assert the `.3` PCIEN alias via SBREG MMIO, unhide P2SB, attempt to mask SMI (GBL_SMI_EN), sweep parents `0xAD/0xAB/0xA1/0xA3`, burst-clear child slots `0x0900`–`0x0930`, then rescan once.
- Runtime constraints:
  * `PMBASE` reads as `0x0000`, so the platform exposes no ACPI I/O window to toggle `SMI_EN`; the script now logs *“PMBASE is 0 — skipping SMI mask.”*
  * PCIEN SBREG writes report `before=0x00000003 → cleared=0x00000003 → restored=0x00000003`, so the AND/OR aliases are acknowledged but bits[1:0] never drop; we emit a warning and continue.
- Parent sweep output (all ports `0xAD`, `0xAB`, `0xA1`, `0xA3` across `0x0900/0x0910/0x0920/0x0930`):
  ```
  parent PID 0xAD base 0x0900: before=0x00000400 → after AND=0x00000400
  ...
  parent PID 0xA3 base 0x0930: before=0x00000400 → after AND=0x00000400
  ```
  Every slot still reports `0x00000400` after the AND write.
- Child burst clear:
  ```
  Child shadows after AND writes:
    0x0900: 0x00000400
    0x0910: 0x00000400
    0x0920: 0x00000400
    0x0930: 0x00000400
  Rescan → PCIEN (.3) via msgbus: 0x00000400
  lspci → only 00:15.0 / 00:15.1
  ```
- Rail check: `PWRM RPD3 (0xFE0010D0) = 0x03F19FFE`, so bit20 stays latched even as the FUNDIS bit reasserts.
- Next actions:
  1. Try masking SMI via an alternate path (e.g., Chipsec `helper.send_sw_smi` to freeze handlers) or confirm with firmware traces that SMM isn’t the actor.
  2. If runtime remains hostile, shift the entire parent+child clear into the early p2sb quirk so it executes before any firmware policy runs; watch for the printk breadcrumbs and verify `00:15.3` enumeration immediately after PCI scan.
  3. Consider instrumenting the quirk or Chipsec helper to monitor the offending write (e.g., log the msgbus traffic while the clear is attempted) to identify the precise re-arm source.

### 2025-10-25 @ 02:18 UTC — Added initramfs `psf_fix` hook (pending rebuild)
- `build.sh` now emits an initcpio install/hook pair (`/usr/lib/initcpio/{install,hooks}/psf_fix`) that:
  * pulls `/usr/bin/devmem` into the image,
  * latches the Serial-IO rail (`PWRM+0x10D0`),
  * iterates parents `0xAD/0xAB/0xA1/0xA3` and children `0xA9` across slots `0x0900`–`0x0930`, clearing FUNDIS/CFGDIS, and
  * logs every before/after BASE value to `/run/initramfs/psf_fix.log` plus `/dev/kmsg` before issuing a single PCI rescan.
- `HOOKS` ordering now runs `psf_fix` immediately after `base udev` and before `pomeon`, so the clears should land before table overrides and PCI enumeration.
- Need to rebuild (`./build.sh`) and flash the new initramfs to verify the early hook’s breadcrumbs, then rerun `psf_clear_cfg.py` post-boot to confirm the shadow dwords stay at `0x00000000` and that `00:15.3` finally enumerates.

### 2025-10-25 @ 01:44 UTC — Parent PSF FUNDIS also re-latches immediately
- Extended `psf_clear_cfg.py` to walk the parent PSF ports (0xAD, 0xAB) across offsets `0x0930/0x0910/0x0950` while P2SB stays unhidden. Each candidate BASE read returns `0x00000400`; AND-alias writes (`0xFFFFFBFF`) momentarily acknowledge but BASE snaps back to `0x00000400` before the follow-up read.
- Sample output:
  ```
  Parent PID 0xAD base 0x0930: 0x00000400 → after AND: 0x00000400 (still set)
  Parent PID 0xAB base 0x0910: 0x00000400 → after AND: 0x00000400 (still set)
  ```
- With the parent still asserting FUNDIS, the child slot (PID 0xA9, 0x0930) stays at `0x00000400` even after the child AND write. Rescan continues to show only 00:15.{0,1}; `setpci -s 00:15.3 10.l` warns (device missing).
- Next steps: identify the higher-level gate—likely another PSF hierarchy layer or PMC policy—that re-writes both parent and child FUNDIS bits immediately after the write. Need to trace firmware writes (IOSF snooping or stepping through the kernel quirk) or pause the watchdog by holding the relevant PMC register before attempting the clear.

### 2025-10-25 @ 01:32 UTC — Unhiding P2SB still leaves CFG_DIS latched
- Deployed the revised helper (`/root/psf_clear_cfg.py`) that fixes the `.3` PCIEN offsets (BASE `0xFDA9007C`, AND `0xFDA90080`, OR `0xFDA90084`) and explicitly unhides P2SB (B0:D31:F1 reg `0xE1`) before issuing the CFG_DIS clear.
- Execution trace:
  ```
  P2SB hide reg (orig): 0xFF → cleared bit0, performed writes, restored to 0xFF
  CFG_DIS before: 0x00000400
  PCIEN   before: 0x00000400
  PCIEN after AND/OR self-test: 0x00000400 (unchanged)
  CFG_DIS after AND (0xA9:0x0934 ← 0xFFFFFBFF): 0x00000400
  pci rescan → no 00:15.3; `setpci -s 00:15.3 10.l` still warns (device absent)
  ```
- Conclusion: even with P2SB temporarily exposed and the correct alias addresses, the `0x0400` bit in `PSF PID 0xA9:0x0930` immediately reasserts. Next check is whether a higher-level PSF agent (likely PID `0xAD`) mirrors the same FUNDIS gate; need to clear the upstream entry before retrying the `.3` slot.

### 2025-10-25 @ 01:05 UTC — PSF alias toggles leave 00:15.x untouched
- Dropped the new helper (`tools/psf_anchor.py`) onto the host as `/root/psf_anchor.py` and ran it under Chipsec (`PYTHONPATH=/opt/chipsec python /root/psf_anchor.py`). The script walks PSF ports `0xA9`, `0xAB`, and `0xAD`, issuing OR/AND alias writes across offsets `0x0900–0x09F0` while forcing a PCI rescan after each poke.
- Every candidate still reports `0x00000400` from the base dword, and forcing `CFG_DIS` via the OR alias (`+0x8`, value `0x00000001`) failed to drop either `00:15.0` or `00:15.1`. Clearing again through the AND alias (`+0x4`, mask `0xFFFFFFFE`) restores the original `0x400` readback. Conclusion: these slots are not actually gating the enumerated Serial-IO pair, or bit 10 (`0x0400`) is being immediately re-asserted upstream.
- Repeated the direct IOSF write against the `.3` entry (`msgbus_reg_write(0xA9, 0x0934, 0xFFFFFBFE)`), confirmed the base read (`msgbus_reg_read(0xA9, 0x0930)`) remains `0x00000400`, and `lspci -nn | grep 00:15` continues to list only `.0` and `.1`. `setpci -s 00:15.3 10.l` still errors because the function is absent.
- Next step: identify the upstream agent whose AND/OR aliases actually honor the CFG/FUNDIS clears (likely the parent PSF bridge or a PMC gate). We may need to momentarily unhide P2SB via PCI config so the write sticks before firmware re-arms the hide bit.

### 2025-10-24 @ 20:14 UTC — Safe sweep re-run, decoded PSF stride
- Rebooted, restored `/usr/local/bin/mmio_rw` execute bit, and re-copied the throttled `psf_sweep.py`; latest log (`/root/psf_sweep_latest.log`) reconfirms only PSF ports `0xA9`, `0xA3`, `0xAB`, and `0xAD` expose populated entries, with the same dword values as the earlier capture.
- Manual dump of the `0xA9` block (addresses `0xFDA90000`–`0xFDA9005c`) shows the expected 0x20-byte stride per function:

  | offset | value       | notes |
  |--------|-------------|-------|
  | 0x0000 | 0x800D0100  | `BAR0` of 00:15.x function 0 |
  | 0x001C | 0x6000C000  | `T0_SHDW_PCIEN` (IOEN/MEMEN clear, BARxDIS bits set) |
  | 0x0038 | 0x0000007F  | `T0_SHDW_CFG_DIS` (`CFGDIS` asserted) |
  | 0x0020 | 0x0D071625  | function 1 BAR0 |
  | 0x003C | 0x00009F02  | function 1 `PCIEN` (FUNDIS asserted) |
  | 0x0058 | 0x2001030F  | function 1 `CFG_DIS` (`CFGDIS` still set) |
  | 0x0030 | 0x80808080  | function 2 BAR0 placeholder (all hides asserted) |
  | 0x004C | 0x001E0001  | function 2 `PCIEN` (IOEN=1, MEMEN cleared) |
  | 0x0038/0x0048/0x0058 combos show the bundle of `CFGDIS`/`BARxDIS` bits we need to clear. |

  This aligns with the kernel patch: `PSF_T0_SHDW_PCIEN` lives at `base+0x1C`, `PSF_T0_SHDW_CFG_DIS` at `base+0x38`, and each function advances by 0x20 bytes. In other words, the I²C3 slot we care about is at **PID 0xA9 base 0x0030**, so the alias addresses to hit are `0xFDA90034` (AND) and `0xFDA90038` (OR) for fundis + CFGDIS toggles.
- Above 0x0880 remains off limits: even the read-only probe hangs the host, so stick to the canonical 0x0000–0x007F range when talking to PSF.
- Set `/usr/local/bin/mmio_rw write 0xFDA9007C 0x00000003` so `.3` now reports `IOEN|MEMEN` (readback `0x00000003`).
- Message-bus reads via Chipsec show `PSF PID 0xA9, reg 0x0938` still returning `0x00000400`; bit0 (`CFGDIS`) is already clear, but the high nibble remains set. Direct MMIO to `0xFD000938` continues to wedge the box, so use IOSF/SBI to clear that `0x0400` bit instead of touching SBREG directly.
- Plan: craft a Chipsec helper that un-hides P2SB long enough to issue `msgbus_reg_write(0xA9, 0x0938, value & ~0x400)`; follow immediately with `echo 1 > /sys/bus/pci/rescan`, then check `lspci -nn | grep -E '8086:(51ea|7a13)'` and `setpci -s 00:15.3 10.l`.

### 2025-10-24 @ 19:05 UTC — Safe PSF sweep succeeded, rail re-latched
- After the reboot, copied the throttled helper to the host (`baremetal_sftp_put … /root/psf_sweep.py`) and confirmed the file landed (`3133 B`, timestamp 19:02 UTC).
- Ran `PYTHONPATH=/opt/chipsec /usr/bin/python -u /root/psf_sweep.py`; script finished in ~8 s and reported populated triplets on:
  - **PID 0xA9**: offsets `0x0000` (`d0=0x800D0100`, `AND=0x0024C164`, `OR=0x00000000`), `0x0010` (`d0=0x72BF0000`, `AND=0x11000511`, `OR=0x0209007C`)
  - **PID 0xA3**: offsets `0x0000` (`d0=0x0000CCC0`, `AND=0x0000CCC0`, `OR=0x00000001`), `0x0010` (`d0=0x0000003F`, `AND=0x00000000`, `OR=0x00000000`)
  - **PID 0xAB**: offsets `0x0000` (`d0=0x808D0100`, `AND=0x00210044`, `OR=0x00000000`), `0x0010` (`d0=0x723F2000`, `AND=0x1100C51D`, `OR=0x0289007C`)
  - **PID 0xAD**: offsets `0x0000` (`d0=0x01210000`, `AND=0x00000400`, `OR=0x01210000`), `0x0010` (`d0=0x0121001E`, `AND=0x00000C00`, `OR=0x0121001F`)
  - All other candidates (0xA1/0xA5/0xA7/0xAF) returned `0xFFFFFFFF` across the 0x0000–0x00F0 window.
- `mmio_rw` had lost its execute bit; restored with `chmod +x /usr/local/bin/mmio_rw`, re-read `0xFE0010D0` (`0x03e19fff`), OR’d bit20, and confirmed the rail latched back to `0x03f19fff`.
- **Next focus:** correlate the PID 0xA9 layout so we can target `00:15.0`/`00:15.1` (expecting T0 stride 0x10) and then attempt the guarded AND/OR clears for the `00:15.3` slot derived from that base.

### 2025-10-24 @ 18:25 UTC — Transfer succeeded, host dropped before sweep could run
- Rebooted host responded (`baremetal_bash 'echo up'` → `up`).
- Uploaded the throttled helper (`make_live_iso/scripts/psf_sweep.py`) via `baremetal_sftp_put`; checksum verified on the first attempt.
- Within a minute of the upload the SSH proxy on port 2222 went dark again (connection refused before we could invoke the script), so the passive sweep still hasn’t been executed.
- Wait for b021 to return, then retry by running `/usr/bin/python -u /root/psf_sweep.py` immediately after the upload—if it crashes again before execution, we’ll add a copy step via `cat <<'EOF' > /root/psf_sweep.py` instead of SFTP to rule out transfer-side effects.

### 2025-10-24 @ 18:15 UTC — Passive PSF sweep caused another hang
- Revalidated the PMC rail before probing: `mmio_rw read 0xFE0010D0` returned `0x03e19fff`; after OR-ing bit20 the register latched at `0x03f19fff`.
- Spawned a guarded Chipsec session (`PYTHONPATH=/opt/chipsec`) and issued `MsgBus.mm_msgbus_reg_read()` scans for PIDs `0xA1/0xA3/0xA5/0xA7/0xA9/0xAB/0xAD/0xAF`, walking offsets `0x0000–0x03F0` in 0x10 strides and collecting the `(offset, +0x4, +0x8)` triplets. No writes were performed—this was a read-only sweep to spot real T0 shadow blocks.
- Around the 90 s mark the SSH session froze; shortly after, the reverse proxy on port 2222 dropped (`ssh: connect … connection refused`). The host has not come back up yet, so the scan produced no durable output.
- **Next attempt (once b021 is reachable again):** rerun the sweep with a shorter window (`0x0000–0x00F0`), pausing between PIDs, and log each triplet immediately so we can stop at the first non-`0xFFFFFFFF` block. Hold off on any AND/OR writes until the passive mapping completes without destabilising the system.

### 2025-10-24 @ 22:50 UTC — PSF search reset after crash
- Bare metal is back up (build 21). Re-ran the rail latch against the real PMC window: `mmio_rw read 0xFE0010D0` returned `0x03e19fff`; OR’ing bit20 produced `0x03f19fff`, confirming we’re touching `PWRMBASE+0x10D0` (FE00xxxx) again instead of the earlier stray FD6E window.
- Previous PID sweep loop (clearing CFG_DIS on every candidate under PID 0xA9) hung the host; after reboot we’re switching to a guarded approach: enumerate PSF candidates first, then toggle one offset at a time with immediate restore and explicit `lspci` checks.
- Next steps in flight:
  1. Use Chipsec IOSF reads to map PSF ports (PIDs `0xA1/0xA3/0xA9/...`) and identify blocks that expose the 16-byte T0-shadow triplets (non-`0xFFFFFFFF` values at `+0x4/+0x8`).
  2. For the candidate hosting an already-visible controller (`00:15.0`), clear only CFG_DIS via AND alias, verify the device disappears on rescan, then restore via OR alias—stop after the first successful hit to avoid another hang.
  3. Derive the `00:15.3` offset (`+0x30` stride once 00:15.0/00:15.1 are anchored), clear bits 0/8/9, rescan immediately, and capture `lspci`/`setpci` output.
- All intermediate reads/writes (PID/offset, register values, and rail state) will be logged here so the follow-up attempt has a precise breadcrumb trail if the PSF block still resists.

### Snapshot
- Bare metal `archlinux-opcode-sniffer-b021` is running `6.16.10-custom #1 Fri Oct 24 10:48:01 UTC 2025` (build 21 with the relaxed objtool/IBT/LTO/FTRACE toggles). Uptime during the latest sweep was ~10 minutes; `/proc/cmdline` remains free of `p2sb.sbreg` and `acpi_override`.
- Chipsec is installed under `/opt/chipsec` with a working venv. After adding the missing IOSF register definitions to `chipsec/cfg/8086/adl.xml`, `chipsec_util msgbus read` now reaches port `0xA1` offset `0x0900` (returns `0x00000400`) and gives structured data for adjacent offsets.
- Direct IOSF writes intended to clear FUNDIS/CFGDIS (`chipsec_util msgbus write 0xA1 0x0900 0x44000203`, `0x44000000`, and a bad-value sanity check) appear to succeed but the register immediately snaps back to `0x44000300`; BAR/CFG enable bits stay disabled. Raw `mmio_rw` writes exhibit the same revert, indicating firmware is restoring FUNDIS while P2SB is hidden.
- Neighboring offsets that usually hold AND/OR masks (`0x0904`, `0x0908`, `0x0938`) all read `0x00000400`; writes there have no observable effect on the primary shadow. `chipsec_util msgbus mm_write` (MMIO opcode) behaves the same as the register write path.
- PMC rail bit (`mmio_rw r32 0xFD6E10D0`) remains `0x00000000`; we have not latched bit20 yet because PSF gating is still intact. PCI rescans after every write continue to list only `00:15.0` and `00:15.1`; `8086:(51ea|7a13)` is absent and `setpci -s 00:15.3` fails as before.
- Next experiments should target the PSF T0 shadow AND/OR registers documented for Alder Lake or leverage a tiny helper that calls `iosf_mbi_write()` inside the kernel so the write bypasses the hide clamp before the bridge re-hides.

### Snapshot (2025-10-22 @ 18:45 UTC)
- Rebuilt `6.16.10-custom` on 2025-10-22 18:44 UTC with the refreshed `0004-x86-p2sb-early-quirk-cache.patch`; build now succeeds and emits the new `"override present, forcing unhide/PSF/PWRM"` breadcrumb.
- Bootloader templates (`systemd-boot`, `syslinux`, `grub loopback`) no longer inject `p2sb.sbreg=0xFD000000`, preventing future builds from reintroducing the override via cmdline.
- Fresh artifacts staged locally (`build/kernel-build/linux-6.16.10/arch/x86/boot/bzImage`, `System.map`, `Module.symvers`; SHA-256 `e22dad5322178352b7a2eebf0cf5bc0efa71be3c842a5f1c0e1773d0a9ee8a40` for `bzImage`). Pending deployment to b016 for validation.
- Still need to reboot bare-metal with this image to confirm the early quirk runs (expect `p2sb early: cleared PSF hide` / `forced PWRM bit` messages) and to check for PCI `00:15.3`.
- `p2sb.sbreg=0xFD000000` is gone from `/proc/cmdline` on b016 after the 2025-10-22 07:55 UTC reboot; loader entries now match the repo templates without the override.
- Refreshed `custom-kernel/patches/0004-x86-p2sb-early-quirk-cache.patch` so it both applies cleanly and keeps the override while still running the unhide + PSF + PWRM steps (look for “-- continuing with unhide/PSF/PWRM”).
- Early initrd override remains in place and loads `SSDT5` (OEM ID `I2C3ON`) and `SSDT6` (OEM ID `I2C4RPGV`) ahead of PCI scan; I²C3 still fails to enumerate with the current kernel, so confirmation hinges on the rebuilt image.
- **Next actions:** install the 2025-10-22 18:44 UTC kernel on b016, reboot to capture the early breadcrumbs (`p2sb early: cleared PSF hide` / `forced PWRM bit`), and retest for PCI device `00:15.3`.

### P2SB DMI override impact (2025-10-22 @ 08:05 UTC)
- The custom kernel patch adds several ThinkPad X1 Fold 16 Gen 1 entries to `drivers/platform/x86/p2sb.c`. During very early init the driver calls `dmi_first_match()` and, when it hits one of those entries, caches the SBREG base (`0xfd000000`) and short-circuits the new unhide logic.
- Once `p2sb_sbreg_cmdline_valid` or the DMI path marks an override as present, the quirk bails out before touching PSF or PWRM. We therefore never see the printk breadcrumbs (`p2sb early: cleared PSF hide`, `forced PWRM bit 20`) that indicate the bridge was actually reopened.
- Because SBREG is already mapped from DMI, the later probe phase reports `source=override`. That keeps Serial-IO 00:1f.0 hidden, which in turn prevents PCI slot `00:15.3` from surfacing even though the initramfs delivered the new SSDTs.
- Removing (or at least gating) the ThinkPad entries from the patch forces the driver back onto its discovery path: it briefly unhides the bridge, maps SBREG, flips PSF/PMC bits, then re-hides it. Only after that happens do we expect the ACPI namespace and PCI core to notice the I²C3 controller.
- Conclusion: the SSDTs embedded in the initramfs are not injecting the override; the DMI hook in the kernel is. We now retain the override while forcing the quirk to keep running so PSF/PWRM breadcrumbs appear.
- `build.sh` once again applies the P2SB patch set. `0004-x86-p2sb-early-quirk-cache.patch` now logs the override branch as “-- continuing with unhide/PSF/PWRM”, so the quirk should execute even when SBREG is seeded from cmdline/DMI.

### Live image b015 sanity pass (2025-10-21 @ 17:05 UTC)
- Host `archlinux-opcode-sniffer-b015` is running the freshly flashed ISO (kernel `6.16.10-custom`).
- `SSDT5` / `SSDT6` **are present** inside the initramfs (`lsinitcpio` shows them under both `/kernel/firmware/acpi/` and `/kernel/firmware/acpi/tables/`), but the kernel still loads them late via configfs: `dmesg` only logs `ACPI: SSDT ... I2C3ON/I2C4RPGV` at `t≈11063 s`, and both appear under `/sys/firmware/acpi/tables/dynamic/SSDT27/28`.
- Because the overrides miss the pre-scan window, `lspci` still shows only `00:15.0/00:15.1/00:19.0`; the target controller `00:15.3` never enumerates and all MMIO telemetry on `0x4017_003000` reads `0xFFFFFFFF`.
- Kernel command line on b015 includes `acpi_override` and the firmware search path, but the boot log reports those parameters as “unknown”, implying the current kernel ignores them despite `CONFIG_ACPI_TABLE_UPGRADE=y`.
- `/run/initramfs/pomeon.log` confirms the initramfs hook re-copies the AMLs post-boot (`firmware_class.path=unset` at hook time, no `/sys/firmware/acpi/tables/override` entries), reinforcing that we still rely on the late configfs reload.
- Action items:
  1. Investigate why `acpi_override` is treated as an unknown parameter even though the kernel config enables table upgrade; verify whether we also need `CONFIG_ACPI_TABLE_OVERRIDE_VIA_BUILTIN_INITRD` or to place the AMLs into the early CPIO blob.
  2. Once the kernel accepts the early overrides, re-check that `00:15.3` publishes at boot and rerun the START canary on BAR `0x4017_003000`.
  3. Until the early load works, continue to expect `/sys/kernel/config/acpi/table/{I2C3ON,I2C4GOV}` to be required after boot and update any automation accordingly.

### Initramfs override fix staging (2025-10-21 @ 18:25 UTC)
- Copied `SSDT5.aml` (table OEM ID `I2C3ON`) and `SSDT6.aml` (OEM ID `I2C4RPGV`) into `/kernel/firmware/acpi/` on b015, then added an `acpi-override` mkinitcpio install hook that drops both AMLs into `/kernel/firmware/acpi/{,tables}/` inside the image.
- Updated `HOOKS` in both `/etc/mkinitcpio.conf` and `/etc/mkinitcpio.conf.d/archiso.conf` to inject `acpi-override` (and removed the old `pomeon` hook so we stop copying via configfs at boot).
- Regenerated `/boot/arch/boot/x86_64/initramfs-linux-custom.img`; `lsinitcpio` now shows  
  `kernel/firmware/acpi/SSDT5.aml` and `kernel/firmware/acpi/tables/SSDT5.aml` (same for `SSDT6.aml` plus SSDT1–4).
- Next boot should show the new SSDTs in early dmesg (before PCI enumeration) without relying on `/sys/kernel/config/acpi/table`. Please remove any leftover manual loads (`echo … > /sys/kernel/config/acpi/table/...`) before rebooting so we can confirm the early-path works.

- Reworked `/etc/mkinitcpio.conf.d/archiso.conf` to treat the AMLs via a single `FILES=( … )` block and ensured each entry has a matching `/kernel/firmware/acpi/tables/…` copy.
- `/usr/lib/initcpio/install/acpi-override` now loops over the complete set `{SSDT1–SSDT9}` (including the renumbered `SSDT5`/`SSDT6`) and calls `add_file` for both the plain and `tables/` paths.
- Fresh `mkinitcpio` run placed all nine AMLs under both directories (verified with `lsinitcpio /boot/arch/boot/x86_64/initramfs-linux-custom.img`).
- Trimmed `/boot` (moved stock `initramfs-linux.img` out of the EFI partition) so the new 39 MiB initramfs fits; copied the rebuilt image in place.
- Ready for another reboot to confirm `ACPI: SSDT … I2C3ON/I2C4RPGV` appear before PCI enumeration and that `/sys/firmware/acpi/tables/SSDT{X}` contains the overlays without using configfs.

- Refactored `acpi/SSDT5.dsl` so the override no longer unconditionally rebuilds every method inside `\_SB.PC00.I2C3`. Each helper (`_CRS`, `_STA`, `_ADR`, `_PS0`, `_PS3`, `_DSM`, `_INI`) now sits behind a `CondRefOf` guard and the table declares the firmware definitions as `External` symbols. This eliminates the boot-time `AE_ALREADY_EXISTS`/`AE_NOT_FOUND` spam we observed once the early override began to load.
- Rebuilt `acpi/SSDT5.aml` (491 B) with the new guards; IASL still emits the benign `_PS0/_PS3` pairing warning, but the generated AML only instantiates those methods when the firmware omitted them, matching Lenovo’s conditional blocks.
- Next verification pass (after PSF gating is solved) should confirm `_INI` runs, `IM3B`/`IM03` flip to `0x01`, and Linux accepts `_STA=0x0F` without interpreter errors.

### PSF hide investigation (2025-10-21 @ 21:00 UTC)
- Confirmed the power rail side: `PWRM + 0x10D0` (`RPD3`) toggles the Serial-IO I²C3 domain and the existing `SSDT-PWRMFORCE` helper can hold it high from initramfs.
- Spent additional cycles probing the cached `SBREG=0xFD000000` window over SSH; quick sweeps for `0x00150003`/`0x15030000` signatures did **not** reveal an obvious PSF shadow block for BDF `00:15.3`. Need the exact Alder Lake PSF PCR definitions (`R_ADL_PSF*_PCR_T0_SHDW_*`) to identify the `FUNDIS`/`CFG_DIS` bits.
- TODO: import the appropriate PSF header (coreboot/EDK2) or derive the offsets from the existing `p2sb` quirk, then wire the unhide + function-enable writes into the early quirk so PCI enumeration sees 00:15.3. Once the offsets are known, update this log with the register addresses and expected bit patterns.

### Early PSF/PMC quirk (2025-10-21 @ 22:55 UTC)
- Extended `custom-kernel/patches/0004-x86-p2sb-early-quirk-cache.patch` so the early p2sb quirk now:
  - Maps the SBREG window before the bridge is re-hidden, locates the Serial-IO I²C3 T0 shadow (LP offset `0x0900`, H offset `0x0500`), clears `FUNDIS`/`CFGDIS`, and re-enables IO+MEM decoding.
  - Maps the PMC window via `PWRMBASE` and sets `RPD3` bit 20 to keep the Serial-IO rail powered prior to PCI enumeration.
  - Drops two explicit `pr_info` breadcrumbs (`"cleared PSF hide..."`, `"forced PWRM RPD3..."`) to confirm the quirk executed on real hardware.
- Device-type detection is crude but sufficient: LPC IDs in the `0x51xx/0x54xx` range are treated as LP (use `0x0900`), everything else falls back to the H offset.
- **Next steps:** rebuild/install the kernel, boot b015, and verify the new printk markers, `00:15.3` enumeration (`setpci -s 00:15.3 10.l`), and successful `_STA/_INI` evaluation from `SSDT-I2C3ON`.


## Repo Housekeeping (2025-10-20)
- Pruned the Amazon EC2 ACPI dumps (`dsdt.dsl`, `ssdt1.dsl`, `ssdt2.dsl`) that were lingering at the repo root; only Lenovo firmware artifacts remain.
- Archived legacy Lenovo table snapshots (`SSDT27*.dsl`, `SSDT28-host.dsl`, `SSDT2.dsl`, `SSDT-POMEON-ORIGINAL.dsl`) under `archive/acpi_legacy/` for reference without cluttering top-level searches.
- Mirrored AML clean-up: legacy binaries (`SSDT27*.aml`, `SSDT28-host.aml`, `SSDT2.aml`, `SSDT-POMEON*.aml`) now live in `archive/acpi_legacy/`; active payloads remain under `acpi/` and initramfs staging under `kernel/firmware/acpi/`.
- Consolidated Lenovo DSDT dumps (`dsdt-baremetal.*`) inside `acpi_extract_baremetal/`; removed the leftover Amazon `dsdt.dat`.
- Archived old GNVS/GPIO/IO capture bundles (`commit_trace_v2*`) under `archive/traces/` to keep the workspace root clear of large trace dumps.
- Canonical sources going forward: `acpi_extract_baremetal/dsdt.dsl` (full Lenovo DSDT) and edited payloads under `acpi/`.
- Live mux handshake validated (2025-10-20): `tail300.raw` from the bare-metal host shows GNVS mailbox writes at `0x936C3FD8`–`0x936C3FEC` followed by a `0xB2` SystemIO poke, matching the Windows SMI helper.

## Driver bind + panel command attempt (2025-10-20 @ 08:25 UTC)
- Kernel cmdline still carries `module_blacklist=intel_lpss,intel_lpss_pci,i2c_designware_platform`; even though the PCI driver is built-in, attempting to bind `0000:00:19.0` to `/sys/bus/pci/drivers/intel-lpss` returns `EBUSY` and dmesg repeats `intel-lpss 0000:00:19.0: probe with driver intel-lpss failed with error -16`. Adding the ID via `new_id` is a no-op because the driver already knows `8086:51c5`.
- `/sys/class/i2c-dev/` consequently lacks an adapter that resolves to `0000:00:19.0`; all published buses belong to the 00:15.x controllers or the GPU AUX channels. Manual controller prep is therefore still going through MMIO helpers.
- Re-running the Windows-style handshake (`echo 0x090E0007 > /sys/kernel/acpi_mux/selector`) reports the expected GNVS mailbox transitions (`srt1=0x14`, `ser1=0x1200`, `ser2=0x0`). However, the telemetry dumped via `/sys/kernel/acpi_mux/info` shows `txfv` settled at `0x00000002`, not the drained FIFO that we previously captured (`0x0000000e`), which explains why manual DW probes continue to stall with `TXFLR=2`.
- Issuing `{0xAB, 0x04}` followed by `{0xAB, 0x00}` directly through `/root/tools/mmio_rw` (DIS controller prep, writes to `IC_DATA_CMD`) left `IC_TXFLR` at `0x4` and `0x6` respectively, and `TX_ABRT_SOURCE` stayed zero. No evidence yet that START actually launched on the wire.
- Immediate next debugging step: either (a) un-blacklist `intel_lpss*`/`i2c_designware_platform` so the DesignWare stack can drain the FIFO for us, or (b) keep using the MMIO path but capture a fresh `tail300` trace around the selector write to confirm that the PMC still pulses `APMC=0xF5` and flips `\ERR` busy. Until one of those succeeds, the panel blank/restore commands should be considered unverified.

## I²C3 early publish work (2025-10-20 @ 11:05 UTC)
- Added `acpi/SSDT5.dsl` -> staged as **SSDT5** in the image pipeline. The overlay now:
  - Declares the IM03 bit via FieldUnit and writes `One` to both the backing byte (`IM3B`) and the canonical `\IM03` Field so the firmware’s `_STA` gate flips before ACPI namespace finalisation.
  - Leaves an ASCII marker (`I2C3ON`) so `check-ssdt-markers` can confirm the correct table loaded.
- Updated build plumbing (`build.sh`, `customize_airootfs.sh`, `config_scripts/run_in_chroot.sh`, `config_scripts/acpi_checks.sh`) so mkinitcpio treats **SSDT5.aml** exactly like the other POMEON overrides:
  - Install hook copies SSDT1–SSDT6 into both `/kernel/firmware/acpi/` and `/kernel/firmware/acpi/tables/`.
  - Hook/HAndler now ensures `FILES+=("/kernel/firmware/acpi/SSDT5.aml")` is present in `archiso.conf` and legacy `/etc/mkinitcpio.conf` when the file exists.
  - `check-ssdt-markers` and initramfs audits now expect SSDT1–SSDT6.
- Working tree staging:
  - `kernel/firmware/acpi/SSDT5.aml` + `kernel/firmware/acpi/tables/SSDT5.aml` hold the freshly compiled overlay.
  - Baseline mkinitcpio templates (`buildconfig`, `airootfs/etc/mkinitcpio.conf.d/archiso.conf`) include SSDT5 so iterative rebuilds inherit the new table.

### Build + deployment checklist
1. Recompile before a build if the DSL changes: `iasl -tc acpi/SSDT5.dsl` (outputs `acpi/SSDT5.aml`).
2. Run `./build.sh` (bias towards `FAST=0 QUICK=0 PRESERVE_WORK=0`) to regenerate the ISO; `build-run.log` will now mention *“Staged SSDT5 (I2C3ON)”* if the AML was picked up.
3. Post-build checks:
   - `check-ssdt-markers` on the image should report the new `I2C3ON` marker.
   - `lsinitcpio -l /path/to/initramfs | grep SSDT5.aml` should succeed; automated verify step in `build.sh` now warns if SSDT5 is missing.
4. On bare metal after flashing the new ISO:
   - Confirm enumeration: `lspci -nn | grep -E '8086:(51ea|7a13)'` should now include `00:15.3` (I²C3). If absent, re-check that SSDT5 is inside the initramfs (`/run/initramfs/pomeon.log`) and that `load-ssdt4.service` executed early enough.
   - If `00:15.3` shows up, bind the LPSS stack (drop the blacklist or `insmod intel-lpss*.ko`, `i2c-designware-*`) and run the SMI handshake + `{0xAB,0x04}/{0xAB,0x00}` on the *I²C3* adapter while `\ERR` is busy.
   - If the device still fails to enumerate, evaluate `_SB.PC00.I2C3._INI` from the debugger helper (`acpi_invoke_ini`) and re-run `echo 1 > /sys/bus/pci/rescan`; the method now writes IM03 directly so any failure points at BIOS-level function disable bits.

### Outstanding validation
- Need a full rebuild + bare-metal boot to confirm `SSDT5` loads during the ACPI override pass (expect `ACPI: SSDT 0x... I2C3ON` in dmesg) and that the PCI function `00:15.3` appears prior to driver probing.
- After enumeration succeeds, re-run the mux handshake and update this log with the first successful `{0xAB,0x04}` + `{0xAB,0x00}` transactions issued through the kernel i2c stack rather than MMIO helpers.
- Once verified, consider removing the `intel_lpss*`/`i2c_designware_platform` blacklist from the default boot entries so the controller binds automatically.

### Next-boot test checklist (post-ISO flash)
1. **Early ACPI override sanity**
   - Capture `/run/initramfs/pomeon.log` and `dmesg | grep -i 'ACPI: SSDT'` to confirm SSDT1–SSDT6 loaded (look for `I2C3ON` / `I2C4RPGV`).
   - Run `check-ssdt-markers` once the system is up; log the output in this file.
2. **I²C3 enumeration**
   - `lspci -nn | grep -E '8086:(51ea|7a13)'` should now list `00:15.3`; record BAR values with `setpci -s 00:15.3 10.l`.
   - Verify `/sys/class/i2c-adapter/i2c-*/device` links to `0000:00:15.3`; note the bus number.
3. **Mux handshake + canary**
   - Run `echo 0x090E0007 > /sys/kernel/acpi_mux/selector` and capture `/sys/kernel/acpi_mux/info`.
   - Execute `probe_start_strict.sh` against the I²C3 BAR while `\ERR` is busy; record `TXFLR/TX_ABRT_SOURCE/STATUS`.
4. **Panel command validation**
   - With the proper adapter, run `i2ctransfer -f -y <bus> w2@0x49 0xAB 0x04` followed by `0xAB 0x00`; note panel behaviour and any driver logs.
   - If the driver is bound, check `dmesg | tail` for DesignWare errors/acks.
5. **Automation + services**
   - Ensure `run-after-boot.service` and `pepper-wifi-autostart.service` report `active` (record `systemctl status` snippets).
   - Confirm `/usr/local/bin/ssdt_canary_scan` succeeds without missing markers.
6. **Upload findings**
   - Append results (pass/fail, key register values, log references) to this section so the next iteration has a clear start point.

#### Test run — 2025-10-21 @ 00:27 UTC (bare metal b014)
- **Initramfs hook**: `/run/initramfs/pomeon.log` shows SSDT1–SSDT6 staged into `/kernel/firmware/acpi/{,tables}`; `check-ssdt-markers` confirms all marker strings but still warns about the missing `load-ssdt4.service` and the absence of initramfs artefacts on the live system.
- **Configfs overlays**: Copied `SSDT6.aml` and `SSDT5.aml` to the host and loaded them via `/sys/kernel/config/acpi/table/{I2C4GOV,I2C3ON}/aml`; dynamic tables `SSDT27` (`I2C4RPGV`) and `SSDT28` (`I2C3ON`) now appear under `/sys/firmware/acpi/tables/dynamic`.
- **acpi_invoke_ini bridge**: Rebuilt `acpi_invoke_ini.ko` against `6.16.10-custom`, inserted it, and verified `/sys/kernel/acpi_mux/{selector,info,method}` became available. The selector write only succeeded after the configfs tables were present (earlier attempts failed with `AE_NOT_FOUND`).
- **XSEL telemetry**: `echo 0x090E0007 > /sys/kernel/acpi_mux/selector` records a healthy mailbox cycle (`srt1=0x14`, `ser1=0x1200`, `srt2=0x0A`, `ser2=0x0`, `smr0=0x14`, `smr1=0x1200`), but both `abrt` and `txfv` report `0x0000ffff` and the `XSL*` fields remain zero because the new AML no longer publishes those helpers.
- **DesignWare probe**: `probe_start_strict.sh` with `I2C_BAR=0x4017002000` (I²C4) and `0x4017003000` (intended I²C3) reads `0xffffffff` for all registers, so the canary never drains and no START is observed.
- **PCI / adapters**: After running `\_SB.PC00.I2C3._INI`, `\_SB.PC00.I2C3._PS0`, and `echo 1 > /sys/bus/pci/rescan`, `lspci -nn` still lists only `0000:00:15.0`, `0000:00:15.1`, and `0000:00:19.0`; there is still no `0000:00:15.3`. `/sys/class/i2c-dev/` continues to link `i2c-0/1` to 00:15.{0,1} and `i2c-2` to 00:19.0.
- **Panel check**: `i2cdetect -r -y 2 0x49 0x49` returns `--`, confirming the panel controller is unreachable through the current path.
- **Automation**: `systemctl is-active run-after-boot.service` and `systemctl is-active pepper-wifi-autostart.service` both report `active`, but `/usr/local/bin/ssdt_canary_scan` still warns about the missing initramfs markers on the running system.
- **Open issue**: Despite the overlay and SMI handshake, I²C3 never enumerates, and MMIO reads return `0xffffffff`. We still need an early-boot mechanism that flips `IM03` (and any accompanying PMC bits) before PCI enumeration so the OS sees `00:15.3`.

Follow-up (same session):
- Re-enabled MEM decode/D0 for `0000:00:19.0` (`echo on > …/power/control; setpci -s 00:19.0 0x04.w=0x0006`). `/root/mmio_rw r32 0x40170020FC` now returns `0x44570140`, confirming the DW window decodes again; `probe_start_strict.sh` shows live register reads but still ends with `TXFLR=2, ABRT=0` (expected while probing I²C4).
- `check-ssdt-markers` now sees the dynamic tables but still warns about missing initramfs copies and `load-ssdt4.service`; until we ship a kernel with CONFIG_ACPI_TABLE_UPGRADE + loader glue, continue to stage the AMLs via configfs after boot.
- `acpidbg` helper regained execute permission (`chmod 0755 /usr/local/bin/acpidbg`); added the same fix to `customize_airootfs.sh` and `config_scripts/run_in_chroot.sh` so future images ship the wrapper executable out of the box.

### QEMU sanity boot (2025-10-20 @ 21:55 UTC)
- `start_qemu.sh` now understands `QEMU_BOOT_MODE`:
  - `cdrom` (default) keeps the old behaviour (`-cdrom`). Useful for quick smoke tests but systemd will loops on `/dev/disk/by-label/ARCHISO_EFI` because the label is not exposed on optical media.
  - `disk` attaches the ISO as a virtio block device (`readonly=on`)—matches the dd-to-USB workflow and allows `/boot` to mount cleanly.
- Test command (headless, serial log, SSH forwarded to port 2227):
  ```
  QEMU_USE_OVMF=1 \
  QEMU_BOOT_MODE=disk \
  QEMU_SERIAL_LOG=/tmp/qemu-serial3.log \
  QEMU_HOST_PORT=2227 \
  ./start_qemu.sh
  ```
- Result: system reached the login prompt, `/boot` mounted (`ARCHISO_EFI` device present), `sshd` accepted connections (`ssh -p 2227 root@localhost uname -a` succeeded). Serial log saved at `/tmp/qemu-serial3.log`.
- Reminder: when booted as `cdrom`, it is expected to see repeated `Timed out waiting for device /dev/disk/by-label/ARCHISO_EFI`; use `disk` mode for regression testing aligned with bare-metal flashes.

# ACPI / SSDT Bring-up Status

## PadCfgLock Strategy (2025-10-19)
- Host writes during the OEM XSEL replay never touch PadCfgLock, so we must add the W1S lock ourselves after programming PAD62/63.
- GPIO community **0x6A** on this platform follows the Tiger-Lake LP register map (`HOSTSW_OWN` at base +0x0B0); therefore PadCfgLock base is `0xFD6A0000 + 0x080`.
- Pads 62/63 live in **group 32–63 (g=1)**:
  - `PADCFGLOCK(g=1)`  → `0xFD6A0088`
  - `PADCFGLOCKTX(g=1)` → `0xFD6A008C`
  - Bitmask for pads 62/63 within that group: `0xC0000000` (bits 30/31).
- Lab procedure right after replay writes PADCFG0/1:
  1. `mmio_rw w32 0xFD6A0088 0xC0000000`
  2. `mmio_rw w32 0xFD6A008C 0xC0000000`
  3. Read both registers back to ensure the bits latched (values retain bit30/31 until cold reset).
- If the readback does not latch, fall back to the TGL-H style offsets (`0xFD6A0098/0xFD6A009C`) but expectation is that LP offsets are correct per HOSTSW_OWN observation.
- Bake the lock into `SSDT-I2C4REPLAY.dsl` by adding an OperationRegion covering `0xFD6A0088`–`0xFD6A008F` and issuing two `Store (0xC0000000, …)` calls immediately after the PADCFG1 writes.
- After locking, rerun `probe_start_strict.sh` (16-bit DATA_CMD writes `{0xAB, STOP|0x04}`) and confirm either `TXFLR` drains or `TX_ABRT_SOURCE` goes non-zero within a few milliseconds—this proves the mux held long enough for DW to launch START.
- Remember: pad locks are lab-only until validated; cold reset clears them. Keep ISH in D3hot during experiments to eliminate another pad owner.
- Checklist to close this item:
  - [ ] Confirm PadCfgLock/TX readbacks show `0xC0000000`.
  - [ ] START canary returns success signature.
  - [ ] Integrate the lock writes into AML and validate with a full driver bind (`i2cdetect` succeeds, `{0xAB,0x04}` blanking works).

## Platform + Goal
- Target hardware: Lenovo X1 Fold platform exposing multiple Microchip MCHP19xx controllers on Intel Serial IO. Current tracing points to bus 4 (pads 7/8, GNVS selector `IM04`, Linux `i2c-17`), though earlier work targeted bus 5.
- Objective: blank the secondary panel by issuing `{0xAB, 0x04}` and restore commands to the active PA0x controller (`0x18`, `0x1E`, `0x11`, or `0x15`).
- Current issue: firmware never drives pad-power (RPD/APD) or pad ownership (PADMUX) high, so Linux cannot reach the controllers without SSDT overrides or explicit PADCFG writes.

## Custom SSDT Payloads
- `SSDT-POMEON.dsl`  
  - `_INI` sets firmware field `POME` to `1` so vendor GNVS state matches our expectations.
- `SSDT-PWRMFORCE.dsl`  
  - Exposes method `APDN()` that forces `\RAA*`, `\RPB*`, `\RPC*`, `\RPE*`, and `\RPD*` FieldUnits to `One`.  
  - Polls until all `\APD*` acknowledge bits assert; returns success if `APE*` remain high.
- `SSDT-I2C4REPLAY.dsl` *(canary)*  
  - Replays the OEM PAD62/63 programming without touching the GNVS mailbox; useful for QEMU or instrumentation runs where we only need PAD state.
- `SSDT6.dsl` *(bare metal/live)*  
  - Extends the replay with the GNVS/SMI handshake so the PMC mux actually flips; this is the table we ship for hardware testing.
  - Exposes `GLOG()` helper so we can pull the captured mailbox telemetry (`SRT1/SER1/SRT2/SER2/SMR0/SMR1`) from user space via `acpi_invoke_ini` after a run.
  - 2025-10-20 validation: `/sys/kernel/acpi_mux/info` shows `srt1=0x14`, `ser1=0x1200`, `srt2=0x0A`, `ser2=0x00000000`, `smr0=0x14`, `smr1=0x1200`, `txfv=0x0E`, `abrt=0x0`, confirming ERR latched busy, START launched, and the mailbox was restored to Windows post-state.
- `SSDT-I2C5ON.dsl` *(legacy name)*  
  - Now targets `\_SB.PC00.I2C4._INI` (pads 7/8).  
  - Sets `\IM04 = 0x01` (PSD3 guard for bus 4).  
  - Calls `\_SB.SGOV` / `\_SB.SPC0` / `\_SB.SPC1` on pads 7 (SDA) and 8 (SCL) to hand ownership to the Serial IO controller and program PADCFG0=`0x44000702`, PADCFG1=`0x0003C01A` (native mode, RX/TX enabled, open-drain, no pulls).  
  - Invokes `_PS0` if present and reports `_STA = 0x0F`.

## Build-Time Integration
- `customize_airootfs.sh` installs a mkinitcpio hook (`pomeon`) that:  
  - Packs `SSDT1`–`SSDT6` into `/kernel/firmware/acpi/` and `/kernel/firmware/acpi/tables/`.  
  - Forces `HOOKS` and `FILES` entries so the AMLs are embedded in the initramfs.  
  - Logs staging results to `/run/initramfs/pomeon.log`.  
- `check-ssdt-markers` runs on boot to confirm marker strings in `SSDT1/2` and verify initramfs contents via `lsinitcpio`.  
- `load-ssdt4.service` (historically installed by `customize_airootfs.sh`) pushes `SSDT-I2C5ON.aml` into configfs at boot so `_INI` can fire without manual intervention; **b008 currently ships without the unit enabled**, so overrides must be injected manually until the packaging step is restored (see TODO).
- TODO items remind us to keep `SSDT-I2C5ON.aml` aligned with the other AMLs, rebuild without shortcuts, and clear `/sys/kernel/config/acpi/table` before manual reloads (`AE_ALREADY_EXISTS` guard).

## Runtime Observations
- `p2sb` tracing now prints every SBI retry (`p2sb early:` + `p2sb runtime:`) so we can tell whether the bridge unhid via SBI or the IOSF fallback; a healthy boot ends with `hide cleared via SBI/IOSF` and `hide restored via SBI/IOSF`.
- The doorbell recovery helper exposes raw status polling; capture `setpci -s 00:1f.0 d8.l` / `d4.l` before and after to prove the GO/BUSY bits clear (the validation loop in `TODO` shows the exact command sequence we run by hand).
- Loading `SSDT-PWRMFORCE.aml` via configfs plus invoking `\APDN()` drives `PWRM+0x10D4` to `0x03FF9FFF`, proving rails and pads can be forced on (RPE*/RPD*/APE*/APD* all `1`).  
- When `load-ssdt4.service` is present it inserts `SSDT-I2C5ON.aml` (seen previously as `/sys/firmware/acpi/tables/dynamic/SSDT28`), but `_SB.PC00.I2C4._INI` still fails to execute automatically (`IM04` remains `0x00`) because pad ownership cannot change while the P2SB bridge is hidden; loading `acpi_invoke_ini.ko` manually forces `_INI` and confirms `IM04 = 0x01` once the override is in place.  On b008 the service is missing, so no dynamic SSDT appears at boot until we reload it by hand.
- Consequently `pinctrl/INTC1055:00` continues to report `MUX UNCLAIMED`, and `i2cdetect -r -y 17/18` still shows `--` everywhere.  
- Firmware PSD3/PSD0 methods remain callable; once the PADCFG write path is restored they should accept the sequence without returning errors.

### Windows SMI capture snapshot (2025-10-19 @ 20:58 UTC)
- Source file: `C:\panel_probe\dumps\event_20251019_205832.json` (5 s Chipsec sampler; keyboard detach→attach triggered by the lab operator).
- GNVS mailbox timeline:
  - t≈0 ms — baseline: `CMD=0x0A`, `ERR=0x00000000`, `PAR0=0x00001200`, `PAR1/2/3=0`.
  - t≈895.9 ms — SMI kicks: `CMD→0x14`, `ERR→0x20000000`, `PAR0→0x00000000`; values stay latched for the remainder of the capture window (no `ERR` clear observed through t≈5000 ms).
- PAD state: `PAD83_DW1` and `PAD84_DW1` never leave `0x0003FC00`; Lenovo’s working path appears to rely purely on the SMI side-effects rather than toggling PADCFG1 to `0x0003C01A/1E`.
- Mailbox logging pointers at `0x904F0014/18` advance rapidly during and after the event, indicating firmware activity, but no deterministic control dword emerged in the sampled offsets.
- Takeaways:
  1. Windows is dispatching `\SMI (0x14, 0x00, 0x00000000, …)` during the hinge attach. The 0x00001200 value observed in `PAR0` prior to the call was simply leftover state from an earlier transaction; firmware overwrites it with 0 immediately when the SMI starts. The `{0x00200000, 0x00000014}` tuple we mirrored earlier never appears in the Windows run.
  2. Firmware leaves `ERR=0x20000000` asserted, so Lenovo likely performs a follow-up SMI or mailbox poke to close the handshake; we have not captured that second phase yet.
  3. Because the pads stay at `0x3FC00`, forcing PADCFG1 to the native mux values from Linux may be unnecessary (or even counterproductive); matching the SMI ordering is the priority.
- Open items from this session:
  - [x] Re-scan the Windows DSDT/SSDT for every `\SMI (0x14, …)` invocation to log the real argument tuples and any chained calls (see table below).
  - [ ] Capture tight pre/post GNVS + mailbox dumps (Chipsec `mem dump`) bracketing the event to spot any additional control bytes outside `0x3FD8`.
  - [ ] Update `SSDT6.dsl` once the true argument set and completion sequence are confirmed.

#### `\SMI (0x14, …)` call sites in Windows DSDT
- `Method (BFWC, 1)` → `\SMI (0x14, 0x00, Arg0, 0, 0)` → `CMD=0x14`, `PAR0=0x00`, `PAR1=Arg0`
- `Method (BFWP, 0)` → `\SMI (0x14, 0x01, 0, 0, 0)` → arms firmware for the write phase (no payload)
- `Method (BFWL, 0)` → `\SMI (0x14, 0x02, 0, 0, 0)`
- `Method (BFWG, 1)` → `\SMI (0x14, 0x03, Arg0, 0, 0)`
- `Method (BDMC, 1)` → `\SMI (0x14, 0x04, Arg0, 0, 0)`
- `Method (PSIF, 2)` → `\SMI (0x14, 0x05, Arg0, Arg1, 0)`
- `Method (FNSC, 2)` → `\SMI (0x14, 0x06, Arg0, Arg1, 0)`
- `Method (AUDC, 2)` → `\SMI (0x14, 0x07, Arg0, Arg1, 0)`
- `Method (SYBC, 2)` → `\SMI (0x14, 0x08, Arg0, Arg1, 0)`
- `Method (KBLS, 2)` → `\SMI (0x14, 0x09, Arg0, Arg1, 0)`
- `Method (SSTI, 2)` → `\SMI (0x14, 0x0A, Arg0, Arg1, 0)`
- `Method (SSTH, 2)` → `\SMI (0x14, 0x0B, Arg0, Arg1, 0)`

All of these calls share the same serialized `SMI` helper:
```
CMD  = Arg0
ERR  = 1              // busy until firmware clears it
PAR0 = Arg1
PAR1 = Arg2
PAR2 = Arg3
PAR3 = Arg4
APMC = 0xF5 (polled until ERR != 1)
```
Our latest capture shows `CMD=0x14` and `PAR0/1/2/3=0`, implying Windows exercised one of the “no payload” helpers (likely `BFWP()` or a chained call sequence) but firmware never dropped `ERR` back to `0`. Next experiment should log the exact method invoked (e.g., via `acpidbg` tracing on Windows) or capture the follow-on SMI that clears `ERR`.

### Extended hinge trace (2025-10-19 @ 21:29 UTC)
- Source file: `C:\panel_probe\dumps\event_20251019_212924.json` (10 s sampler immediately after reboot).
- Sequence captured end-to-end:
  - t≈0.006 ms — attach event fires: `CMD=0x14`, `ERR=0x20000000`, `PAR0/1/2/3=0`. Pads remain `0x0003FC00`.
  - t≈9985 ms — firmware completes: `CMD` drops back to `0x0A`, `ERR` clears to `0x00000000`, `PAR0` returns to `0x00001200`.
- No DesignWare BAR registers changed (all remained `0xFFFFFFFF`), reinforcing that the mux hand-off is entirely inside the PMC/SMI path.
- Implications for AML replay:
  1. Issue the SMI with `Arg0=0x14`, `Arg1=0x00000000`, `Arg2=0x00000000` as Windows does.
  2. Poll `ERR` until it clears, then restore the post-SMI baseline (`CMD=0x0A`, `PAR0=0x00001200`) to mirror firmware’s final state.
  3. PADCFG writes are optional; Lenovo leaves DW1 at `0x0003FC00` the entire time, so our AML should prioritize matching the SMI transaction order.

### Userspace SBI validation (build b006, 2025-10-17)
- Ran the TODO doorbell clear sequence against `archlinux-opcode-sniffer-b006` (proxy port forwarded to localhost:2222).  
- Result: doorbell dropped to `00008000` after the hard clear but every READ attempt stalled at `00008101`; BUSY never cleared, and the bridge remained hidden.

```
$ export BAREMETAL_HOST=127.0.0.1 BAREMETAL_PORT=2222 BAREMETAL_USER=root
$ source ./funcs
$ baremetal_bash "setpci -s 00:1f.0 d8.l"
00008001
$ baremetal_bash "setpci -s 00:1f.0 d4.l"
00000000
$ baremetal_bash "setpci -s 00:1f.0 0xd8.l=0x00000000"
$ baremetal_bash "setpci -s 00:1f.0 d8.l"
00008000
$ baremetal_bash "setpci -s 00:1f.0 0xd0.l=0x001f00e0"
$ baremetal_bash "setpci -s 00:1f.0 0xdc.l=0x00000000"
$ baremetal_bash "setpci -s 00:1f.0 0xd8.l=0x00000101"
$ baremetal_bash 'for i in $(seq 1 10); do v=$(setpci -s 00:1f.0 d8.l); echo "$i $v"; sleep 0.05; done'
1 00008101
2 00008101
3 00008101
4 00008101
5 00008101
6 00008101
7 00008101
8 00008101
9 00008101
10 00008101
$ baremetal_bash "setpci -s 00:1f.0 0xd8.l=0x00000000"
$ baremetal_bash "setpci -s 00:1f.0 d8.l"
00008000
$ baremetal_bash "lspci -s 00:1f.1 || true"
$ baremetal_bash "dmesg | grep -i p2sb"
[    0.040192] p2sb early: hide read failed (-110), aborting
[    1.918906] p2sb: cpu model 154 stepping 4 hidden=1 ret=-2
```

### Checklist coverage snapshot (2025-10-17)
- ✅ Step 0 (triage): confirmed `lspci -s 00:1f.1` missing and `setpci … d8.l` stuck at `0x00008001`.
- ✅ Step 2 (doorbell recovery attempts): ran the hard clear / retry loop; BUSY stayed latched (`00008101`).
- ✅ Step 5 (kernel knobs/logging): refreshed kernel patches enable `CONFIG_X86_P2SB`, `CONFIG_INTEL_IOSF_MBI`, ACPI debugger, and verbose `p2sb` instrumentation for the next build.
- ⚠️ Step 1 (direct unhide via config writes): `setpci -s 00:1f.1 e1.b=00` showed “No devices selected,” and `/usr/local/sbin/p2sb-unhide` (CF8/CFC helper writing D31:F0/F1 0xE0/0xE1) still read `VID=0xFFFF` after 5 attempts; P2SB remains hidden.
- ⚠️ Step 2a (ECAM/MMCONFIG attempt): Writing `0xE0`/`0xE1` via `/usr/local/sbin/devmem2` and running `/usr/local/sbin/p2sb-recover` (with optional SMI gating) still returned `VID=0xFFFF`; firmware/SMM re-hides even MMCONFIG accesses.
- ⚠️ Step 1 heuristic fallback: Without unhiding, probing SBREG candidates via devmem2 identified a workable base at `0xFD000000` (GPIOC0 PADBAR=0x700), but pad states remain at their firmware defaults (PAD7 `DW0=0x00000100`, PAD8 `DW0=0x44000300`, `DW1=0x0000001C`).
- ⚠️ Step 3 (AML `_INI` execution): `acpidbg -b "execute \\\\_SB.PC00.I2C4._INI"` and `acpidbg -b "eval \\\\IM04"` both returned `AE_NOT_FOUND`; `load-ssdt4.service` is absent on build b006, so the override AML never loads.
- ⏳ Steps 3–4 (PCR MMIO validation and padmux checks) — blocked until SBREG BAR is known.
- ⏳ Step 6 (IOSF-MBI fallback probe) — pending; kernel patch will provide runtime fallback, but no standalone userspace test executed yet.
- ⏳ Steps 7–9 (race hygiene, cleanup, full bring-up order) — to revisit once direct unhide or kernel retry succeeds.
- 🔜 Recommended immediate action: try the Step 1 direct-unhide procedure (`setpci -s 00:1f.1 e1.b=00`, capture BAR, then re-hide) and record results before starting the rebuild/flash cycle.

## Remaining Blocks
1. **Kernel config**: present kernel still lacks `CONFIG_ACPI_DEBUGGER`, `CONFIG_ACPI_DEBUGGER_USER`, and `CONFIG_X86_P2SB`; rebuild kernel + initramfs with all three so `acpidbg` works and the P2SB bridge can be unhidden from user space.  
2. **Initramfs parity**: live bare-metal image predates the revised SSDT4 + systemd service; need full `FAST=0 QUICK=0 PRESERVE_WORK=0 ./build.sh` run before reflashing.  
3. **Runtime sequencing**: after new ISO boots, confirm `_SB.PC00.I2C4._INI` executes (watch `IM04`, PADCFG registers) and, if necessary, trigger PSD3/PSD0 plus DW controller reset before issuing `{0xAB, 0x04}`.  
4. **Verification data**: must confirm initramfs contains all four AMLs (`check-ssdt-markers`, `lsinitcpio`) and that `load-ssdt4.service` reports success prior to I²C testing.

## ACPI-Focused Test Checklist
1. Boot fresh ISO, confirm `check-ssdt-markers` and `load-ssdt4.service` both succeed (AMLs present in initramfs + configfs).  
2. `acpidump` + `acpixtract` + `iasl -d` to verify overrides in `/sys/firmware/acpi/tables` and confirm `SSDT-I2C5ON` is attached to `I2C4`.  
3. (Once debugger-enabled kernel is built) use `acpidbg` to evaluate `_SB.PC00.I2C4._INI`, inspect `_SB.GPC0(0x7/0x8)`, and confirm `_STA` transitions.  
4. Confirm `busybox devmem $((PWRM+0x10D4)) 32` reports APD bits high and P2SB PADCFG registers reflect native mode after `_INI`.  
5. Reset DW controller (IC_ENABLE toggle), run `i2cdetect` and `{0xAB, 0x04}` against PA0x addresses once pads show native ownership.  
6. Capture restore sequence `{0xAB, 0x00}` and integrate both commands into automation once ACKs succeed.

## References
- `acpi/SSDT-POMEON.dsl`, `acpi/SSDT-I2C5ON.dsl`, `acpi/SSDT-PWRMFORCE.dsl`
- `customize_airootfs.sh:88-258`
- `build/work/x86_64/airootfs/usr/local/bin/check-ssdt-markers`
- `build/work/x86_64/airootfs/etc/systemd/system/load-ssdt4.service`
- `TODO` (lines covering ISO rebuild, kernel flags, SSDT integration)

## Appendices

### p2sb-unhide attempt (2025-10-17)
```
# helper built from tools/p2sb-unhide.c and copied to /usr/local/sbin
/usr/local/sbin/p2sb-unhide
ERROR: P2SB still hidden or unresponsive after 5 attempts.
P2SB @ 00:1f.1 VID: 0xffff DID: 0xffff

/usr/local/sbin/p2sb-unhide --rehide
ERROR: P2SB still hidden or unresponsive after 5 attempts.
P2SB @ 00:1f.1 VID: 0xffff DID: 0xffff
```
The helper writes both D31:F0 (LPC) and D31:F1 (P2SB) registers at offsets `0xE1` (bit0) and `0xE0` (bit8) on each pass, yet PCI config reads continue to return `0xFFFF`, implying firmware/SMM instantly reasserts the hide state.

### ECAM + heuristic SBREG probes (2025-10-17)
```
# ECAM base from MCFG: 0xC0000000 (bus 0 range)
/usr/local/sbin/devmem2 0xC00F90E0 w 0x00000000   # write to P2SBC via MMCONFIG
/usr/local/sbin/devmem2 0xC00F9000 h             # read VID → still 0xFFFF

# Helper that temporarily disables GBL_SMI_EN before ECAM write
/usr/local/sbin/p2sb-recover
P2SB still appears hidden (VID=0xffff)

# Heuristic SBREG scan (no unhide required)
/usr/local/sbin/devmem2 $((0xFD000000 + (0x6e<<16) + 0x0c)) w
Value at 0xfd6e000c (4-byte access): 0x00000700   # GPIOC0 PADBAR

SBREG=0xFD000000
# Pad configs before any AML execution (pads 7/8):
PAD7: DW0=0x00000100  DW1=0x00000000
PAD8: DW0=0x44000300  DW1=0x0000001C
```
`acpidbg -b "execute \\_SB.PC00.I2C4._INI"` initially returned `AE_NOT_FOUND` because the loader script was targeting a non-existent configfs node; overriding works after writing the AML payload to `/sys/kernel/config/acpi/table/SSDT4/aml`.

### configfs injection (2025-10-17)
```
# Updated loader writes to .../aml and toggles enable
systemctl restart load-ssdt4.service
● load-ssdt4.service - Load SSDT-I2C4 via configfs
     Active: active (exited) ...

# Manual one-liner now succeeds too:
cat /usr/local/share/acpi/SSDT4.aml > /sys/kernel/config/acpi/table/SSDT4/aml
```
Results:
- `/sys/firmware/acpi/tables/dynamic/SSDT27` now appears and strings reveal `X1FD/I2C4ON` plus the expected `_SB.PC00.I2C4` scope.
- `acpidbg` (user-space AML debugger) still reports `AE_NOT_FOUND` when asked to execute `\_SB.PC00.I2C4._INI`; the tool isn’t attached to the kernel interpreter, so `_INI` does not fire automatically yet.
- SBREG reads after loading show pads remain in firmware state (PAD7 `DW0=0x00000100, DW1=0x00000000`; PAD8 `DW0=0x44000300, DW1=0x0000001C`), confirming `_INI` hasn’t run despite the table being staged.
  ```
  SBREG=0xFD000000
  PID=0x6e
  PADBAR=$(/usr/local/sbin/devmem2 $((SBREG + (PID<<16) + 0x0c)) w 2>/dev/null | tail -n1 | awk '{print $6}')
  ```

### Kernel-side `_INI` invocation attempts (2025-10-17)
- Prototype helper module lives under `kernel_modules/acpi_invoke_ini/`. It iterates the candidate paths `\_SB.PC00.I2C4`, `\_SB.PCI0.I2C4`, `\_SB.PC00.I2C5`, and `\_SB.PCI0.I2C5` and, on success, calls `_INI` via `acpi_evaluate_object`.
- Building (`make -C /lib/modules/$(uname -r)/build M=… modules`) succeeds, but inserting with `sudo insmod acpi_invoke_ini.ko` on the current VM returns `No such device`; dmesg shows `AE_NOT_FOUND` for every candidate handle, confirming these nodes are absent in the sandbox ACPI namespace.
- Re-run the module on bare metal (or any environment where `\_SB.PC00.I2C4` exists) to trigger `_INI`; expect a success log once the namespace is live.

### Bare-metal validation via `funcs` helpers (2025-10-17 @ 19:10 UTC)
- Used the new `baremetal_*` wrappers to talk to `archlinux-opcode-sniffer-b008` directly (`baremetal_bash 'hostname'` → `archlinux-opcode-sniffer-b008`) and staged the refreshed AML (`baremetal_scp acpi/SSDT-I2C5ON.aml /root/SSDT-I2C5ON.aml`; `cat /root/SSDT-I2C5ON.aml > /sys/kernel/config/acpi/table/SSDT4/aml`). `iasl -p /tmp/SSDT29 -d /sys/firmware/acpi/tables/dynamic/SSDT29` now shows the nested `Scope (\_SB_.PC00.I2C4)` we expect.
- Rebuilt `acpi_invoke_ini` on the host’s kernel (`uname -r` → `6.16.10-custom`) and inserted it in-place:
  ```
  $ baremetal_bash 'cd /root/acpi_invoke_ini && make'
  $ baremetal_bash 'insmod /root/acpi_invoke_ini/acpi_invoke_ini.ko'
  $ baremetal_bash 'dmesg | grep -i acpi_invoke_ini | tail -n5'
  [34507.699436] acpi_invoke_ini: selected handle \_SB_.PC00.I2C4
  [34507.700591] acpi_invoke_ini: successfully evaluated \_SB_.PC00.I2C4._INI
  [34507.700604] acpi_invoke_ini: IM04 now = 0x01
  ```
  (User-space `acpidbg -b "namespace \\_SB_.PC00"` still returns `AE_NOT_FOUND`, but the kernel log confirms `_INI` ran.)
- Updated `SSDT-I2C5ON.dsl` so the SGOV/SPC0/SPC1 calls use the encoded pad identifiers (`0x006E0007` and `0x006E0008`) that the firmware expects. Reloading the table and reinserting `acpi_invoke_ini` continues to program PADCFG0 to `0x44000702` and leaves PADCFG1 at `0x0003C01F/0x0003C020`; host ownership (`PAD_OWN=0x00848184`) is unchanged, and pinctrl still reports pads 7/8 as `(MUX UNCLAIMED) (ISH_I2C1_*)`.
- Latest AML revision now writes the PAD ownership register (`/dev/mem 0xFD6E00B0`) inside `_INI` so bits 7/8 are set automatically and tries PMODE `2` (`0x44000B02`). In practice the firmware (or PMC) immediately restores PADCFG0 to `0x44000702` and PADCFG1 to `0x0003C01F/20` after `_INI` runs, so the pins remain unmuxed even though `PAD_OWN` stays at `0x00848184`.
- Immediately afterwards, pad registers remain unchanged:  
  `PAD7_DW0=0x44000702`, `PAD7_DW1=0x0003C01F`, `PAD8_DW0=0x44000702`, `PAD8_DW1=0x0003C020` (read via `/root/mmio_rw read 0xFD6E0770/74/80/84`). `PAD_OWN` still reports host ownership bits set (`0x00848184`), yet pinctrl keeps advertising `ISH_I2C1_*` with `(MUX UNCLAIMED)`.
- Manual FIFO probe (driver unbound via `/sys/bus/pci/drivers/intel-lpss/unbind`) still shows bytes stuck in the TX FIFO and no abort reason:
  ```
  $ baremetal_bash '
    BASE=$((0x4017002000))
    mmio=/root/mmio_rw
    write(){ printf "write 0x%X 0x%08X\n" "$1" "$2"; "$mmio" write "$(printf "0x%X" "$1")" "$2"; }
    read32(){ printf "read  0x%X -> " "$1"; "$mmio" read "$(printf "0x%X" "$1")"; }
    write $((BASE+0x6C)) 0x00000000
    for off in 0x40 0x44 0x48 0x4C 0x50 0x54 0x58 0x5C 0x60 0x64 0x68; do
      write $((BASE+off)) 0x00000000
    done
    write $((BASE+0x00)) 0x00000065
    write $((BASE+0x04)) 0x00000018
    write $((BASE+0x6C)) 0x00000001
    read32 $((BASE+0x9C))
    write $((BASE+0x10)) 0x000004AB
    write $((BASE+0x10)) 0x00000204
    sleep 0.02
    read32 $((BASE+0x74))
    read32 $((BASE+0x70))
    read32 $((BASE+0x80))
  '
  read  0x401700209C -> 0x00000001
  read  0x4017002074 -> 0x00000002
  read  0x4017002070 -> 0x00000002
  read  0x4017002080 -> 0x00000000
  ```
  → START still never launches (exactly the failure signature from the earlier VM snapshot).
- Tried forcing pad native mode (`PADCFG0=0x44000B02`) both manually (via `/root/mmio_rw`) and through the new SSDT logic, but firmware immediately restores `0x44000702`. Manually poking `PADCFG1` to `0x0003C01A` also reverts to the firmware value on the next read, indicating the PMC write-protect logic is still in effect.
- Rebinding the controller (`echo 0000:00:19.0 > /sys/bus/pci/drivers/intel-lpss/bind`) restores the driver, but `timeout 15 i2cdetect -r -y 2` continues to time out with an all-`--` matrix and dmesg appends more `i2c_designware i2c_designware.2: controller timed out`.
- Takeaway: `_INI` now fires and sets `IM04`, yet the pads stay in “ISH” mux mode and the DesignWare engine still cannot issue a START. We likely need an additional SGOV/SPC* call (or different PMODE value) to flip the pin function away from ISH_I2C1.
### PCR pad programming & host handoff (2025-10-17)
- Running the devmem2 sequence against `SBREG=0xFD000000` confirmed the per-pad stride is **0x10 bytes**, not 0x08. A quick sweep showed the original (firmware) values at:
  ```
  /usr/local/sbin/devmem2 0xFD6E0738 w → 0x00000100   # earlier guess; same as PADCFG for pad 6
  /usr/local/sbin/devmem2 0xFD6E073C w → 0x00000000
  /usr/local/sbin/devmem2 0xFD6E0740 w → 0x44000300
  /usr/local/sbin/devmem2 0xFD6E0744 w → 0x0000001C
  ```
  After walking the address space in 0x10-byte steps we located the real PADCFG words for the Serial IO bus:
  - **SDA (pad 7)** → `DW0 @ 0xFD6E0770`, `DW1 @ 0xFD6E0774`
  - **SCL (pad 8)** → `DW0 @ 0xFD6E0780`, `DW1 @ 0xFD6E0784`
  `_INI` from `SSDT-I2C4ON` already pushes `DW0=0x44000702` to both pads. `DW1` stubbornly stays at `0x0003C01F/0x0003C020`; even a direct write of `0x0003C01A` is accepted transiently but reverts on the next read (likely because the PMC write-protect logic flips it back).
- **Host ownership**: the first PAD_OWN register (`0xFD6E00B0`) showed `0x00848004`—nibbles for pad 7/8 were zero, but several neighbouring pads were claimed by firmware. Toggling bits 7 and 8 handed ownership explicitly to the OS without disturbing the rest of the field:
  ```
  /usr/local/sbin/devmem2 0xFD6E00B0 w         → 0x00848004   # before
  /usr/local/sbin/devmem2 0xFD6E00B0 w 0x00848184             # after (bits 7/8 set)
  /usr/local/sbin/devmem2 0xFD6E00B0 w         → 0x00848184   # verify
  ```
  Lock registers at `0xFD6E0080/0xFD6E0084` read `0x0078361B`; pads 7/8 sit in a group that isn’t locked, so the write sticks.
- **Verification**: Dumps taken immediately afterwards confirm DW0 values, lock state, and ownership. The pinctrl debugfs report now omits the `[ACPI]` flag for pads 7/8:
  ```
  pin 7 (ISH_I2C1_SDA) 7:INTC1055:00 mode 1 0x44000702 0x0003c01f 0x00000000
  pin 8 (ISH_I2C1_SCL) 8:INTC1055:00 mode 1 0x44000702 0x0003c020 0x00000000
  ```
  Pads 9/10 (firmware’s I2C5) remain `[LOCKED full, ACPI]` at `0x44000300`, so our edits are isolated to the target bus.
- **2025-10-17 follow-up**:
  - Deep reset run (2025-10-17 @ 07:12 UTC):
    ```
    echo i2c_designware.2 > /sys/bus/platform/drivers/i2c_designware/unbind
    echo idma64.2 > /sys/bus/platform/drivers/idma64/unbind
    echo 1 > /sys/bus/pci/devices/0000:00:19.0/remove
    echo 1 > /sys/bus/pci/rescan
    ```
    Device 00:19.0 reappears immediately; PCI runtime PM drops it back to `suspended` until
    `echo on > /sys/devices/pci0000:00/0000:00:19.0/power/control`, after which `runtime_status`
    reports `active` again.
  - After the rescan the kernel immediately re-bound `i2c_designware.2` and `idma64.2`; PCI runtime PM still parked the function in `suspended` until the manual `power/control=on` override.
  - Rebased the `acpi_invoke_ini` helper against `6.16.10-custom`, reloaded it, and watched dmesg confirm `_SB.PC00.I2C4._INI` execution plus `IM04` flipping to `0x01` (`acpi_invoke_ini: IM04 now = 0x01`).
  - Forced the controller out of runtime suspend (`echo on > /sys/devices/pci0000:00/0000:00:19.0/power/control`; `runtime_status` now reports `active`).
  - Repeatedly toggled `IC_ENABLE` via `/usr/local/sbin/devmem2 0x401700206c w {0|1}`; the register latches `1` immediately after the write but the driver drops it back to `0` once the next timeout occurs.
  - Verified pad muxing again through debugfs (same 0x44000702 / 0x0003c01f-20 readback) to confirm AML + manual writes agree.
  - `timeout 15 i2cdetect -r -y 2` and direct `i2ctransfer -f -y 2 w2@{0x18,0x1e,0x11,0x15} 0xAB 0x04` all still return `Connection timed out`; each attempt logs another `i2c_designware i2c_designware.2: controller timed out` burst in dmesg, and reading `IC_ENABLE` immediately afterward shows it back at `0x00000000`.
- **Controller recovery attempts**:
  1. Unbound and rebound the platform driver (`i2c_designware.2`) via `/sys/bus/platform/drivers/i2c_designware/{un,}bind`; the rebind succeeded but `dmesg` flooded with `i2c_designware i2c_designware.2: controller timed out`.
  2. Multiple `i2cdetect -r -y 2` scans all returned `--`, taking ~115 s before timing out.
  3. `lspci` still shows the PCI function (00:19.0), and `firmware_node/path` confirms the ACPI link to `\_SB.PC00.I2C4`; the rebuilt helper module now logs `IM04 = 0x01`, so GNVS sees the override even though the bus keeps timing out.
- **Tooling update (2025-10-17 @ 07:25 UTC)**:
  - BusyBox on the live image does not ship the `devmem` applet and `pacman` has no official `devmem2` package, so we cloned `https://aur.archlinux.org/devmem.git`, built `devmem2.c` with `gcc`, and installed the resulting binary to `/usr/local/sbin/devmem2` (symlinked into `/usr/bin/devmem{,2}`). Verified the helper with `devmem2 0x0 b` before using it for the register work below.
- **SBREG override verification (2025-10-17 @ 07:44 UTC)**:
- `cat /proc/cmdline` shows no `p2sb.sbreg=` entry; we are relying on the new DMI override.
- Confirmed SMBIOS strings on bare metal (via `/sys/class/dmi/id/*` and freshly installed `dmidecode`):
  - `sys_vendor="LENOVO"`
  - `product_name="21ETS1JM00"` (machine-type prefix `21ET`)
  - `product_version="ThinkPad X1 Fold 16 Gen 1"`
  - `product_sku="LENOVO_MT_21ET_BU_Think_FM_ThinkPad X1 Fold 16 Gen 1"`
  - `board_name="21ETS1JM00"`
  - `modalias="dmi:bvnLENOVO:bvrN3LET38W(1.19):...:skuLENOVO_MT_21ET_BU_Think_FM_ThinkPadX1Fold16Gen1:"`
- Regenerated `custom-kernel/patches/0003-platform-x86-p2sb-Try-SBI-unhide-when-scan-fails.patch` so its DMI table now matches all of the above (retail name and 21ES/21ET machine-type prefixes across `product_name`, `product_version`, and `product_sku`). Expect `dmesg` to print `p2sb: DMI match "ThinkPad X1 Fold 16 Gen 1 (...)“` on the next rebuild.
- Dynamic debug enabled via `echo 'file drivers/platform/x86/p2sb.c +p' > /sys/kernel/debug/dynamic_debug/control` for the next boot once the DMI match is fixed.
- **2025-10-17 @ 09:20 UTC sanity sweep (kernel rebuild in progress)**:
  - SBREG pads/locks: `devmem2` reads of `GPIOC0` pad windows (`DW0/DW1`, LOCK/LOCKTX, PAD_OWN) still return `0xFFFFFFFF`, confirming the bridge remains hidden until the new kernel lands.
  - pinctrl snapshot: `/sys/kernel/debug/pinctrl/INTC1055:00/pins` reports pads 7/8 as `mode 1 0x44000702 ... [ACPI]`; ownership has not flipped to the OS yet.
  - LPSS private block (`0000:00:19.0`): `gate=0x0`, `reset=0x7`, `remap=0x17002000/0x40`, `caps=0x4`; no clocks or resets appear asserted.
  - DesignWare registers: `IC_COMP_TYPE=0x44570140`, forcing `IC_ENABLE=1` latches and `IC_ENABLE_STATUS` echoes `0x1`, `IC_STATUS=0x6`, `IC_TX_ABRT_SOURCE=0x0`.
  - `i2cdetect -r -y 2` still times out after ~20 s, with dmesg flooding `i2c_designware.2: controller timed out`.
  - Configfs loader: re-populated `/sys/kernel/config/acpi/table/SSDT4/aml` from `/usr/share/firmware-acpi/SSDT4.aml`; `/sys/firmware/acpi/tables/dynamic/SSDT27` contains the expected `I2C4ON` strings.
  - SBREG stability loop: repeated reads of `0xFD6E000C` remain `0xFFFFFFFF`, so the cached base continues to rely on the kernel quirk.
- **Controller register capture (2025-10-17 @ 07:33 UTC)**:
  - Prior to probing, forced runtime PM to `on`; `lspci` shows PCI power state D0. Register snapshot (all via `devmem2`):
    ```
    power/runtime_status = active
    power/control        = on
    IC_ENABLE            = 0x00000000
    IC_ENABLE_STATUS     = 0x00000000
    IC_STATUS            = 0x00000006   # TFE=1; reserved bit1 also set
    IC_INTR_STAT         = 0x00000000
    IC_RAW_INTR_STAT     = 0x00000000
    IC_TX_ABRT_SOURCE    = 0x00000000
    ```
  - `i2cdetect -r -y 2` (30 s timeout) still reported no devices; the post-scan register dump remained identical to the pre-scan state.
  - Each `i2ctransfer -f -y 2 w2@{0x18,0x1e,0x11,0x15} 0xAB 0x04` timed out in ~1 s; follow-up `0xAB 0x00` writes behaved the same. After every attempt the register block continued to read all zeros with `IC_STATUS=0x00000006` and no abort bits captured.
  - `dmesg` tailed immediately after the sequence shows a burst of `i2c_designware i2c_designware.2: controller timed out` once per second, matching the user-visible timeouts; no additional diagnostic bits latched in hardware.
- **Controller register capture (2025-10-17 @ 07:45 UTC)**:
  - Repeated the deep reset (unbind → D3hot → D0) and reran the probe script with the new `devmem2` helper. `IC_ENABLE`, `IC_ENABLE_STATUS`, `IC_INTR_STAT`, `IC_RAW_INTR_STAT`, and `IC_TX_ABRT_SOURCE` all remain `0x00000000`; `IC_STATUS` stays `0x00000006` before and after every transaction attempt.
  - Each `i2cdetect -r -y 2` (15 s timeout) and `i2ctransfer -f -y 2 w2@{0x18,0x1e,0x11,0x15} {0xAB04,0xAB00}` still times out immediately. `dmesg` logs another burst of `i2c_designware i2c_designware.2: controller timed out` once per second during the loop.
  - Pad mux state now shows host ownership: `pinctrl/INTC1055:00` reports pads 7/8 (`ISH_I2C1_SDA/SCL`) as `mode 1 0x44000702 0x0003c01f/20` with **no** `[ACPI]` tag, confirming `PAD_OWN`=0x00848184 took effect, but the pins still advertise the `ISH_I2C1_*` function (mux likely still on the ISH route until `_INI` runs).
- **Open items after this session**:
  - Figure out why DW1 reverts (does PMC or SHPO enforce its own termination bits?). If the value must stay `0x1F/0x20`, document the electrical implications.
  - Bring the controller out of timeout: try toggling `IC_ENABLE`, clearing `COMBINED_MODE`, or performing a full `intel-lpss` reset before rerunning `i2cdetect`. Retest `IM04` afterwards to be sure AML state persists.
  - Once the bus responds, issue the `{0xAB, 0x04}` / `{0xAB, 0x00}` transactions and capture the panel state change.

- **Manual DW transfer attempt (2025-10-17 @ 17:45 UTC)**:
  - Confirmed the adapter and PCI device share the ACPI path `\_SB_.PC00.I2C4` (`/sys/class/i2c-dev/i2c-2/device/firmware_node/path` and `/sys/bus/pci/devices/0000:00:19.0/firmware_node/path`).
  - With `i2c_designware.2` unbound from the platform driver, issued the two-byte `{0xAB, 0x04}` sequence directly via `/usr/local/bin/mmio_rw`. `IC_ENABLE_STATUS` read back `0x00000001`, the controller status settled at `0x00000002`, and `IC_TX_ABRT_SOURCE` remained `0x00000000` (no START observed).
  - After the manual write, the controller was rebound to `i2c_designware`; behaviour on subsequent driver probes is unchanged (timeouts, `IC_ENABLE` drops back to 0).
- **TX FIFO probe (2025-10-17 @ 17:55 UTC)**:
  - Repeated the manual sequence while sampling the FIFO level: `TXFLR=0x00000002`, `IC_STATUS=0x00000002`, `IC_TX_ABRT_SOURCE=0x00000000`. The delayed enqueue variant (`sleep 200 µs` between writes) produced identical values.
  - Interpretation: bytes *do* land in the FIFO (TFNF=1, TFE=0) but never drain onto the bus, which matches the persistent timeout with a zero abort mask.
  - Pinmux still labels pads 7/8 as `ISH_I2C1_*` even though `[ACPI]` cleared, so the mux likely remains on the ISH fabric until `_INI` executes.
- **Namespace mismatch (same session)**:
  - `acpidbg -b 'execute \\\\_SB_.PC00.I2C4._PS0'` and `_INI` both return `AE_NOT_FOUND`.
  - Decompiling the runtime overlay (`SSDT27`) shows `External (_SB_.PC00.I2C4, DeviceObj)` but its `Scope` block is declared as `(\_SB.PC00.I2C4)` (missing the trailing underscore). The mis-scoped object means the injected `_INI/_PS0` never bind to the live device.
  - Fix: regenerate the SSDT with `Scope (\_SB_.PC00.I2C4)` (or add `External (_SB.PC00.I2C4, DeviceObj)` plus `Alias`) so acpidbg and the firmware interpreter can locate the methods at runtime.

### Build b008 status snapshot (2025-10-17 @ 09:52 UTC)

- SMBIOS strings that the refreshed DMI table matches:

```
$ baremetal_bash 'for f in sys_vendor product_name product_version product_sku board_name modalias; do printf "%s: " "$f"; cat "/sys/class/dmi/id/$f"; done'
sys_vendor: LENOVO
product_name: 21ETS1JM00
product_version: ThinkPad X1 Fold 16 Gen 1
product_sku: LENOVO_MT_21ET_BU_Think_FM_ThinkPad X1 Fold 16 Gen 1
board_name: 21ETS1JM00
modalias: dmi:bvnLENOVO:bvrN3LET38W(1.19):bd05/06/2024:br1.19:efr1.7:svnLENOVO:pn21ETS1JM00:pvrThinkPadX1Fold16Gen1:rvnLENOVO:rn21ETS1JM00:rvrSDK0T76530WIN:cvnLENOVO:ct30:cvrNone:skuLENOVO_MT_21ET_BU_Think_FM_ThinkPadX1Fold16Gen1:
```

- `p2sb` driver output confirms the override path and clean runtime status:

```
$ baremetal_bash "dmesg | grep -i p2sb"
[    0.037444] p2sb: DMI match "ThinkPad X1 Fold 16 Gen 1 (product_version)"
[    0.037445] p2sb early: SBREG via DMI 0xfd000000
[    1.929447] p2sb: DMI match "ThinkPad X1 Fold 16 Gen 1 (product_version)"
[    1.929448] p2sb: SBREG override via ThinkPad X1 Fold 16 Gen 1 (product_version) base=0xfd000000 size=0x1000000
[    1.929450] p2sb: cpu model 154 stepping 4 hidden=1 ret=0 source=override
```

- Doorbell/status registers after boot (no SBI activity yet, GO/DONE latched by firmware):

```
$ baremetal_bash "setpci -s 00:1f.0 d8.l"
0000ffcf
$ baremetal_bash "setpci -s 00:1f.0 d4.l"
00000000
```

- SBREG accesses succeed; pad configuration now shows host ownership on pads 7/8:

```
$ baremetal_bash "dd if=/dev/mem bs=4 skip=$((0xfd6e000c/4)) count=1 2>/dev/null | hexdump -v -e '1/4 \"%08x\\n\"'"
00000700    # PADBAR
$ baremetal_bash "dd if=/dev/mem bs=4 skip=$((0xfd6e0770/4)) count=1 2>/dev/null | hexdump -v -e '1/4 \"%08x\\n\"'"
44000702    # PAD7 DW0
$ baremetal_bash "dd if=/dev/mem bs=4 skip=$((0xfd6e0774/4)) count=1 2>/dev/null | hexdump -v -e '1/4 \"%08x\\n\"'"
0003c01f    # PAD7 DW1
$ baremetal_bash "dd if=/dev/mem bs=4 skip=$((0xfd6e0780/4)) count=1 2>/dev/null | hexdump -v -e '1/4 \"%08x\\n\"'"
44000702    # PAD8 DW0
$ baremetal_bash "dd if=/dev/mem bs=4 skip=$((0xfd6e0784/4)) count=1 2>/dev/null | hexdump -v -e '1/4 \"%08x\\n\"'"
0003c020    # PAD8 DW1
$ baremetal_bash "dd if=/dev/mem bs=4 skip=$((0xfd6e00b0/4)) count=1 2>/dev/null | hexdump -v -e '1/4 \"%08x\\n\"'"
00848184    # PAD_OWN (pads 7/8 now host-controlled)
$ baremetal_bash "dd if=/dev/mem bs=4 skip=$((0xfd6e0080/4)) count=1 2>/dev/null | hexdump -v -e '1/4 \"%08x\\n\"'"
0078361b    # lock region
```

- Pinctrl dump mirrors the register reads — pads 7/8 no longer show the `[ACPI]` tag:

```
$ baremetal_bash "grep -n 'pin 7 ' /sys/kernel/debug/pinctrl/INTC1055:00/pinmux-pins"
10:pin 7 (ISH_I2C1_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
$ baremetal_bash "grep -n 'pin 8 ' /sys/kernel/debug/pinctrl/INTC1055:00/pinmux-pins"
11:pin 8 (ISH_I2C1_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
```

- Serial IO controller still times out at probe time:

```
$ baremetal_bash "i2cdetect -r -y 2"
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- -- 
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
70: -- -- -- -- -- -- -- --                         
```

- Initramfs still carries the AML payloads, and after restoring `load-ssdt4.service` the dynamic table set now includes the injected override:

```
$ baremetal_bash "lsinitcpio -l /boot/arch/boot/x86_64/initramfs-linux-custom.img | grep SSDT"
kernel/firmware/acpi/SSDT1.aml
kernel/firmware/acpi/SSDT2.aml
kernel/firmware/acpi/SSDT3.aml
kernel/firmware/acpi/SSDT4.aml
kernel/firmware/acpi/tables/SSDT1.aml
kernel/firmware/acpi/tables/SSDT2.aml
kernel/firmware/acpi/tables/SSDT3.aml
kernel/firmware/acpi/tables/SSDT4.aml
$ baremetal_bash "ls /sys/firmware/acpi/tables/dynamic"
SSDT19
SSDT20
SSDT21
SSDT22
SSDT23
SSDT24
SSDT25
SSDT26
SSDT27
$ baremetal_bash 'for t in /sys/firmware/acpi/tables/dynamic/SSDT*; do strings "$t" 2>/dev/null | grep -E "POMEON|LOADCHK|I2C4ON" && echo "  -> $(basename "$t")"; done'
I2C4ON
LOADCHK
  -> SSDT27
```

- `/usr/local/bin/check-ssdt-markers` confirms the staged AML files and now reports the loader unit as enabled (initramfs still not visible locally on the live system):

```
$ baremetal_bash "/usr/local/bin/check-ssdt-markers"
[16:21:08] POMEON: marker "POMEON" present in SSDT1.aml
[16:21:08] CANARY: marker "LOADCHK" present in SSDT2.aml
[16:21:08] PWRMFORCE: marker "APDN" present in SSDT3.aml
[16:21:08] I2C4ON: marker "I2C4ON" present in SSDT4.aml
[16:21:08] No initramfs candidates found locally
[16:21:08] load-ssdt4.service is enabled
[16:21:08] Found ACPI override/table messages:
[    ... snip ... ]
[    0.439060] ACPI: SSDT 0xFFFF888101313C00 000394 (v02 PmRef  Cpu0Cst  00003001 INTL 20200717)
[    0.441594] ACPI: SSDT 0xFFFF888102575800 00051E (v02 PmRef  Cpu0Ist  00003000 INTL 20200717)
[    ... snip ... ]
[22894.243838] ACPI: SSDT 0xFFFF88822F1A7800 000153 (v02 X1FD   I2C4ON   00000001 INTL 20250404)
```

- `acpidbg` wrapper is installed with mode 0755, but invoking `_SB.PC00.I2C4._PS0/_INI` still returns `AE_NOT_FOUND` (the namespace hook needs further investigation):

```
$ baremetal_bash "ls -l /usr/local/bin/acpidbg"
-rwxr-xr-x 1 root root 405 Oct 17 16:03 /usr/local/bin/acpidbg
$ baremetal_bash "/usr/local/bin/acpidbg -b 'execute \\\\_SB.PC00.I2C4._INI'"
Evaluating \_SB.PC00.I2C4._INI
Evaluation of \_SB.PC00.I2C4._INI failed with status AE_NOT_FOUND
```

Summary: the DMI override unblocks SBREG access (`ret=0`) and the restored `load-ssdt4.service` now injects SSDT4 dynamically, but `_SB.PC00.I2C4` methods still fail to execute via `acpidbg` and the DesignWare engine never launches a transaction (no abort bits, long timeouts). Next steps: confirm the AML mux methods run and track why the DW driver clears `IC_ENABLE` immediately after each attempt.

### Bare-metal pad retest (2025-10-17 @ 20:45 UTC)
- Rebuilt and reinserted the helper so `_INI` now executes on the live kernel (`6.16.10-custom`):  
  ```
  $ source ./funcs
  $ baremetal_bash 'cd /root/acpi_invoke_ini && make clean && make'
  $ baremetal_bash 'insmod /root/acpi_invoke_ini/acpi_invoke_ini.ko'
  $ baremetal_bash 'dmesg | tail -n6'
  [38276.008650] acpi_invoke_ini: selected handle \_SB_.PC00.I2C4
  [38276.009479] acpi_invoke_ini: successfully evaluated \_SB_.PC00.I2C4._INI
  [38276.009488] acpi_invoke_ini: IM04 now = 0x01
  ```
- Captured fresh register state immediately afterwards using `/root/mmio_rw` (values unchanged from earlier runs):  
  ```
  PAD_OWN        @0xFD6E00B0 → 0x00848184
  PAD7_DW0/DW1   @0xFD6E0770/4 → 0x44000702 / 0x0003C01F
  PAD8_DW0/DW1   @0xFD6E0780/4 → 0x44000702 / 0x0003C020
  ```
  Writing `PADCFG0=0x44000B02` for pads 7/8 persists (no automatic rollback), but `PADCFG1` reverts to `0x0003C01F/20` within microseconds. Debugfs still labels the pads as `ISH_I2C1_*` and shows the mux unclaimed:
  ```
  $ baremetal_bash 'head -n12 /sys/kernel/debug/pinctrl/INTC1055:00/pinmux-pins'
  pin 7 (ISH_I2C1_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
  pin 8 (ISH_I2C1_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
  ```
- Repeated the manual DesignWare poke with the platform driver unbound; the FIFO still fills without launching a START:
  ```
  $ baremetal_bash 'echo i2c_designware.2 > /sys/bus/platform/drivers/i2c_designware/unbind'
  $ baremetal_bash '
    BASE=$((0x4017002000)); mmio=/root/mmio_rw
    for off in 0x40 0x44 0x48 0x4C 0x50 0x54 0x58 0x5C 0x60 0x64 0x68; do $mmio write $(printf "0x%X" $((BASE+off))) 0; done
    $mmio write $(printf "0x%X" $((BASE+0x00))) 0x00000065
    $mmio write $(printf "0x%X" $((BASE+0x04))) 0x00000018
    $mmio write $(printf "0x%X" $((BASE+0x6C))) 0x00000001
    $mmio read  $(printf "0x%X" $((BASE+0x9C)))
    $mmio write $(printf "0x%X" $((BASE+0x10))) 0x000004AB
    $mmio write $(printf "0x%X" $((BASE+0x10))) 0x00000204
    sleep 0.02
    $mmio read  $(printf "0x%X" $((BASE+0x74)))   # TXFLR
    $mmio read  $(printf "0x%X" $((BASE+0x70)))   # STATUS
    $mmio read  $(printf "0x%X" $((BASE+0x80)))   # TX_ABRT_SOURCE
  '
  0x00000002  (TXFLR)
  0x00000002  (IC_STATUS)
  0x00000000  (IC_TX_ABRT_SOURCE)
  $ baremetal_bash 'echo i2c_designware.2 > /sys/bus/platform/drivers/i2c_designware/bind'
  ```
- With the driver rebound, `timeout 5 i2cdetect -r -y 2` still stalls and `dmesg` logs another burst of `i2c_designware ... controller timed out`. Register snapshot while the driver is active remains unchanged:
  ```
  $ baremetal_bash '
    BASE=$((0x4017002000)); mmio=/root/mmio_rw
    for off in 0x00 0x04 0x10 0x1C 0x2C 0x6C 0x70 0x74 0x80; do
      printf "%#04x: " $off; $mmio read $(printf "0x%X" $((BASE+off)))
    done
  '
  0x0000: 0x00000065   (IC_CON)
  0x0004: 0x0000000c   (IC_TAR)
  0x006c: 0x00000000   (IC_ENABLE)
  0x0070: 0x00000006   (IC_STATUS)
  0x0074: 0x00000000   (DW_IC_TXFLR)
  0x0080: 0x00000000   (IC_TX_ABRT_SOURCE)
  ```
- Removed the helper module afterwards (`baremetal_bash 'rmmod acpi_invoke_ini'`) to leave the kernel clean.
- Decompiling the firmware copy of `SSDT2` shows it passes pad selectors `0x09/0x0A` (no 0x6E community bits). Our override still uses `0x006E0007/08`, which would make `GGRP()` return `0x6E` and index past the `GPCL` table. Needs follow-up: switch to plain `0x07/0x08` selectors or provide the correct encoded value before regenerating the AML.

### Selector downgrade attempt (2025-10-17 @ 21:05 UTC)
- Updated `acpi/SSDT-I2C5ON.dsl` so `_INI` now feeds `\_SB.SGOV`/`SPC0`/`SPC1` with raw pad numbers (`0x07`, `0x08`) instead of the prior `0x006E0007/08`. Rebuilt the table locally (`iasl -tc acpi/SSDT-I2C5ON.dsl`) and pushed the AML to the host:
  ```
  $ baremetal_scp acpi/SSDT-I2C5ON.aml /root/SSDT-I2C5ON.aml
  $ baremetal_bash 'cat /root/SSDT-I2C5ON.aml > /sys/kernel/config/acpi/table/SSDT4/aml'
  ```
- Re-ran `_INI` via the helper (rebuilt just in case) and grabbed the confirmation from dmesg:
  ```
  $ baremetal_bash 'cd /root/acpi_invoke_ini && make'
  $ baremetal_bash 'insmod /root/acpi_invoke_ini/acpi_invoke_ini.ko'
  $ baremetal_bash 'dmesg | tail -n4'
  [38958.924290] acpi_invoke_ini: IM04 now = 0x01
  ```
- Post-`_INI` register dump shows **no change** versus the previous revision:
  ```
  $ baremetal_bash '/root/mmio_rw read 0xFD6E00B0'           → 0x00848184
  $ baremetal_bash '/root/mmio_rw read 0xFD6E0770'           → 0x44000702
  $ baremetal_bash '/root/mmio_rw read 0xFD6E0774'           → 0x0003C01F
  $ baremetal_bash '/root/mmio_rw read 0xFD6E0780'           → 0x44000702
  $ baremetal_bash '/root/mmio_rw read 0xFD6E0784'           → 0x0003C020
  $ baremetal_bash 'sed -n "7,12p" /sys/kernel/debug/pinctrl/INTC1055:00/pinmux-pins'
  pin 7 (ISH_I2C1_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
  pin 8 (ISH_I2C1_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
  ```
  PADCFG0 stays at `0x44000702`; `SPC0` either keeps forcing PMODE=1 or firmware restores it immediately. The pinctrl view still reports the pads on the ISH function.
- Repeated the bare-metal DesignWare poke (leaving the platform driver bound this time) and still saw a stuck FIFO with no abort reason:
  ```
  write IC_DATA_CMD → TXFLR=0x00000002, IC_STATUS=0x00000002, IC_TX_ABRT_SOURCE=0x00000000
  ```
  Driver behaviour after rebinding is unchanged (`timeout 5 i2cdetect -r -y 2` → controller timed out; IC_ENABLE drops back to 0).
- Removed `acpi_invoke_ini` again (`baremetal_bash 'rmmod acpi_invoke_ini'`) as a clean-up step.
- Conclusion: using bare pad indices for SGOV/SPC* doesn’t flip the mux either; Lenovo’s firmware SSDT uses selectors `0x09/0x0A`, so the next experiment should match those exactly (or inspect `GGRP()`/`GNMB()` to derive the expected values for pads 7/8).

### Namespace + selector sweep (2025-10-17 @ 22:05 UTC)
- Regenerated `acpi/SSDT-I2C5ON.dsl` with the corrected scope (`Scope (\_SB.PC00.I2C4)`) and updated `External()` declarations so the override actually augments the live device. `_INI` now allocates two selector candidate lists:
  ```asl
  Local3 = Package (0x04) { 0x090E0007, 0x006E0007, 0x000E0007, 0x00000007 }
  Local4 = Package (0x04) { 0x090E0008, 0x006E0008, 0x000E0008, 0x00000008 }
  ```
  Each entry is fed through `\_SB.SGOV`, `\_SB.SPC0`, and `\_SB.SPC1` so we hit both the vendor-style selectors (`0x090E0007/08`), the raw community encodings (`0x006E0007/08`, `0x000E0007/08`), and the plain pad indices (`0x00000007/08`) in a single pass.
- Built and pushed the AML, then reloaded it via configfs and re-ran `_INI` with `acpi_invoke_ini.ko`:
  ```
  $ iasl -tc acpi/SSDT-I2C5ON.dsl
  $ baremetal_scp acpi/SSDT-I2C5ON.aml /root/SSDT-I2C5ON.aml
  $ baremetal_bash 'cat /root/SSDT-I2C5ON.aml > /sys/kernel/config/acpi/table/SSDT4/aml'
  $ baremetal_bash 'rmmod acpi_invoke_ini || true'
  $ baremetal_bash 'insmod /root/acpi_invoke_ini/acpi_invoke_ini.ko'
  $ baremetal_bash "dmesg | grep -i acpi_invoke_ini | tail -n3"
  [41581.820258] acpi_invoke_ini: selected handle \_SB_.PC00.I2C4
  [41581.821692] acpi_invoke_ini: successfully evaluated \_SB_.PC00.I2C4._INI
  [41581.821712] acpi_invoke_ini: IM04 now = 0x01
  ```
- Immediately after `_INI`, the pad registers remain unchanged:
  ```
  $ baremetal_bash '/root/mmio_rw read 0xFD6E0770' → 0x44000702
  $ baremetal_bash '/root/mmio_rw read 0xFD6E0774' → 0x0003C01F
  $ baremetal_bash '/root/mmio_rw read 0xFD6E0780' → 0x44000702
  $ baremetal_bash '/root/mmio_rw read 0xFD6E0784' → 0x0003C020
  $ baremetal_bash \
      "grep -n 'pin [78] ' /sys/kernel/debug/pinctrl/INTC1055:00/pinmux-pins"
  10:pin 7 (ISH_I2C1_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
  11:pin 8 (ISH_I2C1_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
  ```
  `PAD_OWN` stays latched at `0x00848184`, proving `_INI` still flips ownership, but every selector permutation leaves `PADCFG0/1` at the firmware defaults and the pinctrl view on the ISH function.
- Manual DesignWare poke (with the platform driver unbound) still shows bytes stuck in the TX FIFO and no abort source, matching the pre-change behaviour:
  ```
  TXFLR=0x00000002  IC_STATUS=0x00000002  IC_TX_ABRT_SOURCE=0x00000000
  ```
- Rebound `i2c_designware.2` and unloaded the helper module afterwards to keep the host clean:
  ```
  $ baremetal_bash 'echo i2c_designware.2 > /sys/bus/platform/drivers/i2c_designware/bind'
  $ baremetal_bash 'rmmod acpi_invoke_ini'
  ```
- Takeaway: even with the namespace corrected and multiple selector formats tried, `SGOV/SPC0/SPC1` never move pads 7/8 off the ISH function. Next debugging steps:
  1. Inspect `SPC0` semantics (it may mask in only specific bits) and capture the memory writes it issues via `GPC0()` to confirm whether anything lands in the intended PADCFG registers.
  2. Decode `GNUM/GADR` for group 0 and compare against the selectors firmware uses for other 0x006E0000 pads to pin down the exact encoding Lenovo expects.
  3. If `SPC1` continues to revert to `0x0003C01F/20`, plan a direct PCR write (or PMC disable) so the RX/TX enables stick before retrying the DesignWare START probe.

### Mux autoprobe harness (2025-10-17 @ 22:35 UTC)
- Added `/root/mux_autoprobe.sh` and `/root/pmode_sweep.sh` to the host (source in `tools/`). Both rely on the new AML helper `XSEL()` and the existing `/root/mmio_rw` utility. The harness unbinds `i2c_designware.2`, brings the controller up, sweeps selector candidates through `XSEL`, and checks `DW_IC_TXFLR`, `DW_IC_STATUS`, and `DW_IC_TX_ABRT_SOURCE` after queuing `{0xAB, 0x04}`.
- Selector sweep output (no values drained the FIFO or set `ABRT`):
  ```
  $ baremetal_bash '/root/mux_autoprobe.sh'
  Selector   TXFLR     STATUS    ABRT
  ------------------------------------
  0x090E0007 0x00000002 0x00000002 0x00000000
  0x090E0008 0x00000002 0x00000002 0x00000000
  0x006E0007 0x00000002 0x00000002 0x00000000
  0x006E0008 0x00000002 0x00000002 0x00000000
  0x000E0007 0x00000002 0x00000002 0x00000000
  0x000E0008 0x00000002 0x00000002 0x00000000
  0x00000007 0x00000002 0x00000002 0x00000000
  0x00000008 0x00000002 0x00000002 0x00000000
  0x00       0x00000002 0x00000002 0x00000000
  0x01       0x00000002 0x00000002 0x00000000
  0x02       0x00000002 0x00000002 0x00000000
  0x03       0x00000002 0x00000002 0x00000000
  0x04       0x00000002 0x00000002 0x00000000
  0x05       0x00000002 0x00000002 0x00000000
  0x06       0x00000002 0x00000002 0x00000000
  0x07       0x00000002 0x00000002 0x00000000
  0x08       0x00000002 0x00000002 0x00000000
  0x09       0x00000002 0x00000002 0x00000000
  0x0A       0x00000002 0x00000002 0x00000000
  0x0B       0x00000002 0x00000002 0x00000000
  0x0C       0x00000002 0x00000002 0x00000000
  0x0D       0x00000002 0x00000002 0x00000000
  0x0E       0x00000002 0x00000002 0x00000000
  0x0F       0x00000002 0x00000002 0x00000000
  ```
  Every candidate left the pins reported as `ISH_I2C1_*`:
  ```
  $ baremetal_bash "grep -n 'pin [78] ' /sys/kernel/debug/pinctrl/INTC1055:00/pinmux-pins"
  10:pin 7 (ISH_I2C1_SDA): (MUX UNCLAIMED) (GPIO UNCLAIMED)
  11:pin 8 (ISH_I2C1_SCL): (MUX UNCLAIMED) (GPIO UNCLAIMED)
  ```
- PCR fallback (`/root/pmode_sweep.sh`) also failed to trigger a START:
  ```
  $ baremetal_bash '/root/pmode_sweep.sh'
  PMODE   TXFLR       ABRT
  -------------------------
  2      0x00000002 0x00000000
  3      0x00000002 0x00000000
  4      0x00000002 0x00000000
  5      0x00000002 0x00000000
  ```
  The sweep momentarily programmed `PAD7/8_DW0` to `0x44001700`; both were restored to `0x44000702` afterwards for parity with prior snapshots. `PADCFG1` remained `0x0003C01F/0x0003C020` throughout.
- Cleanup steps: rebound `i2c_designware.2`, unloaded `acpi_invoke_ini`, and re-asserted PADCFG0 `0x44000702` so the baseline state matches earlier runs.
- Conclusion: automated selector and PMODE brute force confirms the pads never leave the ISH function. Next action is deeper decoding of Lenovo’s selector encoding (likely via `GPC0`/`GADR` traces) or identifying the PMC bit that locks PADCFG1 so the vendor methods can stick.

### XSEL sysfs bridge + selector decode (2025-10-17 @ 23:05 UTC)
- Extended `acpi_invoke_ini` into a persistent helper: it now exposes `/sys/kernel/acpi_mux/selector` (write a selector, module runs `_SB.PC00.I2C4.XSEL`) and `/sys/kernel/acpi_mux/info` (read-only snapshot of the last invocation: group, pad index, DW0/DW1 before/after). The module still calls `_INI` at load and keeps `IM04` in sync.
- Latest rebuild (2025-10-20) also records the GNVS scratch slots (`SRT1/SER1/SRT2/SER2/SMR0/SMR1`) plus the START canary results (`ABRT/TXFV`); refer to `acpi_mux_info_latest.txt` for the captured values.
- Recompiled and loaded on 6.16.10-custom with:  
  ```bash
  make -C /usr/lib/modules/$(uname -r)/build M=/root/acpi_invoke_ini_src modules
  rmmod acpi_invoke_ini || true
  insmod /root/acpi_invoke_ini_src/acpi_invoke_ini.ko
  ```
  `/sys/kernel/acpi_mux/{selector,info,method}` become available immediately after `insmod`.

## Mux Handshake Reproduction Checklist (2025-10-20)
1. **Deploy SSDT** – copy `acpi/SSDT6.aml` to the host and reload via configfs:
   ```bash
   mkdir /sys/kernel/config/acpi/table/I2C4GOV
   cat /root/SSDT6.aml > /sys/kernel/config/acpi/table/I2C4GOV/aml
   ```
2. **Install helpers** – build + insert `acpi_invoke_ini.ko` (per commands above).  
3. **Enable kprobes trace** – minimal sequence used for the capture:
   ```bash
   TR=/sys/kernel/debug/tracing
   mount -t debugfs none /sys/kernel/debug 2>/dev/null || true
   : > $TR/kprobe_events
   echo 'p:acpi_mem acpi_ex_system_memory_space_handler addr=%si' > $TR/kprobe_events
   echo 'p:acpi_io acpi_ex_system_io_space_handler addr=%si val=%cx' >> $TR/kprobe_events
   echo 1 > $TR/events/kprobes/acpi_mem/enable
   echo 1 > $TR/events/kprobes/acpi_io/enable
   echo 1 > $TR/events/kprobes/enable
   echo nop > $TR/current_tracer
   : > $TR/trace
   echo 1 > $TR/tracing_on
   ```
4. **Trigger the handshake** – `echo 0x090E0007 > /sys/kernel/acpi_mux/selector` (selector replays `XSEL`).  
5. **Stop trace & collect logs**:
   ```bash
   echo 0 > $TR/tracing_on
   cat $TR/trace > /tmp/tail300.raw
   awk '/acpi_mem/' /tmp/tail300.raw > /tmp/tail300.gnvs
   awk '/acpi_io/'  /tmp/tail300.raw > /tmp/tail300.io
   cat /sys/kernel/acpi_mux/info > /tmp/acpi_mux_info.txt
   ```
   Expect `tail300.io` to show an `addr=0xb2` write, while `tail300.gnvs` lists the mailbox offsets `0x936C3FD8`–`0x936C3FEC`. The info file should match the values noted above.
6. **Optional cleanup** – disable kprobes (`echo 0 > $TR/events/kprobes/enable`) and clear `kprobe_events` once captures are done.
- Rebuilt and reloaded the AML so `XSEL` records `XSL*` diagnostics. Writing selectors via the new sysfs hook confirms Lenovo’s encoding:
  - `0x090E0007` → group `0x0E`, index `0x07`; `DW0` stays `0x44000B00`, `DW1` stays `0x0003C033`.
  - `0x090E0008` → group `0x0E`, index `0x08`; `DW0` stays `0x44000B00`, `DW1` stays `0x0003C034`.
  - Plain `0x00000007/0x00000008` report group `0x00`, index `0x07/0x08` with the current host-tuned values (`DW0=0x44000B02`, `DW1=0x0003C01F/20`).
- Updated `/root/mux_autoprobe.sh` so each selector write is followed by a `cat /sys/kernel/acpi_mux/info`, letting us capture the vendor bookkeeping alongside the DW register snapshot. The head of the output now looks like:
  ```
  $ baremetal_bash '/root/mux_autoprobe.sh'
  Selector   TXFLR     STATUS    ABRT
  ------------------------------------
  0x090E0007 0x00000002 0x00000002 0x00000000
  selector=0x90e0007
  group=0xe
  number=0x7
  dw0_before=0x44000b00
  dw1_before=0x0003c033
  dw0_after=0x44000b00
  dw1_after=0x0003c033
  0x090E0008 0x00000002 0x00000002 0x00000000
  selector=0x90e0008
  group=0xe
  number=0x8
  dw0_before=0x44000b00
  dw1_before=0x0003c034
  dw0_after=0x44000b00
  dw1_after=0x0003c034
  ```
- Takeaways:
  1. Lenovo’s selectors for pads 7/8 are indeed `0x090E0007/0x090E0008` (group `0x0E`, indices `7/8`).
  2. The vendor sequence writes the same values we already see at runtime (`DW0=0x44000B00`, `DW1=0x0003C033/34`)—it never enables RX/TX bits or the requested pull settings. Our overlay (`SPC0/SPC1`) tries to push `0x44000B02` / `0x0003C01A`, but the firmware (or PMC) immediately restores its own template.
  3. TX FIFO behaviour is unchanged: every selector still leaves `TXFLR=0x2` / `ABRT=0`, so the mux is not handing the bus to Serial-IO yet.
- Next steps (tracked in TODO): instrument `GPC0`/`SPC0` to see the actual memory writes (looking for the PADCFG offsets the firmware uses), and investigate whether PMC gating is blocking bit[1] (RX/TX enable) so our `0x44000B02` payload can persist.

### Host-ownership toggle experiment (2025-10-18 @ 00:35 UTC)
- Updated `acpi/SSDT-I2C5ON.dsl` so `XSEL` now captures host-switch ownership before/after (`XSLH`/`XSLP`) and calls `\_SB.SHPO(selector, One)` prior to blasting the pad config. Re-deployed the table by recreating `/sys/kernel/config/acpi/table/SSDT4` to avoid stale copies.
- Extended `acpi_invoke_ini` to publish the new diagnostics—`host_before` / `host_after` appear in `/sys/kernel/acpi_mux/info`.
- `baremetal_bash '/root/mux_autoprobe.sh'` now shows the ownership bit flipping for the SDA pad:
  ```
  0x090E0007 ... host_before=0x0 host_after=0x1 dw0_before=0x44000b00 dw0_after=0x44000b00
  0x090E0008 ... host_before=0x1 host_after=0x1 dw0_before=0x44000b00 dw0_after=0x44000b00
  ```
  So `SHPO` succeeds (pad 7 becomes host-owned) but the PADCFG payload is still coerced back to `0x44000B00`.
- Post-run register dump confirms both pins are host-owned yet PMODE remains unchanged:
  ```
  $ baremetal_bash '/root/mmio_rw read 0xFD6A00BC'   # HOSTSW_OWN community 0x0E
  0x00809FA7   # bits 7 and 8 now set
  $ baremetal_bash '/root/mmio_rw write 0xFD6A0AE0 0x44000B02 && /root/mmio_rw read 0xFD6A0AE0'
  0x44000b00   # HW immediately restores DW0
  ```
- Conclusion: grabbing host ownership alone is not enough—the PMC (or another guard) still snaps PADCFG0 back to the firmware template. Next experiment should chase the write-protect path (`GADR(...,0x05)` / `PadCfgLock*`) or replicate the vendor `SGOV` toggle sequence to see what frees PMODE.

### SGWP/SPMV attempt (2025-10-17 @ 23:38 UTC)
- Reworked `acpi/SSDT-I2C5ON.dsl` so `XSEL` now clears the write-protect nibble (`\_SB.SGWP(selector, 0)`), reapplies PMODE via `\_SB.SPMV(selector, 0x02)`, toggles the RX state (`\_SB.SGRA(selector, One)`), and writes back `PADCFG0/1` using the live values (`Local6 = GPC0 | 0x3`, `Local7 = (GPC1 & 0xFFFFFFD6) | 0x1A`). Rebuilt (`iasl -tc acpi/SSDT-I2C5ON.dsl`), pushed the AML to `/sys/kernel/config/acpi/table/SSDT4/aml`, and reloaded `acpi_invoke_ini.ko`.
- Fresh selector sweep still fails to drain the FIFO. Representative rows from `baremetal_bash '/root/mux_autoprobe.sh'`:
  ```
  Selector   TXFLR     STATUS    ABRT
  ------------------------------------
  0x090E0007 0x00000002 0x00000002 0x00000000
  selector=0x90e0007
  group=0xe number=0x7
  host_before=0x1 host_after=0x1
  dw0_before=0x44000b00 dw0_after=0x44000b01
  dw1_before=0x0003c033 dw1_after=0x0003c033

  0x090E0008 0x00000002 0x00000002 0x00000000
  selector=0x90e0008
  group=0xe number=0x8
  host_before=0x1 host_after=0x1
  dw0_before=0x44000b00 dw0_after=0x44000b01
  dw1_before=0x0003c034 dw1_after=0x0003c034
  ```
  Bit 0 now sticks (`dw0_after` ends in `...01`), but bit 1 refuses to stay asserted and PADCFG1 remains at the firmware template (`0x0003C033/34`). `TXFLR` and `IC_STATUS` stay at `0x2`, confirming the controller still never issues a START.
- Direct MMIO pokes agree: forcing either value beyond firmware defaults is immediately clamped by the platform controller.
  ```
  $ baremetal_bash '/root/mmio_rw write 0xFD6A0AE0 0x44000B03 && /root/mmio_rw read 0xFD6A0AE0'
  0x44000b01
  $ baremetal_bash '/root/mmio_rw write 0xFD6A0AE0 0x44000B02 && /root/mmio_rw read 0xFD6A0AE0'
  0x44000b00
  $ baremetal_bash '/root/mmio_rw read 0xFD6A0AE0 && /root/mmio_rw read 0xFD6A0AE4'
  0x44000b00
  0x0003c033
  $ baremetal_bash '/root/mmio_rw read 0xFD6A0AF0 && /root/mmio_rw read 0xFD6A0AF4'
  0x44000b01
  0x0003c034
  ```
- Pinctrl continues to advertise both pads as `ISH_I2C1_*`, so the mux never leaves ISH control despite the new AML sequence.
- Outcome: clearing SGWP and reapplying PMODE updates only flip bit 0 and leave PADCFG1 untouched; the PMC still overrides TX enable and pull-up settings. Next dive needs to decode how Lenovo’s firmware actually programs PADCFG1 (likely via the `GADR(...,0x06/0x07)` path or a PMC-side handshake) so the serial IO function can hold the bus.

### GGOV/GPMV instrumentation (2025-10-18 @ 00:55 UTC)
- Extended both the AML (`XSLM/XSLQ/XSLV/XSLZ`) and `acpi_invoke_ini` so every selector run logs the PMODE field (`GPMV`) and ownership toggle bit (`GGOV`) before/after our overrides. The sysfs bridge now exposes these values (`cat /sys/kernel/acpi_mux/info` shows `ggov_*` and `gpmv_*` lines) and `dmesg` captures the raw numbers (`acpi_invoke_ini: XSLM=...`, etc.).
- Key observations from `baremetal_bash '/root/mux_autoprobe.sh'`:
  - Lenovo’s targets (selectors `0x090E0007/08`, group `0x0E`) already report `ggov_before=ggov_after=0x1` and `gpmv_before=gpmv_after=0x2`. The firmware has the ownership bit set and PMODE locked to value 2 before we touch anything; our `SGOV/SPMV` calls make no functional change.
  - Legacy pads in group `0x00` (e.g., selectors `0x0`, `0x1`) show `ggov_* = 0x0` and `gpmv_* = 0x1`, proving the telemetry discriminates between “Serial-IO native” and “GPIO” configurations.
  - Despite PMODE already being 2, `dw0_after` refuses to keep `TXE` high (`0x...01` only) and `dw1_after` remains at the firmware template (`0x0003C033/34`). Nothing in the GNVS selectors indicates a missing enable step inside SGOV/SPMV themselves.
- Interpretation: the pads are already owned by the PCH Serial-IO block and nominally in function 2, but a secondary agent (likely the PMC via PadCfgLock registers) is forcing the TX enable and pull configuration back to the Lenovo defaults immediately after any write. To progress we need to trace the lock registers (`GADR(group, 0x05..0x07)`) or identify the extra SGOV sequence firmware executes before toggling these pads live.

### Technical recap (2025-10-17 @ 23:45 UTC)
- **Current mux posture:** Pads 7/8 remain branded `ISH_I2C1_*` and every selector/PMODE probe leaves `TXFLR=0x2`, `IC_STATUS=0x2`, `IC_TX_ABRT_SOURCE=0`. The DesignWare engine never issues START, so the custom SSDTs still fail to marshal traffic onto Serial-IO.
- **Scaffolding in place:**  
  - `acpi_invoke_ini.ko` exposes `/sys/kernel/acpi_mux/{selector,info}` and reliably triggers `_SB.PC00.I2C4.XSEL`, capturing GNVS telemetry (`XSL*` fields).  
  - `/root/mux_autoprobe.sh` sweeps selectors, queues FIFO writes, and logs DW/host ownership deltas; `/root/pmode_sweep.sh` brute-forces PMODE values.  
  - `acpi/SSDT-I2C5ON.dsl` now:  
    1. Claims pad ownership (`SHPO`).  
    2. Clears pad write-protect (`SGWP(selector, 0)`).  
    3. Forces PMODE field (`SPMV(selector, 0x2)`).  
    4. Enables RX (`SGRA(selector, 1)`).  
    5. Rewrites PADCFG0/1 using live firmware values with `RXE|TXE` asserted and pulls tightened.  
  - All edits are tracked in this repo so AML deployments remain reproducible.
- **Observed hardware behavior:**  
  - `dw0_after` toggles bit 0 (RX enable) but bit 1 (TX enable) is still cleared by platform firmware; PADCFG1 reverts to `0x0003C033/34`.  
  - Direct MMIO writes (`0xFD6A0AE0/4`, `0xFD6A0AF0/4`) exhibit the same clamp, confirming a PMC or GPIO community agent rewrites the registers post-write.  
  - Ownership bits (`HOSTSW_OWN`) stick after `SHPO`; the block is not a simple “ISH still owns the pad” problem.
- **Working hypotheses:**  
  1. Lenovo’s firmware performs an additional unlock via `GADR(group, 0x06/0x07)` (PadCfgLock/PadCfgTx) or through PMC sideband messages.  
  2. The selector handshake may require a matching `SGOV(..., 0)` tail call (mirroring the firmware’s SGOV toggles seen in `dsdt.dsl`) to release the lock.  
  3. A PCH strap or PMC policy is masking PADCFG1 writes unless a hidden GNVS bit advertises Serial-IO ownership.
- **Action items going forward:**  
  - Diff firmware traces around `SPC0/SPC1/SGOV` call sites (e.g., `dsdt.dsl:28097` EC handler) to capture their complete unlock sequence.  
  - Inspect `GADR(group, 0x05..0x07)` outputs at runtime (requires instrumenting `GPC2/GPC3` equivalents or dumping PMC CSR windows) to locate the pad lock bits.  
  - Once PADCFG1 can be held at `0x0003C01A` and both RX/TX bits stay high, repeat the mux autoprobe → driver rebind → `i2ctransfer` validation to confirm the SSDT pipeline is functional.

### PadCfg lock map via GADR[5..7] (2025-10-18 @ 01:43 UTC)
- Parsed `GPCL` for selector group `0x0E` (the Lenovo encodings `0x090E0007/08`) and confirmed the GPIO community base is `SBRG + 0x006A0000`. `GADR(group, idx)` therefore resolves to:  
  - `idx 0x05` → `SBRG + 0x006A014C` (PadCfgLock block: first dword = `LOCK`, +0x20 = `LOCKTX`).  
  - `idx 0x06` → `SBRG + 0x006A0098` (PadCfgLock1).  
  - `idx 0x07` → `SBRG + 0x006A009C` (PadCfgLock1 Tx mirror).  
  Each pad still uses the standard mask `1 << (pad_index % 32)` with stride `(pad_index >> 5) * 4`, as seen in `CAGS`/`ISME` and `GLOC`/`GLOT`.
- Firmware helpers around these registers behave exactly like Intel’s reference flow:  
  - `CAGS(selector)` writes a single-bit mask into the first dword at `GADR(...,0x05)` (locking the pad).  
  - `ISME(selector)` reads the `LOCK` and `LOCKTX` dwords (offsets 0x00/0x20) to decide whether a pad is still “mask enabled”.  
  - `GLOC/GLOT` read the `PadCfgLock1{,Tx}` dwords at `GADR(...,0x06/0x07)` to mirror the same bit positions. No AML clears these bits; they are write-one-to-set like the datasheet describes.
- Direct MMIO sampling on b008 confirms the live register state for group 0x0E (pads 0–24):
  ```text
  $ baremetal_bash 'printf "PadCfgLock0  : " ; /root/mmio_rw read 0xFD6A014C ; \
                    printf "PadCfgLockTx : " ; /root/mmio_rw read 0xFD6A016C ; \
                    printf "PadCfgLock1  : " ; /root/mmio_rw read 0xFD6A0098 ; \
                    printf "PadCfgLock1Tx: " ; /root/mmio_rw read 0xFD6A009C'
  PadCfgLock0  : 0x00020008
  PadCfgLockTx : 0x00000000
  PadCfgLock1  : 0x00000040
  PadCfgLock1Tx: 0x00000040
  ```
  Bits for our targets (`SDA` = pad 7 → mask `0x00000080`, `SCL` = pad 8 → mask `0x00000100`) are all **clear** in every register; only pads 3, 6, and 17 are presently locked.
- Implication: PADCFG1 reverts even though the lock registers for pads 7/8 are open. The next unlock step must therefore live elsewhere (likely a PMC sideband that rewrites PADCFG after every write). Any future experiment that toggles these pads should still double-check that the masks stay zero before/after the write to avoid tripping the W1S locks.

### Windows OEM capture plan (2025-10-18 @ 02:20 UTC)
Goal: record how Lenovo’s stock Windows image programs the Serial-IO I²C4 stack so we can diff GNVS/PMC state against Linux. Run everything from an elevated PowerShell prompt inside the Windows session (reverse proxy on port 2223). Write all artefacts to `C:\acpi-capture` so we can pull them back later.

1. **Prep & logging**
   - `New-Item -Force -ItemType Directory C:\acpi-capture`
   - `Start-Transcript -Path C:\acpi-capture\windows-capture.log`
   - `systeminfo | Out-File C:\acpi-capture\systeminfo.txt`
   - `Get-PnpDevice -PresentOnly | Sort-Object Class, FriendlyName | Out-File C:\acpi-capture\pnp-present.txt`
   - `Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'ACPI*' -or $_.InstanceId -like 'PCI\\VEN_8086&DEV_7A13*' } | Get-PnpDeviceProperty DEVPKEY_Device_DriverProvider | Format-List | Out-File C:\acpi-capture\pnp-i2c.txt`

2. **Dump ACPI tables (if WDK tools available)**
   - If `C:\Windows\System32\acpidump.exe` exists, run `acpidump.exe -b -n DSDT -n SSDT -o C:\acpi-capture\acpi-tables.dat`.
   - Otherwise, document the absence in the transcript; we can revisit with the Windows ADK if needed.

3. **Install Chipsec tooling (one-time)**
   - `winget install --id Python.Python.3.12 --silent` (only if `python` is missing).
   - `python -m pip install --upgrade pip chipsec`
   - `Set-Location $env:ProgramFiles\Python*\Scripts` (or add to `$env:Path`).

4. **MMIO register grabs (after Chipsec driver loads)**
   - `chipsec_util mmio read 0xFD6A00B0 1 > C:\acpi-capture\pad-own.txt` (HOSTSW_OWN for group 0x0E).
   - `chipsec_util mmio read 0xFD6A0AE0 2 > C:\acpi-capture\pad7-dw.txt`
   - `chipsec_util mmio read 0xFD6A0AF0 2 > C:\acpi-capture\pad8-dw.txt`
   - `chipsec_util mmio read 0xFD6A014C 2 > C:\acpi-capture\pad-lock0.txt`
   - `chipsec_util mmio read 0xFD6A0098 2 > C:\acpi-capture\pad-lock1.txt`
   - `chipsec_util mmio read 0x4017002000 0x20 > C:\acpi-capture\dw-i2c4.txt` (DesignWare block first 32 bytes).

5. **GNVS probe (optional)**
   - `chipsec_util mem read 0x00000000 0x100000 -o C:\acpi-capture\mem-1M.bin` (only if dump size acceptable; we can filter GNVS offsets later).

6. **Wrap up**
   - `Stop-Transcript`
   - Compress artefacts: `Compress-Archive -Path C:\acpi-capture\* -DestinationPath C:\acpi-capture.zip -Force`
   - We can pull the archive with `baremetal_fetch` once collection finishes.

Notes:
- Chipsec loads a signed driver; approve any Windows Defender prompts. If `chipsec_util` fails to open the driver, rerun PowerShell as Administrator and retry.
- Record any errors (missing tools, access denied) in the transcript so we know what to revisit.
- Do not change runtime power/Bios settings during capture; we want the pristine OEM configuration.

### Windows capture attempt (2025-10-18 @ 03:45 UTC)
- Connected via `ssh -p 2223 fenlo@localhost` (PowerShell shell, user `portable\fenlo` has local admin rights).
- Created `C:\acpi-capture` and staged:
  - `systeminfo.txt` (`systeminfo` dump).
  - `pnp-present.txt` (`Get-PnpDevice -PresentOnly | Sort-Object Class, FriendlyName`).
  - `pnp-i2c.txt` (filtered `Get-PnpDevice` output for `ACPI*` + `PCI\VEN_8086&DEV_7A13*`).
  - `pnputil-system.txt` (`pnputil /enum-devices /class System`).
  - `acpidump-missing.txt` (notes `acpidump.exe` absent on stock image).
  - `windows-capture.log` (transcript stub from the initial session).
- Limitation: the transcript only records the `Start-Transcript` call because each `ssh … powershell -Command …` invocation spawns a fresh process. For a full log, wrap the workflow in a dedicated script (`capture_windows_baseline.ps1`) and run it once so `Start-Transcript` remains active.
- Archived the directory via `Compress-Archive -Path C:\acpi-capture\* -DestinationPath C:\acpi-capture.zip -Force`.
- Chipsec install failed: `python -m pip install chipsec` aborts with `error: Microsoft Visual C++ 14.0 or greater is required` (needs Visual Studio Build Tools). Consequently no MMIO/PadCfg dumps yet.
  - Next action: install the Microsoft C++ Build Tools (or fetch a pre-built Chipsec binary/driver) and rerun Step 4 (`chipsec_util mmio …`) to capture PADCFG and DesignWare registers.
- TODO for the next capture pass:
  1. Execute the plan through a single PowerShell script so transcription covers the whole run.
  2. Repeat Step 4 once Chipsec tooling is in place; save the resulting `pad-own`, `pad7-dw`, `pad8-dw`, `pad-lock*`, and `dw-i2c4` dumps under `C:\acpi-capture`.
  3. Optionally add a GNVS snapshot (Step 5) if Chipsec proves stable; document any large dumps before transfer.

### Build Tools + Chipsec setup (2025-10-18 @ 04:35 UTC)
- Installed Visual Studio 2022 Build Tools non-interactively:
  ```
  winget install --id Microsoft.VisualStudio.2022.BuildTools \
    --accept-package-agreements --accept-source-agreements \
    --override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
  ```
  Rebooted the Windows host afterwards (`shutdown /r /t 0`).
- Reconnected on port 2223 and upgraded Python tooling from pip:
  - `python -m pip install --upgrade pip chipsec` now succeeds (`chipsec-1.13.16`, `pywin32-311`).
- Attempted to capture MMIO state via a scripted PowerShell pass (`windows-capture-02.log`). Each `chipsec_util mmio …` invocation failed with `CHIPSEC Windows Driver Not Found`, so the output files currently contain only the error banner:
  - `pad-own-20251018.txt`, `pad7-dw-20251018.txt`, `pad8-dw-20251018.txt`
  - `pad-lock0-20251018.txt`, `pad-locktx-20251018.txt`, `pad-lock1-20251018.txt`, `pad-lock1tx-20251018.txt`
  - `dw-i2c4-20251018.txt`
- Root cause: the kernel driver (`chipsec_hlpr.sys`) is not present in the pip distribution. The helper module `chipsec.modules.tools.windows.build` is also missing, so we cannot compile the driver in-place with `chipsec_main`.
- Next actions before rerunning the capture:
  1. Clone the upstream Chipsec repository and build the Windows helper driver via `python setup.py build_ext --inplace` or the provided `msbuild` scripts (requires the VS build environment we just installed). Copy the resulting `chipsec_hlpr.sys` + `chipsec_service.exe` into `%PROGRAMFILES%\chipsec` or alongside `chipsec_util.exe`.
  2. Load the driver once (`chipsec_util platform driver load`) to confirm the service installs cleanly; keep track of any UAC prompts.
  3. Re-run the PowerShell capture script so the new MMIO dumps include actual register values; update `C:\acpi-capture.zip` with the fresh outputs.

### Chipsec driver build (2025-10-18 @ 06:32 UTC)
- Added the missing Visual Studio components:
  - WDK integration (`WindowsKernelModeDriver10.0` toolset now appears under `MSBuild\Microsoft\VC\v170\Platforms\*\PlatformToolsets`).
  - Spectre-mitigated CRT libraries (`Microsoft.VisualStudio.Component.VC.SpectreMitigation`).
- Built the helper from `C:\Users\fenlo\chipsec`:
  ```
  VsDevCmd -arch=amd64
  msbuild drivers\windows\chipsec\chipsec_hlpr.vcxproj ^
          /p:Configuration=Release /p:Platform=x64 ^
          /p:RunInfVerif=false /p:SignMode=Off
  ```
  Output:
  - `chipsec\helper\windows\windows_amd64\chipsec_hlpr.sys` (39,936 bytes).
  - Unsigned `.cat`/`.inf` in `drivers\windows\chipsec\x64\Release\chipsec_hlpr\`.
- Copied the newly built driver into the pip install path so `chipsec_util` can find it:
  ```
  copy chipsec\chipsec\helper\windows\windows_amd64\chipsec_hlpr.sys `
       %LOCALAPPDATA%\Programs\Python\Python312\Lib\site-packages\chipsec\helper\windows\windows_amd64\
  ```
- Attempted to load via `python -m chipsec_util platform driver`; Windows refused with error 577 (“Windows cannot verify the digital signature for this file.”). Secure Boot + KMCS enforcement block unsigned kernel drivers, so the helper will not load until either:
  1. The system is booted with test-signing enabled (`bcdedit /set testsigning on` + reboot, Secure Boot disabled), **or**
  2. The driver is signed with a trusted kernel-mode certificate (e.g., cross-signed / WHQL / EV attestation).
- Because the driver cannot load, `chipsec_util mmio …` calls still fail; the MMIO capture step remains pending.

Next Windows-side options:
1. Enable test-signing mode temporarily (requires `bcdedit` + reboot + Secure Boot off).
2. Generate a test code-signing certificate, import it into the machine’s Trusted Root / Trusted Publishers stores, and sign `chipsec_hlpr.sys` (and optionally the `.cat`). This still requires Secure Boot disabled.
3. If neither is acceptable, switch to a Linux/Baremetal environment for MMIO dumps using the existing `mmio_rw` tool.

### Test-signed driver + MMIO capture (2025-10-18 @ 06:45 UTC)
- Generated a local machine code-signing certificate with the kernel-mode EKU and injected it into both `Trusted Root` and `Trusted Publishers`:
  ```
  New-SelfSignedCertificate -Subject 'CN=ChipsecTest' `
      -Type CodeSigningCert -CertStoreLocation 'Cert:\LocalMachine\My' `
      -KeyUsage DigitalSignature -KeyExportPolicy Exportable `
      -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3,1.3.6.1.4.1.311.61.1.1')
  Export-Certificate … | certutil -addstore TrustedPublisher/Root …
  ```
- Signed both copies of `chipsec_hlpr.sys` (`repo` + `pip` install) using `signtool sign /fd SHA256 /sha1 <thumb> /s My /sm`.
- `python -m chipsec_util platform driver` now succeeds (`chipsec_hlpr` loads from `%LOCALAPPDATA%\Programs\Python\Python312\Lib\site-packages\chipsec\helper\windows\windows_amd64`), so MMIO access works on the Windows host without additional privileges.
- Re-ran the MMIO probe with Chipsec and captured fresh dumps to `C:\acpi-capture\*` (duplicated into `C:\acpi-capture.zip` for retrieval):
  - `pad-own-20251018.txt`: `0xFD6A00B0` → `0x00000004` (only the low nibble asserts, consistent with PMIO still hiding the host ownership bitmap).
  - `pad7-dw0-20251018.txt`: `0xFD6A0AE0` → `0x84000201`; `pad7-dw1-20251018.txt`: `0x00000033`.
  - `pad8-dw0-20251018.txt`: `0xFD6A0AF0` → `0x44000300`; `pad8-dw1-20251018.txt`: `0x00000034`.
  - Lock registers: `pad-lock0` = `0x00020008`; `pad-locktx` = `0x00000000`; `pad-lock1` = `pad-lock1tx` = `0x00000040`.
  - `dw-i2c4-20251018.txt` shows the 0x40-byte DW block still returning all `0xFFFFFFFF` (SBREG bridge hidden on Windows just like Linux).
- Updated archive: `C:\acpi-capture.zip` now contains the signed-driver telemetry (`pad*-20251018*.txt`, `dw-i2c4-20251018.txt`, etc.) for off-box analysis.

### Windows dock/detach telemetry rollup (2025-10-18 @ 12:05 UTC)
- Archived the three Chipsec capture sets under `docs/acpi-capture-detached.zip`, `docs/acpi-capture-docked.zip`, and `docs/acpi-capture-transition.zip`. Each archive includes the MMIO dumps (`pad*-*.txt`, `pad-lock*.txt`, `dw-i2c4-*.txt`), Plug-and-Play inventory, and the session log corresponding to the state noted in the filename.
- Core PADCFG findings are identical across all three states:
  - `pad7` (SDA) reports `DW0 = 0x84000201`, `DW1 = 0x00000033`.
  - `pad8` (SCL) reports `DW0 = 0x44000300`, `DW1 = 0x00000034`.
  - Pad lock registers stay fixed (`PADCFGLOCK0 = 0x00020008`, `PADCFGLOCKTX = 0x00000000`, `PADCFGLOCK1 = PADCFGLOCK1TX = 0x00000040`), and `PADOWN` shows only bit 2 asserted (`0x00000004`). Attachment/detachment of the keyboard base does not toggle any of these fields within the measurement window.
- Compared with the Linux bare-metal baseline (`DW0 ≈ 0x44000B00` for both pads, reverting to `0x44000B00/01` after our overrides), Windows keeps the host-sw ownership bit asserted (`0x80000000`), selects a leaner PMODE (`0x00000300` / `0x00000200` instead of `0x00000B00`), and leaves only the TX enable bit set on SDA (`…01`). PADCFG1 values (`0x00000033/34`) match the firmware template we observe on Linux after the PMC restores the defaults—so Windows never exposes the `0x0003C033/34` pattern we tried to write.
- The DesignWare window (`dw-i2c4-*.txt`) still returns `0xFFFFFFFF`, confirming that SBREG remains hidden from the Windows environment despite the helper driver; any live controller state will need to be sampled either through an OEM tool or via the bare-metal Linux setup.
- Each capture bundle also contains a 1 MiB MMIO snapshot (`mem-1M-*.bin`). We have not diffed these binaries yet; they likely cover the PMC community space around the pad registers and should be cross-checked once we know which offsets gate the mux.
- Conclusion: docking state does not influence the pad mux configuration under Windows, and Microsoft’s driver stack programs SDA/SCL to static values that differ from the Lenovo firmware defaults we see on Linux. The remaining gap is still the PMC process that enforces those Windows-style values immediately after any override—analysis of the 1 MiB dumps and the GNVS helpers should focus on reproducing that sequence in our AML.

### Windows capture diff analysis (2025-10-18 @ 13:32 UTC)
- Parsed all three archives in `docs/` (`detached`, `docked`, `transition`) and confirmed that every Chipsec MMIO read inside the bundles resolves to the same register values:
  - `PADCFG0` SDA (`0xFD6A0AE0`) → `0x84000201` (host-sw bit set, TX enabled, PMODE `0x2`); `PADCFG1` SDA (`0xFD6A0AE4`) → `0x00000033`.
  - `PADCFG0` SCL (`0xFD6A0AF0`) → `0x44000300` (host ownership without host-sw bit, PMODE `0x3`); `PADCFG1` SCL (`0xFD6A0AF4`) → `0x00000034`.
  - Ownership/lock telemetry is static: `PADOWN` (`0xFD6A00B0`) = `0x00000004`, `PADCFGLOCK0` (`0xFD6A014C`) = `0x00020008`, `PADCFGLOCKTX` (`0xFD6A016C`) = `0x00000000`, `PADCFGLOCK1`/`PADCFGLOCK1TX` (`0xFD6A0098/0xFD6A009C`) = `0x00000040`.
  - The DesignWare aperture readbacks (`0x4017002000 + offset`) stay saturated with `0xFFFFFFFF` regardless of state, reiterating that the SBREG window remains gated on Windows.
- The detached capture uses the earlier ASCII pipeline (`*-20251018.txt`) while the docked/transition sets are UTF-16, but the numerical payload is identical. We now treat the 2025-10-18 captures as a single baseline because no register diverged across the three physical keyboard states.
- Diffed the 1 MiB PMC snapshots: `mem-1M-docked.bin` and `mem-1M-transition.bin` are byte-for-byte identical. The detached run pre-dated that script, so no binary exists there. This suggests the PMC community page around `0xFD6A0000` does not change during a 5 s dock/undock transition.
- PnP inventories:
  - `pnputil-system-*.txt` and `pnp-present-*.txt` match exactly between docked and transition (SHA-256 identical), so the global ACPI namespace stays stable.
  - `pnp-i2c` differs only in ordering and the subset collected when the earlier detached script ran; the union of DeviceIDs is unchanged. No new I²C enumerations appear when the base reconnects.
- Implications for Linux work:
  1. Windows keeps SDA’s host-sw bit high while leaving SCL under pure host ownership; our AML should do the same before asking SGOV/SPC* to flip the mux.
  2. The PMC reasserts `PADCFG0 = 0x84000201/0x44000300` and `PADCFG1 = 0x33/0x34` immediately after any override, independently of keyboard state. The unlock sequence we search for must therefore replicate the Windows provisioning path, not a dock-triggered delta.
  3. Because SBREG is hidden even with Chipsec, DesignWare runtime state must still be inspected from the bare-metal environment; the Windows captures only constrain the pad template we should aim to reproduce.

### Bare-metal mux retest (2025-10-18 @ 13:48 UTC)
- Re-synced tooling onto the X1 Fold target (`/root/tools`): `mmio_rw`, `mux_autoprobe.sh`, `pmode_sweep.sh`, `p2sb-unhide`, `p2sb-recover`, and the rebuilt `acpi_invoke_ini` module compiled directly against `6.16.10-custom`.
- Reloaded the latest `SSDT-I2C5ON.aml` via configfs (`/sys/kernel/config/acpi/table/SSDT4`) before inserting `acpi_invoke_ini.ko`. The module now publishes `/sys/kernel/acpi_mux/{selector,info}` without errors.
- Baseline MMIO (after SSDT load):  
  - `read 0xFD6A0AE0` → `0x84000201`, `read 0xFD6A0AE4` → `0x00000033`.  
  - `read 0xFD6A0AF0` → `0x44000300`, `read 0xFD6A0AF4` → `0x00000034`.  
  These match the Windows template exactly, confirming that our override (or the PMC) has already driven the host-sw bit on SDA while leaving SCL at host ownership only.
- `mux_autoprobe.sh` with the new sysfs bridge (`MMIO=/root/tools/mmio_rw ./mux_autoprobe.sh`):
  ```
  Selector   TXFLR     STATUS    ABRT
  ------------------------------------
  0x090E0007 0xffffffff 0xffffffff 0xffffffff
  selector=0x90e0007
  group=0xe
  number=0x7
  host_before=0x0
  host_after=0x1
  ggov_before=0x1
  ggov_after=0x1
  gpmv_before=0x0
  gpmv_after=0x2
  dw0_before=0x84000201
  dw1_before=0x00000033
  dw0_after=0x84000201
  dw1_after=0x00000033
  ```
  - Sysfs mirrors the dmesg trace (`XSLH=0x00 → XSLP=0x01`, `XSLM=0x00 → XSLQ=0x02`, `XSLV/XSLZ=0x01`), so the AML path is executing and toggling the GNVS selectors exactly once.
  - However, the DesignWare MMIO reads still return `0xFFFFFFFF`; both `mmio_rw 0x4017002074` and the pmode sweep report the same. The P2SB bridge refuses to unhide (`p2sb-unhide` → “still hidden”, `p2sb-recover` → `VID=0xFFFF`), so SBREG remains inaccessible and the FIFO telemetry is not trustworthy yet.
- `pmode_sweep.sh` corroborates that PMODE `2` is the first candidate to trip the “activity” heuristic, but the `0xFFFFFFFF` readbacks again imply SBREG is still gated.
- Action items:
  1. Fix the P2SB exposure on this kernel (audit BIOS guards or update the unhide helper) so `/dev/mem` reads return real DesignWare values—without that we cannot observe TXFLR draining.
  2. Once SBREG is reachable, rerun the selector sweep to confirm whether the Windows-template PADCFG values are sufficient to launch START (expect TXFLR → `0x0` or ABRT ≠ 0).
  3. Keep the rebuilt `acpi_invoke_ini.ko` handy (`/root/tools/acpi_invoke_ini/`); unload with `rmmod acpi_invoke_ini` once tests finish to return the machine to its baseline.

### ACPI write trace with kprobe helper (2025-10-18 @ 16:55 UTC)
- Built a scratch kernel module (`kernel_modules/acpi_kprobe/`) that registers kprobes on `acpi_ex_system_memory_space_handler` and `acpi_ex_system_io_space_handler`. Each SystemMemory/IO write made by AML is logged (via `pr_info`) and the most recent values are mirrored under `/sys/kernel/acpi_mux_trace/{last_mem_write,last_io_write}`.
- Deployed the module to `b009` (`/root/acpi_kprobe`), inserted it, and replayed the mux selector writes (`echo 0x090E0007` / `0x090E0008` → `/sys/kernel/acpi_mux/selector`). The resulting trace (saved on the target as `/tmp/acpi_mem_trace.log` and copied locally for analysis) shows the exact byte-wise sequence used by Lenovo’s AML:

  | Selector | Target | Write order (addr → value, width 8 bit) | Notes |
  |----------|--------|------------------------------------------|-------|
  | `0x090E0007` | Pad 62 (`DW0/DW1` @ `0xFD6A0AE0`) | `0x936C217A→0x01`, `0xFD6A00BC→0xA7`, `0xFD6A00BD→0x9F`, `0xFD6A00BE→0x80`, `0xFD6A00BF→0x00`, `0xFD6A0AE0→0x01`, `0xFD6A0AE5→0x00`, `0xFD6A0AE1→0x0B`, `0xFD6A0AE2→0x10`, `0xFD6A0AE0→0x03`, `0xFD6A0AE1→0x0B`, `0xFD6A0AE2→0x00`, `0xFD6A0AE3→0x44`, `0xFD6A0AE0→0x01`, `0xFD6A0AE4→0x1A`, `0xFD6A0AE5→0x00`, `0xFD6A0AE6→0x00`, `0xFD6A0AE7→0x00` | Writes 0x00809FA7 into `HOSTSW_OWN` (bytes @ 0xFD6A00BC..BF), then programs `PADCFG0=0x44000B01`. `PADCFG1` lands at `0x0000001A` before the PMC template later restores `0x00000033`. |
  | `0x090E0008` | Pad 63 (`DW0/DW1` @ `0xFD6A0AF0`) | `0x936C217A→0x01`, `0xFD6A00BC→0xA7`, `0xFD6A00BD→0x9F`, `0xFD6A00BE→0x80`, `0xFD6A00BF→0x00`, `0xFD6A0AF0→0x01`, `0xFD6A0AF5→0x00`, `0xFD6A0AF1→0x0B`, `0xFD6A0AF2→0x10`, `0xFD6A0AF0→0x03`, `0xFD6A0AF1→0x03`, `0xFD6A0AF2→0x00`, `0xFD6A0AF3→0x44`, `0xFD6A0AF0→0x01`, `0xFD6A0AF4→0x1E`, `0xFD6A0AF5→0x00`, `0xFD6A0AF6→0x00`, `0xFD6A0AF7→0x00` | Mirrors the SDA flow but leaves `PADCFG1=0x0000001E` before the PMC rewrites it back to `0x00000034`. |

- Key takeaways:
  1. Every mux attempt starts by toggling GNVS at `0x936C217A` (likely the `IM04` selector latch) and asserting host-software ownership (`HOSTSW_OWN` mask → `0x00809FA7`). Reproducing this preamble is mandatory.
  2. The AML writes `PADCFG0` byte-by-byte, briefly setting the low byte to `0x03` before restoring `0x01`, so any replay must preserve that intermediate step.
  3. `PADCFG1` is written to `0x0000001A/0x0000001E`, but within a millisecond the PMC forces the familiar Lenovo template (`0x00000033/0x00000034`). This confirms the reversion is performed outside ACPI (likely a PMC task), not by the interpreter itself.
  4. No SystemIO traffic was observed for these selectors; all writes stay in SystemMemory.
- Action items stemming from the trace:
  - Encode the exact byte sequence above into our AML `XSEL` path (or the initramfs helper) so the PMC at least sees the same handshake Lenovo uses before it asserts its own template.
  - Investigate the firmware agent that rewrites `PADCFG1`. Since the PMC fires after our ACPI sequence, we may need either (a) to mimic whatever additional GNVS flag Windows sets before issuing the mux, or (b) lock the pads immediately after writing, on lab hardware, to prove the PMC is the culprit.

### Trace-based capture of the XSEL handshake (2025-10-18 @ 16:57 UTC)
- Hooked `acpi_ex_system_memory_space_handler`/`acpi_os_write_pci_configuration`/`acpi_ns_evaluate` via tracefs kprobes so we could log every write emitted while `_SB.PC00.I2C4.XSEL()` runs. The raw trace is saved as `acpi_mem_trace.txt` (see working tree) and the filtered write-only view lives in `acpi_mem_writes.txt`.
- Each selector invocation (`0x090E0007` for pad 62, `0x090E0008` for pad 63) repeats the same byte-level program sequence:

  | Step | Address (community 0x6A) | Meaning | Value | Notes |
  |------|--------------------------|---------|-------|-------|
  | 1 | `0x936C217A` | `IM04` / GNVS selector latch | `0x01` | Matches Lenovo GNVS toggle. |
  | 2–5 | `0xFD6A00BC`..`0xFD6A00BF` | `HOSTSW_OWN` dword | Bytes `A7 9F 80 00` → `0x00809FA7` | Asserts host-sw bits the same way Windows does. |
  | 6–13 | `0xFD6A0AE0`..`0xFD6A0AE3` (pad 62 DW0) | PADCFG0 byte writes | `01→03→01` pattern with high byte `0x44` | Reproduces the temporary `0x...03` low byte before settling on `0x44000B01`. |
  |   | `0xFD6A0AE4`..`0xFD6A0AE7` (pad 62 DW1) | PADCFG1 | Writes `0x0003C01A` (bytes `1A C0 03 00`). |
  | 14–21 | `0xFD6A0AF0`..`0xFD6A0AF3` (pad 63 DW0) | PADCFG0 (pad 63) | Same pattern → final `0x44000301`. |
  |   | `0xFD6A0AF4`..`0xFD6A0AF7` (pad 63 DW1) | PADCFG1 (pad 63) | Writes `0x0003C01E` (bytes `1E C0 03 00`). |
- The handler never touches the lock registers (`PadCfgLock*`); after the trace finishes the PMC immediately restores PADCFG1 to Lenovo’s defaults (`0x00000033/0x00000034`), exactly as we observed with the earlier module sandbox.
- Key takeaways:
  1. The AML handshake is byte-for-byte identical across both pads and mirrors the Windows provisioning path we captured earlier (`IM04`, `HOSTSW_OWN`, PADCFG0 strobes, then PADCFG1).
  2. We now have explicit offsets for each byte write (`0xFD6A0AE[0-7]`, `0xFD6A0AF[0-7]`), so the replay helper or SSDT can emit the same sequence without guessing.
  3. Because the PMC rewrite happens after the last PADCFG1 hit, the missing piece remains the lock/commit handshake (likely hidden in `SGWP`/`SPC*`). The next job is to trace `SGWP`/`SGOV` so we can map their register writes (and, if necessary, replicate them before the PMC reasserts the template).

### Bare-metal replay & probe sanity (2025-10-18 @ 19:50 UTC)
- Installed `python` on the target host (`pacman -Sy --noconfirm python`) so the existing `probe_start.sh` sleep helper works without local edits; verified `python --version` → `3.13.7`.
- Re-ran the OEM replay + probe on hardware:
  - `MMIO=/root/tools/mmio_wrapper.sh ./replay_oem_sequence.sh` still fails because `/dev/mem` cannot write the GNVS window; fall back to the `acpi_mux` interface.
  - `MMIO=/root/tools/mmio_wrapper.sh ./probe_start.sh` now executes, but the FIFO continues to grow (`attempt=1 TXFLR=0x0000000a`, `attempt=2 TXFLR=0x0000000b`, `attempt=3 TXFLR=0x0000000c`) with `TX_ABRT_SOURCE=0` every time, confirming no START launched.
  - `pad_sweep.sh` immediately after reports the PMC template again: pad 62 `DW1=0x0003c033`, pad 63 `DW1=0x0003c034` (matches the sysfs canary from `acpi_mux/info`).
- Dmesg remains quiet apart from the expected `/dev/mem` PAT warning (`x86/PAT: mmio_rw … write-back`).
- Takeaways / next steps:
  1. The byte-perfect replay alone is insufficient; the PMC agent still rewrites PADCFG1 within ≈1 ms.
  2. Proceed with the SGWP/SGOV/SPC* trace so we can capture the firmware’s unlock/commit handshake and mirror it before the agent runs.
  3. Keep `mmio_wrapper.sh` and `probe_manual.sh` in `/root/tools/` for quick reruns; they depend on the same `mmio_rw` binary and now on Python being available.

### Linux boot hardening + DW bring-up sequence (2025-10-18 @ 17:05 UTC)
- **Boot arg refresh pushed into every loader path** (systemd-boot, Syslinux, GRUB). Each menu entry now sets:
  - `p2sb.sbreg=0xFD000000` so SBREG is always mapped without needing the P2SB hide dance.
  - `modprobe.blacklist=intel_lpss,intel_lpss_pci,i2c_designware_platform` (plus the `module_blacklist=` twin) to keep LPSS/DW drivers off the bus until after the replay + manual probes.
- **Verification checklist after booting the latest ISO:**
  1. `cat /proc/cmdline` → confirm the override and blacklist flags are present once the initramfs finishes.
  2. `lsmod | grep -E 'intel_lpss|i2c_designware'` → expect no matches before you intentionally `modprobe` later.
  3. `/sys/kernel/config/acpi/table/I2C4RPLY/aml` should exist (loaded by `load-ssdt-replay.service`).
- **Deterministic DW power-on helper (manual for now):**
  ```bash
  MMIO=/root/tools/mmio_rw
  BAR=0x4017002000
  $MMIO w32 $((BAR + 0x6C)) 0x0           # IC_ENABLE = 0
  usleep 100
  con=$($MMIO r32 $((BAR + 0x00)))
  con=$(( (con & ~0x21) | 0x21 ))          # ensure MASTER|RESTART
  $MMIO w32 $((BAR + 0x00)) $con
  $MMIO w32 $((BAR + 0x04)) 0x003A         # provisional TAR (panel uC)
  $MMIO w32 $((BAR + 0x6C)) 0x1           # IC_ENABLE = 1
  usleep 200
  $MMIO r32 $((BAR + 0x9C))               # IC_ENABLE_STATUS (expect 1)
  ```
- **Strict START canary (post-replay, before PMC reapply):**
  ```bash
  TEX=$((BAR + 0x74)); ABRT=$((BAR + 0x80)); STAT=$((BAR + 0x70))
  $MMIO w16 $((BAR + 0x10)) 0x00AB        # DATA_CMD (no STOP)
  usleep 200
  $MMIO w16 $((BAR + 0x10)) 0x0204        # DATA_CMD with STOP
  for i in 1 2 3 4 5; do
      printf 'TXFLR=%#010x ABRT=%#010x STAT=%#010x\n' \
        "$($MMIO r32 $TEX)" "$($MMIO r32 $ABRT)" "$($MMIO r32 $STAT)"
      usleep 2000
  done
  ```
  - **Success signature:** `TXFLR` drains to 0 *or* `TX_ABRT_SOURCE` becomes non-zero (even a NACK proves the START launched).
  - If `TXFLR` only grows and `ABRT=0`, the PMC template still wins → proceed with the SGWP/lock trace below.
- **Next steps once BAR access is reliable:**
  1. Re-run the tracefs capture (kprobes on `acpi_ns_evaluate`, `acpi_ex_system_memory_space_handler`, and `acpi_os_write_pci_configuration`) to isolate the SGWP/SGOV/SPC* commit writes.
  2. Lab-only: immediately set the discovered PadCfgLock W1S bits after our PADCFG1 writes to prove the mux sticks ≥ 50 ms before codifying the handshake in AML.
  3. When the commit path is known, append it to `SSDT-I2C4REPLAY` and only then allow LPSS drivers to load (`modprobe intel_lpss_pci i2c_designware_platform`) to validate with `i2cdetect`/`i2ctransfer`.

### Fresh XSEL trace + tooling refresh (2025-10-19 @ 02:30 UTC)
- **Tooling state:**
  - Rebuilt `tools/mmio_rw` in place to use `mmap(2)` instead of `pread/pwrite`, fixing the strict-devmem SIGBUSs once the kernel boots with `iomem=relaxed strict_devmem=0`.
  - Hardened `tools/trace_sgwp.sh` so it programs the kprobe, toggles `tracing_on`, and dumps the buffered trace (`trace` file) instead of relying on `trace_pipe`. The script now emits both `/tmp/sgwp_trace.raw` (full trace) and `/tmp/sgwp_trace.summary` on the target.
  - Captured binaries from the bare-metal host back into the repo (`tools/mmio_rw`, `tools/devmem2`) to keep local + remote copies in sync.
- **What we traced:** ran `/root/tools/trace_sgwp.sh` twice — first with our overlay (`SSDT-I2C4REPLAY`) to sanity check, then after loading the OEM `SSDT4-live.aml` to watch Lenovo’s real `_SB.PC00.I2C4.XSEL` implementation. Both logs are in `/tmp/sgwp_trace.raw|.summary` on the host (and mirrored locally).
- **Key findings (vendor XSEL path):**
  1. `IM04` still flips to `0x01`, but **no host-ownership bytes** (`FD6A00BC..BF`) are touched — Lenovo relies on prior firmware state. Our replay overlay reintroduced that write on purpose.
  2. `_SB.SGOV/_SB.SPC0/_SB.SPC1` sequence issues the same PAD writes we have been hand-coding: `FD6A0AE0..AF7` get the `0x03→0x01` byte shuffle and DW1 → `0x0003C01A/1E`. Every write is paired with interpreter reads (function=0) first; the raw trace shows the exact order and confirms there are **no extra writes to PadCfgLock or companion PCR offsets**.
  3. After the PAD update Lenovo’s AML spams a buffer at **0x904Fxxxx** with ASCII strings (`"TCSS RP _DSW TUID -0x0"`, `"TB2F ..."`, etc.) and pointer updates. That region dereferences to SBRG + 0x004F0000 (derived from the `GPCL` table) and appears to be a logging mailbox, not a hardware handshake.
  4. No accesses landed in the suspected PMC/PWRM window (`setpci -s 00:1f.0 0x48.L` still reads zero), and the kprobe never saw writes beyond the PAD DWords + GNVS logging. **Bottom line:** Lenovo’s AML does not try to lock the pads; the PMC revert we observe after ~1 ms is purely firmware-side.
- **Implications:** we must supply the lock ourselves (PadCfgLock W1S or equivalent) after the replay if we want the mux to persist. The DSL provides helpers (`SGWP`, `SGRA`, `CAGS`) that target other GPIO registers; those are the next suspects for implementing a software lock. For now, the summary makes it clear there is no hidden handshake we missed.
- **Next steps:**
  1. Use the same tracing harness while individually invoking `\_SB.SGWP`, `\_SB.CAGS`, etc. to map the additional offsets (`GPCL[*][5..8]`), looking specifically for writes into the PadCfgLock window.
  2. Once we confirm the correct W1S register/bit, graft that write into `SSDT-I2C4REPLAY.dsl` (or an auxiliary method) so the initramfs replay locks pads 62/63 before LPSS comes online.
  3. Keep `/tmp/sgwp_trace.raw` snapshots around each iteration; they are small (~75 KB) and give us regression history.

## I2C3 bring-up attempt (2025-10-20 @ 09:45 UTC)
- Authored `acpi/SSDT6.dsl` to mirror Lenovo’s I2C4 overlay: it targets GNVS byte **0x936C2179** (adjacent to IM04), stores `0x02` into both the local field and the global `\IM03`, and re-declares `_CRS`, `_STA`, `_ADR`, `_PS0`, `_PS3`, `_DSM`, and `_INI` so Linux has a complete device description even when firmware never promoted `I2C3`.
- The compiled AML (271 B) now loads through configfs (`/sys/kernel/config/acpi/table/I2C3ON{,2}`), producing dynamic tables `SSDT36` (legacy stub) and `SSDT37` (full overlay). Strings inspection confirms the new table exports the expected externs (`\I2CH`, `\IC03`, `\IM03`, `\PCIC`, `\PCID`, `\SOD3`).
- Test loop run after each load:
  1. `echo 0x090E0007 > /sys/kernel/acpi_mux/selector` → GNVS telemetry still shows a healthy mailbox cycle (`srt1=0x14`, `ser1=0x1200`, `abrt=0x0`) and FIFO snapshot `txfv` varies with the canary as expected.
  2. `echo 1 > /sys/bus/pci/rescan` → PCI inventory remains unchanged: only **00:15.0**, **00:15.1**, and **00:19.0** exist; there is still no device at **00:15.3** and BAR `0x4017_003000` reads back `0xFFFFFFFF`.
  3. `acpidbg` checks (`namespace \\_SB.PC00.I2C3`, `execute \\_SB.PC00.I2C3._INI`) return `AE_NOT_FOUND`, which matches earlier findings that the running kernel lacks `CONFIG_ACPI_DEBUGGER_USER` and—more importantly—that Linux never re-evaluates the DSDT node once boot has completed.
- Conclusion: the overlay now sets the correct GNVS selector and defines the missing methods, but because enumeration already finished before we injected it, the PCI core never sees `_ADR=0x00150003`. We therefore still cannot attach `i2c_designware` to the panel controller; all MMIO probes continue to exercise I²C4 (`TXFLR=2`, `ABRT=0`, `STATUS=0x2`).
- Next steps under review:
  1. **Initramfs integration** – include `SSDT6.aml` under `/kernel/firmware/acpi/` so `load-ssdt*.service` injects it before ACPI namespace finalisation.
  2. **ACPI scan hook** – temporarily patch `drivers/acpi/scan.c` to re-enumerate `\_SB.PC00.I2C3` after the overlay loads (forcing the PCI device into existence).
  3. **Firmware-side flip** – identify the pre-boot stage where we can toggle IM03 so the stock DSDT exposes I2C3 without OS assistance.
- Until one of those lands, the mux handshake remains validated but the panel still rides an invisible bus, preventing final `{0xAB,0x04}/{0xAB,0x00}` verification.
### 2025-10-27 @ 17:15 UTC — ISO now boots through BootChain shim
- Updated the live ISO’s EFI partition directly (mtools offset `4611264*512`) so `BOOTX64.EFI` is the edk2 BootChain shim; the original systemd-boot binary is preserved as `BOOTx64-systemd.efi` (fallback copy `BOOTx64-systemd-good.efi`).
- Dropped `PsfPatchDxe.efi` and a trimmed `bootchain.log` alongside the shim at `EFI/systemd/drivers/`. BootChain can now load the DXE helper before Linux ever reaches the initramfs.
- QEMU check on the rebuilt ISO prints the expected sequence (`BootChain: loading driver …`, `driver OK`, `launching primary loader …`) and then lands in the usual systemd-boot menu. Writes to `bootchain.log` still fail on read-only media, so use `dmpstore PsfBootChainStatus` to confirm execution when booting from the ISO.
- Next hardware reboot can happen straight from this image; no kernel rebuild required. After boot, confirm `efivar -p | grep -i PsfBootChainStatus` and capture `/sys/firmware/efi/efivars/PsfBootChainStatus-*` for the runbook.

### 2025-10-27 @ 20:30 UTC — Bare-metal flash results
- Flashed build 023 (`archlinux-opcode-sniffer--x86_64.iso`) onto `/dev/sda`; flash log `/var/log/baremetal/job-20251027-202218.log`.
- Post-reboot EFI vars: `PsfBootChainStatus` = stage 2, `EFI_SUCCESS`; `PsfPatchStatus` = stage 10, `EFI_SUCCESS` (no ReadyToBoot/ExitBootServices progress).
- `/boot/EFI/systemd/drivers/psfpatch.log` still prints “P2SB already visible / Invalid SBREG BAR”, and the deployed `PsfPatchDxe.efi` string table lacks the refreshed “SBREG default programmed” entries. Conclusion: the ISO on disk still carries the old DXE build; the QEMU-tested binary never made it into `build/out/…iso`.
- `bootchain.log` confirms the shim ran and started systemd-boot.
- Action: rebuild/patch the ISO ESP so the updated `PsfPatchDxe.efi` (with SBREG reprogram + replay stages) is what actually ships, then ref lash and re-check `PsfPatchStatus` before attempting Chipsec or PCI validation.

### 2025-11-29 @ 14:35 UTC — Kernel PPS helper wired through ACPI
- Built and deployed the new `drivers/opcode_pps/opcode_pps.ko` on b041 with `dry_run=0 poll_status=0 acpi_hook=1`. The module now maps IGD BAR0, exposes `/sys/kernel/debug/opcode_pps/{state,regs}`, **and** registers an ACPI address-space handler (space ID `0xA0`) under `\_SB.PC00.GFX0`, so AML can call into it without touching >4 GiB MMIO directly. dmesg shows `opcode_pps: ACPI OpRegion handler installed (space_id=0xa0)` followed by the usual BAR/log lines.
- Refreshed `acpi/SSDT-GFX0-PPS.dsl`: instead of a SystemMemory region, it now declares `OperationRegion (PPRG, 0xA0, Zero, 0x04)` and maps `PPOF/PPON/VPPS` to `Store (Zero|One, PPOW)`. Loading the AML via `/root/panel_power_overlay.sh` succeeds without `_PSx` collisions; `/proc/acpi/call` invocations of `\_SB.PC00.GFX0.PPOF` / `PPON` return `0xa0000002` / `0x80000008`, proving the OpRegion calls into the helper.
- `/root/panel_power_cycle.sh` auto-detects `/sys/kernel/debug/opcode_pps/state` and now drives the helper path. On b041 the script reports:
  ```
  -- Before power-off --  PP_STATUS=0x80000008  PP_CONTROL=0x00000067
  -- After power-off --   PP_STATUS=0x00000000  PP_CONTROL=0x00000066
  -- After power-on --    PP_STATUS=0x80000008  PP_CONTROL=0x00000067
  /sys/class/drm/card1-eDP-1/status stays "connected"
  ```
  Combined with the matching dmesg entries (`opcode_pps: OFF request complete …`, `ON request complete …`), this is our first fully ACPI-driven proof that the panel rail drops and recovers on demand.
- Next actions: (1) land a regression test in `userland_tests/test_panel_acpi.py` that exercises `VPPS._OFF/_ON` and asserts the PP registers change, (2) keep the helper in the kernel/initramfs build so it’s always available on boot, and (3) continue investigating `\EDMX`/`GGOV` spoofing now that we have a reliable fallback.

### Kernel helper regression tracking (2025-11-29 @ 16:20 UTC)
- Helper `opcode_pps` is live on b041 and exposes OpRegion-backed VPPS hooks; `/root/panel_power_cycle.sh` now calls it but we have not stress-tested repeated blank/restore loops yet.
- Action item: add a regression harness that toggles VPPS at least 10×, logging `intel_reg read 0x000c7200/0x000c7204`, `/sys/class/drm/card1-eDP-1/status`, and `dmesg` after each pass; declare failure if any iteration leaves PP_STATUS bit27 asserted incorrectly or the connector wedged.
- Once the harness is in place and passing, capture the output and append a follow-up entry here confirming the helper survives the loop without `i915_display_reset`.
- 2025-11-29 16:45 UTC: Added regression harness `scripts/panel_power_regression.sh`; run it with `./scripts/panel_power_regression.sh -n 10` on b041 to log PP registers, connector state, and dmesg across repeated helper-driven blank/restore cycles. Fill in the next entry once the script has been executed on hardware.
- 2025-11-29 17:12 UTC: First execution of `panel_power_regression.sh -n 10` on b041 exited on iteration 1 — OFF leg succeeded (`PP_STATUS` dipped to `0xA0000002` then `0x0`), but the ON poll hit the 20 s timeout even though `PP_STATUS` eventually returned to `0x80000008` a few seconds later. Need to inspect `opcode_pps` (or lengthen the helper delay) so the rail asserts within the regression window.
- 2025-11-29 17:18 UTC: Fixed the regression harness to watch `PP_STATUS` bit31 (`0x80000000`) instead of bit27; reran `/root/panel_power_regression.sh -n 3` on b041 and every cycle succeeded (`PP_STATUS` off→`0x08000001/0x0`, on→`0x80000008`; dmesg shows `opcode_pps: OFF/ON request complete`). Longer run (`-n 5`) also passed, though logs were truncated locally; no `i915_display_reset` needed.
- 2025-11-29 17:28 UTC: Ran `/root/panel_power_regression.sh -n 10` on b041; all 10 helper-driven blank/restore cycles succeeded (OFF leg drove `PP_STATUS` to `0x08000001` → `0x0`, ON leg restored `0x80000008`, `PP_CONTROL` toggled `0x67/0x66`, connector stayed `connected`, and `opcode_pps` logged “OFF/ON request complete” each time). No recovery actions were needed. Next step is to capture this script’s output automatically (e.g., tee to a log for CI) so we can fold it into `userland_tests` once we decide on an interface.
- 2025-11-29 17:32 UTC: `panel_power_regression.sh` now accepts `--log <path>` and tees stdout/stderr there (directories auto-created). Use `./scripts/panel_power_regression.sh -n 10 --log logs/panel_pps-$(date +%F-%H%M).log` so CI or future agents can archive the raw telemetry.
- 2025-11-29 17:46 UTC: Logged regression run via `/root/panel_power_regression.sh -n 10 --log /root/logs/panel_pps-2
### 2025-11-30 @ 04:05 UTC — Half-panel blanking theory (unverified)
- On b042 (X1 Fold) the only PP rail we currently control via `opcode_pps` is the global eDP domain (`PP_STATUS/PP_CONTROL @ 0x000c7200/0x000c7204`), so every `_PS3/_PS0` cycle blanks the entire panel. This matches the telemetry/regression logs collected so far.
- Hypothesis (needs confirmation): Lenovo's half-panel behavior probably relies on additional PP rails or tile-specific governors (e.g., a second `PP_STATUS/PP_CONTROL` pair, extra `DDxx` connector, or a GGOV/EDMX bit) that we haven't located yet. Until we map those, the helper can only toggle the whole panel.
- Next steps: scan `intel_reg` for other PP register blocks (0x000c7220, 0x000c7240, etc.), review the ACPI namespace for additional internal display devices, and extend `opcode_pps` once we prove a path to a single-half rail. Treat this split-panel theory as unproven until hardware evidence shows the secondary control.
- 2025-12-02 00:45 UTC: Added `panel_power_watch.sh` (installs at `/root/panel_power_watch.sh`) to sample PP/pipe/DDI registers plus backlight so we can prove when the display is flickering. Running it on b042 with 0.2 s cadence for 5 s shows `PP_STATUS` stays pegged at `0x80000008` (rail never drops) while `PP_CONTROL` and especially `DDI_BUF_CTL_EDP` thrash between `0x80000086` and `0x80000006` multiple times per second; backlight remains 600. Conclusion: the visible flicker is i915 re-training the eDP link / toggling the DDI buffer, not PPS, so future fixes should focus on why the helper or firmware keeps bouncing that register.
- 2025-12-02 01:12 UTC: Captured a longer `/root/panel_power_watch.sh 0.2 10` run on b042. Log shows `PP_STATUS` rock steady at `0x80000008` while `PP_CONTROL` bumps to `0x0000006f` once and `DDI_BUF_CTL_EDP` flips 14 times between `0x80000086` and `0x80000006`. Cross-checking `i915_reg.h` confirms bit 7 is `DDI_BUF_IS_IDLE`, so the register is just reflecting the DDI buffer hopping in/out of idle rather than the rail turning off. Immediately afterwards `/sys/kernel/debug/dri/1/eDP-1/i915_psr_status` oscillated between `CAPTURE` and `SLEEP`, i.e. PSR2 keeps entering/leaving main-link idle. Working theory: PSR (or panel replay) is dumping the link each time we tug PP_CONTROL via the helper, which manifests as the user-visible flicker. Next action is to repeat after forcing PSR off (`i915_edp_psr_debug=0x1` or booting with `i915.enable_psr=0`) to see if the DDI idle bit stabilises.

### Windows half-blank marked capture (portable, 2025-12-30)
- **Access:** Windows reachable from the Linux host via SSH proxy: `ssh -p 4400 Administrator@localhost` (host `portable`). PowerShell is the default shell; use `;` separators, not `&&`.
- **Capture:** Ran the on-device marked capture script `C:\trace\halfblank\capture_halfblank_marked.ps1`, producing:
  - `C:\trace\halfblank_20251230-131329.etl` (≈ 218 MB)
  - `C:\trace\exports\halfblank_20251230-131329_focus\{dxg_focus.txt,acpi_focus.txt,vendor_focus.txt,summary.txt}`
  - Pulled into the repo as `traces/windows_etl_exports/halfblank_20251230-131329_focus/` via `./scripts/windows_fetch_focus.sh halfblank_20251230-131329`.
- **Markers / window:**
  - `BEFORE_HALFBLANK` appears in-ETL at timestamp **3,964,214**
  - `AFTER_HALFBLANK` appears in-ETL at timestamp **9,988,456**
  - Window length ≈ **6,024,242** (same timestamp units as `xperf -a dumper` output).
- **DxgKrnl result:** Inside the marker window there are **no** `Microsoft-Windows-DxgKrnl/DisplayConfigPlaneChange` events, and MPO flips keep full-screen rectangles (`DstRect 0..2024 x 0..2560`). This argues against “half blank via plane cropping / plane rect update”.
- **Bus-level result:** Inside the marker window, `Intel-iaLPSS2-I2C` shows traffic to **slave `0x0A`**, including a burst attributed to `LenovoModeSwitcher.exe`. This is the first concrete telemetry suggesting the half-blank path is I²C-driven.
  - A marker-bounded raw dump for `Intel-iaLPSS2-I2C` with `-add_rawdata` is stored as `traces/windows_etl_exports/halfblank_20251230-131329_focus/i2c_raw_window.txt`.
- **Topology note (2026-01):** On this unit, ACPI/PnP strongly suggest slave `0x0A` is on `\_SB.PC00.I2C1.TPL1` (Wacom `ACPI\\WACF2200`), i.e. the I²C controller at `PCI(1501)` / `00:15.1`. This implies the fastest Linux replay path may be to target the already-present I2C1 controller, not to chase `00:15.3` first.
- **Provider coverage update:** Expanded `VendorProviders.wprp` and `extract_halfblank_focus.ps1` to include Microsoft bus class providers:
  - `Microsoft-Windows-SPB-ClassExtension` (`{72CD9FF7-4AF8-4B89-AEDE-5F26FDA13567}`)
  - `Microsoft-Windows-SPB-HIDI2C` (`{991F8FE6-249D-44D6-B93D-5A3060C1DEDB}`)
  - `Microsoft-Windows-GPIO-ClassExtension` (`{55AB77F6-FA04-43EF-AF45-688FBF500482}`)
  These are intended to yield richer SPB/I²C context for the next capture. Verified `extract_halfblank_focus.ps1` still runs after the edit, but vendor extraction can take >10 minutes once the provider set expands (xperf remains active).

### Windows half-blank marked capture (portable, follow-up, 2025-12-30)
- **Capture:** `halfblank_20251230-232848`
  - Windows ETL: `C:\trace\halfblank_20251230-232848.etl` (≈ 327 MB)
  - Focus exports: `C:\trace\exports\halfblank_20251230-232848_focus\{dxg_focus.txt,acpi_focus.txt,vendor_focus.txt,summary.txt}`
  - Pulled into the repo as `traces/windows_etl_exports/halfblank_20251230-232848_focus/`.
- **Marks file (wall clock):** `traces/windows_etl_exports/halfblank_20251230-232848_focus/halfblank_20251230-232848.marks.txt` shows a ≈ 3.93 s window between BEFORE/AFTER.
- **New information (critical):** With `Microsoft-Windows-SPB-ClassExtension` enabled, the vendor dump includes `IoSpbPayloadTdBuffer` rows containing the actual payload bytes.
  - We can now extract the I²C-sideband “half blank” candidate traffic as concrete byte strings.
- **Observed signature:** `LenovoModeSwitcher.exe` drives a Serial-IO I²C transaction to slave `0x0A` with length `1034`, and the corresponding SPB write payload begins:
  - `04 00 39 03 05 00 04 04 09 20 …` (remaining bytes are zero padding in the first occurrence).
  - A later occurrence of the same `1034`-byte write includes additional non-zero words at offsets 12–17 (`… 9c 18 2c 28 33 1a …`). Treat this as a post-state / confirm variant (the operator reports they did **not** perform a restore action during capture).
- **Artifacts:** extracted payloads + summary were generated locally:
  - `traces/windows_etl_exports/halfblank_20251230-232848_focus/spb_lenovo_summary.txt`
  - `traces/windows_etl_exports/halfblank_20251230-232848_focus/spb_bins/`
  - `scripts/windows_spb_extract_payloads.py`

### Linux plan — replay the Windows `0x0A` transaction set (2026-01; pending)

Goal: reproduce halfblank/unblank from Linux by replaying the Windows SPB/I²C writes to slave `0x0A` (instead of focusing on `00:15.3` first).

Evidence to base this on:
- Windows ETW shows `Intel-iaLPSS2-I2C` traffic to `SlaveAddress=0x0A` during halfblank/unblank; SPB payload bytes are captured in `traces/windows_etl_exports/*_focus/spb_bins/`.
- On this unit, ACPI/PnP strongly suggest slave `0x0A` is on `\_SB.PC00.I2C1.TPL1` (Wacom `ACPI\\WACF2200`), i.e. controller `PCI(1501)` / Linux `00:15.1` (see “Topology note (2026-01)” above).

Concrete Linux test checklist:
1. **Identify the Linux I²C adapter for `00:15.1` (I2C1)**:
   - `ls -l /sys/class/i2c-adapter/i2c-*/device | rg '0000:00:15\\.1'`
2. **Check whether slave `0x0A` is present** on that adapter:
   - `i2cdetect -y <bus>` → expect `0a` or `UU` at `0x0A` (claimed by a kernel driver).
3. **Replay the exact `len=1034` payloads captured on Windows**:
   - UNBLANK payload: `traces/windows_etl_exports/unblank_*/spb_bins/*LenovoModeSwitcher*len1034.bin`
   - HALFBLANK payload: `traces/windows_etl_exports/halfblank_*/spb_bins/*LenovoModeSwitcher*len1034.bin`
   - Preferred implementation is a small Linux helper that does a single `I2C_RDWR` write of the full 1034-byte buffer (avoid manual `i2ctransfer` because the argv would be huge).
4. Optional / if required by the device: replay the surrounding “query” pattern:
   - `len=6` write payload `04 00 34 02 05 00`, followed by a `len=1029` read (see `.../spb_bins/*len6.bin` + `*len1029.bin`).
5. **Observe and log**:
   - Visual outcome (half-panel blank/unblank).
   - `dmesg -w` during the transaction.
   - `intel_reg` sampling (at least the PP regs + DDI/pipe state) to confirm we didn’t just dim/backlight.
6. If raw I²C replay fails:
   - Determine whether `0x0A` is bound to `i2c-hid`/Wacom on Linux and whether the correct interface is `hidraw` (feature report) rather than raw I²C.
   - Only if `0x0A` is not reachable on any existing adapter do we return to the `00:15.3` enumeration workstream.

### 2026-01-02 @ 23:13 UTC — Linux replay: `0x0A` query works on I2C1 (`00:15.1`); halfblank payload changes device state
- **Environment:** booted live ISO build `b043` (`hostname=archlinux-opcode-sniffer-b043`) and connected over SSH proxy (`root@localhost:2222`), kernel `6.16.10-custom`.
- **On-target I²C adapter mapping (via `/sys/class/i2c-dev/i2c-*`):**
  - `i2c-0` → `0000:00:15.0`
  - `i2c-1` → `0000:00:15.1`
  - `i2c-2` → `0000:00:19.0`
- **Phase 0 “query” probe (Windows-derived):** `i2ctransfer -f -y -b <bus> w6@0x0a 04 00 34 02 05 00 r1029`
  - `i2c-1`: **success**, read `1029` bytes; prefix matches the Windows-like signature:  
    `12 00 04 2c 28 d0 32 0b 0a b4 0c 0a 00 02 00 45 ...`
  - `i2c-0`: fails with `Remote I/O error`
  - `i2c-2`: fails with `Connection timed out`
- **Userspace helper added:** `tools/i2c_write_file.py` writes a binary payload to `/dev/i2c-N` using `I2C_SLAVE_FORCE` and a single `write()` (avoids huge `i2ctransfer` argv for `len=1034`).
- **Payload staging on target:**
  - `/root/i2c_payloads/unblank_len1034.bin` (offset `0x0c..0x11` = `00 00 00 00 00 00`)
  - `/root/i2c_payloads/halfblank_len1034.bin` (offset `0x0c..0x11` = `9c 18 2c 28 33 1a`)
- **Replay run (artifacts in `/root/i2c_payloads/run-20260102-231316/`):**
  1. `query_pre` (baseline)
  2. write `unblank_len1034.bin` → `query_post_unblank`: **no change**
  3. write `halfblank_len1034.bin` → `query_post_halfblank`: **changed**  
     - diffs vs baseline: `0x0010: 00 → 33`, `0x0011: 00 → 1a`
  4. write `unblank_len1034.bin` → `query_post_restore`: **returned to baseline**
  5. `dmesg` tail during the run shows no `i2c_designware` controller timeout bursts.
- **Note:** The operator was not watching the panel during the run, so **we still do not know whether any panel pixels were actually blanked**. DRM mode/fbdev stayed at `2024x2560` (`card1-eDP-1` mode `2024x2560`, `fb0 virtual_size 2024,2560`). This suggests the “halfblank” effect (if present) is likely internal to the panel and not reflected as a KMS mode change. The query state change (`33 1a`) is still a strong indicator that Linux can reach and program the same `0x0A` device path Windows used.

### 2026-01-03 @ 09:45 UTC — PSR-off power probe: `0x0A` state toggles reliably, but pixel shutoff remains unproven
- **Goal:** gather non-visual evidence that the “halfblank” command actually turns off pixels on the foldable panel (remote operator; no one watching the screen).
- **Probe helper:** `tools/halfblank_power_probe.py` (runs on target) fills `/dev/fb0` with simple patterns, toggles `unblank/halfblank/unblank` via the 1034-byte payloads, snapshots i915/opcode_pps debugfs, and samples RAPL energy (focus: `intel-rapl:1` / `psys`).
- **PSR control:** forcing PSR off works via debugfs:
  - Disable: `echo 1 > /sys/kernel/debug/dri/0000:00:02.0/i915_edp_psr_debug`
  - Restore: `echo 0 > /sys/kernel/debug/dri/0000:00:02.0/i915_edp_psr_debug`
  The probe used `--disable-psr` to reduce drift from PSR2 entry/exit.
- **State-first run (recommended ordering):**
  - Command: `/usr/local/bin/halfblank_power_probe.py --disable-psr --mode state-first --loops 2 --pattern white --pattern black --pattern top-white-bottom-black --pattern top-black-bottom-white --duration 60 --interval 1 --settle 5 --pattern-settle 5 --brightness 600`
  - Output: `/root/i2c_payloads/probe-20260103-091742/summary.json` + per-phase artifacts.
- **I²C-side success (strong):** in every state window the query field `0x10..0x11` toggled `00 00 → 33 1a` in the `halfblank` state and returned to `00 00` after restore. The query blob diffs remained limited to those two bytes (no other stable offsets flipped), so Linux is consistently programming a device state bit/field on slave `0x0A`.
- **Power-side evidence (weak / mixed):**
  - White/black `psys_W` deltas remained large and roughly unchanged across `unblank_pre` vs `halfblank`, which is *not* what we’d expect if half of an OLED panel’s pixels were being forced off (we’d expect the white–black gap to shrink materially in halfblank).
  - The “half-and-half” patterns (`top-white-bottom-black` vs `top-black-bottom-white`) did not show a consistent, one-sided collapse that would identify one physical half being blanked; results drifted between loops.
- **Conclusion (today):** we have high confidence that the **`0x0A` mode field is being toggled from Linux**, but the RAPL/pattern tests (with PSR disabled) do **not** yet provide strong supporting evidence that pixels are actually shut off. Possibilities: (a) the `0x0A` write primarily affects the digitizer/mode-switch subsystem, (b) the display blanking requires additional actions not captured here, or (c) the behavior depends on a fold/hinge condition we are not currently able to observe from Linux (hinge IIO readings stayed at 0 during spot checks).

### 2026-01-03 @ 16:20 UTC — If “halfblank” isn’t actually blanking pixels: how to determine what Windows is doing
- **Working suspicion:** the `0x0A` traffic may be **digitizer / mode-switch** configuration (Wacom HID-over-I²C), not a panel pixel-power feature.
  - The “halfblank” payload’s non-zero field bytes `9c 18 2c 28 33 1a` can be read as three little-endian 16-bit values: `0x189c=6300`, `0x282c=10284`, `0x1a33=6707` — these look more like **coordinate ranges / mode parameters** than display timings.
  - ETW also shows small 12-byte writes from `WTabletServiceISD.exe` (`04 00 3b 03 05 00 06 00 0b 01 00 00`), reinforcing that this channel is at least tablet-adjacent.

#### Phase 1: Prove whether `0x0A` changes touch/pen geometry (no physical interaction needed)
- **Linux: identify what `1-000a` is and which driver owns it:**
  - `cat /sys/bus/i2c/devices/1-000a/name`
  - `readlink -f /sys/bus/i2c/devices/1-000a/driver`
  - `dmesg | rg -i 'wacom|i2c-hid|hid|wacf|000a|i2c.*0x0a'`
- **Linux: snapshot evdev ABS ranges before/after toggling:**
  - If `ABS_X/ABS_Y` (or `ABS_MT_POSITION_X/Y`) min/max change across `unblank` vs `halfblank`, that’s strong evidence the command is digitizer/mode geometry, not pixels.
  - Practical: use `evtest /dev/input/eventX` (or a tiny `ioctl(EVIOCGABS)` helper) to log the axis ranges without touching the screen.

#### Phase 2: Determine whether “blanking” is just compositor black bars (software)
- **Windows: take a screenshot before/after the fold/halfblank action and diff it.**
  - If the screenshot itself contains a black region, then the “blanking” is happening in the **graphics stack / compositor** (or via a GPU plane/clip), not via panel-internal pixel shutdown.
  - If so, Linux can likely reproduce the behavior with a KMS overlay/plane that paints black over the folded region (and optionally remap input), even if no panel-specific half-off primitive exists.

#### Phase 3: If screenshots don’t show it but humans see it: it’s likely panel-internal / hardware-side
- That points away from “software black bars” and towards something like:
  - DP AUX / DPCD or vendor panel command sequences,
  - ACPI/WMI methods (or SMI) that program a hidden panel controller,
  - or a multi-tile panel path that is invisible to KMS but real to the panel.
- Next steps here are Windows-first: capture an ETW trace that is explicitly graphics/display oriented around the marker window (not only SPB/I²C), and look for display-mode/plane/clip transitions or driver calls that correlate tightly with the physical blanking.

#### Reality check / fallback plan
- If no robust evidence of panel-internal half-off emerges, treat “halfblank” as a **UX requirement** (hide the folded area) rather than a literal power-rail feature:
  - implement black overlay on the folded region (OLED black ≈ minimal pixel power),
  - and separately implement input remap/disable for the folded region based on hinge state or the digitizer geometry signals we can observe.

### 2026-01-03 @ 17:26 UTC — `0x0A` toggling changes Wacom HID feature reports (strong evidence this is digitizer/mode geometry)
- **Context:** We can write the Windows-derived 1034-byte payloads to slave `0x0A` on Linux (bus `i2c-1` / `00:15.1`) and observe the query state flip `00 00 ↔ 33 1a`. We need to understand whether this is **panel pixels** or **digitizer/mode-switch**.
- **Device identity (Linux):**
  - ACPI enumerates `i2c-WACF2200:00` under `00:15.1` and binds it to `i2c_hid_acpi` (`/sys/bus/i2c/devices/i2c-WACF2200:00`).
  - The corresponding HID raw node is `/dev/hidraw0` with `DRIVER=wacom` and `HID_NAME=WACF2200:00 056A:52BA` (Wacom vendor ID `0x056A`).
- **New probe:** `tools/hid_feature_probe.py` reads hidraw report descriptors, polls HID **feature reports**, and captures the `0x0A` query field in three states: `unblank_pre`, `halfblank`, `unblank_post`.
  - Example run output dir: `/root/i2c_payloads/hidprobe-20260103-172321/summary.json`
- **Results (high signal):**
  - Feature report `0x03` (256B) and `0x04` (256B) each changed **exactly two bytes** when toggling halfblank:
    - offset `0x0e..0x0f`: `00 00 → 33 1a` in `halfblank`, then back to `00 00` on restore.
    - This matches the `0x0A` query field transition and gives us a second, independent “mode applied” signal at the HID layer.
  - Feature report `0x04` begins with `2c 28 d0 32 ...`, and the values `0x282c=10284` and `0x32d0=13008` match the Wacom Finger `ABS_X/ABS_Y` maxes seen via evdev. This strongly suggests these reports encode **digitizer geometry**, not display pixels.
  - Feature reports `0x09`, `0x0b`, and `0x12` also changed substantially between `unblank_pre` and `halfblank` (dozens to hundreds of byte deltas), consistent with calibration/transform or active-area configuration being updated when the mode changes.
- **Len12 WTabletService write is likely orthogonal:** the captured 12-byte payload (`04 00 3b 03 05 00 06 00 0b 01 00 00`) does **not** change the `0x0A` query field nor the `0x03/0x04` feature-report field (spot-tested by sending len12 in both states).
- **Conclusion:** The `0x0A` halfblank/unblank toggling is now proven to propagate into the Wacom HID stack and appears to change **digitizer/mode geometry**. This makes it less likely that `0x0A` is a direct “panel pixel blank” primitive; Windows may instead blank the folded region in the compositor/GPU based on this mode signal.
  - **Important:** This is still **not** proof that the panel is physically blanking pixels/powering down half the OLED; visual confirmation (human observation or the Windows screenshot test above) is still pending.

### 2026-01-04 — Windows next steps now that we can reboot + rerun ETL analysis
- **We can do either of these immediately:**
  - **Re-run analysis on an existing (“mega”) ETL** already captured on the device.
  - **Reboot Windows and take a new marked capture** (then export focused logs).
- **Current state of evidence (from the existing focused exports already in-repo):**
  - We see **in-window SPB/I²C traffic to slave `0x0A`** tied to `LenovoModeSwitcher.exe` (and we have extracted the payload bytes). This aligns with the Linux-side discovery that `0x0A` is the Wacom HID-over-I²C device and that the `halfblank` write changes HID feature report state.
  - `DxgKrnl` analysis so far argues against “half blank via MPO plane cropping” (no in-window `DisplayConfigPlaneChange`; MPO flips remain full-screen rectangles). This does **not** rule out a compositor-level black overlay (content can change without plane rectangles changing).
  - The `VendorProviders` focus export is **not currently giving us decoded DP/AUX/DPCD-style evidence**; most lines are `UnknownEvent`/`InvalidEvent`, so it’s weak for proving a panel-link/AUX sequence from our existing text exports alone.
  - **We still do not have proof of actual pixel blanking** (nobody watched the panel during the Linux tests).

#### Decision tree: compositor/GPU vs panel-internal
1. **Fast discriminator (recommended): Windows screenshot before/after**
   - If the “blanked” region appears in the screenshot, the effect is in **software** (DWM/compositor or a GPU plane drawing black), not panel-internal pixel shutoff.
   - If the screenshot is “normal” while humans see the fold-region dark, the effect is likely **panel-internal** (DP/AUX / vendor panel commands / firmware sideband).
   - Automation now exists:
     - Standalone: `TO_TEST_ON_WINDOWS/halfblank/capture_halfblank_screenshots.ps1` (writes `before.png`/`after.png` + sampled luma diff stats to `..._focus/`).
     - Integrated: `TO_TEST_ON_WINDOWS/halfblank/capture_halfblank_marked.ps1 -CaptureScreenshots -CaptureDisplayState` (adds screenshots + display state JSON alongside the ETL focus export).

2. **If compositor/GPU is suspected**
   - We already have the capture tooling to look for display-pipeline events around the action:
     - Capture: `TO_TEST_ON_WINDOWS/halfblank/capture_halfblank_marked.ps1` (records `BlankDetect` + `GPU` + optional `VendorProviders`).
     - Focus export: `TO_TEST_ON_WINDOWS/halfblank/extract_halfblank_focus.ps1` (extracts `DxgKrnl` patterns and writes `dxg_focus.txt`).
   - Next action: on Windows, rerun focus extraction (or take a fresh marked capture) and inspect `DxgKrnl` events in the marker window for any state changes other than plane rectangles (e.g., `DdiSetVidPn*`, present flags, MPO enable/disable toggles, color space/HDR metadata shifts). The existing “no cropping” finding is good, but it doesn’t exclude “draw black content”.

3. **If DP/AUX / panel-internal is suspected**
   - The current `VendorProviders` text export isn’t sufficient evidence on its own (undecoded). Plan on either:
     - **Re-exporting the old ETL with richer options** (e.g., ensure `xperf` dumper includes raw payloads via `-add_rawdata` for the Intel display providers), or
     - **Taking a new marked capture** with a provider set known to expose display-link/AUX activity (if any exists on this Windows image).
   - If we can’t obtain reliable AUX/DPCD telemetry from ETW, fall back to the screenshot classifier plus Linux-side instrumentation (i915 tracepoints/dynamic debug for AUX transfers) once we can reproduce the same user action under Linux.

#### Concrete “do this now” commands (Windows + repo host)
- **Stage scripts/profiles to `C:\\trace` (recommended):**
  - On the repo host:
    - `./scripts/windows_push_trace_scripts.sh`
- **Re-run focus extraction on an existing ETL (no reboot needed):**
  - On the Windows box (Admin PowerShell):
    - `powershell -NoProfile -ExecutionPolicy Bypass -File C:\trace\halfblank\extract_halfblank_focus.ps1 -EtlPath C:\trace\<existing>.etl -OutDir C:\trace\exports\<existing>_focus`
  - Then on the repo host:
    - `./scripts/windows_fetch_focus.sh <existing>`
- **Capture screenshot evidence only (no ETL):**
  - On the Windows box (interactive PowerShell):
    - `powershell -NoProfile -ExecutionPolicy Bypass -File C:\trace\halfblank\capture_halfblank_screenshots.ps1 -Scenario HalfBlank`
  - Then on the repo host:
    - `./scripts/windows_fetch_focus.sh <base_name_printed_by_script>`
- **Dump Wacom HID feature state before/after (digitizer mode signal):**
  - On the Windows box (interactive PowerShell):
    - `powershell -NoProfile -ExecutionPolicy Bypass -File C:\trace\halfblank\wacom_hid_feature_dump.ps1 -OutPath C:\trace\exports\<base>_focus\wacom_before.json`
    - reproduce HALF-BLANK / UNBLANK
    - `powershell -NoProfile -ExecutionPolicy Bypass -File C:\trace\halfblank\wacom_hid_feature_dump.ps1 -OutPath C:\trace\exports\<base>_focus\wacom_after.json`
- **Take a new marked capture (after reboot if desired):**
  - On the Windows box (Admin PowerShell):
    - `powershell -NoProfile -ExecutionPolicy Bypass -File C:\trace\halfblank\capture_halfblank_marked.ps1`
    - For restore: `powershell -NoProfile -ExecutionPolicy Bypass -File C:\trace\halfblank\capture_halfblank_marked.ps1 -Scenario Unblank -PostSeconds 0`
  - Then on the repo host:
    - `./scripts/windows_fetch_focus.sh <base_name_printed_by_script>`

### 2026-01-05 — Linux visual check: no half-panel blank observed (only full-screen blank/dim at exit)
- **Goal:** confirm (with a human watching the panel) whether the `0x0A` `halfblank_len1034.bin` payload actually blanks pixels on *one physical half* of the foldable panel.
- **Run (on the live ISO):**
  - `sudo /usr/local/bin/halfblank_power_probe.py --disable-psr --mode pattern-first --pattern top-white-bottom-black --pattern top-black-bottom-white --duration 6 --interval 1 --settle 2 --pattern-settle 2 --brightness 600 --out-dir "/root/i2c_payloads/visual-20260105"`
- **Observed:** during the `pre` vs `post_halfblank` vs `post_unblank` windows, the panel never showed a stable “one-half is off” state; the patterns continued to render normally across the full screen.
- **Manual check (also observed):** directly writing the payloads also did **not** visibly blank any part of the panel:
  - `sudo /usr/local/bin/i2c_write_file.py --bus 1 --addr 0x0a --force --file /root/i2c_payloads/halfblank_len1034.bin`
  - `sudo /usr/local/bin/i2c_write_file.py --bus 1 --addr 0x0a --force --file /root/i2c_payloads/unblank_len1034.bin`
- **Oddity:** the screen appeared to go fully dark right at the very end of the run (after all phases completed). This might be:
  - brightness restoration (the probe restores original backlight on exit; check `orig_brightness.txt` + current `/sys/class/backlight/*/brightness`), or
  - DPMS/console blanking, or
  - an I²C restore issue that left the device in an unintended state (check `<out_dir>/summary.json` + `dmesg`).
- **Conclusion update:** this result further supports the working hypothesis that the `0x0A` path is a **digitizer/mode-geometry signal**, not a direct “panel pixels off” primitive.
- **Next (Linux):** re-run with left/right patterns to rule out orientation (`left-white-right-black`, `left-black-right-white` are now supported by the probe) and/or switch to the Windows screenshot discriminator to decide compositor vs panel-internal.
