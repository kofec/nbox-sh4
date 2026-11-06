#!/bin/sh
#
# nbox_kopia - kopia konfiguracji nBoxa i przenosiny na inny box
# (ADB 5800, GraterliaOS, busybox 1.28, sh4). Powstal przy zamianie
# dwoch boxow miedzy domami (2026-11-01). Menu w enigmie: wtyczka
# NBoxKopia (Menu -> Ustawienia -> System -> nBox kopia); ten skrypt robi
# cala robote, wiec dziala tez z SSH. Na boxie: /usr/bin/nbox_kopia.
#
# Kopia to katalog BAZA/nbox_kopia/<oktet>_<data>[_opis]/:
#   kanaly.tgz  lamedb, bukiety, alternatywy, blacklist/whitelist
#   enigma.tgz  reszta /etc/enigma2 (settings, timery, ...), picony, tuxtxt, videomode
#   oscam.tgz   /etc/oscam, /usr/bin/oscam (nasza binarka), /etc/init.d/softcam
#   siec.tgz    interfaces, resolv.conf, hosts, fstab, exports, wpa_supplicant
#   system.tgz  rc.local, hdparm, nasze uslugi (+ dowiazania rc.d), collectd,
#               /root, crontab, passwd/group, klucze dropbeara, strefa czasu
#   pakiety.txt lista pakietow; ipk/ = nasze pakiety (Maintainer kofec80)
#               odtworzone z zainstalowanych plikow
#   *.txt (lista plikow czesci), info.txt, md5sums
# Pomijane: *.bak*, *.ipk, *.pyc, epg.dat, logi crashy, historia powloki,
# cache, pliki w /root ponad 512 KB (stare binarki oscama) - lista w info.txt.
#
# Uzycie:
#   nbox_kopia sprawdz
#       co poszloby do kopii, ile zajmie, gdzie mozna zapisac; nic nie zapisuje
#   nbox_kopia miejsca
#       katalogi na kopie: "sciezka wolne_KB typ_fs" (jffs2 = flash boxa)
#   nbox_kopia zapisz [-d BAZA] [-o OPIS] [-z N]
#       kopia do BAZA (dom. /hdd); -z N: zostaw N najnowszych kopii tego boxa
#       z tym samym OPIS (kopie automatyczne). Ostatnia linia: "KOPIA <katalog>".
#       Settings enigmy sa takie, jak przy ostatnim zapisie - wtyczka zapisuje
#       je przed kopia, z SSH to stan z ostatniego zamkniecia menu/enigmy.
#   nbox_kopia wgraj KOPIA CZESCI PO
#       CZESCI: lista po przecinku (kanaly,enigma,oscam,siec,system,pakiety)
#       albo "wszystko". PO: restart | wylacz | nic.
#       "nic" tylko dla kanaly i oscam: kanaly przeladowane w dzialajacej
#       enigmie, oscam zrestartowany. Inne czesci: enigma zatrzymana czysto,
#       pliki podmienione, potem reboot albo init 0 (box jedzie gdzie indziej).
#       Najpierw zawsze kopia obecnego stanu: BAZA/nbox_kopia/<oktet>_<data>_przed_wgraniem
#       (zostaja 3 ostatnie).
#   nbox_kopia brakujace KOPIA
#       pakiety z kopii, ktorych nie ma na tym boxie (do opkg install z feedu)
#   nbox_kopia --w-tle POLECENIE ...
#       odlaczone od enigmy (setsid), wyjscie w /tmp/nbox_kopia.log - tak
#       wtyczka wola wgraj, ktore zamyka enigme.
#
# NBK_ROOT=katalog: testy na PC (pliki boxa pod tym katalogiem, uslugi,
# opkg i reboot tylko wypisywane).

PATH=/sbin:/bin:/usr/sbin:/usr/bin

WERSJA=1.0
R=${NBK_ROOT:-}
PODKAT=nbox_kopia
LOG=/tmp/nbox_kopia.log
BLOKADA=/tmp/nbox_kopia.blokada
ROOT_MAX_KB=512
CZESCI="kanaly enigma oscam siec system pakiety"
WEBIF=http://127.0.0.1
NASZ_MAINTAINER=kofec80

