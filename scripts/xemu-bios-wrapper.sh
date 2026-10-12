#!/usr/bin/env sh
# Xemu 0.8.136 reads bootrom_path and hdd_path from xemu.toml but does not
# forward flashrom_path to QEMU in this AppImage build. Keep the source of
# truth in xemu.toml and supply the identical, read-only BIOS path at launch.
set -eu
exec /opt/xemu/AppRun "$@" -bios /xemu-firmware/Complex_4627.bin
