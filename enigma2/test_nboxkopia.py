# -*- coding: utf-8 -*-
#
# Test NBoxKopia (kopie.py i plugin.py na atrapach enigmy, PC, Python 3):
#   python enigma2/test_nboxkopia.py
# Atrapy configu i timerow z test_plugin_atrapy.py. Test calosci: prawdziwy
# skrypty/nbox_kopia.sh (NBK_ROOT = atrapa boxa) robi kopie, kopie.py ja znajduje -
# potrzebne sh w PATH (Git Bash), inaczej pominiety.

import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
import zlib

TU = os.path.dirname(os.path.abspath(__file__))
KAT = os.path.join(TU, 'NBoxKopia')
SKRYPT_SH = os.path.join(os.path.dirname(TU), 'skrypty', 'nbox_kopia.sh')
sys.path.insert(0, TU)
sys.path.insert(0, KAT)
import test_plugin_atrapy as A      # noqa: E402
import kopie                        # noqa: E402


class Wybor(A.Element):
    def __init__(self, default=None, choices=None, **kw):
        A.Element.__init__(self, default)
        self.wybory = [c if isinstance(c, tuple) else (c, c) for c in (choices or [])]

    def getText(self):
        return dict(self.wybory).get(self.value, str(self.value))


class Ekran(A.Ekran):
    def __init__(self, session):
        A.Ekran.__init__(self, session)
        self.session = session
        self.onShown = []


class Kontener(object):
    wszystkie = []

    def __init__(self):
        self.dataAvail = []
        self.appClosed = []
        self.polecenia = []
        Kontener.wszystkie.append(self)

    def execute(self, cmd):
        self.polecenia.append(cmd)
        return 0

    def zakoncz(self, rc, wyjscie=''):
        for f in list(self.dataAvail):
            f(wyjscie)
        for f in list(self.appClosed):
            f(rc)


class Sesja(object):
    def __init__(self):
        self.otwarte = []

    def open(self, ekran, *a, **kw):
        self.otwarte.append((ekran, a, kw, None))

    def openWithCallback(self, cb, ekran, *a, **kw):
        self.otwarte.append((ekran, a, kw, cb))


class MenuListAtrapa(object):
    def __init__(self, lista):
        self.list = lista
        self.indeks = 0

    def getCurrent(self):
        return self.list[self.indeks]


class ScrollLabelAtrapa(object):
    def __init__(self, tekst=''):
        self.tekst = tekst

    def setText(self, t):
        self.tekst = t

    def pageUp(self):
        pass

    def pageDown(self):
        pass


class Popen(object):
    """os.popen: zapamietuje polecenie, zwraca zadane wyjscie i kod."""
    polecenia = []
    odpowiedz = ('', None)

    def __init__(self, cmd):
        Popen.polecenia.append(cmd)
        self.wyj, self.rc = Popen.odpowiedz

    def read(self):
        return self.wyj

    def close(self):
        return self.rc


def env_nor(zmienne, rozmiar):
    """Blok srodowiska u-boota: CRC32 + 'k=v\\0...\\0', dopelniony 0xff... do rozmiaru."""
    dane = b''.join(('%s=%s' % kv).encode('latin-1') + b'\0' for kv in zmienne) + b'\0'
    dane = dane + b'\0' * (rozmiar - 4 - len(dane))
    return struct.pack('<I', zlib.crc32(dane) & 0xffffffff) + dane


CMDLINE = ('console=ttyAS0,115200 root=/dev/mtdblock0 rw rootfstype=jffs2 mem=128m '
           'nwhwconf=device:eth0,hwaddr:00:03:91:12:10:11 init=/bin/devinit')
MENU_ENV = [
    ('bootcmd', 'bootmenu'), ('bootdelay', '4'), ('bootmenutimeout', '5'),
    ('bootdesc_items', '9'), ('bootdesc_default', '8'), ('bootargs', CMDLINE),
    ('ethaddr', '00:03:91:12:10:11'),
    ('bootdesc_1', 'Fb-uboot        '), ('bootcmd_1', 'run bootkern_1'),
    ('bootkern_1', 'protect off all; erase a02e0000 a02fffff; go a0206000'),
    ('bootdesc_3', 'USH1            '),
    ('bootcmd_3', 'set bootdesc_default 3; saveenv; run bootargs_3; run bootkern_3'),
    ('bootargs_3', 'set bootargs console=ttyAS0,115200 root=/dev/sdb1 rw rootdelay=6'),
    ('bootkern_3', 'usb reset; ext2load usb 0:1 a5000000 /boot/uImage; bootm a5000000'),
    ('bootdesc_8', 'n-Fbox          '),
    ('bootcmd_8', 'set bootdesc_default 8; saveenv; run bootargs_8; run bootkern_8'),
    ('bootargs_8', 'set bootargs ' + CMDLINE),
    ('bootkern_8', 'nand read.i 0xa5000000 0x3c00000 0x300000; bootm a5000000'),
    ('bootdesc_9', 'UPDT            '), ('bootcmd_9', 'run bootkern_9'),
    ('bootkern_9', 'usb reset; fatload usb 0:1 a4000000 update; autoscr'),
]


