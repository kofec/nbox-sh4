# -*- coding: utf-8 -*-
#
# Test NBoxCEC/plugin.py na atrapach enigmy (PC, Python 3):
#   python enigma2/test_plugin_atrapy.py
# Atrapy odtwarzaja zachowanie z boxow, na ktorym wtyczka sie wywrocila:
# ConfigSubsection.__getattr__ dla brakujacej nazwy rzuca KeyError (bajtkod
# Components/config.pyo z GraterliaOS: return self.content.items[name]), a wyjatek
# z wywolania timera enigmy krecil petla glowna na 100% CPU (2026-10-22).

import importlib.util
import os
import sys
import tempfile
import types
import unittest

TU = os.path.dirname(os.path.abspath(__file__))


class Element(object):
    def __init__(self, default=None, choices=None):
        self._value = default
        self.default = default
        self.notifiers = []

    def _get(self):
        return self._value

    def _set(self, v):
        if v != self._value:
            self._value = v
            for n in list(self.notifiers):
                n(self)

    value = property(_get, _set)

    def addNotifier(self, f, initial_call=True, immediate_feedback=True):
        self.notifiers.append(f)
        if initial_call:
            f(self)

    def save(self):
        pass

    def cancel(self):
        pass


class Content(object):
    pass


class ConfigSubsection(object):
    def __init__(self):
        self.__dict__['content'] = Content()
        self.content.items = {}

    def __setattr__(self, name, value):
        self.content.items[name] = value

    def __getattr__(self, name):
        return self.content.items[name]     # KeyError, jak na boxie


class ETimer(object):
    wszystkie = []

    def __init__(self):
        self.callback = []
        self.aktywny = False
        self.ms = None
        self.single = None
        ETimer.wszystkie.append(self)

    def start(self, ms, single=False):
        self.aktywny, self.ms, self.single = True, ms, single

    def stop(self):
        self.aktywny = False

    def isActive(self):
        return self.aktywny

    def odpal(self):
        """Jak petla enigmy: wyjatek z callbacku = blad testu."""
        if self.single:
            self.aktywny = False
        for f in list(self.callback):
            f()


class Ekran(object):
    def __init__(self, session):
        self.pola = {}
        self.onClose = []
        self.zamkniety = False

    def __setitem__(self, k, v):
        self.pola[k] = v

    def __getitem__(self, k):
        return self.pola[k]

    def setTitle(self, t):
        self.tytul = t

    def close(self, *a):
        self.zamkniety = True
        for f in self.onClose:
            f()


class ListaUstawien(object):
    """ConfigListScreen: lista w self['config'], strzalki zmieniaja wybrany element."""

    def __init__(self, lista, session=None):
        self['config'] = types.SimpleNamespace(list=lista, l=types.SimpleNamespace(setList=lambda l: None))
        self.wybrany = 0

    def keyLeft(self):
        pass

    def keyRight(self):
        el = self['config'].list[self.wybrany][1]
        if isinstance(el.value, bool):
            el.value = not el.value


class ActionMapAtrapa(object):
    """eActionMap.getInstance().keyPressed(urzadzenie, klawisz, flaga) -> lista."""
    wcisniete = []
    blad = None

    @classmethod
    def getInstance(cls):
        return cls

    @classmethod
    def keyPressed(cls, urzadzenie, klawisz, flaga):
        if cls.blad:
            raise cls.blad
        cls.wcisniete.append((urzadzenie, klawisz, flaga))


