#!/bin/sh
#
# zbuduj_collectd.sh - collectd 5.12.0 dla nBoxow ADB 5800 (sh4, glibc 2.14.1),
# ta sama wersja i lacznie te same latki co pakiet collectd 5.12.0-2 w OpenWrt
# 19.07 (openwrt/packages, galaz openwrt-19.07, utils/collectd). Uruchamiac
# w kontenerze z sh4/Dockerfile, z katalogiem repo jako /work:
#
#   docker run --rm -u $(id -u):$(id -g) -v "$PWD":/work nbox-sh4:4.8.4 \
#       sh /work/sh4/collectd/zbuduj_collectd.sh
#
# Zrodla collectd-5.12.0.tar.bz2 pobiera sam (jesli ich nie ma) i sprawdza
# sha256; patches/ - trzy latki z pakietu OpenWrt.
#
# Latki: tylko te, ktore nie ruszaja configure.ac/Makefile.am (bez autoreconf):
# 140 FQDNLookup, 300 opoznienie pierwszego odczytu, 320 skok czasu z NTP po
# starcie - nBoxy startuja z zegarem 2000-01-01. iwinfo, rrdtool, modbus, olsrd,
# netlink nie sa tu budowane, a 700 (libcap) zbedna - sysroot nie ma libcap.
#
# Pluginy: jak na routerach 19.07 (cpu, interface, load, memory, network,
# uptime) bez rrdtool, iwinfo i ping, plus df, disk, table, exec, syslog.
# Wynik: sh4/collectd/inst (usr/sbin, usr/lib/collectd, usr/share/collectd;
# binarki obciete) - z niego zrob_ipk.sh sklada pakiet.

set -e

V=5.12.0
SRC=/work/sh4/collectd
URL=https://github.com/collectd/collectd/releases/download/collectd-$V/collectd-$V.tar.bz2
SHA256=5bae043042c19c31f77eb8464e56a01a5454e0b39fa07cf7ad0f1bfc9c3a09d6
B=$SRC/build-$V
DST=$SRC/inst
PATCHES="
140-fix-fqdnlookup.patch
300-delay-first-read-cycle.patch
320-reaction-to-ntp-time-change-at-boot.patch
"
PLUGINS="cpu df disk exec interface load memory network syslog table uptime"

[ -f "$SRC/collectd-$V.tar.bz2" ] || wget -q -O "$SRC/collectd-$V.tar.bz2" "$URL"
echo "$SHA256  $SRC/collectd-$V.tar.bz2" | sha256sum -c -

rm -rf "$B" "$DST"
mkdir -p "$B"
tar -xjf "$SRC/collectd-$V.tar.bz2" -C "$B" --strip-components=1
cd "$B"
for p in $PATCHES; do
    patch -p1 -s < "$SRC/patches/$p"
done

ENABLE=""
for m in $PLUGINS; do
    ENABLE="$ENABLE --enable-$m"
done

./configure --host=sh4-linux --build=x86_64-linux-gnu \
    --prefix=/usr --sysconfdir=/etc --localstatedir=/var \
    --disable-all-plugins $ENABLE \
    --disable-werror --disable-debug --enable-daemon \
    --with-nan-emulation --with-fp-layout=nothing \
    --with-libyajl=no --without-perl-bindings --without-libudev \
    --without-libgcrypt --without-libcap \
    CFLAGS="-Os -pipe" LDFLAGS="-lm" > configure.log 2>&1

make -j"$(nproc)" > make.log 2>&1
make install DESTDIR="$DST" > install.log 2>&1

P=$DST/usr
sh4-linux-strip "$P/sbin/collectd" "$P/sbin/collectdmon"
sh4-linux-strip --strip-unneeded "$P"/lib/collectd/*.so
rm -f "$P"/lib/collectd/*.la
rm -rf "$P/include" "$P/share/man" "$P/lib/pkgconfig" "$P"/lib/libcollectdclient* \
    "$P/bin" "$DST/etc" "$DST/var"

grep -A40 "Modules:" configure.log | grep -E "yes|no \(" | grep -vE "\bno \(disabled" || true
ls -l "$P/sbin" "$P/lib/collectd"
