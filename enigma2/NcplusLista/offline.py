# -*- coding: utf-8 -*-
"""Przebieg wtyczki poza enigmą: zrzut SI + kopia /etc/enigma2 -> zmienione pliki i raport.

    python offline.py ZRZUT_SI.json KATALOG_ENIGMA2 WYJSCIE [--bat C024|2020|auto]
        [--bez-4k] [--bez-powtorek] [--radio-osobno]
        [--miejsce pierwszy|ostatni|zawsze_pierwszy] [--popraw-inne] [--bez-bukietu]

KATALOG_ENIGMA2 to kopia /etc/enigma2 (lamedb, bouquets.*, userbouquet.*,
ewentualnie ncpluslista.json i userbouquet.ncplus_bat.tv z poprzedniego przebiegu).
Nic w nim nie zmienia; do WYJSCIE trafiają tylko pliki, które wtyczka by zapisała,
oraz raport.txt. Kolejny przebieg: skopiuj WYJSCIE na KATALOG_ENIGMA2.
"""
from __future__ import print_function, unicode_literals

import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import si as si_mod          # noqa: E402
import budowa                # noqa: E402
import przebieg              # noqa: E402

CZYTANE = ('lamedb', 'bouquets.tv', 'bouquets.radio', przebieg.PLIK_STANU)


def wczytaj_katalog(kat):
    pliki = {}
    for n in os.listdir(kat):
        if n in CZYTANE or (n.startswith('userbouquet.') and (n.endswith('.tv') or n.endswith('.radio'))):
            with io.open(os.path.join(kat, n), 'rb') as f:
                pliki[n] = f.read()
    return pliki


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('si')
    ap.add_argument('enigma2')
    ap.add_argument('wyjscie')
    ap.add_argument('--bat', default='%X' % budowa.BAT_DOMYSLNY, help="bouquet_id hex albo 'auto'")
    ap.add_argument('--bez-4k', action='store_true')
    ap.add_argument('--bez-powtorek', action='store_true')
    ap.add_argument('--radio-osobno', action='store_true', help='radio w osobnym bukiecie radiowym')
    ap.add_argument('--miejsce', default='pierwszy', choices=budowa.MIEJSCA)
    ap.add_argument('--bez-bukietu', action='store_true', help='nie tworz bukietu CANAL+ (satelita)')
    ap.add_argument('--popraw-inne', action='store_true',
                    help='podmieniaj przeniesione kanały w ręcznych bukietach')
    a = ap.parse_args()

    opcje = budowa.Opcje(bat=a.bat if a.bat == 'auto' else int(a.bat, 16),
                         bez_4k=a.bez_4k, powtorki=not a.bez_powtorek, radio_osobno=a.radio_osobno,
                         miejsce=a.miejsce, popraw_inne=a.popraw_inne, bukiet=not a.bez_bukietu)
    with io.open(a.si, encoding='utf-8') as f:
        si = si_mod.z_sekcji(json.load(f)['sekcje'])
    do_zapisu, raport = przebieg.aktualizuj(si, wczytaj_katalog(a.enigma2), opcje)

    if not os.path.isdir(a.wyjscie):
        os.makedirs(a.wyjscie)
    for n, b in sorted(do_zapisu.items()):
        with io.open(os.path.join(a.wyjscie, n), 'wb') as f:
            f.write(b)
    raport += 'pliki do zapisu: %s\n' % (', '.join(sorted(do_zapisu)) or 'brak')
    with io.open(os.path.join(a.wyjscie, 'raport.txt'), 'wb') as f:
        f.write(raport.encode('utf-8'))
    sys.stdout.write(raport if sys.version_info[0] >= 3 else raport.encode('utf-8'))
    return 0 if do_zapisu or 'BŁĄD' not in raport else 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
