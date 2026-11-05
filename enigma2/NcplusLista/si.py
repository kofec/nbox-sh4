# -*- coding: utf-8 -*-
"""Parser tabel DVB SI: NIT, SDT, BAT (EN 300 468).

Działa w Pythonie 2.7 (enigma2 na nBoxie) i 3.x (testy). Sekcje to bytes/str
z demuxa albo hex z si_zbierz.py; wewnątrz wszystko jako bytearray.
"""
from __future__ import unicode_literals

import binascii

TV_TYPY = (0x01, 0x11, 0x16, 0x19, 0x1F, 0x20)
RADIO_TYPY = (0x02, 0x0A)


def _b(sekcja):
    if isinstance(sekcja, bytearray):
        return sekcja
    if isinstance(sekcja, type('')):           # hex z si_zbierz.py
        return bytearray(binascii.unhexlify(sekcja.encode('ascii')))
    return bytearray(sekcja)


def tekst(b):
    """Tekst DVB (aneks A) -> unicode, bez znaków sterujących."""
    b = bytearray(b)
    if not b:
        return ''
    c = b[0]
    kod = 'iso6937'
    if c < 0x20:
        if 0x01 <= c <= 0x0B:
            kod, b = 'iso8859_%d' % (c + 4), b[1:]
        elif c == 0x10 and len(b) >= 3:
            kod, b = 'iso8859_%d' % b[2], b[3:]
        elif c == 0x15:
            kod, b = 'utf_8', b[1:]
        else:
            kod, b = 'latin_1', b[1:]
    if kod == 'iso6937':
        s = _iso6937(b)
    else:
        try:
            s = bytes(b).decode(kod, 'replace')
        except LookupError:
            s = bytes(b).decode('latin_1', 'replace')
    return ''.join(ch for ch in s if ch >= ' ' and not ('\x80' <= ch <= '\x9f')).strip()


# ISO 6937: znak diakrytyczny 0xC1-0xCF przed literą. Tylko to, co spotyka się
# w nazwach kanałów; reszta jak latin-1.
_AKCENTY = {0xC1: '\u0300', 0xC2: '\u0301', 0xC3: '\u0302', 0xC4: '\u0303', 0xC5: '\u0304',
            0xC6: '\u0306', 0xC7: '\u0307', 0xC8: '\u0308', 0xCA: '\u030a', 0xCB: '\u0327',
            0xCD: '\u030b', 0xCE: '\u0328', 0xCF: '\u030c'}


def _iso6937(b):
    import unicodedata
    out, i = [], 0
    while i < len(b):
        c = b[i]
        if c in _AKCENTY and i + 1 < len(b):
            out.append(unicodedata.normalize('NFC', chr_(b[i + 1]) + _AKCENTY[c]))
            i += 2
            continue
        out.append(chr_(c))
        i += 1
    return ''.join(out)


try:
    chr_ = unichr  # noqa: F821  (Python 2)
except NameError:
    chr_ = chr


def deskryptory(b, i, koniec):
    while i + 2 <= koniec:
        tag, n = b[i], b[i + 1]
        yield tag, b[i + 2:i + 2 + n]
        i += 2 + n


def _bcd(b):
    s = binascii.hexlify(bytes(b)).decode('ascii')
    return int(s.rstrip('f') or '0')


def dostawa_sat(b):
    """Deskryptor 0x43 -> parametry w enumach enigmy (eDVBFrontendParametersSatellite)."""
    poz = _bcd(b[4:6])                          # w dziesiątych stopnia
    if not (b[6] & 0x80):                       # west_east_flag = 0 -> zachód
        poz = 3600 - poz
    return {
        'czestotliwosc': _bcd(b[0:4]) * 10,     # kHz
        'poz': poz,                             # 130 = 13.0E
        'polaryzacja': (b[6] >> 5) & 3,         # 0 H, 1 V, 2 L, 3 R
        'rolloff': (b[6] >> 3) & 3,             # 0 0.35, 1 0.25, 2 0.20
        'system': (b[6] >> 2) & 1,              # 0 DVB-S, 1 DVB-S2
        'modulacja': b[6] & 3,                  # 0 auto, 1 QPSK, 2 8PSK, 3 16QAM
        # 7 cyfr BCD w setkach sym/s, ósmy półbajt to FEC
        'sr': int(binascii.hexlify(bytes(b[7:11])).decode('ascii')[:7]) * 100,
        'fec': b[10] & 0x0F,                    # 1 1/2 ... 9 9/10, 15 brak
    }


