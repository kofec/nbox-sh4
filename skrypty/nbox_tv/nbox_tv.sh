#!/bin/sh
#
# nbox_tv.sh - nBox zasypia i budzi sie razem z telewizorem
# (nBox ADB 5800, GraterliaOS, busybox, sh4).
#
# Po co: telewizor, z ktorym nie dogada sie wtyczka NBoxCEC (brak CEC, CEC
# wylaczone w TV, stary TV bez sieci). Nie uruchamiac razem z NBoxCEC - oba
# usypialyby i budzily box.
#
# Pierwsze zrodlo stanu TV (TV_ZRODLO=hotplug, domyslne): linia hotplug HDMI.
# Czesc telewizorow (np. plazma LG 50PJ250 z 2010) w standby ja puszcza, a box
# widzi to w /sys/class/stmcoredisplay/hdmi0.0/hotplug - takze wtedy, gdy sam
# jest w standby (nie odcina 5 V na HDMI): TV wlaczony = y, TV w standby z
# pilota = n, w obu stanach boxa.
#
# Sterownik (stmcore-display) nie wysyla ueventu przy zmianie hotplug, jest
# tylko sysfs_notify - wiec skrypt odpytuje plik co POLL s. To odczyt zmiennej
# sterownika, nie sprzetu: linii HPD pilnuje sam sterownik.
#
# Drugie zrodlo (TV_ZRODLO=sony): telewizory Sony, ktore w standby trzymaja
# hotplug (np. BRAVIA 8). Odpytuje Simple IP Control (TCP 20060, "Proste
# sterowanie IP" w ustawieniach TV, bez klucza):
# *SEPOWR################ -> *SAPOWR0000000000000001 wlaczony, ...0000 standby.
# Brak odpowiedzi (TV poza siecia, zmiana adresu) to "nie wiem", nie "wylaczony":
# zeruje licznik wylaczenia i nic nie robi, zeby nie uspic boxa w czasie
# ogladania.
#
# Trzecie zrodlo (TV_ZRODLO=ping): dla TV, ktory trzyma hotplug w standby i nie
# ma otwartego API (np. LG webOS z filtrowanym 3000/3001). Zalozenie: TV
# w standby schodzi z Wi-Fi, wiec odpowiedz na ping = wlaczony, brak =
# wylaczony. Okazalo sie zawodne - LG webOS potrafi trzymac siec w standby.
# Ping nie ma stanu "nie wiem", dlatego TV_OFF_PO/STANDBY_PO w konfiguracji
# dluzsze (Wi-Fi gubi pingi).
#
# Czwarte zrodlo (TV_ZRODLO=cec): podsluch CEC z /proc/cec_rx (modul nbox_cec
# albo cec_rx z tego repo: "<nr> <epoch.ms> <nad>><odb> <bajt><+|->...").
# Kazdy TV gada inaczej (README, "Zachowanie telewizorow"), wiec reguly to
# wyrazenia regularne z konfiguracji, dopasowywane do ramki bez nr i czasu,
# np. "0>F 0f- 36-":
#   CEC_WL     ramka = TV wlaczony (dom. Report Physical Address / Active
#              Source / Routing Change od TV),
#   CEC_WYL    ramka = TV wylaczony (dom. Standby rozgloszony przez TV),
#   CEC_ZYJE   ramki, ktore TV nadaje tylko wlaczony (np. odpytywanie u LG,
#              cokolwiek od TV u plazmy LG) - brak takiej ramki przez
#              CEC_ZYJE_S s = wylaczony; przez CEC_PO_WYL s po CEC_WYL
#              ignorowane, bo TV konczy rozmowy (Sony z soundbarem jeszcze
#              ~65 s).
# Wygrywa najswiezszy sygnal. Bez backslashy (awk -v je zjada): "+" jako [+].
# Czasy zdarzen w $CEC_STAN, bo bufor modulu ma 256 ramek (~85 s przy gadatliwym
# TV). Bez modulu albo przed pierwszym sygnalem - pusto, a wtedy TV_ZAPAS (np.
# hotplug, ping), jesli ustawiony.
#
# Budzenie impulsem hotplug (PULS_BUDZI=1): LG webOS przy wlaczaniu puszcza
# hotplug na kilka s (zalozenie z jednej probki). Hotplug n krotszy niz
# PULS_MAX s, a box w standby -> pobudka. Dluzsze n to nie impuls.
# Impuls bywa falszywy: LG w standby potrafil mrugnac hotplug 5 razy w 7 min,
# nie pojawiajac sie w sieci, a pobudka trzymala box 4 h. Dlatego po pobudce
# impulsem: TV dalej n przez PULS_SPRAWDZ s -> box z powrotem w standby.
#
# Diagnostyka (DIAG_LOG=plik): kazda zmiana ping/hotplug/tmds_status (tmds
# Stopped = box w standby) i co DIAG_CO s licznik pingow - do sprawdzenia
# zalozen po fakcie, bez wplywu na dzialanie.
#
# Ustawienia boxa: $KONF (domyslnie /root/nbox_tv.conf), jesli jest - wzor
# nbox_tv.conf.example. Bez pliku: hotplug.
#
# Reguly - dzialaja na zmianach stanu TV, zeby nie walczyc z pilotem:
#   - hotplug n dluzej niz TV_OFF_PO s  -> TV uznany za wylaczony; krotsze
#                                          mrugniecia (zmiana trybu, EDID)
#                                          nic nie robia,
#   - hotplug n dluzej niz STANDBY_PO s -> box w standby, raz na jedno
#                                          wylaczenie TV (ponawia, dopoki
#                                          enigma2 nie odpowie),
#   - y po TV uznanym za wylaczony      -> box sie budzi, jesli spi.
# Wiec: box uspiony pilotem przy wlaczonym TV zostaje w standby, a obudzony
# pilotem przy dawno wylaczonym TV zostaje wlaczony. Po starcie boxa przy
# wylaczonym TV zasnie po STANDBY_PO s.
#
# Standby i budzenie przez OpenWebif na 127.0.0.1 (/web/powerstate,
# newstate=5 / newstate=4) - to samo, co robi pilot, bez deep standby.
#
# Log: $LOG w RAM-ie (przyciety do LOG_MAX linii) i logger -t nbox_tv.
# Start: /etc/init.d/nbox_tv start (linia w /etc/rc.local) albo wprost
# nohup /root/nbox_tv.sh >/dev/null 2>&1 & (stop: kill PID z $PIDF).
# Sprawdzenie zrodla bez petli i bez dotykania boxa: nbox_tv.sh --stan (wypisuje
# y / n / pusto; przy cec aktualizuje tylko $CEC_STAN).

