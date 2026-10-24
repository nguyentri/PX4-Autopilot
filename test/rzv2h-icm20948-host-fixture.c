#include "rzv2h-icm20948-host-stubs.h"
#include "board-under-test.c"
#include "icm20948-under-test.c"

static struct spi_dev_s controller = {0};
static unsigned int configurations, writes, exchanges, selects, locks, unlocks;
static uint32_t last_pin;
static uint32_t configured_pins[16];
static bool last_level, locked, selected;
static int fail_pin, fail_register, fail_lock, fail_unlock;
static bool fail_init;
static uint32_t actual_frequency = 1000000;
static uint8_t commands[2][13];
static size_t lengths[2];

int rzv_gpioconfig(uint32_t pin)
{
	assert(configurations < 16);
	configured_pins[configurations] = pin;
	configurations++;
	return fail_pin == (int)configurations ? -EIO : 0;
}

void rzv_gpiowrite(uint32_t pin, bool level)
{
	writes++;
	last_pin = pin;
	last_level = level;
}

struct spi_dev_s *rzv_spibus_initialize(int port)
{
	assert(port == 0);
	return fail_init ? NULL : &controller;
}

int rzv_spibus_uninitialize(struct spi_dev_s *dev)
{
	assert(dev == &controller);
	return 0;
}

int spi_register(struct spi_dev_s *dev, int port)
{
	assert(dev == &controller && port == 0);
	return fail_register;
}

int host_lock(struct spi_dev_s *dev, bool lock)
{
	assert(dev == &controller);
	if (lock) {
		locks++;
		assert(!locked);
		if (fail_lock) { return fail_lock; }
		locked = true;
		return 0;
	}

	unlocks++;
	assert(locked);
	locked = false;
	return fail_unlock;
}

void host_mode(struct spi_dev_s *dev, int mode)
{
	assert(dev == &controller && locked && mode == 3);
}

void host_bits(struct spi_dev_s *dev, int bits)
{
	assert(dev == &controller && locked && bits == 8);
}

uint32_t host_frequency(struct spi_dev_s *dev, uint32_t frequency)
{
	assert(dev == &controller && locked && frequency == 1000000);
	return actual_frequency;
}

void host_select(struct spi_dev_s *dev, uint32_t id, bool active)
{
	assert(locked && id == SPIDEV_ACCELEROMETER(0));
	selects++;
	selected = active;
	rzv_spi_select(dev, id, active);
}

void host_exchange(struct spi_dev_s *dev, const void *tx, void *rx, size_t len)
{
	assert(dev == &controller && locked && selected);
	assert(exchanges < 2 && len <= sizeof(commands[0]));
	lengths[exchanges] = len;
	memcpy(commands[exchanges++], tx, len);
	if (rx) { memset(rx, 0x5a, len); }
}

static void clear_traffic(void)
{
	writes = exchanges = selects = locks = unlocks = 0;
}

