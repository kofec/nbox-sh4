# -*- coding: utf-8 -*-
#
# nBox CEC - wtyczka enigmy (GraterliaOS / OpenPLi, Python 2.7) do
# wspolpracy nBoxa z telewizorem przez HDMI-CEC:
#   - odczyt: stan TV i wejscie, ktore TV pokazuje, z podsluchu CEC
#     (/proc/cec_rx, pakiet kernel-module-cec-rx); zapas: hotplug HDMI,
#   - sterowanie boxem: obudz / uspij wg TV (np. budz tylko, gdy ktos wybierze
#     wejscie nBoxa, a nie Smart TV),
#   - sterowanie TV: wlacz / przelacz wejscie / wylacz przy budzeniu i
#     usypianiu boxa (przez /proc/stb/hdmi/cec, modul cec_ctrl Graterlii),
#   - z modulem nbox_cec (sh4/nbox_cec): pilot TV steruje nBoxem
#     (/proc/nbox_cec_klawisze -> eActionMap.keyPressed, jak OpenWebif
#     remotecontrol), modul zna stan boxa (parametr standby - TV pyta o
#     zasilanie), polecenia do TV raz przez /proc/nbox_cec (modul sam
#     sprawdza ACK i ponawia).
# Kazda funkcja osobno w menu: Ustawienia -> System -> nBox CEC. Domyslnie
# wszystko "nic" i wtyczka wylaczona - sama instalacja niczego nie zmienia.
#
# Bez nbox_cec (sam podsluch cec_rx) TV nie widzi nBoxa jako urzadzenia CEC:
# bez pilota TV -> box, bez nazwy na liscie zrodel. Nazwe, adres i odpowiedzi
# na zapytania TV daje sam modul, wtyczka do tego niepotrzebna.
#
# Nie uruchamiac razem z wtyczka CEC Graterlii (config.plugins.CEC.Enable;
# opcja w menu ja wylacza) ani z nbox_tv.sh - kazde z nich steruje tym samym.
#
# Logika (bez enigmy, z testami): cec_core.py; test tej czesci na atrapach
# enigmy: enigma2/test_plugin_atrapy.py. Log: /tmp/nboxcec.log.
# Zdalnie: OpenWebif /api/saveconfig?key=config.plugins.nboxcec.<nazwa>&value=...
# (np. enable=true) - wtyczka przeladowuje ustawienia sama; do pliku settings
# trafiaja dopiero przy zamknieciu enigmy.
#
# Kazde wywolanie z enigmy (timery, notifiery, standby) jest w try/except:
# wyjatek z callbacku timera krecil petla enigmy na 100% CPU (2026-10-22).

import errno
import os
import time
import traceback

from enigma import eTimer, eActionMap
from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.Sources.StaticText import StaticText
from Components.config import config, ConfigSubsection, ConfigYesNo, \
    ConfigSelection, ConfigText, getConfigListEntry, configfile
import Screens.Standby

from Plugins.SystemPlugins.NBoxCEC import cec_core

WERSJA = '2.0.2'
PROC = '/proc/cec_rx'
CEC_TX = '/proc/stb/hdmi/cec'
NBOX_CEC = '/proc/nbox_cec'                     # modul nbox_cec: nadawanie z ACK
KLAWISZE = '/proc/nbox_cec_klawisze'
STANDBY_PARAM = '/sys/module/nbox_cec/parameters/standby'
PILOT_MS = 100
PILOT_URZADZENIE = 'dreambox remote control (native)'   # jak OpenWebif (rcused standard)
HOTPLUG = '/sys/class/stmcoredisplay/hdmi0.0/hotplug'
ADRES = '/sys/class/stmcoredisplay/hdmi0.0/cec_address'
NBOX_TV_PID = '/tmp/nbox_tv.pid'
LOG = '/tmp/nboxcec.log'
LOG_MAX_B = 64 * 1024   # potem zostaje druga polowa
KROK_MS = 2000
HOTPLUG_N_PO = 15       # hotplug n tyle s = TV wylaczony (zmiana trybu mruga)
ODSTEP_TX_MS = 300


def sekundy(lista):
    return [(str(s), opis) for s, opis in lista]


