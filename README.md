# nbox-sh4: HDMI-CEC i collectd dla nBoxa ADB 5800 (GraterliaOS)

*English summary at the end.*

Zestaw do budowania własnych programów i modułów jądra dla dekoderów **nBox
ADB 5800 (BSLA / BSKA, STi7100, sh4)** z obrazem **GraterliaOS** (jądro
`2.6.32.61_stm24_0217`, enigma2 OpenPLi, Python 2.7, glibc 2.14.1).

W środku:

| Katalog | Co to jest |
|---|---|
| [sh4/Dockerfile](sh4/Dockerfile), [sh4/przygotuj_jadro.sh](sh4/przygotuj_jadro.sh) | toolchain STLinux 2.4 (gcc 4.8.4, tym samym zbudowano jądro Graterlii) w Dockerze i drzewo jądra gotowe do budowania modułów — `vermagic` zgodny z boxem |
| [sh4/nbox_cec](sh4/nbox_cec) | **moduł `nbox_cec`** — pełne HDMI-CEC na nBoxie: odbiór, ACK, odpowiedzi na zapytania TV, nadawanie z arbitrażem, klawisze pilota TV |
| [sh4/cec_rx](sh4/cec_rx) | moduł `cec_rx` — sam podsłuch linii CEC (nic nie nadaje) i logger |
| [sh4/cec_diag](sh4/cec_diag), [sh4/cec_rx_test](sh4/cec_rx_test) | moduły diagnostyczne, którymi szukaliśmy nóżki CEC (rejestry PIO, zbocza) |
| [enigma2/NBoxCEC](enigma2/NBoxCEC) | wtyczka enigmy **nBox CEC**: stan TV i wybrane wejście, budzenie / usypianie boxa wg TV, włączanie / wyłączanie TV wg boxa, pilot TV |
| [pakiety](pakiety) | pliki `control` / skrypty i [zbuduj_ipk.py](pakiety/zbuduj_ipk.py), który składa z tego pakiety `.ipk` dla opkg 0.2.4 |
| [sh4/collectd](sh4/collectd) | **collectd 5.12.0** na nBoxa (CPU, RAM, dyski, sieć) wysyłający statystyki do routera, np. OpenWrt z `luci-app-statistics` |

Działa od października 2026 na czterech nBoxach (BSLA i BSKA) z telewizorami
LG (starszy i webOS) oraz Sony BRAVIA (z soundbarem i bez).

## Dlaczego

