# EPGRefresh dla GraterliaOS

Wtyczka **EPGRefresh** z [OpenPLi/enigma2-plugins](https://github.com/OpenPLi/enigma2-plugins/tree/479eeb18de51ebe344a139cbcfa46ec876585663/epgrefresh),
gałąź `master` (ostatnia z Pythonem 2), commit `479eeb1` z 2024-11-14, wersja
`1.5-git` (OpenPLi, dima73). Pliki `.py`, `mphelp.xml`, `maintainer.info`,
`plugin.png` i `LICENSE` są **bez zmian** względem upstreamu.

Pakiet: `enigma2-plugin-extensions-epgrefresh` (`pakiety/zbuduj_ipk.py`), instaluje
się do `/usr/lib/enigma2/python/Plugins/Extensions/EPGRefresh`.

## Licencja

EPGRefresh **nie jest na GPL** jak reszta tego repozytorium: Creative Commons
BY-NC-SA 3.0 (plik [LICENSE](LICENSE)). Wolno go zmieniać i rozpowszechniać
niekomercyjnie, z zachowaniem licencji.

## Co robi

W ustalonych godzinach (domyślnie 20:15–06:30), gdy box jest w standby,
przełącza po kolei wybrane kanały / bukiety i czeka na każdym (domyślnie
120 s), żeby enigma zebrała EPG. Potem może zapisać cache EPG na dysk i
uśpić / wyłączyć box. Lista kanałów: `/etc/enigma2/epgrefresh.xml` (edytor
w ustawieniach wtyczki albo „dodaj do EPGRefresh” w menu kanału).

**Po instalacji jest wyłączona** (`config.plugins.epgrefresh.enabled = False`)
i bez listy kanałów — nic nie robi, dopóki się jej nie skonfiguruje.

## Sprawdzone pod Graterlię (bez uruchomienia na boxie)

- składnia wszystkich plików pod gramatyką Pythona 2.7 (parso 0.7.1);
- każda nazwa importowana z enigmy (`Components`, `Screens`, `Tools`,
  `enigma`) jest w bajtkodzie GraterliaOS, m.in. `ConfigSelectionNumber`,
  `SetupSummary`, `stringToXML`, `eEPGCache.save/load/setCacheFile`,
  `eDVBLocalTimeHandler`; `config.misc.epgcache_filename` definiuje
  `mytest.py` (domyślnie `/hdd/epg.dat`);
- grafiki ze skórek (`skin_default/buttons/*.png`, `div-h.png`) są w obrazie;
- MPHelp, AutoTimer, SeriesPlugin i stary WebInterface są importowane
  w `try` — bez nich znika tylko pomoc i współpraca z AutoTimerem.

Brak polskiego tłumaczenia (upstream ma 16 języków, bez `pl`) — menu po
angielsku.

## Na co uważać na nBoxach

- Odświeżanie przełącza kanały w standby — oscam dostaje ECM z kolejnych
  kanałów, a `nbox_monitor` może to widzieć jako zmiany kanału.
- „Po odświeżeniu: standby / wyłącz” (`afterevent`) i budzenie boxa
  (`wakeup`) wchodzą w drogę wtyczce nBox CEC (box śpi i budzi się z TV)
  — przy CEC zostawić wyłączone.
- Cache EPG na `/hdd` — bez dysku zmienić ścieżkę w „Manual EPG”, NAND jest
  prawie pełny.
