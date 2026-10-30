# GraterliaOS na nBoxie ADB 5800 — notatki

Rzeczy ustalone w 2026 r. przy pracy z pięcioma nBoxami (ADB 5800SX, BSLA i BSKA).
Większość nie jest nigdzie opisana, a kosztowała po kilka godzin szukania.

## System

- STi7100 (ST40, sh4), 98 MB RAM, jądro `2.6.32.61_stm24_0217` z `preempt`.
- busybox 1.28, Python 2.7 (`/usr/bin/python`), glibc 2.14.1, opkg 0.2.4,
  skrypty init przez `chkconfig`.
- rootfs na NAND (~60 MB) bywa zapełniony w 89–96%. Większe rzeczy trzymaj
  na `/hdd` albo w `/tmp` (RAM).
- `load average` nie znaczy tu nic: stale ~4 (a bywa ~15), bo w stanie D
  siedzą wątki jądra sterowników STi (`Player_Aud_*`, `Interocitor_*`,
  `pti_task`…). Obciążenie liczy się z `/proc/stat`.

## Dostęp

- dropbear 2018.76: klucz hosta tylko `ssh-rsa`, kluczy ed25519 nie zna.
  Z nowszego OpenSSH:
  `ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -i ~/.ssh/id_rsa root@<box>`.
- `scp` z nowego OpenSSH (domyślnie SFTP) nie działa — dropbear nie ma `sftp-server`.
  Pliki idą przez `cat`, a przy okazji bez CR z checkoutu na Windowsie:
  `tr -d '\r' < plik | ssh root@<box> 'cat > /root/plik'`.
- Skrypt można sprawdzić bez wgrywania: `tr -d '\r' < skrypt.sh | ssh root@<box> 'sh -s -- --opcje'`.
- Wgrywanie i start w tle to **osobne** wywołania `ssh`. W jednym łańcuchu
  `cat > plik && nohup … &` cały łańcuch idzie w tło ze stdin z `/dev/null`
  i plik zostaje pusty.
- W sesji ssh `PATH` nie ma `/sbin` ani `/usr/sbin`: `hdparm` tylko jako
  `/sbin/hdparm`, `smartctl` jako `/usr/sbin/smartctl`, `ethtool` jako
  `/sbin/ethtool`; `ip` jako `busybox ip`.

## busybox

- awk: brak `^` jako potęgi, a `nazwa (` (spacja przed nawiasem) to wywołanie
  funkcji — oba wywalają cały program. `awk -v` zjada backslashe.
- `od` nie zna `-A` (kodowanie URL: `hexdump`).
- `nohup` i `setsid` są.

## Start i wyłączanie

- `/etc/rc.d/rc5.d`: `S19ghdparm`, `S24mountall`, `S32network`, `S34ntpd`,
  `S56autofs`, `S82softcam`, `S91rc.local`, `S92gui` (enigma2).
- `/etc/init.d/rc` uruchamia skrypty **bezpośrednio** — przez `sh` idą tylko
  nazwy kończące się na `.sh`. `/etc/rc.local` bez bitu `x` po prostu się
  nie wykona i nikt tego nie zgłosi. Po każdej podmianie `chmod 755 /etc/rc.local`.
  (`/etc/sysconfig/rc.local` to tylko wzór.)
- Wyłączenie: enigma2 kończy się kodem 1, `/usr/bin/startopenpli` robi
  `init 0`, potem `K*` z `rc0.d`: `K08gui` (enigma), `K18softcam` (oscam,
  do ~80 s), `S20sendsigs` (`killall5 -15`), `S40umountfs`. Własny demon,
  który ma zniknąć przed enigmą i zwolnić `/hdd`, potrzebuje skryptu init
  i dowiązań `K05…` w `rc0.d` i `rc6.d`.
- Własne usługi: skrypt w `/etc/init.d/` z nagłówkiem `# chkconfig: 5 NN MM`
  i `chkconfig --add`; zobacz init w [pakiety](../pakiety).

## Zegar

- Box startuje z datą **2000-01-01**, a NTP w obrazie nie działało nigdy:
  `/etc/init.d/ntpd` (i `/etc/cron/daily/ntpdate`) przed `ntpdate` pingują
  martwy `212.77.100.101` i bez odpowiedzi nie synchronizują. Zegar ustawia
  dopiero enigma2 z transpondera.
