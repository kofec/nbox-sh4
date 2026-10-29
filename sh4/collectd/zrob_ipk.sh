#!/bin/sh
#
# zrob_ipk.sh - pakiet collectd-nbox_<wersja>_sh4.ipk dla opkg 0.2.4 na
# GraterliaOS (format ar: debian-binary, control.tar.gz, data.tar.gz, wlasciciel
# root). Po zbuduj_collectd.sh, w tym samym kontenerze:
#
#   docker run --rm -u $(id -u):$(id -g) -v "$PWD":/work nbox-sh4:4.8.4 \
#       sh /work/sh4/collectd/zrob_ipk.sh
#
# Pliki pakietu z sh4/collectd/pakiet (CONTROL/ i etc/), binarki z
# sh4/collectd/inst. Wynik: sh4/collectd/*.ipk.
# Instalacja na boxie: opkg install /tmp/collectd-nbox_*.ipk, potem Hostname
# (i Server, gdy router nie jest 192.168.1.1) w /etc/collectd.conf i
# /etc/init.d/collectd start.

set -e

SRC=/work/sh4/collectd
PKG=$SRC/pakiet
T=$SRC/ipk-tmp
V=$(sed -n 's/^Version: //p' "$PKG/CONTROL/control")
OUT=$SRC/collectd-nbox_${V}_sh4.ipk

rm -rf "$T" "$OUT"
mkdir -p "$T/data/usr/sbin" "$T/data/usr/lib/collectd" \
    "$T/data/usr/share/collectd" "$T/control"

cp "$SRC/inst/usr/sbin/collectd" "$T/data/usr/sbin/"
cp "$SRC"/inst/usr/lib/collectd/*.so "$T/data/usr/lib/collectd/"
cp "$SRC/inst/usr/share/collectd/types.db" "$T/data/usr/share/collectd/"
cp -r "$PKG/etc" "$T/data/"
chmod 755 "$T/data/etc/init.d/collectd" "$T/data/usr/sbin/collectd"
chmod 644 "$T/data/etc/collectd.conf"

cp "$PKG"/CONTROL/* "$T/control/"
chmod 755 "$T/control/postinst" "$T/control/prerm"

# Rozmiar rozpakowany - opkg pokazuje go w opkg info
R=$(du -sk "$T/data" | cut -f1)
echo "Installed-Size: $R" >> "$T/control/control"

TARO="--owner=0 --group=0 --numeric-owner"
(cd "$T/data" && tar $TARO -czf ../data.tar.gz .)
(cd "$T/control" && tar $TARO -czf ../control.tar.gz .)
echo 2.0 > "$T/debian-binary"
(cd "$T" && ar rc "$OUT" debian-binary control.tar.gz data.tar.gz)
rm -rf "$T"

ls -l "$OUT"
md5sum "$OUT"
