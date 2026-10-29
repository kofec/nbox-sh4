/*
 * nbox_cec.c - HDMI-CEC na nBoxie ADB 5800 (STi7100, GraterliaOS, jadro
 * 2.6.32.61_stm24_0217) w jednym module: odbior (jak cec_rx), potwierdzanie
 * (ACK) ramek do nBoxa, odpowiedzi na zapytania TV (nazwa "nBox", adres
 * fizyczny...), nadawanie z arbitrazem i sprawdzaniem ACK (zamiast cec_ctrl)
 * i kolejka klawiszy pilota TV dla wtyczki enigmy.
 *
 * Linia CEC: PIO 4.4, open-drain (BIDIR). Zbocza - przerwanie GPIO na obu
 * zboczach, dekoder z ../cec_rx/cec_rx_dekoder.h. Czasy nadawania i ACK -
 * TMU2 procesora (jadro uzywa tylko TMU0 i TMU1; HIGH_RES_TIMERS nie ma, HZ
 * 250), jednorazowo: stop kanalu, TCNT2 = ile tykniec do przerwania, start;
 * "wylaczony" = kanal zatrzymany. Bezpiecznik co 1 s: nadawanie albo ACK
 * dluzej niz BEZPIECZNIK_US = zegar stoi, nozka puszczona.
 *
 * Gdy nozke trzyma cec_ctrl (Graterlia, pakiet kernel-modules-cec-gos),
 * modul dziala z nia wspolnie (do testow bez restartu): steruje nozka bez
 * gpio_request i nie rejestruje /proc/stb/hdmi/cec - nadaje sie wtedy przez
 * /proc/nbox_cec. cec_ctrl po rmmod nie oddaje IRQ 120 ani nozki, wiec na
 * stale: bez cec_ctrl i restart boxa.
 *
 * /proc/cec_rx           - jak w cec_rx 1.2 (wtyczka nBox CEC czyta bez zmian)
 * /proc/nbox_cec         - stan i ostatnie zdarzenia; zapis "3004" = nadaj
 * /proc/nbox_cec_klawisze - pilot TV: linie "44 <kod>" / "45", czytanie
 *                          zabiera, poll() gdy cos jest
 * /proc/stb/hdmi/cec     - zapis jak do cec_ctrl (tylko gdy nozka nasza)
 *
 * Parametry (/sys/module/nbox_cec/parameters/, 0644 - do zmiany w biegu):
 *   ack, odpowiedzi - 0 wylacza potwierdzanie / odpowiedzi,
 *   standby - stan boxa dla Report Power Status (ustawia wtyczka),
 *   adres_fiz - 0 = z cec_address stmfb (zapamietany ostatni niezerowy),
 *   nazwa, vendor, pokaz; adres_log (dom. 3, Tuner 1), port, pin, tmu_irq.
 *
 * Zabezpieczenie: ponad BURZA zboczy/s -> przerwanie GPIO wylaczone do rmmod.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/gpio.h>
#include <linux/interrupt.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/ktime.h>
#include <linux/time.h>
#include <linux/jiffies.h>
#include <linux/spinlock.h>
#include <linux/mutex.h>
#include <linux/string.h>
#include <linux/workqueue.h>
#include <linux/wait.h>
#include <linux/poll.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/stm/gpio.h>
#include <linux/stm/pio.h>
#include <asm/io.h>

#define WERSJA "2.0.1"

static void czas_ramki(unsigned long *sek, unsigned long *ms)
{
	struct timeval tv = ktime_to_timeval(ktime_get_real());

	*sek = tv.tv_sec;
	*ms = tv.tv_usec / 1000;
}

struct ramka;
static void po_ramce(const struct ramka *r);

#define DEK_CZAS(s, m)		czas_ramki(&(s), &(m))
#define DEK_PRINTF(c, ...)	seq_printf((struct seq_file *)(c), __VA_ARGS__)
#define DEK_PO_RAMCE(r)		po_ramce(r)
#include "cec_rx_dekoder.h"
#include "cec_protokol.h"

static int port = 4;
static int pin = 4;
module_param(port, int, 0444);
module_param(pin, int, 0444);
static unsigned int pokaz = 64;
module_param(pokaz, uint, 0644);
static int adres_log = 3;
module_param(adres_log, int, 0444);
static int ack = 1;
module_param(ack, int, 0644);
static int odpowiedzi = 1;
module_param(odpowiedzi, int, 0644);
static int standby;
module_param(standby, int, 0644);
static uint adres_fiz;
module_param(adres_fiz, uint, 0644);
/*
 * Pulse-Eight (libCEC, m.in. Kodi). Na 000000 LG webOS co 14 s pytal o
 * producenta jak o nieznanego, od 0x001582 przestal (2026-10-23). ID samego
 * TV (LG 00e091, Sony 080046) - nie: TV slalby komendy producenta.
 */