def atrapy():
    m = {}

    def mod(nazwa, **attr):
        x = types.ModuleType(nazwa)
        x.__dict__.update(attr)
        m[nazwa] = x
        return x

    config = ConfigSubsection()
    config.plugins = ConfigSubsection()
    config.misc = ConfigSubsection()
    config.misc.standbyCounter = Element(0)
    mod('enigma', eTimer=ETimer, eActionMap=ActionMapAtrapa)
    mod('Plugins')
    mod('Plugins.Plugin', PluginDescriptor=type('PluginDescriptor', (), {
        'WHERE_SESSIONSTART': 1, 'WHERE_MENU': 2, 'WHERE_PLUGINMENU': 3,
        '__init__': lambda self, **kw: None}))
    mod('Plugins.SystemPlugins')
    pakiet = mod('Plugins.SystemPlugins.NBoxCEC')
    pakiet.__path__ = [os.path.join(TU, 'NBoxCEC')]
    mod('Screens')
    mod('Screens.Screen', Screen=Ekran)
    sb = mod('Screens.Standby', inStandby=None, Standby=type('Standby', (), {}))
    m['Screens'].Standby = sb
    mod('Components')
    mod('Components.ActionMap', ActionMap=lambda *a, **k: None)
    mod('Components.ConfigList', ConfigListScreen=ListaUstawien)
    mod('Components.Sources')
    mod('Components.Sources.StaticText', StaticText=lambda t='': types.SimpleNamespace(text=t))
    mod('Components.config', config=config, ConfigSubsection=ConfigSubsection,
        ConfigYesNo=Element, ConfigSelection=Element, ConfigText=Element,
        getConfigListEntry=lambda *a: a, configfile=types.SimpleNamespace(save=lambda: None))
    return m, config