KONF="${KONF:-/root/nbox_tv.conf}"
[ -r "$KONF" ] && . "$KONF"

TV_ZRODLO="${TV_ZRODLO:-hotplug}"
TV_IP="${TV_IP:-}"
TV_PORT="${TV_PORT:-20060}"
POLL="${POLL:-5}"
TV_OFF_PO="${TV_OFF_PO:-15}"
STANDBY_PO="${STANDBY_PO:-180}"
HOTPLUG="${HOTPLUG:-/sys/class/stmcoredisplay/hdmi0.0/hotplug}"
WEBIF="${WEBIF:-http://127.0.0.1}"
LOG="${LOG:-/tmp/nbox_tv.log}"
LOG_MAX="${LOG_MAX:-300}"
PIDF="${PIDF:-/tmp/nbox_tv.pid}"
PULS_BUDZI="${PULS_BUDZI:-0}"
PULS_MAX="${PULS_MAX:-20}"
PULS_SPRAWDZ="${PULS_SPRAWDZ:-180}"
TMDS="${TMDS:-/sys/class/stmcoredisplay/hdmi0.0/tmds_status}"
DIAG_LOG="${DIAG_LOG:-}"
DIAG_CO="${DIAG_CO:-300}"
DIAG_MAX="${DIAG_MAX:-3000}"
TV_ZAPAS="${TV_ZAPAS:-}"
CEC_PROC="${CEC_PROC:-/proc/cec_rx}"
CEC_STAN="${CEC_STAN:-/tmp/nbox_tv.cec}"
CEC_WL="${CEC_WL:-^0>F 0f- (84|82|80)-}"
CEC_WYL="${CEC_WYL:-^0>F 0f- 36-}"
CEC_ZYJE="${CEC_ZYJE:-}"
CEC_ZYJE_S="${CEC_ZYJE_S:-60}"
CEC_PO_WYL="${CEC_PO_WYL:-90}"
TAG=nbox_tv