static uint vendor = 0x001582;
module_param(vendor, uint, 0644);
static char nazwa[15] = "nBox";
module_param_string(nazwa, nazwa, sizeof(nazwa), 0644);
static int tmu_irq = 18;	/* TMU2 TUNI2, evt 0x440 */
module_param(tmu_irq, int, 0444);
static int e2proc = 1;
module_param(e2proc, int, 0444);

/* czasy CEC 1.3a w us */
#define T_BIT		2400
#define T_START_NISKI	3700
#define T_START_CALY	4500
#define T_JEDEN_NISKI	600
#define T_ZERO_NISKI	1500
#define T_PROBKA	1050
#define T_ACK_NISKI	1450	/* od wejscia w przerwanie, ~1,5 ms od zbocza */
#define MARGINES	30
#define TX_PROBY	2	/* powtorzen po NACK, razem 3 proby */

#define BURZA 5000

/* TMU (P4, SH4) */
#define TMU_TSTR	((void __iomem *)0xffd80004)
#define TMU0_TCOR	((void __iomem *)0xffd80008)
#define TMU2_TCOR	((void __iomem *)0xffd80020)
#define TMU2_TCNT	((void __iomem *)0xffd80024)
#define TMU2_TCR	((void __iomem *)0xffd80028)
#define TCR_UNIE	0x0020
#define TSTR_STR2	0x04

static u32 tmu_khz;
static int gpio_nr = -1, irq_nr = -1, nozka_nasza, e2_nasze, tmu_jest;
static struct stpio_pin *nozka;
static DEFINE_SPINLOCK(blokada);
static unsigned long w_oknie, okno;
static int burza;
static int la_akt = 0xf;
static s64 t_ost;		/* ostatnie zbocze */
static int ack_trwa;
static s64 ack_koniec;
static u16 pa_ost;
static unsigned long n_ack, n_tx_ok, n_tx_nack, n_tx_odrz, n_tx_arb, n_tx_blad,
	n_tx_zgub, n_zegar;

static s64 teraz_us(void)
{
	return ktime_to_us(ktime_get());
}

static void linia(int v)
{
	gpio_set_value(gpio_nr, v);
}

static int linia_stan(void)
{
	return gpio_get_value(gpio_nr) ? 1 : 0;
}

/* --- notatki (printk w obrazie Graterlii wylaczony) --- */

#define N_NOTATEK 32
static struct {
	unsigned long sek, ms;
	char t[56];
} notatki[N_NOTATEK];
static unsigned int n_not;
static DEFINE_SPINLOCK(not_blokada);

static void notuj(const char *fmt, ...)
{
	unsigned long f, sek, ms;
	va_list ap;

	czas_ramki(&sek, &ms);
	spin_lock_irqsave(&not_blokada, f);
	notatki[n_not % N_NOTATEK].sek = sek;
	notatki[n_not % N_NOTATEK].ms = ms;
	va_start(ap, fmt);
	vsnprintf(notatki[n_not % N_NOTATEK].t, sizeof(notatki[0].t), fmt, ap);
	va_end(ap);
	n_not++;
	spin_unlock_irqrestore(&not_blokada, f);
}

static char *hex(const struct cec_tx *r, char *buf)
{
	int i;

	for (i = 0; i < r->n; i++)
		sprintf(buf + 2 * i, "%02x", r->b[i]);
	buf[2 * r->n] = 0;
	return buf;
}

/* --- TMU2 --- */

/*
 * Zapis TCNT2 przy dzialajacym kanale ST40 ignoruje (BSLA, 2026-10-23: UNF
 * zgaszony, licznik dalej od 0xffffffff), wiec: stop, TCNT2, start. TSTR
 * dzielony z TMU0/1 - sh_tmu rusza go tylko przy starcie i pod irqsave, a my
 * zawsze pod blokada z wylaczonymi przerwaniami (jeden procesor).
 */