KANALY_RE='^etc/enigma2/(lamedb5?|bouquets\.(tv|radio)|userbouquet\..*|alternatives\..*|blacklist|whitelist)$'
POMIN_RE='(\.bak|_bak$|\.ipk$|\.pyc$|/\.ash_history$|/\.cache/|/epg\.dat$|enigma2_crash|/\.e2settings\.pkl$|^root/bukiety-usuniete)'
USLUGI="nbox_monitor nbox_tv collectd"

ENIGMA="usr/share/enigma2/picon usr/local/share/enigma2/picon etc/tuxtxt etc/videomode"
OSCAM="etc/oscam usr/bin/oscam etc/init.d/softcam"
SIEC="etc/network/interfaces etc/resolv.conf etc/hostname etc/hosts etc/fstab
etc/auto.network etc/exports etc/wpa_supplicant.conf etc/wpa_supplicant.ra0.conf"
SYSTEM="etc/rc.local etc/sysconfig/hdparm.conf etc/init.d/nbox_monitor
etc/init.d/nbox_tv etc/init.d/collectd etc/collectd.conf usr/sbin/collectd
usr/lib/collectd usr/share/collectd etc/dropbear etc/passwd etc/group
etc/shadow etc/timezone etc/vdstandby.cfg var/spool/cron/crontabs root"

T=

blad() { echo "BLAD: $*" >&2; exit 1; }
uwaga() { echo "UWAGA: $*"; }

# w testach (NBK_ROOT) tylko wypisz
zrob() {
	if [ -n "$R" ]; then
		echo "(test) $*"
	else
		"$@"
	fi
}

sprzatnij() {
	[ -n "$T" ] && rm -rf "$T"
	rmdir "$BLOKADA" 2> /dev/null
}

zablokuj() {
	mkdir "$BLOKADA" 2> /dev/null || blad "nbox_kopia juz dziala (albo zostal $BLOKADA)"
	T=/tmp/nbox_kopia.$$
	rm -rf "$T"
	mkdir -p "$T" || blad "nie moge utworzyc $T"
	trap sprzatnij EXIT
	trap 'exit 1' INT TERM HUP
}

oktet() {
	o=$(ip -4 addr show eth0 2> /dev/null |
		sed -n 's/.*inet [0-9]*\.[0-9]*\.[0-9]*\.\([0-9]*\)\/.*/\1/p' | head -n 1)
	echo "${o:-x}"
}

boxtype() { sed -n 's/^boxtype=//p' "$R/var/grun/grcstype" 2> /dev/null; }

wolne_kb() { df -k "$1" 2> /dev/null | awk 'NR > 1 { w = $(NF - 2) } END { print w + 0 }'; }

rozmiar_kb() { echo $(( $(wc -c < "$1") / 1024 )); }

# pliki i dowiazania pod podanymi sciezkami (wzgledne, bez /)
znajdz() {
	(
		cd "$R/" || exit 1
		for p in "$@"; do
			if [ -e "$p" ] || [ -L "$p" ]; then
				find "$p" \( -type f -o -type l \) -print
			fi
		done
	)
}

linki_uslug() {
	(
		cd "$R/" || exit 1
		for u in $USLUGI; do
			find etc/rc.d/rc?.d -type l -name "*$u" 2> /dev/null
		done
	)
}

kandydaci() {
	case $1 in
	kanaly) znajdz etc/enigma2 | grep -E "$KANALY_RE" ;;
	enigma) znajdz etc/enigma2 | grep -vE "$KANALY_RE"; znajdz $ENIGMA ;;
	oscam) znajdz $OSCAM ;;
	siec) znajdz $SIEC ;;
	system) znajdz $SYSTEM; linki_uslug ;;
	esac
}

