# -*- coding: utf-8 -*-
#
# nBox kopia - logika bez enigmy (Python 2.7 na boxie, 3 w testach na PC):
# kopie na dyskach, opisy, ktore czesci wymagaja restartu, termin kopii
# automatycznej, plik sprzetu (nbox_HW_<id>.txt), menu startowe u-boota ze
# srodowiska w NOR. Robote na plikach robi /usr/bin/nbox_kopia (skrypty/nbox_kopia.sh).

import os
import re
import struct
import time
import zlib

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


# --- sprzet: id egzemplarza i plik HW ---------------------------------------

def parsuj_sprzet(tekst):
    """Wyjscie 'nbox_kopia sprzet': dict box_id, boxtype, plik, tresc."""
    wynik = {'box_id': '', 'boxtype': '', 'plik': '', 'tresc': ''}
    linie = tekst.splitlines()
    for i, l in enumerate(linie):
        if l == '---':
            wynik['tresc'] = '\n'.join(linie[i + 1:])
            break
        if '=' in l:
            k, v = l.split('=', 1)
            if k in wynik:
                wynik[k] = v.strip()
    return wynik


def opis_sprzetu(s):
    """Tekst ekranu 'Sprzet' z dict parsuj_sprzet."""
    t = ['Wariant płyty: %s' % (s['boxtype'] or '?')]
    if not s['box_id']:
        t.append('Numer boxa: brak - potrzebne jądro z NOR tylko do odczytu i pakiet nbox-nor-otp')
        return '\n'.join(t)
    t.append('Numer boxa (kość NOR): %s' % s['box_id'])
    t.append('Plik: %s' % s['plik'])
    t.append('')
    tresc = s['tresc'].strip('\n')
    t.append(tresc or '(pusto - zielony: dodaj pierwszy wpis, np. wymiana kondensatorów)')
    return '\n'.join(t)


# --- menu startowe u-boota ---------------------------------------------------

ROZMIARY_ENV = (0x10000, 0x8000, 0x4000, 0x2000)
KROK_ENV = 0x2000
AKTYWNE_ENV = 0x60000           # Freebox ze zworka A20 (sprawdzone na jednym boxie)


def _str(b):
    # Python 2 na boxie: zostaw bajty (str), bo mieszanie unicode z polskimi
    # literami w formatach daje UnicodeDecodeError; Python 3 w testach: str
    return b if str is bytes else b.decode('latin-1')


def _zmienne(blok):
    """Zmienne srodowiska 'k=v\\0k=v\\0\\0' -> dict albo None."""
    env = {}
    for x in blok.split(b'\0'):
        if not x:
            break
        if b'=' not in x:
            return None
        k, v = x.split(b'=', 1)
        env[_str(k)] = _str(v)
    return env


def srodowiska(dane, granica=0x200000):
    """Srodowiska u-boota z poprawnym CRC w zrzucie NOR: [(offset, rozmiar, env)].
    Na boxach ze zworka A20 druga polowa 4 MB to lustro, wiec granica 2 MB."""
    wynik = []
    koniec = min(len(dane), granica)
    for off in range(0, koniec, KROK_ENV):
        poczatek = dane[off + 4:off + 36]
        if not re.match(br'[A-Za-z_][A-Za-z0-9_#]*=', poczatek):
            continue
        crc = struct.unpack('<I', dane[off:off + 4])[0]
        for r in ROZMIARY_ENV:
            if off + r > koniec:
                continue
            if zlib.crc32(dane[off + 4:off + r]) & 0xffffffff == crc:
                env = _zmienne(dane[off + 4:off + r])
                if env:
                    wynik.append((off, r, env))
                break
        else:
            # zestaw ENV2/ENV3 Duo Multiboot: 'cp.b a02b4000 a0260000 4000' na skasowane
            # 64 KB, wiec CRC liczone z dopelnieniem 0xff, a nie z tym, co lezy dalej
            for r in ROZMIARY_ENV[1:]:
                if off + r <= koniec and zlib.crc32(
                        dane[off + 4:off + r] + b'\xff' * (ROZMIARY_ENV[0] - r)) & 0xffffffff == crc:
                    env = _zmienne(dane[off + 4:off + r])
                    if env:
                        wynik.append((off, r, env))
                    break
    return wynik


def aktywne(srodowiska_lista, cmdline=''):
    """Srodowisko, z ktorego wystartowal box: bootargs jak /proc/cmdline,
    potem 0x60000, potem pierwsze z bootcmd. None, gdy nic nie pasuje."""
    cmdline = cmdline.strip()
    if cmdline:
        for s in srodowiska_lista:
            if s[2].get('bootargs', '').strip() == cmdline:
                return s
    for s in srodowiska_lista:
        if s[0] == AKTYWNE_ENV:
            return s
    for s in srodowiska_lista:
        if 'bootcmd' in s[2]:
            return s
    return None


