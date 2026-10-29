/*
 * cec_diag.c - diagnostyka nozek PIO na nBoxie ADB 5800 (STi7100, GraterliaOS,
 * jadro 2.6.32.61_stm24_0217), wersja 2 testu odbioru CEC.
 *
 * cec_rx_test (v1) nie wstal: gpio_request(PIO 3.7) = -EBUSY - nozke trzyma
 * cos w jadrze Graterlii, a kto - nie da sie odczytac (bez printk, debugfs,
 * kallsyms; klasa gpio i irq_desc nie sa eksportowane). Ten modul niczego nie
 * rezerwuje i nie zmienia trybu zadnej nozki.
 *
 * Domyslnie tylko odczyt: /proc/cec_diag - rejestry PIO 0-5 (PIN, POUT, PCOMP,
 * PMASK) i tryb kazdej nozki z PC2:PC1:PC0 (nazwy jak STPIO_* w
 * linux/stm/pio.h; 0 = wejscie z podciagnieciem).
 *
 * nasluch=1: przerwanie na obu zboczach PIO port.pin (domyslnie 3.7) bez
 * gpio_request - jadro rusza tylko bity PCOMP/PMASK tej nozki. Zbocza (poziom
 * po zboczu : us od poprzedniego) w /proc/cec_diag; zapis czegokolwiek do
 * /proc/cec_diag zeruje liczniki. Ponad BURZA zboczy/s -> przerwanie
 * wylaczone do rmmod. Jesli nozka jest za tranzystorem odwracajacym, linia
 * CEC w spoczynku (wysoko) daje na nozce 0, a ramka - impulsy w gore.
 *
 * insmod cec_diag.ko [nasluch=1] [port=3 pin=7]
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/gpio.h>
#include <linux/interrupt.h>
#include <linux/proc_fs.h>
#include <linux/ktime.h>
#include <linux/jiffies.h>
#include <linux/spinlock.h>
#include <linux/io.h>
#include <linux/stm/gpio.h>

static int nasluch;
static int port = 3;
static int pin = 7;
module_param(nasluch, int, 0444);
module_param(port, int, 0444);
module_param(pin, int, 0444);

#define PORTOW   6
#define N_ZBOCZY 512
#define POKAZ    150
#define BURZA    5000

/* offsety rejestrow PIO (drivers/stm/reg_pio.h) */
#define R_POUT  0x00
#define R_PIN   0x10
#define R_PC0   0x20
#define R_PC1   0x30
#define R_PC2   0x40
#define R_PCOMP 0x50
#define R_PMASK 0x60

static const char *tryby[8] = {
	"we-pu", "bidir", "wy", "3?", "we-hiz", "5?", "alt-wy", "alt-bidir"
};

static struct {
	u32 us;
	u8 poziom;
} zbocza[N_ZBOCZY];
static unsigned int poz;
static unsigned long ile, n_gora, n_dol, w_oknie, okno;
static int burza;
static ktime_t ostatnie;
static int gpio_nr = -1, irq_nr = -1, irq_ok;
static DEFINE_SPINLOCK(blokada);

static irqreturn_t diag_irq(int irq, void *dev)
{
	ktime_t teraz = ktime_get();
	int v = gpio_get_value(gpio_nr);
	s64 d = ktime_to_us(ktime_sub(teraz, ostatnie));
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
	ostatnie = teraz;
	zbocza[poz].us = d > 0xffffffffLL ? 0xffffffff : (u32)d;
	zbocza[poz].poziom = v ? 1 : 0;
	poz = (poz + 1) % N_ZBOCZY;
	ile++;
	if (v)
		n_gora++;
	else
		n_dol++;
	spin_unlock_irqrestore(&blokada, f);
	return IRQ_HANDLED;
}