# $T/<czesc>.lista dla kazdej czesci, $T/pominiete; pliki w /root ponad ROOT_MAX_KB odsiane
przygotuj_listy() {
	: > "$T/pominiete"
	for c in $CZESCI; do
		[ "$c" = pakiety ] && continue
		kandydaci $c | sort -u > "$T/$c.kand"
		grep -E "$POMIN_RE" "$T/$c.kand" >> "$T/pominiete"
		grep -vE "$POMIN_RE" "$T/$c.kand" | while IFS= read -r f; do
			case $f in
			root/*)
				if [ -f "$R/$f" ] && [ ! -L "$R/$f" ] && [ "$(rozmiar_kb "$R/$f")" -gt $ROOT_MAX_KB ]; then
					echo "$f" >> "$T/pominiete"
					continue
				fi
				;;
			esac
			echo "$f"
		done > "$T/$c.lista"
	done
}

zainstalowane() {
	awk '/^Package:/ { p = $2 } /^Version:/ { v = $2 } /^Status:/ { s = $0 }
		/^$/ { if (p != "" && s ~ / installed/) print p " - " v; p = v = s = "" }
		END { if (p != "" && s ~ / installed/) print p " - " v }' "$R/var/lib/opkg/status" | sort
}

nasze_pakiety() {
	grep -l "^Maintainer: .*$NASZ_MAINTAINER" "$R"/var/lib/opkg/info/*.control 2> /dev/null |
		sed 's|.*/||; s|\.control$||'
}

# naglowek czlonka archiwum ar + dane (wyrownanie do 2 B)
ar_czlon() {
	r=$(wc -c < "$1")
	r=$((r + 0))
	printf '%-16s%-12s%-6s%-6s%-8s%-10s`\n' "$2" "$(date +%s)" 0 0 100644 "$r"
	cat "$1"
	[ $((r % 2)) -eq 1 ] && printf '\n'
	return 0
}

# $1 pakiet, $2 katalog wyjsciowy: .ipk z zainstalowanych plikow (control i skrypty z opkg/info)
zrob_ipk() {
	p=$1
	i=$R/var/lib/opkg/info
	t=$T/ipk.$p
	rm -rf "$t"
	mkdir -p "$t/ctl" "$t/data"
	cp "$i/$p.control" "$t/ctl/control" || return 1
	for s in preinst postinst prerm postrm conffiles; do
		[ -f "$i/$p.$s" ] && cp "$i/$p.$s" "$t/ctl/$s"
	done
	chmod 644 "$t/ctl/control"
	for s in preinst postinst prerm postrm; do
		[ -f "$t/ctl/$s" ] && chmod 755 "$t/ctl/$s"
	done
	: > "$t/brak"
	cut -f1 "$i/$p.list" | sed 's|^/||' | while IFS= read -r f; do
		case $f in '' | */) continue ;; esac
		if [ -f "$R/$f" ] || [ -L "$R/$f" ]; then
			mkdir -p "$t/data/${f%/*}"
			cp -a "$R/$f" "$t/data/$f"
		else
			echo "/$f" >> "$t/brak"
		fi
	done
	[ -s "$t/brak" ] && uwaga "$p: brak plikow $(tr '\n' ' ' < "$t/brak")- pakiet niepelny"
	(cd "$t/ctl" && tar czf ../control.tar.gz .) || return 1
	(cd "$t/data" && tar czf ../data.tar.gz .) || return 1
	echo "2.0" > "$t/debian-binary"
	n=$(sed -n 's/^Package: //p' "$t/ctl/control")
	v=$(sed -n 's/^Version: //p' "$t/ctl/control")
	a=$(sed -n 's/^Architecture: //p' "$t/ctl/control")
	{
		printf '!<arch>\n'
		ar_czlon "$t/debian-binary" debian-binary
		ar_czlon "$t/control.tar.gz" control.tar.gz
		ar_czlon "$t/data.tar.gz" data.tar.gz
	} > "$2/${n}_${v}_${a}.ipk" || return 1
	echo "  ipk/${n}_${v}_${a}.ipk"
	rm -rf "$t"
}