uptime_s() { cut -d. -f1 /proc/uptime; }
stempel()  { date '+%F %T'; }
pobierz()  { wget -q -T 5 -O - "$1" 2>/dev/null; }

log() {
    logger -t "$TAG" "$1" 2>/dev/null
    echo "$(stempel) up=$(uptime_s) $1" >> "$LOG"
    if [ "$(wc -l < "$LOG")" -gt "$LOG_MAX" ]; then
        tail -n $((LOG_MAX / 2)) "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
    fi
}

# y / n / pusto z ramek CEC. $CEC_STAN: "t0 t_wl t_wyl t_zyje" (epoch; t0 =
# poczatek obserwacji, od niego liczy sie CEC_ZYJE_S, gdy TV jeszcze nic nie
# nadal). CEC_TERAZ tylko do testow na nagranych logach.
tv_cec() {
    [ -r "$CEC_PROC" ] || return 0
    awk -v teraz="${CEC_TERAZ:-$(date +%s)}" -v plik="$CEC_STAN" \
        -v wl="$CEC_WL" -v wyl="$CEC_WYL" -v zy="$CEC_ZYJE" \
        -v zy_s="$CEC_ZYJE_S" -v po_wyl="$CEC_PO_WYL" '
        BEGIN {
            t0 = teraz; twl = 0; twyl = 0; tzy = 0
            if ((getline l < plik) > 0 && split(l, p, " ") == 4 && p[1] <= teraz + 60) {
                t0 = p[1]; twl = p[2]; twyl = p[3]; tzy = p[4]
            }
            close(plik)
        }
        /^#/ || NF < 3 { next }
        {
            t = $2 + 0
            r = $0
            sub(/^[0-9]+ [0-9.]+ /, "", r)
            if (wyl != "" && r ~ wyl) { if (t > twyl) twyl = t }
            else if (wl != "" && r ~ wl) { if (t > twl) twl = t }
            if (zy != "" && r ~ zy && t > twyl + po_wyl && t > tzy) tzy = t
        }
        END {
            printf "%.3f %.3f %.3f %.3f\n", t0, twl, twyl, tzy > plik
            close(plik)
            kiedy = 0; st = ""
            if (twl > 0) { kiedy = twl; st = "y" }
            if (twyl > 0 && twyl >= kiedy) { kiedy = twyl; st = "n" }
            if (zy != "") {
                if (tzy > kiedy) { kiedy = tzy; st = "y" }
                od = t0
                if (twl > od) od = twl
                if (tzy > od) od = tzy
                if (teraz - od > zy_s && od + zy_s >= kiedy) st = "n"
            }
            print st
        }' "$CEC_PROC" 2>/dev/null
}

