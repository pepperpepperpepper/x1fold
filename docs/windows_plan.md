# Windows ETL Analysis Plan (AWS VM)

## Goal
Use the AWS Windows Server instance (13.222.177.142, key `~/.ssh/claude_key`, user `arch`) to analyze the Lenovo ETL/telemetry dumps so we can locate the half-panel blanking controls. This document tracks the setup and the tasks we will run on that host.

## Update (2025-12): Prefer On-Device Windows via SSH Proxy
The AWS VM approach works for offline analysis, but our current fastest iteration loop is running WPR + `xperf` **directly on the target Windows install** (so we don’t have to upload multi‑GB ETLs) and then pulling the small focused exports back into the repo.

### Access
- Windows SSH proxy: `ssh -p 4400 Administrator@localhost` (PowerShell; use `;` separators, not `&&`).
- Working directory on Windows: `C:\trace` (profiles + scripts + captures).

### Update (2025-12): Prefer Chipsec register snapshots for SerialIO unlock debugging
When the problem is **Linux enumeration** (getting `00:15.3` / I2C3 to appear), ETW/WPR is usually not enough.
What we need is the **hardware “target state”**: PSF/SerialIO gating bits and PnP location paths *as seen by Windows*.

This is small data (KBs) and can be captured + fetched quickly, without moving multi‑GB ETLs.

#### Goal
- Determine whether Windows has `00:15.3` (I2C3) present and what PSF shadow registers look like when it is.
- Use that as the ground truth for the Linux early-boot PSF work (EFI stub / BootChain / kernel quirk), instead of guessing which bits to clear.

#### Preconditions
- Admin PowerShell on the target Windows install.
- Chipsec driver must be loadable (this may require test-signing / Secure Boot relaxed; see `docs/ACPI_STATUS.md` “Test-signed driver + MMIO capture” notes).

#### One-shot snapshot (Windows)
Run this in an elevated PowerShell (edit the output folder if desired):
```powershell
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$out = "C:\\trace\\serialio_unlock_$ts"
New-Item -ItemType Directory -Force -Path $out | Out-Null

# Security / boot-policy sanity snapshot (so we know whether we're already in a “low security” state)
# NOTE: some of these may throw on non-UEFI or when cmdlets are unavailable; we still want whatever does work.
try { Confirm-SecureBootUEFI | Out-File -Encoding utf8 "$out\\secureboot.txt" } catch { $_ | Out-File -Encoding utf8 "$out\\secureboot.txt" }
bcdedit /enum {current} | Out-File -Encoding utf8 "$out\\bcdedit-current.txt"
bcdedit /enum | Out-File -Encoding utf8 "$out\\bcdedit-all.txt"
Get-BitLockerVolume | Format-List | Out-File -Encoding utf8 "$out\\bitlocker.txt"
try { Get-CimInstance -ClassName Win32_DeviceGuard | Format-List | Out-File -Encoding utf8 "$out\\deviceguard.txt" } catch { $_ | Out-File -Encoding utf8 "$out\\deviceguard.txt" }
try { Get-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\DeviceGuard\\Scenarios\\HypervisorEnforcedCodeIntegrity" -Name Enabled | Out-File -Encoding utf8 "$out\\hvci.txt" } catch { $_ | Out-File -Encoding utf8 "$out\\hvci.txt" }

# Record PnP inventory + location paths (used to confirm BDF/function numbers)
pnputil /enum-devices /class System | Out-File -Encoding utf8 "$out\\pnputil-system.txt"
Get-PnpDevice -PresentOnly | Sort-Object Class, FriendlyName | Format-Table -AutoSize | Out-File -Encoding utf8 "$out\\pnp-present.txt"

# Capture Intel SerialIO devices + location paths (look for PCI(1503) / function 3 for I2C3)
$intel = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like "PCI\\VEN_8086*" -or $_.InstanceId -like "ACPI\\*" }
$intel | ForEach-Object {
  $id = $_.InstanceId
  try {
    $lp = (Get-PnpDeviceProperty -InstanceId $id -KeyName "DEVPKEY_Device_LocationPaths").Data
    if ($lp) { "$id`n  $($lp -join \"`n  \")`n" | Out-File -Append -Encoding utf8 "$out\\location-paths.txt" }
  } catch {}
}

