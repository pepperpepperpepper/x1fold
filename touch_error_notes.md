# Touch / Pen resume flakiness notes (WACF2200)

These are field notes for intermittent “touchscreen dead for minutes after suspend” issues on the ThinkPad X1 Fold.

## Symptoms

- After waking from **suspend (s2idle)**, the touchscreen/pen sometimes doesn’t work for a while.
- It can “come back” later without action.

## What we’ve seen in logs

Device:

- Wacom over I²C HID: `i2c-WACF2200:00` (Wacom `056A:52BA`)

Kernel error signatures (I²C/HID comms problems):

- `i2c_hid_acpi i2c-WACF2200:00: failed to get a report from device: -121`
- `i2c_hid_acpi i2c-WACF2200:00: failed to set a report to device: -121`
- `i2c_hid_acpi i2c-WACF2200:00: failed to reset device: -121`
- `i2c_hid_acpi i2c-WACF2200:00: failed to change power setting.`

Example timestamps from one boot (2026-02-04):

- `19:13:38` reset/power-setting failures (`-121`), then device re-enumerates ~2s later
- `19:20:40`, `19:33:03`, `19:33:22`, `21:55:53` “failed to get a report” (`-121`)
- `21:38:31` reset/power-setting failures (`-121`), then device re-enumerates ~1s later

User-session / compositor-facing symptoms:

- `x1fold-halfblank-ui` can log:
  - `sway_touch_map_reset_failed` with `no matching x1fold touch inputs`
  - `sway_touch_map_reset_failed` with `failed to read sway inputs`
  This means: at that moment, Sway’s `get_inputs` didn’t list the internal Wacom touch/pen devices (or Sway input query failed).

Halfblank daemon symptoms:

- `x1fold_halfblankd.py: no hidraw candidates found (need WACF2200 / 056a:52ba?)`
- `enforce_check_error` timeouts (`TimeoutExpired: timeout_s=8.0`) sometimes occur right after `PM: suspend exit`

## Quick recovery (when touch is dead)

1. Rebind the Wacom I²C HID device:

```bash
sudo x1fold-wacom-reset reset
```

2. If touch is present but mapping/state seems wrong under Sway, restart the UI helper:

```bash
systemctl --user restart x1fold-halfblank-ui.service
```

One-liner:

```bash
sudo x1fold-wacom-reset reset && systemctl --user restart x1fold-halfblank-ui.service
```

## Docked mode: touch offset / wrong mapping (Sway crop)

Symptom:

- In **docked/half** mode (Sway `x1fold_halfblank` crop active), touch can be systematically offset (e.g. taps land ~1 inch away).

What we found:

- `x1fold_halfblank_ui.py` chooses between:
  - `map_from_region` (needed when the digitizer reports **full-range** coords while the output is cropped), and
  - identity mapping (needed when the digitizer is truly in **half** mode and its coords already match the cropped output).
- If `/run/x1fold-halfblank/state.json` is stale or wrong about `digitizer_observed` / `status.i2c_query.mode`, the UI helper can apply the wrong mapping and touch will feel offset.

Quick recovery:

```bash
sudo systemctl restart x1fold-halfblankd.service
systemctl --user restart x1fold-halfblank-ui.service
```

Sanity check (expected to match dock policy):

```bash
sudo x1fold_mode.py status --i2c-query | jq '{mode, mode_source, i2c: .i2c_query}'
cat /run/x1fold-halfblank/state.json | jq '{desired, digitizer_expected, digitizer_observed, i2c: .status.i2c_query}'
```

## “Protection” / mitigation

- Prefer **hibernate** over suspend for “reliability-first” scenarios; the flakiness correlates with **s2idle suspend/resume**.
- Keep a non-touch input path handy (TrackPoint/mouse/keyboard) so you can run the recovery quickly.

## What to capture next time (so we can root-cause)

When touch is broken, note the wall-clock time, then collect these:

1. Does Sway see the internal devices?

```bash
swaymsg -t get_inputs | rg -n "056A|Wacom|WACF2200" || true
```

2. Kernel log slice around the failure (replace times):

```bash
journalctl -b -k --since "YYYY-MM-DD HH:MM:SS" --until "YYYY-MM-DD HH:MM:SS" \
  | rg -n "PM: suspend|WACF2200|i2c_hid_acpi|\\-121|wacom" || true
```

3. User-session log slice (replace times):

```bash
journalctl --user -b -u x1fold-halfblank-ui.service --since "YYYY-MM-DD HH:MM:SS" --until "YYYY-MM-DD HH:MM:SS" --no-pager \
  | rg -n "sway_touch_map_.*failed|failed to read sway inputs|no matching x1fold touch inputs" || true
```

4. Halfblank daemon log slice (replace times):

```bash
journalctl -b -u x1fold-halfblankd.service --since "YYYY-MM-DD HH:MM:SS" --until "YYYY-MM-DD HH:MM:SS" --no-pager \
  | rg -n "no hidraw candidates|TimeoutExpired|status_error|digitizer_observed" || true
```

## Working hypotheses (keep open)

- Primary: intermittent I²C transport errors (`-121`) on resume cause the digitizer to be unresponsive until it recovers/re-enumerates.
- Secondary: even if the kernel device comes back quickly, compositor/libinput may lag before exposing it in `swaymsg -t get_inputs`.
