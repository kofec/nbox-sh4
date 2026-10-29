# -*- coding: utf-8 -*-
#
# cec_core.py - logika wtyczki nBox CEC bez zaleznosci od enigmy (Python 2.7
# na boxie, testy na PC pod Pythonem 3: enigma2/test_cec_core.py).
#
# Wejscie: ramki z /proc/cec_rx (modul sh4/cec_rx), linie
#   <nr> <epoch.ms> <nad>><odb> <bajt><+|->... [?] [!blad]
# np. "4379 1792601166.049 0>F 0f- 36-"; "?" = bez EOM, "!n" = blad dekodera.
#
# Trzy warstwy:
#   ProcReader - nowe ramki z kolejnych odczytow /proc/cec_rx,
#   TvTracker  - stan TV (y / n / None) i wejscie, ktore TV pokazuje
#                ("nbox" / "inne" / None) z ramek wg profilu TV,
#   Policy     - co z tym zrobic wg ustawien: obudzic / uspic box, wlaczyc /
#                wylaczyc TV. Dziala na zmianach, zeby nie walczyc z pilotem,
#                i nie reaguje na wlasne akcje (box uspiony przez wtyczke nie
#                wylacza TV).
# Do tego Pilot - klawisze pilota TV z modulu nbox_cec (/proc/nbox_cec_klawisze)
# jako klawisze enigmy.
#
# Zachowanie TV z podsluchu 2026-10-21/22 (README.md, tabela "Zachowanie TV
# kazdego TV"): Standby 0>F 36 przy wylaczeniu (LG, Sony), Report Physical
# Address / Routing Change / Active Source od TV przy wlaczeniu; w standby LG
# starszy i Sony milkna, LG webOS dalej co 10 s nadaje Vendor ID (0>F 87), ale
# odpytuje adresy (0>1..0>B bez danych) tylko wlaczony. Wejscie: Routing Change
# 0x80 / Set Stream Path 0x86 / Active Source 0x82 (0.0.0.0 = sam TV - tuner,
# aplikacje Smart TV).

OP_ACTIVE_SOURCE = 0x82
OP_ROUTING_CHANGE = 0x80
OP_ROUTING_INFO = 0x81
OP_SET_STREAM_PATH = 0x86
OP_REPORT_PA = 0x84
OP_STANDBY = 0x36
OP_IMAGE_VIEW_ON = 0x04

TV = 0x0
NBOX = 0x3          # adres logiczny, z ktorego nadaje cec_ctrl (Tuner 1)
BROADCAST = 0xF

# profile "TV dziala": ramki, ktore TV nadaje tylko wlaczony
PROFIL_CISZA = 'cisza'              # cokolwiek od TV; w standby milczy
PROFIL_ODPYTYWANIE = 'odpytywanie'  # TV odpytuje adresy (LG webOS)
PROFIL_ZDARZENIA = 'zdarzenia'      # tylko wlaczenie / Standby

ECHO_TRASY_S = 3.0

# profil odpytywanie: "TV dziala" dopiero przy serii - LG wlaczony odpytuje
# 0>1..0>B w ~0,5 s co ~15 s, a w standby potrafi odpytac jeden adres (0>7 po
# restarcie enigmy, LG webOS, 2026-10-22 12:56:32 - falszywe "tv y")
SERIA_N = 3         # tyle roznych adresow
SERIA_S = 3.0       # w tylu sekundach


class Frame(object):
    __slots__ = ('nr', 't', 'src', 'dst', 'data', 'ack', 'complete', 'err')

    def __init__(self, nr, t, src, dst, data, ack, complete, err):
        self.nr = nr
        self.t = t
        self.src = src
        self.dst = dst
        self.data = data            # bajty po naglowku; data[0] = opcode
        self.ack = ack              # bit ACK naglowka i kolejnych bajtow
        self.complete = complete    # z EOM i bez bledu
        self.err = err

    def opcode(self):
        if self.data:
            return self.data[0]
        return None

    def __repr__(self):
        return '%X>%X %s%s' % (self.src, self.dst,
                               ' '.join('%02x' % b for b in self.data),
                               '' if self.complete else ' ?')


