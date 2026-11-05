# -*- coding: utf-8 -*-
"""Porównuje bukiet enigma2 z tym, co nadaje satelita (NIT/SDT/BAT z si_zbierz.py).

    python si_porownaj.py si.json lamedb userbouquet.01_ncplus.tv [--siec 13e] [--json wynik.json]

Wejście:
  si.json   - wynik si_zbierz.py (surowe sekcje w hex)
  lamedb    - /etc/enigma2/lamedb z boxa
  bukiet    - /etc/enigma2/userbouquet.*.tv z boxa
"""
import argparse, binascii, collections, json, sys

TV_TYPY = {0x01, 0x11, 0x16, 0x19, 0x1F, 0x20}


# ---------- tekst DVB (EN 300 468, aneks A) ----------
def dvb_tekst(b):
    if not b:
        return ''
    c = b[0]
    if c >= 0x20:
        kod = 'latin-1'           # ISO 6937 ~ latin-1 dla tego, co tu potrzebne
    elif 0x01 <= c <= 0x0B:
        kod, b = 'iso8859-%d' % (c + 4), b[1:]
    elif c == 0x10 and len(b) >= 3:
        kod, b = 'iso8859-%d' % b[2], b[3:]
    elif c == 0x15:
        kod, b = 'utf-8', b[1:]
    else:
        kod, b = 'latin-1', b[1:]
    s = b.decode(kod, errors='replace')
    return ''.join(ch for ch in s if ch >= ' ' and not (0x80 <= ord(ch) <= 0x9F)).strip()


def deskryptory(b):
    i, out = 0, []
    while i + 2 <= len(b):
        tag, n = b[i], b[i + 1]
        out.append((tag, b[i + 2:i + 2 + n]))
        i += 2 + n
    return out


def bcd(b):
    return int(binascii.hexlify(b).decode().rstrip('f') or 0)


def petla_ts(d, i, koniec):
    """Pętla transport_stream z NIT i BAT."""
    while i + 6 <= koniec:
        tsid = (d[i] << 8) | d[i + 1]
        onid = (d[i + 2] << 8) | d[i + 3]
        n = ((d[i + 4] & 0x0F) << 8) | d[i + 5]
        yield tsid, onid, deskryptory(d[i + 6:i + 6 + n])
        i += 6 + n


def lcn_z(tag, b):
    """Typowy deskryptor LCN (EICTA 0x83 i podobne): po 4 B sid(16) + flaga + lcn(10/14)."""
    out = {}
    if len(b) % 4:
        return out
    for i in range(0, len(b), 4):
        sid = (b[i] << 8) | b[i + 1]
        out[sid] = ((b[i + 2] & 0x03) << 8 | b[i + 3]) if tag == 0x83 else ((b[i + 2] & 0x3F) << 8 | b[i + 3])
    return out


def parsuj(sekcje):
    nit, sdt, bat = {}, {}, {}
    nieznane_bat = collections.Counter()
    for h in sekcje:
        d = binascii.unhexlify(h)
        tid, ext = d[0], (d[3] << 8) | d[4]
        koniec = len(d) - 4
        if tid in (0x40, 0x41):
            n = ((d[8] & 0x0F) << 8) | d[9]
            siec = nit.setdefault(ext, {'aktualna': tid == 0x40, 'nazwa': '', 'tp': {}})
            for tag, b in deskryptory(d[10:10 + n]):
                if tag == 0x40:
                    siec['nazwa'] = dvb_tekst(b)
            i = 10 + n
            m = ((d[i] & 0x0F) << 8) | d[i + 1]
            for tsid, onid, ds in petla_ts(d, i + 2, min(i + 2 + m, koniec)):
                tp = siec['tp'].setdefault((onid, tsid), {})
                for tag, b in ds:
                    if tag == 0x43:
                        pol = 'HVLR'[(b[6] >> 5) & 3]
                        tp.update(f=bcd(b[0:4]) // 100, poz=bcd(b[4:6]) / 10.0,
                                  pol=pol, sr=bcd(b[7:11]) // 100,  # ksym/s, ostatnia cyfra to FEC
                                  s2=bool(b[6] & 0x04))
        elif tid in (0x42, 0x46):
            onid = (d[8] << 8) | d[9]
            i = 11
            while i + 5 <= koniec:
                sid = (d[i] << 8) | d[i + 1]
                free_ca = bool(d[i + 3] & 0x10)
                n = ((d[i + 3] & 0x0F) << 8) | d[i + 4]
                rek = {'aktualny': tid == 0x42, 'kod': free_ca}
                for tag, b in deskryptory(d[i + 5:i + 5 + n]):
                    if tag == 0x48:
                        pn = b[1]
                        rek['typ'] = b[0]
                        rek['dostawca'] = dvb_tekst(b[2:2 + pn])
                        rek['nazwa'] = dvb_tekst(b[3 + pn:3 + pn + b[2 + pn]])
                sdt[(onid, ext, sid)] = rek
                i += 5 + n
        elif tid == 0x4A:
            n = ((d[8] & 0x0F) << 8) | d[9]
            bq = bat.setdefault(ext, {'nazwa': '', 'uslugi': {}, 'lcn': {}})
            for tag, b in deskryptory(d[10:10 + n]):
                if tag == 0x47:
                    bq['nazwa'] = dvb_tekst(b)
            i = 10 + n
            m = ((d[i] & 0x0F) << 8) | d[i + 1]
            for tsid, onid, ds in petla_ts(d, i + 2, min(i + 2 + m, koniec)):
                for tag, b in ds:
                    if tag == 0x41:
                        for j in range(0, len(b) - 2, 3):
                            bq['uslugi'][(onid, tsid, (b[j] << 8) | b[j + 1])] = b[j + 2]
                    elif tag >= 0x80:
                        nieznane_bat[tag] += 1
                        for sid, l in lcn_z(tag, b).items():
                            bq['lcn'].setdefault(tag, {})[(onid, tsid, sid)] = l
    return nit, sdt, bat, nieznane_bat


