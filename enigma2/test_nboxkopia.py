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
import subprocess
import sys
import tempfile
import time
import types
import unittest

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
    mod('Components')
    mod('Components.ActionMap', ActionMap=lambda *a, **k: None)
    mod('Components.ConfigList', ConfigListScreen=A.ListaUstawien)
    mod('Components.MenuList', MenuList=MenuListAtrapa)
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
        self.p.autostart(0, session=Sesja())
        self.h = self.p.harmonogram

    def tearDown(self):
        os.system = self.stary_system
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
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
