# X1 Fold 16 webcam (Intel IPU6 + IVSC + OVTI5675)

This ThinkPad is **not** a USB/UVC webcam. The internal camera is an **Intel IPU6** pipeline with an **IVSC/VSC** bridge and an **OVTI5675** sensor.

On Arch Linux (kernel `6.18.x` tested), the missing piece was `ipu_bridge` not advertising `OVTI5675` (and its CSI-2 link frequency) to the media graph. This directory contains:

- Install + enable/disable scripts (`x1fold-webcam-on`, `x1fold-webcam-off`)
- Chrome bridge scripts (`x1fold-webcam-chrome-on`, `x1fold-webcam-chrome-off`)
- A DKMS helper that builds an `ipu-bridge` override with `OVTI5675` enabled
- A modprobe policy file to keep the camera stack off-by-default

## Packages (Arch)

You need the kernel headers and DKMS tooling:

- `linux-headers` (or headers for your kernel)
- `dkms`
- `v4l-utils` (for `v4l2-ctl`/`media-ctl`)
- `libcamera` + `libcamera-tools` (for `cam`)

For IPU6 userspace + psys (AUR packages used on this machine):

- `intel-ipu6-dkms-git`
- `intel-ipu6-camera-bin`
- `intel-ipu6-camera-hal-git`
- `icamerasrc-git` (optional if you only use libcamera)

## Install

From the repo root:

```bash
sudo ./webcam/install_x1fold_webcam.sh
```

Or from this directory:

```bash
sudo ./install_x1fold_webcam.sh
```

That installs:

- `/usr/local/bin/x1fold-webcam-on`
- `/usr/local/bin/x1fold-webcam-off`
- `/usr/local/bin/x1fold-webcam-chrome-on`
- `/usr/local/bin/x1fold-webcam-chrome-off`
- `/etc/modprobe.d/99-x1fold-disable-ipu6.conf`
- `/usr/lib/systemd/system-sleep/53-x1fold-webcam-off`
- DKMS override module: `ipu-bridge-ovti5675` (builds `ipu-bridge.ko`)

Reboot after installing the DKMS module so the new `ipu_bridge` is used cleanly.

## Use

Enable the camera stack (bridge on by default for Chrome):

```bash
sudo x1fold-webcam-on
```

`x1fold-webcam-on` also forces the Intel VSC device to stay awake while the camera is enabled (`/sys/devices/platform/intel_vsc/power/control=on`). `x1fold-webcam-off` returns it to `auto`.
It also starts a V4L2 bridge (`/dev/video42`, label `libcamera`) for Chrome unless you pass `--no-bridge`.

List cameras:

```bash
cam --list
```

Capture a single frame (PPM):

```bash
cam --camera 1 --capture=1 --file=/tmp/webcam-#.ppm
```

Disable again:

```bash
sudo x1fold-webcam-off
```

Note: unloading `intel_ipu6` is not reliable on this platform; `x1fold-webcam-off` intentionally avoids removing the core helper modules once they’ve been used. For a full reset back to “off by default”, reboot.

If `x1fold-webcam-on` shows `Device or resource busy` for `intel_ipu6_isys`/`intel_ipu6_psys`, or `cam --list` still shows no cameras, reboot and try again (the IPU6 stack does not always recover cleanly after partial unloads).

## Chrome (V4L2 bridge)

Chrome expects a V4L2 `/dev/video*` device. The bridge is now started by default with `x1fold-webcam-on`.
To disable it:

```bash
sudo x1fold-webcam-on --no-bridge
```

Defaults for the bridge:
- device: `/dev/video42`
- label: `libcamera`
- size: `2584x1944@30fps`

Override via env vars:

```bash
DEVICE_NUM=42 WIDTH=2584 HEIGHT=1944 FPS=30 LABEL=libcamera sudo x1fold-webcam-on
```

## Expected kernel signals (sanity check)

When working, `dmesg` should include:

- `Found supported sensor OVTI5675:00`
- `Connected 1 cameras`

And `media-ctl -d /dev/media0 -p` should show an `ov5675` sensor entity linked to `Intel IVSC CSI`, linked to an `Intel IPU6 CSI2` sink.

If you see `ov5675 ... no link frequency 450000000 supported`, you likely unloaded the bridge after the graph was created. Reboot and re-enable with `sudo x1fold-webcam-on`.

If you see `vsc-tp ... wakeup firmware failed ret: -110` or `ivsc_csi ... mei_cldev_enable failed`, the IVSC firmware is wedged; reboot is the reliable recovery.