# ---------- enigma2 ----------
def wczytaj_lamedb(sciezka):
    L = open(sciezka, encoding='utf-8', errors='replace').read().split('\n')
    uslugi = {}
    i = L.index('services') + 1
    while L[i] != 'end':
        f = L[i].split(':')
        k = (int(f[3], 16), int(f[2], 16), int(f[0], 16))
        # ten sam SID bywa w lamedb i jako TV, i jako radio (typ 2) - TV ma pierwszeństwo
        if k not in uslugi or uslugi[k][1] == 2:
            uslugi[k] = (L[i + 1], int(f[4]))
        i += 3
    return uslugi


def wczytaj_bukiet(sciezka):
    wpisy = []
    poprz = None
    for l in open(sciezka, encoding='utf-8', errors='replace').read().split('\n'):
        if l.startswith('#SERVICE '):
            r = l[9:].split(':')
            if r[1] != '0':
                poprz = None
                continue
            nazwa = r[10] if len(r) > 10 and r[10] else None
            poprz = {'ref': ':'.join(r[:10]), 'klucz': (int(r[5], 16), int(r[4], 16), int(r[3], 16)),
                     'typ': int(r[2], 16), 'nazwa': nazwa}
            wpisy.append(poprz)
        elif l.startswith('#DESCRIPTION ') and poprz is not None:
            poprz['nazwa'] = poprz['nazwa'] or l[13:]
    return wpisy