Graterlia ma `cec_ctrl.ko` (pakiet `kernel-modules-cec-gos`, sterownik
`cec_adb_box` z [Duckbox-Developers/driver](https://github.com/Duckbox-Developers/driver/tree/master/cec_adb_box)),
ale on **tylko nadaje** — odbiór jest w źródle w `#if 0`, a `/proc/stb/hdmi/cec`
przy odczycie zwraca zawsze pusto. Enigma ma pełne CEC (`eHdmiCEC`,
`Components/HdmiCec.py`), tylko szuka `/dev/hdmi_cec`, którego na nBoxach nie
ma — a ogólny sterownik Duckboxa jest na sprzętowy blok CEC STx7105/7111,
którego STi7100 nie ma. Box nie wie więc, czy TV jest włączony i jakie wejście
pokazuje, a TV nie widzi boxa na liście źródeł.

## Jak to działa

- **Linia CEC to PIO 4.4** — ta sama nóżka, na której nadaje `cec_ctrl`, w
  trybie open-drain (bidir), więc rejestr wejścia pokazuje faktyczny stan linii.
  PIO 3.7, które sugeruje kod `cec_adb_box`, to nie CEC (na nim są tylko
  impulsy ~0,8 s przy przełączaniu TV).
- **Odbiór:** przerwanie GPIO na obu zboczach, czasy z zegara, dekoder bitów
  w [cec_rx_dekoder.h](sh4/cec_rx/cec_rx_dekoder.h) (testowany na PC na
  zboczach nagranych z boxów). Python z `/dev/mem` daje ~2000 próbek/s, a CEC
  potrzebuje ~10 000 — dlatego moduł jądra.
- **Nadawanie i ACK:** czasy z kanału **TMU2** procesora (jądro używa tylko
  TMU0 i TMU1, `HIGH_RES_TIMERS` nie ma, HZ 250). Uwaga: ST40 ignoruje zapis
  `TCNT2` przy działającym kanale — trzeba stop, zapis, start. Bezpiecznik co
  1 s puszcza nóżkę, gdyby zegar stanął.
- **Odpowiedzi** ([cec_protokol.h](sh4/nbox_cec/cec_protokol.h)): Give
  Physical Address, OSD Name „nBox”, Vendor ID, CEC Version, Power Status (z
  parametru `standby`, który ustawia wtyczka), Menu Request, Set Stream Path →
  Active Source; reszta Feature Abort. Adres logiczny 3 (Tuner 1), fizyczny z
  `cec_address` sterownika stmfb.
- **Ochrona:** ponad `BURZA` zboczy/s przerwanie wyłącza się do `rmmod`.

Interfejsy `nbox_cec`:

| Plik | |
|---|---|
| `/proc/cec_rx` | ostatnie ramki: `<nr> <epoch.ms> <nad>><odb> <bajt><+\|->…` (`+` = ACK), `?` bez EOM, `!n` błąd dekodera |
| `/proc/nbox_cec` | stan, liczniki, ostatnie zdarzenia; zapis hex (np. `echo 3004 >`) = nadaj ramkę |
| `/proc/nbox_cec_klawisze` | klawisze pilota TV: `44 <kod>` / `45`, odczyt zabiera, działa `poll()` |
| `/proc/stb/hdmi/cec` | zapis jak do `cec_ctrl` (zgodność z wtyczką Graterlii) |
| `/sys/module/nbox_cec/parameters/` | `ack`, `odpowiedzi`, `standby`, `adres_fiz`, `nazwa`, `vendor`, `adres_log`… — zmieniane w biegu |

`cec_rx` daje tylko `/proc/cec_rx` w tym samym formacie i może działać obok
`cec_ctrl`.

## Budowanie

Potrzebny Linux x86_64 z Dockerem. Wszystkie polecenia z katalogu repo.

```sh
# 1. toolchain (pobiera RPM-y z Duckbox-Developers/stlinux i sprawdza sha256)
docker build -t nbox-sh4:4.8.4 sh4

# 2. drzewo jadra (pobiera linux-sh4 i buildsystem Audionieka do build/,
#    naklada 27 latek, konfiguracja z sh4/config-graterlia-*, modules_prepare)
docker run --rm -v "$PWD":/work nbox-sh4:4.8.4 sh /work/sh4/przygotuj_jadro.sh

# 3. modul (tak samo cec_rx, cec_diag)
docker run --rm -u $(id -u):$(id -g) -v "$PWD":/work -w /work/sh4/nbox_cec nbox-sh4:4.8.4 \
    make -C /work/build/linux-2.6.32.61_stm24_0217 ARCH=sh CROSS_COMPILE=sh4-linux- \
    M=/work/sh4/nbox_cec modules

# 4. pakiety .ipk (Python 3; sprawdza vermagic modulow)
python3 pakiety/zbuduj_ipk.py --nbox-ko sh4/nbox_cec/nbox_cec.ko --wyj wynik
```

`przygotuj_jadro.sh` działa jako root w kontenerze, więc `build/` należy do
roota. Sprawdzian: `modinfo nbox_cec.ko` musi pokazać
`vermagic: 2.6.32.61_stm24_0217 preempt mod_unload SH4LE` — taki sam jak
`cec_ctrl.ko` z boxa.

Testy na PC (bez boxa):

```sh
cd sh4/cec_rx && gcc -O2 -Wall -o test_dekoder test_dekoder.c && ./test_dekoder
cd sh4/nbox_cec && gcc -O2 -Wall -I../cec_rx -o test_protokol test_protokol.c && ./test_protokol
python3 enigma2/test_cec_core.py
python3 enigma2/test_plugin_atrapy.py
```

Tym samym kontenerem da się budować zwykłe programy: `sh4-linux-gcc t.c` daje
ELF z `/lib/ld-linux.so.2` i symbolami glibc najwyżej `GLIBC_2.12`.

## Instalacja na boxie

Pakiety skopiować do `/tmp` (np. `scp -O`) i:

```sh
opkg install /tmp/enigma2-plugin-systemplugins-nboxcec_*_all.ipk
opkg remove kernel-modules-cec-gos       # cec_ctrl.ko; patrz niżej
opkg install /tmp/kernel-module-nbox-cec_*_adb5800xx.ipk
reboot
```

- `nbox_cec` zastępuje `cec_ctrl`. Gdy `cec_ctrl` jest jeszcze w pamięci
  (nie oddaje nóżki ani IRQ po `rmmod`), moduł działa z nim wspólnie — do
  restartu boxa. Po restarcie `/proc/nbox_cec` powinien pokazać `nozka nasza`.
- Jeśli jest zainstalowana wtyczka CEC Graterlii (`enigma2-plugin-hdmicec`),
  zależy od `kernel-modules-cec-gos`, a od niej na niektórych obrazach
  `graterlia-e2gui` — wtedy `opkg remove --force-depends kernel-modules-cec-gos`
  (znika tylko `cec_ctrl.ko`). Wtyczki Graterlii nie włączać razem z nBox CEC.
- Wycofanie: `opkg remove kernel-module-nbox-cec`,
  `opkg install kernel-modules-cec-gos` z feedu Graterlii, restart.
- Skrypty init przez `chkconfig` (`S39`: po `gstm`, przed enigmą).

Wtyczka: **Menu → Ustawienia → System → nBox CEC**. Domyślnie wyłączona,
wszystkie reakcje „nic” — sama instalacja niczego nie zmienia. Ustawia się
profil TV (jak rozpoznać, że TV działa), reakcje boxa na TV (obudź, gdy TV
wybierze wejście nBoxa / uśpij po N s od wyłączenia TV lub przełączenia na
inne wejście) i TV na box (włącz i przełącz wejście przy budzeniu, wyłącz przy
usypianiu), pilot TV. Log: `/tmp/nboxcec.log`.

## Zachowanie telewizorów

Z podsłuchu (`0>F` = TV do wszystkich):

| TV | włączenie | w trakcie | wyłączenie | standby |
|---|---|---|---|---|
| LG plazma 50PJ250 | — | odpytywanie `0>1…0>B` + `0>F 87` | `0>F 36` | cisza |
| LG webOS | `0>F 84`, `80`, `82` | odpytywanie `0>1…0>B` co ~15 s | `0>F 36` | **tylko** `0>F 87` co 10 s |
| Sony + soundbar HT-A3000 | `0>F 84`, `87`, `82`, audio `70`/`72` | `0>4`/`0>5 8f` co 60 s | `0>F 36`, soundbar jeszcze ~65 s | cisza |
| Sony BRAVIA 8 | — | odpytywanie `0>1…0>E` co 15 s | — | cisza |
| Samsung LE40C650 | ACK na ramki, brak odpowiedzi | | | (Anynet+ wyłączony?) |

Stąd profile w wtyczce: `zdarzenia` (tylko włączenie / Standby),
`odpytywanie` (LG webOS, który w standby nadal nadaje), `cisza` (cokolwiek od
TV = działa). Sony przekazuje z pilota tylko strzałki i OK (`44 00…04`),
cyfr i kanałów nie; głośność idzie do soundbara.

## collectd

collectd 5.12.0 — ta sama wersja i łatki co OpenWrt 19.07 (140 FQDNLookup,
300, 320: skok zegara po NTP — nBoxy startują z datą 2000-01-01), bez rrdtool:
box tylko wysyła, RRD powstają na routerze. Pluginy: cpu, df, disk, exec,
interface, load, memory, network, syslog, table, uptime. Binarka 167 KB.

```sh
docker run --rm -u $(id -u):$(id -g) -v "$PWD":/work nbox-sh4:4.8.4 sh /work/sh4/collectd/zbuduj_collectd.sh
docker run --rm -u $(id -u):$(id -g) -v "$PWD":/work nbox-sh4:4.8.4 sh /work/sh4/collectd/zrob_ipk.sh
```

Na boxie `opkg install /tmp/collectd-nbox_*_sh4.ipk`, potem w
`/etc/collectd.conf` **`Hostname`** (wszystkie boxy mają `GraterliaOS`; póki
jest `ZMIEN_MNIE`, init nie startuje) i `Server` (adres routera z collectd,
port 25826), `/etc/init.d/collectd start`. Plugin `table` czyta temperaturę
dysku z `/tmp/collectd_nbox.tab` (`sda 45`) — pisze ją
[nbox_monitor.sh](https://github.com/kofec/Domoticz-Enigma2/blob/master/nbox/nbox_monitor.sh),
bez niego plik zostaje pusty.

## Skąd co jest

- Toolchain: RPM-y STLinux 2.4 z [Duckbox-Developers/stlinux](https://github.com/Duckbox-Developers/stlinux).
- Jądro: [Duckbox-Developers/linux-sh4-2.6.32.71](https://github.com/Duckbox-Developers/linux-sh4-2.6.32.71)
  (gałąź `stmicro`, `b43f8252`) + łatki `COMMON_PATCHES_24` i
  `ADB_BOX_PATCHES_24` z [Audioniek/buildsystem](https://github.com/Audioniek/buildsystem).
  Build bez zmian daje obraz o 739 B mniejszy niż ten na boxie — drzewo
  praktycznie to samo co Graterlii.
- Wiedza o `cec_adb_box`: [Duckbox-Developers/driver](https://github.com/Duckbox-Developers/driver),
  [Audioniek/driver](https://github.com/Audioniek/driver).
- collectd: [collectd/collectd](https://github.com/collectd/collectd), łatki z
  [openwrt/packages](https://github.com/openwrt/packages/tree/openwrt-19.07/utils/collectd/patches).

Moduły `nbox_cec`, `cec_rx`, wtyczka i skrypty są napisane od nowa; komentarze
w kodzie są po polsku.

## Licencja

GPL-2.0 ([LICENSE](LICENSE)). Łatki collectd z OpenWrt — na licencji collectd
(MIT / GPL-2.0).

---

## English summary

Build kit for **nBox ADB 5800** set-top boxes (STi7100, sh4) running
**GraterliaOS** (kernel 2.6.32.61_stm24_0217):

- a Docker image with the STLinux 2.4 toolchain (gcc 4.8.4) and a script that
  prepares a matching kernel tree, so out-of-tree modules load on the stock
  image (`vermagic 2.6.32.61_stm24_0217 preempt mod_unload SH4LE`);
- **`nbox_cec`**, a kernel module that adds full HDMI-CEC to the box — the stock
  `cec_ctrl` (`cec_adb_box`) can only transmit. CEC is on PIO 4.4
  (open-drain); receive uses a both-edge GPIO interrupt, transmit and ACK use
  the CPU's spare TMU2 channel. It answers TV queries (OSD name, physical
  address, power status), forwards TV remote keys, and exposes `/proc/cec_rx`,
  `/proc/nbox_cec`, `/proc/nbox_cec_klawisze` and `/proc/stb/hdmi/cec`;
- **nBox CEC**, an enigma2 plugin that wakes / puts the box to standby following
  the TV and switches the TV on / off following the box;
- **collectd 5.12.0** for the box, sending stats to a router's collectd.

Build steps are in the *Budowanie* section above; the commands work as they
are. Comments in the code are in Polish.
