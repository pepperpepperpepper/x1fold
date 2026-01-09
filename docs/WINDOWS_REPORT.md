WINDOWS-ORIGINATED HANDSHAKE RESEARCH REPORT  
============================================

Mission Context
---------------

- **Objective:** Discover the exact OEM “commit” that switches the Lenovo X1 Fold’s I²C4 pads from the Intel Sensor Hub (ISH) back to the Intel Serial‑IO (DesignWare) controller, then mirror that sequence from Linux AML so a START condition actually fires.  
- **Hardware/OS:** Lenovo ThinkPad X1 Fold, Windows 11 Pro (Test Mode enabled, Secure Boot relaxed to allow Chipsec helper).  
- **Rationale for Windows:** Only the OEM firmware + Lenovo policy stack on Windows triggers the hidden PMC/SMM path reliably (hinge magnet attach/detach, fold events, etc.). Capturing memory deltas around these events exposes the mailbox / GNVS writes we must replicate on Linux.


Tooling and Environment Setup
-----------------------------

1. **Prerequisites:**  
   - Elevated PowerShell session (administrative).  
   - Test Signing enabled (`bcdedit /set testsigning on`), BitLocker suspended as needed.  
   - Chipsec 1.13.16 with helper driver, ACPICA tools (`acpidump`, `acpixtract`, `iasl`).  
   - `diff_mem.py` Python helper for byte-level diffs (stored at `C:\oem_trace\diff_mem.py`).  
   - Capture orchestration script `capture_oem_snapshot.ps1` plus wrapper `run_oem_snapshot.ps1`.

2. **ACPI Discovery:**  
   - Dumped Windows ACPI tables (`acpidump -o C:\acpi\acpidump.bin`).  
   - Decomposed to DSL via `acpixtract` + `iasl`.  
   - Key findings from `DSDT.dsl`:  
     * `OperationRegion (GNVS, SystemMemory, 0x936A4000, ...)` and `OperationRegion (MNVS, SystemMemory, 0x936C3018, 0x2000)`.  
     * Mailbox logging region referenced in SSDT18 (`DPTR = 0x904F0000`).  
     * `Field (MNVS, AnyAcc, NoLock, Preserve)` at offset `0xFC0` defines the SMI mailbox registers:  
       - `CMD` (byte) @ `0x936C3FD8`.  
       - `ERR` (dword) @ `0x936C3FDC`.  
       - `PAR0` (dword) @ `0x936C3FE0`.  
       - `PAR1` (dword) @ `0x936C3FE4`.  
     * SMI helper `Method (SMI, 5, Serialized)` writes those fields then pokes `APMC = 0xF5`.


Capture Workflow
----------------

**Scripts:**
- `capture_oem_snapshot.ps1` (parameterized Chipsec dumper).  
- `run_oem_snapshot.ps1` wrapper — defaults GNVS/mailbox/GPIO ranges, pauses for manual event, prints snapshot folder.  

**Capture Procedure:**
1. Start with keyboard **detached**; run the wrapper script in elevated PowerShell via `powershell -ExecutionPolicy Bypass -File C:\oem_trace\run_oem_snapshot.ps1`.  
2. Script takes `pre_*` dumps, prompts; manually snap keyboard **on** (magnet attach).  
3. Hit Enter for `post_*` dumps, waits 1 second, records `post2_*` (captures short-lived values).  
4. Each run stored under timestamped `C:\oem_trace\YYYYMMDD_HHMMSS` with `meta.txt` documenting bases and tool versions.

**Captured Sessions (attach transition):**

| Folder | Event | Notes |
|--------|-------|-------|
| `20251019_152158` | warm-up run | No event triggered (baseline). |
| `20251019_153049` | attach | First complete capture; large mailbox churn, no GNVS change. |
| `20251019_161310` | attach | Additional run while user triggered locally. |
| `20251019_161907` | attach | Repeat with consistent magnet movement. |
| `20251019_161950` | attach | Follow-up confirmatory run with same motion. |


Data Extraction & Diffing
-------------------------

**Tool:** `diff_mem.py pre.bin post.bin BASE` → prints address-wise byte transitions.