def zrzut_nor():
    """2 MB jak NOR boxa: szablon pod 0x40000 (bez bootargs), aktywne pod 0x60000,
    zepsute CRC pod 0x70000."""
    d = bytearray(b'\xff' * 0x200000)
    szablon = env_nor([('bootdelay', '3'), ('baudrate', '115200'), ('board', 'mb442_27')], 0x8000)
    d[0x40000:0x48000] = szablon
    d[0x60000:0x70000] = env_nor(MENU_ENV, 0x10000)
    zle = bytearray(env_nor(MENU_ENV, 0x10000))
    zle[100] ^= 1
    d[0x70000:0x80000] = zle
    return bytes(d)


def atrapy():
    m = {}

    def mod(nazwa, **attr):
        x = types.ModuleType(nazwa)
        x.__dict__.update(attr)
        m[nazwa] = x
        return x

    config = A.ConfigSubsection()
    config.plugins = A.ConfigSubsection()
    powiadomienia = []
    mod('enigma', eTimer=A.ETimer, eConsoleAppContainer=Kontener)
    mod('Plugins')
    mod('Plugins.Plugin', PluginDescriptor=type('PluginDescriptor', (), {
        'WHERE_SESSIONSTART': 1, 'WHERE_MENU': 2, 'WHERE_PLUGINMENU': 3,
        '__init__': lambda self, **kw: None}))
    mod('Plugins.SystemPlugins')
    pakiet = mod('Plugins.SystemPlugins.NBoxKopia')
    pakiet.__path__ = [KAT]
    mod('Screens')
    mod('Screens.Screen', Screen=Ekran)
    mod('Screens.MessageBox', MessageBox=type('MessageBox', (), {'TYPE_YESNO': 0, 'TYPE_INFO': 1, 'TYPE_ERROR': 3}))
    mod('Screens.ChoiceBox', ChoiceBox=type('ChoiceBox', (), {}))
    mod('Screens.Console', Console=type('Console', (), {}))
    mod('Screens.VirtualKeyBoard', VirtualKeyBoard=type('VirtualKeyBoard', (), {}))
    mod('Components')
    mod('Components.ActionMap', ActionMap=lambda *a, **k: None)
    mod('Components.ConfigList', ConfigListScreen=A.ListaUstawien)
    mod('Components.MenuList', MenuList=MenuListAtrapa)
    mod('Components.ScrollLabel', ScrollLabel=ScrollLabelAtrapa)
    mod('Components.Sources')
    mod('Components.Sources.StaticText', StaticText=lambda t='': types.SimpleNamespace(text=t))
    mod('Components.config', config=config, ConfigSubsection=A.ConfigSubsection,
        ConfigYesNo=A.Element, ConfigSelection=Wybor, ConfigText=Wybor, ConfigInteger=Wybor,
        getConfigListEntry=lambda *a: a, configfile=types.SimpleNamespace(save=lambda: None))
    mod('Tools', Notifications=types.SimpleNamespace(
        AddNotification=lambda *a, **kw: powiadomienia.append((a, kw))))
    return m, config, powiadomienia


def msys(p):
    """C:/x -> /c/x dla sh i tar z Git Bash (tar bierze 'C:' za zdalny host)."""
    p = p.replace(os.sep, '/')
    if p[1:2] == ':':
        p = '/' + p[0].lower() + p[2:]
    return p


def zrob_kopie(baza, nazwa, **pola):
    kat = os.path.join(baza, kopie.PODKAT, nazwa)
    os.makedirs(kat)
    info = dict(data='2026-11-05 21:00:00', oktet='41', boxtype='BSLA', host='nbox',
                czesci='kanaly enigma oscam siec system pakiety', opis='')
    info.update(pola)
    with open(os.path.join(kat, 'info.txt'), 'w') as f:
        f.write(''.join('%s=%s\n' % kv for kv in info.items()))
    with open(os.path.join(kat, 'kanaly.tgz'), 'wb') as f:
        f.write(b'x' * 2048)
    return kat