class SI(object):
    """Zebrane tabele: nit[(onid, tsid)] = parametry, sdt[(onid, tsid, sid)],
    bat[bouquet_id] = {'nazwa', 'uslugi': {(onid, tsid, sid): typ}, 'lcn': {...}}."""

    def __init__(self):
        self.sieci = {}     # network_id -> nazwa
        self.nit = {}       # (onid, tsid) -> dostawa_sat(...)
        self.sdt = {}       # (onid, tsid, sid) -> {'nazwa', 'dostawca', 'typ', 'kod', 'aktualny'}
        self.sdt_actual = set()  # (onid, tsid) z pełnym SDT actual
        self.bat = {}

    def dodaj(self, sekcja):
        d = _b(sekcja)
        if len(d) < 12:
            return
        tid = d[0]
        dl = min(len(d), 3 + (((d[1] & 0x0F) << 8) | d[2])) - 4   # bez CRC
        ext = (d[3] << 8) | d[4]
        if tid in (0x40, 0x41, 0x4A):
            self._nit_bat(d, tid, ext, dl)
        elif tid in (0x42, 0x46):
            self._sdt(d, tid, ext, dl)

    def _nit_bat(self, d, tid, ext, dl):
        n = ((d[8] & 0x0F) << 8) | d[9]
        nazwa = ''
        for tag, b in deskryptory(d, 10, 10 + n):
            if tag in (0x40, 0x47):
                nazwa = tekst(b)
        if tid == 0x4A:
            bq = self.bat.setdefault(ext, {'nazwa': nazwa, 'uslugi': {}, 'lcn': {}})
            bq['nazwa'] = bq['nazwa'] or nazwa
        else:
            self.sieci[ext] = self.sieci.get(ext) or nazwa
        i = 10 + n
        koniec = min(i + 2 + (((d[i] & 0x0F) << 8) | d[i + 1]), dl)
        i += 2
        while i + 6 <= koniec:
            tsid = (d[i] << 8) | d[i + 1]
            onid = (d[i + 2] << 8) | d[i + 3]
            m = ((d[i + 4] & 0x0F) << 8) | d[i + 5]
            for tag, b in deskryptory(d, i + 6, i + 6 + m):
                if tid != 0x4A and tag == 0x43 and len(b) >= 11:
                    self.nit[(onid, tsid)] = dostawa_sat(b)
                elif tid == 0x4A and tag == 0x41:
                    for j in range(0, len(b) - 2, 3):
                        bq['uslugi'][(onid, tsid, (b[j] << 8) | b[j + 1])] = b[j + 2]
                elif tid == 0x4A and tag == 0x83 and len(b) % 4 == 0:
                    for j in range(0, len(b), 4):
                        sid = (b[j] << 8) | b[j + 1]
                        bq['lcn'][(onid, tsid, sid)] = ((b[j + 2] & 0x03) << 8) | b[j + 3]
            i += 6 + m

    def _sdt(self, d, tid, tsid, dl):
        onid = (d[8] << 8) | d[9]
        if tid == 0x42:
            self.sdt_actual.add((onid, tsid))
        i = 11
        while i + 5 <= dl:
            sid = (d[i] << 8) | d[i + 1]
            n = ((d[i + 3] & 0x0F) << 8) | d[i + 4]
            rek = {'aktualny': tid == 0x42, 'kod': bool(d[i + 3] & 0x10),
                   'typ': None, 'nazwa': '', 'dostawca': ''}
            for tag, b in deskryptory(d, i + 5, i + 5 + n):
                if tag == 0x48 and len(b) >= 3:
                    pn = b[1]
                    rek['typ'] = b[0]
                    rek['dostawca'] = tekst(b[2:2 + pn])
                    rek['nazwa'] = tekst(b[3 + pn:3 + pn + b[2 + pn]])
            k = (onid, tsid, sid)
            if rek['aktualny'] or k not in self.sdt:   # actual wygrywa z other
                self.sdt[k] = rek
            i += 5 + n


def z_sekcji(sekcje):
    si = SI()
    for s in sekcje:
        si.dodaj(s)
    return si
