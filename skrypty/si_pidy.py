# -*- coding: utf-8 -*-
# Mapa PID-ów transpondera, na którym stoi enigma2: PAT -> PMT wszystkich usług,
# potem przez chwilę podsłuch PID-ów z danymi (stream_type 0x05/0x0B/0x0C/0x0D i >= 0x80)
# - które table_id tam płyną i ile. NIE przestraja tunera, niczego nie zapisuje na boxie.
#
#   ssh root@ADRES_BOXA 'python - 30' < si_pidy.py > pidy.json
#
# Argument: ile sekund słuchać PID-ów z danymi (domyślnie 30).
import os, sys, fcntl, select, struct, binascii, time, json

DEMUX = '/dev/dvb/adapter0/demux0'
SLUCHAJ = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
SCT_FMT = '=H16s16s16s2xII'
DMX_STOP = (ord('o') << 8) | 42
DMX_SET_FILTER = (1 << 30) | (struct.calcsize(SCT_FMT) << 16) | (ord('o') << 8) | 43
DMX_SET_BUFFER_SIZE = (ord('o') << 8) | 45
DANE = (0x05, 0x0B, 0x0C, 0x0D)
NIE_DANE = (0x81, 0x87)  # AC-3 / E-AC-3 w "user private"


def otworz(pid, tid=0, mask=0, ext=None):
    fd = os.open(DEMUX, os.O_RDWR | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, DMX_SET_BUFFER_SIZE, 128 * 1024)
    except IOError:
        pass
    f = [tid] + [0] * 15
    m = [mask] + [0] * 15
    if ext is not None:  # filter[1..2] = table_id_extension (bajty 3-4 sekcji)
        f[1], f[2], m[1], m[2] = ext >> 8, ext & 0xFF, 0xFF, 0xFF
    p = struct.pack(SCT_FMT, pid, ''.join(map(chr, f)), ''.join(map(chr, m)), '\0' * 16, 0, 1 | 4)
    fcntl.ioctl(fd, DMX_SET_FILTER, p)
    return fd


def zamknij(fd):
    try:
        fcntl.ioctl(fd, DMX_STOP)
    except IOError:
        pass
    os.close(fd)


def czytaj_po_jednej(zadania, limit):
    """zadania: {klucz: (pid, tid, ext)} -> {klucz: sekcja}; po 8 filtrów naraz."""
    wynik, klucze = {}, list(zadania)
    while klucze:
        partia, klucze = klucze[:8], klucze[8:]
        fds = {}
        for k in partia:
            pid, tid, ext = zadania[k]
            fds[otworz(pid, tid, 0xFF, ext)] = k
        koniec = time.time() + limit
        while fds and time.time() < koniec:
            r, _, _ = select.select(list(fds), [], [], 0.5)
            for fd in r:
                try:
                    d = os.read(fd, 4096)
                except OSError:
                    continue
                wynik[fds.pop(fd)] = d
                zamknij(fd)
        for fd in fds:
            zamknij(fd)
    return wynik


def main():
    pat = czytaj_po_jednej({'pat': (0x00, 0x00, None)}, 5).get('pat')
    if not pat:
        json.dump({'blad': 'brak PAT - tuner nie pracuje?'}, sys.stdout)
        return
    tsid = (ord(pat[3]) << 8) | ord(pat[4])
    prog = {}
    for i in range(8, len(pat) - 4, 4):
        nr = (ord(pat[i]) << 8) | ord(pat[i + 1])
        pid = ((ord(pat[i + 2]) & 0x1F) << 8) | ord(pat[i + 3])
        if nr:
            prog[nr] = pid
    pmt = czytaj_po_jednej(dict((sid, (pid, 0x02, sid)) for sid, pid in prog.items()), 3)
    uslugi, dane = {}, {}
    for sid, d in pmt.items():
        pil = ((ord(d[10]) & 0x0F) << 8) | ord(d[11])
        i, es = 12 + pil, []
        while i + 5 <= len(d) - 4:
            st = ord(d[i])
            pid = ((ord(d[i + 1]) & 0x1F) << 8) | ord(d[i + 2])
            n = ((ord(d[i + 3]) & 0x0F) << 8) | ord(d[i + 4])
            es.append([st, pid, binascii.hexlify(d[i + 5:i + 5 + n])])
            if st in DANE or (st >= 0x80 and st not in NIE_DANE):
                dane.setdefault(pid, []).append(sid)
            i += 5 + n
        uslugi[sid] = {'pmt_pid': prog[sid], 'opis': binascii.hexlify(d[12:12 + pil]), 'es': es}
    # podsłuch PID-ów z danymi
    fds, stat = {}, {}
    for pid in sorted(dane)[:24]:
        try:
            fds[otworz(pid)] = pid
        except (IOError, OSError) as e:
            stat[pid] = {'blad': str(e)}
    koniec = time.time() + SLUCHAJ
    while fds and time.time() < koniec:
        r, _, _ = select.select(list(fds), [], [], 0.5)
        for fd in r:
            try:
                d = os.read(fd, 4096)
            except OSError:
                continue
            s = stat.setdefault(fds[fd], {})
            t = s.setdefault('%02x' % ord(d[0]), {'ile': 0, 'ext': [], 'przyklad': []})
            t['ile'] += 1
            ext = '%04x' % ((ord(d[3]) << 8) | ord(d[4])) if len(d) > 4 else ''
            if ext not in t['ext'] and len(t['ext']) < 40:
                t['ext'].append(ext)
            if len(t['przyklad']) < 2:
                t['przyklad'].append(binascii.hexlify(d[:512]))
    for fd in fds:
        zamknij(fd)
    json.dump({'czas': time.strftime('%Y-%m-%d %H:%M:%S'), 'tsid': tsid,
               'pat': prog, 'pmt_brak': sorted(set(prog) - set(pmt)),
               'uslugi': uslugi, 'dane': dict((p, s) for p, s in dane.items()),
               'podsluch': stat}, sys.stdout)

main()
