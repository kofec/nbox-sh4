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
# Bez NAND= jadro nie widzi NAND (/proc/mtd pusty).
#
# ROOT (opcjonalnie) dopisuje do cmdline z u-boota "root=... rootfstype=ext3
# rootdelay=10 rw" - kernel bierze ostatnie root=, wiec wpis menu u-boota nie
# musi go znac. Pendrive jest sdb na boxie z dyskiem SATA, sda bez dysku. Takie
# jadro startuje tylko z tego pendrive'a - nie do NAND.
#
# NAND=ro: latki/graterlia_gen_nand.patch daje NAND jak w jadrze Graterlii
# (gen_nand, bank 1, CLE A17, ALE A16, nCE PIO 3.6, R/B PIO 4.5, ECC programowe,
# tablica zlych blokow w RAM-ie), a partycjom odbiera prawo zapisu (mask_flags).
# NAND=rw to samo z zapisem, bez ROOT startuje z NAND i z pendrive'a (root= podaje
# wpis u-boota). Drzewo w build/jadro-nand, reszta polecen bez zmian.
#
# NOR=ro (razem z NAND): latki/nbox_nor_ro.patch rejestruje kosc NOR z u-bootem
# jako mtd2 "nor" (4 MB, bez MTD_WRITEABLE, po NAND w late_initcall) i blokuje
# zapis/blokade OTP uzytkownika na partycjach tylko do odczytu. Do configu
# dochodzi MTD_CFI_INTELEXT (kosci ST M28W320 maja komendy Intela, Graterlia ma
# tylko AMDSTD), MTD_CFI_ADV_OPTIONS i MTD_OTP (ioctl OTPSELECT w mtdchar).
# Po starcie: dmesg pokaze kosc, cat /dev/mtd2 da zrzut u-boota i srodowiska,
# sh4/nor_otp odczyta fabryczny rejestr ochronny. Drzewo w build/jadro-nor.

set -e

M="ARCH=sh CROSS_COMPILE=sh4-linux-"
B=/work/build
DST=$B/jadro-printk
[ -z "$NAND" ] || DST=$B/jadro-nand
if [ -n "$NOR" ]; then
    [ "$NOR" = ro ] || { echo "NOR tylko ro"; exit 1; }
    [ -n "$NAND" ] || { echo "NOR=ro wymaga NAND"; exit 1; }
    DST=$B/jadro-nor
fi

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
if [ -n "$NAND" ]; then
    patch -p1 -i /work/sh4/latki/graterlia_gen_nand.patch
fi
if [ "$NAND" = ro ]; then
    sed -i '/^static struct mtd_partition iti_5800_nand_parts/,/^};/ s/^\(\s*\)\.name.*$/&\n\1.mask_flags   = MTD_WRITEABLE,/' arch/sh/boards/mach-mb442/setup.c
    [ "$(grep -c 'mask_flags   = MTD_WRITEABLE' arch/sh/boards/mach-mb442/setup.c)" = 2 ] || { echo "BRAK mask_flags"; exit 1; }
fi
if [ -n "$NOR" ]; then
    patch -p1 -i /work/sh4/latki/nbox_nor_ro.patch
    sed -i -e 's/^# CONFIG_MTD_CFI_INTELEXT is not set/CONFIG_MTD_CFI_INTELEXT=y/' \
           -e 's/^# CONFIG_MTD_CFI_ADV_OPTIONS is not set/CONFIG_MTD_CFI_ADV_OPTIONS=y/' .config
fi
yes "" | make $M oldconfig > "$B/jadro-printk-oldconfig.log" 2>&1
sed -i 's/^# CONFIG_PRINTK_TIME is not set/CONFIG_PRINTK_TIME=y/' .config
[ -z "$NOR" ] || sed -i 's/^# CONFIG_MTD_OTP is not set/CONFIG_MTD_OTP=y/' .config
yes "" | make $M oldconfig >> "$B/jadro-printk-oldconfig.log" 2>&1
grep -E "^CONFIG_PRINTK|^CONFIG_LOG_BUF|^CONFIG_CMDLINE" .config
if [ -n "$NOR" ]; then
    for o in MTD_CFI_INTELEXT MTD_CFI_ADV_OPTIONS MTD_OTP MTD_PHYSMAP MTD_CHAR; do
        grep -q "^CONFIG_$o=y" .config || { echo "BRAK CONFIG_$o=y"; exit 1; }
    done
fi
diff /work/sh4/config-graterlia-2.6.32.61_stm24_0217 .config | grep '^[<>] [A-Z#]' || true

make -j"$(nproc)" $M vmlinux > "$B/jadro-printk.log" 2>&1 || { tail -30 "$B/jadro-printk.log"; exit 1; }
# naglowek uImage dopisuje mkimage_sh4.py - mkimage w kontenerze nie ma,
# make uImage zostawia sam vmlinux.bin.gz
make $M uImage >> "$B/jadro-printk.log" 2>&1
echo "kernelrelease: $(make -s $M kernelrelease)"
sh4-linux-size vmlinux | tail -1
ls -l arch/sh/boot/vmlinux.bin.gz
