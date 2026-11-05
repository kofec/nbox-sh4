# -*- coding: utf-8 -*-
#
# NcplusLista - wtyczka enigmy (GraterliaOS / OpenPLi 4, Python 2.7): raz na kilka
# dni stroi wolny tuner na transponder nc+, czyta z satelity NIT/SDT/BAT i odświeża
# bukiet "CANAL+ (satelita)" (kolejność wg numeracji nc+, zmiany użytkownika
# zachowane) oraz dopisuje do lamedb brakujące transpondery i kanały.
# Logika bez enigmy (Python 2 i 3, da się uruchomić na PC przez offline.py): si.py,
# lamedb.py, budowa.py, scalanie.py, przebieg.py, odczyt.py; tutaj tylko tuner, demux,
# harmonogram, zapis i menu. Log: /tmp/ncpluslista.log.
#
# Domyślnie TRYB PRÓBNY: wtyczka czyta satelitę i pisze raport, ale nie zmienia
# żadnego pliku w /etc/enigma2. Zapis dopiero po wyłączeniu trybu próbnego w menu
# (Ustawienia -> System -> Lista kanałów z satelity).
#
# Każde wywołanie z enigmy (timery, ekrany) jest w try/except: wyjątek z callbacku
# timera kręcił pętlą enigmy na 100% CPU (nBox, 2026-10-22, NBoxCEC).

import json
import os
import tarfile
import threading
import time
import traceback

from enigma import eTimer, eDVBResourceManager, eDVBFrontendParameters, \
    eDVBFrontendParametersSatellite, eDVBDB
from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.ScrollLabel import ScrollLabel
from Components.Sources.StaticText import StaticText
from Components.config import config, ConfigSubsection, ConfigYesNo, \
    ConfigSelection, ConfigText, getConfigListEntry, configfile
from Tools import Notifications

from Plugins.SystemPlugins.NcplusLista import si as si_mod
from Plugins.SystemPlugins.NcplusLista import budowa, przebieg, odczyt

WERSJA = '0.1.4'
ETC = '/etc/enigma2'
TMP = '/tmp'
LOG = '/tmp/ncpluslista.log'
LOG_MAX_B = 64 * 1024
KOPIE_GDZIE = ('/hdd', '/media/hdd', '/media/usb')   # pierwszy zamontowany, potem /media/net/*
KOPIE_KATALOG = 'ncpluslista'
KOPIE_ILE = 4
# Gdy nie ma dysku ani udziału: NAND (rootfs). Mniej kopii, bez zrzutu SI i tylko,
# gdy zostanie zapas - rootfs nBoxów bywa zajęty w 85-96%.
KOPIE_NAND = '/root/ncpluslista'
KOPIE_ILE_NAND = 2
NAND_ZAPAS_B = 2 * 1024 * 1024
SPRAWDZ_CO_MS = 60 * 60 * 1000
PIERWSZE_SPRAWDZENIE_MS = 10 * 60 * 1000          # po starcie: zegar, oscam, dysk
KROK_MS = 200
LOCK_LIMIT_S = 15
NAGRANIE_ZAPAS_S = 15 * 60
CZYTANE = ('lamedb', 'lamedb5', 'bouquets.tv', 'bouquets.radio', przebieg.PLIK_STANU)

# Transpondery nc+ z pełnym SI (NIT/SDT other/BAT), pomiar 2026-11-05 na 10719 V.
# Parametry w enumach enigmy; po każdym odczycie nadpisywane tymi z NIT.
TP_START = [
    {'nazwa': '10719 V', 'onid': 0x13E, 'tsid': 0x2AF8, 'czestotliwosc': 10719000, 'sr': 27500000,
     'polaryzacja': 1, 'fec': 4, 'poz': 130, 'system': 1, 'modulacja': 2, 'rolloff': 2},
    {'nazwa': '11278 V', 'onid': 0x13E, 'tsid': 0x0190, 'czestotliwosc': 11278000, 'sr': 27500000,
     'polaryzacja': 1, 'fec': 4, 'poz': 130, 'system': 1, 'modulacja': 2, 'rolloff': 2},
    {'nazwa': '11411 H', 'onid': 0x13E, 'tsid': 0x044C, 'czestotliwosc': 11411000, 'sr': 27500000,
     'polaryzacja': 0, 'fec': 4, 'poz': 130, 'system': 1, 'modulacja': 2, 'rolloff': 2},
]

