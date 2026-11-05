# -*- coding: utf-8 -*-
"""Lista kanałów nc+ z BAT: wybór BAT, filtr pozycji, lamedb, bukiety, raport.

Bez zależności od enigmy (Python 2.7 i 3.x). Wtyczka podaje obiekt si.SI,
Lamedb i bukiety; tu nic nie jest zapisywane na dysk.
"""
from __future__ import unicode_literals

import collections

from si import TV_TYPY, RADIO_TYPY
from lamedb import namespace

# Kolejność zastępcza, gdy wybranego BAT nie ma w danych. 0xC024 = tylko Hot Bird
# (domyślny), 0xC023 = to samo + Astra, 0xC022 = bez 4K, 0x2020 = + NETFLIX, SERWISY INT.
BAT_DOMYSLNY = 0xC024
BAT_AUTO = (0xC024, 0xC023, 0xC022, 0x2020)
# Do menu wtyczki: (bouquet_id, opis)
BAT_MENU = [
    (0xC024, '0xC024 CANAL+ (Hot Bird)'),
    (0xC023, '0xC023 CANAL+ (Hot Bird + Astra)'),
    (0xC022, '0xC022 CANAL+ (bez 4K)'),
    (0x2020, '0x2020 CANAL+ (pełny)'),
    (0x2022, '0x2022 nc+ (stara numeracja)'),
]

# Bloki tematyczne numeracji CANAL+ (pomiar 2026-11-05): (od LCN, opis)
BLOKI = [
    (1, 'Podstawowe'),
    (31, 'CANAL+'),
    (49, 'Informacyjne i ogólne'),
    (71, 'Filmy i seriale'),
    (128, 'Dokumentalne'),
    (150, 'Dla dzieci'),
    (170, 'Sport'),
    (210, 'Lifestyle'),
    (235, 'Muzyczne'),
    (265, 'Zagraniczne i inne'),
    (300, 'Dla dorosłych'),
    (310, 'Radio'),
    (315, 'Zagraniczne i inne'),
    (550, 'Radio zagraniczne'),
]

Kanal = collections.namedtuple('Kanal', 'lcn onid tsid sid typ nazwa')


class Opcje(object):
    def __init__(self, bat=BAT_DOMYSLNY, zastepczy=True, pozycje=(130,), bez_4k=False,
                 powtorki=True, radio=True, radio_osobno=False, bloki=True, popraw_tp=True,
                 dostawca='CANAL+', miejsce='pierwszy', popraw_inne=False, bukiet=True):
        self.radio_osobno = radio_osobno  # False: radio w bukiecie TV, w kolejności LCN
        self.miejsce = miejsce            # MIEJSCA: gdzie bukiet na liście bukietów
        self.popraw_inne = popraw_inne    # podmieniać przeniesione kanały w ręcznych bukietach
        self.bukiet = bukiet              # False: bez bukietu CANAL+ (satelita), tylko lamedb i inne bukiety
        self.bat = bat                  # bouquet_id albo 'auto'
        self.zastepczy = zastepczy      # brak wybranego BAT -> pierwszy z BAT_AUTO
        self.pozycje = set(pozycje)
        self.bez_4k = bez_4k
        self.powtorki = powtorki
        self.radio = radio
        self.bloki = bloki
        self.popraw_tp = popraw_tp
        self.dostawca = dostawca


def norm(s):
    return ''.join((s or '').upper().split())


def wybierz_bat(si, opcje):
    if opcje.bat != 'auto':
        if opcje.bat in si.bat and si.bat[opcje.bat]['uslugi']:
            return opcje.bat
        if not opcje.zastepczy:
            return None
    for b in BAT_AUTO:
        if b in si.bat and si.bat[b]['uslugi']:
            return b
    return None


def _jest_4k(typ, nazwa):
    n = norm(nazwa)
    return typ == 0x1F or '4K' in n or 'UHD' in n


def lista(si, opcje):
    """-> (bat_id, [Kanal TV], [Kanal radio], {pominięte: liczba})."""
    bid = wybierz_bat(si, opcje)
    if bid is None:
        return None, [], [], {}
    bq = si.bat[bid]
    tv, radio = [], []
    pominiete = collections.Counter()
    for k, typ_bat in bq['uslugi'].items():
        onid, tsid, sid = k
        tp = si.nit.get((onid, tsid))
        if not tp or tp['poz'] not in opcje.pozycje:
            pominiete['inna pozycja / brak TP w NIT'] += 1
            continue
        s = si.sdt.get(k) or {}
        typ = s.get('typ') or typ_bat
        nazwa = s.get('nazwa') or ''
        lcn = bq['lcn'].get(k)
        if not nazwa:
            pominiete['brak w SDT'] += 1
            continue
        if lcn is None:
            pominiete['bez LCN'] += 1
            continue
        kanal = Kanal(lcn, onid, tsid, sid, typ, nazwa)
        if typ in TV_TYPY:
            if opcje.bez_4k and _jest_4k(typ, nazwa):
                pominiete['4K'] += 1
                continue
            tv.append(kanal)
        elif typ in RADIO_TYPY:
            radio.append(kanal)
        else:
            pominiete['typ 0x%02X' % typ] += 1
    tv.sort()
    radio.sort()
    if not opcje.powtorki:
        tv = _bez_powtorek(tv, pominiete)
        radio = _bez_powtorek(radio, pominiete)
    return bid, tv, radio, dict(pominiete)