**Mailbox Region (0x904F0000..0x904F0FFF, length 0x10000):**
- `pre` vs. `post` showed thousands of ASCII log differences (strings like `TCON`, `Drop TCON due to it is already ...`).  
- Head/tail pointers at `0x904F0014 / 0x904F0018` advanced into new log pages; values differed per run (e.g., `0x904F0014: 0xE053→0x00E9` in run1 vs. `0x60B6→0x60ED` or `0x60F5` in later runs).  
- No stable mailbox offsets changed identically across runs beyond the expected pointer movement; treat mailbox diffs as logging noise rather than the actual commit.

**GPIO Window (0xFD6A0000..0xFD6A1FFF):**
- No meaningful differences in any run, confirming PMC promptly reverts PAD DW1 unless the full commit is replayed.

**GNVS Slice (`GNVS_BASE_WIN + 0x3F00`, length 0x0400):**
- Key consistent deltas found at addresses:  
-  - `0x936C3FD8` (`CMD`): Byte toggles `0x0A → 0x14` at attach, then drops back to `0x0A` when firmware clears the handshake.
-  - `0x936C3FDC`..`0x936C3FDF` (`ERR` field): `0x00000000 → 0x20000000` while the SMI runs, then `→ 0x00000000` at completion.
-  - `0x936C3FE0`..`0x936C3FE3` (`PAR0`): `0x00001200` (idle baseline) → `0x00000000` during the busy window, then restored to `0x00001200`.
- Interpreting the 32-bit fields (10 s capture, hinge attach immediately after boot):  
  - Immediate post state:  
    * `CMD = 0x14`  
    * `ERR = 0x20000000`  
    * `PAR0 = 0x00000000`  
    * `PAR1/2/3 = 0x00000000`  
  - Completion (~10 s later):  
    * `CMD = 0x0A`  
    * `ERR = 0x00000000`  
    * `PAR0 = 0x00001200`  
    * `PAR1/2/3 = 0x00000000`

These offsets match the `MNVS` SMI mailbox fields used by OEM ACPI `SMI()` method—confirming the handshake is a custom SMI command rather than simple MMIO writes.


Analysis of GNVS / SMI Mechanism
--------------------------------

From `DSDT.dsl`:
```asl
Field (MNVS, AnyAcc, NoLock, Preserve)
{
    Offset (0xFC0),
    CMD, 8,
    ERR, 32,
    PAR0, 32,
    PAR1, 32,
    PAR2, 32,
    PAR3, 32
}

Method (SMI, 5, Serialized)
{
    Acquire (MSMI, 0xFFFF)
    CMD  = Arg0
    ERR  = One
    PAR0 = Arg1
    PAR1 = Arg2
    PAR2 = Arg3
    PAR3 = Arg4
    APMC = 0xF5
    While ((ERR == One)) { Stall (1) }
    Release (MSMI)
}
```

Decoded handshake sequence (updated 2025-10-19 based on 10 s sampler `event_20251019_212924.json`):
1. Lenovo policy issues `SMI (0x14, 0x00000000, 0x00000000, 0, 0)` immediately after the hinge attach. The SMI helper stores those arguments, so GNVS shows `CMD=0x14`, `PAR0=0x00000000`, `PAR1/2/3=0`, and `ERR=1`.
2. Firmware/PMC performs the mux hand-off while `ERR` remains busy (`0x20000000`). Roughly 10 s later it reports completion by restoring `CMD=0x0A`, clearing `ERR` to `0x00000000`, and writing `PAR0=0x00001200`, leaving `PAR1/2/3` at zero.

Therefore, reproducible bytes to replay:  
- Invoke `\SMI (0x14, 0x00000000, 0x00000000, Zero, Zero)` if the method exists.  
- Otherwise replicate the field writes:
  * Set `CMD=0x14`, `ERR=1`, `PAR0=0`, `PAR1/2/3=0` and pulse `APMC=0xF5` while polling until firmware clears `ERR`.  
  * Once `ERR` becomes `0`, restore `CMD=0x0A` and `PAR0=0x00001200` to match Windows’ post-handshake state.


Integration into Linux AML (`SSDT7.dsl`)
------------------------------------------------------