# y / n / pusto (nie wiadomo) - wspolny jezyk wszystkich zrodel
tv_zrodlo() {
    case "$1" in
    cec)
        tv_cec
        ;;
    sony)
        ( printf '*SEPOWR################\n'; sleep 1 ) |
            nc -w 3 "$TV_IP" "$TV_PORT" 2>/dev/null | tr -d '\r' |
            sed -n 's/^\*SAPOWR0\{15\}\([01]\)$/\1/p' | tail -n 1 |
            sed 's/1/y/; s/0/n/'
        ;;
    ping)
        if ping -c 1 -W 2 "$TV_IP" > /dev/null 2>&1; then echo y; else echo n; fi
        ;;
    *)
        cat "$HOTPLUG" 2>/dev/null
        ;;
    esac
}

# zrodlo glowne, a gdy nie wie - zapasowe
tv_stan() {
    s=$(tv_zrodlo "$TV_ZRODLO")
    [ -z "$s" ] && [ -n "$TV_ZAPAS" ] && [ "$TV_ZAPAS" != "$TV_ZRODLO" ] &&
        s=$(tv_zrodlo "$TV_ZAPAS")
    echo "$s"
}

if [ "$1" = --stan ]; then
    tv_stan
    exit 0
fi

# true / false z OpenWebifu; pusto, gdy enigma2 nie odpowiada (np. start boxa)
box_standby() {
    pobierz "$WEBIF/web/powerstate" | tr -d ' \t\r\n' |
        sed -n 's/.*<e2instandby>\([a-z]*\)<.*/\1/p'
}

diag() {
    [ -n "$DIAG_LOG" ] || return 0
    echo "$(stempel) up=$(uptime_s) $1" >> "$DIAG_LOG"
    if [ "$(wc -l < "$DIAG_LOG")" -gt "$DIAG_MAX" ]; then
        tail -n $((DIAG_MAX / 2)) "$DIAG_LOG" > "$DIAG_LOG.tmp" && mv "$DIAG_LOG.tmp" "$DIAG_LOG"
    fi
}

echo $$ > "$PIDF"
trap 'log "stop"; rm -f "$PIDF"; exit 0' TERM INT

n_od=       # uptime, od ktorego hotplug = n; pusto przy y
tv_off=0    # TV uznany za wylaczony (n dluzej niz TV_OFF_PO)
uspiony=0   # w tym wylaczeniu TV box juz uspiony (albo juz spal)
poprz=
hpn_od=     # uptime, od ktorego sama linia hotplug = n (impuls)
puls_od=    # uptime pobudki impulsem; pusto, gdy TV potem odpowiedzial
d_poprz=    # ostatni stan w diagnostyce
d_od=       # poczatek okna licznika pingow
d_ok=0
d_brak=0

cel=
case "$TV_ZRODLO $TV_ZAPAS" in
*sony*) cel=" $TV_IP:$TV_PORT" ;;
*ping*) cel=" $TV_IP" ;;
esac
if [ -n "$cel" ] && [ -z "$TV_IP" ]; then
    log "TV_ZRODLO=$TV_ZRODLO${TV_ZAPAS:+ TV_ZAPAS=$TV_ZAPAS} bez TV_IP - koniec"
    rm -f "$PIDF"
    exit 1
fi
[ "$TV_ZRODLO" = cec ] && cel="$cel CEC_ZYJE='$CEC_ZYJE' CEC_ZYJE_S=$CEC_ZYJE_S"

log "start: TV_ZRODLO=$TV_ZRODLO${TV_ZAPAS:+ TV_ZAPAS=$TV_ZAPAS}$cel POLL=$POLL TV_OFF_PO=$TV_OFF_PO STANDBY_PO=$STANDBY_PO PULS_BUDZI=$PULS_BUDZI${DIAG_LOG:+ DIAG_LOG=$DIAG_LOG}"

