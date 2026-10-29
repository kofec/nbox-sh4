/*
 * cec_protokol.h - czesc nbox_cec bez zaleznosci od jadra (test:
 * test_protokol.c): odpowiedzi na zapytania do nBoxa, bity nadawanej ramki,
 * zapis ramki szesnastkowo. Przed #include: typy u8/u16/u32 i MAX_BAJT
 * (z cec_rx_dekoder.h).
 *
 * Odpowiada tylko na to, czego TV wymaga od urzadzenia odtwarzajacego, zeby
 * pokazac je na liscie zrodel i wysylac mu pilota: adres fizyczny, nazwa,
 * producent, wersja CEC, stan zasilania, menu. Na reszte ramek do nBoxa -
 * Feature Abort (wymog CEC), z wyjatkiem tych, ktore sa odpowiedziami albo
 * obsluguje je wtyczka (pilot, standby, wybor zrodla).
 */

#define CEC_ROZGL 0xf

/* opkody (HDMI-CEC 1.3a) */
#define OP_FEATURE_ABORT	0x00
#define OP_IMAGE_VIEW_ON	0x04
#define OP_TEXT_VIEW_ON		0x0d
#define OP_STANDBY		0x36
#define OP_UI_PRESSED		0x44
#define OP_UI_RELEASED		0x45
#define OP_GIVE_OSD_NAME	0x46
#define OP_SET_OSD_NAME		0x47
#define OP_ROUTING_CHANGE	0x80
#define OP_ROUTING_INFO		0x81
#define OP_ACTIVE_SOURCE	0x82
#define OP_GIVE_PHYS_ADDR	0x83
#define OP_REPORT_PHYS_ADDR	0x84
#define OP_REQ_ACTIVE_SOURCE	0x85
#define OP_SET_STREAM_PATH	0x86
#define OP_DEVICE_VENDOR_ID	0x87
#define OP_VENDOR_CMD		0x89
#define OP_VENDOR_RC_DOWN	0x8a
#define OP_VENDOR_RC_UP		0x8b
#define OP_GIVE_VENDOR_ID	0x8c
#define OP_MENU_REQUEST		0x8d
#define OP_MENU_STATUS		0x8e
#define OP_GIVE_POWER_STATUS	0x8f
#define OP_REPORT_POWER_STATUS	0x90
#define OP_CEC_VERSION		0x9e
#define OP_GET_CEC_VERSION	0x9f
#define OP_VENDOR_CMD_ID	0xa0
#define OP_ABORT		0xff

#define TYP_TUNER	3
#define CEC_WERSJA_13A	0x04

struct cec_stan {
	u8 la;			/* adres logiczny nBoxa, 0xF = nie odpowiada */
	u16 pa;			/* adres fizyczny 0xABCD = A.B.C.D, 0 = nie znany */
	u8 standby;		/* 1 = box w standby (ustawia wtyczka) */
	u32 vendor;		/* Device Vendor ID, 24 bity */
	const char *nazwa;	/* OSD name, do 14 znakow */
};

struct cec_tx {
	u8 n;
	u8 b[MAX_BAJT];
};

static void cec_tx_ustaw(struct cec_tx *t, u8 nadawca, u8 odbiorca, u8 op)
{
	t->n = 2;
	t->b[0] = (nadawca << 4) | odbiorca;
	t->b[1] = op;
}

static void cec_tx_dodaj(struct cec_tx *t, u8 bajt)
{
	if (t->n < MAX_BAJT)
		t->b[t->n++] = bajt;
}

/* ramki bez odpowiedzi i bez Feature Abort: odpowiedzi innych, rzeczy wtyczki */
static int cec_bez_odpowiedzi(u8 op)
{
	switch (op) {
	case OP_FEATURE_ABORT:
	case OP_IMAGE_VIEW_ON:
	case OP_TEXT_VIEW_ON:
	case OP_STANDBY:
	case OP_UI_PRESSED:
	case OP_UI_RELEASED:
	case OP_SET_OSD_NAME:
	case OP_ROUTING_CHANGE:
	case OP_ROUTING_INFO:
	case OP_ACTIVE_SOURCE:
	case OP_REPORT_PHYS_ADDR:
	case OP_SET_STREAM_PATH:
	case OP_DEVICE_VENDOR_ID:
	case OP_VENDOR_RC_DOWN:
	case OP_VENDOR_RC_UP:
	case OP_MENU_STATUS:
	case OP_REPORT_POWER_STATUS:
	case OP_CEC_VERSION:
		return 1;
	}
	return 0;
}

/*
 * Odebrana ramka b[0..n-1] (b[0] naglowek, kompletna, z EOM) -> odpowiedzi
 * w odp[0..CEC_MAX_ODP-1], zwraca ich liczbe.
 */
#define CEC_MAX_ODP 2

static int cec_odpowiedz(const struct cec_stan *s, const u8 *b, int n,
			 struct cec_tx *odp)
{
	u8 od = b[0] >> 4, do_ = b[0] & 0xf, op;
	const char *c;

	if (s->la == CEC_ROZGL || n < 2 || od == s->la || od == CEC_ROZGL)
		return 0;
	op = b[1];
	if (do_ == CEC_ROZGL) {
		/* TV wybral nBox z listy zrodel (gdy box dziala; budzi wtyczka) */
		if (op == OP_SET_STREAM_PATH && n >= 4 && s->pa && !s->standby &&
		    ((b[2] << 8) | b[3]) == s->pa) {
			cec_tx_ustaw(&odp[0], s->la, CEC_ROZGL, OP_ACTIVE_SOURCE);
			cec_tx_dodaj(&odp[0], s->pa >> 8);
			cec_tx_dodaj(&odp[0], s->pa & 0xff);
			return 1;
		}
		return 0;
	}
	if (do_ != s->la)
		return 0;

