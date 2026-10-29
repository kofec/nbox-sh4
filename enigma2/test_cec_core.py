# -*- coding: utf-8 -*-
#
# Testy logiki wtyczki nBox CEC (NBoxCEC/cec_core.py) na PC:
#   python enigma2/test_cec_core.py            - testy na ramkach z logow
#   python enigma2/test_cec_core.py LOG PROFIL ADRES [CISZA_S]
#                                                    - odtworzenie logu cec_rx_log.sh
# Ramki w testach wyciete z podsluchu 2026-10-21/22 (kopie w
# logach cec_rx_log.sh), czasy przesuniete do malych liczb.

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'NBoxCEC'))
import cec_core as c  # noqa: E402


def ramki(spec):
    """'t ramka' w liniach -> lista Frame (nr kolejny)."""
    out = []
    for i, l in enumerate(x for x in spec.strip().splitlines() if x.strip()):
        t, r = l.strip().split(' ', 1)
        f = c.parse_line('%d %s %s' % (i + 1, t, r))
        assert f is not None, l
        out.append(f)
    return out


class Uklad(object):
    """Tracker + Policy + symulowany box (stan boxa idzie za akcjami)."""

    def __init__(self, profil, own, ust=None, box_standby=False, cisza_s=60):
        self.tr = c.TvTracker(profil, cisza_s=cisza_s, own_pa=c.pa_parse(own), t0=0.0)
        self.po = c.Policy(ust)
        self.po.box_event(box_standby, 0.0)
        self.box = box_standby
        self.log = []

    def _akcje(self, akcje, t):
        for a, powod in akcje:
            self.log.append((t, a))
            if a == c.WAKE:
                self.box_zmiana(False, t)
            elif a == c.STANDBY:
                self.box_zmiana(True, t)

    def box_zmiana(self, standby, t):
        self.box = standby
        self._akcje(self.po.box_event(standby, t), t)

    def ramki(self, frames, do=None):
        for f in frames:
            for zd in self.tr.feed([f], f.t):
                self.log.append((f.t, zd))
                self._akcje(self.po.tv_event(zd, f.t), f.t)
            self._akcje(self.po.tick(f.t), f.t)
        if do is not None:
            self.czas(do)

    def czas(self, do, krok=1.0):
        t = self.tr.t_wl
        t = max([t] + [x[0] for x in self.log])
        while t < do:
            t += krok
            for zd in self.tr.tick(t):
                self.log.append((t, zd))
                self._akcje(self.po.tv_event(zd, t), t)
            self._akcje(self.po.tick(t), t)

    def zdarzenia(self):
        return [x[1] for x in self.log]