1. Declared the OEM handler: `External (\SMI, MethodObj)` at file top.  
2. Inside `XSEL` (after PAD83/84 programming but before LPSS `Store` / canary), added:
   ```asl
   If (CondRefOf (\SMI))
   {
       \SMI (0x14, Zero, Zero, Zero, Zero)
   }
   Else
   {
       // Fallback direct GNVS pokes mirroring Windows
       Store (0x14, GFD8)  // CMD = 0x14
       Store (One,  GFD9)  // ERR busy
       Store (Zero, GFDA)
       Store (Zero, GFDB)

       Store (Zero, GFDC)  // PAR0 = 0
       Store (Zero, GFDD)
       Store (Zero, GFDE)
       Store (Zero, GFDF)

       Store (Zero, GFE0)  // PAR1/2/3 = 0
       Store (Zero, GFE1)
       Store (Zero, GFE2)
       Store (Zero, GFE3)
   }
   ```
   `GFD8`..`GFEB` map the 0x936C3FD8..0x936C3FEB byte window already defined in the DSL.
3. After firmware clears `ERR`, restore the steady-state bytes (`CMD=0x0A`, `PAR0=0x00001200`) before proceeding with the canary/dump logic.  
4. Rebuilt AML with `iasl -tc acpi/SSDT7.dsl` — success (no errors).


Operational Checklist (Post-Windows)
------------------------------------

1. Deploy updated `SSDT7.aml` into initramfs or EFI override.  
2. On Linux boot: verify `\SMI` resolves (should be defined in DBT). If present, the command will be identical to Windows path; fallback ensures older overlays still write the GNVS bytes.  
3. Observe in AML canary: `ABRT` should stay non-zero, TX FIFO drain should happen quickly, confirming START launched.  
4. Rebind `i2c_designware_platform`, run `i2cdetect` and panel commands (`{0xAB,0x04}` / `{0xAB,0x00}`) to confirm handshake persists.


Repository Artifact Map (2025-11-30)
------------------------------------

After mounting the Windows volume on the bare-metal host via `baremetal_ssh`, we copied the following directories into the repo/workspace. This list summarizes what each contains and how useful it is for the half-panel blanking investigation:

- `docs/acpi-capture/…` (from `/mnt/windows/acpi-capture`): one GNVS dump per static state (`20251018-docked`, `20251018-transition`) plus PowerShell transcripts. Helpful for context, but **no** pre/post pair across the magnet event, so there are no half-panel deltas inside.
- `docs/windows-acpi/acpi/…` (from `/mnt/windows/acpi`): full Windows ACPI namespace (DSDT/SSDT DSL + DAT). Use these when decoding `EDMX`, `GGOV/SGOV`, `_DSM 0x15`, etc.
- `/tmp/oem_trace/oem_trace/…` (from `/mnt/windows/oem_trace`): timestamped GNVS/GPIO/PMR snapshots plus the capture scripts (`capture_oem_snapshot.ps1`, `run_oem_snapshot.ps1`, `diff_mem.py`). These runs are the prime candidates for discovering the tile-specific governor bit; diff the `pre/post` binaries inside each folder.
- `/tmp/panel_probe/panel_probe/…` (from `/mnt/windows/panel_probe`): Windows panel-probing scripts and dumps (ETW/telemetry) for correlating GNVS changes with visible blanking.
- `/tmp/psf/psf/…` (from `/mnt/windows/psf`): CSV traces (`gnvs_trace.csv`, `psf_trace.csv`) plus Python helpers for quick plotting.
- `/mnt/windows/trace`: still on the host (contains ETLs such as `blank_run*.etl`, `wpr_boot*.etl`). Tarballing the entire folder timeouts; pull individual ETLs only when we actually need them.

Action item: rerun `run_oem_snapshot.ps1` on Windows while deliberately attaching/detaching the keyboard so each timestamped folder captures **both** the “before” and “after” GNVS snapshots around the magnet blank. Once we have those pairs, `diff_mem.py` will reveal which GNVS/EDMX bit Lenovo flips for half-panel blanking, which we can then emulate from Linux.

Artifacts & References
----------------------

