/*
 * cec_rx_test.c - test odbioru CEC na nBoxie ADB 5800 (STi7100, GraterliaOS,
 * jadro 2.6.32.61_stm24_0217): czy nozka PIO 3.7 - "pin_cec_rx" ze sterownika
 * cec_adb_box, tam w #if 0 - widzi linie CEC.
 *
 * Ustawia nozke jako wejscie i na kazdym zboczu (IRQ_TYPE_EDGE_BOTH) zapisuje
 * czas od poprzedniego zbocza i poziom po nim. Niczego nie nadaje. CEC: start
 * 3,7 ms niski + 0,8 ms wysoki, bit 2,4 ms (0 = 1,5 ms niski, 1 = 0,6 ms
 * niski) - jesli nozka widzi linie, nadanie z cec_ctrl (echo 308f >
 * /proc/stb/hdmi/cec) da tu ok. 40 zboczy z takimi czasami.
 *
 * /proc/cec_rx_test - odczyt: stan nozki, liczniki, ostatnie zbocza
 *                     ("<poziom po zboczu>:<us od poprzedniego>");
 *                     zapis czegokolwiek: zerowanie.
 *
 * Zabezpieczenie: wiecej niz BURZA zboczy w sekundzie (plywajaca nozka) ->
 * przerwanie wylaczone do rmmod.
 *
 * insmod cec_rx_test.ko [port=3 pin=7]
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/gpio.h>
#include <linux/interrupt.h>
#include <linux/irq.h>
#include <linux/proc_fs.h>
#include <linux/ktime.h>
#include <linux/jiffies.h>
#include <linux/spinlock.h>
#include <linux/stm/gpio.h>

static int port = 3;
static int pin = 7;
module_param(port, int, 0444);
module_param(pin, int, 0444);

#define N_ZBOCZY 512
#define POKAZ    200
#define BURZA    5000

static struct {
	u32 us;
	u8 poziom;
} zbocza[N_ZBOCZY];
static unsigned int poz;
static unsigned long ile, n_gora, n_dol, w_oknie;
static unsigned long okno;
static int burza;
static ktime_t ostatnie;
static int gpio_nr = -1, irq_nr = -1;
static DEFINE_SPINLOCK(blokada);

static irqreturn_t cec_rx_irq(int irq, void *dev)
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

static int proc_odczyt(char *strona, char **start, off_t off, int count,
		       int *eof, void *data)
{
	int len = 0, i, n;
	unsigned int p;
	unsigned long f;

	if (off > 0) {
		*eof = 1;
		return 0;
	}
	spin_lock_irqsave(&blokada, f);
	len += sprintf(strona + len,
		       "PIO %d.%d gpio %d irq %d stan %d zboczy %lu (w gore %lu, w dol %lu)%s\n",
		       port, pin, gpio_nr, irq_nr, gpio_get_value(gpio_nr),
		       ile, n_gora, n_dol,
		       burza ? " BURZA - przerwanie wylaczone" : "");
	n = ile < POKAZ ? ile : POKAZ;
	p = (poz + N_ZBOCZY - n) % N_ZBOCZY;
	for (i = 0; i < n && len < PAGE_SIZE - 32; i++) {
		len += sprintf(strona + len, "%u:%u%c", zbocza[p].poziom,
			       zbocza[p].us, (i % 10 == 9) ? '\n' : ' ');
		p = (p + 1) % N_ZBOCZY;
	}
	spin_unlock_irqrestore(&blokada, f);
	len += sprintf(strona + len, "\n");
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

static int __init cec_rx_test_init(void)
{
	struct proc_dir_entry *e;
	int r;

	gpio_nr = stm_gpio(port, pin);
	r = gpio_request(gpio_nr, "cec_rx_test");
	if (r) {
		printk(KERN_ERR "cec_rx_test: PIO %d.%d zajeta (%d)\n", port, pin, r);
		return r;
	}
	gpio_direction_input(gpio_nr);
	irq_nr = gpio_to_irq(gpio_nr);
	ostatnie = ktime_get();
	okno = jiffies;
	r = request_irq(irq_nr, cec_rx_irq,
			IRQF_TRIGGER_RISING | IRQF_TRIGGER_FALLING,
			"cec_rx_test", NULL);
	if (r) {
		printk(KERN_ERR "cec_rx_test: irq %d (%d)\n", irq_nr, r);
		gpio_free(gpio_nr);
		return r;
	}
	e = create_proc_entry("cec_rx_test", 0644, NULL);
	if (e) {
		e->read_proc = proc_odczyt;
		e->write_proc = proc_zapis;
	}
	printk(KERN_INFO "cec_rx_test: PIO %d.%d gpio %d irq %d stan %d\n",
	       port, pin, gpio_nr, irq_nr, gpio_get_value(gpio_nr));
	return 0;
}

static void __exit cec_rx_test_exit(void)
{
	remove_proc_entry("cec_rx_test", NULL);
	free_irq(irq_nr, NULL);
	gpio_free(gpio_nr);
}

module_init(cec_rx_test_init);
module_exit(cec_rx_test_exit);

MODULE_DESCRIPTION("Test odbioru CEC na PIO 3.7 (ADB 5800)");
MODULE_LICENSE("GPL");
