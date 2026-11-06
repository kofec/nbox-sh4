# -*- coding: utf-8 -*-
#
# nBox kopia - wtyczka enigmy (GraterliaOS / OpenPLi 4, Python 2.7): kopia
# konfiguracji nBoxa i przenosiny na inny box, jak przy zamianie dwoch
# boxow miedzy domami 2026-11-01 (wtedy recznie).
# Menu -> Ustawienia -> System -> nBox kopia:
#   - Zrob kopie teraz      - nbox_kopia zapisz do wybranego miejsca,
#   - Wgraj kopie           - wybor kopii ze wszystkich dyskow/NFS, czesci
#                             do wgrania, potem restart / wylaczenie boxa,
#   - Co wejdzie do kopii   - nbox_kopia sprawdz,
#   - Ustawienia            - miejsce, kopia automatyczna (dzien/tydzien, godzina,
#                             ile zostawic).
# Cala robote na plikach robi /usr/bin/nbox_kopia (skrypty/nbox_kopia.sh);
# wtyczka to menu i harmonogram. Domyslnie kopia automatyczna wylaczona -
# sama instalacja niczego nie zapisuje.
#
# Wgranie czesci innych niz kanaly i oscam zamyka enigme (settings z kopii
# musza przetrwac jej wyjscie), wiec skrypt idzie odlaczony (--w-tle),
# przebieg w /tmp/nbox_kopia.log. Przed wgraniem skrypt sam robi kopie
# obecnego stanu (<oktet>_<data>_przed_wgraniem obok).
#
# Logika bez enigmy: kopie.py; test: enigma2/test_nboxkopia.py.
# Kazde wywolanie z enigmy (timer, kontener) w try/except - wyjatek z
# callbacku timera krecil petla enigmy na 100% CPU (2026-10-22).

import os
import time
import traceback

from enigma import eTimer, eConsoleAppContainer
from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.ChoiceBox import ChoiceBox
from Screens.Console import Console
from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.MenuList import MenuList
from Components.Sources.StaticText import StaticText
from Components.config import config, ConfigSubsection, ConfigYesNo, \
    ConfigSelection, ConfigText, ConfigInteger, getConfigListEntry, configfile
from Tools import Notifications

from Plugins.SystemPlugins.NBoxKopia import kopie

WERSJA = '1.0'
SKRYPT = '/usr/bin/nbox_kopia'
LOG = '/tmp/nbox_kopia_wtyczka.log'
LOG_TLA = '/tmp/nbox_kopia.log'
LOG_MAX = 64 * 1024
PIERWSZE_SPRAWDZENIE_MS = 5 * 60 * 1000     # po starcie enigmy - niech box sie ustabilizuje
CO_ILE_MS = 10 * 60 * 1000
PONOW_PO_BLEDZIE_S = 6 * 3600
ZEGAR_USTAWIONY = 1500000000                # przed NTP box ma rok 2000

config.plugins.nboxkopia = ConfigSubsection()
ust = config.plugins.nboxkopia
ust.miejsce = ConfigText(default='/hdd', fixed_size=False)
ust.auto = ConfigSelection(default='nie', choices=[
    ('nie', 'nie'), ('dzien', 'codziennie'), ('tydzien', 'co tydzień (w niedzielę)')])
ust.godzina = ConfigSelection(default='4', choices=[(str(h), '%02d:00' % h) for h in range(24)])
ust.zostaw = ConfigSelection(default='7', choices=['3', '5', '7', '14', '30'])
ust.ostatnia = ConfigInteger(default=0, limits=(0, 2147483647))