config.plugins.ncpluslista = ConfigSubsection()
ust = config.plugins.ncpluslista
ust.enable = ConfigYesNo(default=True)
ust.probny = ConfigYesNo(default=True)
ust.co_dni = ConfigSelection(default='7', choices=[
    ('1', '1 dzień'), ('3', '3 dni'), ('7', '7 dni'), ('14', '14 dni'), ('30', '30 dni')])
ust.bat = ConfigSelection(default='%X' % budowa.BAT_DOMYSLNY,
                          choices=[('%X' % b, opis if isinstance(opis, str) else opis.encode('utf-8'))
                                   for b, opis in budowa.BAT_MENU] +
                          [('auto', 'automatycznie')])
ust.zastepczy = ConfigYesNo(default=True)
ust.powtorki = ConfigYesNo(default=True)
ust.radio = ConfigYesNo(default=True)
ust.radio_osobno = ConfigYesNo(default=False)
ust.bloki = ConfigYesNo(default=True)
ust.bez_4k = ConfigYesNo(default=False)
ust.miejsce = ConfigSelection(default='pierwszy', choices=[
    ('pierwszy', 'na górze (potem tam, gdzie go przestawisz)'),
    ('ostatni', 'na końcu'),
    ('zawsze_pierwszy', 'zawsze na górze')])
ust.popraw_inne = ConfigYesNo(default=False)
ust.bukiet = ConfigYesNo(default=True)
ust.ostatnio = ConfigText(default='0')            # time() ostatniego udanego przebiegu
ust.ostatni_wynik = ConfigText(default='')
ust.tp_nit = ConfigText(default='')               # JSON: parametry TP startowych z NIT


def opcje_z_ustawien():
    return budowa.Opcje(
        bat='auto' if ust.bat.value == 'auto' else int(ust.bat.value, 16),
        zastepczy=ust.zastepczy.value, bez_4k=ust.bez_4k.value, powtorki=ust.powtorki.value,
        radio=ust.radio.value, radio_osobno=ust.radio_osobno.value, bloki=ust.bloki.value,
        miejsce=ust.miejsce.value, popraw_inne=ust.popraw_inne.value, bukiet=ust.bukiet.value)


try:
    _TEKST = unicode    # noqa: F821  (Python 2: literały w tym pliku to bajty UTF-8)
except NameError:
    _TEKST = str        # Python 3 (testy na PC)


def u8(s):
    """Tekst -> bajty UTF-8 (na boxie GUI i pliki chcą bajtów)."""
    return s.encode('utf-8') if isinstance(s, _TEKST) else s


def nat(s):
    """Napis natywny do łączenia z literałami tego pliku: Python 2 - bajty UTF-8,
    Python 3 - str."""
    if _TEKST is str:
        return s.decode('utf-8') if isinstance(s, bytes) else s
    return u8(s)


def bezpiecznie(f):
    """Wywołanie z enigmy: wyjątek tylko do logu, nigdy do pętli enigmy."""
    def opak(self, *a):
        try:
            return f(self, *a)
        except Exception:
            self.log('błąd (%s): %s' % (f.__name__, traceback.format_exc().replace('\n', ' | ')))
            try:
                self.przerwij('błąd w %s' % f.__name__)
            except Exception:
                pass
    opak.__name__ = f.__name__
    return opak


def miejsca_kopii():
    """Dyski lokalne, potem udziały sieciowe zamontowane w /media/net (NFS, CIFS)."""
    siec = []
    try:
        siec = sorted(os.path.join('/media/net', n) for n in os.listdir('/media/net'))
    except OSError:
        pass
    return list(KOPIE_GDZIE) + siec


def wolne_b(sciezka):
    try:
        s = os.statvfs(sciezka)
    except (AttributeError, OSError):
        return None                                 # nie wiadomo (np. Windows w testach)
    return s.f_bavail * s.f_frsize


def na_nand(katalog):
    return katalog is not None and katalog.rstrip('/') == KOPIE_NAND.rstrip('/')


