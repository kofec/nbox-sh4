# -*- coding: utf-8 -*-
#
# nBox kopia - logika bez enigmy (Python 2.7 na boxie, 3 w testach na PC):
# kopie na dyskach, opisy, ktore czesci wymagaja restartu, termin kopii
# automatycznej. Robote na plikach robi /usr/bin/nbox_kopia (skrypty/nbox_kopia.sh).

import os
import time

PODKAT = 'nbox_kopia'
CZESCI = ('kanaly', 'enigma', 'oscam', 'siec', 'system', 'pakiety')
NAZWY = {
    'kanaly': 'Kanały i bukiety',
    'enigma': 'Ustawienia enigmy, timery, picony',
    'oscam': 'Oscam (konfiguracja i binarka)',
    'siec': 'Sieć: adres, fstab, NFS',
    'system': 'System: rc.local, /root, usługi, crontab',
    'pakiety': 'Nasze pakiety (.ipk)',
}
BEZ_RESTARTU = ('kanaly', 'oscam')
OKRES = {'dzien': 1, 'tydzien': 7}
NIEDZIELA = 6                   # time.struct_time.tm_wday


def czytaj_info(kat):
    """Pola info.txt kopii albo None, gdy to nie kopia nbox_kopia."""
    try:
        with open(os.path.join(kat, 'info.txt')) as f:
            linie = f.read().splitlines()
    except (IOError, OSError):
        return None
    info = {}
    for l in linie:
        if '=' in l:
            k, v = l.split('=', 1)
            info[k] = v
    if 'data' not in info:
        return None
    info['czesci'] = info.get('czesci', '').split()
    return info


def rozmiar(kat):
    r = 0
    for korzen, _, pliki in os.walk(kat):
        for p in pliki:
            try:
                r += os.path.getsize(os.path.join(korzen, p))
            except OSError:
                pass
    return r


def kopie(miejsca):
    """Kopie we wszystkich miejscach, od najnowszej: [dict info + kat, miejsce, rozmiar]."""
    wynik = []
    widziane = set()
    for m in miejsca:
        baza = os.path.join(m, PODKAT)
        try:
            nazwy = os.listdir(baza)
        except OSError:
            continue
        for n in nazwy:
            kat = os.path.join(baza, n)
            prawdziwy = os.path.realpath(kat)
            if prawdziwy in widziane:
                continue                # /media/hdd -> /hdd
            info = czytaj_info(kat)
            if info is None:
                continue
            widziane.add(prawdziwy)
            info['kat'] = kat
            info['miejsce'] = m
            info['rozmiar'] = rozmiar(kat)
            wynik.append(info)
    wynik.sort(key=lambda k: (k['data'], k['kat']), reverse=True)
    return wynik


def mb(bajty):
    return ('%.1f MB' % (bajty / 1048576.0)).replace('.', ',')


def opis_kopii(k):
    opis = k.get('opis') or ''
    return '%s  .%s %s  %s%s  (%s)' % (
        k['data'][:16], k.get('oktet', '?'), k.get('boxtype', '?'),
        opis and opis + '  ' or '', k['miejsce'], mb(k['rozmiar']))


def parsuj_miejsca(tekst):
    """Wyjscie 'nbox_kopia miejsca': [(sciezka, wolne_kb, system plikow)]."""
    wynik = []
    for l in tekst.splitlines():
        c = l.split()
        if len(c) == 3 and c[1].isdigit():
            wynik.append((c[0], int(c[1]), c[2]))
    return wynik


def opis_miejsca(m):
    sciezka, wolne, fs = m
    flash = fs in ('jffs2', 'ubifs', 'yaffs2') and ', flash boxa!' or ''
    return '%s  (%s, wolne %s%s)' % (sciezka, fs, mb(wolne * 1024), flash)


def wymaga_restartu(czesci):
    return [c for c in czesci if c not in BEZ_RESTARTU]


def ostatni_termin(teraz, tryb, godzina):
    """Ostatnia chwila <= teraz, o ktorej kopia automatyczna powinna byla ruszyc."""
    lt = time.localtime(teraz)

    def dzien(przesun):
        # mktime sam przelicza dzien 0 / ujemny na poprzedni miesiac
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + przesun, godzina, 0, 0, 0, 0, -1))

    przesun = 0
    t = dzien(0)
    if t > teraz:
        przesun = -1
        t = dzien(-1)
    if tryb == 'tydzien':
        cofnij = (time.localtime(t).tm_wday - NIEDZIELA) % 7
        if cofnij:
            t = dzien(przesun - cofnij)
    return t


def nalezna(teraz, ostatnia, tryb, godzina):
    """Kopia automatyczna do zrobienia: ostatnia udana byla przed ostatnim terminem.
    Box wylaczony o tej godzinie (Off = shutdown) - kopia po najblizszym starcie."""
    if tryb not in OKRES:
        return False
    return ostatnia < ostatni_termin(teraz, tryb, godzina)


def cytuj(s):
    return "'" + s.replace("'", "'\\''") + "'"