- Skutek dla oscama: startuje w 2000 r., uczy się cyklu ECM równego 26 latom
  i odrzuca ECM aż do zmiany kanału. Poprawki: żywy adres w `ntpd`, `ntpdate`
  na początku `oscam_start()` w `/etc/init.d/softcam` i w `rc.local`
  ```sh
  [ $(date +%Y) -lt 2020 ] && ( while [ $(date +%Y) -lt 2020 ]; do sleep 5; done; sleep 5; /etc/init.d/softcam restart ) &
  ```
- Pliki i logi z datą `20000101` to rzeczy zapisane przed ustawieniem zegara.
  collectd z tego repo ma łatkę OpenWrt na skok czasu po starcie.

## Dysk

- Po starcie dysk potrafi się kręcić (`hdparm -C`: `active/idle`), a przez
  kilkanaście minut nie odpowiadać na odczyt: `mount` daje
  `No such device or address`, `/proc/diskstats` zero operacji.
  Zobacz [skrypty/mount_hdd.sh](../skrypty/mount_hdd.sh).
- `hdparm -S 60` wykonany, gdy dysk jeszcze nie odpowiada, **nie ustawia**
  licznika usypiania — dysk kręci się bez końca (było 56 °C i SMART 190
  `FAILING_NOW`). Trzeba go powtórzyć po udanym montowaniu.
- `smartctl -n standby -A` nie budzi śpiącego dysku (kończy się `exit(2)`),
  `hdparm -H` budzi. `df /hdd` nie budzi. `drivetemp` jest od jądra 5.6,
  `hddtemp` nie ma — temperatura tylko ze SMART-u. Nie każdy obraz ma `smartctl`.

## Wentylator

- `/proc/stb/fan/fan_ctrl` (PWM 0–255) ustawia tylko firmware przy starcie
  (`gmodules_init`) z `/etc/enigma2/settings`: `config.fans.0.pwm` i
  `config.fans.0.pwm_standby`. Chłodzenie idzie za stanem boxa, nie za
  temperaturą — innego czujnika niż dysk box nie ma (`/proc/stb/fp` bez
  temperatury).