def parse_line(line):
    """Ramka z linii /proc/cec_rx albo None (komentarz, smiec, brak naglowka)."""
    p = line.split()
    if len(p) < 4 or p[0].startswith('#'):
        return None
    try:
        nr = int(p[0])
        t = float(p[1])
    except ValueError:
        return None
    adr = p[2]
    if len(adr) != 3 or adr[1] != '>':
        return None             # "-" = ramka bez ani jednego bajtu
    try:
        src = int(adr[0], 16)
        dst = int(adr[2], 16)
    except ValueError:
        return None
    bajty = []
    ack = []
    eom = True
    err = None
    for tok in p[3:]:
        if tok == '?':
            eom = False
        elif tok.startswith('!'):
            err = tok[1:]
        elif len(tok) == 3 and tok[2] in '+-':
            try:
                bajty.append(int(tok[:2], 16))
            except ValueError:
                return None
            ack.append(tok[2] == '+')
        else:
            return None
    if not bajty:
        return None
    return Frame(nr, t, src, dst, bajty[1:], ack, eom and err is None, err)


def pa_str(hi, lo):
    return '%d.%d.%d.%d' % (hi >> 4, hi & 0xf, lo >> 4, lo & 0xf)


def pa_parse(s):
    """'1.0.0.0' -> (1, 0, 0, 0) albo None."""
    try:
        t = tuple(int(x, 16) for x in s.strip().split('.'))
    except (ValueError, AttributeError):
        return None
    if len(t) != 4 or [x for x in t if x < 0 or x > 15]:
        return None
    return t


def pa_bytes(pa):
    """(1, 0, 0, 0) -> '1000' (do ramki Active Source)."""
    return '%X%X%X%X' % pa


def pa_covers(path, own):
    """Czy TV przelaczony na `path` pokazuje urzadzenie `own` (path rowne
    albo nad own, np. 1.0.0.0 nad 1.1.0.0). 0.0.0.0 = sam TV - nie."""
    if path is None or own is None or path == (0, 0, 0, 0):
        return False
    for a, b in zip(path, own):
        if a == 0:
            return True
        if a != b:
            return False
    return True


class ProcReader(object):
    """Z kolejnych odczytow bufora (256 ostatnich ramek) zwraca tylko nowe.
    Nowa = pozniejsza (czas, nr) niz ostatnia oddana - dziala tez po
    przeladowaniu modulu, kiedy nr liczy sie od 1."""

    def __init__(self):
        self.ost = (0.0, 0)

    def new_frames(self, lines):
        # od konca do pierwszej znanej: parse_line na STi7100 to ~2 ms, a 256
        # linii co krok dawalo 0,55 s na krok (enigma ~30% CPU, 2026-10-22)
        out = []
        for line in reversed(lines):
            p = line.split(None, 2)
            if len(p) < 3 or p[0].startswith('#'):
                continue
            try:
                k = (float(p[1]), int(p[0]))
            except ValueError:
                continue
            if k <= self.ost:
                break
            f = parse_line(line)
            if f is not None:
                out.append(f)
        out.sort(key=lambda f: (f.t, f.nr))
        if out:
            self.ost = (out[-1].t, out[-1].nr)
        return out


def swieze(frames, teraz, max_s):
    """Ramki nie starsze niz max_s - pierwszy odczyt bufora po starcie. Tracker
    liczy cisze od poczatku obserwacji, wiec ramki sprzed godzin dawaly "tv y"
    i wejscie (Sony BRAVIA 8, 2026-10-23 06:15, ostatnie ramki z 22.10 23:56)."""
    return [f for f in frames if teraz - f.t <= max_s]


