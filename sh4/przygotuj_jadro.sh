#!/bin/sh
#
# przygotuj_jadro.sh - drzewo jadra 2.6.32.61_stm24_0217 gotowe do budowania
# modulow dla nBoxow ADB 5800 (GraterliaOS, STi7100). Uruchamiac w kontenerze
# z sh4/Dockerfile, z katalogiem repo zamontowanym jako /work:
#
#   docker run --rm -v "$PWD":/work nbox-sh4:4.8.4 sh /work/sh4/przygotuj_jadro.sh
#
# Sam klonuje do /work/build (jesli jeszcze nie ma):
#   linux.git    - https://github.com/Duckbox-Developers/linux-sh4-2.6.32.71
#                  (galaz stmicro, rewizja REV)
#   audioniek-bs - https://github.com/Audioniek/buildsystem (rewizja BS_REV)
# Konfiguracja: sh4/config-graterlia-2.6.32.61_stm24_0217 = zcat /proc/config.gz
# z nBoxa (md5 198db3da, ta sama na pieciu boxach, 2026-10-21).
#
# Rewizja i lista latek jak w buildsystemie Audionieka (make/linux-kernel-env.mk,
# KERNEL_STM=p0217_61; make/linux-kernel.mk, COMMON_PATCHES_24 +
# ADB_BOX_PATCHES_24, gcc 4.8.4 - bez remove_m4-nofpu-arg, bez POWER_VU_DES).
# Wynik: /work/build/linux-2.6.32.61_stm24_0217 po modules_prepare; moduly buduje sie
#   make -C /work/build/linux-2.6.32.61_stm24_0217 ARCH=sh CROSS_COMPILE=sh4-linux- M=$PWD modules

set -e

REV=b43f8252e9f72e5b205c8d622db3ac97736351fc
BS_REV=71d4a4a608e42dd1d54f34e1ca1024c34b92dbec
B=/work/build
CONFIG=/work/sh4/config-graterlia-2.6.32.61_stm24_0217
L=0217
DST=$B/linux-2.6.32.61_stm24_$L
PATCHES="
linux-sh4-makefile_stm24.patch
linux-stm-gpio-fix-build-CONFIG_BUG_$L.patch
linux-kbuild-generate-modules-builtin_stm24_$L.patch
linux-sh4-linuxdvb_stm24_$L.patch
linux-sh4-sound_stm24_$L.patch
linux-sh4-time_stm24_$L.patch
linux-sh4-init_mm_stm24_$L.patch
linux-sh4-copro_stm24_$L.patch
linux-sh4-strcpy_stm24_$L.patch
linux-sh4-ext23_as_ext4_stm24_$L.patch
linux-sh4-bpa2_procfs_stm24_$L.patch
linux-ftdi_sio.c_stm24_$L.patch
linux-sh4-lzma-fix_stm24_$L.patch
linux-tune_stm24.patch
linux-net_stm24.patch
linux-sh4-permit_gcc_command_line_sections_stm24.patch
linux-sh4-mmap_stm24.patch
linux-defined_is_deprecated_timeconst.pl_stm24_$L.patch
linux-sh4-fs-dev-no-warnings_stm24_$L.patch
linux-patch_swap_notify_core_support_stm24_$L.patch
linux-sh4-stx7100_fdma_fix_stm24_$L.patch
linux-sh4-sata_32bit_fix_stm24_$L.patch
linux-sh4-adb_box_setup_stm24_$L.patch
linux-usbwait123_stm24.patch
linux-sh4-ufs910_reboot_stm24_$L.patch
linux-sh4-i2c-st40-pio_stm24_$L.patch
linux-sh4-pcm_noise_fix_stm24_$L.patch
"
M="ARCH=sh CROSS_COMPILE=sh4-linux-"

mkdir -p "$B"
if [ ! -d "$B/linux.git" ]; then
    git clone -n -b stmicro https://github.com/Duckbox-Developers/linux-sh4-2.6.32.71.git "$B/linux.git"
fi
if [ ! -d "$B/audioniek-bs" ]; then
    git clone -n https://github.com/Audioniek/buildsystem.git "$B/audioniek-bs"
    git -C "$B/audioniek-bs" -c advice.detachedHead=false checkout -q "$BS_REV"
fi

rm -rf "$DST"
git -c advice.detachedHead=false clone -q "$B/linux.git" "$DST"
cd "$DST"
git checkout -q "$REV"

for p in $PATCHES; do
    f=
    for d in build-enigma2 build-all; do
        [ -f "$B/audioniek-bs/patches/$d/$p" ] && { f="$B/audioniek-bs/patches/$d/$p"; break; }
    done
    [ -n "$f" ] || { echo "BRAK latki $p"; exit 1; }
    echo "latka $p"
    patch -p1 -s -i "$f"
done

cp "$CONFIG" .config
yes "" | make $M oldconfig > "$B/oldconfig.log" 2>&1
if ! cmp -s .config "$CONFIG"; then
    echo "UWAGA: oldconfig zmienil .config:"
    diff "$CONFIG" .config | grep '^[<>] [A-Z#]' | head -20
fi
make $M modules_prepare > "$B/modules_prepare.log" 2>&1
echo "kernelrelease: $(make -s $M kernelrelease)"
