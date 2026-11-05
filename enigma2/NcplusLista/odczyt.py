# -*- coding: utf-8 -*-
"""Odczyt sekcji SI z demuxa, bez blokowania pętli enigmy.

Filtry jak w si_zbierz.py w trybie "wszystko" (sprawdzone na nBoxie 2026-11-05
na 10719 V): jeden filtr bez maski na PID 0x10 (NIT) i 0x11 (SDT, BAT), tabele
odsiewane tutaj. Dwóch filtrów na jednym PID na demuxie STi nie sprawdzano.

Czytnik nie ma własnej pętli: wtyczka woła krok() z eTimer (co ~200 ms), krok()
czyta wszystko, co czeka w deskryptorach (O_NONBLOCK), i mówi, czy koniec.
"""
from __future__ import unicode_literals

import errno
import os
import struct
import time

SCT_FMT = str('=H16s16s16s2xII')                 # dmx_sct_filter_params, 60 B na 32 bit
DMX_STOP = (ord('o') << 8) | 42
DMX_SET_FILTER = (1 << 30) | (struct.calcsize(SCT_FMT) << 16) | (ord('o') << 8) | 43
DMX_SET_BUFFER_SIZE = (ord('o') << 8) | 45
DMX_CHECK_CRC, DMX_IMMEDIATE_START = 1, 4
PIDY = (0x10, 0x11)
TABELE = (0x40, 0x41, 0x42, 0x46, 0x4A)


def otworz_filtr(demux, pid):
    import fcntl
    fd = os.open(demux, os.O_RDWR | os.O_NONBLOCK)
    try:
        try:
            fcntl.ioctl(fd, DMX_SET_BUFFER_SIZE, 256 * 1024)
        except IOError:
            pass
        zero = b'\0' * 16
        p = struct.pack(SCT_FMT, pid, zero, zero, zero, 0, DMX_CHECK_CRC | DMX_IMMEDIATE_START)
        fcntl.ioctl(fd, DMX_SET_FILTER, p)
    except Exception:
        os.close(fd)
        raise
    return fd


def zamknij_filtr(fd):
    try:
        import fcntl
        fcntl.ioctl(fd, DMX_STOP)
    except Exception:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


class Czytnik(object):
    """Zbiera sekcje NIT/SDT/BAT. Koniec: wszystkie podtabele kompletne i przez
    `cisza` s nic nowego (nie wcześniej niż po `minimum` s), albo `limit` s."""

    def __init__(self, demux, minimum=20, cisza=15, limit=120, zegar=time.time,
                 otworz=otworz_filtr, zamknij=zamknij_filtr, czytaj=os.read):
        self.zegar = zegar
        self._zamknij = zamknij
        self._czytaj = czytaj
        self.minimum, self.cisza, self.limit = minimum, cisza, limit
        self.sekcje = {}        # (tid, ext, wersja, nr) -> bajty
        self.podtabele = {}     # (tid, ext, wersja) -> last_section_number
        self.start = self.zegar()
        self.ostatnia_nowa = self.start
        self.fds = []
        for pid in PIDY:
            self.fds.append(otworz(demux, pid))

    def krok(self):
        """-> True, gdy zbieranie skończone (wtedy deskryptory już zamknięte)."""
        for fd in self.fds:
            for _ in range(200):                    # ogranicznik na jeden krok
                try:
                    d = self._czytaj(fd, 4096)
                except OSError as e:
                    if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        break
                    continue                        # EOVERFLOW itp. - następna sekcja
                if not d:
                    break
                self._dodaj(bytearray(d))
        teraz = self.zegar()
        koniec = teraz - self.start >= self.limit or (
            teraz - self.start >= self.minimum and teraz - self.ostatnia_nowa >= self.cisza
            and self.kompletne())
        if koniec:
            self.zamknij()
        return koniec

    def _dodaj(self, d):
        if len(d) < 8 or d[0] not in TABELE:
            return
        tid, ext = d[0], (d[3] << 8) | d[4]
        ver, nr, last = (d[5] >> 1) & 0x1F, d[6], d[7]
        k = (tid, ext, ver, nr)
        if k not in self.sekcje:
            self.sekcje[k] = bytes(d)
            self.podtabele[(tid, ext, ver)] = last
            self.ostatnia_nowa = self.zegar()

    def kompletne(self):
        return bool(self.podtabele) and all(
            all((k[0], k[1], k[2], n) in self.sekcje for n in range(last + 1))
            for k, last in self.podtabele.items())

    def brakujace(self):
        return ['%02x/%04x/v%d/%d' % (k[0], k[1], k[2], n)
                for k, last in sorted(self.podtabele.items())
                for n in range(last + 1) if (k[0], k[1], k[2], n) not in self.sekcje]

    def ma_bat(self):
        return any(k[0] == 0x4A for k in self.podtabele)

    def wynik(self):
        return [self.sekcje[k] for k in sorted(self.sekcje)]

    def zamknij(self):
        for fd in self.fds:
            self._zamknij(fd)
        self.fds = []
