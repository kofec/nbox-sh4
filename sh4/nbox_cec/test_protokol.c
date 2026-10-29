/*
 * test_protokol.c - czesc nbox_cec bez jadra: odpowiedzi (cec_protokol.h),
 * moment ACK z dekodera (cec_rx_dekoder.h) na zboczach z boxa BSLA i bity
 * nadawania odczytane z powrotem dekoderem. Na komputerze:
 *
 *   gcc -O2 -Wall -I../cec_rx -o test_protokol test_protokol.c && ./test_protokol
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
#include "cec_protokol.h"

static int bledy;

static void wynik(const char *nazwa, const char *jest, const char *ma_byc)
{
	if (strcmp(jest, ma_byc)) {
		printf("BLAD %s\n  jest:      %s\n  oczekiwane: %s\n", nazwa, jest, ma_byc);
		bledy++;
	} else {
		printf("ok   %s: %s\n", nazwa, jest);
	}
}

/* --- odpowiedzi --- */

static void odp(const char *nazwa, const struct cec_stan *s, const char *ramka,
		const char *ma_byc)
{
	struct cec_tx r, o[CEC_MAX_ODP];
	char jest[256] = "";
	int i, j, n;

	cec_z_hex(ramka, strlen(ramka), &r);
	n = cec_odpowiedz(s, r.b, r.n, o);
	for (i = 0; i < n; i++) {
		if (i)
			strcat(jest, " ");
		for (j = 0; j < o[i].n; j++)
			sprintf(jest + strlen(jest), "%02x", o[i].b[j]);
	}
	if (!n)
		strcpy(jest, "-");
	wynik(nazwa, jest, ma_byc);
}

static void test_odpowiedzi(void)
{
	struct cec_stan s = { 3, 0x4000, 0, 0, "nBox" };
	struct cec_stan bez_la = s, bez_pa = s, uspiony = s;

	bez_la.la = 0xf;
	bez_pa.pa = 0;
	uspiony.standby = 1;

	odp("Give Physical Address", &s, "0383", "3f84400003");
	odp("Give OSD Name", &s, "0346", "30476e426f78");
	odp("Give OSD Name od soundbara", &s, "5346", "35476e426f78");
	odp("Give Vendor ID", &s, "038c", "3f87000000");
	odp("Get CEC Version", &s, "039f", "309e04");
	odp("Give Power Status, dziala", &s, "038f", "309000");
	odp("Give Power Status, standby", &uspiony, "038f", "309001");
	odp("Menu Request", &s, "038d02", "308e00");
	odp("Set Stream Path na nBox", &s, "0f864000", "3f824000");
	odp("Set Stream Path na nBox w standby", &uspiony, "0f864000", "-");
	odp("Set Stream Path gdzie indziej", &s, "0f861000", "-");
	odp("Sony vendor command z ID", &s, "03a0080046003f", "3000a000");
	odp("Abort", &s, "03ff", "3000ff04");
	odp("pilot 44", &s, "034401", "-");
	odp("pilot 45", &s, "0345", "-");
	odp("Standby rozgloszenie", &s, "0f36", "-");
	odp("Standby do nBoxa", &s, "0336", "-");
	odp("do soundbara", &s, "0583", "-");
	odp("wlasna ramka", &s, "3083", "-");
	odp("sonda", &s, "03", "-");
	odp("bez adresu logicznego", &bez_la, "0383", "-");
	odp("bez adresu fizycznego", &bez_pa, "0383", "-");
}

/* --- ACK w dekoderze --- */

static void zeruj(void)
{
	memset(ramki, 0, sizeof(ramki));
	poz = 0;
	nastepny_nr = 1;
	w_ramce = 0;
	poziom_pop = 1;
	t_spadek = t_wzrost = 0;
	dek_adresat = -1;
	n_ramek = n_zboczy = n_zgubione = n_szum = n_bledy = 0;
}

/* BSLA, Sony: 3>0 30 8f, potem 4x naglowek 0>3 (z test_dekoder.c) */
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

/* ile razy dekoder kaze potwierdzac dla `la` */
static int ile_ack(const char *zbocza, int la)
{
	s64 t = 0;
	int p, us, n, ile = 0;

	zeruj();
	while (sscanf(zbocza, " %d:%d%n", &p, &us, &n) == 2) {
		t += us;
		if (!p && dek_czas_na_ack(la))
			ile++;
		dek_zbocze(p, t);
		zbocza += n;
	}
	return ile;
}

static void test_ack(void)
{
	char t[64];

	sprintf(t, "%d", ile_ack(sony, 3));
	wynik("ACK dla 3 (4 naglowki 0>3)", t, "4");
	sprintf(t, "%d", ile_ack(sony, 0));
	wynik("ACK dla 0 (3>0 30 8f: 2 bloki)", t, "2");
	sprintf(t, "%d", ile_ack(sony, 0xf));
	wynik("ACK dla F (nigdy)", t, "0");
	sprintf(t, "%d", ile_ack(sony, 5));
	wynik("ACK dla 5 (nic do niego)", t, "0");
}

/* --- nadawanie: bity -> zbocza -> dekoder --- */

/* ack_od: odbiorca sciaga ACK w dol (1) albo nie (0) */
static void nadaj(const char *nazwa, const char *ramka, int ack_od,
		  const char *ma_byc)
{
	struct cec_tx r;
	char linia[256] = "";
	s64 t = 100000;
	int k;

	zeruj();
	cec_z_hex(ramka, strlen(ramka), &r);
	dek_zbocze(0, t);
	dek_zbocze(1, t + 3700);
	t += 4500;
	for (k = 1; k < cec_bitow(&r); k++) {
		int v = cec_bit(&r, k), niski;

		if (cec_bit_ack(k) && ack_od)
			v = 0;
		niski = v ? 600 : 1500;
		dek_zbocze(0, t);
		dek_zbocze(1, t + niski);
		t += 2400;
	}
	dek_cisza(t + 10000);
	if (ramki[0].nr)
		dek_wypisz(linia, &ramki[0]);
	wynik(nazwa, strchr(strchr(linia, ' ') + 1, ' ') + 1, ma_byc);
}

static void test_nadawanie(void)
{
	nadaj("3004 z ACK", "3004", 1, "3>0 30+ 04+\n");
	nadaj("3f84400003 rozgloszenie", "3f84400003", 0, "3>F 3f- 84- 40- 00- 03-\n");
	nadaj("sonda 33 bez ACK", "33", 0, "3>3 33-\n");
	nadaj("OSD name", "30476e426f78", 1, "3>0 30+ 47+ 6e+ 42+ 6f+ 78+\n");
}

static void test_hex_pa(void)
{
	struct cec_tx r;
	char t[64];

	sprintf(t, "%d %d %d %d", cec_z_hex("3004\n", 5, &r), cec_z_hex("300", 3, &r),
		cec_z_hex("30zz", 4, &r),
		cec_z_hex("000102030405060708090a0b0c0d0e0f10", 34, &r));
	wynik("hex: dobra, nieparzysta, nie hex, za dluga", t, "0 -1 -1 -1");
	sprintf(t, "%04x %04x %04x", cec_pa_z_tekstu("1.0.0.0\n", 8),
		cec_pa_z_tekstu("4.0.0.0", 7), cec_pa_z_tekstu("", 0));
	wynik("adres fizyczny z tekstu", t, "1000 4000 0000");
}

int main(void)
{
	test_odpowiedzi();
	test_ack();
	test_nadawanie();
	test_hex_pa();
	printf("%s (%d)\n", bledy ? "BLEDY" : "wszystko ok", bledy);
	return bledy != 0;
}