def _bez_powtorek(kanaly, pominiete):
    widziane, out = set(), []
    for k in kanaly:                          # posortowane po LCN
        n = norm(k.nazwa)
        if n in widziane:
            pominiete['powtórka'] += 1
            continue
        widziane.add(n)
        out.append(k)
    return out


def uzupelnij_lamedb(db, si, kanaly, opcje):
    """Dopisuje do lamedb transpondery i usługi z listy. Zwraca db.zmiany."""
    tp_zrobione = set()
    for k in kanaly:
        tp = si.nit[(k.onid, k.tsid)]
        ns = namespace(tp['poz'])
        if (k.onid, k.tsid) not in tp_zrobione:
            db.dodaj_tp(ns, k.tsid, k.onid, tp, popraw=opcje.popraw_tp)
            tp_zrobione.add((k.onid, k.tsid))
        db.dodaj_usluge(k.sid, ns, k.tsid, k.onid, k.typ, k.nazwa, opcje.dostawca)
    return db.zmiany


def ref(k, poz):
    return '1:0:%X:%X:%X:%X:%X:0:0:0:' % (k.typ, k.sid, k.tsid, k.onid, namespace(poz))


def bukiety(tv, radio, si, opcje):
    """{plik: (lista bouquets.*, tekst)}; domyślnie jeden bukiet z TV i radiem wg LCN."""
    if opcje.radio and not opcje.radio_osobno:
        return {PLIK_TV: ('bouquets.tv', bukiet(NAZWA, sorted(tv + radio), si, opcje))}
    out = {PLIK_TV: ('bouquets.tv', bukiet(NAZWA, tv, si, opcje))}
    if opcje.radio:
        out[PLIK_RADIO] = ('bouquets.radio', bukiet(NAZWA_RADIO, radio, si, opcje, radio=True))
    return out


NAZWA = 'CANAL+ (satelita)'
NAZWA_RADIO = 'CANAL+ radio (satelita)'
PLIK_TV = 'userbouquet.ncplus_bat.tv'
PLIK_RADIO = 'userbouquet.ncplus_bat.radio'


def bukiet(nazwa, kanaly, si, opcje, radio=False):
    """Tekst userbouquet: kolejność wg LCN, znaczniki bloków, nazwa w każdym refie."""
    out = ['#NAME %s' % nazwa]
    blok = None
    znacznik = 0
    for k in kanaly:
        if opcje.bloki and not radio:
            b = [opis for od, opis in BLOKI if k.lcn >= od]
            b = b[-1] if b else None
            if b != blok:
                blok = b
                znacznik += 1
                out.append('#SERVICE 1:64:%d:0:0:0:0:0:0:0::%s' % (znacznik, b))
                out.append('#DESCRIPTION %s' % b)
        poz = si.nit[(k.onid, k.tsid)]['poz']
        nazwa_k = k.nazwa.replace(':', ' ')
        out.append('#SERVICE %s:%s' % (ref(k, poz), nazwa_k))
        out.append('#DESCRIPTION %s' % nazwa_k)
    return '\n'.join(out) + '\n'


MIEJSCA = ('pierwszy', 'ostatni', 'zawsze_pierwszy')


def dopisz_do_listy(tekst, plik, radio=False, miejsce='pierwszy'):
    """bouquets.tv/.radio z wpisem pliku. Zachowuje końce linii.

    miejsce: 'pierwszy' / 'ostatni' - gdzie wstawić nowy wpis; istniejący zostaje
    tam, gdzie go ktoś przestawił. 'zawsze_pierwszy' - przenosi go na górę za każdym razem.
    """
    nl = '\r\n' if '\r\n' in tekst else '\n'
    linie = tekst.split(nl)
    znak = '"%s"' % plik
    jest = [i for i, l in enumerate(linie) if znak in l]
    pierwsza = next((i for i, l in enumerate(linie) if l.startswith('#SERVICE ')), None)
    if jest:
        if miejsce != 'zawsze_pierwszy' or pierwsza is None or jest[0] == pierwsza:
            return tekst
        wpis = linie.pop(jest[0])
        linie.insert(pierwsza, wpis)
        return nl.join(linie)
    nr = 0                                     # 10. pole refa: kolejny wolny numer jak u enigmy
    for l in tekst.split('\n'):
        r = l[9:].split(':') if l.startswith('#SERVICE 1:7:') else []
        if len(r) > 9:
            try:
                nr = max(nr, int(r[9], 16) + 1)
            except ValueError:
                pass
    wpis = '#SERVICE 1:7:%d:0:0:0:0:0:0:%X:FROM BOUQUET "%s" ORDER BY bouquet' % (
        2 if radio else 1, nr, plik)
    if miejsce != 'ostatni' and pierwsza is not None:
        linie.insert(pierwsza, wpis)
        return nl.join(linie)
    if tekst and not tekst.endswith(nl):
        tekst += nl
    return tekst + wpis + nl