def tylko_koncowe(zd):
    """Z historii (pierwszy odczyt bufora po starcie) tylko koncowy stan TV i
    wejscia - bez przejsc, ktore juz minely (w logu y, n, y w jednej sekundzie)."""
    tv = [z for z in zd if z[0] == 'tv'][-1:]
    we = [z for z in zd if z[0] == 'wejscie'][-1:]
    if we and tv and tv[0][1] == 'n':
        we = []
    return tv + we


class TvTracker(object):
    """Stan TV i wejscia z ramek. feed() i tick() zwracaja liste zdarzen:
    ('tv', 'y'|'n') przy zmianie stanu, ('wejscie', 'nbox'|'inne', '1.0.0.0')
    przy zmianie wejscia."""

    def __init__(self, profil=PROFIL_CISZA, cisza_s=60, po_wyl_s=90, own_pa=None, t0=0.0):
        self.profil = profil
        self.cisza_s = cisza_s
        self.po_wyl_s = po_wyl_s    # po Standby TV jeszcze gada (Sony ~65 s)
        self.own_pa = own_pa
        self.t0 = t0                # poczatek obserwacji
        self.t_wl = 0.0
        self.t_wyl = 0.0
        self.t_zyje = 0.0
        self.stan = None
        self.wejscie = None
        self.sciezka = None
        self.t_trasa = 0.0
        self.odpytania = []         # (czas, adres) z ostatnich SERIA_S s

    def _zyje(self, f):
        if f.src != TV or self.t_wyl > 0 and f.t <= self.t_wyl + self.po_wyl_s:
            return False
        if self.profil == PROFIL_CISZA:
            return True
        if self.profil == PROFIL_ODPYTYWANIE:
            if f.data or not 0 < f.dst < BROADCAST:
                return False
            self.odpytania = [(t, d) for t, d in self.odpytania
                              if f.t - t <= SERIA_S] + [(f.t, f.dst)]
            return len(set(d for t, d in self.odpytania)) >= SERIA_N
        return False

    def _stan(self, teraz):
        kiedy = 0.0
        st = None
        if self.t_wl > 0:
            kiedy, st = self.t_wl, 'y'
        if self.t_wyl > 0 and self.t_wyl >= kiedy:
            kiedy, st = self.t_wyl, 'n'
        if self.profil != PROFIL_ZDARZENIA:
            if self.t_zyje > kiedy:
                kiedy, st = self.t_zyje, 'y'
            od = max(self.t0, self.t_wl, self.t_zyje)
            if teraz - od > self.cisza_s and od + self.cisza_s >= kiedy:
                st = 'n'
        return st

    def _zmiana(self, teraz, zd):
        st = self._stan(teraz)
        if st is not None and st != self.stan:
            self.stan = st
            zd.append(('tv', st))
            if st == 'n' and self.wejscie is not None:
                self.wejscie = None
                self.sciezka = None

    def _wejscie(self, f, zd):
        op = f.opcode()
        d = f.data
        sc = None
        if op == OP_ROUTING_CHANGE and len(d) >= 5:
            sc = (d[3], d[4])
            if f.src == TV:
                self.t_trasa = f.t
        elif op in (OP_SET_STREAM_PATH, OP_ACTIVE_SOURCE, OP_ROUTING_INFO) and len(d) >= 3:
            sc = (d[1], d[2])
            # LG zaraz po Routing Change (wlaczenie, zmiana wejscia) rozglasza
            # Active Source 0.0.0.0 - echo, nie przejscie na wlasne zrodlo
            if (op == OP_ACTIVE_SOURCE and f.src == TV and sc == (0, 0)
                    and f.t - self.t_trasa <= ECHO_TRASY_S):
                return
        if sc is None:
            return
        s = pa_str(sc[0], sc[1])
        # Active Source od samego boxa to zawsze nBox, takze ze zlym adresem
        # (wtyczka Graterlii ogloszala 1.1.0.0 przy boxie na HDMI 1 i 3)
        if op == OP_ACTIVE_SOURCE and f.src == NBOX:
            w = 'nbox'
        else:
            w = 'nbox' if pa_covers(pa_parse(s), self.own_pa) else 'inne'
        if w != self.wejscie or s != self.sciezka:
            zmiana_w = w != self.wejscie
            self.wejscie = w
            self.sciezka = s
            if zmiana_w:
                zd.append(('wejscie', w, s))

    def feed(self, frames, teraz):
        zd = []
        for f in frames:
            op = f.opcode()
            if f.complete and f.src == TV and f.dst == BROADCAST:
                if op == OP_STANDBY:
                    self.t_wyl = max(self.t_wyl, f.t)
                elif op in (OP_REPORT_PA, OP_ACTIVE_SOURCE, OP_ROUTING_CHANGE,
                            OP_SET_STREAM_PATH):
                    self.t_wl = max(self.t_wl, f.t)
            if self._zyje(f):
                self.t_zyje = max(self.t_zyje, f.t)
            # stan przed wejsciem: Standby kasuje wejscie, wlaczenie je ustawia
            self._zmiana(f.t, zd)
            if f.complete and f.dst == BROADCAST:
                self._wejscie(f, zd)
        self._zmiana(teraz, zd)
        return zd

    def tick(self, teraz):
        zd = []
        self._zmiana(teraz, zd)
        return zd