static void tmu_za(s64 us)
{
	u8 tstr = __raw_readb(TMU_TSTR);

	if (us < 10)
		us = 10;
	if (us > 100000)
		us = 100000;
	__raw_writeb(tstr & ~TSTR_STR2, TMU_TSTR);
	__raw_writel((u32)us * tmu_khz / 1000, TMU2_TCNT);
	__raw_writeb(tstr | TSTR_STR2, TMU_TSTR);
}

static void tmu_stop(void)
{
	__raw_writeb(__raw_readb(TMU_TSTR) & ~TSTR_STR2, TMU_TSTR);
}

/* --- nadawanie --- */

enum { TX_NIC, TX_CZEKA, TX_BIT };
enum { W_OK, W_NACK, W_ODRZUCONA, W_BLAD };
static const char *wynik_txt[] = { "ok", "NACK", "odrzucona", "blad" };

#define N_KOLEJKA 16
static struct cec_tx kolejka[N_KOLEJKA];
static unsigned int k_odcz, k_zap;

static struct {
	int stan;
	struct cec_tx r;
	int proby, bit, faza;
	s64 t_bitu, nast;
	int wolne;
	u16 ack;
} tx;

static void planuj(s64 teraz)
{
	s64 t = -1;

	if (!tmu_jest)
		return;
	if (ack_trwa)
		t = ack_koniec;
	if (tx.stan != TX_NIC && (t < 0 || tx.nast < t))
		t = tx.nast;
	if (t < 0)
		tmu_stop();
	else
		tmu_za(t - teraz);
}

static int tx_nastepna(s64 teraz, int wolne)
{
	if (k_odcz == k_zap) {
		tx.stan = TX_NIC;
		return 0;
	}
	tx.r = kolejka[k_odcz];
	k_odcz = (k_odcz + 1) % N_KOLEJKA;
	tx.proby = 0;
	tx.stan = TX_CZEKA;
	tx.wolne = wolne;
	tx.nast = teraz;
	return 1;
}

static void tx_koniec(int wynik, s64 teraz)
{
	char h[2 * MAX_BAJT + 1];
	int sonda = tx.r.n == 1;

	linia(1);
	if (wynik == W_NACK && !sonda && tx.proby < TX_PROBY) {
		tx.proby++;
		tx.stan = TX_CZEKA;
		tx.wolne = 3 * T_BIT;
		tx.nast = teraz + tx.wolne;
		return;
	}
	if (sonda) {
		/* sprawdzenie wlasnego adresu: ACK = ktos go juz ma */
		if ((tx.r.b[0] >> 4) == (tx.r.b[0] & 0xf) && wynik == W_OK) {
			notuj("adres %X zajety - bez ACK i odpowiedzi", la_akt);
			la_akt = 0xf;
		}
	} else if (wynik == W_OK) {
		n_tx_ok++;
	} else if (wynik == W_NACK) {
		n_tx_nack++;
	} else if (wynik == W_ODRZUCONA) {
		n_tx_odrz++;
	} else {
		n_tx_blad++;
	}
	notuj("tx %s %s%s", hex(&tx.r, h), wynik_txt[wynik],
	      tx.proby ? " (powt.)" : "");
	tx_nastepna(teraz, 5 * T_BIT);
}

