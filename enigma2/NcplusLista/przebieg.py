# -*- coding: utf-8 -*-
"""Jeden przebieg aktualizacji: pliki /etc/enigma2 na wejściu -> pliki do zapisu + raport.

Wspólne dla wtyczki i offline.py. Nic tu nie czyta ani nie pisze dysku: wejście to
słownik {nazwa pliku: bajty}, wyjście to słownik plików do zapisania (tylko zmienione).
"""
from __future__ import unicode_literals

import json

import budowa
import scalanie
from lamedb import Lamedb

PLIK_STANU = 'ncpluslista.json'


def _t(b):
    return b.decode('utf-8', 'replace') if b is not None else None


def aktualizuj(si, pliki, opcje):
    """-> (do_zapisu {nazwa: bajty}, raport tekst). Pusty do_zapisu = brak zmian lub błąd."""
    bid, tv, radio, pominiete = budowa.lista(si, opcje)
    if bid is None:
        return {}, 'BŁĄD: w danych nie ma BAT 0x%X ani zastępczego\n' % opcje.bat
    db = Lamedb(pliki['lamedb'].decode('latin-1'))
    przed = pliki['lamedb']

    # martwe refy w ręcznych bukietach liczone na lamedb sprzed zmian
    wlasne_pliki = (budowa.PLIK_TV, budowa.PLIK_RADIO)
    reczne = dict((n, _t(b)) for n, b in pliki.items()
                  if n.startswith('userbouquet.') and n.endswith('.tv') and n not in wlasne_pliki)
    martwe = budowa.martwe_refy(reczne, si, db, tv + radio, opcje)
    zmiany = budowa.uzupelnij_lamedb(db, si, tv + (radio if opcje.radio else []), opcje)

    do_zapisu = {}
    if db.bajty() != przed:
        do_zapisu['lamedb'] = db.bajty()
        do_zapisu['lamedb5'] = db.tekst5().encode('latin-1')

    # własne bukiety: scalanie z tym, co jest na boxie, i stan
    stary_stan = (json.loads(_t(pliki[PLIK_STANU])) if PLIK_STANU in pliki else {}) or {}
    if not isinstance(stary_stan, dict):
        stary_stan = {}
    stan = {'wersja': 1, 'pliki': {}}
    rap_scal = {}
    # bez bukietu z satelity: nie tworzymy go, nie ruszamy istniejącego ani
    # bouquets.*, ani pliku stanu (gdyby ktoś opcję potem włączył - stan z ostatniego razu)
    zestaw = []
    if opcje.bukiet:
        zestaw.append((budowa.PLIK_TV, 'bouquets.tv',
                       sorted(tv + radio) if opcje.radio and not opcje.radio_osobno else tv))
        if opcje.radio and opcje.radio_osobno:
            zestaw.append((budowa.PLIK_RADIO, 'bouquets.radio', radio))
    for plik, lista_plik, kanaly in zestaw:
        st = scalanie.wczytaj_stan(json.dumps(stary_stan.get('pliki', {}).get(plik)))
        tekst, nst, r = scalanie.scal(_t(pliki.get(plik)), st, bid, kanaly, si, opcje)
        if plik == budowa.PLIK_RADIO and not _t(pliki.get(plik)):
            tekst = tekst.replace('#NAME ' + budowa.NAZWA, '#NAME ' + budowa.NAZWA_RADIO, 1)
        stan['pliki'][plik] = nst
        rap_scal[plik] = r
        nowy = tekst.encode('utf-8')
        if nowy != pliki.get(plik):
            do_zapisu[plik] = nowy
        if lista_plik in pliki:
            lt = budowa.dopisz_do_listy(_t(pliki[lista_plik]), plik, lista_plik.endswith('.radio'),
                                        opcje.miejsce).encode('utf-8')
            if lt != pliki[lista_plik]:
                do_zapisu[lista_plik] = lt

    # ręczne bukiety: podmiana przeniesionych kanałów (opcja)
    poprawione = []
    if opcje.popraw_inne:
        for n in sorted(reczne):
            m = [(nr, r, nazwa, nast) for p, nr, r, nazwa, nast in martwe if p == n]
            if not m:
                continue
            nowy, z = scalanie.popraw_przeniesione(reczne[n], m)
            if z:
                do_zapisu[n] = nowy.encode('utf-8')
                poprawione.extend((n,) + x for x in z)

    if opcje.bukiet:
        s = scalanie.stan_json(stan).encode('utf-8')
        if s != pliki.get(PLIK_STANU):
            do_zapisu[PLIK_STANU] = s

    raport = budowa.raport(bid, si, tv, radio, pominiete, zmiany, martwe, opcje)
    if not opcje.bukiet:
        raport += 'bukiet %s: wyłączony w ustawieniach (nie tworzony, istniejący bez zmian)\n' % budowa.NAZWA
    raport += _raport_scalania(rap_scal, poprawione, opcje)
    return do_zapisu, raport


def _raport_scalania(rap_scal, poprawione, opcje):
    L = []
    for plik, r in sorted(rap_scal.items()):
        L.append('%s: nowe %d, przeniesione %d, zniknęły %d, nowe numery %d, '
                 'usunięte przez użytkownika (nie dodaję) %d' % (
                     plik, len(r['nowe']), len(r['przeniesione']), len(r['zniknely']),
                     len(r['nowy_numer']), r['usuniete_przez_uzytkownika']))
        for lcn, nazwa in r['nowe']:
            L.append('  + %d %s' % (lcn, nazwa))
        for nazwa, stary, nowy in r['przeniesione']:
            L.append('  ~ %s %s -> %s' % (nazwa, stary, nowy))
        for nazwa, stary in r['zniknely']:
            L.append('  - %s %s' % (nazwa, stary))
        for nazwa, a, b in r['nowy_numer']:
            L.append('  # %s %d -> %d' % (nazwa, a, b))
    if opcje.popraw_inne:
        L.append('zaktualizowane parametry kanałów w pozostałych bukietach: %d' % len(poprawione))
        for plik, nr, stary, nowy, nazwa in poprawione:
            L.append('  %s:%d %s %s -> %s' % (plik, nr, nazwa, stary, nowy))
    return '\n'.join(L) + '\n' if L else ''