# ustawienia Policy (wartosci jak w ConfigSelection wtyczki)
DOMYSLNE = {
    'tv_wl': 'nic',          # TV wlaczony: nic / obudz / obudz_nbox
    'tv_wyl': 'nic',         # TV wylaczony: nic / usypiaj
    'tv_wyl_po': 180,
    'tv_inne': 'nic',        # TV przelaczony na inne zrodlo: nic / usypiaj
    'tv_inne_po': 600,
    'box_wl': 'nic',         # box obudzony (nie przez wtyczke): nic / wlacz_tv / wlacz_tv_wejscie
    'box_wyl': 'nic',        # box uspiony (nie przez wtyczke): nic / wylacz_tv_nbox / wylacz_tv
}

# akcje Policy
WAKE = 'obudz_box'
STANDBY = 'uspij_box'
TV_ON = 'wlacz_tv'
TV_ON_INPUT = 'wlacz_tv_wejscie'
TV_OFF = 'wylacz_tv'

WLASNA_AKCJA_S = 30     # zmiana stanu boxa tyle s po naszej akcji = nasza
POWER_TV_S = 2.0        # Power od TV: tyle s na Standby / wlaczenie od TV


class Policy(object):
    """Decyzje z zdarzen TV i boxa. Kazda metoda zwraca liste (akcja, powod)."""

    def __init__(self, ust=None):
        self.ust = dict(DOMYSLNE)
        if ust:
            self.ust.update(ust)
        self.tv = None
        self.wejscie = None
        self.box_standby = None
        self.uspij_o = None         # czas zaplanowanego uspienia boxa
        self.uspij_powod = None
        self.nasze = {}             # akcja -> czas, do rozpoznania wlasnych
        self.power_o = None         # Power od TV: decyzja w tick() od tej chwili

    def _plan(self, teraz, po, powod):
        if self.box_standby is False:
            self.uspij_o = teraz + po
            self.uspij_powod = powod

    def _anuluj(self):
        self.uspij_o = None
        self.uspij_powod = None

    def _nasza(self, akcja, teraz):
        t = self.nasze.pop(akcja, None)
        return t is not None and teraz - t <= WLASNA_AKCJA_S

    def _wyk(self, akcja, teraz, powod):
        self.nasze[akcja] = teraz
        return [(akcja, powod)]

    def tv_event(self, zd, teraz):
        u = self.ust
        out = []
        if zd[0] == 'tv':
            poprz = self.tv
            self.tv = zd[1]
            if zd[1] == 'n':
                self.wejscie = None
                self._anuluj()
                # poprz None: start boxa (np. po zaniku pradu) przy wylaczonym TV
                if poprz != 'n' and u['tv_wyl'] == 'usypiaj':
                    self._plan(teraz, u['tv_wyl_po'], 'TV wylaczony')
            elif zd[1] == 'y':
                self._anuluj()
                if poprz == 'n' and u['tv_wl'] == 'obudz' and self.box_standby:
                    out += self._wyk(WAKE, teraz, 'TV wlaczony')
        elif zd[0] == 'wejscie':
            self.wejscie = zd[1]
            if zd[1] == 'nbox':
                self._anuluj()
                if u['tv_wl'] == 'obudz_nbox' and self.box_standby:
                    out += self._wyk(WAKE, teraz, 'TV przelaczony na nBox')
            elif zd[1] == 'inne' and u['tv_inne'] == 'usypiaj':
                self._plan(teraz, u['tv_inne_po'], 'TV na innym zrodle')
        return out

    def box_event(self, standby, teraz):
        """Box wszedl w standby (True) albo z niego wyszedl (False)."""
        u = self.ust
        poprz = self.box_standby
        self.box_standby = standby
        out = []
        if poprz is None or poprz == standby:
            return out
        self._anuluj()
        if standby:
            if self._nasza(STANDBY, teraz):
                return out
            if u['box_wyl'] == 'wylacz_tv' and self.tv != 'n':
                out += self._wyk(TV_OFF, teraz, 'box uspiony')
            elif u['box_wyl'] == 'wylacz_tv_nbox' and self.tv == 'y' and self.wejscie == 'nbox':
                out += self._wyk(TV_OFF, teraz, 'box uspiony, TV pokazywal nBox')
        else:
            if self._nasza(WAKE, teraz):
                return out
            if u['box_wl'] == 'wlacz_tv':
                out += self._wyk(TV_ON, teraz, 'box obudzony')
            elif u['box_wl'] == 'wlacz_tv_wejscie':
                out += self._wyk(TV_ON_INPUT, teraz, 'box obudzony')
            # obudzony pilotem przy TV na innym zrodle - liczy od nowa
            if self.wejscie == 'inne' and u['tv_inne'] == 'usypiaj' and u['box_wl'] != 'wlacz_tv_wejscie':
                self._plan(teraz, u['tv_inne_po'], 'TV na innym zrodle')
        return out

    def power_tv(self, teraz):
        """Power od TV: box za stanem TV, decyzja po POWER_TV_S - LG wysyla
        Power przed Standby (16:23:07 / 16:23:08) i tuz po wlaczeniu."""
        self.power_o = teraz + POWER_TV_S

    def tick(self, teraz):
        if self.power_o is not None and teraz >= self.power_o:
            self.power_o = None
            if self.tv == 'y' and self.box_standby:
                self._anuluj()
                return self._wyk(WAKE, teraz, 'Power od TV, TV wlaczony')
            if self.tv == 'n' and self.box_standby is False:
                self._anuluj()
                return self._wyk(STANDBY, teraz, 'Power od TV, TV wylaczony')
        if self.uspij_o is not None and teraz >= self.uspij_o:
            powod = self.uspij_powod
            self._anuluj()
            if self.box_standby is False:
                return self._wyk(STANDBY, teraz, powod)
        return []