int main(int argc, char **argv)
{
	assert(argc == 2);
	const char *scenario = argv[1];
	if (!strcmp(scenario, "pin-retry")) { fail_pin = 2; }
	if (!strcmp(scenario, "init-retry")) { fail_init = true; }
	if (!strcmp(scenario, "register-retry")) { fail_register = -EIO; }
	if (fail_pin || fail_init || fail_register) {
		assert(board_spi_initialize() < 0);
		clear_traffic();
		rzv_spi_select(&controller, SPIDEV_ACCELEROMETER(0), true);
		assert(writes == 0); /* Failed init must not publish a device. */
		fail_pin = fail_register = 0;
		fail_init = false;
	}
	assert(board_spi_initialize() == 0);
	assert(configurations >= 4);
	for (unsigned int i = 0; i < configurations; i++) {
		assert(configured_pins[i] != GPIO_P9_4_INPUT);
		assert(configured_pins[i] != GPIO_TINT_P9_4);
	}
	assert(configured_pins[configurations - 4] == BOARD_SPI0_MOSI_GPIO);
	assert(configured_pins[configurations - 3] == BOARD_SPI0_MISO_GPIO);
	assert(configured_pins[configurations - 2] == BOARD_SPI0_SCK_GPIO);
	assert(configured_pins[configurations - 1] == BOARD_SPI0_SS0_GPIO);
#if defined(CONFIG_RZV2H_SPI0_HARDWARE_SSL)
	assert(BOARD_SPI0_SS0_GPIO ==
	       (GPIO_SSLA0_P9_3_M1 | RZV_GPIO_PERIPH | RZV_GPIO_DRVSTR_HIGH));
	assert(writes == 0);
#else
	assert(BOARD_SPI0_SS0_GPIO == GPIO_P9_3_OUTPUT_HIGH);
	assert(last_pin == GPIO_P9_3_OUTPUT_HIGH && last_level);
#endif
	const unsigned int configured = configurations;
	assert(board_spi_initialize() == 0 && configurations == configured);
	assert(BOARD_ICM20948_DRDY_GPIO == GPIO_TINT_P9_4);
	clear_traffic();
	if (strstr(scenario, "retry")) { return 0; }

	if (!strcmp(scenario, "foreign-device")) {
		struct spi_dev_s other = {1};
		rzv_spi_select(&other, SPIDEV_ACCELEROMETER(0), true);
		assert(writes == 0);
		return 0;
	}
	if (!strcmp(scenario, "select")) {
		const uint32_t ids[] = {SPIDEV_ACCELEROMETER(0), 0x12345678};
		for (unsigned int i = 0; i < 2; i++) {
			rzv_spi_select(&controller, ids[i], true);
#if defined(CONFIG_RZV2H_SPI0_HARDWARE_SSL)
			assert(writes == 0);
#elif defined(CONFIG_RZV2H_SPI_INTERNAL_LOOPBACK_SAMPLE)
			assert(last_pin == BOARD_SPI0_SS0_GPIO && last_level);
#else
			assert(last_pin == BOARD_SPI0_SS0_GPIO && !last_level);
#endif
			rzv_spi_select(&controller, ids[i], false);
#ifndef CONFIG_RZV2H_SPI0_HARDWARE_SSL
			assert(last_level);
#endif
		}
		return 0;
	}

	uint8_t data[12];
	memset(data, 0xa5, sizeof(data));
	if (!strcmp(scenario, "invalid")) {
		assert(icm20948_read(&controller, 4, 0, data, 1) == -EINVAL);
		assert(icm20948_read(&controller, 0, 0, data, 0) == -EINVAL);
		assert(icm20948_read(&controller, 0, 0, data, 13) == -EINVAL);
		assert(icm20948_write(&controller, 4, 0, 0) == -EINVAL);
		assert(icm20948_write(&controller, 0, 0x80, 0) == -EINVAL);
		assert(locks == 0 && exchanges == 0 && writes == 0);
		return 0;
	}
	if (!strcmp(scenario, "lock-error")) { fail_lock = -EBUSY; }
	if (!strcmp(scenario, "frequency-zero")) { actual_frequency = 0; }
	if (!strcmp(scenario, "frequency-high")) { actual_frequency = 1000001; }
	if (!strcmp(scenario, "unlock-error")) { fail_unlock = -EIO; }
	int result;
	if (!strcmp(scenario, "write")) {
		result = icm20948_write(&controller, 2, 0x14, 0x11);
		assert(result == 0 && lengths[1] == 2);
		assert(commands[1][0] == 0x14 && commands[1][1] == 0x11);
	} else {
		result = icm20948_read(&controller, 2, 0x2d, data, sizeof(data));
		if (fail_lock) {
			assert(result == -EBUSY && unlocks == 0 && exchanges == 0);
			return 0;
		}
		if (actual_frequency == 0 || actual_frequency > 1000000) {
			assert(result == -ERANGE && exchanges == 0 && !locked && !selected);
			assert(data[0] == 0xa5);
			return 0;
		}
		assert(result == fail_unlock);
		assert(lengths[1] == 13 && commands[1][0] == (0x2d | 0x80));
		assert(data[0] == (fail_unlock ? 0xa5 : 0x5a));
	}
	assert(commands[0][0] == 0x7f && commands[0][1] == 0x20);
	assert(lengths[0] == 2 && exchanges == 2 && selects == 5);
	assert(locks == 1 && unlocks == 1 && !locked && !selected);
	return 0;
}