def log(tekst):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX:
            os.rename(LOG, LOG + '.1')
        with open(LOG, 'a') as f:
            f.write('%s %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), tekst))
    except Exception:
        pass


def miejsca():
    """[(sciezka, wolne_kb, fs)] z nbox_kopia miejsca; ustawione miejsce zawsze na liscie."""
    try:
        p = os.popen('%s miejsca 2>/dev/null' % SKRYPT)
        wynik = kopie.parsuj_miejsca(p.read())
        p.close()
    except Exception:
        log('miejsca: %s' % traceback.format_exc())
        wynik = []
    if ust.miejsce.value not in [m[0] for m in wynik] and os.path.isdir(ust.miejsce.value):
        wynik.insert(0, (ust.miejsce.value, 0, '?'))
    return wynik


def zapisz_settings():
    # settings enigmy na dysk, zeby kopia miala biezace (inaczej stan z ostatniego wyjscia)
    try:
        configfile.save()
    except Exception:
        log('configfile.save: %s' % traceback.format_exc())


class Harmonogram(object):
    """Kopia automatyczna w tle; box wylaczony o tej godzinie - zaraz po starcie."""

    def __init__(self):
        self.kontener = None
        self.wyjscie = []
        self.blad_o = 0
        self.timer = eTimer()
        self.timer.callback.append(self.sprawdz)
        self.timer.start(PIERWSZE_SPRAWDZENIE_MS, True)

    def sprawdz(self):
        try:
            self._sprawdz()
        except Exception:
            log('harmonogram: %s' % traceback.format_exc())
        self.timer.start(CO_ILE_MS, True)

    def _sprawdz(self):
        if ust.auto.value == 'nie' or self.kontener is not None:
            return
        teraz = time.time()
        if teraz < ZEGAR_USTAWIONY or teraz - self.blad_o < PONOW_PO_BLEDZIE_S:
            return
        if not kopie.nalezna(teraz, ust.ostatnia.value, ust.auto.value, int(ust.godzina.value)):
            return
        m = ust.miejsce.value
        if not os.path.isdir(m) or not os.path.exists(SKRYPT):
            self.blad('nie ma %s albo %s' % (m, SKRYPT))
            return
        zapisz_settings()
        cmd = '%s zapisz -d %s -o auto -z %s' % (SKRYPT, kopie.cytuj(m), ust.zostaw.value)
        log('start: %s' % cmd)
        self.wyjscie = []
        self.kontener = eConsoleAppContainer()
        self.kontener.dataAvail.append(self.dane)
        self.kontener.appClosed.append(self.koniec)
        if self.kontener.execute(cmd):
            self.kontener = None
            self.blad('nie uruchomilem %s' % SKRYPT)

    def dane(self, tekst):
        try:
            self.wyjscie.append(tekst)
        except Exception:
            pass

    def koniec(self, rc):
        try:
            self.kontener = None
            wyj = ''.join(self.wyjscie)
            log('koniec rc=%s\n%s' % (rc, wyj))
            if rc == 0:
                ust.ostatnia.value = int(time.time())
                ust.ostatnia.save()
                configfile.save()
            else:
                ostatnie = [l for l in wyj.splitlines() if l.strip()][-3:]
                self.blad('rc=%s %s' % (rc, ' / '.join(ostatnie)))
        except Exception:
            log('koniec: %s' % traceback.format_exc())

    def blad(self, tekst):
        self.blad_o = time.time()
        log('BLAD: %s' % tekst)
        Notifications.AddNotification(
            MessageBox, 'nBox kopia: kopia automatyczna się nie udała\n%s\nLog: %s' % (tekst, LOG),
            type=MessageBox.TYPE_ERROR, timeout=30)


harmonogram = None


def opis_auto():
    if ust.auto.value == 'nie':
        return 'wyłączona'
    o = ust.ostatnia.value
    return '%s o %s:00, zostaje %s; ostatnia: %s' % (
        ust.auto.getText(), ust.godzina.value.zfill(2), ust.zostaw.value,
        o and time.strftime('%Y-%m-%d %H:%M', time.localtime(o)) or 'jeszcze nie było')


class NBoxKopiaMenu(Screen):
    skin = """
    <screen position="center,center" size="900,480" title="nBox kopia">
        <widget name="menu" position="10,10" size="880,240" scrollbarMode="showOnDemand" />
        <widget source="status" render="Label" position="10,270" size="880,200" font="Regular;20" />
    </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self['menu'] = MenuList([
            ('Zrób kopię teraz', self.zrob),
            ('Wgraj kopię (też z innego boxa)', self.wybierz_kopie),
            ('Co wejdzie do kopii', self.sprawdz),
            ('Ustawienia: miejsce, kopia automatyczna', self.ustawienia),
        ])
        self['status'] = StaticText('')
        self['actions'] = ActionMap(['OkCancelActions'], {'ok': self.ok, 'cancel': self.close}, -1)
        self.setTitle('nBox kopia %s' % WERSJA)
        self.onShown.append(self.odswiez)

    def odswiez(self):
        try:
            if not os.path.exists(SKRYPT):
                self['status'].text = 'Brak %s - przeinstaluj pakiet' % SKRYPT
                return
            self['status'].text = 'Miejsce kopii: %s%s\nKopia automatyczna: %s' % (
                ust.miejsce.value, os.path.isdir(ust.miejsce.value) and ' ' or ' (NIE MA TERAZ)',
                opis_auto())
        except Exception:
            log('odswiez: %s' % traceback.format_exc())

    def ok(self):
        c = self['menu'].getCurrent()
        if c:
            c[1]()

    def zrob(self):
        m = ust.miejsce.value
        if not os.path.isdir(m):
            self.session.open(MessageBox, 'Nie ma katalogu %s (dysk, pendrive, NFS?).\nZmień miejsce w ustawieniach.' % m,
                              MessageBox.TYPE_ERROR)
            return
        zapisz_settings()
        self.session.open(Console, title='nBox kopia: zapis do %s' % m,
                          cmdlist=['%s zapisz -d %s' % (SKRYPT, kopie.cytuj(m))])

    def sprawdz(self):
        self.session.open(Console, title='nBox kopia: co wejdzie do kopii',
                          cmdlist=['%s sprawdz' % SKRYPT])

    def ustawienia(self):
        self.session.openWithCallback(lambda *a: self.odswiez(), NBoxKopiaUstawienia)

    def wybierz_kopie(self):
        lista = kopie.kopie([m[0] for m in miejsca()])
        if not lista:
            self.session.open(MessageBox, 'Nie znalazłem kopii (katalog %s/ na dyskach, pendrive, NFS).' % kopie.PODKAT,
                              MessageBox.TYPE_INFO)
            return
        self.session.openWithCallback(self.wybrana, ChoiceBox, title='Którą kopię wgrać?',
                                      list=[(kopie.opis_kopii(k), k) for k in lista])

    def wybrana(self, wybor):
        if wybor:
            self.session.open(NBoxKopiaWgraj, wybor[1])


class NBoxKopiaUstawienia(Screen, ConfigListScreen):
    skin = """
    <screen position="center,center" size="900,400" title="nBox kopia - ustawienia">
        <widget name="config" position="10,10" size="880,250" scrollbarMode="showOnDemand" />
        <widget source="status" render="Label" position="10,270" size="880,80" font="Regular;20" />
        <widget source="key_red" render="Label" position="10,360" size="200,30" font="Regular;20" foregroundColor="#ff4040" />
        <widget source="key_green" render="Label" position="220,360" size="200,30" font="Regular;20" foregroundColor="#40ff40" />
    </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self['key_red'] = StaticText('Anuluj')
        self['key_green'] = StaticText('Zapisz')
        self['status'] = StaticText('Kopia automatyczna idzie w tle; gdy box był wtedy wyłączony - po najbliższym starcie.')
        self['actions'] = ActionMap(['SetupActions', 'ColorActions'], {
            'ok': self.zapisz, 'save': self.zapisz, 'green': self.zapisz,
            'cancel': self.anuluj, 'red': self.anuluj}, -2)
        m = miejsca()
        wybory = [(s, kopie.opis_miejsca((s, w, fs))) for s, w, fs in m]
        if ust.miejsce.value not in [w[0] for w in wybory]:
            wybory.insert(0, (ust.miejsce.value, '%s  (teraz niedostępne)' % ust.miejsce.value))
        self.miejsce = ConfigSelection(default=ust.miejsce.value, choices=wybory)
        ConfigListScreen.__init__(self, self.lista(), session=session)
        self.setTitle('nBox kopia %s - ustawienia' % WERSJA)

    def lista(self):
        e = getConfigListEntry
        l = [e('Miejsce kopii', self.miejsce),
             e('Kopia automatyczna', ust.auto)]
        if ust.auto.value != 'nie':
            l += [e('Kopia automatyczna: godzina', ust.godzina),
                  e('Kopia automatyczna: zostaw ostatnich', ust.zostaw)]
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

    def zapisz(self):
        ust.miejsce.value = self.miejsce.value
        ust.miejsce.save()
        for x in (ust.auto, ust.godzina, ust.zostaw):
            x.save()
        configfile.save()
        self.close()

    def anuluj(self):
        for x in (ust.auto, ust.godzina, ust.zostaw):
            x.cancel()
        self.close()


class NBoxKopiaWgraj(Screen, ConfigListScreen):
    skin = """
    <screen position="center,center" size="900,560" title="nBox kopia - wgraj">
        <widget name="config" position="10,10" size="880,300" scrollbarMode="showOnDemand" />
        <widget source="status" render="Label" position="10,320" size="880,190" font="Regular;20" />
        <widget source="key_red" render="Label" position="10,520" size="200,30" font="Regular;20" foregroundColor="#ff4040" />
        <widget source="key_green" render="Label" position="220,520" size="200,30" font="Regular;20" foregroundColor="#40ff40" />
    </screen>"""

    def __init__(self, session, kopia):
        Screen.__init__(self, session)
        self.kopia = kopia
        self['key_red'] = StaticText('Anuluj')
        self['key_green'] = StaticText('Wgraj')
        self['status'] = StaticText('')
        self['actions'] = ActionMap(['SetupActions', 'ColorActions'], {
            'ok': self.wgraj, 'save': self.wgraj, 'green': self.wgraj,
            'cancel': self.close, 'red': self.close}, -2)
        self.czesci = [(c, ConfigYesNo(default=True)) for c in kopie.CZESCI if c in kopia['czesci']]
        self.po = ConfigSelection(default='restart', choices=[
            ('restart', 'restart boxa'),
            ('wylacz', 'wyłącz boxa (jedzie gdzie indziej)'),
            ('nic', 'bez restartu (tylko kanały i oscam)')])
        ConfigListScreen.__init__(self, self.lista(), session=session)
        self.setTitle('Wgraj kopię z %s' % kopia['data'][:16])
        self.onShown.append(self.odswiez)

    def lista(self):
        e = getConfigListEntry
        return [e(kopie.NAZWY[c], el) for c, el in self.czesci] + [e('Po wgraniu', self.po)]

    def wybrane(self):
        return [c for c, el in self.czesci if el.value]

    def keyLeft(self):
        ConfigListScreen.keyLeft(self)
        self.odswiez()

    def keyRight(self):
        ConfigListScreen.keyRight(self)
        self.odswiez()

    def odswiez(self):
        try:
            k = self.kopia
            t = ['Kopia: box .%s %s (%s), %s' % (k.get('oktet', '?'), k.get('boxtype', '?'),
                                                 k.get('host', ''), k['kat'])]
            if k.get('boxtype') != self.boxtype():
                t.append('UWAGA: ten box to %s - tunery w ustawieniach enigmy mogą nie pasować.' % self.boxtype())
            w = self.wybrane()
            if self.po.value == 'nic' and kopie.wymaga_restartu(w):
                t.append('Bez restartu tylko kanały i oscam - wybierz restart albo wyłączenie.')
            elif self.po.value != 'nic':
                t.append('Enigma się zamknie, pliki zostaną podmienione, potem %s. Przebieg: %s' % (
                    self.po.value == 'restart' and 'restart' or 'wyłączenie', LOG_TLA))
            t.append('Najpierw kopia obecnego stanu (…_przed_wgraniem obok).')
            self['status'].text = '\n'.join(t)
        except Exception:
            log('odswiez wgraj: %s' % traceback.format_exc())

    def boxtype(self):
        try:
            with open('/var/grun/grcstype') as f:
                for l in f:
                    if l.startswith('boxtype='):
                        return l.strip().split('=', 1)[1]
        except Exception:
            pass
        return '?'

    def wgraj(self):
        w = self.wybrane()
        if not w:
            self.session.open(MessageBox, 'Nie wybrano nic do wgrania.', MessageBox.TYPE_ERROR)
            return
        if self.po.value == 'nic' and kopie.wymaga_restartu(w):
            self.session.open(MessageBox, 'Bez restartu można wgrać tylko kanały i oscam.', MessageBox.TYPE_ERROR)
            return
        self.session.openWithCallback(self.potwierdzone, MessageBox, 'Wgrać: %s\nz kopii %s?' % (
            ', '.join(kopie.NAZWY[c] for c in w), self.kopia['kat']), MessageBox.TYPE_YESNO, default=False)

    def potwierdzone(self, tak):
        if not tak:
            return
        w = self.wybrane()
        argumenty = 'wgraj %s %s %s' % (kopie.cytuj(self.kopia['kat']), ','.join(w), self.po.value)
        log('wgraj: %s' % argumenty)
        if self.po.value == 'nic':
            self.session.openWithCallback(self.close, Console, title='nBox kopia: wgrywanie',
                                          cmdlist=['%s %s' % (SKRYPT, argumenty)],
                                          finishedCallback='kanaly' in w and self.przeladuj or None)
            return
        # odlaczone od enigmy: skrypt ja zamyka
        os.system('%s --w-tle %s >/dev/null 2>&1' % (SKRYPT, argumenty))
        self.session.open(MessageBox, 'Wgrywanie ruszyło. Enigma za chwilę się zamknie, potem %s.\nPrzebieg: %s' % (
            self.po.value == 'restart' and 'restart boxa' or 'wyłączenie boxa', LOG_TLA), MessageBox.TYPE_INFO)

    def przeladuj(self):
        try:
            from enigma import eDVBDB
            db = eDVBDB.getInstance()
            db.reloadServicelist()
            db.reloadBouquets()
        except Exception:
            log('przeladuj: %s' % traceback.format_exc())


def autostart(reason, **kwargs):
    global harmonogram
    if reason == 0 and harmonogram is None:
        try:
            harmonogram = Harmonogram()
        except Exception:
            log('autostart: %s' % traceback.format_exc())


def main(session, **kwargs):
    session.open(NBoxKopiaMenu)


def menu(menuid, **kwargs):
    if menuid == 'system':
        return [('nBox kopia', main, 'nbox_kopia', 47)]
    return []


def Plugins(**kwargs):
    return [
        PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=autostart),
        PluginDescriptor(name='nBox kopia', description='kopia konfiguracji i przenosiny na inny box',
                         where=PluginDescriptor.WHERE_MENU, fnc=menu),
        PluginDescriptor(name='nBox kopia', description='kopia konfiguracji i przenosiny na inny box',
                         where=PluginDescriptor.WHERE_PLUGINMENU, fnc=main),
    ]