class Plugin(unittest.TestCase):
    def setUp(self):
        ETimer.wszystkie = []
        self.moduly, self.config = atrapy()
        self.stare = {k: sys.modules.get(k) for k in self.moduly}
        sys.modules.update(self.moduly)
        sys.modules.pop('Plugins.SystemPlugins.NBoxCEC.cec_core', None)
        spec = importlib.util.spec_from_file_location('nboxcec_plugin', os.path.join(TU, 'NBoxCEC', 'plugin.py'))
        self.p = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.p)
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, 'nboxcec.log')
        self.tx = os.path.join(self.tmp, 'cec_tx')
        self.p.LOG = self.log
        self.p.PROC = os.path.join(self.tmp, 'cec_rx')
        self.p.CEC_TX = self.tx
        self.p.HOTPLUG = os.path.join(self.tmp, 'hotplug')
        self.p.ADRES = os.path.join(self.tmp, 'cec_address')
        self.p.NBOX_CEC = os.path.join(self.tmp, 'nbox_cec')            # nie ma = cec_ctrl
        self.p.KLAWISZE = os.path.join(self.tmp, 'nbox_cec_klawisze')
        self.p.STANDBY_PARAM = os.path.join(self.tmp, 'standby')
        ActionMapAtrapa.wcisniete = []
        ActionMapAtrapa.blad = None
        self.nadane = []
        self.p.autostart(0, session=types.SimpleNamespace(open=lambda *a: None))
        self.s = self.p.sterownik
        self.u = self.p.ust

    def tearDown(self):
        self.s.pilot_stop()                         # otwarty plik nie da sie skasowac (Windows)
        for k, v in self.stare.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def tekst(self):
        with open(self.log, encoding='utf-8') as f:
            return f.read()

    def zapisz(self, sciezka, tresc):
        with open(sciezka, 'w') as f:
            f.write(tresc)

    def wlacz(self, **ust):
        for k, v in ust.items():
            getattr(self.u, k).value = v
        self.u.enable.value = True                  # jak /api/saveconfig
        self.s.ust_timer.odpal()

    def test_wlaczenie_bez_wtyczki_graterlii(self):
        self.assertIn('wylaczona (wersja', self.tekst())
        self.assertFalse(self.s.timer.isActive())
        self.u.profil.value = 'cisza'
        self.u.enable.value = True
        self.assertTrue(self.s.ust_timer.isActive())
        self.s.ust_timer.odpal()                    # config.plugins.CEC -> KeyError
        self.assertTrue(self.s.timer.isActive())
        self.assertEqual(self.s.timer.ms, 2000)
        self.assertFalse(self.s.timer.single)
        self.assertIn('start %s: profil=cisza' % self.p.WERSJA, self.tekst())
        self.assertIn('UWAGA: brak', self.tekst())  # nie ma cec_rx
        for _ in range(5):
            self.s.timer.odpal()
        self.assertNotIn('blad', self.tekst())

    def test_wyjatek_w_konfiguracji_nie_wychodzi(self):
        self.p.cec_core.TvTracker = None            # TypeError w konfiguruj
        self.wlacz()
        self.assertIn('blad (konfiguruj)', self.tekst())

    def test_ramki_i_wlaczenie_tv(self):
        self.zapisz(self.p.ADRES, '3.0.0.0')
        self.wlacz(profil='odpytywanie', tv_wl='obudz_nbox', box_wl='wlacz_tv_wejscie')
        teraz = __import__('time').time()
        self.zapisz(self.p.PROC, '# PIO 4.4\n1 %.3f 0>F 0f- 84- 00- 00- 00-\n2 %.3f 0>F 0f- 80- 00- 00- 30- 00-\n'
                    % (teraz - 2, teraz - 1))
        sb = types.SimpleNamespace(onClose=[], Power=lambda: self.nadane.append('Power'))
        sys.modules['Screens.Standby'].inStandby = sb
        self.config.misc.standbyCounter.value = 1   # box w standby
        self.s.timer.odpal()
        t = self.tekst()
        self.assertIn('TV: tv y', t)
        self.assertIn('TV: wejscie nbox 3.0.0.0', t)
        self.assertIn('AKCJA obudz_box', t)
        self.assertEqual(self.nadane, ['Power'])
        sys.modules['Screens.Standby'].inStandby = None
        for f in sb.onClose:
            f()
        self.assertNotIn('CEC ->', self.tekst())    # obudzony przez wtyczke - TV nie ruszac
        # obudzony pilotem: wlacz TV i przelacz na nBox, z wlasnym adresem
        sys.modules['Screens.Standby'].inStandby = sb
        self.config.misc.standbyCounter.value = 2
        sys.modules['Screens.Standby'].inStandby = None
        for f in sb.onClose:
            f()
        while self.s.tx_timer.isActive() or self.s.kolejka:
            self.s.tx_timer.odpal()
        t = self.tekst()
        self.assertEqual(t.count('CEC -> 3004'), 2)
        self.assertEqual(t.count('CEC -> 3f823000'), 2)
        self.assertNotIn('blad', t)

    def test_nowa_akcja_kasuje_stara_kolejke(self):
        # Sony BRAVIA 8, 22.10 23:56: uspienie pilotem (3036 x2), po 2 s obudzenie -
        # drugie 3036 nie moze pojsc po obudzeniu, przed 3004
        self.zapisz(self.p.ADRES, '1.0.0.0')
        self.wlacz(box_wl='wlacz_tv_wejscie', box_wyl='wylacz_tv')
        sb = types.SimpleNamespace(onClose=[], Power=lambda: None)
        sys.modules['Screens.Standby'].inStandby = sb
        self.config.misc.standbyCounter.value = 1   # pilot: standby
        self.assertEqual(self.s.kolejka, ['3036'])  # pierwsze 3036 juz poszlo
        sys.modules['Screens.Standby'].inStandby = None
        for f in sb.onClose:                        # pilot: obudzenie
            f()
        while self.s.tx_timer.isActive() or self.s.kolejka:
            self.s.tx_timer.odpal()
        t = self.tekst()
        nadane = [l.split('CEC -> ')[1] for l in t.splitlines() if 'CEC -> ' in l]
        self.assertEqual(nadane, ['3036', '3004', '3004', '3f821000', '3f821000'])
        self.assertIn('CEC pominiete (nowa akcja): 3036', t)
        self.assertNotIn('blad', t)

    def test_stare_ramki_przy_starcie(self):
        # bufor z ramkami sprzed 6 h (Sony BRAVIA 8, 23.10 06:15) - bez "tv y"
        self.zapisz(self.p.ADRES, '1.0.0.0')
        self.wlacz(profil='cisza', tv_wl='obudz_nbox')
        teraz = __import__('time').time()
        self.zapisz(self.p.PROC, '# PIO 4.4\n1 %.3f 3>F 3f+ 82+ 10+ 00+\n2 %.3f 0>F 0f- a0- 08- 00- 46- 00- 09- 00- 01-\n'
                    % (teraz - 22750, teraz - 22745))
        self.s.timer.odpal()
        self.assertNotIn('TV:', self.tekst())
        # nowe ramki juz normalnie
        with open(self.p.PROC, 'a') as f:
            f.write('3 %.3f 0>F 0f- 84- 10- 00- 00-\n' % teraz)
        self.s.timer.odpal()
        self.assertIn('TV: tv y', self.tekst())

    def test_zapas_hotplug(self):
        self.zapisz(self.p.HOTPLUG, 'y')
        self.wlacz(zapas='hotplug')
        self.s.timer.odpal()
        self.assertIn('TV: tv y', self.tekst())
        self.zapisz(self.p.HOTPLUG, 'n')
        self.s.timer.odpal()
        self.assertNotIn('TV: tv n', self.tekst())  # mrugniecie
        self.s.hp_n_od -= 20
        self.s.timer.odpal()
        self.assertIn('TV: tv n', self.tekst())

    def test_wylaczenie_wtyczki_graterlii(self):
        cec = ConfigSubsection()
        cec.Enable = Element(True)
        self.config.plugins.CEC = cec
        self.wlacz()
        self.assertIn('UWAGA: wlaczona wtyczka CEC Graterlii', self.tekst())
        self.assertTrue(cec.Enable.value)
        self.u.wylacz_graterlie.value = True
        self.s.ust_timer.odpal()
        self.assertFalse(cec.Enable.value)
        self.assertIn('wylaczona wtyczka CEC Graterlii', self.tekst())

    def test_ekran_ustawien(self):
        ekran = self.p.NBoxCECSetup(None)
        self.assertEqual(len(ekran['config'].list), 1)      # tylko "Wlaczona"
        ekran.keyRight()                                    # wlacz
        nazwy = [x[0] for x in ekran['config'].list]
        self.assertIn('TV włączony', nazwy)
        self.assertNotIn('TV wyłączony: uśpij po', nazwy)   # tv_wyl = nic
        self.assertNotIn('Wyłącz wtyczkę CEC Graterlii', nazwy)
        self.u.tv_wyl.value = 'usypiaj'
        ekran.przebuduj()
        self.assertIn('TV wyłączony: uśpij po', [x[0] for x in ekran['config'].list])
        ekran.status_timer.odpal()
        self.assertTrue(ekran['status'].text)
        ekran.anuluj()
        self.assertFalse(ekran.status_timer.isActive())

    def test_log_obcinany(self):
        self.p.LOG_MAX_B = 2000
        for i in range(200):
            self.s.log('linia %03d xxxxxxxxxxxxxxxxxxxx' % i)
        self.assertLess(os.path.getsize(self.log), 2100)
        t = self.tekst()
        self.assertIn('linia 199', t)
        self.assertTrue(t.split('\n')[0][:4].isdigit())     # od pelnej linii

    # --- 2.0: modul nbox_cec ---

    def dopisz(self, sciezka, tresc):
        with open(sciezka, 'a') as f:
            f.write(tresc)

    def test_pilot_tv(self):
        self.zapisz(self.p.KLAWISZE, '44 01\n45\n')        # sprzed startu - do kosza
        self.wlacz()
        self.assertTrue(self.s.pilot_timer.isActive())
        self.assertEqual(self.s.pilot_timer.ms, 100)
        self.s.pilot_timer.odpal()
        self.assertEqual(ActionMapAtrapa.wcisniete, [])
        self.dopisz(self.p.KLAWISZE, '44 00\n45\n44 30\n')  # OK, kanal + (bez 45)
        self.s.pilot_timer.odpal()
        u = self.p.PILOT_URZADZENIE
        self.assertEqual(ActionMapAtrapa.wcisniete, [(u, 352, 0), (u, 352, 1), (u, 402, 0)])
        self.s.pilot.od -= 1                                # TV nie przyslal 45
        self.s.pilot_timer.odpal()
        self.assertEqual(ActionMapAtrapa.wcisniete[-1], (u, 402, 1))
        self.dopisz(self.p.KLAWISZE, '44 76\n')
        self.s.pilot_timer.odpal()
        t = self.tekst()
        self.assertIn('pilot TV: 00 -> 352', t)
        self.assertIn('pilot TV: kod 76 bez klawisza', t)
        self.assertIn('modul=cec_rx pilot_tv=True', t)
        self.assertNotIn('blad', t)

    def test_pilot_power_od_tv(self):
        # LG webOS 23.10 16:23: Power przy wylaczaniu TV obudzil box (KEY_POWER)
        self.zapisz(self.p.KLAWISZE, '')
        self.wlacz(tv_wyl='usypiaj')
        self.s.pilot_timer.odpal()
        self.s.policy.tv = 'y'
        self.dopisz(self.p.KLAWISZE, '44 40\n45\n')
        self.s.pilot_timer.odpal()
        self.assertEqual(ActionMapAtrapa.wcisniete, [])     # bez KEY_POWER
        self.assertIn('pilot TV: 40 -> za stanem TV', self.tekst())
        self.s.policy.tv = 'n'                              # Standby od TV
        otwarte = []
        self.s.session = types.SimpleNamespace(open=lambda *a: otwarte.append(a))
        self.s.wykonaj(self.s.policy.tick(self.s.policy.power_o + 0.1))
        self.assertEqual(len(otwarte), 1)                   # Screens.Standby
        self.assertIn('AKCJA uspij_box (Power od TV, TV wylaczony)', self.tekst())
        self.assertNotIn('blad', self.tekst())

    def test_pilot_tv_wylaczony_albo_bez_modulu(self):
        self.wlacz()                                        # bez pliku klawiszy
        self.assertFalse(self.s.pilot_timer.isActive())
        self.zapisz(self.p.KLAWISZE, '')
        self.wlacz(pilot_tv=False)
        self.assertFalse(self.s.pilot_timer.isActive())

    def test_pilot_blad_wylacza_pilota_raz(self):
        self.zapisz(self.p.KLAWISZE, '')
        self.wlacz()
        ActionMapAtrapa.blad = RuntimeError('brak eActionMap')
        self.dopisz(self.p.KLAWISZE, '44 00\n')
        self.s.pilot_timer.odpal()
        self.assertFalse(self.s.pilot_timer.isActive())
        self.assertEqual(self.tekst().count('blad (pilot_krok)'), 1)

    def test_standby_modulu(self):
        self.zapisz(self.p.STANDBY_PARAM, '0')
        self.wlacz()
        sb = types.SimpleNamespace(onClose=[], Power=lambda: None)
        sys.modules['Screens.Standby'].inStandby = sb
        self.config.misc.standbyCounter.value = 1
        with open(self.p.STANDBY_PARAM) as f:
            self.assertEqual(f.read(), '1')
        sys.modules['Screens.Standby'].inStandby = None
        for f in sb.onClose:
            f()
        with open(self.p.STANDBY_PARAM) as f:
            self.assertEqual(f.read(), '0')

    def test_z_modulem_ramki_raz_przez_nbox_cec(self):
        self.zapisz(self.p.NBOX_CEC, '')
        self.zapisz(self.p.ADRES, '4.0.0.0')
        self.wlacz(box_wl='wlacz_tv_wejscie')
        self.assertIn('modul=nbox_cec', self.tekst())
        sb = types.SimpleNamespace(onClose=[], Power=lambda: None)
        sys.modules['Screens.Standby'].inStandby = sb
        self.config.misc.standbyCounter.value = 1
        sys.modules['Screens.Standby'].inStandby = None
        for f in sb.onClose:                                # pilot nBoxa: obudzenie
            f()
        while self.s.tx_timer.isActive() or self.s.kolejka:
            self.s.tx_timer.odpal()
        t = self.tekst()
        nadane = [l.split('CEC -> ')[1] for l in t.splitlines() if 'CEC -> ' in l]
        self.assertEqual(nadane, ['3004', '3f824000'])     # bez powtorzen
        with open(self.p.NBOX_CEC) as f:
            self.assertEqual(f.read(), '3f824000')
        self.assertFalse(os.path.exists(self.tx))           # nie do cec_ctrl

    def test_ekran_bez_powtorzen_z_modulem(self):
        self.zapisz(self.p.NBOX_CEC, '')
        self.u.box_wl.value = 'wlacz_tv'
        ekran = self.p.NBoxCECSetup(None)
        ekran.keyRight()
        nazwy = [x[0] for x in ekran['config'].list]
        self.assertNotIn('Powtórzenia poleceń do TV', nazwy)
        self.assertIn('Pilot TV steruje nBoxem (moduł nbox_cec)', nazwy)
        ekran.anuluj()

    def test_standby_i_powrot(self):
        self.wlacz()
        sb = types.SimpleNamespace(onClose=[], Power=lambda: None)
        sys.modules['Screens.Standby'].inStandby = sb
        self.config.misc.standbyCounter.value = 1
        self.assertIn('box: standby', self.tekst())
        sys.modules['Screens.Standby'].inStandby = None
        for f in sb.onClose:
            f()
        self.assertIn('box: dziala', self.tekst())
        self.assertNotIn('blad', self.tekst())


if __name__ == '__main__':
    unittest.main()