- Rampa wg temperatury dysku (bez budzenia go, z histerezą):
  `FAN=1` w [nbox_monitor.sh](https://github.com/kofec/Domoticz-Enigma2/tree/master/nbox).

## Enigma2 i OpenWebif

- OpenWebif na `:80` bez hasła: `/web/powerstate?newstate=` — 5 standby,
  4 obudzenie, 2 reboot, 3 restart enigmy, 1 „deep standby”. nBox nie ma
  prawdziwego deep standby: `newstate=1` to shutdown systemu, po którym box
  jeszcze chwilę odpowiada na ping. Dobre przed odcięciem zasilania przekaźnikiem.
- `/api/statusinfo` (`inStandby`), `/api/signal`. Stan standby widać też
  w `/sys/class/stmcoredisplay/hdmi0.0/tmds_status` (`Stopped`).
- Pingwinek (Tux) na ekranie to spinner enigmy
  (`/usr/share/enigma2/skin_default/spinner` → `spinner_graterlia`): główny
  wątek nie wraca do pętli zdarzeń. Sam w sobie nie znaczy, że CPU jest na 100%.
- Piloty: `lircd` na `/var/run/lirc/lircd` rozsyła rozpoznane klawisze
  wszystkim klientom — można słuchać obok enigmy
  ([skrypty/nbox_klawisze.py](../skrypty/nbox_klawisze.py)).

## dmesg

Jądro Graterlii ma `CONFIG_PRINTK=n`: `dmesg` jest puste, a komunikatów nie
przywrócą nowe moduły, bo brakuje samego `printk` w jądrze. Potrzebne jest nowe
jądro, a moduły z obrazu (player2, stmdvb…) ładują się na nim bez przebudowy
(ten sam `vermagic`, bez `MODVERSIONS`). Same pozostają nieme, bo ich wywołania
`printk` wycięto przy kompilacji: o dekodowaniu obrazu `dmesg` nic nie powie.

Budowanie: [sh4/zbuduj_jadro_printk.sh](../sh4/zbuduj_jadro_printk.sh) (polecenia
w nagłówku), nagłówek uImage dopisuje [sh4/mkimage_sh4.py](../sh4/mkimage_sh4.py).
Kosztuje 320 kB RAM-u (`MemTotal` 98 460 → 98 140 kB), reszta zajętości bez zmian.

Plik płyty z łatek Audionieka **nie jest** tym z Graterlii i bez
[sh4/latki/graterlia_zgodnosc.patch](../sh4/latki/graterlia_zgodnosc.patch) jest
groźny: zamienia `root` z u-boota na UBI, rejestruje NOR z u-bootem jako `mtd0`
(skrypty Graterlii piszące do `/dev/mtd0` skasowałyby u-boota) i inaczej dzieli
pamięć BPA2. Mimo łatki to jądro **nie widzi NAND** (`/proc/mtd` pusty, w konfiguracji
Graterlii nie ma sterownika `stm_nand_emi`, którego używa ten plik płyty), więc
nadaje się tylko do startu z pendrive'a. NAND jest wtedy bezpieczny, ale backup
i flashowanie NAND z tego systemu nie zadziałają.

Pendrive: u-boot czyta ext2/ext3 tylko z inode'ami 128 B, a `mke2fs` z boxa
domyślnie daje 256, więc trzeba podać to wprost. Kopia działającego systemu z NAND,
z jądrem wgranym wcześniej do `/tmp/uImage` (`sdb1` to przykład, **sprawdź
najpierw `lsblk`**: format kasuje partycję):

```sh
mkfs.ext3 -I 128 -b 4096 -L Graterlia1 /dev/sdb1
mkdir -p /tmp/nand /tmp/usb
mount -o bind / /tmp/nand
mount -t ext3 /dev/sdb1 /tmp/usb
cd /tmp/nand && tar cf - . | tar xf - -C /tmp/usb
cp /tmp/uImage /tmp/usb/boot/uImage-printk
rm /tmp/usb/boot/uImage && ln -s uImage-printk /tmp/usb/boot/uImage
cd / && sync && umount /tmp/usb /tmp/nand
```

Kopia przez `bind` zabiera też `/dev` z NAND, którego zwykły `tar` z `/` by nie
ruszył. Start: wpis USB w menu u-boota (`ext2load usb 0:N a5000000 /boot/uImage`).
W `/proc/cmdline` wpis USB na naszym boxie podaje już `root=/dev/sdb1`, a jądro
zbudowane z `ROOT=` wymusza to samo niezależnie od u-boota. Gdy jądro stanie:
wyjąć pendrive i odciąć prąd, box wraca na NAND.

Sprawdzone na jednym boxie: start z USB, oba tunery, enigma2, oscam, powrót po
odcięciu prądu.

## HDMI i CEC

- `/sys/class/stmcoredisplay/hdmi0.0/hotplug` (`y`/`n`) działa także w
  standby boxa (5 V na HDMI zostaje). Sterownik nie wysyła ueventu, tylko
  `sysfs_notify` — trzeba odpytywać. Część TV w standby puszcza hotplug
  (plazma LG), część trzyma (Sony, LG webOS) —
  [skrypty/nbox_tv](../skrypty/nbox_tv).
- Fabryczny `cec_ctrl.ko` (`kernel-modules-cec-gos`) tylko nadaje; kod
  odbioru jest w `#if 0`. Linia CEC to PIO 4.4 (open-drain), a nie 3.7
  (tam są inne impulsy co 0,8 s). Szczegóły i zamiennik: [README](../README.md).
- ST40: TMU0 to clockevent, TMU1 clocksource, **TMU2 wolny**
  (Pphi/4 = 16,594 MHz, irq 18). Zapis TCNT2 przy działającym kanale jest
  ignorowany — najpierw stop kanału w TSTR.
- Na boxie nie ma `/proc/kallsyms`; eksporty sprawdza się `grep EXPORT_SYMBOL`
  w drzewie jądra (`stm_gpio_direction` nie jest eksportowane — nóżka przez
  `stpio_request_pin(..., STPIO_BIDIR)`). Rejestry: `busybox devmem 0xffd80028 16`;
  Python `mmap` na `/dev/mem` czyta rejestry 16-bitowe jako 0.