# --- pilot TV (modul nbox_cec: /proc/nbox_cec_klawisze, linie "44 <kod>" / "45") ---

# kod User Control (CEC 1.3a) -> klawisz enigmy (linux/input.h). Exit ->
# KEY_HOME: tak nadaje pilot nBoxa (lircd.conf), w keymap.xml na boxach
# KEY_HOME = cancel i hide, KEY_EXIT tylko cancel.
KLAWISZE_CEC = {
    0x00: 352,                                  # Select -> KEY_OK
    0x01: 103, 0x02: 108, 0x03: 105, 0x04: 106,  # gora, dol, lewo, prawo
    0x09: 139, 0x0A: 139,                       # Root Menu, Setup Menu -> KEY_MENU
    0x0D: 102,                                  # Exit -> KEY_HOME
    0x20: 11, 0x21: 2, 0x22: 3, 0x23: 4, 0x24: 5,
    0x25: 6, 0x26: 7, 0x27: 8, 0x28: 9, 0x29: 10,  # cyfry 0..9
    0x30: 402, 0x31: 403,                       # kanal + / -
    0x35: 358,                                  # Display Information -> KEY_INFO
    0x37: 104, 0x38: 109,                       # Page Up / Down
    0x40: 'power_tv', 0x6B: 'power_tv',         # Power, Power Toggle -> za stanem TV
    0x44: 207, 0x45: 128, 0x46: 119, 0x47: 167,  # Play, Stop, Pause, Record
    0x48: 168, 0x49: 208,                       # Rewind, Fast Forward
    0x4B: 407, 0x4C: 412,                       # Forward -> KEY_NEXT, Backward -> KEY_PREVIOUS
    0x53: 365,                                  # Electronic Program Guide -> KEY_EPG
    0x71: 401, 0x72: 398, 0x73: 399, 0x74: 400,  # F1 niebieski, F2 czerwony, F3 zielony, F4 zolty
}
KEY_POWER = 116
# Power / Power Toggle od TV to nie klawisz, tylko Policy.power_tv(): LG webOS
# wysyla 44 40 przy kazdym wlaczeniu i wylaczeniu TV, wiec jako przelacznik
# box chodzil odwrotnie do TV (LG webOS 2026-10-23 15:25 i 16:23)
POWER_TV = 'power_tv'
CEC_POWER_OFF_FN = 0x6C     # tylko gdy box dziala
CEC_POWER_ON_FN = 0x6D      # tylko gdy box w standby

