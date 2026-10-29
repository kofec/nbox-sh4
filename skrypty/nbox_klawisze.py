#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# nbox_klawisze.py - zapis klawiszy pilota, ktore odebral nBox. Sluchacz gniazda
# lircd (/var/run/lirc/lircd): lircd rozsyla kazdy rozpoznany klawisz do
# wszystkich podlaczonych klientow, wiec enigma2 dostaje go jak dotad - skrypt
# niczego nie wysyla i nie przechwytuje.
#
# Po co: lircd na nBoxie moze znac kilka pilotow naraz (np. RC-nBox(XMP)
# i pilota dekodera nc+ SagemCom-DSI87-NEW, gdy oba dekodery stoja na jednym
# pilocie) - linia pokazuje, ktorym pilotem wcisnieto klawisz i kiedy byl
# ostatni (timery bezczynnosci: nBox 2 h, nc+ ~4 h).
#
# Ograniczenia: tylko klawisze, ktore lircd rozpoznal (kod spoza
# /etc/lircd.conf nie przyjdzie wcale); w deep standby nic; czy inny dekoder
# tez odebral podczerwien - nie widac.
#
# Linia logu: data godzina up=<uptime> <klawisz> <pilot> [x<powtorzenia>]
# Powtorzenia trzymanego klawisza sklejane w jedna linie (x - ile ramek).
#
# Uzycie: python /root/nbox_klawisze.py [--stdin]
#   --stdin  linie w formacie lircd ze standardowego wejscia (test)
# Python 2.7 (GraterliaOS) i 3.

import os
import signal
import socket
import sys
import time

GNIAZDO = os.environ.get("GNIAZDO", "/var/run/lirc/lircd")
LOG = os.environ.get("LOG", "/tmp/nbox_klawisze.log")
LOG_MAX = int(os.environ.get("LOG_MAX", "5000"))
PIDF = os.environ.get("PIDF", "/tmp/nbox_klawisze.pid")
PONOW_CO = 10


def uptime():
    try:
        with open("/proc/uptime") as f:
            return f.read().split(".")[0]
    except IOError:
        return "?"


class Log(object):
    def __init__(self, sciezka, maks):
        self.sciezka = sciezka
        self.maks = maks
        self.linie = 0
        try:
            with open(sciezka) as f:
                self.linie = sum(1 for _ in f)
        except IOError:
            pass

    def pisz(self, tekst, czas=None, up=None):
        linia = "%s up=%s %s\n" % (czas or time.strftime("%Y-%m-%d %H:%M:%S"),
                                   up or uptime(), tekst)
        with open(self.sciezka, "a") as f:
            f.write(linia)
        self.linie += 1
        if self.linie >= self.maks:
            os.rename(self.sciezka, self.sciezka + ".1")
            self.linie = 0


class Klawisze(object):
    """Trzymany klawisz (ramki z licznikiem lircd > 0) = jedna linia z xN;
    kazde osobne wcisniecie (licznik 00) = nowa linia. Linia trafia do logu
    przy nastepnym klawiszu albo po 1 s ciszy, z czasem pierwszej ramki."""

    def __init__(self, log):
        self.log = log
        self.biezacy = None  # (klawisz, pilot, czas, uptime)
        self.ramek = 0

    def _wypisz(self):
        if self.biezacy is None:
            return
        klawisz, pilot, czas, up = self.biezacy
        dopisek = " x%d" % self.ramek if self.ramek > 1 else ""
        self.log.pisz("%s %s%s" % (klawisz, pilot, dopisek), czas, up)
        self.biezacy = None
        self.ramek = 0

    def linia(self, tekst):
        # "<kod hex> <powtorzenie hex> <klawisz> <pilot>"
        pola = tekst.split()
        if len(pola) < 4:
            return
        try:
            powt = int(pola[1], 16)
        except ValueError:
            return
        klawisz, pilot = pola[2], " ".join(pola[3:])
        if powt > 0 and self.biezacy is not None \
                and self.biezacy[0] == klawisz and self.biezacy[1] == pilot:
            self.ramek += 1
            return
        self._wypisz()
        self.biezacy = (klawisz, pilot, time.strftime("%Y-%m-%d %H:%M:%S"),
                        uptime())
        self.ramek = 1

    def cisza(self):
        self._wypisz()


def z_gniazda(log, kl):
    bez_polaczenia = False
    while True:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(GNIAZDO)
        except socket.error as e:
            if not bez_polaczenia:
                log.pisz("brak polaczenia z %s (%s) - ponawiam co %d s"
                         % (GNIAZDO, e, PONOW_CO))
                bez_polaczenia = True
            time.sleep(PONOW_CO)
            continue
        log.pisz("polaczono z %s" % GNIAZDO)
        bez_polaczenia = False
        # ramki powtorzen lircd co ~110 ms; 1 s ciszy = koniec trzymania
        s.settimeout(1.0)
        bufor = b""
        try:
            while True:
                try:
                    dane = s.recv(4096)
                except socket.timeout:
                    kl.cisza()
                    continue
                if not dane:
                    break
                bufor += dane
                while b"\n" in bufor:
                    wiersz, bufor = bufor.split(b"\n", 1)
                    kl.linia(wiersz.decode("ascii", "replace"))
        except socket.error as e:
            log.pisz("blad gniazda: %s" % e)
        finally:
            kl.cisza()
            s.close()
        log.pisz("lircd zamknal polaczenie - ponawiam")
        time.sleep(PONOW_CO)


def main():
    log = Log(LOG, LOG_MAX)
    kl = Klawisze(log)
    if "--stdin" in sys.argv[1:]:
        for wiersz in sys.stdin:
            if wiersz.strip() == "-":
                kl.cisza()
            else:
                kl.linia(wiersz)
        kl.cisza()
        return
    with open(PIDF, "w") as f:
        f.write("%d\n" % os.getpid())
    log.pisz("start (pid %d)" % os.getpid())
    # kill (TERM) -> finally: dopisz trzymany klawisz, skasuj wlasny PIDF
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        z_gniazda(log, kl)
    finally:
        kl.cisza()
        log.pisz("stop")
        try:
            with open(PIDF) as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(PIDF)
        except (IOError, OSError):
            pass


if __name__ == "__main__":
    main()