	switch (op) {
	case OP_GIVE_PHYS_ADDR:
		if (!s->pa)
			return 0;
		cec_tx_ustaw(&odp[0], s->la, CEC_ROZGL, OP_REPORT_PHYS_ADDR);
		cec_tx_dodaj(&odp[0], s->pa >> 8);
		cec_tx_dodaj(&odp[0], s->pa & 0xff);
		cec_tx_dodaj(&odp[0], TYP_TUNER);
		return 1;
	case OP_GIVE_OSD_NAME:
		cec_tx_ustaw(&odp[0], s->la, od, OP_SET_OSD_NAME);
		for (c = s->nazwa; *c && *c != '\n' && odp[0].n < 16; c++)
			cec_tx_dodaj(&odp[0], *c);
		return 1;
	case OP_GIVE_VENDOR_ID:
		cec_tx_ustaw(&odp[0], s->la, CEC_ROZGL, OP_DEVICE_VENDOR_ID);
		cec_tx_dodaj(&odp[0], (s->vendor >> 16) & 0xff);
		cec_tx_dodaj(&odp[0], (s->vendor >> 8) & 0xff);
		cec_tx_dodaj(&odp[0], s->vendor & 0xff);
		return 1;
	case OP_GET_CEC_VERSION:
		cec_tx_ustaw(&odp[0], s->la, od, OP_CEC_VERSION);
		cec_tx_dodaj(&odp[0], CEC_WERSJA_13A);
		return 1;
	case OP_GIVE_POWER_STATUS:
		cec_tx_ustaw(&odp[0], s->la, od, OP_REPORT_POWER_STATUS);
		cec_tx_dodaj(&odp[0], s->standby ? 1 : 0);
		return 1;
	case OP_MENU_REQUEST:
		/* menu "aktywne" = TV przekazuje pilota (LG, Samsung tego chca) */
		cec_tx_ustaw(&odp[0], s->la, od, OP_MENU_STATUS);
		cec_tx_dodaj(&odp[0], s->standby ? 1 : 0);
		return 1;
	}
	if (cec_bez_odpowiedzi(op))
		return 0;
	/* nieobslugiwany: Feature Abort, powod 0 (nieznany) / 4 (Abort) */
	cec_tx_ustaw(&odp[0], s->la, od, OP_FEATURE_ABORT);
	cec_tx_dodaj(&odp[0], op);
	cec_tx_dodaj(&odp[0], op == OP_ABORT ? 4 : 0);
	return 1;
}

/*
 * Bity nadawania: 0 = start, potem 10 na bajt (8 danych od najstarszego,
 * EOM, ACK). Wartosc bitu k >= 1; ACK nadawca wysyla jako 1.
 */
static int cec_bitow(const struct cec_tx *t)
{
	return 1 + 10 * t->n;
}

static int cec_bit(const struct cec_tx *t, int k)
{
	int j = (k - 1) / 10, p = (k - 1) % 10;

	if (p < 8)
		return (t->b[j] >> (7 - p)) & 1;
	if (p == 8)
		return j == t->n - 1;
	return 1;
}

/* bit k to probkowanie ACK bloku */
static int cec_bit_ack(int k)
{
	return k >= 1 && (k - 1) % 10 == 9;
}

/* bit k to adres nadawcy (tu przegrany arbitraz to nie blad) */
static int cec_bit_nadawcy(int k)
{
	return k >= 1 && k <= 4;
}

/* "3f821000" -> ramka; -1 gdy zly zapis (nieparzysty, nie hex, za dlugi) */
static int cec_z_hex(const char *s, int len, struct cec_tx *t)
{
	int i, v = 0, h;

	while (len > 0 && (s[len - 1] == '\n' || s[len - 1] == '\r' ||
			   s[len - 1] == ' '))
		len--;
	if (len < 2 || len % 2 || len / 2 > MAX_BAJT)
		return -1;
	t->n = 0;
	for (i = 0; i < len; i++) {
		char c = s[i];

		if (c >= '0' && c <= '9')
			h = c - '0';
		else if (c >= 'a' && c <= 'f')
			h = c - 'a' + 10;
		else if (c >= 'A' && c <= 'F')
			h = c - 'A' + 10;
		else
			return -1;
		if (i % 2 == 0) {
			v = h << 4;
		} else {
			t->b[t->n++] = v | h;
		}
	}
	return 0;
}

/* "1.0.0.0" (z cec_address stmfb) -> 0x1000; 0 gdy nie da sie odczytac */
static u16 cec_pa_z_tekstu(const char *s, int len)
{
	u16 pa = 0;
	int cyfr = 0, i;

	for (i = 0; i < len && cyfr < 4; i++) {
		if (s[i] >= '0' && s[i] <= '9') {
			pa = (pa << 4) | (s[i] - '0');
			cyfr++;
		} else if (s[i] >= 'a' && s[i] <= 'f') {
			pa = (pa << 4) | (s[i] - 'a' + 10);
			cyfr++;
		}
	}
	return cyfr == 4 ? pa : 0;
}
