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

Then hold the keyboard's **Bluetooth button** until its light changes. That is
all. The watcher pairs it automatically the instant it advertises, and your
existing keyboard stays connected the whole time.

Needs `sudo` (it reads raw HCI). If it has been running a while and nothing has
happened, hold the button *longer* — see
[Reconnect mode vs pairing mode](#reconnect-mode-vs-pairing-mode).

To see what the keyboard is currently doing without pairing:

```bash
x1fold-pair-keyboard.sh --check
```

```
E6:DE:D6:52:04:C2  X1FKeyboard    flags=0x06 RSSI=-59  ==> PAIRING MODE, ready to pair
```

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
| `Device ... not available` | Advertising with flags `0x04`, filtered by BlueZ | Hold the Bluetooth button until it reaches pairing mode; use `--watch` |
| `--check` says `reconnect only` | Still bonded to another host | Hold the button longer to clear the bond |
| `--check` says nothing heard | Not advertising; window expired | Press the button again; `--watch` waits for you |
| `Connect Failed (0x04)` / `0x3e` | Connected in reconnect mode, keyboard dropped us | Same as above — it needs real pairing mode |
| `Busy (0x0a)` | Earlier pairing still pending in kernel | `btmgmt cancelpair`, or just rerun `--watch` |
| Paired but no keystrokes | Bonded but not connected | `bluetoothctl connect <addr>` |

## Wired fallback

The keyboard works over USB with no pairing at all. Plugged in it enumerates as
`17ef:6142` (`Primax Electronics Ltd.`) with keyboard, TrackPoint and touchpad
all functional. Note the different product ID: `613E` over Bluetooth, `6142`
over USB — `x1fold-fnctl` already handles both.

Useful while debugging, and a genuine fallback if a unit's radio is bonded to a
host you no longer have access to.
