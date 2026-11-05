# -*- coding: utf-8 -*-
"""lamedb w formacie /4/ (enigma2 OpenPLi 4): odczyt, dopisywanie, zapis.

Zasada: niczego nie usuwamy i nie zmieniamy kolejności. Istniejące bloki
zostają co do bajtu; nowe transpondery i usługi idą na koniec swojej sekcji,
a poprawka transpondera podmienia tylko jego linię parametrów.
"""
from __future__ import unicode_literals

import io


def klucz_tp(ns, tsid, onid):
    return '%08x:%04x:%04x' % (ns, tsid, onid)


def klucz_uslugi(sid, ns, tsid, onid, typ):
    return '%04x:%08x:%04x:%04x:%d:0' % (sid, ns, tsid, onid, typ)


def namespace(poz):
    """Namespace DVB-S dla pozycji w dziesiątych stopnia (130 -> 0x00820000)."""
    return (poz & 0xFFFF) << 16


class Lamedb(object):
    def __init__(self, tekst):
        L = tekst.split('\n')
        if not L[0].startswith('eDVB services /4/'):
            raise ValueError('to nie jest lamedb /4/: %r' % L[0][:40])
        i = L.index('transponders') + 1
        # transpondery: klucz -> [indeks linii parametrów]
        self.tp = {}
        self.tp_kolejnosc = []
        self._tp_linie = {}
        while L[i] != 'end':
            k = L[i]
            self.tp_kolejnosc.append(k)
            self._tp_linie[k] = [L[i + 1]]
            self.tp[k] = parsuj_tp(L[i + 1])
            i += 3                                      # klucz, parametry, "/"
        self._po_tp = i
        j = L.index('services', i) + 1
        self.uslugi = {}                                # klucz -> (nazwa, dane)
        self.us_kolejnosc = []
        while L[j] != 'end':
            self.uslugi[L[j]] = (L[j + 1], L[j + 2])
            self.us_kolejnosc.append(L[j])
            j += 3
        self._naglowek = L[:L.index('transponders') + 1]
        self._ogon = L[j:]                              # "end", "Have a lot of bugs!", ""
        self.zmiany = {'tp_nowe': [], 'tp_poprawione': [], 'uslugi_nowe': []}

    # Plik czytamy jako bajty i dekodujemy latin-1 (bijekcja), więc zapis oddaje
    # dokładnie te same bajty, także przy błędnym UTF-8. Nazwy dla wywołującego
    # zamienia _nazwa(), nowe nazwy koduje _l1().
    @classmethod
    def z_pliku(cls, sciezka):
        with io.open(sciezka, 'rb') as f:
            return cls(f.read().decode('latin-1'))

    # --- odczyt ---
    def usluga(self, sid, ns, tsid, onid, typ=None):
        """(klucz, nazwa) usługi; typ None = dowolny (TV przed radiem)."""
        if typ is not None:
            k = klucz_uslugi(sid, ns, tsid, onid, typ)
            return (k, _nazwa(self.uslugi[k][0])) if k in self.uslugi else None
        pref = '%04x:%08x:%04x:%04x:' % (sid, ns, tsid, onid)
        traf = [k for k in self.uslugi if k.startswith(pref)]
        traf.sort(key=lambda k: k.split(':')[4] == '2')
        return (traf[0], _nazwa(self.uslugi[traf[0]][0])) if traf else None

    # --- zmiany ---
    def dodaj_tp(self, ns, tsid, onid, par, popraw=True):
        """Dopisuje transponder albo poprawia jego parametry. Zwraca 'nowy', 'poprawiony' albo None."""
        k = klucz_tp(ns, tsid, onid)
        if k not in self.tp:
            self.tp[k] = dict(par, inwersja=2, flagi=0, pilot=2)
            self._tp_linie[k] = [linia_tp(self.tp[k])]
            self.tp_kolejnosc.append(k)
            self.zmiany['tp_nowe'].append(k)
            return 'nowy'
        if not popraw:
            return None
        stary = self.tp[k]
        if 'inny' in stary:
            return None
        # Rolloff demodulator DVB-S2 wykrywa sam, a NIT podaje częstotliwość
        # zaokrągloną do MHz - takie różnice nie są powodem do zmiany.
        pola = ('polaryzacja', 'fec', 'poz', 'system')
        if stary['system'] == 1 or par['system'] == 1:
            pola += ('modulacja',)
        rozne = [p for p in pola if stary.get(p) != par.get(p)]
        if abs(stary['czestotliwosc'] - par['czestotliwosc']) > 2000:
            rozne.append('czestotliwosc')
        if abs(stary['sr'] - par['sr']) > 1000:
            rozne.append('sr')
        if not rozne:
            return None
        nowy = dict(stary)
        for p in pola + ('czestotliwosc', 'sr', 'rolloff'):
            nowy[p] = par[p]
        if nowy['system'] == 1:
            nowy.setdefault('pilot', 2)
        self.tp[k] = nowy
        self._tp_linie[k] = [linia_tp(nowy)]
        self.zmiany['tp_poprawione'].append((k, linia_tp(stary).strip(), linia_tp(nowy).strip()))
        return 'poprawiony'

    def dodaj_usluge(self, sid, ns, tsid, onid, typ, nazwa, dostawca):
        k = klucz_uslugi(sid, ns, tsid, onid, typ)
        if k in self.uslugi:
            return False
        self.uslugi[k] = (_l1(nazwa), _l1('p:%s' % dostawca.replace(',', ' ')))
        self.us_kolejnosc.append(k)
        self.zmiany['uslugi_nowe'].append(k)
        return True

    # --- zapis ---
    def tekst(self):
        out = list(self._naglowek)
        for k in self.tp_kolejnosc:
            out.append(k)
            out.extend(self._tp_linie[k])
            out.append('/')
        out.append('end')
        out.append('services')
        for k in self.us_kolejnosc:
            out.append(k)
            out.extend(self.uslugi[k])
        out.extend(self._ogon)
        return '\n'.join(out)

    def bajty(self):
        return self.tekst().encode('latin-1')

    def tekst5(self):
        """Ta sama baza w formacie /5/ (lamedb5), którą enigma zapisuje obok lamedb."""
        out = [NAGLOWEK5]
        for k in self.tp_kolejnosc:
            par = self._tp_linie[k][0].strip()
            out.append('t:%s,%s' % (k, par[0] + ':' + par[2:]))
        for k in self.us_kolejnosc:
            nazwa, dane = self.uslugi[k]
            pola = [_pole5(p) for p in dane.split(',') if p and p != 'p:']
            out.append('s:%s,"%s"%s' % (k, nazwa, ''.join(',' + p for p in pola)))
        out.append('# done. %d channels and %d services' % (len(self.tp_kolejnosc), len(self.us_kolejnosc)))
        return '\n'.join(out) + '\n'

    def zapisz5(self, sciezka):
        with io.open(sciezka, 'wb') as f:
            f.write(self.tekst5().encode('latin-1'))

    def zapisz(self, sciezka):
        with io.open(sciezka, 'wb') as f:
            f.write(self.bajty())