while :; do
    hp=$(tv_stan)
    teraz=$(uptime_s)
    [ "$hp" != "$poprz" ] && log "TV ${poprz:-?} -> ${hp:-?}"
    poprz=$hp

    # sama linia hotplug - impuls przy wlaczaniu TV i diagnostyka
    if [ "$PULS_BUDZI" = 1 ] || [ -n "$DIAG_LOG" ]; then
        linia=$(cat "$HOTPLUG" 2>/dev/null)
        if [ "$linia" = n ]; then
            [ -z "$hpn_od" ] && hpn_od=$teraz
        elif [ "$linia" = y ] && [ -n "$hpn_od" ]; then
            dl=$((teraz - hpn_od))
            hpn_od=
            if [ $dl -le "$PULS_MAX" ]; then
                sb=$(box_standby)
                diag "PULS hotplug n ok. $dl s (+POLL), box standby=${sb:-?}"
                if [ "$PULS_BUDZI" = 1 ] && [ "$sb" = true ]; then
                    if pobierz "$WEBIF/web/powerstate?newstate=4" > /dev/null; then
                        puls_od=$teraz
                        log "WAKEUP: impuls hotplug ok. $dl s"
                    fi
                fi
            fi
        fi
    fi

    if [ -n "$DIAG_LOG" ]; then
        [ -z "$d_od" ] && d_od=$teraz
        if [ "$TV_ZRODLO" = ping ]; then
            if [ "$hp" = y ]; then d_ok=$((d_ok + 1)); else d_brak=$((d_brak + 1)); fi
        fi
        d_stan="tv=${hp:-?} hotplug=${linia:-?} tmds=$(cat "$TMDS" 2>/dev/null)"
        [ "$d_stan" != "$d_poprz" ] && diag "ZMIANA $d_stan"
        d_poprz=$d_stan
        if [ $((teraz - d_od)) -ge "$DIAG_CO" ]; then
            diag "CO ${DIAG_CO}s $d_stan ping ok=$d_ok brak=$d_brak"
            d_od=$teraz d_ok=0 d_brak=0
        fi
    fi

    if [ "$hp" = n ]; then
        [ -z "$n_od" ] && n_od=$teraz
        ile=$((teraz - n_od))
        if [ $tv_off -eq 0 ] && [ $ile -ge "$TV_OFF_PO" ]; then
            tv_off=1
            log "TV wylaczony ($TV_ZRODLO n od $ile s)"
        fi
        if [ $uspiony -eq 0 ] && [ $ile -ge "$STANDBY_PO" ]; then
            case "$(box_standby)" in
            true)
                uspiony=1
                log "box juz w standby"
                ;;
            false)
                if pobierz "$WEBIF/web/powerstate?newstate=5" > /dev/null; then
                    uspiony=1
                    log "STANDBY: TV wylaczony od $ile s"
                fi
                ;;
            esac    # pusto: enigma2 nie odpowiada - sprobuje w nastepnym obiegu
        fi
    elif [ "$hp" = y ]; then
        if [ $tv_off -eq 1 ]; then
            case "$(box_standby)" in
            true)
                if pobierz "$WEBIF/web/powerstate?newstate=4" > /dev/null; then
                    tv_off=0
                    log "WAKEUP: TV wlaczony"
                fi
                ;;
            false)
                tv_off=0
                log "TV wlaczony, box nie spi"
                ;;
            esac    # pusto: enigma2 nie odpowiada - tv_off zostaje, ponowi
        fi
        n_od=
        uspiony=0
        puls_od=
    else
        n_od=   # nie wiadomo: wylaczenie liczy sie od nowa po pierwszym n
    fi

    # pobudka impulsem, a TV dalej n - impuls falszywy, box wraca do standby
    if [ -n "$puls_od" ] && [ "$hp" = n ] &&
       [ $((teraz - puls_od)) -ge "$PULS_SPRAWDZ" ]; then
        case "$(box_standby)" in
        true)
            puls_od=    # zasnal sam (CEC z TV, pilot)
            ;;
        false)
            if pobierz "$WEBIF/web/powerstate?newstate=5" > /dev/null; then
                log "STANDBY: po impulsie TV n od $((teraz - puls_od)) s"
                puls_od=
            fi
            ;;
        esac
    fi

    sleep "$POLL"
done
