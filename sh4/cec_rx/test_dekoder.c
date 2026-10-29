/*
 * test_dekoder.c - dekoder z cec_rx_dekoder.h na zboczach zapisanych przez
 * cec_diag 2026-10-21 (format /proc/cec_diag: "<poziom po zboczu>:<us od
 * poprzedniego>"). Uruchamiac na komputerze (zwykly gcc):
 *
 *   gcc -O2 -o test_dekoder test_dekoder.c && ./test_dekoder
 *
 * Kazdy przypadek: zbocza -> oczekiwane linie (bez nr i czasu).
 */

#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdarg.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef int64_t s64;

#define DEK_CZAS(s, m)		do { (s) = 0; (m) = 0; } while (0)
#define DEK_PRINTF(c, ...)	pisz((char *)(c), __VA_ARGS__)

static void pisz(char *bufor, const char *fmt, ...)
{
	va_list ap;

	va_start(ap, fmt);
	vsprintf(bufor + strlen(bufor), fmt, ap);
	va_end(ap);
}

#include "cec_rx_dekoder.h"

static void zeruj(void)
{
	memset(ramki, 0, sizeof(ramki));
	poz = 0;
	nastepny_nr = 1;
	w_ramce = 0;
	poziom_pop = 1;
	t_spadek = t_wzrost = 0;
	n_ramek = n_zboczy = n_zgubione = n_szum = n_bledy = 0;
}

/* zbocza jako tekst "p:us p:us ..." -> wynik: linie ramek bez "nr 0.000 " */
static void dekoduj(const char *zbocza, char *wynik)
{
	s64 t = 0;
	int p, us, n;
	unsigned int i;
	char linia[256];

	zeruj();
	while (sscanf(zbocza, " %d:%d%n", &p, &us, &n) == 2) {
		t += us;
		dek_zbocze(p, t);
		zbocza += n;
	}
	dek_cisza(t + 10000);
	wynik[0] = 0;
	for (i = 0; i < N_RAMEK; i++) {
		struct ramka *r = &ramki[(poz + i) % N_RAMEK];

		if (!r->nr)
			continue;
		linia[0] = 0;
		dek_wypisz(linia, r);
		strcat(wynik, strchr(strchr(linia, ' ') + 1, ' ') + 1);
	}
}

static int bledy;

static void sprawdz(const char *nazwa, const char *zbocza, const char *oczekiwane)
{
	char wynik[4096];

	dekoduj(zbocza, wynik);
	if (strcmp(wynik, oczekiwane)) {
		printf("BLAD %s\n-- jest:\n%s-- oczekiwane:\n%s", nazwa, wynik, oczekiwane);
		bledy++;
	} else {
		printf("ok   %s\n%s", nazwa, wynik);
	}
}

/* BSLA, Sony, echo 308f > /proc/stb/hdmi/cec (08:4x) */
static const char *sony =
	"0:578809 1:3584 0:974 1:1519 0:1039 1:1484 0:891 1:602 0:1794 1:825 "
	"0:1562 1:1497 0:901 1:1514 0:891 1:1499 0:892 1:1508 0:885 1:1500 "
	"0:879 1:1533 0:860 1:621 0:1779 1:1614 0:822 1:1476 0:893 1:1505 "
	"0:888 1:601 0:1798 1:613 0:1798 1:595 0:1799 1:598 0:1785 1:587 "
	"0:1797 1:1521 0:31376 1:3706 0:790 1:1515 0:907 1:1506 0:899 1:1517 "
	"0:900 1:1503 0:898 1:1507 0:891 1:1517 0:905 1:593 0:1813 1:605 "
	"0:1793 1:1507 0:930 1:590 0:9045 1:3700 0:795 1:1514 0:907 1:1504 "
	"0:893 1:1519 0:899 1:1513 0:897 1:1507 0:906 1:1501 0:899 1:602 "
	"0:1806 1:627 0:1794 1:1492 0:910 1:599 0:17369 1:3698 0:804 1:1505 "
	"0:894 1:1506 0:913 1:1512 0:897 1:1511 0:900 1:1510 0:901 1:1502 "
	"0:894 1:606 0:1802 1:616 0:1794 1:1506 0:917 1:593 0:9057 1:3705 "
	"0:789 1:1514 0:895 1:1519 0:890 1:1515 0:894 1:1506 0:912 1:1507 "
	"0:900 1:1513 0:899 1:604 0:1806 1:617 0:1793 1:1503 0:945 1:564";

/* BSKA, Samsung w standby, echo 308f (09:02:14) */
static const char *samsung =
	"0:1042437 1:3923 0:914 1:1488 0:898 1:1504 0:887 1:602 0:1793 1:601 "
	"0:1787 1:1487 0:896 1:1500 0:893 1:1497 0:896 1:1499 0:897 1:1493 "
	"0:900 1:1493 0:896 1:599 0:1844 1:1467 0:901 1:1542 0:897 1:1494 "
	"0:900 1:597 0:1793 1:596 0:1798 1:661 0:1746 1:626 0:1795 1:598 "
	"0:1798 1:1495";

/* BSLA, PIO 3.7, impulsy przy przelaczaniu Sony - to nie CEC */
static const char *impulsy =
	"1:12699095 0:799875 1:8760285 0:799575";

int main(void)
{
	sprawdz("sony 308f + 4x odpowiedz bez ACK", sony,
		"3>0 30+ 8f+\n"
		"0>3 03- ?\n"
		"0>3 03- ?\n"
		"0>3 03- ?\n"
		"0>3 03- ?\n");
	sprawdz("samsung 308f", samsung, "3>0 30+ 8f+\n");
	sprawdz("impulsy 0,8 s", impulsy, "");
	printf("%s (%d)\n", bledy ? "BLEDY" : "wszystko ok", bledy);
	return bledy != 0;
}
