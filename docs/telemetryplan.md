# Windows Telemetry Mining Plan (Panel PPS / Half-Panel Blanking)

## Goal
Correlate Lenovo's Windows-only panel blanking behavior with concrete ACPI/SMI/MMIO calls so we can replicate a half-panel blackout from Linux. All relevant telemetry now lives under `/mnt/finished/windows-trace` (ETLs, WPR templates, helper scripts). This plan describes how we will mine those artifacts.

## Current Status (2025-12)
- We have a working **marked capture** workflow on-device (Windows) via `C:\trace\halfblank\capture_halfblank_marked.ps1`, and a Linux fetch helper `./scripts/windows_fetch_focus.sh <base_name>` that pulls the focused exports into `traces/windows_etl_exports/<base_name>_focus/`.
- Key finding from `halfblank_20251230-131329` (see `traces/windows_etl_exports/halfblank_20251230-131329_focus/`):
  - During the marker window (`BEFORE_HALFBLANK` → `AFTER_HALFBLANK`), **DxgKrnl plane rectangles do not change** (no in-window `DisplayConfigPlaneChange`), so this is not “half blank via MPO plane cropping”.
  - We do see **Intel Serial IO I²C activity** in-window: `Intel-iaLPSS2-I2C` traffic to slave `0x0A`, including a burst initiated by `LenovoModeSwitcher.exe`. This strongly suggests the half-blank path involves **I²C commands** rather than a pure DxgKrnl display-mode/plane change.
- Follow-up capture `halfblank_20251230-232848` (see `traces/windows_etl_exports/halfblank_20251230-232848_focus/`) enabled `Microsoft-Windows-SPB-ClassExtension` and yielded **payload bytes**:
  - `LenovoModeSwitcher.exe` performs an SPB transfer that maps to an `Intel-iaLPSS2-I2C` write to slave `0x0A` with length `1034`, with a “mostly-zero” payload starting `04 00 39 03 05 00 04 04 09 20 …` (see `.../spb_lenovo_summary.txt` + `.../spb_bins/*len1034.bin`).
- Confirmatory capture `halfblank_20251231-024301` (run with **no post-window**, see `traces/windows_etl_exports/halfblank_20251231-024301_focus/`) shows the same Lenovo sequence still contains **two** distinct `len=1034` writes:
  - “All-zero tail” variant: `04 00 39 03 05 00 04 04 09 20` + zero-padding out to 1034 bytes.
  - “6-byte payload” variant: same header, but with 6 additional non-zero bytes at offsets `0x0c..0x11`: `9c 18 2c 28 33 1a` (see `.../spb_bins/*len1034.bin`).
  - This means the second `len=1034` write is **not** just an artifact of our previous post-window delay; it occurs during the marked capture itself and must be treated as part of the half-blank transaction set (or an immediate follow-up poll/commit).
- Restore capture `unblank_20251231-050055` (run with **no post-window**, see `traces/windows_etl_exports/unblank_20251231-050055_focus/`) shows `LenovoModeSwitcher.exe` issuing only the “all-zero tail” `len=1034` write (plus the usual query `len=6` + `len=1029` read). The `len=1034` payload is **byte-identical** to the first `len=1034` write from `halfblank_20251231-024301`; the only difference vs the half-blank “6-byte payload” variant is bytes at offsets `0x0c..0x11` (`00 00 00 00 00 00` vs `9c 18 2c 28 33 1a`).
- Newer marked captures on 2026-01-01 (`halfblank_20260101-045907`, `unblank_20260101-051802`) reproduce the same delta at offsets `0x0c..0x11` (halfblank has `9c 18 2c 28 33 1a`, unblank has zeros). See `traces/windows_etl_exports/*_focus/spb_lenovo_summary.txt`.
- Important topology clue (2026-01): on this unit, ACPI/PnP strongly suggest slave `0x0A` is on **I2C1**:
  - Windows shows `Intel(R) Serial IO I2C Host Controller - 51E9` at `PCI(1501)` / `ACPI(I2C1)` (`00:15.1` on Linux).
  - The Wacom device `ACPI\\WACF2200\\...` lives at `ACPI(I2C1)#ACPI(TPL1)`, and the DSDT sets `TPL1`’s I²C address to `0x0A`.
  - So the fastest Linux path is likely: get working access to the existing I2C1 controller and replay the `len=1034` write to slave `0x0A`, rather than chasing `00:15.3` first.
- Screenshot + HID confirmation (2026-01-06):
  - Screenshot classifier captures (`halfblank_screens_20260106-222645`, `unblank_screens_20260106-222717`) show the virtual screen size toggles between **`2024x2560`** and **`2024x1240`** (at 200% scaling), meaning HALFBLANK/UNBLANK includes a **desktop/display config change** (the “blanked” area is outside the desktop). This does **not** prove anything about panel rail state by itself.
  - Wacom HID feature dumps (`wacom_halfblank_20260106-231916`, `wacom_unblank_20260106-231936`) show `WACF2200&COL02` `ReportId=0x03` bytes **[10..15]** toggle between `00 00 00 00 00 00` and `9c 18 2c 28 33 1a`, matching the SPB `len=1034` write delta.