class Parsowanie(unittest.TestCase):
    def test_linie(self):
        f = c.parse_line('4379 1792601166.049 0>F 0f- 36-')
        self.assertEqual((f.src, f.dst, f.data, f.complete), (0, 15, [0x36], True))
        f = c.parse_line('5404 1792635919.103 0>1 01- ?')
        self.assertEqual((f.src, f.dst, f.data, f.complete), (0, 1, [], False))
        f = c.parse_line('3065 1792598021.372 3>0 30+ 04+')
        self.assertEqual((f.ack, f.opcode()), ([True, True], 0x04))
        self.assertIsNone(c.parse_line('5526 1792609787.784 - ? !2'))
        self.assertIsNone(c.parse_line('# PIO 4.4 irq 212 ramek 0 zboczy 0'))
        f = c.parse_line('4037 1792600541.337 0>F 0f- ? !2')
        self.assertFalse(f.complete)

    def test_adresy(self):
        self.assertTrue(c.pa_covers((1, 0, 0, 0), (1, 0, 0, 0)))
        self.assertTrue(c.pa_covers((1, 0, 0, 0), (1, 1, 0, 0)))
        self.assertFalse(c.pa_covers((1, 0, 0, 0), (3, 0, 0, 0)))
        self.assertFalse(c.pa_covers((0, 0, 0, 0), (1, 0, 0, 0)))
        self.assertEqual(c.pa_bytes(c.pa_parse('3.0.0.0')), '3000')

    def test_reader_po_przeladowaniu(self):
        r = c.ProcReader()
        a = r.new_frames(['1 100.0 0>F 0f- 36-', '2 101.0 0>F 0f- 87- 00- e0- 91-'])
        self.assertEqual(len(a), 2)
        self.assertEqual(r.new_frames(['1 100.0 0>F 0f- 36-', '2 101.0 0>F 0f- 87- 00- e0- 91-']), [])
        b = r.new_frames(['1 200.0 0>F 0f- 36-'])     # modul od nowa, nr 1
        self.assertEqual(len(b), 1)

    def test_reader_parsuje_tylko_nowe(self):
        r = c.ProcReader()
        bufor = ['# PIO 4.4'] + ['%d %d.0 0>5 05+ 8f+' % (i, 100 + i) for i in range(1, 257)]
        self.assertEqual(len(r.new_frames(bufor)), 256)
        stary = c.parse_line
        wywolania = []
        c.parse_line = lambda l: wywolania.append(l) or stary(l)
        try:
            nowy = bufor[3:] + ['257 357.0 0>F 0f- 36-', '258 358.0 0>F 0f- 84- 00- 00- 00-']
            f = r.new_frames(nowy)
        finally:
            c.parse_line = stary
        self.assertEqual([x.nr for x in f], [257, 258])
        self.assertEqual(len(wywolania), 2)

    def test_tylko_koncowe(self):
        zd = [('tv', 'y'), ('wejscie', 'nbox', '1.0.0.0'), ('tv', 'n'), ('tv', 'y'),
              ('wejscie', 'inne', '0.0.0.0')]
        self.assertEqual(c.tylko_koncowe(zd), [('tv', 'y'), ('wejscie', 'inne', '0.0.0.0')])
        self.assertEqual(c.tylko_koncowe([('tv', 'y'), ('wejscie', 'nbox', '1.0.0.0'), ('tv', 'n')]),
                         [('tv', 'n')])
        self.assertEqual(c.tylko_koncowe([]), [])

    def test_stara_historia_przy_starcie(self):
        # Sony BRAVIA 8: ostatnie ramki w buforze z 22.10 23:56, start wtyczki
        # 23.10 06:15:37 - przed 1.5 "tv y" + "wejscie nbox 1.0.0.0"
        linie = ['23084 1792706193.550 3>F 3f+ 82+ 10+ 00+',
                 '23086 1792706197.853 3>0 30+ 36+',
                 '23088 1792706198.235 0>F 0f- a0- 08- 00- 46- 00- 3f- 00- 00- 00- 00- 00-',
                 '23089 1792706198.544 0>F 0f- a0- 08- 00- 46- 00- 09- 00- 01-']
        teraz = 1792728944.0
        for odrzuc, oczekiwane in ((False, [('tv', 'y'), ('wejscie', 'nbox', '1.0.0.0')]),
                                   (True, [])):
            tr = c.TvTracker(c.PROFIL_CISZA, cisza_s=60, own_pa=c.pa_parse('1.0.0.0'), t0=teraz)
            f = c.ProcReader().new_frames(linie)
            if odrzuc:
                f = c.swieze(f, teraz, tr.cisza_s)
            self.assertEqual(c.tylko_koncowe(tr.feed(f, teraz)), oczekiwane)
            if odrzuc:      # cisza od startu -> wylaczony, jak bez ramek
                self.assertEqual(tr.tick(teraz + 61), [('tv', 'n')])
        # ramki z ostatnich 60 s zostaja (TV wlaczony w chwili startu)
        f = c.ProcReader().new_frames(['1 %.3f 0>1 01-' % (teraz - 10), '2 %.3f 0>F 0f- 36-' % (teraz - 70)])
        self.assertEqual([x.nr for x in c.swieze(f, teraz, 60)], [1])


# LG webOS (nBox na HDMI 3): standby z Vendor ID co 10 s, wlaczenie
# 20:12:21, odpytywanie, Standby 22:46:17
PIOTR_STANDBY = '''
10.0 0>F 0f- 87- 00- e0- 91-
20.0 0>F 0f- 87- 00- e0- 91-
30.0 0>F 0f- 87- 00- e0- 91-
40.0 0>F 0f- 87- 00- e0- 91-
50.0 0>F 0f- 87- 00- e0- 91-
60.0 0>F 0f- 87- 00- e0- 91-
70.0 0>F 0f- 87- 00- e0- 91-
80.0 0>F 0f- 87- 00- e0- 91-
'''
PIOTR_WL = '''
100.000 0>F 0f- 84- 00- 00- 00-
100.560 0>F 0f- 85-
101.160 0>F 0f- 80- 00- 00- 10- 00-
101.326 0>F 0f- 82- 00- 00-
110.0 0>F 0f- 87- 00- e0- 91-
112.0 0>1 01-
112.1 0>2 02-
112.2 0>3 03-
127.0 0>1 01-
127.1 0>2 02-
127.2 0>3 03-
'''
PIOTR_NA_NBOX = '''
130.000 0>F 0f- 80- 10- 00- 30- 00-
'''
PIOTR_WYL = '''
140.0 0>F 0f- 36-
150.0 0>F 0f- 87- 00- e0- 91-
160.0 0>F 0f- 87- 00- e0- 91-
'''


