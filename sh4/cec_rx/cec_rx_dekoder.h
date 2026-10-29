/*
 * cec_rx_dekoder.h - dekoder ramek HDMI-CEC z czasow zboczy, wspolny dla
 * modulu cec_rx.c i testu test_dekoder.c. Bez zaleznosci od jadra: przed
 * #include trzeba zdefiniowac typy u8/u16/u32/s64 i makro
 * DEK_CZAS(sek, ms) - czas rzeczywisty poczatku ramki.
 *
 * Wejscie: dek_zbocze(poziom po zboczu, czas w us). Start = niski
 * T_START_MIN..T_START_MAX; bit = niski T_JEDEN_MIN..T_JEDEN_MAX -> 1,
 * do T_ZERO_MAX -> 0; blok = 8 bitow danych + EOM + ACK. Ramka konczy sie
 * na EOM=1, na nastepnym starcie albo po wysokim dluzszym niz T_KONIEC.
 *
 * Dla nbox_cec (potwierdzanie): dek_czas_na_ack(la) przed zboczem w dol mowi,
 * ze zaczyna sie bit ACK bloku ramki do `la`; DEK_PO_RAMCE(r) - zamknieta
 * ramka (domyslnie nic).
 */

#ifndef DEK_PO_RAMCE
#define DEK_PO_RAMCE(r)	do { } while (0)
#endif

#define N_RAMEK   256
#define MAX_BAJT  16

#define T_START_MIN 3300
#define T_START_MAX 4300
#define T_JEDEN_MIN 300
#define T_JEDEN_MAX 1050
#define T_ZERO_MAX  2050
#define T_KONIEC    3500

/* blad: 1 zly czas bitu, 2 urwana w bloku, 4 zgubione zbocze */
struct ramka {
	u32 nr;
	unsigned long sek;
	unsigned long ms;
	u8 n;
	u8 b[MAX_BAJT];
	u16 ack;
	u8 eom;
	u8 blad;
};

static struct ramka ramki[N_RAMEK];
static unsigned int poz;
static u32 nastepny_nr = 1;

static struct ramka biez;
static int w_ramce, bit_w_bloku, eom_bloku;
static int dek_adresat = -1;	/* odbiorca z naglowka, -1 = jeszcze nie ma */
static u8 bajt;
static s64 t_spadek, t_wzrost;
static int poziom_pop = 1;
static unsigned long n_ramek, n_zboczy, n_zgubione, n_szum, n_bledy;

static void dek_zamknij(void)
{
	if (!w_ramce)
		return;
	if (bit_w_bloku != 0)
		biez.blad |= 2;
	if (biez.blad)
		n_bledy++;
	biez.nr = nastepny_nr++;
	ramki[poz] = biez;
	DEK_PO_RAMCE(&ramki[poz]);
	poz = (poz + 1) % N_RAMEK;
	n_ramek++;
	w_ramce = 0;
}

static void dek_zacznij(void)
{
	memset(&biez, 0, sizeof(biez));
	DEK_CZAS(biez.sek, biez.ms);
	w_ramce = 1;
	bit_w_bloku = 0;
	eom_bloku = 0;
	bajt = 0;
	dek_adresat = -1;
}

static void dek_bit(int b)
{
	if (bit_w_bloku < 8) {
		bajt = (bajt << 1) | b;
	} else if (bit_w_bloku == 8) {
		eom_bloku = b;
		if (biez.n == 0)
			dek_adresat = bajt & 0xf;
	} else {
		if (biez.n < MAX_BAJT) {
			biez.b[biez.n] = bajt;
			if (!b)
				biez.ack |= 1 << biez.n;
			biez.n++;
		}
		bajt = 0;
		bit_w_bloku = 0;
		if (eom_bloku) {
			biez.eom = 1;
			dek_zamknij();
		}
		return;
	}
	bit_w_bloku++;
}

/* v - poziom po zboczu (0/1), t - czas w us (monotoniczny) */
static void dek_zbocze(int v, s64 t)
{
	s64 niski;

	n_zboczy++;
	if (v == poziom_pop) {
		/* zgubione zbocze - stan sie nie zgadza, ramka do kosza */
		n_zgubione++;
		if (w_ramce) {
			biez.blad |= 4;
			bit_w_bloku = 0;
			dek_zamknij();
		}
	} else if (!v) {
		if (w_ramce && t - t_wzrost > T_KONIEC)
			dek_zamknij();
	} else {
		niski = t - t_spadek;
		if (niski >= T_START_MIN && niski <= T_START_MAX) {
			dek_zamknij();
			dek_zacznij();
		} else if (!w_ramce) {
			n_szum++;
		} else if (niski < T_JEDEN_MIN || niski > T_ZERO_MAX) {
			biez.blad |= 1;
			bit_w_bloku = 0;
			dek_zamknij();
		} else {
			dek_bit(niski <= T_JEDEN_MAX);
		}
	}
	poziom_pop = v;
	if (v)
		t_wzrost = t;
	else
		t_spadek = t;
}

/*
 * Wolac przed dek_zbocze(0, ...): 1 = to zbocze zaczyna bit ACK bloku ramki
 * kierowanej do `la` (rozgloszen 0xF sie nie potwierdza - tam ACK w dol to
 * odrzucenie).
 */
static int dek_czas_na_ack(int la)
{
	return w_ramce && poziom_pop && bit_w_bloku == 9 && la != 0xf &&
	       dek_adresat == la;
}

/* ramka urwana (bez EOM), po ktorej linia stoi wysoko od T_KONIEC */
static void dek_cisza(s64 t)
{
	if (w_ramce && poziom_pop && t - t_wzrost > T_KONIEC)
		dek_zamknij();
}

/*
 * Linia ramki: <nr> <sek.ms> <nadawca>><odbiorca> <bajt><a> ... [?] [!blad]
 * a: '+' bit ACK sciagniety w dol, '-' nie; ? - bez EOM.
 * DEK_PRINTF(ctx, fmt, ...) definiuje includer.
 */
static void dek_wypisz(void *ctx, const struct ramka *r)
{
	int j;

	DEK_PRINTF(ctx, "%u %lu.%03lu ", r->nr, r->sek, r->ms);
	if (r->n)
		DEK_PRINTF(ctx, "%X>%X", r->b[0] >> 4, r->b[0] & 0xf);
	else
		DEK_PRINTF(ctx, "-");
	for (j = 0; j < r->n; j++)
		DEK_PRINTF(ctx, " %02x%c", r->b[j],
			   (r->ack & (1 << j)) ? '+' : '-');
	if (!r->eom)
		DEK_PRINTF(ctx, " ?");
	if (r->blad)
		DEK_PRINTF(ctx, " !%d", r->blad);
	DEK_PRINTF(ctx, "\n");
}