config.plugins.nboxcec = ConfigSubsection()
ust = config.plugins.nboxcec
ust.enable = ConfigYesNo(default=False)
ust.profil = ConfigSelection(default=cec_core.PROFIL_ZDARZENIA, choices=[
    (cec_core.PROFIL_CISZA, 'cisza w standby (LG starszy, Sony)'),
    (cec_core.PROFIL_ODPYTYWANIE, 'odpytuje urządzenia, gdy włączony (LG webOS)'),
    (cec_core.PROFIL_ZDARZENIA, 'tylko zdarzenia włącz / wyłącz'),
])
ust.cisza = ConfigSelection(default='60', choices=sekundy([
    (30, '30 s'), (60, '60 s'), (90, '90 s'), (150, '150 s'), (300, '5 min')]))
ust.zapas = ConfigSelection(default='brak', choices=[
    ('brak', 'brak'), ('hotplug', 'hotplug HDMI')])
ust.tv_wl = ConfigSelection(default='nic', choices=[
    ('nic', 'nic'), ('obudz', 'obudź nBox'),
    ('obudz_nbox', 'obudź nBox, gdy TV przełączy się na jego wejście')])
ust.tv_wyl = ConfigSelection(default='nic', choices=[
    ('nic', 'nic'), ('usypiaj', 'uśpij nBox')])
ust.tv_wyl_po = ConfigSelection(default='180', choices=sekundy([
    (15, '15 s'), (60, '1 min'), (180, '3 min'), (300, '5 min'), (600, '10 min'), (1800, '30 min')]))
ust.tv_inne = ConfigSelection(default='nic', choices=[
    ('nic', 'nic'), ('usypiaj', 'uśpij nBox')])
ust.tv_inne_po = ConfigSelection(default='600', choices=sekundy([
    (60, '1 min'), (300, '5 min'), (600, '10 min'), (1800, '30 min'), (3600, '1 h')]))
ust.box_wl = ConfigSelection(default='nic', choices=[
    ('nic', 'nic'), ('wlacz_tv', 'włącz TV'),
    ('wlacz_tv_wejscie', 'włącz TV i przełącz na nBox')])
ust.box_wyl = ConfigSelection(default='nic', choices=[
    ('nic', 'nic'), ('wylacz_tv_nbox', 'wyłącz TV, jeśli pokazuje nBox'),
    ('wylacz_tv', 'wyłącz TV zawsze')])
ust.adres = ConfigSelection(default='auto', choices=[
    ('auto', 'automatycznie (z HDMI)'), ('1.0.0.0', 'HDMI 1'), ('2.0.0.0', 'HDMI 2'),
    ('3.0.0.0', 'HDMI 3'), ('4.0.0.0', 'HDMI 4')])
ust.adres_ost = ConfigText(default='')     # ostatni adres z HDMI (TV wylaczony = 0.0.0.0)
ust.powtorz = ConfigSelection(default='2', choices=sekundy([(1, '1'), (2, '2'), (3, '3')]))
ust.wylacz_graterlie = ConfigYesNo(default=False)
# reaguje tylko na klawisze, ktore ktos nacisnie na pilocie TV przy wejsciu nBoxa
ust.pilot_tv = ConfigYesNo(default=True)
ust.log = ConfigYesNo(default=True)
USTAWIENIA = (ust.enable, ust.profil, ust.cisza, ust.zapas, ust.tv_wl, ust.tv_wyl,
              ust.tv_wyl_po, ust.tv_inne, ust.tv_inne_po, ust.box_wl, ust.box_wyl,
              ust.adres, ust.powtorz, ust.wylacz_graterlie, ust.pilot_tv, ust.log)

OPISY_TV = {'y': 'włączony', 'n': 'wyłączony', None: 'nie wiadomo'}
OPISY_WE = {'nbox': 'nBox', 'inne': 'inne źródło', None: 'nie wiadomo'}


def czytaj(sciezka):
    try:
        f = open(sciezka)
        try:
            return f.read().strip()
        finally:
            f.close()
    except (IOError, OSError):
        return None


def modul_nbox_cec():
    return os.path.exists(NBOX_CEC)


def wtyczka_graterlii():
    """config.plugins.CEC albo None. ConfigSubsection.__getattr__ w enigmie dla
    brakujacej nazwy rzuca KeyError, nie AttributeError (bajtkod config.pyo)."""
    try:
        return config.plugins.CEC
    except (AttributeError, KeyError):
        return None


def bezpiecznie(f):
    """Wywolanie z enigmy: wyjatek tylko do logu, nigdy do petli enigmy."""
    def opak(self, *a):
        try:
            return f(self, *a)
        except Exception:
            self.log('blad (%s): %s' % (f.__name__, traceback.format_exc().replace('\n', ' | ')))
    opak.__name__ = f.__name__
    return opak