class LgWebos(unittest.TestCase):
    def test_stan_i_wejscie(self):
        u = Uklad(c.PROFIL_ODPYTYWANIE, '3.0.0.0', box_standby=True)
        u.ramki(ramki(PIOTR_STANDBY))
        self.assertEqual(u.zdarzenia(), [('tv', 'n')])   # Vendor ID nie budzi
        u.ramki(ramki(PIOTR_WL))
        self.assertIn(('tv', 'y'), u.zdarzenia())
        self.assertEqual(u.tr.wejscie, 'inne')           # 1.0.0.0, potem sam TV
        u.ramki(ramki(PIOTR_NA_NBOX))
        self.assertEqual(u.tr.wejscie, 'nbox')
        u.ramki(ramki(PIOTR_WYL), do=400)
        self.assertEqual(u.zdarzenia()[-1], ('tv', 'n'))
        self.assertEqual(u.zdarzenia().count(('tv', 'y')), 1)

    def test_pojedyncze_odpytanie_to_nie_wlaczenie(self):
        # 12:56:32, LG webOS: jedno 0>7 w standby (po restarcie enigmy)
        u = Uklad(c.PROFIL_ODPYTYWANIE, '3.0.0.0', box_standby=True)
        u.ramki(ramki(PIOTR_STANDBY + '''
85.0 0>7 07+
95.0 0>F 0f- 87- 00- e0- 91-
101.0 0>2 02-
105.0 0>5 05-
'''), do=200)
        self.assertNotIn(('tv', 'y'), u.zdarzenia())
        # seria: trzy adresy w 0,2 s
        u.ramki(ramki('300.0 0>1 01-\n300.1 0>2 02-\n300.2 0>3 03-'))
        self.assertEqual(u.zdarzenia()[-1], ('tv', 'y'))

    def test_obudz_tylko_na_wejsciu_nboxa(self):
        u = Uklad(c.PROFIL_ODPYTYWANIE, '3.0.0.0', {'tv_wl': 'obudz_nbox'}, box_standby=True)
        u.ramki(ramki(PIOTR_STANDBY + PIOTR_WL))
        self.assertTrue(u.box)                           # TV wlaczony na Smart TV - box spi
        u.ramki(ramki(PIOTR_NA_NBOX))
        self.assertFalse(u.box)
        self.assertIn((130.0, c.WAKE), u.log)

    def test_obudz_zawsze(self):
        u = Uklad(c.PROFIL_ODPYTYWANIE, '3.0.0.0', {'tv_wl': 'obudz'}, box_standby=True)
        u.ramki(ramki(PIOTR_STANDBY + PIOTR_WL))
        self.assertFalse(u.box)

    def test_wlasne_uspienie_nie_wylacza_tv(self):
        ust = {'tv_wl': 'obudz', 'tv_wyl': 'usypiaj', 'tv_wyl_po': 60, 'box_wyl': 'wylacz_tv'}
        u = Uklad(c.PROFIL_ODPYTYWANIE, '3.0.0.0', ust, box_standby=True)
        u.ramki(ramki(PIOTR_STANDBY + PIOTR_WL + PIOTR_WYL), do=400)
        akcje = [a for t, a in u.log if isinstance(a, str)]
        self.assertEqual(akcje, [c.WAKE, c.STANDBY])     # bez wylacz_tv
        self.assertTrue(u.box)

    def test_box_uspiony_pilotem(self):
        ust = {'box_wyl': 'wylacz_tv_nbox'}
        u = Uklad(c.PROFIL_ODPYTYWANIE, '3.0.0.0', ust)
        u.ramki(ramki(PIOTR_STANDBY + PIOTR_WL))
        u.box_zmiana(True, 128.0)                        # TV na Smart TV
        self.assertNotIn(c.TV_OFF, [a for t, a in u.log])
        u.box_zmiana(False, 129.0)
        u.ramki(ramki(PIOTR_NA_NBOX))
        u.box_zmiana(True, 135.0)                        # TV pokazuje nBox
        self.assertIn((135.0, c.TV_OFF), u.log)

    def test_uspij_na_innym_zrodle(self):
        ust = {'tv_inne': 'usypiaj', 'tv_inne_po': 300}
        u = Uklad(c.PROFIL_ODPYTYWANIE, '3.0.0.0', ust)
        u.ramki(ramki(PIOTR_STANDBY + PIOTR_WL))         # 101.326: sam TV
        u.ramki(ramki(PIOTR_NA_NBOX))                    # 130: nBox - anuluje
        u.czas(300)
        self.assertFalse(u.box)
        # cisza_s duze: w ramkach testu odpytywanie konczy sie na 127 s
        u2 = Uklad(c.PROFIL_ODPYTYWANIE, '3.0.0.0', ust, cisza_s=1000)
        u2.ramki(ramki(PIOTR_STANDBY + PIOTR_WL))
        u2.czas(450)
        self.assertTrue(u2.box)
        self.assertIn((401, c.STANDBY), [(round(t), a) for t, a in u2.log])   # 101.16 + 300