# zapisz BAZA OPIS ZOSTAW
zapisz() {
	baza=$1
	opis=$2
	zostaw=${3:-0}
	[ -d "$baza" ] || blad "nie ma katalogu $baza"
	ok=$(oktet)
	kat=$baza/$PODKAT/${ok}_$(date +%Y%m%d_%H%M%S)${opis:+_$opis}
	[ -e "$kat" ] && blad "$kat juz jest"
	echo "=== kopia do $kat"
	przygotuj_listy
	cat "$T"/*.lista > "$T/wszystko"
	szac=$(( $( (cd "$R/" && tar cf - -T "$T/wszystko") | wc -c) / 1024 ))
	wolne=$(wolne_kb "$baza")
	echo "  plikow $(wc -l < "$T/wszystko"), ok. $szac KB przed kompresja, wolne $wolne KB"
	[ "$wolne" -gt $((szac + 512)) ] || blad "za malo miejsca w $baza ($wolne KB, potrzeba do $szac KB)"
	mkdir -p "$kat" || blad "nie moge utworzyc $kat"
	porzuc() { rm -rf "$kat"; blad "$*"; }
	zapisane=
	for c in $CZESCI; do
		[ "$c" = pakiety ] && continue
		[ -s "$T/$c.lista" ] || { echo "  $c: brak plikow na tym boxie"; continue; }
		tar czf "$kat/$c.tgz" -C "$R/" -T "$T/$c.lista" || porzuc "tar $c.tgz"
		tar tzf "$kat/$c.tgz" > "$kat/$c.txt" || porzuc "$c.tgz nieczytelne"
		echo "  $c: $(wc -l < "$kat/$c.txt") plikow, $(rozmiar_kb "$kat/$c.tgz") KB"
		zapisane="$zapisane $c"
	done
	zainstalowane > "$kat/pakiety.txt"
	nasze=$(nasze_pakiety)
	if [ -n "$nasze" ]; then
		mkdir -p "$kat/ipk"
		for p in $nasze; do
			zrob_ipk "$p" "$kat/ipk" || porzuc "nie zbudowalem ipk $p"
		done
	fi
	zapisane="$zapisane pakiety"
	{
		echo "wersja=$WERSJA"
		echo "data=$(date '+%Y-%m-%d %H:%M:%S')"
		echo "opis=$opis"
		echo "host=$(hostname 2> /dev/null)"
		echo "oktet=$ok"
		echo "mac=$(cat "$R/sys/class/net/eth0/address" 2> /dev/null)"
		echo "boxtype=$(boxtype)"
		echo "jadro=$(uname -v)"
		echo "czesci=${zapisane# }"
		echo "nasze_pakiety=$(echo $nasze)"
		echo "pominiete=$(sort -u "$T/pominiete" | tr '\n' ' ')"
	} > "$kat/info.txt"
	(cd "$kat" && md5sum *.tgz pakiety.txt info.txt $( [ -d ipk ] && ls ipk/*.ipk) > md5sums) ||
		porzuc "md5sums"
	sync
	echo "  razem $(du -sk "$kat" | cut -f1) KB"
	if [ "$zostaw" -gt 0 ] && [ -n "$opis" ]; then
		ls -d "$baza/$PODKAT/${ok}_"*"_$opis" 2> /dev/null | sort -r | tail -n +$((zostaw + 1)) |
			while IFS= read -r d; do
				rm -rf "$d" && echo "  usunieta stara kopia $d"
			done
	fi
	echo "KOPIA $kat"
}

miejsca() {
	{
		[ -d "$R/hdd" ] && echo /hdd
		awk '$2 ~ /^\/(media|mnt|hdd)/ && $3 != "autofs" { print $2 }' /proc/mounts 2> /dev/null
	} | sort -u | while IFS= read -r m; do
		[ -d "$m" ] && [ -w "$m" ] || continue
		fs=$(awk -v m="$m" '$2 == m { t = $3 } END { print t }' /proc/mounts 2> /dev/null)
		[ -z "$fs" ] && fs=$(awk '$2 == "/" && $1 != "rootfs" { t = $3 } END { print t }' /proc/mounts 2> /dev/null)
		echo "$m $(wolne_kb "$m") ${fs:-?}"
	done
}

sprawdz() {
	zablokuj
	echo "box: $(boxtype), oktet $(oktet), MAC $(cat "$R/sys/class/net/eth0/address" 2> /dev/null), nbox_kopia $WERSJA"
	przygotuj_listy
	for c in $CZESCI; do
		[ "$c" = pakiety ] && continue
		n=$(wc -l < "$T/$c.lista")
		kb=0
		[ "$n" -gt 0 ] && kb=$(( $( (cd "$R/" && tar cf - -T "$T/$c.lista") | wc -c) / 1024 ))
		echo "  $c: $n plikow, $kb KB przed kompresja"
	done
	echo "  pakiety: $(zainstalowane | wc -l) zainstalowanych, nasze: $(echo $(nasze_pakiety))"
	if [ -s "$T/pominiete" ]; then
		echo "pominiete:"
		sort -u "$T/pominiete" | sed 's|^|  /|'
	fi
	echo "miejsca (sciezka, wolne KB, system plikow; jffs2 = flash boxa):"
	miejsca | sed 's|^|  |'
}

zatrzymaj() {
	if [ -n "$R" ]; then
		echo "(test) zatrzymuje monitor, enigme, oscama, collectd"
		return
	fi
	# monitor przy stojacej enigmie restartowalby box
	[ -x /etc/init.d/nbox_monitor ] && /etc/init.d/nbox_monitor stop
	# bez petli startopenpli nikt nie podniesie enigmy po wyjsciu
	start-stop-daemon --stop --quiet --oknodo --name startopenpli --user 0
	if pidof enigma2 > /dev/null; then
		# newstate=3 = restart enigmy: wychodzi czysto (zapisuje settings, potem je podmienimy)
		wget -q -T 5 -O /dev/null "$WEBIF/web/powerstate?newstate=3"
		i=0
		while pidof enigma2 > /dev/null; do
			i=$((i + 1))
			[ $i -eq 30 ] && kill $(pidof enigma2) 2> /dev/null
			[ $i -ge 40 ] && { kill -9 $(pidof enigma2) 2> /dev/null; sleep 1; break; }
			sleep 1
		done
		echo "  enigma zatrzymana po $i s"
	fi
	rm -f /var/grun/ggui
	/etc/init.d/softcam stop
	[ -x /etc/init.d/collectd ] && /etc/init.d/collectd stop
	sync
}

brakujace() {
	kat=$1
	[ -f "$kat/pakiety.txt" ] || blad "nie ma $kat/pakiety.txt"
	zainstalowane | cut -d' ' -f1 > "$T/teraz"
	cut -d' ' -f1 "$kat/pakiety.txt" | while IFS= read -r p; do
		grep -qx "$p" "$T/teraz" || echo "$p"
	done
}

wgraj() {
	kat=${1%/}
	po=$3
	case $2 in
	wszystko) czesci=$CZESCI ;;
	'') blad "podaj czesci (np. kanaly,enigma albo wszystko)" ;;
	*) czesci=$(echo "$2" | tr ',' ' ') ;;
	esac
	case $po in restart | wylacz | nic) ;; *) blad "PO: restart, wylacz albo nic" ;; esac
	[ -f "$kat/info.txt" ] && [ -f "$kat/md5sums" ] || blad "$kat to nie kopia nbox_kopia"
	(cd "$kat" && md5sum -c md5sums > /dev/null) || blad "md5 plikow kopii sie nie zgadza ($kat/md5sums)"
	wybrane=
	zatrzymac=0
	for c in $czesci; do
		case " $CZESCI " in *" $c "*) ;; *) blad "nieznana czesc: $c" ;; esac
		if [ "$c" != pakiety ] && [ ! -f "$kat/$c.tgz" ]; then
			uwaga "w kopii nie ma czesci $c - pomijam"
			continue
		fi
		wybrane="$wybrane $c"
		case $c in enigma | siec | system | pakiety) zatrzymac=1 ;; esac
	done
	[ -n "$wybrane" ] || blad "nic do wgrania"
	[ $zatrzymac = 1 ] && [ "$po" = nic ] && blad "czesci$wybrane wymagaja restartu boxa (PO: restart albo wylacz)"
	z=$(sed -n 's/^boxtype=//p' "$kat/info.txt")
	[ "$z" != "$(boxtype)" ] && uwaga "kopia z boxa $z, ten box to $(boxtype) - tunery w settings moga nie pasowac"
	echo "=== wgrywam$wybrane z $kat"

	baza=${kat%/*}
	baza=${baza%/*}
	echo "=== najpierw kopia obecnego stanu tego boxa"
	( zapisz "$baza" przed_wgraniem 3 ) > "$T/przed.log" 2>&1
	rc=$?
	sed 's|^|  |' "$T/przed.log"
	[ $rc -eq 0 ] || blad "kopia obecnego stanu sie nie udala - niczego nie zmieniam"
	przed=$(sed -n 's/^KOPIA //p' "$T/przed.log")

	if [ $zatrzymac = 1 ]; then
		echo "=== zatrzymuje uslugi"
		zatrzymaj
	else
		case " $wybrane " in *" oscam "*) zrob /etc/init.d/softcam stop ;; esac
	fi

	for c in $wybrane; do
		[ "$c" = pakiety ] && continue
		case $c in
		kanaly)
			# stare bukiety by zostaly, gdy kopia ma ich mniej
			kandydaci kanaly | while IFS= read -r f; do rm -f "$R/$f"; done
			;;
		oscam)
			rm -rf "$R/etc/oscam/"*
			;;
		system)
			# uslugi wlaczone tak jak w kopii
			for u in $USLUGI; do rm -f "$R"/etc/rc.d/rc?.d/*"$u"; done
			;;
		esac
		echo "=== $c"
		tar xzf "$kat/$c.tgz" -C "$R/" || blad "rozpakowanie $c.tgz (kopia sprzed: $przed)"
		if [ "$c" = siec ] && [ -f "$R/etc/fstab" ]; then
			# bez punktow montowania NFS mount z rc.local wisi
			for m in $(awk '$3 == "nfs" { print $2 }' "$R/etc/fstab"); do
				mkdir -p "$R$m"
			done
		fi
	done

	case " $wybrane " in *" pakiety "*)
		for ipk in "$kat"/ipk/*.ipk; do
			[ -f "$ipk" ] || continue
			echo "=== opkg install ${ipk##*/}"
			zrob opkg install "$ipk"
		done
		b=$(brakujace "$kat")
		if [ -n "$b" ]; then
			echo "=== na tym boxie nie ma pakietow z kopii (opkg install z feedu):"
			echo "$b" | sed 's|^|  |'
		fi
		;;
	esac
	sync

	if [ $zatrzymac = 0 ]; then
		case " $wybrane " in *" oscam "*) zrob /etc/init.d/softcam start ;; esac
		case " $wybrane " in *" kanaly "*)
			# mode=0: lamedb i bukiety od nowa
			if [ -n "$R" ]; then
				echo "(test) servicelistreload"
			elif ! wget -q -T 10 -O /dev/null "$WEBIF/web/servicelistreload?mode=0"; then
				uwaga "enigma nie przeladowala listy - zrob to z menu albo zrestartuj enigme"
			fi
			;;
		esac
		echo "=== gotowe (kopia sprzed: $przed)"
	else
		echo "=== gotowe, teraz $po (kopia sprzed: $przed)"
		if [ "$po" = wylacz ]; then zrob init 0; else zrob reboot; fi
	fi
}