static int proc_odczyt(char *s, char **start, off_t off, int count,
		       int *eof, void *data)
{
	int len = 0, n, i, p;
	unsigned int k;
	unsigned long f;

	if (off > 0) {
		*eof = 1;
		return 0;
	}
	for (n = 0; n < PORTOW && n * STM_GPIO_PINS_PER_PORT < stm_gpio_num; n++) {
		void __iomem *b = stm_gpio_bases[n];
		u32 pc0 = readl(b + R_PC0), pc1 = readl(b + R_PC1),
		    pc2 = readl(b + R_PC2), in = readl(b + R_PIN);

		len += sprintf(s + len, "PIO%d PIN=%02x POUT=%02x PCOMP=%02x PMASK=%02x |",
			       n, in & 0xff, readl(b + R_POUT) & 0xff,
			       readl(b + R_PCOMP) & 0xff, readl(b + R_PMASK) & 0xff);
		for (p = 0; p < STM_GPIO_PINS_PER_PORT; p++) {
			int t = ((pc2 >> p) & 1) << 2 | ((pc1 >> p) & 1) << 1 |
				((pc0 >> p) & 1);
			len += sprintf(s + len, " %d:%s=%d", p, tryby[t],
				       (in >> p) & 1);
		}
		len += sprintf(s + len, "\n");
	}
	if (!nasluch) {
		len += sprintf(s + len, "nasluch wylaczony (insmod cec_diag.ko nasluch=1)\n");
		*eof = 1;
		return len;
	}
	spin_lock_irqsave(&blokada, f);
	len += sprintf(s + len,
		       "nasluch PIO %d.%d gpio %d irq %d%s stan %d zboczy %lu (w gore %lu, w dol %lu)%s\n",
		       port, pin, gpio_nr, irq_nr, irq_ok ? "" : " NIEAKTYWNE",
		       gpio_get_value(gpio_nr), ile, n_gora, n_dol,
		       burza ? " BURZA - przerwanie wylaczone" : "");
	i = ile < POKAZ ? ile : POKAZ;
	k = (poz + N_ZBOCZY - i) % N_ZBOCZY;
	for (n = 0; n < i && len < PAGE_SIZE - 32; n++) {
		len += sprintf(s + len, "%u:%u%c", zbocza[k].poziom, zbocza[k].us,
			       (n % 10 == 9) ? '\n' : ' ');
		k = (k + 1) % N_ZBOCZY;
	}
	spin_unlock_irqrestore(&blokada, f);
	len += sprintf(s + len, "\n");
	*eof = 1;
	return len;
}

static int proc_zapis(struct file *plik, const char __user *bufor,
		      unsigned long count, void *data)
{
	unsigned long f;

	spin_lock_irqsave(&blokada, f);
	poz = 0;
	ile = n_gora = n_dol = 0;
	spin_unlock_irqrestore(&blokada, f);
	return count;
}

static int __init cec_diag_init(void)
{
	struct proc_dir_entry *e;
	int r;

	gpio_nr = stm_gpio(port, pin);
	if (nasluch) {
		if (gpio_nr >= stm_gpio_num)
			return -EINVAL;
		irq_nr = gpio_to_irq(gpio_nr);
		ostatnie = ktime_get();
		okno = jiffies;
		r = request_irq(irq_nr, diag_irq,
				IRQF_TRIGGER_RISING | IRQF_TRIGGER_FALLING,
				"cec_diag", NULL);
		if (r)
			return r;
		irq_ok = 1;
	}
	e = create_proc_entry("cec_diag", 0644, NULL);
	if (!e) {
		if (irq_ok)
			free_irq(irq_nr, NULL);
		return -ENOMEM;
	}
	e->read_proc = proc_odczyt;
	e->write_proc = proc_zapis;
	return 0;
}

static void __exit cec_diag_exit(void)
{
	remove_proc_entry("cec_diag", NULL);
	if (irq_ok)
		free_irq(irq_nr, NULL);
}

module_init(cec_diag_init);
module_exit(cec_diag_exit);

MODULE_DESCRIPTION("Diagnostyka PIO i nasluch CEC bez rezerwacji nozki (ADB 5800)");
MODULE_LICENSE("GPL");