class Sterownik(object):
    def __init__(self, session):
        self.session = session
        self.timer = eTimer()
        self.timer.callback.append(self.krok)
        self.tx_timer = eTimer()
        self.tx_timer.callback.append(self.nadaj_kolejke)
        self.pilot_timer = eTimer()
        self.pilot_timer.callback.append(self.pilot_krok)
        self.pilot = cec_core.Pilot()
        self.kl_fd = None
        self.kolejka = []
        self.zrodlo = None
        self.hp = None
        self.hp_n_od = None
        self.n_krok = 0
        self.tracker = None
        config.misc.standbyCounter.addNotifier(self.wszedl_w_standby, initial_call=False)
        # zmiana ustawien takze spoza menu (OpenWebif /api/saveconfig) - jedno
        # przeladowanie po serii zmian
        self.ust_timer = eTimer()
        self.ust_timer.callback.append(self.konfiguruj)
        for el in USTAWIENIA:
            el.addNotifier(self.zmiana_ust, initial_call=False)
        self.konfiguruj()

    @bezpiecznie
    def zmiana_ust(self, el):
        self.ust_timer.start(500, True)

    # --- ustawienia ---

    @bezpiecznie
    def konfiguruj(self):
        self.timer.stop()
        self.pilot_stop()
        teraz = time.time()
        self.ustaw_standby(Screens.Standby.inStandby is not None)
        self.reader = cec_core.ProcReader()
        self.tracker = cec_core.TvTracker(ust.profil.value, cisza_s=int(ust.cisza.value),
                                          own_pa=self.wlasny_adres(), t0=teraz)
        self.policy = cec_core.Policy({
            'tv_wl': ust.tv_wl.value, 'tv_wyl': ust.tv_wyl.value,
            'tv_wyl_po': int(ust.tv_wyl_po.value),
            'tv_inne': ust.tv_inne.value, 'tv_inne_po': int(ust.tv_inne_po.value),
            'box_wl': ust.box_wl.value, 'box_wyl': ust.box_wyl.value})
        self.policy.box_event(Screens.Standby.inStandby is not None, teraz)
        self.hp = None
        self.hp_n_od = None
        self.pierwszy = True        # pierwszy odczyt bufora = historia
        if not ust.enable.value:
            self.log('wylaczona (wersja %s)' % WERSJA)
            return
        self.log('start %s: profil=%s cisza=%s zapas=%s tv_wl=%s tv_wyl=%s/%s tv_inne=%s/%s '
                 'box_wl=%s box_wyl=%s adres=%s modul=%s pilot_tv=%s' % (
                     WERSJA, ust.profil.value, ust.cisza.value, ust.zapas.value, ust.tv_wl.value,
                     ust.tv_wyl.value, ust.tv_wyl_po.value, ust.tv_inne.value, ust.tv_inne_po.value,
                     ust.box_wl.value, ust.box_wyl.value, self.adres_tekst(),
                     modul_nbox_cec() and 'nbox_cec' or 'cec_rx', ust.pilot_tv.value))
        self.timer.start(KROK_MS)
        self.pilot_start()
        self.ostrzezenia()

    def ostrzezenia(self):
        g = wtyczka_graterlii()
        if g is not None and g.Enable.value:
            if ust.wylacz_graterlie.value:
                g.Enable.value = False
                g.Enable.save()
                configfile.save()
                self.log('wylaczona wtyczka CEC Graterlii (config.plugins.CEC.Enable=false)')
            else:
                self.log('UWAGA: wlaczona wtyczka CEC Graterlii - steruje tym samym')
        pid = czytaj(NBOX_TV_PID)
        if pid and pid.isdigit() and os.path.exists('/proc/' + pid):
            self.log('UWAGA: dziala nbox_tv.sh (PID %s) - steruje tym samym' % pid)
        if not os.path.exists(PROC):
            self.log('UWAGA: brak %s (cec_rx.ko) - zrodlo: %s' % (PROC, ust.zapas.value))
        if not os.path.exists(self.tx_plik()) and (ust.box_wl.value != 'nic' or ust.box_wyl.value != 'nic'):
            self.log('UWAGA: brak %s (cec_ctrl) - sterowanie TV nie zadziala' % CEC_TX)

    def wlasny_adres(self):
        if ust.adres.value != 'auto':
            return cec_core.pa_parse(ust.adres.value)
        pa = cec_core.pa_parse(czytaj(ADRES) or '')
        if pa and pa != (0, 0, 0, 0):
            s = '%d.%d.%d.%d' % pa
            if ust.adres_ost.value != s:
                ust.adres_ost.value = s
                ust.adres_ost.save()
                configfile.save()
            return pa
        return cec_core.pa_parse(ust.adres_ost.value)

    def adres_tekst(self):
        pa = self.tracker and self.tracker.own_pa
        return pa and '%d.%d.%d.%d' % pa or '?'

    # --- petla ---

    @bezpiecznie
    def krok(self):
        teraz = time.time()
        self.n_krok += 1
        if self.n_krok % 30 == 0:
            self.tracker.own_pa = self.wlasny_adres()
        zd = []
        if os.path.exists(PROC):
            self.zrodlo = 'cec'
            f = open(PROC)
            try:
                linie = f.readlines()
            finally:
                f.close()
            ramki = self.reader.new_frames(linie)
            if self.pierwszy:
                ramki = cec_core.swieze(ramki, teraz, self.tracker.cisza_s)
            zd = self.tracker.feed(ramki, teraz)
            if self.pierwszy:
                zd = cec_core.tylko_koncowe(zd)
                self.pierwszy = False
        elif ust.zapas.value == 'hotplug':
            self.zrodlo = 'hotplug'
            zd = self.hotplug(teraz)
        else:
            self.zrodlo = None
        for z in zd:
            self.log('TV: %s' % (' '.join(z),))
            self.wykonaj(self.policy.tv_event(z, teraz))
        self.wykonaj(self.policy.tick(teraz))

    def hotplug(self, teraz):
        hp = czytaj(HOTPLUG)
        if hp == 'n':
            if self.hp_n_od is None:
                self.hp_n_od = teraz
            if teraz - self.hp_n_od < HOTPLUG_N_PO:
                return []
        elif hp == 'y':
            self.hp_n_od = None
        else:
            return []
        if hp != self.hp:
            self.hp = hp
            return [('tv', hp)]
        return []

    # --- box ---

    @bezpiecznie
    def wszedl_w_standby(self, el):
        if Screens.Standby.inStandby is not None:
            Screens.Standby.inStandby.onClose.append(self.wyszedl_ze_standby)
        self.box(True)

    @bezpiecznie
    def wyszedl_ze_standby(self):
        self.box(False)

    def box(self, standby):
        self.ustaw_standby(standby)     # prawdziwy stan dla TV, takze bez reszty wtyczki
        if not ust.enable.value:
            return
        self.log('box: %s' % (standby and 'standby' or 'dziala'))
        self.wykonaj(self.policy.box_event(standby, time.time()))

    def ustaw_standby(self, standby):
        """Parametr modulu nbox_cec (Report Power Status dla TV); bez modulu nic."""
        if not os.path.exists(STANDBY_PARAM):
            return
        try:
            f = open(STANDBY_PARAM, 'w')
            try:
                f.write(standby and '1' or '0')
            finally:
                f.close()
        except (IOError, OSError) as e:
            self.log('standby modulu: blad %r' % (e,))

    # --- pilot TV ---

    def pilot_start(self):
        if not ust.pilot_tv.value or not os.path.exists(KLAWISZE):
            return
        # O_NONBLOCK: pusta kolejka = EAGAIN, nie blokuje enigmy (na Windows
        # w testach go nie ma - tam zwykly plik)
        self.kl_fd = os.open(KLAWISZE, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        self.czytaj_klawisze()          # stare klawisze sprzed startu - do kosza
        self.pilot = cec_core.Pilot()
        self.pilot_timer.start(PILOT_MS)

    def pilot_stop(self):
        self.pilot_timer.stop()
        if self.kl_fd is not None:
            try:
                os.close(self.kl_fd)
            except OSError:
                pass
            self.kl_fd = None

    def czytaj_klawisze(self):
        try:
            return os.read(self.kl_fd, 512).decode('ascii', 'replace').splitlines()
        except OSError as e:
            if e.errno == errno.EAGAIN:
                return []
            raise

    def pilot_krok(self):
        # co 100 ms, wiec nie @bezpiecznie: blad wylacza pilota z jednym wpisem
        # w logu zamiast wpisu co 100 ms
        try:
            teraz = time.time()
            standby = Screens.Standby.inStandby is not None
            zd = self.pilot.feed(self.czytaj_klawisze(), teraz, standby)
            zd += self.pilot.tick(teraz)
            for kod, klawisz, flaga in zd:
                if klawisz is None:
                    self.log('pilot TV: kod %02x bez klawisza' % kod)
                    continue
                if klawisz == cec_core.POWER_TV:    # nie przelacznik - za stanem TV
                    if flaga == cec_core.MAKE:
                        self.log('pilot TV: %02x -> za stanem TV' % kod)
                        self.policy.power_tv(teraz)
                    continue
                if flaga == cec_core.MAKE:
                    self.log('pilot TV: %02x -> %d' % (kod, klawisz))
                eActionMap.getInstance().keyPressed(PILOT_URZADZENIE, klawisz, flaga)
        except Exception:
            self.pilot_stop()
            self.log('blad (pilot_krok), pilot TV wylaczony: %s' %
                     traceback.format_exc().replace('\n', ' | '))

    # --- akcje ---

    def wykonaj(self, akcje):
        for akcja, powod in akcje:
            self.log('AKCJA %s (%s)' % (akcja, powod))
            if akcja == cec_core.WAKE:
                if Screens.Standby.inStandby is not None:
                    Screens.Standby.inStandby.Power()
            elif akcja == cec_core.STANDBY:
                if Screens.Standby.inStandby is None:
                    self.session.open(Screens.Standby.Standby)
            elif akcja == cec_core.TV_ON:
                self.nadaj(['3004'])
            elif akcja == cec_core.TV_ON_INPUT:
                pa = self.tracker.own_pa
                self.nadaj(['3004'] + (pa and ['3f82' + cec_core.pa_bytes(pa)] or []))
            elif akcja == cec_core.TV_OFF:
                self.nadaj(['3036'])

    def nadaj(self, ramki):
        # nowa akcja zastepuje niewyslane ramki poprzedniej (Sony BRAVIA 8, 22.10
        # 23:56: powtorzenie 3036 poszlo juz po obudzeniu boxa, przed 3004)
        if self.kolejka:
            self.log('CEC pominiete (nowa akcja): %s' % ' '.join(self.kolejka))
            self.kolejka = []
        # nbox_cec sam sprawdza ACK i ponawia po NACK - kazda ramka raz;
        # cec_ctrl nadaje na slepo, wiec tam powtorz z ustawien
        ile = modul_nbox_cec() and 1 or int(ust.powtorz.value)
        for r in ramki:
            self.kolejka += [r] * ile
        if not self.tx_timer.isActive():
            self.nadaj_kolejke()

    def tx_plik(self):
        return modul_nbox_cec() and NBOX_CEC or CEC_TX

    @bezpiecznie
    def nadaj_kolejke(self):
        if not self.kolejka:
            return
        r = self.kolejka.pop(0)
        try:
            f = open(self.tx_plik(), 'w')
            try:
                f.write(r)
            finally:
                f.close()
            self.log('CEC -> %s' % r)
        except (IOError, OSError) as e:
            self.log('CEC -> %s: blad %r' % (r, e))
        if self.kolejka:
            self.tx_timer.start(ODSTEP_TX_MS, True)

    # --- log i stan ---

    def log(self, tekst):
        if not ust.log.value:
            return
        try:
            f = open(LOG, 'a')
            try:
                f.write('%s %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), tekst))
            finally:
                f.close()
            if os.path.getsize(LOG) > LOG_MAX_B:
                f = open(LOG, 'rb')
                try:
                    f.seek(-(LOG_MAX_B // 2), 2)
                    f.readline()                # od pelnej linii
                    reszta = f.read()
                finally:
                    f.close()
                f = open(LOG, 'wb')
                try:
                    f.write(reszta)
                finally:
                    f.close()
        except (IOError, OSError):
            pass

    def status(self):
        if not ust.enable.value:
            return 'Wtyczka wyłączona (wersja %s).' % WERSJA
        t = self.tracker
        if t is None:
            return 'Wtyczka nie wystartowała - patrz %s.' % LOG
        we = OPISY_WE.get(t.wejscie)
        if t.sciezka:
            we += ' (%s)' % t.sciezka
        return 'TV: %s, wejście: %s, nBox na %s, źródło: %s' % (
            OPISY_TV.get(t.stan), we, self.adres_tekst(), self.zrodlo or 'brak')


sterownik = None


class NBoxCECSetup(Screen, ConfigListScreen):
    skin = """
    <screen position="center,center" size="900,560" title="nBox CEC">
        <widget name="config" position="10,10" size="880,440" scrollbarMode="showOnDemand" />
        <widget source="status" render="Label" position="10,460" size="880,50" font="Regular;20" />
        <widget source="key_red" render="Label" position="10,520" size="200,30" font="Regular;20" foregroundColor="#ff4040" />
        <widget source="key_green" render="Label" position="220,520" size="200,30" font="Regular;20" foregroundColor="#40ff40" />
    </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self['key_red'] = StaticText('Anuluj')
        self['key_green'] = StaticText('Zapisz')
        self['status'] = StaticText('')
        self['actions'] = ActionMap(['SetupActions', 'ColorActions'], {
            'ok': self.zapisz, 'save': self.zapisz, 'green': self.zapisz,
            'cancel': self.anuluj, 'red': self.anuluj}, -2)
        ConfigListScreen.__init__(self, self.lista(), session=session)
        self.setTitle('nBox CEC %s' % WERSJA)
        self.status_timer = eTimer()
        self.status_timer.callback.append(self.odswiez_status)
        self.status_timer.start(2000)
        self.onClose.append(self.status_timer.stop)
        self.odswiez_status()

    def lista(self):
        """Pola zalezne tylko wtedy, gdy maja znaczenie."""
        e = getConfigListEntry
        l = [e('Włączona', ust.enable)]
        if not ust.enable.value:
            return l
        l.append(e('Odczyt TV: profil telewizora', ust.profil))
        if ust.profil.value != cec_core.PROFIL_ZDARZENIA:
            l.append(e('Odczyt TV: cisza = TV wyłączony po', ust.cisza))
        l += [e('Odczyt TV: zapas bez cec_rx', ust.zapas),
              e('TV włączony', ust.tv_wl),
              e('TV wyłączony', ust.tv_wyl)]
        if ust.tv_wyl.value != 'nic':
            l.append(e('TV wyłączony: uśpij po', ust.tv_wyl_po))
        l.append(e('TV na innym źródle (Smart TV, HDMI)', ust.tv_inne))
        if ust.tv_inne.value != 'nic':
            l.append(e('TV na innym źródle: uśpij po', ust.tv_inne_po))
        l += [e('nBox obudzony (pilot, timer)', ust.box_wl),
              e('nBox uśpiony (pilot, timer)', ust.box_wyl),
              e('Wejście nBoxa w TV', ust.adres)]
        if (ust.box_wl.value != 'nic' or ust.box_wyl.value != 'nic') and not modul_nbox_cec():
            l.append(e('Powtórzenia poleceń do TV', ust.powtorz))
        l.append(e('Pilot TV steruje nBoxem (moduł nbox_cec)', ust.pilot_tv))
        if wtyczka_graterlii() is not None:
            l.append(e('Wyłącz wtyczkę CEC Graterlii', ust.wylacz_graterlie))
        l.append(e('Log %s' % LOG, ust.log))
        return l

    def przebuduj(self):
        self['config'].list = self.lista()
        self['config'].l.setList(self['config'].list)

    def keyLeft(self):
        ConfigListScreen.keyLeft(self)
        self.przebuduj()

    def keyRight(self):
        ConfigListScreen.keyRight(self)
        self.przebuduj()

    def odswiez_status(self):
        try:
            self['status'].text = sterownik and sterownik.status() or ''
        except Exception:
            pass

    def zapisz(self):
        for x in self['config'].list:
            x[1].save()
        configfile.save()
        if sterownik:
            sterownik.konfiguruj()
        self.close()

    def anuluj(self):
        for x in self['config'].list:
            x[1].cancel()
        self.close()


def autostart(reason, **kwargs):
    global sterownik
    if reason == 0 and 'session' in kwargs and sterownik is None:
        sterownik = Sterownik(kwargs['session'])


def main(session, **kwargs):
    session.open(NBoxCECSetup)


def menu(menuid, **kwargs):
    if menuid == 'system':
        return [('nBox CEC', main, 'nbox_cec', 46)]
    return []


def Plugins(**kwargs):
    return [
        PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=autostart),
        PluginDescriptor(name='nBox CEC', description='nBox i telewizor przez HDMI-CEC',
                         where=PluginDescriptor.WHERE_MENU, fnc=menu),
        PluginDescriptor(name='nBox CEC', description='nBox i telewizor przez HDMI-CEC',
                         where=PluginDescriptor.WHERE_PLUGINMENU, fnc=main),
    ]