# Chipsec: confirm the driver is available (writes status to stdout)
python -m chipsec_util platform driver | Out-File -Encoding utf8 "$out\\chipsec_driver_status.txt"

# Chipsec: GNVS selectors related to I2C3/I2C4 promotion (helps confirm whether IM03 is set as expected on Windows)
# These addresses are platform-specific; update if GNVS base moves on a new BIOS.
try { python -m chipsec_util mem read 0x936C2160 0x80 | Out-File -Encoding utf8 "$out\\gnvs_936C2160.txt" } catch { $_ | Out-File -Encoding utf8 "$out\\gnvs_936C2160.txt" }

# PSF / SerialIO gating snapshots (ports/offsets mirror what we probe on Linux)
#
# IMPORTANT: on this target, CHIPSEC's WindowsHelper does NOT implement the msgbus API,
# so `python -m chipsec_util msgbus read ...` fails. Use our helper script instead:
#
#   - Copy: TO_TEST_ON_WINDOWS/serialio/msgbus_dump.py -> C:\trace\serialio\msgbus_dump.py
#   - Then run it to emit msgbus_A9_*.txt into $out (via PCI config MCR/MDR).
python C:\trace\serialio\msgbus_dump.py --port 0xA9 --out-dir $out | Out-File -Encoding utf8 "$out\\msgbus_dump_stdout.txt"

# Driver/version inventory for Intel SerialIO (useful if behavior changes across driver versions)
pnputil /enum-drivers | findstr /i "Intel iaLPSS Serial IO I2C" | Out-File -Encoding utf8 "$out\\pnputil-serialio-drivers.txt"

# Zip for easy fetch
Compress-Archive -Path "$out\\*" -DestinationPath "${out}.zip" -Force
Write-Host "Wrote: ${out}.zip"
```

#### Fetch the snapshot to Linux
From the repo host:
```bash
scp -P 4400 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  Administrator@localhost:C:/trace/serialio_unlock_*.zip traces/windows_etl_exports/
```

#### Before/after snapshot around HALF-BLANK / UNBLANK (recommended)
The one-shot snapshot is great for “static state”, but for **unlock debugging** we want “what changed when the event happened”.

Recommended: use the marked/polling helper (prompts for BEFORE/AFTER and records a msgbus poll timeline):
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
cd C:\trace\serialio
.\capture_serialio_unlock_marked.ps1 -Scenario HalfBlank -PollSeconds 60 -PollMs 100
.\capture_serialio_unlock_marked.ps1 -Scenario Unblank   -PollSeconds 60 -PollMs 100
```

Run the one-shot snippet **twice**:
1) once *before* reproducing the event (name the zip `..._before.zip`),  
2) once *immediately after* reproducing the event (name the zip `..._after.zip`).

Minimal example:
```powershell
cd C:\trace

# BEFORE
# (paste/run the one-shot snippet above)
Rename-Item -Force "C:\trace\serialio_unlock_*.zip" "C:\trace\serialio_unlock_before.zip"

Read-Host "Now reproduce HALF-BLANK/UNBLANK physically, then press Enter for AFTER"

# AFTER
# (paste/run the one-shot snippet above)
Rename-Item -Force "C:\trace\serialio_unlock_*.zip" "C:\trace\serialio_unlock_after.zip"
```

Then fetch both zips and diff the `msgbus_*.txt` files (this tells us which gating bits actually changed on Windows).

#### Polling loop during the event (optional, high signal if values are transient)
If we suspect firmware flips bits briefly (and then restores), a before/after snapshot can miss it.
This loop logs repeated msgbus reads to a single file so we can search for transient transitions.

```powershell
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$out = "C:\\trace\\serialio_unlock_poll_$ts"
New-Item -ItemType Directory -Force -Path $out | Out-Null

# Uses msgbus_dump.py (see note above re: WindowsHelper msgbus).
python C:\trace\serialio\msgbus_dump.py --port 0xA9 --poll-ms 100 --poll-seconds 30 --csv-out "$out\\msgbus_poll_A9.csv"

Compress-Archive -Path "$out\\*" -DestinationPath "${out}.zip" -Force
Write-Host "Wrote: ${out}.zip"
```

