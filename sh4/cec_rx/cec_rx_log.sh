#!/bin/sh
#
# cec_rx_log.sh - co CO s dopisuje nowe ramki z /proc/cec_rx (modul cec_rx.ko)
# do $LOG, z czasem lokalnym na poczatku linii:
#   2026-10-21 09:10:11.123 <nr> <epoch.ms> 3>0 30+ 8f+
# Odpytywanie bez odpowiedzi (sam naglowek, NACK - TV szuka urzadzen, Sony
# co 15 s adresy 1-E) idzie jedna linia na obieg zamiast linii na
# ramke: "<czas> polling NACK xN: 0>1 0>2 ...". Raz na godzine linia "#" ze
# statystyka modulu. Bez modulu czeka. Po LOG_MAX liniach log -> $LOG.1.
# Stop: kill $(cat /tmp/cec_rx_log.pid).
#
# Start (osobnym ssh, bo & w jednym ssh z wgraniem daje pusty plik):
#   nohup sh /tmp/cec_rx_log.sh >/dev/null 2>&1 &

LOG="${LOG:-/tmp/cec_rx.log}"
CO="${CO:-15}"
LOG_MAX="${LOG_MAX:-20000}"
PIDF="${PIDF:-/tmp/cec_rx_log.pid}"
PROC="${PROC:-/proc/cec_rx}"
ZRZUT="${ZRZUT:-/tmp/cec_rx.zrzut}"

echo $$ > "$PIDF"
trap '[ "$(cat "$PIDF" 2>/dev/null)" = "$$" ] && rm -f "$PIDF"; rm -f "$ZRZUT"; exit 0' TERM INT

# po restarcie loggera dalej od ostatniej ramki w logu (pole 3 = nr)
ost=$(awk '$3 ~ /^[0-9]+$/ && $4 ~ /^[0-9]+\.[0-9]+$/ { n = $3 } END { print n + 0 }' "$LOG" 2>/dev/null)
licz=0
echo "$(date '+%F %T') start pid $$ od ramki $ost" >> "$LOG"
while :; do
    # jeden odczyt na obieg - nr ostatniej ramki z tego samego zrzutu, ktory
    # idzie do logu (dwa odczyty dublowaly ramki zamkniete miedzy nimi)
    if cat "$PROC" > "$ZRZUT" 2>/dev/null; then
        maks=$(awk '!/^#/ { m = $1 } END { print m + 0 }' "$ZRZUT")
        # nr mniejszy niz ostatni = modul przeladowany, liczymy od nowa
        [ "$maks" -lt "$ost" ] && ost=0
        awk -v ost="$ost" -v teraz="$(date '+%F %T')" '
            !/^#/ && $1 + 0 > ost {
                if (NF == 4 && $4 ~ /^[0-9a-f][0-9a-f]-$/) {
                    n++
                    if (!(($3) in byl)) { byl[$3] = 1; lista = lista " " $3 }
                    next
                }
                split($2, t, ".")
                print strftime("%Y-%m-%d %H:%M:%S", t[1]) "." t[2], $0
            }
            END { if (n) print teraz " polling NACK x" n ":" lista }
        ' "$ZRZUT" >> "$LOG"
        ost=$maks
        if [ $((licz % (3600 / CO))) -eq 0 ]; then
            echo "$(date '+%F %T') $(head -1 "$ZRZUT")" >> "$LOG"
        fi
    fi
    licz=$((licz + 1))
    if [ "$(wc -l < "$LOG")" -gt "$LOG_MAX" ]; then
        mv "$LOG" "$LOG.1"
    fi
    sleep "$CO"
done
