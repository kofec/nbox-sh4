# -*- coding: utf-8 -*-
"""Aktualizacja bukietu z zachowaniem zmian użytkownika i poprawa przeniesionych kanałów.

Bukiet „CANAL+ (satelita)” może być edytowany w enigmie (kolejność, usunięcia,
własne kanały i znaczniki). Enigma przy zapisie przepisuje plik, więc to, co
wtyczka wpisała, pamiętamy w osobnym pliku stanu (JSON):

    {"wersja": 1, "bat": 49188,
     "kanaly": {"1:0:1:1131:2AF8:13E:820000:0:0:0": [1, "CANAL+ 360"], ...},
     "zaproponowane": [[1, "CANAL+360"], ...]}

kanaly        - refy wpisane przez wtyczkę -> [LCN, nazwa] z chwili wpisania
zaproponowane - (LCN, nazwa znormalizowana) wszystkich kanałów z BAT przy ostatniej
                aktualizacji; kanał stąd, którego nie ma w bukiecie, ktoś usunął.

Rozpoznanie kanału z bukietu w nowej liście: ten sam ref -> ta sama nazwa (przy
kilku: ten sam LCN, potem najbliższy) -> brak = zniknął.
"""
from __future__ import unicode_literals

import json

from budowa import BLOKI, NAZWA, bukiet, norm, ref as ref_kanalu

WERSJA_STANU = 1


def ref_bez_nazwy(linia):
    """'#SERVICE 1:0:1:...:0:0:0::NAZWA' -> '1:0:1:...:0:0:0' (10 pól, wielkie litery)."""
    r = linia[9:].split(':')
    return ':'.join(x.upper() for x in r[:10]) if len(r) >= 10 else None


def _ref(k, si):
    return ref_kanalu(k, si.nit[(k.onid, k.tsid)]['poz']).rstrip(':').upper()


def _wpis(k, si, nl):
    nazwa = k.nazwa.replace(':', ' ')
    return ['#SERVICE %s::%s' % (_ref(k, si), nazwa), '#DESCRIPTION %s' % nazwa]


def wczytaj_stan(tekst):
    try:
        s = json.loads(tekst)
    except (ValueError, TypeError):
        return None
    if not isinstance(s, dict) or s.get('wersja') != WERSJA_STANU:
        return None
    return s


