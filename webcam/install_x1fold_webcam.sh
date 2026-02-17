#!/usr/bin/env bash
# Repo source: x1fold/webcam/install_x1fold_webcam.sh
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: install_x1fold_webcam.sh [--no-dkms] [--kernel-base <X.Y.Z>]

Installs the X1 Fold webcam helper tooling into a live system:
  - /usr/local/bin/{x1fold-webcam-on,x1fold-webcam-off}
  - /etc/modprobe.d/99-x1fold-disable-ipu6.conf
  - /usr/lib/systemd/system-sleep/53-x1fold-webcam-off

By default, also builds + installs a DKMS override for `ipu_bridge` that adds
OVTI5675 support (required on the tested kernel).

Options:
  --no-dkms              Skip the DKMS build/install step.
  --kernel-base X.Y.Z    Kernel base version to fetch ipu-bridge.c from
                         (defaults to uname -r, stripping Arch suffix).
EOF
}

orig_args=("$@")

do_dkms=1
kernel_base=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-dkms) do_dkms=0; shift ;;
    --kernel-base)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "error: --kernel-base requires an argument (X.Y.Z)" >&2
        usage
        exit 2
      fi
      kernel_base="$2"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  exec sudo -- "$0" "${orig_args[@]}"
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
x1fold_root="$repo_root"

install -Dm0755 "$x1fold_root/webcam/bin/x1fold-webcam-on" /usr/local/bin/x1fold-webcam-on
install -Dm0755 "$x1fold_root/webcam/bin/x1fold-webcam-off" /usr/local/bin/x1fold-webcam-off
install -Dm0755 "$x1fold_root/webcam/bin/x1fold-webcam-chrome-on" /usr/local/bin/x1fold-webcam-chrome-on
install -Dm0755 "$x1fold_root/webcam/bin/x1fold-webcam-chrome-off" /usr/local/bin/x1fold-webcam-chrome-off
install -Dm0644 "$x1fold_root/webcam/modprobe.d/99-x1fold-disable-ipu6.conf" /etc/modprobe.d/99-x1fold-disable-ipu6.conf
install -Dm0755 "$x1fold_root/webcam/systemd/system-sleep/53-x1fold-webcam-off" /usr/lib/systemd/system-sleep/53-x1fold-webcam-off

if [[ "$do_dkms" -eq 0 ]]; then
  echo "installed: x1fold webcam helpers (DKMS skipped)"
  exit 0
fi

if ! command -v dkms >/dev/null 2>&1; then
  echo "warning: dkms not found; skipping ipu-bridge OVTI5675 DKMS override" >&2
  echo "installed: x1fold webcam helpers" >&2
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "error: curl not found (needed to fetch upstream ipu-bridge.c); install curl or re-run with --no-dkms" >&2
  exit 2
fi

kver="$(uname -r)"
if [[ -z "$kernel_base" ]]; then
  kernel_base="${kver%%-*}"
fi

pkg_name="ipu-bridge-ovti5675"
pkg_ver="1"
src_dir="/usr/src/${pkg_name}-${pkg_ver}"

tmp="$(mktemp -t ipu-bridge.c.XXXXXX)"
trap 'rm -f "$tmp"' EXIT

url="https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/drivers/media/pci/intel/ipu-bridge.c?h=v${kernel_base}"
echo "fetching ipu-bridge.c from: $url" >&2
curl -fsSL "$url" -o "$tmp"

# Insert OVTI5675 support if missing.
if ! grep -q 'OVTI5675' "$tmp"; then
  if ! command -v perl >/dev/null 2>&1; then
    echo "error: perl not found (needed to patch ipu-bridge.c); install perl or re-run with --no-dkms" >&2
    exit 2
  fi

  perl -0777 -i -pe 's/(\\/\\* Omnivision OV2680 \\*\\/\\s*\\n\\s*IPU_SENSOR_CONFIG\\(\"OVTI2680\", 1, 331200000\\),\\s*\\n)/$1\\t\\/\\* Omnivision OV5675 \\*\\/\\n\\tIPU_SENSOR_CONFIG(\"OVTI5675\", 1, 450000000),\\n/s' "$tmp"

  if ! grep -q 'OVTI5675' "$tmp"; then
    echo "error: failed to patch ipu-bridge.c to add OVTI5675; upstream file format may have changed" >&2
    exit 2
  fi
fi

mkdir -p "$src_dir"
install -Dm0644 "$tmp" "$src_dir/ipu-bridge.c"

cat >"$src_dir/Makefile" <<'EOF'
obj-m += ipu-bridge.o
EOF

cat >"$src_dir/dkms.conf" <<'EOF'
PACKAGE_NAME="ipu-bridge-ovti5675"
PACKAGE_VERSION="1"

BUILT_MODULE_NAME[0]="ipu-bridge"
BUILT_MODULE_LOCATION[0]="."
DEST_MODULE_LOCATION[0]="/updates/dkms"

AUTOINSTALL="yes"

MAKE[0]="make -C /usr/lib/modules/${kernelver}/build M=${dkms_tree}/${PACKAGE_NAME}/${PACKAGE_VERSION}/build modules"
EOF

dkms remove -m "$pkg_name" -v "$pkg_ver" --all 2>/dev/null || true
dkms add -m "$pkg_name" -v "$pkg_ver"
dkms build -m "$pkg_name" -v "$pkg_ver" -k "$kver"
dkms install -m "$pkg_name" -v "$pkg_ver" -k "$kver"

depmod -a "$kver"

echo "installed: x1fold webcam helpers + ${pkg_name} DKMS override"
echo "note: reboot recommended to ensure the updated ipu_bridge is used cleanly"