NOR_CPU = 0xa0000000
NOR_POLOWA = 0x200000
# Duo Multiboot v2 (jacektorun.pl): dwa u-booty w NOR. Freebox startuje pierwszy i
# skacze do B4Team, gdy pod 0xe0000 jest znacznik "u-b4"; pozycja "Fb-uboot"
# kasuje znacznik, wiec Freebox zostaje tez po restarcie (powrot: "u-B4").
UBOOTY = {0x6000: 'Freebox', 0x80000: 'B4Team'}


def _nor(adres):
    """Adres CPU u-boota (a02b4000) -> offset w NOR; polowy 2 MB sa lustrem."""
    return (int(adres, 16) - NOR_CPU) % NOR_POLOWA


def _uboot(adres):
    n = UBOOTY.get(_nor(adres))
    return n and 'u-boot %s' % n or 'u-boot pod %s' % adres


def _przelacza(kern):
    """'uboot' - skok do innego u-boota, 'env' - zestaw ENV z szablonu, '' - start systemu."""
    if 'erase ' not in kern or not re.search(r'\bgo ', kern):
        return ''
    return re.search(r'\bcp\.b ', kern) and 'env' or 'uboot'


def _mac(lista, off):
    for o, _, env in lista or ():
        if o == off:
            return env.get('ethaddr', '')
    return ''


def _skad(kern, lista=None):
    rodzaj = _przelacza(kern)
    if rodzaj:
        ub = _uboot(re.search(r'\bgo ([^\s;]+)', kern).group(1))
        if rodzaj == 'uboot':
            return 'przejście do: %s' % ub
        zrodlo = _nor(re.search(r'\bcp\.b ([^\s;]+)', kern).group(1))
        mac = _mac(lista, zrodlo)
        return 'zestaw ENV spod 0x%x%s zamiast obecnego, %s' % (
            zrodlo, mac and ' (MAC %s)' % mac or '', ub)
    m = re.search(r'nand read(?:\.i)? \S+ (0x[0-9a-fA-F]+) (0x[0-9a-fA-F]+)', kern)
    if m:
        return 'NAND od %s (%d MB)' % (m.group(1), int(m.group(2), 16) // 0x100000)
    m = re.search(r'ext2load usb (\d+:\d+) \S+ ([^\s;]+)', kern)
    if m:
        return 'USB %s %s' % (m.group(1), m.group(2))
    if 'fatload usb' in kern and 'autoscr' in kern:
        return 'skrypt "update" z pendrive\'a (FAT)'
    if 'nfs ' in kern:
        return 'NFS'
    return kern[:60]


def menu_uboot(env, lista=None):
    """Pozycje menu z srodowiska: [dict nr, opis, domyslna, skad, root, zapamietuje, przelacza, bootargs].
    lista - wszystkie srodowiska z NOR (MAC zestawu, na ktory przelacza pozycja ENV)."""
    nry = sorted(int(k[9:]) for k in env if re.match(r'bootdesc_\d+$', k))
    domyslna = env.get('bootdesc_default', '')
    wynik = []
    for n in nry:
        kern = env.get('bootkern_%d' % n, '')
        cmd = env.get('bootcmd_%d' % n, '')
        args = env.get('bootargs_%d' % n, '')
        if args.startswith('set bootargs '):
            args = args[len('set bootargs '):]
        m = re.search(r'(?:^| )root=(\S+)', args)
        wynik.append({
            'nr': n,
            'opis': env['bootdesc_%d' % n].strip(),
            'domyslna': str(n) == domyslna,
            'skad': _skad(kern, lista),
            'root': m and m.group(1) or '',
            'zapamietuje': 'saveenv' in cmd,
            'przelacza': _przelacza(kern),
            'bootargs': args,
        })
    return wynik


def opis_menu(off, env, lista=None):
    """Tekst ekranu z menu startowym."""
    t = ['Środowisko u-boota w NOR pod 0x%x (CRC poprawne)' % off,
         'Start: %s, %s s na wybór, domyślna pozycja %s; MAC %s' % (
             env.get('bootcmd', '?'), env.get('bootmenutimeout', env.get('bootdelay', '?')),
             env.get('bootdesc_default', '?'), env.get('ethaddr', '?')),
         '']
    for p in menu_uboot(env, lista):
        linia = '%s %d  %-16s %s' % (p['domyslna'] and '>' or ' ', p['nr'], p['opis'], p['skad'])
        if p['root']:
            linia += ', root=%s' % p['root']
        if p['przelacza'] == 'uboot':
            linia += '  (zostaje po restarcie, powrót: u-B4)'
        elif p['przelacza'] == 'env':
            linia += '  (zostaje po restarcie)'
        elif p['zapamietuje']:
            linia += '  (zostaje domyślna)'
        t.append(linia)
    t += ['', 'Obecny start (bootargs):', env.get('bootargs', '?')]
    return '\n'.join(t)