if [ "$1" = --w-tle ]; then
	shift
	setsid "$0" "$@" > "$LOG" 2>&1 < /dev/null &
	echo "w tle, log $LOG"
	exit 0
fi

case $1 in
sprawdz)
	sprawdz
	;;
miejsca)
	miejsca
	;;
zapisz)
	shift
	baza=/hdd
	opis=
	zostaw=0
	while [ $# -gt 0 ]; do
		case $1 in
		-d) baza=${2%/}; shift ;;
		-o) opis=$2; shift ;;
		-z) zostaw=$2; shift ;;
		*) blad "zapisz: nieznana opcja $1" ;;
		esac
		shift
	done
	case $opis in *[!a-zA-Z0-9_-]*) blad "OPIS tylko litery, cyfry, _ i -" ;; esac
	zablokuj
	zapisz "$baza" "$opis" "$zostaw"
	;;
wgraj)
	[ $# -eq 4 ] || blad "wgraj KOPIA CZESCI PO"
	zablokuj
	wgraj "$2" "$3" "$4"
	;;
brakujace)
	[ -n "$2" ] || blad "brakujace KOPIA"
	zablokuj
	brakujace "${2%/}"
	;;
*)
	sed -n '/^# Uzycie:/,/^# NBK_ROOT/p' "$0" | sed 's/^# \{0,1\}//'
	exit 1
	;;
esac