NAGLOWEK5 = '\n'.join([
    'eDVB services /5/',
    '# Transponders: t:dvb_namespace:transport_stream_id:original_network_id,FEPARMS',
    '#     DVBS  FEPARMS:   s:frequency:symbol_rate:polarisation:fec:orbital_position:inversion:flags',
    '#     DVBS2 FEPARMS:   s:frequency:symbol_rate:polarisation:fec:orbital_position:inversion:flags:system:modulation:rolloff:pilot',
    '#     DVBT  FEPARMS:   t:frequency:bandwidth:code_rate_HP:code_rate_LP:modulation:transmission_mode:guard_interval:hierarchy:inversion:flags:system:plp_id',
    '#     DVBC  FEPARMS:   c:frequency:symbol_rate:inversion:modulation:fec_inner:flags:system',
    '#     ATSC  FEPARMS:   a:frequency:inversion:modulation:flags:system',
    '# Services    : s:service_id:dvb_namespace:transport_stream_id:original_network_id:service_type:0,"service_name"[,p:provider_name][,c:cached_pid]*[,C:cached_capid]*[,f:flags]',
])


def _pole5(p):
    """Pole danych usługi /4/ -> /5/: c:TTPPPP -> c:%02x%x, C:XXXX -> C:%x."""
    if p.startswith('c:') and len(p) == 8:
        try:
            return 'c:%02x%x' % (int(p[2:4], 16), int(p[4:], 16))
        except ValueError:
            return p
    if p.startswith('C:'):
        try:
            return 'C:%x' % int(p[2:], 16)
        except ValueError:
            return p
    return p


def _l1(s):
    return s.encode('utf-8').decode('latin-1')


def _nazwa(s):
    return s.encode('latin-1').decode('utf-8', 'replace')


def parsuj_tp(linia):
    """'\ts f:sr:pol:fec:poz:inw:flagi[:system:mod:rolloff:pilot]' -> dict."""
    s = linia.strip()
    if not s.startswith('s '):
        return {'inny': s}
    p = [int(x) for x in s[2:].split(':')]
    d = {'czestotliwosc': p[0], 'sr': p[1], 'polaryzacja': p[2], 'fec': p[3], 'poz': p[4],
         'inwersja': p[5], 'flagi': p[6], 'system': 0, 'modulacja': 1, 'rolloff': 0, 'pilot': 2}
    if len(p) >= 11:
        d.update(system=p[7], modulacja=p[8], rolloff=p[9], pilot=p[10])
    return d


def linia_tp(d):
    if 'inny' in d:
        return '\t' + d['inny']
    s = '\ts %d:%d:%d:%d:%d:%d:%d' % (d['czestotliwosc'], d['sr'], d['polaryzacja'], d['fec'],
                                      d['poz'], d.get('inwersja', 2), d.get('flagi', 0))
    if d['system'] == 1:
        s += ':%d:%d:%d:%d' % (1, d['modulacja'], d['rolloff'], d.get('pilot', 2))
    return s