/* zdarzenie nadawania o czasie tx.nast; pod blokada, w przerwaniu TMU2 */
static void tx_zdarzenie(s64 teraz)
{
	int v;

	if (tx.stan == TX_CZEKA) {
		dek_cisza(teraz);	/* urwana ramka nie blokuje nadawania */
		if (!linia_stan() || w_ramce || ack_trwa) {
			tx.nast = teraz + T_BIT;
			return;
		}
		if (teraz - t_ost < tx.wolne) {
			tx.nast = t_ost + tx.wolne;
			return;
		}
		tx.stan = TX_BIT;
		tx.bit = 0;
		tx.faza = 0;
		tx.t_bitu = teraz;
		tx.ack = 0;
	}
	switch (tx.faza) {
	case 3:		/* koniec bitu = poczatek nastepnego */
		tx.t_bitu += tx.bit == 0 ? T_START_CALY : T_BIT;
		tx.bit++;
		if (tx.bit >= cec_bitow(&tx.r)) {
			tx_koniec(W_OK, teraz);
			return;
		}
		if (teraz > tx.t_bitu + 200)
			tx.t_bitu = teraz;
		/* dalej */
	case 0:
		linia(0);
		tx.faza = 1;
		if (tx.bit == 0)
			tx.nast = tx.t_bitu + T_START_NISKI;
		else
			tx.nast = tx.t_bitu + (cec_bit(&tx.r, tx.bit) ?
					       T_JEDEN_NISKI : T_ZERO_NISKI);
		return;
	case 1:
		linia(1);
		if (tx.bit == 0) {
			tx.faza = 3;
			tx.nast = tx.t_bitu + T_START_CALY;
		} else if (cec_bit(&tx.r, tx.bit)) {
			tx.faza = 2;
			tx.nast = tx.t_bitu + T_PROBKA;
		} else {
			tx.faza = 3;
			tx.nast = tx.t_bitu + T_BIT;
		}
		return;
	case 2:		/* probka w bicie 1 */
		v = linia_stan();
		if (cec_bit_ack(tx.bit)) {
			int rozgl = (tx.r.b[0] & 0xf) == CEC_ROZGL;

			if (!v)
				tx.ack |= 1 << ((tx.bit - 1) / 10);
			if (rozgl ? !v : v) {
				tx_koniec(rozgl ? W_ODRZUCONA : W_NACK, teraz);
				return;
			}
		} else if (!v) {
			if (cec_bit_nadawcy(tx.bit)) {
				/* przegrany arbitraz: ramka tamtego leci dalej */
				n_tx_arb++;
				tx.stan = TX_CZEKA;
				tx.wolne = 7 * T_BIT;
				tx.nast = teraz + T_BIT;
				return;
			}
			tx_koniec(W_BLAD, teraz);
			return;
		}
		tx.faza = 3;
		tx.nast = tx.t_bitu + T_BIT;
		return;
	}
}

/* z kontekstu procesu: ramka do kolejki */
static int kolejkuj(const struct cec_tx *r)
{
	unsigned long f;
	int ok = 1;

	spin_lock_irqsave(&blokada, f);
	if ((k_zap + 1) % N_KOLEJKA == k_odcz) {
		n_tx_zgub++;
		ok = 0;
	} else {
		kolejka[k_zap] = *r;
		k_zap = (k_zap + 1) % N_KOLEJKA;
		if (tx.stan == TX_NIC && tmu_jest) {
			s64 t = teraz_us();

			tx_nastepna(t, 7 * T_BIT);
			planuj(t);
		}
	}
	spin_unlock_irqrestore(&blokada, f);
	return ok;
}

static irqreturn_t tmu_przerwanie(int irq, void *dev)
{
	unsigned long f;
	s64 teraz;

	__raw_writew(TCR_UNIE, TMU2_TCR);	/* kasuje UNF */
	spin_lock_irqsave(&blokada, f);
	teraz = teraz_us();
	if (ack_trwa && teraz >= ack_koniec - MARGINES) {
		linia(1);
		ack_trwa = 0;
	}
	if (tx.stan != TX_NIC && teraz >= tx.nast - MARGINES)
		tx_zdarzenie(teraz);
	planuj(teraz);
	spin_unlock_irqrestore(&blokada, f);
	return IRQ_HANDLED;
}

/* --- odbior --- */

#define N_ODEBR 16
static struct cec_tx odebrane[N_ODEBR];
static unsigned int o_odcz, o_zap;

#define N_KLAW 32
static struct {
	u8 op, kod;
} klawisze[N_KLAW];
static unsigned int kl_odcz, kl_zap;
static DECLARE_WAIT_QUEUE_HEAD(kl_kolejka);

static void praca_odp(struct work_struct *w);
static DECLARE_WORK(praca, praca_odp);

