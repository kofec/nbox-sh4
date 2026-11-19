/*
 * nor_otp - odczyt rejestru ochronnego (OTP) kosci NOR nBoxa, tylko odczyt.
 *
 * Wymaga jadra z latki/nbox_nor_ro.patch (MTD_OTP, NOR jako mtd2 "nor").
 * Kosci ST M28W320 maja 64-bitowy numer nadany fabrycznie (unikalny dla
 * kosci) i 64/128 bitow OTP uzytkownika. Program wybiera tryb OTP ioctl-em
 * OTPSELECT, wypisuje regiony (OTPGETREGIONINFO) i ich zawartosc. Urzadzenie
 * otwiera tylko O_RDONLY; zapisu i blokady OTP nie ma (a jadro z latka i tak
 * je odrzuca na partycji bez MTD_WRITEABLE).
 *
 *   nor_otp [/dev/mtd2]
 *
 * Wynik: "fabryczny: <hex>" to identyfikator kosci. Kod wyjscia 0 = odczytany
 * przynajmniej region fabryczny.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <mtd/mtd-abi.h>

#define MAX_REG 16

static int pokaz(int fd, int tryb, const char *nazwa)
{
	struct otp_info info[MAX_REG];
	unsigned char buf[256];
	int ile = 0, i, j, odczytano = 0;

	if (ioctl(fd, OTPSELECT, &tryb) < 0) {
		printf("%s: OTPSELECT: %s\n", nazwa, strerror(errno));
		return 0;
	}
	if (ioctl(fd, OTPGETREGIONCOUNT, &ile) < 0) {
		printf("%s: OTPGETREGIONCOUNT: %s\n", nazwa, strerror(errno));
		ile = 0;
	}
	printf("%s: regionow %d\n", nazwa, ile);
	if (ile > MAX_REG)
		ile = MAX_REG;
	if (ile > 0 && ioctl(fd, OTPGETREGIONINFO, info) < 0) {
		printf("%s: OTPGETREGIONINFO: %s\n", nazwa, strerror(errno));
		ile = 0;
	}
	for (i = 0; i < ile; i++) {
		unsigned int dl = info[i].length;
		ssize_t n;

		printf("%s: region %d start 0x%x dlugosc %u %s\n", nazwa, i,
		       info[i].start, info[i].length,
		       info[i].locked ? "zablokowany" : "niezablokowany");
		if (dl > sizeof(buf))
			dl = sizeof(buf);
		if (lseek(fd, info[i].start, SEEK_SET) < 0) {
			printf("%s: lseek: %s\n", nazwa, strerror(errno));
			continue;
		}
		n = read(fd, buf, dl);
		if (n <= 0) {
			printf("%s: read: %s\n", nazwa, n < 0 ? strerror(errno) : "0 bajtow");
			continue;
		}
		printf("%s: ", nazwa);
		for (j = 0; j < n; j++)
			printf("%02x", buf[j]);
		printf("\n");
		odczytano = 1;
	}
	return odczytano;
}

int main(int argc, char **argv)
{
	const char *dev = argc > 1 ? argv[1] : "/dev/mtd2";
	struct mtd_info_user mi;
	int fd, ok;

	fd = open(dev, O_RDONLY);
	if (fd < 0) {
		perror(dev);
		return 2;
	}
	if (ioctl(fd, MEMGETINFO, &mi) == 0) {
		printf("%s: typ %u flagi 0x%x rozmiar %u blok %u\n", dev,
		       mi.type, mi.flags, mi.size, mi.erasesize);
		if (mi.flags & MTD_WRITEABLE)
			printf("UWAGA: %s jest zapisywalne - to nie jadro z nbox_nor_ro\n", dev);
	} else
		printf("%s: MEMGETINFO: %s\n", dev, strerror(errno));

	ok = pokaz(fd, MTD_OTP_FACTORY, "fabryczny");
	pokaz(fd, MTD_OTP_USER, "uzytkownika");
	close(fd);
	return ok ? 0 : 1;
}
