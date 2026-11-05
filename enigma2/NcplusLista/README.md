# Lista kanałów z satelity (NcplusLista)

Wtyczka enigmy dla nBoxów z GraterliaOS (OpenPLi 4, Python 2.7). Raz na kilka
dni stroi wolny tuner na transponder nc+, czyta z satelity listę kanałów
operatora i:

- tworzy bukiet **„CANAL+ (satelita)”** w kolejności numerów nc+ (LCN), ze
  znacznikami bloków tematycznych,
- dopisuje do `lamedb` transpondery i kanały, których box nie zna,
- opcjonalnie aktualizuje w Twoich bukietach kanały, którym operator zmienił
  SID albo transponder.

Domyślnie działa w **trybie próbnym**: czyta satelitę i pisze raport, ale nie
zmienia żadnego pliku w `/etc/enigma2`.

*English summary at the end.*

## Skąd lista kanałów

Dekoder nc+ nie pobiera listy z internetu — bierze ją z tabel DVB nadawanych
na transponderach operatora (np. 10719 V na Hot Birdzie 13°E):

- **BAT** (PID `0x11`, tabela `0x4A`) — pakiety operatora z numeracją w
  deskryptorze LCN `0x83`: `0xC024` CANAL+ (tylko Hot Bird), `0xC023` (Hot Bird
  + Astra 19,2°), `0xC022` (bez 4K), `0x2020` (pełny), `0x2022` nc+ (stara
  numeracja). Na 13°E bukiety `0xC02x` i `0x2020` mają te same numery.
- **NIT other** — wszystkie transpondery sieci z parametrami (częstotliwość,
  polaryzacja, SR, DVB-S/S2, modulacja, FEC),
- **SDT other** — nazwy i typy usług.

Na transponderach innych nadawców (TVN, Polsat) tych tabel nie ma — tylko
NIT/SDT tego jednego transpondera. SDT other nc+ opisuje wyłącznie ofertę nc+,
więc kanałów spoza niej wtyczka nie sprawdza.

## Działanie

1. **Kiedy:** 10 min po starcie enigmy, potem co godzinę sprawdza, czy minęło
   „co ile dni” (domyślnie 7), czy zegar jest ustawiony i czy w ciągu 15 min nie
   zaczyna się nagranie. Ręcznie: żółty „Uruchom teraz” w menu.
2. **Tuner:** wolny slot DVB-S z 13,0°E (od ostatniego — przy dwóch tunerach
   zwykle B, więc oglądanie nie jest przerywane); `allocateRawChannel` nie
   odbierze tunera, który pracuje. Lock do 15 s, inaczej następny transponder
   (10719 V → 11278 V → 11411 H; parametry odświeżane z NIT).
3. **Odczyt:** `reserveDemux`, filtry sekcji na PID `0x10` i `0x11`
   ([odczyt.py](odczyt.py)), krok co 200 ms z `eTimer` — bez blokowania enigmy.
   Zwykle ~25 s.
4. **Przetwarzanie** (~10–25 s na STi7100) w osobnym wątku, tuner już zwolniony.
5. **Zapis** (poza trybem próbnym): kopia plików enigmy (`etc_enigma2_*.tgz`) do
   `ncpluslista/` na pierwszym zamontowanym z `/hdd`, `/media/hdd`, `/media/usb`,
   `/media/net/*` — 4 ostatnie; bez dysku i udziału na NAND `/root/ncpluslista`
   (2 kopie, tylko gdy zostaje ≥ 2 MB). Bez miejsca na kopię nie ma zapisu. Potem
   sprawdzenie, że pliki nie zmieniły się od odczytu, wszystkie pliki jako
   `*.ncpl_tmp`, `rename`, `reloadServicelist()` / `reloadBouquets()`.
   Zapisywane są `lamedb` i `lamedb5` (enigma tego obrazu prowadzi oba).
6. **Raport:** `/tmp/raport_ostatni.txt` i w katalogu kopii, log
   `/tmp/ncpluslista.log`; niebieski „Raport” w menu.

### Bukiet „CANAL+ (satelita)” i Twoje zmiany

Bukiet można edytować w enigmie (przestawiać, usuwać, dodawać kanały i
znaczniki). Wtyczka pamięta, co sama wpisała (`/etc/enigma2/ncpluslista.json`), i
przy aktualizacji:

- zostawia Twoją kolejność, Twoje kanały spoza nc+ i znaczniki,
- nie przywraca kanałów, które usunąłeś,
- nowe kanały wstawia za kanałem z najbliższym niższym numerem,
- kanałowi przeniesionemu przez operatora (nowy SID / transponder) podmienia
  odwołanie w tym samym miejscu (rozpoznanie: ref → nazwa → numer LCN),