If this produces a hit (values changing), we can tighten the loop or add more offsets/ports (`0xAD/0xAB/0xA1/0xA3`) to follow the full hierarchy.

#### Mapping ETW “Idx” / controller handles → PCI function (recommended)
ETW often only tells us `Idx=0/1` and `SlaveAddress=0x000a`. To relate that to `00:15.x`:
- capture the PnP “LocationPaths” for every “Intel(R) Serial IO I2C Host Controller” (already included in the one-shot snapshot),
- and confirm which path contains `PCI(1503)` (function 3), which is the device Linux must enumerate as `00:15.3`.

#### Mapping slave `0x0A` → ACPI device (2026-01; important for halfblank)
In the halfblank/unblank captures, the high-signal transaction set is to **slave `0x0A`** (SPB / `Intel-iaLPSS2-I2C`).
Before assuming this implies “unlock I2C3”, first establish which controller/device `0x0A` belongs to on this unit:

On our target, Windows shows:
- `Intel(R) Serial IO I2C Host Controller - 51E8` → `PCI(1500)` → `ACPI(I2C0)` (Linux: `00:15.0`)
- `Intel(R) Serial IO I2C Host Controller - 51E9` → `PCI(1501)` → `ACPI(I2C1)` (Linux: `00:15.1`)
- `Intel(R) Serial IO I2C Host Controller - 51C5` → `PCI(1900)` → `ACPI(I2C4)` (Linux: `00:19.0`)

And the Wacom HID-over-I2C device is:
- `ACPI\WACF2200\...` (service `hidi2c`) with LocationPath `ACPI(_SB_)#ACPI(PC00)#ACPI(I2C1)#ACPI(TPL1)`
- The ACPI tables for `\_SB.PC00.I2C1.TPL1` select I²C address `0x0A` for `WACF2200`.

That strongly suggests the halfblank/unblank `SlaveAddress=0x0A` traffic is occurring on **I2C1** (not I2C3).

Quick Windows commands (Admin PowerShell) to reproduce the mapping:
```powershell
# Controllers → BDF (via LocationPaths)
$ctrls = Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -like "*Serial IO I2C Host Controller*" }
foreach ($c in $ctrls) {
  $lp = (Get-PnpDeviceProperty -InstanceId $c.InstanceId -KeyName "DEVPKEY_Device_LocationPaths").Data
  Write-Output "=== $($c.FriendlyName) ==="
  Write-Output $c.InstanceId
  if ($lp) { $lp | ForEach-Object { "  $_" } }
  ""
}

# Wacom device → confirms it sits under ACPI(I2C1)#ACPI(TPL1) and uses hidi2c
$w = Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -like "*Wacom*" } | Select-Object -First 1
(Get-PnpDeviceProperty -InstanceId $w.InstanceId -KeyName "DEVPKEY_Device_LocationPaths").Data
(Get-PnpDeviceProperty -InstanceId $w.InstanceId -KeyName "DEVPKEY_Device_Service").Data
```

### Capture (interactive, marked)
On Windows (Admin PowerShell):
```powershell
Set-ExecutionPolicy -Scope LocalMachine -ExecutionPolicy RemoteSigned -Force
cd C:\trace\halfblank
.\capture_halfblank_marked.ps1 -CapturePpRegs
```

For an explicit **UNBLANK / restore** capture (so filenames + markers are unambiguous):
```powershell
Set-ExecutionPolicy -Scope LocalMachine -ExecutionPolicy RemoteSigned -Force
cd C:\trace\halfblank
.\capture_halfblank_marked.ps1 -Scenario Unblank -PostSeconds 0 -CapturePpRegs
```

