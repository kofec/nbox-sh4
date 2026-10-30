#!/usr/bin/env python3
"""Naglowek uImage (legacy U-Boot) dla jadra nBoxa ADB 5800 bez mkimage.

    python3 mkimage_sh4.py vmlinux.bin.gz uImage

Wartosci jak w /boot/uImage.gz z Graterlia_OS_ADB5800xx_rootfs_gui.tar.gz:
load 0x84001000, entry 0x84002000, Linux / SuperH / kernel / gzip,
nazwa "Linux-2.6.32.61_stm24_0217".
"""
import struct
import sys
import time
import zlib

MAGIC = 0x27051956
LOAD = 0x84001000
ENTRY = 0x84002000
OS_LINUX, ARCH_SH, TYPE_KERNEL, COMP_GZIP = 5, 9, 2, 1
NAME = b"Linux-2.6.32.61_stm24_0217"


def naglowek(dane, hcrc=0):
    return struct.pack(">7I4B32s", MAGIC, hcrc, int(time.time()), len(dane),
                       LOAD, ENTRY, zlib.crc32(dane) & 0xffffffff,
                       OS_LINUX, ARCH_SH, TYPE_KERNEL, COMP_GZIP, NAME)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    dane = open(sys.argv[1], "rb").read()
    h = naglowek(dane)
    h = h[:4] + struct.pack(">I", zlib.crc32(h) & 0xffffffff) + h[8:]
    with open(sys.argv[2], "wb") as f:
        f.write(h + dane)
    print("%s: %d B (dane %d B, dcrc %08x)" % (sys.argv[2], len(h) + len(dane),
                                             len(dane), zlib.crc32(dane) & 0xffffffff))


if __name__ == "__main__":
    main()
