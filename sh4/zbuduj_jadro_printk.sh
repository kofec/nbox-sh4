#!/bin/sh
#
# zbuduj_jadro_printk.sh - jadro GraterliaOS 2.6.32.61_stm24_0217 z wlaczonym
# printk (dmesg) dla nBoxow ADB 5800, do startu z pendrive'a (/boot/uImage).
# Uruchamiac w kontenerze z sh4/Dockerfile, po przygotuj_jadro.sh, z katalogu repo:
#
#   docker run --rm -v "$PWD":/work -e ROOT=/dev/sdb1 nbox-sh4:4.8.4 sh /work/sh4/zbuduj_jadro_printk.sh
#   python3 sh4/mkimage_sh4.py build/jadro-printk/arch/sh/boot/vmlinux.bin.gz uImage
#
# Zmiany wobec konfiguracji Graterlii: PRINTK=y, PRINTK_TIME=y, bufor 64 KB.
# Eksporty jadra to nadzbior Graterlii (dochodza printk, vprintk,
# printk_ratelimit, printk_timed_ratelimit), MODVERSIONS wylaczone, vermagic
# ten sam - moduly z obrazu laduja sie bez przebudowy.
#
# Plik plyty z latki Audionieka (adb_box_setup) rozni sie od jadra Graterlii;
# latki/graterlia_zgodnosc.patch cofa trzy roznice:
# - podmiana cmdline "root=/dev/mtdblock0 ... jffs2" na UBI (Graterlia jej nie ma),
# - NOR z u-bootem jako mtd0-2 (w Graterlii mtd0 = rootfs, mtd1 = kernel;
#   skrypty Graterlii piszace do /dev/mtd0 skasowalyby u-boota),
# - BPA2: LMI_VID 56 MB, LMI_SYS 28 MB z bootmem (Audioniek 44 MB / 32 MB stale).
# NAND tego jadra nie widzi (/proc/mtd pusty): plik plyty konfiguruje
# stm_nand_emi, a w configu Graterlii MTD_NAND_STM_EMI jest wylaczone.
#
# ROOT (opcjonalnie) dopisuje do cmdline z u-boota "root=... rootfstype=ext3
# rootdelay=10 rw" - kernel bierze ostatnie root=, wiec wpis menu u-boota nie
# musi go znac. Pendrive jest sdb na boxie z dyskiem SATA, sda bez dysku. Takie
# jadro startuje tylko z tego pendrive'a - nie do NAND.

set -e

M="ARCH=sh CROSS_COMPILE=sh4-linux-"
B=/work/build
DST=$B/jadro-printk

[ -d "$B/linux-2.6.32.61_stm24_0217" ] || { echo "BRAK drzewa - najpierw przygotuj_jadro.sh"; exit 1; }
# CONFIG_EXTRA_FIRMWARE_DIR="../integrated_firmware/" - wzgledem drzewa jadra
ln -sfn audioniek-bs/integrated_firmware "$B/integrated_firmware"
[ -e "$B/integrated_firmware/fdma_STx7100_0.elf" ] || { echo "BRAK integrated_firmware"; exit 1; }

rm -rf "$DST"
cp -a "$B/linux-2.6.32.61_stm24_0217" "$DST"
cd "$DST"
patch -p1 -i /work/sh4/latki/graterlia_zgodnosc.patch
sed -i -e 's/^# CONFIG_PRINTK is not set/CONFIG_PRINTK=y/' \
       -e 's/^CONFIG_LOG_BUF_SHIFT=.*/CONFIG_LOG_BUF_SHIFT=16/' .config
if [ -n "$ROOT" ]; then
    sed -i "s|^# CONFIG_CMDLINE_EXTEND is not set|CONFIG_CMDLINE_EXTEND=y\nCONFIG_CMDLINE=\"root=$ROOT rootfstype=ext3 rootdelay=10 rw\"|" .config
fi
yes "" | make $M oldconfig > "$B/jadro-printk-oldconfig.log" 2>&1
sed -i 's/^# CONFIG_PRINTK_TIME is not set/CONFIG_PRINTK_TIME=y/' .config
yes "" | make $M oldconfig >> "$B/jadro-printk-oldconfig.log" 2>&1
grep -E "^CONFIG_PRINTK|^CONFIG_LOG_BUF|^CONFIG_CMDLINE" .config
diff /work/sh4/config-graterlia-2.6.32.61_stm24_0217 .config | grep '^[<>] [A-Z#]' || true

make -j"$(nproc)" $M vmlinux > "$B/jadro-printk.log" 2>&1 || { tail -30 "$B/jadro-printk.log"; exit 1; }
# naglowek uImage dopisuje mkimage_sh4.py - mkimage w kontenerze nie ma,
# make uImage zostawia sam vmlinux.bin.gz
make $M uImage >> "$B/jadro-printk.log" 2>&1
echo "kernelrelease: $(make -s $M kernelrelease)"
sh4-linux-size vmlinux | tail -1
ls -l arch/sh/boot/vmlinux.bin.gz