- Captured directories on Windows host:  
  * `C:\oem_trace\20251019_161907` (attach run #1).  
  * `C:\oem_trace\20251019_161950` (attach run #2).  
  * Prior runs at `...\153049` and `...\161310` provide baseline/logging-only comparisons.
- Local copies for analysis (Codex workspace `/tmp` naming):  
  * `/tmp/win_attach_run3_*` ↔ `161907`.  
  * `/tmp/win_attach_run4_*` ↔ `161950`.  
- Updated AML: `acpi/SSDT7.dsl` and compiled `acpi/SSDT7.aml`.  
- Supporting scripts stored on Windows host:  
  * `C:\oem_trace\capture_oem_snapshot.ps1`  
  * `C:\oem_trace\run_oem_snapshot.ps1` (prints latest folder)  
  * `C:\oem_trace\diff_mem.py`


Key Takeaways
-------------

1. The Lenovo mux commit is not a GPIO register write—it is a PMC/SMI transaction: `SMI (0x14, 0x00000000, 0x00000000, 0, 0)`, followed by firmware restoring `CMD=0x0A`, `PAR0=0x00001200` once `ERR` clears.  
2. Attaching the keyboard triggers that SMI; the 10 s sampler confirmed `ERR` holds busy (`0x20000000`) for ~10 s before dropping to `0`, so any Linux replay must poll until completion.  
3. Mailbox logs (0x904F0000) contain verbose debugging but no deterministic control bytes beyond the head/tail pointers.  
4. Integrating the SMI call (or emulating its GNVS writes plus the completion poll) inside `SSDT7.dsl` should provide the missing handshake, allowing the Serial‑IO controller to launch START immediately after pad configuration.

Supplementary Windows Facts
---------------------------

### MNVS Mailbox Field Layout (from DSDT)

`OperationRegion (MNVS, SystemMemory, 0x936C3018, 0x2000)`

| Field | Offset (hex) | Width | Physical Address |
|-------|--------------|-------|------------------|
| `CMD` | `0x0FC0` | 8 bits  | `0x936C3FD8` |
| `ERR` | `0x0FC1` | 32 bits | `0x936C3FDC` |
| `PAR0`| `0x0FC5` | 32 bits | `0x936C3FE0` |
| `PAR1`| `0x0FC9` | 32 bits | `0x936C3FE4` |
| `PAR2`| `0x0FCD` | 32 bits | `0x936C3FE8` |
| `PAR3`| `0x0FD1` | 32 bits | `0x936C3FEC` |

Widths align with the OEM `SMI` helper: `CMD` is byte-accurate; each parameter is stored little‑endian as a DWORD.

### Global `\SMI` Helper Signature

Located at the ACPI root:

```asl
OperationRegion (SMI0, SystemIO, 0xB2, 0x01)
Field (SMI0, ByteAcc, NoLock, Preserve) { APMC, 8 }

Mutex (MSMI, 0x00)
Method (SMI, 5, Serialized)
{
    Acquire (MSMI, 0xFFFF)
    CMD  = Arg0
    ERR  = One
    PAR0 = Arg1
    PAR1 = Arg2
    PAR2 = Arg3
    PAR3 = Arg4
    APMC = 0xF5
    While ((ERR == One))
    {
        Sleep (One)
        APMC = 0xF5
    }

    Local0 = PAR0
    Release (MSMI)
    Return (Local0)
}
```

- Path: `\SMI`
- Arguments: `(command, param0, param1, param2, param3)`
- Side effects: latches arguments into the MNVS mailbox (`CMD/ERR/PARx`), pokes SMM via `APMC = 0xF5`, spins until firmware clears `ERR`, returns the post-SMI value of `PAR0`.

### Panel-Oriented I²C Resource Values

From GNVS capture (`chipsec_util mem read 0x936A4400` and `0x936A5800`):

| Symbol | Description (per `_SB.PC00.CLP4`) | Offset (hex) | Value | Notes |
|--------|-----------------------------------|--------------|-------|-------|
| `C4IB` | Controller selector               | `0x55E` | `0x03` | `_DEP` maps `0x03` → `I2C3`. |
| `C4IA` | 7‑bit slave address               | `0x55F` | `0x0049` | Same value mirrored in `C5IA`. |
| `C5IB` | Alternate controller selector     | `0x590` | `0x03` | |
| `C5IA` | Alternate 7‑bit address           | `0x591` | `0x0049` | |

`_CRS` for `\_SB.PC00.CLP4` invokes `IICB (C4IA, C4IB)`, so Windows enumerates the panel interface at address `0x49`. With the mux commits replayed, userspace can target this device immediately using the `{0xAB,0x04}` / `{0xAB,0x00}` sequence.

Windows Telemetry Mining Progress (2025-11-30)
----------------------------------------------

- **GNVS batch diffing:** A new helper (`traces/windows_gnvs_diffs.csv`) walks every `pre/post` pair inside `/tmp/oem_trace/oem_trace`. Across all runs we only observed deltas at `CMD/ERR/PAR0` (absolute addresses `0x936C3FD8`–`0x936C3FE5`) plus one outlier run (`20251019_161310`) where Lenovo briefly stuffs status bytes into the upper `ERR/PAR0` window (`0x936C3FDD/0x936C3FDF/0x936C3FE1/0x936C3FE5`). No additional GNVS fields toggled, so the half-panel blanking flag is still undiscovered.
- **Panel probe dumps:** Parsed every JSON trace under `/tmp/panel_probe/panel_probe/dumps` and summarized them in `traces/panel_probe_summary.csv`. Every capture repeats the same mailbox choreography (CMD `0x14` → `0x0A`, ERR `0x20000000` → `0`, PAR0 `0x0` ↔ `0x1200/0x1400`), and none of the samples show a third command index (e.g., `0x16`). This corroborates that Windows is driving only the global panel PPS rail during those instrumented events.
- **Open question:** Because neither the GNVS diffs nor the panel probe traces expose a second-stage/tile-specific control, the working theory is that Lenovo hides the half-panel blank under another GNVS bank (perhaps `EDMX` or a runtime-populated SGOV bit) that was not captured in the existing runs. We need fresh Windows captures that explicitly include the “keyboard magnet blank” state to validate this.

Windows Half-Blank Marked Capture (2025-12-30)
---------------------------------------------

- **Capture:** `halfblank_20251230-131329` (ETL on Windows: `C:\trace\halfblank_20251230-131329.etl`; focused exports in `C:\trace\exports\halfblank_20251230-131329_focus\`). Pulled into the repo as `traces/windows_etl_exports/halfblank_20251230-131329_focus/`.
- **Markers:** In-ETL marker events show `BEFORE_HALFBLANK` at `3,964,214` and `AFTER_HALFBLANK` at `9,988,456` (≈ 6.0 s window). These marker timestamps are more reliable than wall-clock when bounding `xperf -a dumper -range`.
- **DxgKrnl result (important):** Within the marker window there are **no** `Microsoft-Windows-DxgKrnl/DisplayConfigPlaneChange` events; the observed MPO flips keep full-screen rectangles (`DstRect 0..2024 x 0..2560`). This argues against “half blank via plane cropping” on this platform.
- **Update (2026-01-07):** newer marked captures (see `traces/windows_etl_exports/halfblank_20260107-074913_focus/`) *do* show a half-height clip in DxgKrnl/DWM:
  - `FlipMultiPlaneOverlay` / `DisplayConfigPlaneChange` for `PlaneIndex=2` with `ClipRect.bottom=1240` (half-height), near the `LenovoModeSwitcher.exe` I²C write to slave `0x0A`.
  - So we can no longer treat “no plane cropping” as a stable conclusion; it appears capture-dependent and/or our earlier focus filters missed the relevant plane-change rows.
- **Bus-level result (important):** Within the same marker window, `Intel-iaLPSS2-I2C` logs a burst of traffic to **slave `0x0A`**, including transactions attributed to `LenovoModeSwitcher.exe`. This is the first concrete telemetry indicating the half-blank behavior is driven by an I²C-sideband command rather than a visible DxgKrnl mode/plane transition.
- **Raw dump artifact:** A marker-bounded raw dump for `Intel-iaLPSS2-I2C` (with `-add_rawdata`) is stored at `traces/windows_etl_exports/halfblank_20251230-131329_focus/i2c_raw_window.txt`.
- **Follow-up change:** `VendorProviders.wprp` and `extract_halfblank_focus.ps1` were updated to also include Microsoft bus class providers (`Microsoft-Windows-SPB-ClassExtension`, `Microsoft-Windows-SPB-HIDI2C`, `Microsoft-Windows-GPIO-ClassExtension`) for the next capture. The goal is to obtain richer event decoding / payload context around the in-window I²C activity.

### Follow-up capture with SPB payload bytes (2025-12-30)
- **Capture:** `halfblank_20251230-232848` (ETL on Windows: `C:\trace\halfblank_20251230-232848.etl`; focused exports in `C:\trace\exports\halfblank_20251230-232848_focus\`). Pulled into the repo as `traces/windows_etl_exports/halfblank_20251230-232848_focus/`.
- **Key win:** With `Microsoft-Windows-SPB-ClassExtension` enabled, the focused vendor export contains `IoSpbPayloadTdBuffer` rows with **actual transfer bytes**.
- **Concrete signature (candidate half-blank control):** `LenovoModeSwitcher.exe` issues an `Intel-iaLPSS2-I2C` transaction to **slave `0x0A`** with **length `1034`**, and the corresponding SPB payload is a single write whose only non-zero bytes are at the front:
  - `04 00 39 03 05 00 04 04 09 20` + zero-padding out to 1034 bytes (see `traces/windows_etl_exports/halfblank_20251230-232848_focus/spb_bins/*len1034.bin`).
- **Important nuance:** The marked half-blank sequence also includes a *second* `len=1034` write with the same header, but with 6 additional non-zero bytes at offsets `0x0c..0x11`:
  - `... 9c 18 2c 28 33 1a ...` (see `traces/windows_etl_exports/halfblank_20251230-232848_focus/spb_bins/*len1034.bin`).
- **No-post-window confirmation (2025-12-31):** Capture `halfblank_20251231-024301` (focused exports in `traces/windows_etl_exports/halfblank_20251231-024301_focus/`) reproduces both `len=1034` variants even when the capture is run with no post-window delay, so the second write is not merely “post” noise.
- **UNBLANK capture (2025-12-31):** Capture `unblank_20251231-050055` (focused exports in `traces/windows_etl_exports/unblank_20251231-050055_focus/`) contains only the “all-zero tail” `len=1034` write. That `len=1034` payload is **byte-identical** to the first `len=1034` write in `halfblank_20251231-024301`; the only difference vs the half-blank “6-byte payload” variant is bytes at offsets `0x0c..0x11` (`00 00 00 00 00 00` vs `9c 18 2c 28 33 1a`).
- **Re-confirmation (2026-01-01):** The newer marked captures `halfblank_20260101-045907` and `unblank_20260101-051802` (focused exports in `traces/windows_etl_exports/*_focus/`) reproduce the same signature:
  - Halfblank: `len=1034` write has the 6 non-zero bytes at offsets `0x0c..0x11` (`9c 18 2c 28 33 1a`).
  - Unblank: the same offsets are `00 00 00 00 00 00`.
  - In this run there is exactly **one** Lenovo `len=1034` write in each capture (no second all-zero/extra variant pair), but the per-byte delta remains exactly the same (see `.../spb_lenovo_summary.txt` in each focus dir).
- **Related pre/post traffic:** We also see a repeated “query” pattern: a 6-byte write `04 00 34 02 05 00` followed by a 1029-byte read response beginning `12 00 04 2c 28 d0 32 0b 0a b4 0c 0a …` (extracted in the same `spb_bins/` directory).
- **Topology clue (2026-01):** On this unit, ACPI/PnP strongly suggest the `SlaveAddress=0x0A` traffic is on **I2C1** and corresponds to the Wacom HID-over-I²C device:
  - Windows `Get-PnpDevice` shows `ACPI\\WACF2200\\...` (“Wacom Device”, service `hidi2c`) with LocationPath `ACPI(_SB_)#ACPI(PC00)#ACPI(I2C1)#ACPI(TPL1)`.
  - The DSDT’s `\_SB.PC00.I2C1.TPL1` selects I²C address `0x0A` for `WACF2200` (see `dsdt-baremetal.dsl` `Device (TPL1)` / `ITML`).
  - Practical implication: replicating halfblank/unblank from Linux may only require access to the already-present `00:15.1` controller (I2C1), not `00:15.3`.
- **Artifacts for review/replay:**
  - Human summary: `traces/windows_etl_exports/halfblank_20251230-232848_focus/spb_lenovo_summary.txt`
  - Extracted payloads: `traces/windows_etl_exports/halfblank_20251230-232848_focus/spb_bins/`
  - Extractor: `scripts/windows_spb_extract_payloads.py`

### Screenshot classifier + Wacom HID feature reports (2026-01-06)

- **Screenshot classifier captures:** `halfblank_screens_20260106-222645` and `unblank_screens_20260106-222717` (fetched into `traces/windows_etl_exports/*_focus/`).
  - The screenshots prove this is not “black pixels inside an unchanged desktop”: the captured virtual screen size toggles between:
    - **Normal:** `1012x1280` (≈ `2024x2560` at 200% scaling)
    - **Half-blank:** `1012x620` (≈ `2024x1240` at 200% scaling)
  - This shows HALFBLANK/UNBLANK includes an **OS-visible display configuration / desktop size change** (the “blanked” area is outside the desktop). This does **not** by itself prove whether panel rails change; rail proof requires PP telemetry.
- **Marked WPR captures (with screenshots + display-state):** `halfblank_20260106-222748` and `unblank_20260106-223930`.
  - The SPB payload signature is unchanged: HALFBLANK contains **two** `len=1034` writes (all-zero variant + `9c 18 2c 28 33 1a` variant), and UNBLANK contains only the all-zero variant. See `traces/windows_etl_exports/*/spb_bins/*len1034.bin`.
- **Wacom HID feature dumps (before/after):** `wacom_halfblank_20260106-231916` and `wacom_unblank_20260106-231936`.
  - Only the Wacom vendor-defined HID collection **`WACF2200&COL02`** changes across HALFBLANK/UNBLANK; `COL03/COL05/COL07` remain stable.
  - `ReportId=0x03`: bytes **[10..15]** toggle exactly with the Lenovo SPB write delta:
    - Normal/unblank state: `00 00 00 00 00 00`
    - Half-blank state: `9c 18 2c 28 33 1a`
  - `ReportId=0x04`: bytes **[14..15]** toggle between `00 00` and `33 1a` (matching the last 2 bytes of the 6-byte delta seen in the 1029-byte read response).
  - These are in `traces/windows_etl_exports/wacom_*_focus/wacom_{before,after}.json`.

### Forcing full-height while the keyboard is still attached (2026-01-07)

- **Result:** `cap7_force_fullheight.ps1` (a `ChangeDisplaySettingsEx`-based override) restores full-height content immediately even when the keyboard is still attached and HALFBLANK policy would normally apply.
- **Implication:** this strongly supports the model that HALFBLANK is *primarily* a Windows policy + display pipeline configuration (DxgKrnl/DWM clip / desktop geometry), not a panel power rail cut.
- **Notes:** this must be run from an interactive console/RDP session (OpenSSH sessions are non-interactive and do not expose display devices to the process).

Windows SerialIO / I2C3 Enumeration Snapshot (2025-12-31)
--------------------------------------------------------

- **Access:** on-device Windows SSH proxy via `ssh -p 4400 Administrator@localhost`.
- **Why:** the Linux blocker is still `00:15.3` (I2C3) not enumerating; we want a Windows “ground truth” snapshot of PSF/SerialIO gating + PnP LocationPaths to avoid guessing.
- **Tooling note:** CHIPSEC’s `msgbus` utilcommand is not implemented on the Windows helper on this box, so we added a small workaround (`TO_TEST_ON_WINDOWS/serialio/msgbus_dump.py`) that performs message-bus reads via PCI config (MCR/MDR at `00:00.0`).
- **Baseline result (static):** PSF msgbus reads at port `0xA9` offsets `0x0900/0x0910/0x0920/0x0930/0x0934/0x0938` all read `0x00000400` (no variance).
- **PnP mapping result:** Windows reports SerialIO I²C controllers at `PCI(1500)` and `PCI(1501)` (`DEV_51E8` and `DEV_51E9`) but the snapshot does **not** show a `PCI(1503)` path (expected `00:15.3` / `DEV_51EA`).
- **Next test (interactive):** run `C:\trace\serialio\capture_serialio_unlock_marked.ps1` during a physical HALF-BLANK/UNBLANK to see if any gating bits flip transiently (a static snapshot can miss brief windows).

### Follow-up non-interactive validation (2025-12-31)

- Added a multi-port baseline dump (Windows, on-device): `msgbus_dump.py` reads for ports `0xA1/0xA3/0xA9/0xAB/0xAD` across offsets `0x0900/0x0910/0x0920/0x0930/0x0934/0x0938` all still return `0x00000400` (see `traces/windows_serialio_unlock/msgbus_multi_20251231-165707.zip`).
- Fixed a pattern bug in `TO_TEST_ON_WINDOWS/serialio/capture_serialio_unlock_marked.ps1` (the `Get-PnpDevice` filter used `PCI\\VEN_...` instead of `PCI\VEN_...`), so the marked snapshot now correctly records the present SerialIO devices (`DEV_51E8` + `DEV_51E9`) while still showing no `DEV_51EA` (see `traces/windows_serialio_unlock/serialio_HALFBLANK_20251231-172537.zip`).
- Re-ran the marked SerialIO snapshot on 2026-01-01 (`serialio_HALFBLANK_20260101-043901.zip`, `serialio_UNBLANK_20260101-045707.zip`): still no `DEV_51EA`, GNVS slice unchanged, and PSF msgbus reads at port `0xA9` remain `0x00000400` at all probed offsets.