/* pod blokada, z przerwania GPIO (DEK_PO_RAMCE) */
static void po_ramce(const struct ramka *r)
{
	u8 od, do_;

	if (!r->eom || r->blad || r->n < 2 || la_akt == 0xf)
		return;
	od = r->b[0] >> 4;
	do_ = r->b[0] & 0xf;
	if (od == la_akt)
		return;
	if (do_ == la_akt &&
	    (r->b[1] == OP_UI_PRESSED || r->b[1] == OP_UI_RELEASED)) {
		if ((kl_zap + 1) % N_KLAW != kl_odcz) {
			klawisze[kl_zap].op = r->b[1];
			klawisze[kl_zap].kod = r->n > 2 ? r->b[2] : 0;
			kl_zap = (kl_zap + 1) % N_KLAW;
		}
		wake_up_interruptible(&kl_kolejka);
		return;
	}
	if (do_ != la_akt && !(do_ == CEC_ROZGL && r->b[1] == OP_SET_STREAM_PATH))
		return;
	if ((o_zap + 1) % N_ODEBR == o_odcz)
		return;
	odebrane[o_zap].n = r->n;
	memcpy(odebrane[o_zap].b, r->b, r->n);
	o_zap = (o_zap + 1) % N_ODEBR;
	schedule_work(&praca);
}

static irqreturn_t cec_przerwanie(int irq, void *dev)
{
	s64 teraz = teraz_us();
	int v = linia_stan();
	unsigned long f;

	spin_lock_irqsave(&blokada, f);
	if (time_after(jiffies, okno + HZ)) {
		okno = jiffies;
		w_oknie = 0;
	}
	if (++w_oknie > BURZA) {
		disable_irq_nosync(irq);
		burza = 1;
	}
	if (!v && ack && tx.stan != TX_BIT && dek_czas_na_ack(la_akt)) {
		linia(0);
		ack_trwa = 1;
		ack_koniec = teraz + T_ACK_NISKI;
		n_ack++;
		planuj(teraz);
	}
	dek_zbocze(v, teraz);
	t_ost = teraz;
	spin_unlock_irqrestore(&blokada, f);
	return IRQ_HANDLED;
}

/* --- odpowiedzi i adres fizyczny (kontekst procesu) --- */

#define CEC_ADDRESS "/sys/class/stmcoredisplay/hdmi0.0/cec_address"

static u16 czytaj_pa(void)
{
	struct file *f;
	char buf[32];
	int n;

	f = filp_open(CEC_ADDRESS, O_RDONLY, 0);
	if (IS_ERR(f))
		return 0;
	n = kernel_read(f, 0, buf, sizeof(buf) - 1);
	filp_close(f, NULL);
	return n > 0 ? cec_pa_z_tekstu(buf, n) : 0;
}

static u16 biezacy_pa(void)
{
	return adres_fiz ? (u16)adres_fiz : pa_ost;
}

static void zglos_adres(void)
{
	struct cec_tx r;
	u16 pa = biezacy_pa();

	if (la_akt == 0xf || !odpowiedzi || !pa)
		return;
	cec_tx_ustaw(&r, la_akt, CEC_ROZGL, OP_REPORT_PHYS_ADDR);
	cec_tx_dodaj(&r, pa >> 8);
	cec_tx_dodaj(&r, pa & 0xff);
	cec_tx_dodaj(&r, TYP_TUNER);
	kolejkuj(&r);
}

static void praca_odp(struct work_struct *w)
{
	struct cec_tx r, odp[CEC_MAX_ODP];
	struct cec_stan s;
	unsigned long f;
	int i, n;

	for (;;) {
		spin_lock_irqsave(&blokada, f);
		if (o_odcz == o_zap) {
			spin_unlock_irqrestore(&blokada, f);
			break;
		}
		r = odebrane[o_odcz];
		o_odcz = (o_odcz + 1) % N_ODEBR;
		spin_unlock_irqrestore(&blokada, f);
		if (!odpowiedzi)
			continue;
		s.la = la_akt;
		s.pa = biezacy_pa();
		s.standby = standby ? 1 : 0;
		s.vendor = vendor;
		s.nazwa = nazwa;
		n = cec_odpowiedz(&s, r.b, r.n, odp);
		for (i = 0; i < n; i++)
			kolejkuj(&odp[i]);
	}
}

static void praca_pa_fn(struct work_struct *w);
static DECLARE_DELAYED_WORK(praca_pa, praca_pa_fn);
static int pierwszy_obieg = 1;

#define BEZPIECZNIK_US 50000