`-CapturePpRegs` writes `before_pp_regs.json`/`after_pp_regs.json` into `C:\trace\exports\<base>_focus\` by reading IGD BAR0 + `PP_STATUS/PP_CONTROL` offsets (`0xC7200/0xC7204`) via CHIPSEC. This is our current “rail” ground truth on Windows.

### Fetch focused exports to Linux
From the repo host:
```bash
./scripts/windows_fetch_focus.sh <base_name>
```
This pulls `dxg_focus.txt`, `acpi_focus.txt`, `vendor_focus.txt`, `summary.txt`, and `<base_name>.marks.txt` into `traces/windows_etl_exports/<base_name>_focus/`.

### Notes / gotchas
- Markers: on this Windows build, the correct command is `wpr -marker <text>` (not `wpr -mark`).
- If `wpr` is already recording you’ll get `0xC5583001` (“profiles already running”); `capture_halfblank_marked.ps1` now checks `wpr -status` and can stop/cancel the preexisting session before starting a new one.
- Vendor focus extraction can take >10 minutes once we include extra SPB/GPIO providers; if your SSH command times out, re-run extraction separately or use `-SkipExtract` and extract later.

## Host Prep
1. SSH (or mstsc/RDP) into `arch@13.222.177.142` using the provided SSH key.
2. Confirm Windows PowerShell access and enable execution of unsigned scripts: `Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process`.
3. Install the Windows Performance Toolkit (WPT):
   - Download the Windows ADK installer (`adksetup.exe`).
   - Select “Windows Performance Toolkit” only.
   - Verify `wpa.exe` and `wpaexporter.exe` exist under `"C:\Program Files (x86)\Windows Kits\10\Windows Performance Toolkit"`.
4. Install auxiliary CLI tools we’ll need: 7-Zip (for archives), git (optional), Python 3 (if not already present for diff scripts).

## Data Staging
1. From the Linux repo host, rsync the relevant directories to the Windows VM (via `scp`/`rsync` over SSH or an SMB share):
   - `/mnt/finished/windows-trace` → `C:\windows-trace` (contains `blank_run*.etl`, `BlankDetect.wprp`, scripts).
   - `/tmp/oem_trace/oem_trace` → `C:\oem_trace` (GNVS snapshots, PowerShell helpers).
   - `/tmp/panel_probe/panel_probe` → `C:\panel_probe` (JSON traces, scripts).
2. Keep the transfers incremental (use `rsync --size-only`) since the ETLs are large.
3. After copying, verify file integrity (spot-check a few ETLs/JSON files with `Get-FileHash`).

## Analysis Tasks
1. **ETL Inspection**
   - Launch WPA (GUI) or use `wpaexporter`:
     ```powershell
     cd C:\windows-trace
     "C:\Program Files (x86)\Windows Kits\10\Windows Performance Toolkit\wpaexporter.exe" \
         -i blank_run1.etl -profile BlankDetect.wprp -o blank_run1.csv
     ```
   - Focus on ACPI, Kernel-PnP, DxgKrnl, and custom Lenovo providers around the magnet blank timestamps. Export CSV slices for each.
2. **Event Correlation**
   - Use `tracerpt blank_run1.etl -y -o blank_run1_events.csv -of CSV` to get raw provider events.
   - Filter for the Lenovo GUID (`3e5b41c6-eb1d-4260-9d15-c71fbadae414`) and any ACPI Video `_DSS/_DOS` calls.
3. **GNVS/Panel Probe Cross-Reference**
   - Run the existing PowerShell helper scripts (`analyze-blank.ps1`, `run_blank_trace.ps1`) to produce summary logs if needed.
   - Compare ETL timestamps with GNVS diffs (`diff_mem.py`) and panel_probe JSON entries.
4. **Half-Panel Hypothesis Testing**
   - Search the ETL logs for changes in the `EDMX`/`SGOV/GGOV` fields, or for secondary `_DSM` calls occurring only during keyboard attach/detach.
   - Document any newly identified GUID/function combos.

## Deliverables
- CSV exports of key tables (ACPI, DxgKrnl, PnP) under `traces/windows_etl_exports/` in the repo.
- A short write-up (`analysis/windows_blank_<date>.md`) summarizing findings per ETL.
- Updates to `docs/ACPI_STATUS.md` and `docs/WINDOWS_REPORT.md` once we confirm a half-panel control path.

## Open Questions
- Do we need additional Windows captures expressly covering “detached” vs “docked” states? If yes, plan how to trigger and record them using the same scripts.
- Can we automate wpaexporter (via PowerShell) to batch-process every ETL? If the exported CSVs are manageable, we can parse them back on Linux.