def norm(s):
    return ''.join(s.upper().split()) if s else ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('si'); ap.add_argument('lamedb'); ap.add_argument('bukiet')
    ap.add_argument('--siec', default='13e', help='ONID sieci operatora (hex), nc+ = 13e')
    ap.add_argument('--bat', help='bouquet_id BAT do porównania (hex, po przecinku), np. 2020; domyślnie wszystkie')
    ap.add_argument('--poz', type=float, default=13.0, help='pozycja satelity z NIT, domyślnie 13.0 (Hot Bird)')
    ap.add_argument('--json')
    a = ap.parse_args()
    siec = int(a.siec, 16)

    si = json.load(open(a.si))
    nit, sdt, bat, nieznane = parsuj(si['sekcje'])
    lamedb = wczytaj_lamedb(a.lamedb)
    bukiet = wczytaj_bukiet(a.bukiet)
    for w in bukiet:
        if not w['nazwa'] and w['klucz'] in lamedb:
            w['nazwa'] = lamedb[w['klucz']][0]

    P = print
    P('Zebrane %s, %s s, sekcji %d, brakujących %d' % (si['czas'], si['sekund'], len(si['sekcje']), len(si['brakujace'])))
    for nid, s in sorted(nit.items()):
        P('NIT sieć 0x%04x %r%s: %d TP' % (nid, s['nazwa'], ' (aktualna)' if s['aktualna'] else '', len(s['tp'])))
    onidy = collections.Counter(k[0] for k in sdt)
    P('SDT: %d usług, wg ONID: %s' % (len(sdt), {hex(k): v for k, v in onidy.items()}))
    for bid, b in sorted(bat.items()):
        P('BAT 0x%04x %r: %d usług, LCN w tagach %s' % (bid, b['nazwa'], len(b['uslugi']),
                                                     {hex(t): len(v) for t, v in b['lcn'].items()}))
    if nieznane:
        P('Prywatne deskryptory w pętli TS BAT:', {hex(k): v for k, v in nieznane.items()})

    # transpondery: lamedb vs NIT operatora
    tp_nit = {}
    for s in nit.values():
        for (onid, tsid), tp in s['tp'].items():
            if onid == siec:
                tp_nit[tsid] = tp
    tp_lamedb = {k[1] for k in lamedb if k[0] == siec}
    P('\n== Transpondery sieci 0x%x ==' % siec)
    P('w NIT: %d, w lamedb: %d' % (len(tp_nit), len(tp_lamedb)))
    for tsid in sorted(set(tp_nit) - tp_lamedb):
        P('  tylko w NIT:    %04x %s' % (tsid, tp_nit[tsid]))
    for tsid in sorted(tp_lamedb - set(tp_nit)):
        P('  tylko w lamedb: %04x' % tsid)

    # bukiet vs SDT
    # sprawdzać da się tylko transpondery, z których przyszło SDT (actual albo other)
    ts_z_sdt = {(k[0], k[1]) for k in sdt}
    sprawdzalne = [w for w in bukiet if w['klucz'][:2] in ts_z_sdt]
    P('\n== Bukiet (%d kanałów, %d na TP z SDT: %s) vs SDT ==' % (
        len(bukiet), len(sprawdzalne), ' '.join('%x:%x' % t for t in sorted(ts_z_sdt))))
    po_nazwie = collections.defaultdict(list)
    for k, r in sdt.items():
        po_nazwie[norm(r.get('nazwa'))].append(k)
    brak, inna_nazwa, kod = [], [], 0
    for w in sprawdzalne:
        r = sdt.get(w['klucz'])
        if r is None:
            gdzie = [k for k in po_nazwie.get(norm(w['nazwa']), []) if k != w['klucz']]
            brak.append((w, gdzie))
        elif norm(r.get('nazwa')) != norm(w['nazwa']):
            inna_nazwa.append((w, r))
    P('nie ma w SDT: %d' % len(brak))
    for w, gdzie in brak:
        dalej = ', nazwa jest pod ' + ' '.join('%x:%x:%x' % k for k in gdzie) if gdzie else ''
        P('  %-30s %s%s' % (w['nazwa'], w['ref'], dalej))
    P('inna nazwa w SDT: %d' % len(inna_nazwa))
    for w, r in inna_nazwa:
        P('  %-30s -> %-30s %s' % (w['nazwa'], r.get('nazwa'), w['ref']))

    # BAT vs bukiet - tylko usługi TV z pozycji --poz (BAT nc+ ma też Astrę 19,2)
    pozycja = {}
    for s in nit.values():
        for k, tp in s['tp'].items():
            pozycja[k] = tp.get('poz')
    nazwa = lambda k: (sdt.get(k) or {}).get('nazwa') or (lamedb.get(k) or ('?',))[0]
    w_bukiecie = {w['klucz'] for w in bukiet}
    nazwy_bukietu = {norm(w['nazwa']) for w in bukiet} | {norm(nazwa(w['klucz'])) for w in bukiet}
    wybrane = [int(x, 16) for x in a.bat.split(',')] if a.bat else sorted(bat)
    for bid in wybrane:
        b = bat.get(bid)
        if not b:
            P('\nBAT 0x%04x: nie ma w danych' % bid)
            continue
        lcn = {}
        for v in b['lcn'].values():
            lcn.update(v)
        tv = {k for k, t in b['uslugi'].items() if t in TV_TYPY and pozycja.get(k[:2]) == a.poz}
        P('\n== BAT 0x%04x %r: %d usług, TV na %.1f°: %d, z bukietu w BAT: %d ==' % (
            bid, b['nazwa'], len(b['uslugi']), a.poz, len(tv), len(w_bukiecie & set(b['uslugi']))))
        poza = [w for w in bukiet if w['klucz'] not in b['uslugi']]
        P('kanały bukietu, których nie ma w tym BAT: %d' % len(poza))
        for w in poza:
            r = sdt.get(w['klucz'])
            P('  %-30s %x:%x:%x  %s' % (w['nazwa'], *w['klucz'],
                                        'SDT: ' + r.get('nazwa', '?') if r else 'brak w SDT'))
        brakuje = sorted((lcn.get(k, 99999), k) for k in tv
                         if k not in w_bukiecie and norm(nazwa(k)) not in nazwy_bukietu)
        P('TV z BAT bez odpowiednika w bukiecie (ani po kluczu, ani po nazwie): %d' % len(brakuje))
        for l, k in brakuje:
            P('  LCN %-5s %-30s %x:%x:%x' % ('' if l == 99999 else l, nazwa(k), *k))
        kolej = [lcn[w['klucz']] for w in bukiet if w['klucz'] in lcn]
        P('kolejność bukietu wg LCN: %d spadków na %d par' % (
            sum(1 for x, y in zip(kolej, kolej[1:]) if y < x), max(len(kolej) - 1, 0)))

    if a.json:
        json.dump({
            'nit': {hex(n): {'nazwa': s['nazwa'], 'tp': {'%x:%x' % k: v for k, v in s['tp'].items()}} for n, s in nit.items()},
            'sdt': {'%x:%x:%x' % k: v for k, v in sdt.items()},
            'bat': {hex(b): {'nazwa': v['nazwa'], 'uslugi': {'%x:%x:%x' % k: t for k, t in v['uslugi'].items()},
                             'lcn': {hex(t): {'%x:%x:%x' % k: l for k, l in m.items()} for t, m in v['lcn'].items()}}
                    for b, v in bat.items()},
        }, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