/* zegar TMU2 nie przyszedl na czas: puszcza nozke, kasuje nadawanie */
static void bezpiecznik(void)
{
	unsigned long f;
	s64 teraz;
	int stoi;

	spin_lock_irqsave(&blokada, f);
	teraz = teraz_us();
	stoi = (tx.stan != TX_NIC && teraz > tx.nast + BEZPIECZNIK_US) ||
	       (ack_trwa && teraz > ack_koniec + BEZPIECZNIK_US);
	if (stoi) {
		linia(1);
		ack_trwa = 0;
		tx.stan = TX_NIC;
		k_odcz = k_zap;
		tmu_stop();
		n_zegar++;
	}
	spin_unlock_irqrestore(&blokada, f);
	if (stoi)
		notuj("BEZPIECZNIK: TMU2 nie odpowiada, nozka puszczona");
}

/* co 1 s: bezpiecznik, adres fizyczny ze stmfb; zmiana -> Report Physical Address */
static void praca_pa_fn(struct work_struct *w)
{
	u16 pa = czytaj_pa();

	bezpiecznik();
	if (pierwszy_obieg) {
		struct cec_tx sonda;

		pierwszy_obieg = 0;
		if (la_akt != 0xf) {
			sonda.n = 1;
			sonda.b[0] = (la_akt << 4) | la_akt;
			kolejkuj(&sonda);
		}
	}
	if (pa && pa != pa_ost) {
		notuj("adres fizyczny %x.%x.%x.%x", pa >> 12, (pa >> 8) & 0xf,
		      (pa >> 4) & 0xf, pa & 0xf);
		pa_ost = pa;
		zglos_adres();
	}
	schedule_delayed_work(&praca_pa, HZ);
}

/* --- /proc/cec_rx (jak cec_rx 1.2) --- */

static struct ramka kopia[N_RAMEK];
static DEFINE_MUTEX(czytanie);

static int cec_rx_show(struct seq_file *s, void *v)
{
	unsigned long f, k_ramek, k_zboczy, k_zgubione, k_szum, k_bledy;
	unsigned int i, n, ile;
	int k_burza;

	ile = pokaz;
	if (ile == 0 || ile > N_RAMEK)
		ile = N_RAMEK;
	mutex_lock(&czytanie);
	spin_lock_irqsave(&blokada, f);
	dek_cisza(teraz_us());
	k_ramek = n_ramek;
	k_zboczy = n_zboczy;
	k_zgubione = n_zgubione;
	k_szum = n_szum;
	k_bledy = n_bledy;
	k_burza = burza;
	for (i = N_RAMEK - ile, n = 0; i < N_RAMEK; i++) {
		struct ramka *r = &ramki[(poz + i) % N_RAMEK];

		if (r->nr)
			kopia[n++] = *r;
	}
	spin_unlock_irqrestore(&blokada, f);
	seq_printf(s, "# PIO %d.%d irq %d ramek %lu zboczy %lu zgubione %lu szum %lu bledy %lu%s\n",
		   port, pin, irq_nr, k_ramek, k_zboczy, k_zgubione, k_szum,
		   k_bledy, k_burza ? " BURZA - przerwanie wylaczone" : "");
	for (i = 0; i < n; i++)
		dek_wypisz(s, &kopia[i]);
	mutex_unlock(&czytanie);
	return 0;
}

static int cec_rx_open(struct inode *inode, struct file *file)
{
	return single_open(file, cec_rx_show, NULL);
}

static const struct file_operations cec_rx_fops = {
	.owner   = THIS_MODULE,
	.open    = cec_rx_open,
	.read    = seq_read,
	.llseek  = seq_lseek,
	.release = single_release,
};

/* --- /proc/nbox_cec --- */

