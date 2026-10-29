#!/bin/sh
# mount_hdd.sh - montowanie /hdd na nBoxie, gdy dysk po starcie nie odpowiada.
# Na boxie /root/mount_hdd.sh, wolany w tle z /etc/rc.local:
#   /root/mount_hdd.sh &
# Wymaga wpisu /hdd w /etc/fstab i dysku na /dev/sda.
#
# Po starcie /dev/sda1 bywa w stanie, w ktorym dysk sie kreci (hdparm -C mowi
# "active/idle"), ale nie odpowiada na odczyt partycji - kazdy mount konczy sie
# "No such device or address", a /proc/diskstats pokazuje zero operacji.
# Dysk (Seagate 500 GB, ~54 tys. h pracy) potrzebowal na dojscie do gotowosci
# wyraznie wiecej niz minuta: petla w rc.local poddawala sie po 108 s, a ten sam
# mount udawal sie za pierwszym razem w 17. minucie po starcie. Cykl standby
# (hdparm -y) zostaje jako ostatnia deska ratunku - raz zbiegl sie z koncem tego
# stanu, ale nie ma dowodu, ze to on go przerwal.
#
# Limit: 5 cykli po 5 prob co 15 s, czyli ok. 7 minut. Rzadziej niz co 2 s,
# bo dysk i tak nie odpowiada - nie ma po co go dobijac. Slad w /tmp/mount_hdd.log.
LOG=/tmp/mount_hdd.log
up() { cut -d. -f1 /proc/uptime; }

c=0
while ! mountpoint -q /hdd && [ $c -lt 5 ]; do
    n=0
    while ! mountpoint -q /hdd && [ $n -lt 5 ]; do
        mount /hdd 2>>$LOG || echo "$(up) proba $n" >>$LOG
        sleep 15
        n=$((n + 1))
    done
    if ! mountpoint -q /hdd; then
        echo "$(up) cykl standby $c" >>$LOG
        # -S 60 z rc.local mogl sie nie ustawic, bo dysk wtedy nie odpowiadal
        /sbin/hdparm -y /dev/sda >>$LOG 2>&1
        sleep 10
        /sbin/hdparm -S 60 /dev/sda >>$LOG 2>&1
    fi
    c=$((c + 1))
done

if mountpoint -q /hdd; then
    echo "$(up) /hdd zamontowany po $c cyklach" >>$LOG
    # -S 60 z rc.local wykonuje sie, gdy dysk jeszcze nie odpowiada,
    # wiec licznik bezczynnosci mogl sie nie ustawic. Bez niego dysk kreci sie
    # bez konca i grzeje (bylo 56 C i SMART 190 FAILING_NOW).
    /sbin/hdparm -S 60 /dev/sda >>$LOG 2>&1
else
    echo "$(up) /hdd NIE zamontowany, poddaje sie" >>$LOG
fi