# flagi eActionMap.keyPressed (jak w OpenWebif remoteControl)
MAKE = 0
BREAK = 1
REPEAT = 2


class Pilot(object):
    """Linie z /proc/nbox_cec_klawisze -> [(kod CEC, klawisz, flaga)] do
    eActionMap.keyPressed; klawisz None = kod bez odpowiednika (do logu).
    Przytrzymanie = kolejne 44 z tym samym kodem -> REPEAT; 45 albo inny
    klawisz -> BREAK poprzedniego; bez 45 przez PUSC_S -> BREAK z tick()."""

    PUSC_S = 0.6

    def __init__(self):
        self.wcisniety = None       # (kod CEC, klawisz)
        self.od = 0.0

    def klawisz(self, kod, standby):
        if kod == CEC_POWER_ON_FN:
            return standby and KEY_POWER or 0
        if kod == CEC_POWER_OFF_FN:
            return (not standby) and KEY_POWER or 0
        return KLAWISZE_CEC.get(kod)

    def _pusc(self):
        if self.wcisniety is None:
            return []
        kod, k = self.wcisniety
        self.wcisniety = None
        return [(kod, k, BREAK)]

    def feed(self, linie, teraz, standby=False):
        out = []
        for l in linie:
            cz = l.split()
            if not cz:
                continue
            if cz[0] == '45':
                out += self._pusc()
                continue
            if cz[0] != '44' or len(cz) < 2:
                continue
            try:
                kod = int(cz[1], 16)
            except ValueError:
                continue
            k = self.klawisz(kod, standby)
            if k == 0:              # Power On/Off Function w zlym stanie boxa
                continue
            if k is None:
                out += self._pusc()
                out.append((kod, None, None))
                continue
            if self.wcisniety == (kod, k):
                out.append((kod, k, REPEAT))
            else:
                out += self._pusc()
                out.append((kod, k, MAKE))
                self.wcisniety = (kod, k)
            self.od = teraz
        return out

    def tick(self, teraz):
        if self.wcisniety is not None and teraz - self.od > self.PUSC_S:
            return self._pusc()
        return []
