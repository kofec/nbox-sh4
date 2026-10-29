# -*- coding: utf-8 -*-
#
# zbuduj_ipk.py - pakiety opkg dla nBoxow (GraterliaOS, opkg 0.2.4):
#   kernel-module-nbox-cec               - sh4/nbox_cec (nbox_cec.ko + /etc/init.d/nbox_cec),
#                                          zastepuje cec_ctrl (kernel-modules-cec-gos) i cec_rx
#   kernel-module-cec-rx                 - sh4/cec_rx (cec_rx.ko + /etc/init.d/cec_rx)
#   enigma2-plugin-systemplugins-nboxcec - enigma2/NBoxCEC (zawsze)
#
#   python pakiety/zbuduj_ipk.py [--nbox-ko SCIEZKA/nbox_cec.ko] [--ko SCIEZKA/cec_rx.ko] [--wyj KATALOG]
#
# Moduly .ko nie sa w repo: buduje je kontener z sh4/Dockerfile
# (README.md); sprawdzany vermagic jadra nBoxow.
# Pakiet = archiwum ar: debian-binary, control.tar.gz, data.tar.gz; wlasciciel
# root, konce linii LF (git na Windows daje CRLF - skrypty sh by padly).

import argparse
import gzip
import hashlib
import io
import os
import re
import sys
import tarfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAKIETY = os.path.join(REPO, 'pakiety')
WTYCZKA = os.path.join(REPO, 'enigma2', 'NBoxCEC')
NBOX_CEC_C = os.path.join(REPO, 'sh4', 'nbox_cec', 'nbox_cec.c')
CEL_WTYCZKI = 'usr/lib/enigma2/python/Plugins/SystemPlugins/NBoxCEC'
VERMAGIC = b'vermagic=2.6.32.61_stm24_0217 preempt mod_unload SH4LE'


def tekst(sciezka):
    with open(sciezka, 'rb') as f:
        return f.read().replace(b'\r\n', b'\n')


def tar_gz(pliki, mtime):
    """pliki: [(sciezka w archiwum, bajty albo None = katalog, tryb)]."""
    surowe = io.BytesIO()
    with tarfile.open(fileobj=surowe, mode='w', format=tarfile.GNU_FORMAT) as t:
        for nazwa, dane, tryb in pliki:
            ti = tarfile.TarInfo('./' + nazwa if nazwa else '.')
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = 'root'
            ti.mtime = mtime
            ti.mode = tryb
            if dane is None:
                ti.type = tarfile.DIRTYPE
                t.addfile(ti)
            else:
                ti.size = len(dane)
                t.addfile(ti, io.BytesIO(dane))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode='wb', mtime=mtime) as g:
        g.write(surowe.getvalue())
    return out.getvalue()


def katalogi(sciezki):
    """Wszystkie katalogi nadrzedne, od korzenia."""
    k = set()
    for s in sciezki:
        czesci = s.split('/')[:-1]
        for i in range(1, len(czesci) + 1):
            k.add('/'.join(czesci[:i]))
    return sorted(k, key=lambda x: (x.count('/'), x))


def ar(czlonki, mtime):
    out = io.BytesIO()
    out.write(b'!<arch>\n')
    for nazwa, dane in czlonki:
        nag = '%-16s%-12d%-6d%-6d%-8o%-10d`\n' % (nazwa, mtime, 0, 0, 0o100644, len(dane))
        out.write(nag.encode('ascii'))
        out.write(dane)
        if len(dane) % 2:
            out.write(b'\n')
    return out.getvalue()


