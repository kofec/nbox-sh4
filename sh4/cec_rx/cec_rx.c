/*
 * cec_rx.c - podsluch linii HDMI-CEC na nBoxie ADB 5800 (STi7100, GraterliaOS,
 * jadro 2.6.32.61_stm24_0217). Tylko odbior: niczego nie nadaje, nie
 * potwierdza (ACK) i nie rezerwuje nozki.
 *
 * Linia CEC jest na PIO 4.4 - tej samej nozce, na ktorej nadaje cec_ctrl
 * (cec_adb_box, tryb bidir open-drain, wiec PIN pokazuje faktyczny stan
 * linii). Sprawdzone 2026-10-21 na nBoxach BSLA (Sony) i BSKA (Samsung):
 * wlasna ramka 30:8f i odpowiedz Sony dekoduja sie z czasow zboczy.
 *
 * Przerwanie na obu zboczach bez gpio_request (jadro rusza tylko bity
 * PCOMP/PMASK tej nozki); dekoder w cec_rx_dekoder.h (test: test_dekoder.c).
 *
 * /proc/cec_rx (seq_file) - linia "#" ze statystyka, potem `pokaz` ostatnich
 * ramek od najstarszej (bufor N_RAMEK), format w dek_wypisz(). Kolejne nr
 * rosna, wiec logger dopisuje tylko nowe (cec_rx_log.sh).
 *
 * Zabezpieczenie: ponad BURZA zboczy/s -> przerwanie wylaczone do rmmod.
 *
 * insmod cec_rx.ko [port=4 pin=4] [pokaz=64]
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
#include <linux/stm/gpio.h>

static void czas_ramki(unsigned long *sek, unsigned long *ms)
{
	struct timeval tv = ktime_to_timeval(ktime_get_real());

	*sek = tv.tv_sec;
	*ms = tv.tv_usec / 1000;
}

#define DEK_CZAS(s, m)		czas_ramki(&(s), &(m))
#define DEK_PRINTF(c, ...)	seq_printf((struct seq_file *)(c), __VA_ARGS__)
#include "cec_rx_dekoder.h"

static int port = 4;
static int pin = 4;
module_param(port, int, 0444);
module_param(pin, int, 0444);

/*
 * Ile ostatnich ramek pokazuje /proc/cec_rx (bufor dalej N_RAMEK). 256 linii
 * pod spin_lock_irqsave to dlugo bez przerwan, a wtyczka nBox CEC czyta co
 * 2 s; do analiz: echo 256 > /sys/module/cec_rx/parameters/pokaz.
 */
static unsigned int pokaz = 64;
module_param(pokaz, uint, 0644);

#define BURZA 5000

static unsigned long w_oknie, okno;
static int burza;
static int gpio_nr = -1, irq_nr = -1;
static DEFINE_SPINLOCK(blokada);

static irqreturn_t cec_rx_irq(int irq, void *dev)
{
	s64 teraz = ktime_to_us(ktime_get());
	int v = gpio_get_value(gpio_nr) ? 1 : 0;
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
	dek_zbocze(v, teraz);
	spin_unlock_irqrestore(&blokada, f);
	return IRQ_HANDLED;
}

/* kopia pod blokada, wypisywanie bez niej; mutex - kilku czytelnikow naraz */
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
	dek_cisza(ktime_to_us(ktime_get()));
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

static int __init cec_rx_init(void)
{
	int r;

	gpio_nr = stm_gpio(port, pin);
	if (gpio_nr >= stm_gpio_num)
		return -EINVAL;
	poziom_pop = gpio_get_value(gpio_nr) ? 1 : 0;
	t_spadek = t_wzrost = ktime_to_us(ktime_get());
	okno = jiffies;
	irq_nr = gpio_to_irq(gpio_nr);
	r = request_irq(irq_nr, cec_rx_irq,
			IRQF_TRIGGER_RISING | IRQF_TRIGGER_FALLING,
			"cec_rx", NULL);
	if (r)
		return r;
	if (!proc_create("cec_rx", 0444, NULL, &cec_rx_fops)) {
		free_irq(irq_nr, NULL);
		return -ENOMEM;
	}
	return 0;
}

static void __exit cec_rx_exit(void)
{
	remove_proc_entry("cec_rx", NULL);
	free_irq(irq_nr, NULL);
}

module_init(cec_rx_init);
module_exit(cec_rx_exit);

MODULE_DESCRIPTION("Podsluch HDMI-CEC na PIO 4.4 (ADB 5800), tylko odbior");
MODULE_LICENSE("GPL");