static int stan_show(struct seq_file *s, void *v)
{
	unsigned long f;
	unsigned int i, od;
	u16 pa = biezacy_pa();

	seq_printf(s, "nbox_cec %s la %X pa %x.%x.%x.%x standby %d nazwa \"%s\" vendor %06x\n",
		   WERSJA, la_akt, pa >> 12, (pa >> 8) & 0xf, (pa >> 4) & 0xf,
		   pa & 0xf, standby, nazwa, vendor & 0xffffff);
	seq_printf(s, "ack %d odpowiedzi %d nozka %s e2proc %d tmu %u kHz irq %d/%d\n",
		   ack, odpowiedzi, nozka_nasza ? "nasza" : "wspolna (cec_ctrl)",
		   e2_nasze, tmu_khz, irq_nr, tmu_irq);
	seq_printf(s, "potwierdzone %lu tx ok %lu nack %lu odrzucone %lu arbitraz %lu bledy %lu zgubione %lu zegar %lu\n",
		   n_ack, n_tx_ok, n_tx_nack, n_tx_odrz, n_tx_arb, n_tx_blad,
		   n_tx_zgub, n_zegar);
	spin_lock_irqsave(&not_blokada, f);
	od = n_not > N_NOTATEK ? n_not - N_NOTATEK : 0;
	for (i = od; i < n_not; i++)
		seq_printf(s, "%lu.%03lu %s\n", notatki[i % N_NOTATEK].sek,
			   notatki[i % N_NOTATEK].ms, notatki[i % N_NOTATEK].t);
	spin_unlock_irqrestore(&not_blokada, f);
	return 0;
}

static int nadaj_z_hex(const char __user *buf, unsigned long count)
{
	char b[2 * MAX_BAJT + 4];
	struct cec_tx r;

	if (count >= sizeof(b))
		return -EINVAL;
	if (copy_from_user(b, buf, count))
		return -EFAULT;
	if (cec_z_hex(b, count, &r) < 0)
		return -EINVAL;
	if (!kolejkuj(&r))
		return -EBUSY;
	return count;
}

static ssize_t stan_write(struct file *file, const char __user *buf,
			  size_t count, loff_t *off)
{
	return nadaj_z_hex(buf, count);
}

static int stan_open(struct inode *inode, struct file *file)
{
	return single_open(file, stan_show, NULL);
}

static const struct file_operations stan_fops = {
	.owner   = THIS_MODULE,
	.open    = stan_open,
	.read    = seq_read,
	.write   = stan_write,
	.llseek  = seq_lseek,
	.release = single_release,
};

/* --- /proc/nbox_cec_klawisze --- */

static ssize_t kl_read(struct file *file, char __user *buf, size_t len,
		       loff_t *off)
{
	char t[N_KLAW * 7];
	unsigned long f;
	int n = 0;

	for (;;) {
		spin_lock_irqsave(&blokada, f);
		while (kl_odcz != kl_zap && n + 7 <= len) {
			if (klawisze[kl_odcz].op == OP_UI_PRESSED)
				n += sprintf(t + n, "44 %02x\n", klawisze[kl_odcz].kod);
			else
				n += sprintf(t + n, "45\n");
			kl_odcz = (kl_odcz + 1) % N_KLAW;
		}
		spin_unlock_irqrestore(&blokada, f);
		if (n)
			break;
		if (file->f_flags & O_NONBLOCK)
			return -EAGAIN;
		if (wait_event_interruptible(kl_kolejka, kl_odcz != kl_zap))
			return -ERESTARTSYS;
	}
	if (copy_to_user(buf, t, n))
		return -EFAULT;
	return n;
}

static unsigned int kl_poll(struct file *file, poll_table *wait)
{
	poll_wait(file, &kl_kolejka, wait);
	return kl_odcz != kl_zap ? POLLIN | POLLRDNORM : 0;
}

static const struct file_operations kl_fops = {
	.owner = THIS_MODULE,
	.read  = kl_read,
	.poll  = kl_poll,
};

/* --- /proc/stb/hdmi/cec (e2_proc, jak cec_ctrl) --- */

int remove_e2_procs(char *path, read_proc_t *read_func, write_proc_t *write_func);
int install_e2_procs(char *path, read_proc_t *read_func, write_proc_t *write_func, void *data);

static int e2_odczyt(char *page, char **start, off_t off, int count,
		     int *eof, void *data)
{
	*eof = 1;
	return 0;
}

static int e2_zapis(struct file *file, const char __user *buf,
		    unsigned long count, void *data)
{
	return nadaj_z_hex(buf, count);
}

/* --- start / stop --- */

static void tmu_start(void)
{
	tmu_khz = (__raw_readl(TMU0_TCOR) + 1) * HZ / 1000;
	__raw_writel(0xffffffff, TMU2_TCOR);
	__raw_writel(0xffffffff, TMU2_TCNT);
	__raw_writew(TCR_UNIE, TMU2_TCR);	/* Pphi/4, przerwanie na niedomiar */
	/* kanal stoi do pierwszego tmu_za() */
}