# LG plazma: odpytywanie bez EOM, Standby, potem cisza
BABCIA = '''
10.0 0>F 0f- 87- 00- e0- 91-
10.1 0>1 01- ?
10.2 0>2 02- ?
25.0 0>F 0f- 87- 00- e0- 91-
25.1 0>1 01- ?
35.0 0>F 0f- 36-
36.0 0>F 0f- 36-
'''


class LgPlazma(unittest.TestCase):
    def test_cisza(self):
        ust = {'tv_wl': 'obudz', 'tv_wyl': 'usypiaj', 'tv_wyl_po': 180}
        u = Uklad(c.PROFIL_CISZA, '1.0.0.0', ust)
        u.ramki(ramki(BABCIA), do=300)
        self.assertEqual([z for z in u.zdarzenia() if z[0] == 'tv'], [('tv', 'y'), ('tv', 'n')])
        self.assertIn((215.0, c.STANDBY), u.log)
        # rano: pierwsza ramka budzi
        u.ramki(ramki('1000.0 0>F 0f- 87- 00- e0- 91-'))
        self.assertFalse(u.box)
        self.assertEqual(u.tr.wejscie, None)             # plazma nie mowi o wejsciu


# Sony z soundbarem (box BSLA); po Standby jeszcze ~65 s rozmowy z soundbarem
G41 = '''
10.000 0>F 0f- 84- 00- 00- 00-
10.150 0>F 0f- 87- 08- 00- 46-
10.300 0>F 0f- 82- 00- 00-
16.400 0>5 05+ 8f+
16.460 5>0 50+ 90+ 00+
76.400 0>5 05+ 8f+
100.000 0>F 0f- 36-
100.150 0>F 0f- a0- 08- 00- 46- 00- 3f- 00- 00- 00- 00- 00-
101.500 0>5 05+ 00+ a0+ 01+
112.200 0>5 05+ 00+ c5+ 01+
163.700 0>5 05+ a0+ 08+ 00+ 46+ 00+ 33+ 00+
'''


class G41Test(unittest.TestCase):
    def test_bez_mrugania_po_standby(self):
        u = Uklad(c.PROFIL_CISZA, '4.0.0.0', cisza_s=150)
        u.ramki(ramki(G41), do=600)
        self.assertEqual([z for z in u.zdarzenia() if z[0] == 'tv'], [('tv', 'y'), ('tv', 'n')])


# Sony BRAVIA 8, nBox na HDMI 1: TV na wlasnym zrodle, potem HDMI 1
PODLIPIE = '''
10.0 0>1 01-
10.1 0>2 02-
20.0 0>F 0f- 82- 00- 00-
25.0 0>1 01-
40.0 0>F 0f- 80- 00- 00- 10- 00-
55.0 0>1 01-
70.0 0>F 0f- a0- 08- 00- 46- 00- 3f- 00- 00- 00- 00- 00-
70.3 0>F 0f- 36-
'''