- usuwa kanały, których operator już nie nadaje (są w raporcie),
- zmianę numeru tylko zgłasza w raporcie.

Zmiana nazwy i SID naraz jest nie do rozpoznania („zniknął” + „nowy”). Bez pliku
stanu bukiet powstaje od nowa wg numerów.

## Ustawienia

Ustawienia → System → **Lista kanałów z satelity**:

| opcja | domyślnie |
|---|---|
| Włączona | tak |
| Tryb próbny (tylko raport) | tak |
| Aktualizuj co | 7 dni |
| Lista operatora (BAT) | `0xC024` CANAL+ (Hot Bird) |
| Gdy jej nie ma — użyj zastępczej | tak (`0xC024` → `0xC023` → `0xC022` → `0x2020`) |
| Twórz bukiet CANAL+ (satelita) | tak; „nie” = tylko `lamedb` i (opcja niżej) inne bukiety |
| Kanał pod kilkoma numerami — wszystkie numery | tak (jak dekoder nc+) |
| Radio / radio w osobnym bukiecie | tak / nie (radio w kolejności LCN) |
| Znaczniki bloków tematycznych | tak |
| Pomiń kanały 4K | nie |
| Bukiet na liście bukietów | na górze (potem tam, gdzie go przestawisz); też „na końcu”, „zawsze na górze” |
| Aktualizuj parametry kanałów w pozostałych bukietach | nie — tylko raport |

„Aktualizuj parametry kanałów w pozostałych bukietach” zmienia tylko wpisy
**martwe** (na transponderze operatora nie ma już usługi o tym SID), dla których
operator nadaje kanał o tej samej nazwie gdzie indziej (przy kilku SID-ach —
najniższy numer). Zmienia tylko tę linię: pozycja, opis i końce linii zostają.

## Instalacja

Pakiet buduje [../../pakiety/zbuduj_ipk.py](../../pakiety/zbuduj_ipk.py)
(`enigma2-plugin-systemplugins-ncpluslista_<wersja>_all.ipk`), dalej jak przy
nBox CEC — sekcja *Instalacja na boxie* w [README](../../README.md#instalacja-na-boxie):

```sh
opkg install /tmp/enigma2-plugin-systemplugins-ncpluslista_*_all.ipk
wget -q -O - "http://127.0.0.1/web/powerstate?newstate=3"     # restart enigmy
```

Usunięcie: `opkg remove enigma2-plugin-systemplugins-ncpluslista`. Bukiet
„CANAL+ (satelita)” i `ncpluslista.json` zostają — to już Twoje dane.

## Bez enigmy

Logika ([si.py](si.py), [lamedb.py](lamedb.py), [budowa.py](budowa.py),
[scalanie.py](scalanie.py), [przebieg.py](przebieg.py)) działa w Pythonie 2.7 i 3
i nie potrzebuje enigmy. [offline.py](offline.py) robi pełny przebieg na kopii
`/etc/enigma2` i zrzucie tabel, nic nie zmieniając w kopii:

```sh
ssh root@ADRES_BOXA 'python - 90 wszystko' < skrypty/si_zbierz.py > si.json   # box na kanale nc+
python enigma2/NcplusLista/offline.py si.json KOPIA_ETC_ENIGMA2 WYNIK [--bat C024] [--popraw-inne]
```

[skrypty/si_zbierz.py](../../skrypty/si_zbierz.py) czyta tabele z bieżącego
transpondera (bez przestrajania), [skrypty/si_pidy.py](../../skrypty/si_pidy.py)
pokazuje PID-y transpondera i co w nich płynie,
[skrypty/si_porownaj.py](../../skrypty/si_porownaj.py) porównuje bukiet z tabelami.

## Ograniczenia

- Tylko satelita z konfiguracji tunerów (tu 13,0°E); usługi z Astry z BAT nc+ są
  pomijane.
- Kanały innych operatorów (np. pakiet Polsatu) nie są sprawdzane — wymagałoby to
  odczytu ich własnych tabel.
- Kanały, których karta nie odkoduje, trafiają na listę (wtyczka nie zna CAID-ów
  karty).

## English summary

An enigma2 plugin for nBox / GraterliaOS (OpenPLi 4, Python 2.7) that, every few
days, tunes a free tuner to an nc+ (CANAL+ Poland) transponder on Hot Bird 13°E,
reads NIT/SDT/BAT and builds a **"CANAL+ (satelita)"** bouquet in the operator's
LCN order (BAT `0xC024` by default, LCN descriptor `0x83`), adds missing
transponders and services to `lamedb` / `lamedb5`, and can optionally fix
channels moved to a new SID / transponder in your own bouquets. User edits of the
bouquet (order, deletions, own entries, markers) survive updates. Trial mode is on
by default (report only). Backups before every write; the core runs on a PC
(`offline.py`). Comments and UI are in Polish.