static void tmu_wylacz(void)
{
	__raw_writeb(__raw_readb(TMU_TSTR) & ~TSTR_STR2, TMU_TSTR);
	__raw_writew(0, TMU2_TCR);
}

static int __init nbox_cec_init(void)
{
	int r;

	gpio_nr = stm_gpio(port, pin);
	if (gpio_nr >= stm_gpio_num)
		return -EINVAL;
	/*
	 * stpio jak cec_ctrl (stm_gpio_direction nie jest eksportowane); NULL =
	 * nozke ma cec_ctrl (ten sam stm_pad_claim_gpio) - wtedy wspolnie.
	 */
	nozka = stpio_request_pin(port, pin, "nbox_cec", STPIO_BIDIR);
	if (nozka) {
		nozka_nasza = 1;
		gpio_set_value(gpio_nr, 1);
	}
	if (adres_log >= 0 && adres_log < 0xf)
		la_akt = adres_log;

	tmu_start();
	if (tmu_khz < 1000 || tmu_khz > 100000) {
		r = -ENODEV;
		goto bez_tmu;
	}
	r = request_irq(tmu_irq, tmu_przerwanie, IRQF_DISABLED, "nbox_cec_tmu", NULL);
	if (r)
		goto bez_tmu;
	tmu_jest = 1;

	poziom_pop = linia_stan();
	t_spadek = t_wzrost = t_ost = teraz_us();
	okno = jiffies;
	irq_nr = gpio_to_irq(gpio_nr);
	r = request_irq(irq_nr, cec_przerwanie,
			IRQF_TRIGGER_RISING | IRQF_TRIGGER_FALLING, "nbox_cec", NULL);
	if (r)
		goto bez_gpio_irq;

	if (!proc_create("cec_rx", 0444, NULL, &cec_rx_fops) ||
	    !proc_create("nbox_cec", 0644, NULL, &stan_fops) ||
	    !proc_create("nbox_cec_klawisze", 0444, NULL, &kl_fops)) {
		r = -ENOMEM;
		goto bez_proc;
	}
	if (nozka_nasza && e2proc) {
		install_e2_procs("stb/hdmi/cec", e2_odczyt, e2_zapis, NULL);
		e2_nasze = 1;
	}
	notuj("start %s, la %X, nozka %s", WERSJA, la_akt,
	      nozka_nasza ? "nasza" : "wspolna");
	schedule_delayed_work(&praca_pa, HZ / 10);
	return 0;

bez_proc:
	remove_proc_entry("nbox_cec_klawisze", NULL);
	remove_proc_entry("nbox_cec", NULL);
	remove_proc_entry("cec_rx", NULL);
	free_irq(irq_nr, NULL);
bez_gpio_irq:
	tmu_jest = 0;
	free_irq(tmu_irq, NULL);
bez_tmu:
	tmu_wylacz();
	if (nozka_nasza)
		stpio_free_pin(nozka);
	return r;
}

static void __exit nbox_cec_exit(void)
{
	unsigned long f;

	cancel_delayed_work_sync(&praca_pa);
	if (e2_nasze)
		remove_e2_procs("stb/hdmi/cec", e2_odczyt, e2_zapis);
	remove_proc_entry("nbox_cec_klawisze", NULL);
	remove_proc_entry("nbox_cec", NULL);
	remove_proc_entry("cec_rx", NULL);
	free_irq(irq_nr, NULL);
	spin_lock_irqsave(&blokada, f);
	tmu_jest = 0;
	tx.stan = TX_NIC;
	ack_trwa = 0;
	linia(1);
	spin_unlock_irqrestore(&blokada, f);
	tmu_wylacz();
	free_irq(tmu_irq, NULL);
	/* po TMU nikt juz nie zamknie ramki, wiec praca nie wroci */
	cancel_work_sync(&praca);
	if (nozka_nasza)
		stpio_free_pin(nozka);
}

module_init(nbox_cec_init);
module_exit(nbox_cec_exit);

MODULE_DESCRIPTION("HDMI-CEC nBoxa ADB 5800: odbior, ACK, odpowiedzi, nadawanie, pilot TV");
MODULE_LICENSE("GPL");
