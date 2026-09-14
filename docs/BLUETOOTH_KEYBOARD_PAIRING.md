# Pairing a ThinkPad Bluetooth TrackPoint Keyboard on Linux

This keyboard does not pair through the normal Linux path. The GNOME/KDE
Bluetooth panel will not show it, `bluetoothctl scan on` will not list it, and
`bluetoothctl pair <address>` answers `Device ... not available` **even while
the keyboard is sitting six inches away actively advertising**.

None of that is a bug in your machine. It is a consequence of how the keyboard
advertises. This document explains what is happening and how to work around it.

## Just pair the thing

```bash
x1fold-pair-keyboard.sh --watch
```

1. Hold the keyboard's **Bluetooth button** until its light changes — on this
   model that is a slow double-pulse.
2. When the script prints **PRESS ENTER ON THE NEW KEYBOARD**, do exactly that:
   **press Enter on the keyboard being paired**, not on the one you are typing
   on.

Step 2 is the whole ballgame. Read the next section before doing anything else.

Needs `sudo` (it reads raw HCI). Your existing keyboard stays connected
throughout. If nothing happens for a while, hold the button *longer* — see
[Reconnect mode vs pairing mode](#reconnect-mode-vs-pairing-mode).

## The step that wastes hours

Pairing completes **only when Enter is pressed on the keyboard itself.**

When pairing starts, the kernel emits:

```
hci0 E6:DE:D6:52:04:C2 User Confirm 000000 hint 1
```

That reads like a dialog on the computer waiting to be clicked. **It is not.**
Nothing on the computer can answer it:

- `bluetoothctl`'s agent cannot — including `NoInputNoOutput`, which is
  supposed to auto-accept.
- The desktop Bluetooth applet cannot. Under Sway it raises a "Connection
  request" notification that disappears on its own, leaving nothing to click.
- `btmgmt` run non-interactively cannot.

The keyboard is sitting in passkey entry waiting for a keystroke. If none
arrives it hangs up, and the trace shows:

```
Reason: Remote User Terminated Connection (0x13)
Pairing with ... failed. status 0x03 (Failed)
```

That failure is not a bad link, a wrong address, or a BlueZ problem. It means
nobody pressed Enter on the keyboard.

### I/O capability matters

Only `DisplayOnly` (`-c 0`) negotiates the method this keyboard accepts.

| Capability | Method negotiated | Result |
| --- | --- | --- |
| `-c 4` KeyboardDisplay | Numeric comparison | `User Confirm`, nothing can answer → `0x03` |
| `-c 3` NoInputNoOutput | Just Works | Keyboard refuses; it wants MITM protection → `0x03` |
| **`-c 0` DisplayOnly** | **Passkey entry** | **Works — press Enter on the keyboard** |

Override with `X1FOLD_PAIR_CAP` if a different unit needs something else.

To see what the keyboard is currently doing without pairing:

```bash
x1fold-pair-keyboard.sh --check
```

```
E6:DE:D6:52:04:C2  X1FKeyboard    flags=0x06 RSSI=-59  ==> PAIRING MODE, ready to pair
```

## Never do this again: back up the pairing keys

Pairing is only hard because the machine has no key for the keyboard. The keys
live in `/var/lib/bluetooth/<adapter>/<device>/info`, so keep a copy and a
reinstall needs no pairing at all — no buttons, no passkeys, no pairing mode.

```bash
# Before wiping the machine
x1fold-pair-keyboard --backup-bonds ~/kbd-bonds.tar.gz

# After reimaging, then just switch the keyboards on
x1fold-pair-keyboard --restore-bonds ~/kbd-bonds.tar.gz
```

Constraints worth knowing:

- **Same adapter only.** The keys are bound to the controller's address, and
  the keyboard stored *our* identity when it bonded. Restoring onto different
  Bluetooth hardware produces records the keyboard rejects. `--restore-bonds`
  compares the adapter address and refuses rather than leaving you with dead
  bonds that look valid.
- **The backup is a secret.** It contains `LongTermKey` and
  `IdentityResolvingKey` — anyone holding it can impersonate your machine to
  those keyboards. It is written mode `0600`; keep it that way, and do not
  commit it to a repository.
- Restoring stops and restarts `bluetooth.service`.

Put the backup wherever your dotfiles/secrets already go. This is the single
highest-value thing in this document: it converts an afternoon into one command.

## Running it as a service

The installer drops an on-demand unit. Nothing is enabled — pairing is a
deliberate act, and a service that retries forever is how you get 8,000
restarts in a journal.

```bash
sudo systemctl start x1fold-pair-keyboard      # watches for 10 minutes
journalctl -fu x1fold-pair-keyboard            # watch it work
```

Hold the keyboard's Bluetooth button, then press Enter on that keyboard when
the journal asks.

## Why the normal tools fail

### Reconnect mode vs pairing mode

Every BLE advertisement carries a **Flags** byte:

| Bit | Meaning |
| --- | --- |
| `0x01` | LE Limited Discoverable |
| `0x02` | LE General Discoverable |
| `0x04` | BR/EDR Not Supported |

This keyboard advertises in two completely different states, and they look
nearly identical from the outside:

| Flags | State | What happens |
| --- | --- | --- |
| `0x04` | **Reconnect only** | Advertising so a host it is *already bonded to* can reconnect. Neither discoverable bit is set. |
| `0x06` | **Pairing mode** | `0x02` is set. A new host may bond. |

**BlueZ discards advertisements with no discoverable bit before they become
D-Bus device objects.** So in the `0x04` state the daemon never creates a
`Device` for it, and everything downstream — the GUI, `bluetoothctl devices`,
`bluetoothctl pair`, `bluetoothctl info` — reports it as nonexistent. The
kernel is receiving the packets perfectly; you simply cannot see them through
BlueZ.

Observed here: a five-minute scan catalogued **195 distinct Bluetooth devices**
and did not include the keyboard, while raw HCI showed it advertising the whole
time at RSSI -67.

If you connect anyway (possible via the kernel, see below) while it is in
`0x04`, the keyboard accepts the link, finds you have no key it recognises, and
drops you:

```
Status: Connection Failed to be Established (0x3e)
Handle: 2049 (LE-ACL) Address: E6:DE:D6:52:03:C2 (Static)
Features[0/0][8]: 00 00 00 00 00 00 00 00
```

So a keyboard that is already bonded to some other computer, phone or tablet
**cannot be paired** until you clear that bond by holding the Bluetooth button
long enough to reach real pairing mode.

### The advertising window is short

In pairing mode the keyboard advertises for well under a minute and then goes
quiet. That is too short for the usual sequence:

1. start a scan
2. wait for BlueZ to build a `Device` object
3. call `Pair()`

By step 3 the keyboard has often stopped. This produces the maddening result of
`--check` reporting `PAIRING MODE` and `bluetoothctl pair` replying
`not available` seconds later.

`--watch` avoids the race entirely: it is *already listening* on raw HCI and
pairs through the kernel management interface (`btmgmt`), which puts the
address on the controller's accept list and connects on the first advertisement
received — no scan cycle, no D-Bus object required.

### Each host slot has its own address

The keyboard is multi-host. Each slot has a **different Bluetooth address and a
different advertised name**:

| Slot | Address | Name | Observed flags |
| --- | --- | --- | --- |
| previously bonded | `E6:DE:D6:52:03:C2` | `ThinkPad Bl…` | `0x04` |
| free slot | `E6:DE:D6:52:**04**:C2` | `X1FKeyboard` | `0x06` |

Note the single-octet difference. Holding the Bluetooth button moves between
slots, so **the address changes** — do not assume the address you saw earlier is
still the right one. `--watch` does not care; it matches on advertised name and
signal strength rather than a fixed address.

## Two keyboards at once

The X1 Fold's Intel AX211 holds both keyboards simultaneously. This is verified,
not theoretical — both appear as connected in the same management trace:

```
hci0 C6:45:40:B5:83:91 type LE Random connected
hci0 E6:DE:D6:52:04:C2 type LE Random connected
```

Nothing in `x1fold-pair-keyboard.sh` disconnects an already-connected keyboard.
`--watch` and `btmgmt pair` target one address and have no disconnect path.

### Telling two identical units apart

Two units of the same model produce input nodes with **identical names**, and
`Phys` is the *adapter's* address, so it is identical too. Only `uniq` carries
the keyboard's own address, and event numbers shift across reconnects.

```bash
x1fold-pair-keyboard.sh --list
```

```
C6:45:40:B5:83:91  connected   ThinkPad Bluetooth TrackPoint Keyboard
    /dev/input/event15  ThinkPad Bluetooth TrackPoint Keyboard
    /dev/input/event16  ThinkPad Bluetooth TrackPoint Keyboard Mouse
    /dev/input/event17  ThinkPad Bluetooth TrackPoint Keyboard
    /dev/input/event18  ThinkPad Bluetooth TrackPoint Keyboard Touchpad
```

Use `uniq` (not the name, not the event number) for per-keyboard `keyd` or
udev `hwdb` rules.

## Safety: it will not pair someone else's keyboard

Another keyboard in pairing mode nearby would otherwise be a valid target, so
`--watch` only auto-pairs devices whose advertised name matches this hardware
and whose signal is close:

| Variable | Default | Meaning |
| --- | --- | --- |
| `X1FOLD_KBD_NAME_RE` | `ThinkPad\|TrackPoint\|X1F` | Name must match |
| `X1FOLD_KBD_MIN_RSSI` | `-75` | Must be at least this strong |

Passing an explicit address bypasses both:

```bash
x1fold-pair-keyboard.sh --watch E6:DE:D6:52:04:C2
```

## Manual diagnosis

Watch raw advertisements yourself. `btmon` only *observes*; a scan must be
running for the controller to receive anything:

```bash
sudo btmon > /tmp/btmon.log &
bluetoothctl --timeout 20 scan on
grep -B20 'Appearance: Keyboard' /tmp/btmon.log | grep -E 'Address:|Flags:|RSSI:|Name'
```

Pair by address through the kernel, bypassing BlueZ discovery entirely:

```bash
sudo btmgmt --index 0 pair -t 2 -c 4 <ADDRESS>    # -t 2 = LE random
```

If that returns `Busy (0x0a)`, a previous attempt is still pending:

```bash
sudo btmgmt --index 0 cancelpair -t 2 <ADDRESS>
```

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| **`status 0x03 (Failed)` after it connects** | **Nobody pressed Enter on the keyboard** | **Press Enter on the NEW keyboard when prompted** |
| `Remote User Terminated Connection (0x13)` | Same — the keyboard gave up waiting | Same |
| "Connection request" notification vanishes | Sway has no agent that can hold the dialog | Ignore it; the answer is Enter on the keyboard, not a click |
| `Device ... not available` | Advertising with flags `0x04`, filtered by BlueZ | Hold the Bluetooth button until it reaches pairing mode; use `--watch` |
| `--check` says `reconnect only` | Still bonded to another host | Hold the button longer to clear the bond |
| `--check` says nothing heard | Not advertising; window expired | Press the button again; `--watch` waits for you |
| `Connect Failed (0x04)` / `0x3e` | Connected in reconnect mode, keyboard dropped us | Same as above — it needs real pairing mode |
| `Busy (0x0a)` | Earlier pairing still pending in kernel | `btmgmt cancelpair`, or just rerun `--watch` |
| Paired but no keystrokes | Bonded but not connected | `bluetoothctl connect <addr>` |
| Works now, dead after reboot | Bonded but not trusted | `bluetoothctl trust <addr>` (`--watch` does this automatically) |

## Doing it entirely by hand

If the script is unavailable, this is the whole procedure:

```bash
# 1. Find the address while holding the keyboard's Bluetooth button.
sudo btmon > /tmp/b.log &
bluetoothctl --timeout 20 scan on
grep -B20 'Appearance: Keyboard' /tmp/b.log | grep -E 'Address:|Flags:|Name'
#    Flags must be 0x06. 0x04 means hold the button longer.

# 2. Pair by address. BlueZ discovery is not involved.
sudo btmgmt --index 0 pair -t 2 -c 0 <ADDRESS>

# 3. When it prints "User Confirm", PRESS ENTER ON THE NEW KEYBOARD.

# 4. Trust it so it reconnects after a reboot.
bluetoothctl trust <ADDRESS>
```

## Wired fallback

The keyboard works over USB with no pairing at all. Plugged in it enumerates as
`17ef:6142` (`Primax Electronics Ltd.`) with keyboard, TrackPoint and touchpad
all functional. Note the different product ID: `613E` over Bluetooth, `6142`
over USB — `x1fold-fnctl` already handles both.

Useful while debugging, and a genuine fallback if a unit's radio is bonded to a
host you no longer have access to.