class SonyBravia8(unittest.TestCase):
    def test_wejscie(self):
        u = Uklad(c.PROFIL_CISZA, '1.0.0.0')
        u.ramki(ramki(PODLIPIE), do=300)
        we = [z for z in u.zdarzenia() if z[0] == 'wejscie']
        self.assertEqual(we, [('wejscie', 'inne', '0.0.0.0'), ('wejscie', 'nbox', '1.0.0.0')])
        self.assertEqual(u.zdarzenia()[-1], ('tv', 'n'))

    def test_active_source_od_boxa(self):
        # 22.10 17:03, Sony BRAVIA 8: wtyczka Graterlii po restarcie enigmy
        # oglosila 1.1.0.0 (box na HDMI 1) - to nadal nBox
        u = Uklad(c.PROFIL_CISZA, '1.0.0.0')
        u.ramki(ramki('''
10.0 0>F 0f- 82- 00- 00-
20.0 3>F 3f+ 82+ 11+ 00+
30.0 0>F 0f- 80- 10- 00- 20- 00-
'''))
        we = [z for z in u.zdarzenia() if z[0] == 'wejscie']
        self.assertEqual(we, [('wejscie', 'inne', '0.0.0.0'), ('wejscie', 'nbox', '1.1.0.0'),
                              ('wejscie', 'inne', '2.0.0.0')])


def odtworz(sciezka, profil, adres, cisza_s=60):
    """Log cec_rx_log.sh -> zdarzenia trackera (ramki 'polling NACK' rozwiniete)."""
    linie = []
    off = None
    for l in open(sciezka):
        p = l.split()
        if len(p) >= 5 and p[2].isdigit() and '.' in p[3]:
            linie.append(' '.join(p[2:]))
            if off is None:
                off = float(p[3]) - time.mktime(time.strptime(p[0] + ' ' + p[1][:8], '%Y-%m-%d %H:%M:%S'))
        elif 'polling NACK' in l and off is not None:
            t = time.mktime(time.strptime(p[0] + ' ' + p[1], '%Y-%m-%d %H:%M:%S')) + off
            for a in p[5:]:
                s, d = a.split('>')
                linie.append('0 %.3f %s %s%s-' % (t, a, s.lower(), d.lower()))
    frames = sorted((c.parse_line(x) for x in linie if c.parse_line(x)), key=lambda f: f.t)
    tr = c.TvTracker(profil, cisza_s=cisza_s, own_pa=c.pa_parse(adres), t0=frames[0].t)
    ost = frames[0].t
    for f in frames:
        t = ost
        while t + 5 < f.t:              # tick co 5 s w przerwach
            t += 5
            for zd in tr.tick(t):
                print(time.strftime('%m-%d %H:%M:%S', time.localtime(t)), zd)
        for zd in tr.feed([f], f.t):
            print(time.strftime('%m-%d %H:%M:%S', time.localtime(f.t)), zd)
        ost = f.t


class PilotTest(unittest.TestCase):
    """Klawisze z /proc/nbox_cec_klawisze (test na boxie BSLA 23.10 06:12, Sony)."""

    def test_strzalki_z_testu_sony(self):
        p = c.Pilot()
        zd = p.feed(['44 00', '45', '44 04', '45', '44 03', '45'], 0.0)
        self.assertEqual(zd, [(0x00, 352, c.MAKE), (0x00, 352, c.BREAK),
                              (0x04, 106, c.MAKE), (0x04, 106, c.BREAK),
                              (0x03, 105, c.MAKE), (0x03, 105, c.BREAK)])

    def test_przytrzymanie_i_brak_puszczenia(self):
        p = c.Pilot()
        self.assertEqual(p.feed(['44 01'], 0.0), [(0x01, 103, c.MAKE)])
        self.assertEqual(p.feed(['44 01'], 0.5), [(0x01, 103, c.REPEAT)])
        self.assertEqual(p.tick(1.0), [])                   # 0,5 s od ostatniego
        self.assertEqual(p.tick(1.2), [(0x01, 103, c.BREAK)])
        self.assertEqual(p.tick(2.0), [])

    def test_inny_klawisz_bez_45(self):
        p = c.Pilot()
        zd = p.feed(['44 01', '44 02'], 0.0)
        self.assertEqual(zd, [(0x01, 103, c.MAKE), (0x01, 103, c.BREAK), (0x02, 108, c.MAKE)])

    def test_cyfry_kanaly_nieznane(self):
        p = c.Pilot()
        zd = p.feed(['44 25', '45', '44 30', '45', '44 76', '', 'smiec', '44 zz'], 0.0)
        self.assertEqual(zd, [(0x25, 6, c.MAKE), (0x25, 6, c.BREAK),
                              (0x30, 402, c.MAKE), (0x30, 402, c.BREAK),
                              (0x76, None, None)])

    def test_power_on_off_function(self):
        p = c.Pilot()
        self.assertEqual(p.feed(['44 6d', '45'], 0.0, standby=False), [])
        self.assertEqual(p.feed(['44 6d'], 0.0, standby=True), [(0x6d, 116, c.MAKE)])
        p = c.Pilot()
        self.assertEqual(p.feed(['44 6c'], 0.0, standby=True), [])
        self.assertEqual(p.feed(['44 6c'], 0.0, standby=False), [(0x6c, 116, c.MAKE)])

    def test_power_to_nie_klawisz(self):
        p = c.Pilot()
        self.assertEqual(p.feed(['44 40', '45', '44 6b'], 0.0),
                         [(0x40, c.POWER_TV, c.MAKE), (0x40, c.POWER_TV, c.BREAK),
                          (0x6b, c.POWER_TV, c.MAKE)])