def ipk(katalog_ctl, dane, wersja, wyj, mtime):
    ctl = tekst(os.path.join(katalog_ctl, 'control')).replace(b'@WERSJA@', wersja.encode())
    m = re.search(br'^Package: (\S+)', ctl, re.M)
    a = re.search(br'^Architecture: (\S+)', ctl, re.M)
    wer = re.search(br'^Version: (\S+)', ctl, re.M).group(1).decode()
    rozmiar = sum(len(d) for _, d, _ in dane if d is not None)
    ctl = ctl.rstrip(b'\n') + b'\nInstalled-Size: %d\n' % rozmiar
    ctl_pliki = [('', None, 0o755), ('control', ctl, 0o644)]
    for skr in ('preinst', 'postinst', 'prerm', 'postrm'):
        p = os.path.join(katalog_ctl, skr)
        if os.path.exists(p):
            ctl_pliki.append((skr, tekst(p), 0o755))
    dane_pliki = [('', None, 0o755)] + [(k, None, 0o755) for k in katalogi([n for n, _, _ in dane])] + dane
    nazwa = '%s_%s_%s.ipk' % (m.group(1).decode(), wer, a.group(1).decode())
    pakiet = ar([('debian-binary', b'2.0\n'),
                 ('control.tar.gz', tar_gz(ctl_pliki, mtime)),
                 ('data.tar.gz', tar_gz(dane_pliki, mtime))], mtime)
    sciezka = os.path.join(wyj, nazwa)
    with open(sciezka, 'wb') as f:
        f.write(pakiet)
    print('%s  %d B  md5 %s' % (sciezka, len(pakiet), hashlib.md5(pakiet).hexdigest()))
    for n, d, _ in dane:
        if d is not None:
            print('    /%s  md5 %s' % (n, hashlib.md5(d).hexdigest()))
    return sciezka


def wersja_wtyczki():
    m = re.search(r"^WERSJA = '([^']+)'", tekst(os.path.join(WTYCZKA, 'plugin.py')).decode('utf-8'), re.M)
    return m.group(1)


def wersja_nbox_cec():
    m = re.search(r'^#define WERSJA "([^"]+)"', tekst(NBOX_CEC_C).decode('ascii'), re.M)
    return m.group(1)


def modul(sciezka):
    with open(sciezka, 'rb') as f:
        ko = f.read()
    if VERMAGIC not in ko:
        sys.exit('%s: brak "%s" - modul nie pod jadro nBoxow' % (sciezka, VERMAGIC.decode()))
    return ko


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nbox-ko', help='zbudowany nbox_cec.ko (sh4)')
    ap.add_argument('--ko', help='zbudowany cec_rx.ko (sh4)')
    ap.add_argument('--wyj', default=os.path.join(os.path.expanduser('~'), 'nbox_pakiety'))
    ap.add_argument('--mtime', type=int, default=int(time.time()))
    a = ap.parse_args()
    if not os.path.isdir(a.wyj):
        os.makedirs(a.wyj)
    if a.nbox_ko:
        k = os.path.join(PAKIETY, 'kernel-module-nbox-cec')
        ipk(k, [
            ('lib/modules/nbox_cec.ko', modul(a.nbox_ko), 0o644),
            ('etc/init.d/nbox_cec', tekst(os.path.join(k, 'nbox_cec.init')), 0o755),
        ], wersja_nbox_cec(), a.wyj, a.mtime)
    if a.ko:
        ipk(os.path.join(PAKIETY, 'kernel-module-cec-rx'), [
            ('lib/modules/cec_rx.ko', modul(a.ko), 0o644),
            ('etc/init.d/cec_rx', tekst(os.path.join(PAKIETY, 'kernel-module-cec-rx', 'cec_rx.init')), 0o755),
        ], '1.1', a.wyj, a.mtime)
    ipk(os.path.join(PAKIETY, 'enigma2-plugin-systemplugins-nboxcec'), [
        (CEL_WTYCZKI + '/' + n, tekst(os.path.join(WTYCZKA, n)), 0o644)
        for n in ('__init__.py', 'cec_core.py', 'plugin.py')
    ], wersja_wtyczki(), a.wyj, a.mtime)


if __name__ == '__main__':
    main()