def stan_json(stan):
    return json.dumps(stan, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _klucz_propozycji(k):
    return [k.lcn, norm(k.nazwa)]


def nowy_stan(bid, kanaly, si, wpisane):
    return {
        'wersja': WERSJA_STANU,
        'bat': bid,
        'kanaly': dict((_ref(k, si), [k.lcn, k.nazwa]) for k in wpisane),
        'zaproponowane': sorted(_klucz_propozycji(k) for k in kanaly),
    }


def _bloki_jednostki(linie):
    """Linie bukietu -> nagłówek i jednostki: [linia #SERVICE, (#DESCRIPTION)] albo inne."""
    naglowek, jednostki = [], []
    i = 0
    while i < len(linie) and not linie[i].startswith('#SERVICE'):
        naglowek.append(linie[i])
        i += 1
    while i < len(linie):
        j = [linie[i]]
        if linie[i].startswith('#SERVICE') and i + 1 < len(linie) and linie[i + 1].startswith('#DESCRIPTION'):
            j.append(linie[i + 1])
            i += 1
        jednostki.append(j)
        i += 1
    return naglowek, jednostki


def scal(tekst, stan, bid, kanaly, si, opcje):
    """-> (nowy tekst bukietu, nowy stan, raport: dict list).

    tekst/stan None (pierwszy raz albo zgubiony stan) = nowy bukiet z BAT.
    """
    raport = {'przeniesione': [], 'zniknely': [], 'nowe': [], 'nowy_numer': [],
              'usuniete_przez_uzytkownika': 0}
    if not tekst or not stan:
        return bukiet(NAZWA, kanaly, si, opcje), nowy_stan(bid, kanaly, si, kanaly), raport

    nl = '\r\n' if '\r\n' in tekst else '\n'
    linie = tekst.split(nl)
    while linie and linie[-1] == '':
        linie.pop()
    naglowek, jednostki = _bloki_jednostki(linie)

    po_refie = dict((_ref(k, si), k) for k in kanaly)
    po_nazwie = {}
    for k in kanaly:
        po_nazwie.setdefault(norm(k.nazwa), []).append(k)
    uzyte = set()          # refy z nowej listy już obecne w bukiecie
    nasze = {}             # id(jednostka) -> Kanal (do wstawiania wg LCN i nowego stanu)
    stare = stan.get('kanaly', {})
    wynik = []

    for j in jednostki:
        l = j[0]
        r = ref_bez_nazwy(l) if l.startswith('#SERVICE 1:0:') else None
        if r is None:
            wynik.append(j)                       # znaczniki, podbukiety, inne
            continue
        if r in po_refie:                         # bez zmian (może nowa nazwa / numer)
            k = po_refie[r]
            if r in stare:
                lcn0, nazwa0 = stare[r]
                if lcn0 != k.lcn:
                    raport['nowy_numer'].append((k.nazwa, lcn0, k.lcn))
                if nazwa0 != k.nazwa:
                    j = _wpis(k, si, nl)
                nasze[id(j)] = k
            uzyte.add(r)
            wynik.append(j)
            continue
        if r not in stare:
            wynik.append(j)                       # dodany ręcznie spoza nc+ - nie ruszamy
            continue
        lcn0, nazwa0 = stare[r]
        kand = [k for k in po_nazwie.get(norm(nazwa0), []) if _ref(k, si) not in uzyte]
        if kand:
            kand.sort(key=lambda k: (k.lcn != lcn0, abs(k.lcn - lcn0), k.lcn))
            k = kand[0]
            j = _wpis(k, si, nl)
            raport['przeniesione'].append((nazwa0, r, _ref(k, si)))
            uzyte.add(_ref(k, si))
            nasze[id(j)] = k
            wynik.append(j)
        else:
            raport['zniknely'].append((nazwa0, r))

    zaproponowane = set(tuple(x) for x in stan.get('zaproponowane', []))
    for k in kanaly:                              # posortowane po LCN
        if _ref(k, si) in uzyte:
            continue
        if tuple(_klucz_propozycji(k)) in zaproponowane:
            raport['usuniete_przez_uzytkownika'] += 1
            continue
        j = _wpis(k, si, nl)
        poz = _gdzie_wstawic(wynik, nasze, k.lcn)
        wynik.insert(poz, j)
        nasze[id(j)] = k
        uzyte.add(_ref(k, si))
        raport['nowe'].append((k.lcn, k.nazwa))

    out = list(naglowek)
    for j in wynik:
        out.extend(j)
    wpisane = [nasze[id(j)] for j in wynik if id(j) in nasze]
    return nl.join(out) + nl, nowy_stan(bid, kanaly, si, wpisane), raport


def _gdzie_wstawic(wynik, nasze, lcn):
    """Za kanałem z największym LCN < lcn (w kolejności użytkownika); bez takiego -
    przed kanałem z najmniejszym LCN > lcn; bez obu - na koniec."""
    za, przed = None, None
    for i, j in enumerate(wynik):
        k = nasze.get(id(j))
        if k is None:
            continue
        if k.lcn < lcn and (za is None or k.lcn > nasze[id(wynik[za])].lcn):
            za = i
        if k.lcn > lcn and (przed is None or k.lcn < nasze[id(wynik[przed])].lcn):
            przed = i
    if za is not None:
        return za + 1
    if przed is not None:
        return przed
    return len(wynik)


# --- ręczne bukiety ---

def popraw_przeniesione(tekst, martwe_w_pliku):
    """Podmienia martwe refy na następców (ten sam kanał, inny SID/TP).

    martwe_w_pliku: [(nr linii, ref, nazwa, [Kanal następcy])] z budowa.martwe_refy.
    Następca: najniższy LCN wśród kanałów o tej samej nazwie. Pozycja, końce linii
    i reszta pliku bez zmian; ref dostaje nazwę (bez niej enigma pokazuje <n/a>,
    gdy typ w refie różni się od lamedb).
    -> (nowy tekst, [(nr linii, stary ref, nowy ref, nazwa)])
    """
    nl = '\r\n' if '\r\n' in tekst else '\n'
    linie = tekst.split(nl)
    zmiany = []
    for nr, _, nazwa, nastepcy in martwe_w_pliku:
        if not nastepcy:
            continue
        k = sorted(nastepcy, key=lambda x: x.lcn)[0]
        l = linie[nr - 1]
        stary = ref_bez_nazwy(l)
        r = l[9:].split(':')
        nazwa_l = r[10] if len(r) > 10 and r[10] else (nazwa or k.nazwa).replace(':', ' ')
        nowy = '1:0:%X:%X:%X:%X:%s:0:0:0' % (k.typ, k.sid, k.tsid, k.onid, r[6])
        linie[nr - 1] = '#SERVICE %s::%s' % (nowy, nazwa_l)
        zmiany.append((nr, stary, nowy.upper(), nazwa_l))
    return nl.join(linie), zmiany