def katalog_kopii():
    for k in miejsca_kopii():
        if os.path.ismount(k):
            d = os.path.join(k, KOPIE_KATALOG)
            try:
                if not os.path.isdir(d):
                    os.makedirs(d)
                return d
            except OSError:
                continue
    wolne = wolne_b(os.path.dirname(KOPIE_NAND.rstrip('/')) or '/')
    if wolne is not None and wolne < NAND_ZAPAS_B:
        return None
    try:
        if not os.path.isdir(KOPIE_NAND):
            os.makedirs(KOPIE_NAND)
        return KOPIE_NAND
    except OSError:
        return None


class Sterownik(object):
    def __init__(self, session):
        self.session = session
        self.etap = 'czeka'
        self.opis = ''
        self.raw = None
        self.frontend = None
        self.czytnik = None
        self.watek = None
        self.wynik = None
        self.recznie = False
        self.tp_kolejka = []
        self.tp = None
        self.lock_od = 0
        self.timer = eTimer()
        self.timer.callback.append(self.sprawdz)
        self.krok_timer = eTimer()
        self.krok_timer.callback.append(self.krok)
        self.log('start %s (próbny=%s, co %s dni, BAT %s)' % (
            WERSJA, ust.probny.value, ust.co_dni.value, ust.bat.value))
        self.timer.start(PIERWSZE_SPRAWDZENIE_MS, True)

    # --- harmonogram ---

    @bezpiecznie
    def sprawdz(self):
        self.timer.start(SPRAWDZ_CO_MS, True)
        if not ust.enable.value or self.etap != 'czeka':
            return
        try:
            ostatnio = float(ust.ostatnio.value or 0)
        except ValueError:
            ostatnio = 0
        if time.time() - ostatnio < int(ust.co_dni.value) * 86400:
            return
        if time.localtime().tm_year < 2020:
            return                                     # zegar jeszcze nie ustawiony
        self.uruchom(recznie=False)

    def nagranie_blisko(self):
        try:
            nast = self.session.nav.RecordTimer.getNextRecordingTime()
        except Exception:
            return False
        return nast is not None and nast > 0 and nast - time.time() < NAGRANIE_ZAPAS_S

    def uruchom(self, recznie=True):
        """Start przebiegu (z menu albo harmonogramu). -> komunikat dla użytkownika."""
        if self.etap != 'czeka':
            return 'Już trwa: %s' % self.etap
        if self.nagranie_blisko():
            self.log('pominięte: nagranie w ciągu 15 min')
            return 'Za chwilę nagranie - spróbuję później.'
        self.recznie = recznie
        self.tp_kolejka = self.transpondery()
        self.log('przebieg (%s)' % (recznie and 'ręcznie' or 'harmonogram'))
        self.nastepny_tp()
        return 'Start: strojenie tunera.'

    # --- strojenie ---

    def transpondery(self):
        tp = [dict(t) for t in TP_START]
        try:
            z_nit = json.loads(ust.tp_nit.value or '{}')
        except ValueError:
            z_nit = {}
        for t in tp:
            t.update(z_nit.get('%X' % t['tsid'], {}))
        return tp

    def sloty(self):
        """Tunery DVB-S z pozycją 13.0E w konfiguracji; od ostatniego (zwykle wolny B)."""
        from Components.NimManager import nimmanager
        wynik = []
        for slot in nimmanager.getNimListOfType('DVB-S'):
            try:
                pozycje = [s[0] for s in nimmanager.getSatListForNim(slot)]
            except Exception:
                pozycje = []
            if 130 in pozycje:
                wynik.append(slot)
        return list(reversed(wynik))

    def przydziel(self):
        rm = eDVBResourceManager.getInstance()
        if not rm:
            return None
        for slot in self.sloty():
            raw = rm.allocateRawChannel(slot)
            if raw:
                fe = raw.getFrontend()
                if fe:
                    self.log('tuner %d przydzielony' % slot)
                    return raw, fe, slot
                raw = None
        return None

    @bezpiecznie
    def nastepny_tp(self):
        self.zwolnij()
        if not self.tp_kolejka:
            self.przerwij('żaden transponder nc+ nie dał BAT')
            return
        self.tp = self.tp_kolejka.pop(0)
        p = self.przydziel()
        if p is None:
            self.przerwij('brak wolnego tunera z 13.0E')
            return
        self.raw, self.frontend, slot = p
        t = self.tp
        parm = eDVBFrontendParametersSatellite()
        parm.frequency = t['czestotliwosc']
        parm.symbol_rate = t['sr']
        parm.polarisation = t['polaryzacja']
        parm.fec = t['fec']
        parm.inversion = 2                          # Inversion_Unknown
        parm.orbital_position = t['poz']
        parm.system = t['system']
        parm.modulation = t['modulacja']
        parm.rolloff = t['rolloff']
        parm.pilot = 2                              # Pilot_Unknown
        fep = eDVBFrontendParameters()
        fep.setDVBS(parm, False)
        self.frontend.tune(fep)
        self.etap, self.opis = 'strojenie', '%s, tuner %d' % (t['nazwa'], slot)
        self.lock_od = time.time()
        self.log('strojenie %s' % self.opis)
        self.krok_timer.start(500, True)

    # --- pętla kroków (strojenie -> odczyt -> przetwarzanie) ---

    @bezpiecznie
    def krok(self):
        if self.etap == 'strojenie':
            st = {}
            self.frontend.getFrontendStatus(st)
            stan = st.get('tuner_state')
            if stan == 'LOCKED':
                demux = self.raw.reserveDemux()
                if demux is None or demux < 0:
                    self.log('reserveDemux: %r' % (demux,))
                    self.nastepny_tp()
                    return
                self.czytnik = odczyt.Czytnik('/dev/dvb/adapter0/demux%d' % demux)
                self.etap = 'odczyt'
                self.log('lock %s po %.1f s, demux %d' % (self.tp['nazwa'], time.time() - self.lock_od, demux))
            elif time.time() - self.lock_od > LOCK_LIMIT_S:
                self.log('brak locka na %s (%s)' % (self.tp['nazwa'], stan))
                self.nastepny_tp()
                return
            self.krok_timer.start(KROK_MS if self.etap == 'odczyt' else 500, True)
        elif self.etap == 'odczyt':
            if not self.czytnik.krok():
                self.krok_timer.start(KROK_MS, True)
                return
            c = self.czytnik
            self.log('odczyt %s: %d sekcji w %.0f s, BAT %s, brakujące %s' % (
                self.tp['nazwa'], len(c.sekcje), c.zegar() - c.start, c.ma_bat(), c.brakujace()[:5]))
            if not c.ma_bat():
                self.nastepny_tp()
                return
            sekcje = c.wynik()
            self.czytnik = None
            self.zwolnij()                              # tuner wolny przed przetwarzaniem
            self.etap = 'przetwarzanie'
            self.wynik = None
            self.watek = threading.Thread(target=self.przetworz, args=(sekcje, opcje_z_ustawien()))
            self.watek.daemon = True
            self.watek.start()
            self.krok_timer.start(500, True)
        elif self.etap == 'przetwarzanie':
            if self.watek.is_alive():
                self.krok_timer.start(500, True)
                return
            self.watek = None
            self.zakoncz(self.wynik)

    def przetworz(self, sekcje, opcje):
        """W osobnym wątku: tylko czysty Python, bez wywołań enigmy."""
        try:
            t0 = time.time()
            si = si_mod.z_sekcji(sekcje)
            pliki = self.wczytaj_etc()
            do_zapisu, raport = przebieg.aktualizuj(si, pliki, opcje)
            tp = {}
            for t in TP_START:
                n = si.nit.get((t['onid'], t['tsid']))
                if n:
                    tp['%X' % t['tsid']] = n
            self.wynik = {'pliki': pliki, 'do_zapisu': do_zapisu, 'raport': raport, 'tp': tp,
                          'sekcje': sekcje, 'czas': time.time() - t0}
        except Exception:
            self.wynik = {'blad': traceback.format_exc()}

    def wczytaj_etc(self):
        pliki = {}
        for n in os.listdir(ETC):
            if n in CZYTANE or (n.startswith('userbouquet.') and (n.endswith('.tv') or n.endswith('.radio'))):
                f = open(os.path.join(ETC, n), 'rb')
                try:
                    pliki[n] = f.read()
                finally:
                    f.close()
        return pliki

    # --- zakończenie ---

    def zakoncz(self, w):
        self.etap = 'zapis'
        if not w or 'blad' in w:
            self.przerwij('przetwarzanie: %s' % (w and w['blad'].replace('\n', ' | ') or 'brak wyniku'))
            return
        raport = u8(w['raport'])
        kopie = katalog_kopii()
        self.zapisz_raport(raport, kopie, w['sekcje'])
        if w['tp']:
            ust.tp_nit.value = json.dumps(w['tp'])
            ust.tp_nit.save()
        # nazwy z rdzenia to unicode (Python 2); z bajtowym 'próbny...' dawały
        # UnicodeDecodeError (nBox, 0.1.0, 2026-11-05)
        zmiany = sorted(nat(n) for n in w['do_zapisu'])
        if ust.probny.value:
            wynik = 'próbny: zmieniłby %s' % (', '.join(zmiany) or 'nic')
        elif not zmiany:
            wynik = 'bez zmian'
        elif kopie is None:
            self.przerwij('brak miejsca na kopię (%s, /media/net/*, %s) - nic nie zapisano' % (' / '.join(KOPIE_GDZIE), KOPIE_NAND))
            return
        elif self.wczytaj_etc_zmienione(w['pliki']):
            self.przerwij('pliki w %s zmieniły się w trakcie - spróbuję za godzinę' % ETC)
            return
        else:
            self.kopia(kopie)
            self.zapisz_pliki(w['do_zapisu'])
            wynik = 'zapisano %s' % ', '.join(zmiany)
        ust.ostatnio.value = str(int(time.time()))
        ust.ostatnio.save()
        ust.ostatni_wynik.value = '%s: %s' % (time.strftime('%Y-%m-%d %H:%M'), wynik)
        ust.ostatni_wynik.save()
        configfile.save()
        self.log('%s (przetwarzanie %.1f s)' % (wynik, w['czas']))
        self.log(raport)
        if zmiany or self.recznie:
            self.komunikat('Lista kanałów z satelity: %s.\nRaport: %s' % (
                wynik, os.path.join(kopie or TMP, 'raport_ostatni.txt')))
        self.etap, self.opis = 'czeka', ''

    def wczytaj_etc_zmienione(self, przed):
        teraz = self.wczytaj_etc()
        return any(teraz.get(n) != b for n, b in przed.items())

    def kopia(self, kat):
        nazwa = os.path.join(kat, 'etc_enigma2_%s.tgz' % time.strftime('%Y%m%d_%H%M%S'))
        t = tarfile.open(nazwa, 'w:gz')
        try:
            for n in sorted(os.listdir(ETC)):
                if n in CZYTANE or n.startswith('userbouquet.'):
                    t.add(os.path.join(ETC, n), arcname=n)
        finally:
            t.close()
        stare = sorted(x for x in os.listdir(kat) if x.startswith('etc_enigma2_') and x.endswith('.tgz'))
        for x in stare[:-(KOPIE_ILE_NAND if na_nand(kat) else KOPIE_ILE)]:
            os.remove(os.path.join(kat, x))
        self.log('kopia %s' % nazwa)

    def zapisz_pliki(self, do_zapisu):
        """Najpierw wszystkie pliki tymczasowe (brak miejsca = nic nie podmienione),
        potem podmiany przez rename."""
        tmp = []
        try:
            for n, b in sorted(do_zapisu.items()):
                t = os.path.join(ETC, n + '.ncpl_tmp')
                tmp.append((t, os.path.join(ETC, n)))
                f = open(t, 'wb')
                try:
                    f.write(b)
                finally:
                    f.close()
        except (IOError, OSError):
            for t, _ in tmp:
                try:
                    os.remove(t)
                except OSError:
                    pass
            raise
        for t, cel in tmp:
            if os.name == 'nt' and os.path.exists(cel):
                os.remove(cel)                      # tylko testy na Windows; na boxie rename nadpisuje
            os.rename(t, cel)
        db = eDVBDB.getInstance()
        if 'lamedb' in do_zapisu:
            db.reloadServicelist()
        if any(n.startswith('userbouquet.') or n.startswith('bouquets.') for n in do_zapisu):
            db.reloadBouquets()

    def zapisz_raport(self, raport, kopie, sekcje):
        naglowek = u8('%s NcplusLista %s, TP %s, próbny=%s\n' % (
            time.strftime('%Y-%m-%d %H:%M:%S'), WERSJA, self.tp and self.tp['nazwa'], ust.probny.value))
        for kat in (TMP,) + ((kopie,) if kopie else ()):
            try:
                f = open(os.path.join(kat, 'raport_ostatni.txt'), 'wb')
                try:
                    f.write(naglowek + raport)
                finally:
                    f.close()
            except (IOError, OSError) as e:
                self.log('raport w %s: %r' % (kat, e))
        if kopie and not na_nand(kopie):            # zrzut SI ~120 KB - nie na NAND
            try:
                import binascii
                f = open(os.path.join(kopie, 'si_ostatni.json'), 'wb')
                try:
                    f.write(u8(json.dumps({
                        'czas': time.strftime('%Y-%m-%d %H:%M:%S'),
                        'sekcje': [binascii.hexlify(s).decode('ascii') for s in sekcje]})))
                finally:
                    f.close()
            except (IOError, OSError) as e:
                self.log('zrzut SI: %r' % (e,))

    def przerwij(self, powod):
        self.krok_timer.stop()
        if self.czytnik is not None:
            self.czytnik.zamknij()
            self.czytnik = None
        self.zwolnij()
        ust.ostatni_wynik.value = '%s: BŁĄD %s' % (time.strftime('%Y-%m-%d %H:%M'), powod)
        ust.ostatni_wynik.save()
        self.log('przerwane: %s' % powod)
        self.komunikat('Lista kanałów z satelity: %s' % powod, blad=True)
        self.etap, self.opis = 'czeka', ''

    def zwolnij(self):
        self.frontend = None
        self.raw = None                                 # eUsePtr zwalnia tuner

    def komunikat(self, tekst, blad=False):
        try:
            Notifications.AddNotification(MessageBox, tekst,
                                          type=blad and MessageBox.TYPE_ERROR or MessageBox.TYPE_INFO,
                                          timeout=10)
        except Exception:
            self.log('komunikat: %s' % traceback.format_exc().replace('\n', ' | '))

    # --- log i stan ---

    def log(self, tekst):
        try:
            f = open(LOG, 'ab')
            try:
                znacznik = u8(time.strftime('%Y-%m-%d %H:%M:%S '))
                for i, l in enumerate(u8(tekst).split(b'\n')):
                    if l or i == 0:
                        f.write(znacznik + l + b'\n')
            finally:
                f.close()
            if os.path.getsize(LOG) > LOG_MAX_B:
                f = open(LOG, 'rb')
                try:
                    f.seek(-(LOG_MAX_B // 2), 2)
                    f.readline()
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
        if self.etap != 'czeka':
            return 'Trwa: %s %s' % (self.etap, self.opis)
        s = ust.ostatni_wynik.value or 'jeszcze nie uruchamiana'
        return 'Ostatnio: %s' % s


sterownik = None


class NcplusRaport(Screen):
    skin = """
    <screen position="center,center" size="1000,600" title="Raport">
        <widget name="tekst" position="10,10" size="980,580" font="Regular;18" />
    </screen>"""

    def __init__(self, session, tekst):
        Screen.__init__(self, session)
        self['tekst'] = ScrollLabel(tekst)
        self['actions'] = ActionMap(['OkCancelActions', 'DirectionActions'], {
            'ok': self.close, 'cancel': self.close,
            'up': self['tekst'].pageUp, 'down': self['tekst'].pageDown,
            'left': self['tekst'].pageUp, 'right': self['tekst'].pageDown}, -1)
        self.setTitle('Lista kanałów z satelity - ostatni raport')


class NcplusListaSetup(Screen, ConfigListScreen):
    skin = """
    <screen position="center,center" size="980,600" title="Lista kanałów z satelity">
        <widget name="config" position="10,10" size="960,460" scrollbarMode="showOnDemand" />
        <widget source="status" render="Label" position="10,480" size="960,70" font="Regular;20" />
        <widget source="key_red" render="Label" position="10,560" size="230,30" font="Regular;20" foregroundColor="#ff4040" />
        <widget source="key_green" render="Label" position="250,560" size="230,30" font="Regular;20" foregroundColor="#40ff40" />
        <widget source="key_yellow" render="Label" position="490,560" size="230,30" font="Regular;20" foregroundColor="#ffff40" />
        <widget source="key_blue" render="Label" position="730,560" size="230,30" font="Regular;20" foregroundColor="#4080ff" />
    </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self['key_red'] = StaticText('Anuluj')
        self['key_green'] = StaticText('Zapisz')
        self['key_yellow'] = StaticText('Uruchom teraz')
        self['key_blue'] = StaticText('Raport')
        self['status'] = StaticText('')
        self['actions'] = ActionMap(['SetupActions', 'ColorActions'], {
            'ok': self.zapisz, 'save': self.zapisz, 'green': self.zapisz,
            'cancel': self.anuluj, 'red': self.anuluj,
            'yellow': self.teraz, 'blue': self.raport}, -2)
        ConfigListScreen.__init__(self, self.lista(), session=session)
        self.setTitle('Lista kanałów z satelity %s' % WERSJA)
        self.status_timer = eTimer()
        self.status_timer.callback.append(self.odswiez_status)
        self.status_timer.start(1000)
        self.onClose.append(self.status_timer.stop)
        self.odswiez_status()

    def lista(self):
        e = getConfigListEntry
        l = [e('Włączona', ust.enable)]
        if not ust.enable.value:
            return l
        l += [e('Tryb próbny (tylko raport, bez zmian w plikach)', ust.probny),
              e('Aktualizuj co', ust.co_dni),
              e('Lista operatora (BAT)', ust.bat)]
        if ust.bat.value != 'auto':
            l.append(e('Gdy jej nie ma - użyj zastępczej', ust.zastepczy))
        l.append(e('Twórz bukiet %s' % nat(budowa.NAZWA), ust.bukiet))
        if ust.bukiet.value:
            l += [e('Kanał pod kilkoma numerami - wszystkie numery', ust.powtorki),
                  e('Radio', ust.radio)]
            if ust.radio.value:
                l.append(e('Radio w osobnym bukiecie', ust.radio_osobno))
            l += [e('Znaczniki bloków tematycznych', ust.bloki),
                  e('Pomiń kanały 4K', ust.bez_4k),
                  e('Bukiet na liście bukietów', ust.miejsce)]
        l.append(e('Aktualizuj parametry kanałów w pozostałych bukietach', ust.popraw_inne))
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
            self['status'].text = sterownik and sterownik.status() or 'Wtyczka nie wystartowała - patrz %s.' % LOG
        except Exception:
            pass

    def teraz(self):
        if sterownik:
            self['status'].text = sterownik.uruchom(recznie=True)

    def raport(self):
        tekst = None
        for kat in (TMP, katalog_kopii()):
            if kat:
                try:
                    f = open(os.path.join(kat, 'raport_ostatni.txt'), 'rb')
                    try:
                        tekst = f.read()
                    finally:
                        f.close()
                    break
                except (IOError, OSError):
                    pass
        self.session.open(NcplusRaport, tekst or 'Brak raportu - wtyczka jeszcze nie działała.')

    def zapisz(self):
        for x in self['config'].list:
            x[1].save()
        configfile.save()
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
    session.open(NcplusListaSetup)


def menu(menuid, **kwargs):
    if menuid == 'system':
        return [('Lista kanałów z satelity', main, 'ncpluslista', 47)]
    return []


def Plugins(**kwargs):
    return [
        PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=autostart),
        PluginDescriptor(name='Lista kanałów z satelity', description='bukiet CANAL+ (satelita) z BAT nc+',
                         where=PluginDescriptor.WHERE_MENU, fnc=menu),
        PluginDescriptor(name='Lista kanałów z satelity', description='bukiet CANAL+ (satelita) z BAT nc+',
                         where=PluginDescriptor.WHERE_PLUGINMENU, fnc=main),
    ]