- **Rail telemetry (2026-01-07):** we can read the iGPU MMIO `PP_STATUS/PP_CONTROL` pair from Windows via CHIPSEC by:
  - reading IGD BAR0 (`00:02.0` @ `0x10/0x14`) and adding offsets `0xC7200/0xC7204`, and
  - capturing those values before/after HALFBLANK/UNBLANK via `C:\trace\halfblank\capture_halfblank_marked.ps1 -CapturePpRegs` (writes `before_pp_regs.json`/`after_pp_regs.json` into the focus dir).
  - **Result so far:** on `portable`, the marked captures `halfblank_20260107-074913` + `unblank_20260107-084645` show `PP_STATUS/PP_CONTROL` remain `0x80000008 / 0x00000067` before/after the action (see `docs/ACPI_STATUS.md`), so the standard iGPU eDP PPS pair does not transition during HALFBLANK/UNBLANK.
  - **Additional DxgKrnl evidence (same captures):** `halfblank_20260107-074913` shows `FlipMultiPlaneOverlay` + `DisplayConfigPlaneChange` with `PlaneIndex=2` and `ClipRect.bottom=1240` (half-height) near the I²C write. This is consistent with a GPU composition/pipeline clip as part of the HALFBLANK implementation (still not “rail proof”).

## Inputs
1. `/mnt/finished/windows-trace/blank*.etl`, `run*_*.txt`, `events.txt`
2. `/mnt/finished/windows-trace/wpr_boot*.etl` (boot/resume baselines)
3. `/mnt/windows/oem_trace/*` GNVS snapshots (already mirrored to `/tmp/oem_trace`)
4. Panel probe JSON dumps (`/tmp/panel_probe/panel_probe/dumps/*.json`)
5. New on-device marked captures + focused exports under `traces/windows_etl_exports/*_focus/`.

## Toolchain
- Windows Performance Analyzer (WPA) or `wpaexporter` (run inside a Windows VM or via wine) for ETLs.
- `tracerpt` (Windows) for quick event CSV exports.
- `xperf -a dumper` (Windows) for provider-dumper exports (optionally bounded via `-range T1 T2` and richer via `-add_rawdata`).
- Existing scripts in `C:\trace\halfblank\` (`capture_halfblank_marked.ps1`, `extract_halfblank_focus.ps1`, `BlankDetect.wprp`, `VendorProviders.wprp`) to reproduce the views.
- Python helpers (`diff_mem.py`, `panel_probe` parsers) already in repo.

## Work Breakdown
0. **Capture with markers (preferred)**
   - Run `C:\trace\halfblank\capture_halfblank_marked.ps1` on Windows, reproduce the half-blank between the markers, and let it write `C:\trace\exports\<base>_focus\{dxg,acpi,vendor}_focus.txt`.
   - Fetch to Linux with `./scripts/windows_fetch_focus.sh <base>`.

1. **Index ETLs**
   - On a Windows analysis VM, copy `/mnt/finished/windows-trace` (or SSH-mount) and run `wpaexporter -i blank_run1.etl -profile GPU.wprp -o blank_run1.csv` to list relevant tables (ACPI, Device Manager, PNP, power notifications).
   - Document which providers appear (ACPI, Kernel-PnP, Power-Thermal, ETW trace names) and which timestamps align with magnet attach/detach.

2. **Extract ACPI/SMI activity**
   - Use WPA graphs (Generic Events filtered by `ACPI` provider) to find `_DSM`, `_PSx`, `SMI` or custom GUID events near the blanking timestamp.
   - Export those rows to CSV. Note the GUID/function indices and arguments (look for `Lenovo` GUID `3e5b…` etc.).
   - Correlate event timestamps with GNVS diffs from `20251019_161907` to ensure we capture the same command (CMD/ERR/PAR0 timeline).

3. **Correlate connector state**
   - From `run1.txt`, `run2.txt`, `run1_pnp.txt`, identify which PnP device IDs change state when the keyboard/magnet moves. Look for `DISPLAYoldtile` or `ACPI\VIDDDxx` entries.
   - Cross-reference with `blank_run*.etl` GPU/Display pipeline events (DxgKrnl Present/Flip, `PowerTransition` events) to spot when only one tile goes dark.

4. **Panel probe JSON analysis**
   - Parse `/tmp/panel_probe/panel_probe/dumps/*.json` to extract time-series of `CMD`, `ERR`, I²C registers, and any `EDMX`-like fields.
   - Confirm whether any run shows `CMD=0x16/0x18` or other values besides the global 0x0A/0x14 handshake.

5. **GNVS diff automation**
   - Use `diff_mem.py` (already in repo) to diff every `pre/post` pair in `/tmp/oem_trace` and log the offsets that change. Automate via a Python script so we know if any run besides `161907` exhibits additional fields toggling.

6. **Synthesize candidate control path**
   - Based on ETL + GNVS results, produce a shortlist of possible half-panel controls: specific `_DSM` function, a GGOV bit, or another SMI command.
   - Feed that back into Linux via the existing kernel helper or an AML overlay.

## Deliverables
- `analysis/windows_blank_<date>.md` summarizing ETL findings, including tables of event timestamps, GUIDs, and associated GNVS fields.
- CSV/JSON exports of the key ETL selections (checked into `traces/panel_logs/` or similar).
- Updated `docs/ACPI_STATUS.md` with confirmed half-panel control path (once discovered).
- Automation script (`scripts/windows_trace_extract.py`) to batch-export ETL sections if feasible.

## Next Immediate Tasks
1. Attempt a Linux **replay** of the extracted I²C transaction set to slave `0x0A` (requires access to the same Serial-IO I²C controller and slave `0x0A`):
   - “Restore / unblank” payload: `len=1034` all-zero tail (matches `unblank_20251231-050055`).
   - “Half-blank parameter” payload: same `len=1034` header, but with the 6 bytes at offsets `0x0c..0x11` set to `9c 18 2c 28 33 1a` (matches the second `len=1034` write in `halfblank_20251231-024301`).
   - If needed, replay the same surrounding query pattern (`len=6` write + `len=1029` read) that appears around these writes in the Windows captures.
2. If we still can’t talk to the bus from Linux, keep iterating on the “mux commit” path (SMI/GNVS sequence) until the controller becomes usable, then validate the replay.