# --- przegląd ręcznych bukietów ---

def refy_bukietu(tekst):
    """[(nr linii, typ, sid, tsid, onid, ns, nazwa z refa lub #DESCRIPTION)] dla zwykłych usług DVB."""
    out = []
    L = tekst.replace('\r\n', '\n').split('\n')
    for i, l in enumerate(L):
        if not l.startswith('#SERVICE 1:0:'):
            continue
        r = l[9:].split(':')
        if len(r) < 10:
            continue
        try:
            typ, sid, tsid, onid, ns = [int(x, 16) for x in r[2:7]]
        except ValueError:
            continue
        nazwa = r[10] if len(r) > 10 and r[10] else ''
        if not nazwa and i + 1 < len(L) and L[i + 1].startswith('#DESCRIPTION '):
            nazwa = L[i + 1][13:]
        out.append((i + 1, typ, sid, tsid, onid, ns, nazwa))
    return out


def tp_operatora(db, dostawca='CANAL+'):
    """(onid, tsid), na których większość usług w lamedb ma dostawcę operatora."""
    licz = collections.defaultdict(collections.Counter)
    for k, (nazwa, dane) in db.uslugi.items():
        f = k.split(':')
        p = dane.split(',')[0]
        licz[(int(f[3], 16), int(f[2], 16))][p == 'p:' + dostawca] += 1
    return set(t for t, c in licz.items() if c[True] > c[False])


def martwe_refy(bukiety, si, db, wybrane, opcje):
    """Refy z ręcznych bukietów na TP operatora, których nie ma w SDT, z propozycją następcy.

    bukiety: {nazwa pliku: tekst}; wybrane: lista Kanal (do następców i LCN).
    """
    wlasne = tp_operatora(db, opcje.dostawca)
    po_nazwie = collections.defaultdict(list)
    for k in wybrane:
        po_nazwie[norm(k.nazwa)].append(k)
    wynik = []
    for plik in sorted(bukiety):
        for nr, typ, sid, tsid, onid, ns, nazwa in refy_bukietu(bukiety[plik]):
            if (ns >> 16) not in opcje.pozycje or (onid, tsid, sid) in si.sdt:
                continue
            if (onid, tsid) not in wlasne:
                continue
            if not nazwa:
                u = db.usluga(sid, ns, tsid, onid, typ)
                nazwa = u[1] if u else ''
            nastepcy = po_nazwie.get(norm(nazwa), [])
            wynik.append((plik, nr, '%X:%X:%X' % (sid, tsid, onid), nazwa, nastepcy))
    return wynik


def raport(bid, si, tv, radio, pominiete, zmiany, martwe, opcje):
    L = []
    if opcje.bat != 'auto' and opcje.bat != bid:
        L.append('UWAGA: wybranego BAT 0x%04X nie ma w danych, użyty zastępczy' % opcje.bat)
    L.append('BAT 0x%04X %s: TV %d, radio %d' % (bid, si.bat[bid]['nazwa'], len(tv), len(radio)))
    if pominiete:
        L.append('pominięte: ' + ', '.join('%s %d' % kv for kv in sorted(pominiete.items())))
    L.append('lamedb: transpondery nowe %d, poprawione %d; usługi nowe %d' % (
        len(zmiany['tp_nowe']), len(zmiany['tp_poprawione']), len(zmiany['uslugi_nowe'])))
    for k in zmiany['tp_nowe']:
        L.append('  + TP %s' % k)
    for k, stary, nowy in zmiany['tp_poprawione']:
        L.append('  ~ TP %s: %s -> %s' % (k, stary, nowy))
    L.append('martwe refy w ręcznych bukietach: %d' % len(martwe))
    for plik, nr, r, nazwa, nast in martwe:
        prop = ', '.join('%X:%X (LCN %d)' % (k.sid, k.tsid, k.lcn) for k in nast[:3])
        L.append('  %s:%d %s %s%s' % (plik, nr, r, nazwa, ' -> ' + prop if prop else ''))
    return '\n'.join(L) + '\n'