class PowerOdTv(unittest.TestCase):
    """LG webOS 2026-10-23: 44 40 przy wlaczeniu (15:25:46, box juz
    obudzony przez wtyczke) i przy wylaczeniu (16:23:07, sekunde przed Standby)
    - w 2.0.1 KEY_POWER przelaczal box odwrotnie do TV."""

    PIOTR = {'tv_wl': 'obudz_nbox', 'tv_wyl': 'usypiaj', 'tv_wyl_po': 300,
             'tv_inne': 'usypiaj', 'tv_inne_po': 1800, 'box_wl': 'wlacz_tv_wejscie'}

    def test_wlaczenie_tv_box_zostaje(self):
        po = c.Policy(self.PIOTR)
        po.box_event(True, 0.0)
        po.tv_event(('tv', 'n'), 1.0)
        po.tv_event(('tv', 'y'), 100.0)
        self.assertEqual(po.tv_event(('wejscie', 'nbox', '3.0.0.0'), 102.0),
                         [(c.WAKE, 'TV przelaczony na nBox')])
        self.assertEqual(po.box_event(False, 103.0), [])     # wlasne
        po.power_tv(103.0)
        self.assertEqual(po.tick(105.5), [])                 # TV y, box dziala

    def test_wylaczenie_tv_box_w_standby_zostaje(self):
        po = c.Policy(self.PIOTR)
        po.box_event(True, 0.0)
        po.tv_event(('tv', 'y'), 1.0)
        po.power_tv(200.0)
        po.tv_event(('tv', 'n'), 201.0)
        self.assertEqual(po.tick(202.5), [])                 # nie budzi

    def test_wylaczenie_tv_usypia_od_razu_bez_wylaczania_tv(self):
        po = c.Policy(dict(self.PIOTR, box_wyl='wylacz_tv'))
        po.box_event(False, 0.0)
        po.tv_event(('tv', 'y'), 1.0)
        po.power_tv(300.0)
        po.tv_event(('tv', 'n'), 301.0)                       # plan 300 s
        self.assertEqual(po.tick(301.5), [])                  # czeka na POWER_TV_S
        self.assertEqual(po.tick(302.5), [(c.STANDBY, 'Power od TV, TV wylaczony')])
        self.assertEqual(po.box_event(True, 303.0), [])       # wlasne - TV nie ruszac
        self.assertEqual(po.tick(700.0), [])                  # plan skasowany

    def test_wlaczenie_tv_budzi_box(self):
        po = c.Policy({'box_wl': 'wlacz_tv_wejscie'})        # tv_wl = nic
        po.box_event(True, 0.0)
        po.tv_event(('tv', 'n'), 1.0)
        po.tv_event(('tv', 'y'), 400.0)
        po.power_tv(400.5)
        self.assertEqual(po.tick(403.0), [(c.WAKE, 'Power od TV, TV wlaczony')])
        self.assertEqual(po.box_event(False, 404.0), [])      # bez 3004 / 3f82

    def test_stan_tv_nieznany(self):
        po = c.Policy(self.PIOTR)
        po.box_event(False, 0.0)
        po.power_tv(1.0)
        self.assertEqual(po.tick(4.0), [])


if __name__ == '__main__':
    if len(sys.argv) >= 4:
        odtworz(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 60)
    else:
        unittest.main()