class Kopie(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def t(self, s):
        return time.mktime(time.strptime(s, '%Y-%m-%d %H:%M'))

    def test_termin_dzienny(self):
        self.assertEqual(kopie.ostatni_termin(self.t('2026-11-06 05:00'), 'dzien', 4), self.t('2026-11-06 04:00'))
        self.assertEqual(kopie.ostatni_termin(self.t('2026-11-06 03:59'), 'dzien', 4), self.t('2026-11-05 04:00'))
        self.assertEqual(kopie.ostatni_termin(self.t('2026-11-01 03:00'), 'dzien', 4), self.t('2026-10-31 04:00'))

    def test_termin_tygodniowy_niedziela(self):
        # 2026-11-08 to niedziela
        self.assertEqual(kopie.ostatni_termin(self.t('2026-11-06 12:00'), 'tydzien', 4), self.t('2026-11-01 04:00'))
        self.assertEqual(kopie.ostatni_termin(self.t('2026-11-08 04:00'), 'tydzien', 4), self.t('2026-11-08 04:00'))
        self.assertEqual(kopie.ostatni_termin(self.t('2026-11-08 03:00'), 'tydzien', 4), self.t('2026-11-01 04:00'))

    def test_nalezna(self):
        teraz = self.t('2026-11-06 05:00')
        self.assertTrue(kopie.nalezna(teraz, 0, 'dzien', 4))
        self.assertTrue(kopie.nalezna(teraz, self.t('2026-11-05 04:10'), 'dzien', 4))
        self.assertFalse(kopie.nalezna(teraz, self.t('2026-11-06 04:01'), 'dzien', 4))
        self.assertFalse(kopie.nalezna(teraz, 0, 'nie', 4))
        # box wylaczony w niedziele o 4 - kopia po starcie w poniedzialek
        self.assertTrue(kopie.nalezna(self.t('2026-11-09 18:00'), self.t('2026-11-01 04:02'), 'tydzien', 4))

    def test_kopie_od_najnowszej_bez_smieci(self):
        zrob_kopie(self.tmp, '41_20261105_210000', data='2026-11-05 21:00:00')
        zrob_kopie(self.tmp, '11_20261106_040000_auto', data='2026-11-06 04:00:00', oktet='11', opis='auto')
        os.makedirs(os.path.join(self.tmp, kopie.PODKAT, 'nie_kopia'))
        lista = kopie.kopie([self.tmp, os.path.join(self.tmp, 'brak')])
        self.assertEqual([k['oktet'] for k in lista], ['11', '41'])
        self.assertEqual(lista[0]['czesci'], list(kopie.CZESCI))
        self.assertGreaterEqual(lista[0]['rozmiar'], 2048)
        self.assertIn('auto', kopie.opis_kopii(lista[0]))
        self.assertIn('.11 BSLA', kopie.opis_kopii(lista[0]))
        # to samo miejsce dwa razy (np. /media/hdd -> /hdd) - kopie raz
        self.assertEqual(len(kopie.kopie([self.tmp, self.tmp])), 2)

    def test_miejsca(self):
        m = kopie.parsuj_miejsca('/hdd 1000 ext4\nsmiec\n/media/net/nsa310 5000 nfs\n')
        self.assertEqual(m, [('/hdd', 1000, 'ext4'), ('/media/net/nsa310', 5000, 'nfs')])
        self.assertIn('flash', kopie.opis_miejsca(('/hdd', 18000, 'jffs2')))
        self.assertNotIn('flash', kopie.opis_miejsca(m[0]))

    def test_restart(self):
        self.assertEqual(kopie.wymaga_restartu(['kanaly', 'oscam']), [])
        self.assertEqual(kopie.wymaga_restartu(['kanaly', 'siec']), ['siec'])

    def test_cytuj(self):
        self.assertEqual(kopie.cytuj("/media/a b'c"), "'/media/a b'\\''c'")

    def test_sprzet(self):
        s = kopie.parsuj_sprzet('box_id=2d08\nboxtype=BSLA\nplik=/root/nbox_HW_2d08.txt\n---\n'
                                '# nBox BSLA\n2026-11-19 wymiana C270\n')
        self.assertEqual((s['box_id'], s['boxtype']), ('2d08', 'BSLA'))
        self.assertIn('2026-11-19 wymiana C270', s['tresc'])
        t = kopie.opis_sprzetu(s)
        self.assertIn('2d08', t)
        self.assertIn('C270', t)
        bez = kopie.parsuj_sprzet('box_id=\nboxtype=BSKA\nplik=\n---\n')
        self.assertIn('brak', kopie.opis_sprzetu(bez))
        self.assertIn('pusto', kopie.opis_sprzetu(kopie.parsuj_sprzet('box_id=1\nplik=/x\n---\n')))
        self.assertEqual(kopie.parsuj_sprzet('')['box_id'], '')

    def test_srodowiska_uboot(self):
        sr = kopie.srodowiska(zrzut_nor())
        self.assertEqual([(o, r) for o, r, _ in sr], [(0x40000, 0x8000), (0x60000, 0x10000)])
        self.assertEqual(kopie.aktywne(sr, CMDLINE + '\n')[0], 0x60000)
        self.assertEqual(kopie.aktywne(sr, 'inna linia')[0], 0x60000)
        self.assertIsNone(kopie.aktywne(sr[:1], 'inna'))    # sam szablon: bez bootargs i bootcmd
        przesuniete = [(0x50000, r, env) for o, r, env in sr if o == 0x60000]
        self.assertEqual(kopie.aktywne(sr[:1] + przesuniete, 'inna')[0], 0x50000)
        self.assertEqual(kopie.srodowiska(b'\xff' * 0x10000), [])

    def test_menu_uboot(self):
        env = dict(MENU_ENV)
        m = kopie.menu_uboot(env)
        self.assertEqual([p['nr'] for p in m], [1, 3, 8, 9])
        p = dict((x['nr'], x) for x in m)
        self.assertTrue(p[8]['domyslna'])
        self.assertEqual(p[8]['skad'], 'NAND od 0x3c00000 (3 MB)')
        self.assertEqual(p[8]['root'], '/dev/mtdblock0')
        self.assertEqual(p[3]['skad'], 'USB 0:1 /boot/uImage')
        self.assertEqual(p[3]['root'], '/dev/sdb1')
        self.assertTrue(p[3]['zapamietuje'])
        self.assertTrue(p[1]['kasuje_nor'])
        self.assertIn('update', p[9]['skad'])
        t = kopie.opis_menu(0x60000, env)
        self.assertIn('0x60000', t)
        self.assertIn('> 8  n-Fbox', t)
        self.assertIn('KASUJE', t)
        self.assertIn(CMDLINE, t)


class Wtyczka(unittest.TestCase):
    def setUp(self):
        A.ETimer.wszystkie = []
        Kontener.wszystkie = []
        self.moduly, self.config, self.powiadomienia = atrapy()
        self.stare = dict((k, sys.modules.get(k)) for k in self.moduly)
        sys.modules.update(self.moduly)
        sys.modules.pop('Plugins.SystemPlugins.NBoxKopia.kopie', None)
        spec = importlib.util.spec_from_file_location('nboxkopia_plugin', os.path.join(KAT, 'plugin.py'))
        self.p = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.p)
        self.tmp = tempfile.mkdtemp()
        self.p.LOG = os.path.join(self.tmp, 'wtyczka.log')
        self.skrypt = os.path.join(self.tmp, 'skrypt_nbox_kopia')
        with open(self.skrypt, 'w') as f:
            f.write('#!/bin/sh\n')
        self.p.SKRYPT = self.skrypt
        self.p.miejsca = lambda: [(self.tmp, 1000, 'ext4')]
        self.u = self.p.ust
        self.u.miejsce.value = self.tmp
        self.systemowe = []
        self.stary_system = os.system
        os.system = lambda cmd: self.systemowe.append(cmd) or 0
        self.stary_popen = os.popen
        Popen.polecenia = []
        Popen.odpowiedz = ('', None)
        os.popen = Popen
        self.p.autostart(0, session=Sesja())
        self.h = self.p.harmonogram

    def tearDown(self):
        os.system = self.stary_system
        os.popen = self.stary_popen
        for k, v in self.stare.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_domyslnie_nic_nie_robi(self):
        self.assertEqual(self.h.timer.ms, self.p.PIERWSZE_SPRAWDZENIE_MS)
        self.h.timer.odpal()
        self.assertEqual(Kontener.wszystkie, [])
        self.assertTrue(self.h.timer.aktywny)

    def test_kopia_automatyczna(self):
        self.u.auto.value = 'dzien'
        self.u.zostaw.value = '5'
        self.h.timer.odpal()
        k = Kontener.wszystkie[0]
        self.assertEqual(k.polecenia, ["%s zapisz -d '%s' -o auto -z 5" % (self.skrypt, self.tmp)])
        self.h.timer.odpal()                        # trwa - drugiej nie zaczyna
        self.assertEqual(len(Kontener.wszystkie), 1)
        przed = time.time()
        k.zakoncz(0, 'KOPIA /hdd/nbox_kopia/x\n')
        self.assertGreaterEqual(self.u.ostatnia.value, int(przed))
        self.h.timer.odpal()                        # zrobiona dzis - nic
        self.assertEqual(len(Kontener.wszystkie), 1)
        self.assertEqual(self.powiadomienia, [])

    def test_blad_kopii_powiadomienie_i_przerwa(self):
        self.u.auto.value = 'tydzien'
        self.h.timer.odpal()
        Kontener.wszystkie[0].zakoncz(1, 'BLAD: za malo miejsca\n')
        self.assertEqual(len(self.powiadomienia), 1)
        self.assertIn('za malo miejsca', self.powiadomienia[0][0][1])
        self.assertEqual(self.u.ostatnia.value, 0)
        self.h.timer.odpal()                        # 6 h przerwy po bledzie
        self.assertEqual(len(Kontener.wszystkie), 1)
        self.h.blad_o -= self.p.PONOW_PO_BLEDZIE_S
        self.h.timer.odpal()
        self.assertEqual(len(Kontener.wszystkie), 2)

    def test_brak_miejsca_bez_uruchamiania(self):
        self.u.auto.value = 'dzien'
        self.u.miejsce.value = os.path.join(self.tmp, 'nie_ma')
        self.h.timer.odpal()
        self.assertEqual(Kontener.wszystkie, [])
        self.assertEqual(len(self.powiadomienia), 1)
        self.assertTrue(self.h.timer.aktywny)

    def test_wyjatek_nie_wychodzi_z_timera(self):
        self.u.auto.value = 'dzien'
        self.u.godzina.value = 'zle'                # int() rzuci
        self.h.timer.odpal()
        self.assertTrue(self.h.timer.aktywny)
        with open(self.p.LOG) as f:
            self.assertIn('ValueError', f.read())

    def test_menu_zrob_kopie(self):
        s = Sesja()
        menu = self.p.NBoxKopiaMenu(s)
        menu.odswiez()
        self.assertIn(self.tmp, menu['status'].text)
        menu.ok()                                   # pierwsza pozycja: zrob kopie
        ekran, a, kw, cb = s.otwarte[-1]
        self.assertEqual(ekran.__name__, 'Console')
        self.assertEqual(kw['cmdlist'], ["%s zapisz -d '%s'" % (self.skrypt, self.tmp)])
        self.u.miejsce.value = os.path.join(self.tmp, 'nie_ma')
        menu.ok()
        self.assertEqual(s.otwarte[-1][0].__name__, 'MessageBox')

    def test_menu_wybor_kopii(self):
        zrob_kopie(self.tmp, '41_20261105_210000')
        s = Sesja()
        menu = self.p.NBoxKopiaMenu(s)
        menu.wybierz_kopie()
        ekran, a, kw, cb = s.otwarte[-1]
        self.assertEqual(ekran.__name__, 'ChoiceBox')
        self.assertEqual(len(kw['list']), 1)
        cb(kw['list'][0])
        self.assertIs(s.otwarte[-1][0], self.p.NBoxKopiaWgraj)

    def wgraj(self, czesci, **pola):
        kat = zrob_kopie(self.tmp, '41_x', czesci=czesci, **pola)
        s = Sesja()
        e = self.p.NBoxKopiaWgraj(s, dict(kopie.czytaj_info(kat), kat=kat, miejsce=self.tmp, rozmiar=1))
        return s, e, kat

    def test_wgraj_bez_restartu_tylko_kanaly_i_oscam(self):
        s, e, kat = self.wgraj('kanaly enigma oscam')
        self.assertEqual([c for c, _ in e.czesci], ['kanaly', 'enigma', 'oscam'])
        e.po.value = 'nic'
        e.odswiez()
        self.assertIn('Bez restartu tylko', e['status'].text)
        e.wgraj()
        self.assertEqual(s.otwarte[-1][0].__name__, 'MessageBox')
        self.assertIsNone(s.otwarte[-1][3])         # blad, nie pytanie
        dict(e.czesci)['enigma'].value = False
        e.wgraj()
        ekran, a, kw, cb = s.otwarte[-1]
        cb(True)
        ekran, a, kw, cb = s.otwarte[-1]
        self.assertEqual(ekran.__name__, 'Console')
        self.assertEqual(kw['cmdlist'], ["%s wgraj '%s' kanaly,oscam nic" % (self.skrypt, kat)])
        self.assertEqual(self.systemowe, [])

    def test_wgraj_z_restartem_odlaczone(self):
        s, e, kat = self.wgraj('kanaly enigma siec pakiety', boxtype='BXZB')
        e.odswiez()
        self.assertIn('UWAGA: ten box', e['status'].text)
        e.wgraj()
        cb = s.otwarte[-1][3]
        cb(False)                                   # "nie" - nic
        self.assertEqual(self.systemowe, [])
        e.wgraj()
        s.otwarte[-1][3](True)
        self.assertEqual(self.systemowe, ["%s --w-tle wgraj '%s' kanaly,enigma,siec,pakiety restart >/dev/null 2>&1"
                                          % (self.skrypt, kat)])

    def test_wgraj_inny_egzemplarz(self):
        Popen.odpowiedz = ('box_id=bbbb\nboxtype=BSLA\nplik=/root/nbox_HW_bbbb.txt\n---\n', None)
        s, e, kat = self.wgraj('kanaly system', box_id='aaaa')
        e.odswiez()
        self.assertIn('innego egzemplarza (aaaa)', e['status'].text)
        e.kopia['box_id'] = 'bbbb'
        e.odswiez()
        self.assertNotIn('innego egzemplarza', e['status'].text)

    def test_sprzet_ekran_i_wpis(self):
        Popen.odpowiedz = ('box_id=2d08\nboxtype=BSLA\nplik=/root/nbox_HW_2d08.txt\n---\n'
                           '2026-11-19 wymiana C270\n', None)
        s = Sesja()
        menu = self.p.NBoxKopiaMenu(s)
        menu.sprzet()
        self.assertIs(s.otwarte[-1][0], self.p.NBoxKopiaSprzet)
        e = self.p.NBoxKopiaSprzet(s)
        e.odswiez()
        self.assertIn('C270', e['tekst'].tekst)
        self.assertEqual(e['key_green'].text, 'Dodaj wpis')
        e.zielony()
        ekran, a, kw, cb = s.otwarte[-1]
        self.assertEqual(ekran.__name__, 'VirtualKeyBoard')
        Popen.polecenia = []
        cb("wymiana C271 'low ESR'")
        self.assertEqual(Popen.polecenia[0], "%s sprzet dodaj 'wymiana C271 '\\''low ESR'\\''' 2>&1" % self.skrypt)
        Popen.polecenia = []
        cb(None)                                    # anulowana klawiatura
        cb('   ')
        self.assertEqual(Popen.polecenia, [])

    def test_sprzet_bez_id(self):
        Popen.odpowiedz = ('box_id=\nboxtype=BSKA\nplik=\n---\n', None)
        s = Sesja()
        e = self.p.NBoxKopiaSprzet(s)
        e.odswiez()
        self.assertIn('brak', e['tekst'].tekst)
        self.assertEqual(e['key_green'].text, '')
        e.zielony()
        self.assertEqual(s.otwarte, [])

    def test_sprzet_blad_dopisania(self):
        Popen.odpowiedz = ('box_id=2d08\nboxtype=BSLA\nplik=/x\n---\n', None)
        s = Sesja()
        e = self.p.NBoxKopiaSprzet(s)
        e.odswiez()
        Popen.odpowiedz = ('BLAD: zegar boxa nieustawiony\n', 256)
        e.wpis('C1')
        self.assertEqual(s.otwarte[-1][0].__name__, 'MessageBox')
        self.assertIn('zegar', s.otwarte[-1][1][0])

    def test_menu_uboot(self):
        nor = os.path.join(self.tmp, 'mtd2')
        with open(nor, 'wb') as f:
            f.write(zrzut_nor() + b'\xff' * 0x200000)
        mtd = os.path.join(self.tmp, 'mtd')
        with open(mtd, 'w') as f:
            f.write('dev:    size   erasesize  name\nmtd0: 03c00000 00004000 "rootfs"\n'
                    'mtd1: 00400000 00004000 "kernel"\nmtd2: 00400000 00010000 "nor"\n')
        cmdline = os.path.join(self.tmp, 'cmdline')
        with open(cmdline, 'w') as f:
            f.write(CMDLINE + '\n')
        self.p.PROC_MTD, self.p.DEV_KAT, self.p.PROC_CMDLINE = mtd, self.tmp + os.sep, cmdline
        s = Sesja()
        menu = self.p.NBoxKopiaMenu(s)
        menu.uboot()
        ekran, a, kw, cb = s.otwarte[-1]
        self.assertIs(ekran, self.p.NBoxKopiaTekst)
        self.assertIn('n-Fbox', a[1])
        self.assertIn('0x60000', a[1])
        # jadro bez NOR
        with open(mtd, 'w') as f:
            f.write('mtd0: 03c00000 00004000 "rootfs"\n')
        menu.uboot()
        self.assertIn('nie widzi', s.otwarte[-1][1][1])
        # wyjatek (np. brak dostepu) - komunikat, nie wywrotka
        self.p.tekst_menu_uboot = lambda: 1 / 0
        menu.uboot()
        self.assertIn('Błąd', s.otwarte[-1][1][1])

    def test_ustawienia(self):
        s = Sesja()
        e = self.p.NBoxKopiaUstawienia(s)
        self.assertEqual(len(e['config'].list), 2)  # bez auto - bez godziny i liczby
        self.u.auto.value = 'dzien'
        e.przebuduj()
        self.assertEqual(len(e['config'].list), 4)
        e.zapisz()
        self.assertTrue(e.zamkniety)
        self.assertIn('codziennie', self.p.opis_auto())


