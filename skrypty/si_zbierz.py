# -*- coding: utf-8 -*-
# Zbiera surowe sekcje SI (NIT, SDT, BAT) z demuxa nBoxa, NIE przestraja tunera.
# Czyta to, co nadaje transponder, na którym enigma2 aktualnie stoi.
# Python 2.7 na boxie, bez zapisu plików: wynik (JSON) idzie na stdout.
#
#   ssh root@ADRES_BOXA 'python - 60' < si_zbierz.py > si.json
#
# Argument: maksymalny czas zbierania w sekundach (domyślnie 60).
# Parsowanie i porównanie robi si_porownaj.py po stronie komputera.
import os, sys, fcntl, select, struct, binascii, time, json

DEMUX = '/dev/dvb/adapter0/demux0'
LIMIT = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
# "wszystko": jeden filtr na PID, każda tabela, bez wcześniejszego końca
WSZYSTKO = len(sys.argv) > 2 and sys.argv[2] == 'wszystko'

# linux/dvb/dmx.h: struct dmx_sct_filter_params = u16 pid; u8 filter[16], mask[16], mode[16];
# (2 B wyrównania) u32 timeout; u32 flags  -> 60 B na 32-bit
SCT_FMT = '=H16s16s16s2xII'
SCT_SIZE = struct.calcsize(SCT_FMT)
def _IOW(t, nr, size): return (1 << 30) | (size << 16) | (ord(t) << 8) | nr
DMX_START = (ord('o') << 8) | 41
DMX_STOP = (ord('o') << 8) | 42
DMX_SET_FILTER = _IOW('o', 43, SCT_SIZE)
DMX_SET_BUFFER_SIZE = (ord('o') << 8) | 45
DMX_CHECK_CRC, DMX_IMMEDIATE_START = 1, 4

# (pid, table_id, maska table_id)
FILTRY = [
    (0x10, 0x40, 0xFE),   # NIT actual 0x40 + other 0x41
    (0x11, 0x42, 0xFB),   # SDT actual 0x42 + other 0x46
    (0x11, 0x4A, 0xFF),   # BAT
]
if WSZYSTKO:
    FILTRY = [(0x10, 0x00, 0x00), (0x11, 0x00, 0x00)]

def otworz(pid, tid, mask):
    fd = os.open(DEMUX, os.O_RDWR | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, DMX_SET_BUFFER_SIZE, 256 * 1024)
    except IOError:
        pass
    f = chr(tid) + '\0' * 15
    m = chr(mask) + '\0' * 15
    p = struct.pack(SCT_FMT, pid, f, m, '\0' * 16, 0, DMX_CHECK_CRC | DMX_IMMEDIATE_START)
    fcntl.ioctl(fd, DMX_SET_FILTER, p)
    return fd

def main():
    fds = {}
    for pid, tid, mask in FILTRY:
        fds[otworz(pid, tid, mask)] = (pid, tid)
    sekcje = {}      # (tid, ext, ver, nr) -> hex
    podtabele = {}   # (tid, ext, ver) -> last_section_number
    start = time.time()
    ostatnia_nowa = start
    try:
        while True:
            teraz = time.time()
            if teraz - start > LIMIT:
                break
            # pełne podtabele i 15 s bez nowej sekcji = koniec
            if not WSZYSTKO and podtabele and teraz - ostatnia_nowa > 15:
                kompletne = all(
                    all((k[0], k[1], k[2], n) in sekcje for n in range(last + 1))
                    for k, last in podtabele.items())
                if kompletne:
                    break
            r, _, _ = select.select(list(fds), [], [], 1.0)
            for fd in r:
                try:
                    d = os.read(fd, 4096)
                except OSError:
                    continue  # przepełnienie bufora - następna sekcja przyjdzie
                if len(d) < 8:
                    continue
                tid = ord(d[0])
                ext = (ord(d[3]) << 8) | ord(d[4])
                ver = (ord(d[5]) >> 1) & 0x1F
                nr, last = ord(d[6]), ord(d[7])
                k = (tid, ext, ver, nr)
                if k not in sekcje:
                    sekcje[k] = binascii.hexlify(d)
                    podtabele[(tid, ext, ver)] = last
                    ostatnia_nowa = time.time()
    finally:
        for fd in fds:
            try:
                fcntl.ioctl(fd, DMX_STOP)
            except IOError:
                pass
            os.close(fd)
    brak = []
    for k, last in sorted(podtabele.items()):
        for n in range(last + 1):
            if (k[0], k[1], k[2], n) not in sekcje:
                brak.append('%02x/%04x/v%d/%d' % (k[0], k[1], k[2], n))
    json.dump({
        'czas': time.strftime('%Y-%m-%d %H:%M:%S'),
        'sekund': round(time.time() - start, 1),
        'brakujace': brak,
        'sekcje': [sekcje[k] for k in sorted(sekcje)],
    }, sys.stdout)

main()