@unittest.skipUnless(shutil.which('sh') and shutil.which('tar'), 'brak sh/tar (Git Bash)')
class Calosc(unittest.TestCase):
    """nbox_kopia.sh na atrapie boxa -> kopie.py widzi kopie z wszystkimi czesciami."""

    def test_skrypt_i_lista(self):
        tmp = tempfile.mkdtemp()
        try:
            boks = os.path.join(tmp, 'boks')
            for p, t in (('etc/enigma2/lamedb', 'eDVB'), ('etc/enigma2/settings', 'x=1'),
                         ('etc/oscam/oscam.conf', 'ATRAPA'), ('etc/rc.local', 'exit 0'),
                         ('etc/network/interfaces', 'auto eth0'), ('root/nbox_monitor.conf', 'X=1'),
                         ('var/grun/grcstype', 'boxtype=BSLA'),
                         ('var/lib/opkg/status', 'Package: busybox\nVersion: 1\nStatus: install ok installed\n')):
                sciezka = os.path.join(boks, p)
                os.makedirs(os.path.dirname(sciezka), exist_ok=True)
                with open(sciezka, 'w', newline='\n') as f:
                    f.write(t + '\n')
            os.makedirs(os.path.join(boks, 'var/lib/opkg/info'))
            dysk = os.path.join(tmp, 'dysk')
            os.makedirs(dysk)
            with open(SKRYPT_SH, 'rb') as f:
                tresc = f.read().replace(b'\r\n', b'\n')
            skrypt = os.path.join(tmp, 'nbox_kopia')
            with open(skrypt, 'wb') as f:
                f.write(tresc)
            env = dict(os.environ, NBK_ROOT=msys(boks))
            w = subprocess.run(['sh', msys(skrypt), 'zapisz', '-d', msys(dysk)],
                               env=env, capture_output=True, text=True)
            self.assertEqual(w.returncode, 0, w.stdout + w.stderr)
            lista = kopie.kopie([dysk])
            self.assertEqual(len(lista), 1)
            self.assertEqual(lista[0]['boxtype'], 'BSLA')
            self.assertEqual(lista[0]['czesci'], ['kanaly', 'enigma', 'oscam', 'siec', 'system', 'pakiety'])
            self.assertEqual(lista[0]['box_id'], '')       # bez nor_otp
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def boks(self, tmp, nazwa, pliki):
        boks = os.path.join(tmp, nazwa)
        pliki = dict(pliki)
        pliki.setdefault('etc/rc.local', 'exit 0')
        pliki.setdefault('var/grun/grcstype', 'boxtype=BSLA')
        pliki.setdefault('var/lib/opkg/status', 'Package: busybox\nVersion: 1\nStatus: install ok installed\n')
        for p, t in pliki.items():
            sciezka = os.path.join(boks, p)
            os.makedirs(os.path.dirname(sciezka), exist_ok=True)
            with open(sciezka, 'w', newline='\n') as f:
                f.write(t + '\n')
        os.makedirs(os.path.join(boks, 'var/lib/opkg/info'), exist_ok=True)
        return boks

    def uruchom(self, skrypt, boks, box_id, *arg):
        env = dict(os.environ, NBK_ROOT=msys(boks), NBK_BOX_ID=box_id)
        w = subprocess.run(['sh', msys(skrypt)] + list(arg), env=env, capture_output=True, text=True)
        self.assertEqual(w.returncode, 0, w.stdout + w.stderr)
        return w.stdout

    def czytaj(self, *s):
        with open(os.path.join(*s)) as f:
            return f.read()

    def test_plik_hw(self):
        tmp = tempfile.mkdtemp()
        try:
            id1, id2 = '2d084c4c587fda55', '1111222233334444'
            hw1, hw2 = 'nbox_HW_%s.txt' % id1, 'nbox_HW_%s.txt' % id2
            with open(SKRYPT_SH, 'rb') as f:
                tresc = f.read().replace(b'\r\n', b'\n')
            skrypt = os.path.join(tmp, 'nbox_kopia')
            with open(skrypt, 'wb') as f:
                f.write(tresc)
            dysk = os.path.join(tmp, 'dysk')
            os.makedirs(dysk)
            b1 = self.boks(tmp, 'b1', {'root/' + hw1: '# nBox BSLA\n2026-11-19 wymiana C270'})

            # sprzet i dopisanie wpisu
            wyj = self.uruchom(skrypt, b1, id1, 'sprzet')
            s = kopie.parsuj_sprzet(wyj)
            self.assertEqual((s['box_id'], s['plik']), (id1, '/root/' + hw1))
            self.assertIn('C270', s['tresc'])
            self.uruchom(skrypt, b1, id1, 'sprzet', 'dodaj', 'wymiana', 'C271')
            self.assertIn('%s wymiana C271' % time.strftime('%Y-%m-%d'), self.czytaj(b1, 'root', hw1))
            # nowy plik dostaje naglowek
            b3 = self.boks(tmp, 'b3', {})
            self.uruchom(skrypt, b3, id2, 'sprzet', 'dodaj', 'C1')
            self.assertTrue(self.czytaj(b3, 'root', hw2).startswith('# nBox BSLA, id kosci NOR %s' % id2))
            # bez id - blad
            env = dict(os.environ, NBK_ROOT=msys(b3), NBK_BOX_ID='')
            w = subprocess.run(['sh', msys(skrypt), 'sprzet', 'dodaj', 'x'], env=env, capture_output=True, text=True)
            self.assertNotEqual(w.returncode, 0)

            # kopia: plik HW na wierzchu, box_id w info, w md5sums
            self.uruchom(skrypt, b1, id1, 'zapisz', '-d', msys(dysk))
            k = kopie.kopie([dysk])[0]
            self.assertEqual(k['box_id'], id1)
            self.assertIn('C271', self.czytaj(k['kat'], hw1))
            self.assertIn(hw1, self.czytaj(k['kat'], 'md5sums'))

            # wgranie na inny egzemplarz: jego plik bez zmian, obcy nie trafia do /root
            b2 = self.boks(tmp, 'b2', {'root/' + hw2: 'moj plik'})
            wyj = self.uruchom(skrypt, b2, id2, 'wgraj', msys(k['kat']), 'system', 'restart')
            self.assertIn('innego egzemplarza', wyj)
            self.assertEqual(self.czytaj(b2, 'root', hw2), 'moj plik\n')
            self.assertFalse(os.path.exists(os.path.join(b2, 'root', hw1)))
            self.assertTrue(os.path.exists(os.path.join(b2, 'etc', 'rc.local')))

            # ten sam egzemplarz po flashowaniu (bez pliku) - plik wraca z kopii
            os.remove(os.path.join(b1, 'root', hw1))
            wyj = self.uruchom(skrypt, b1, id1, 'wgraj', msys(k['kat']), 'system', 'restart')
            self.assertIn('wrocil z kopii', wyj)
            self.assertIn('C271', self.czytaj(b1, 'root', hw1))
            # ten sam egzemplarz z nowszym plikiem - zostaje nowszy
            with open(os.path.join(b1, 'root', hw1), 'a', newline='\n') as f:
                f.write('2026-12-01 nowszy wpis\n')
            self.uruchom(skrypt, b1, id1, 'wgraj', msys(k['kat']), 'system', 'restart')
            self.assertIn('nowszy wpis', self.czytaj(b1, 'root', hw1))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
