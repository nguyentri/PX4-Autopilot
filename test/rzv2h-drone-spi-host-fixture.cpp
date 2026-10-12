/* Execute production PX4 descriptors and the production NuttX CS callback.
 * Only controller/GPIO operations cross the host boundary.
 */
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <syslog.h>
#include <unistd.h>

#include "../boards/renesas/rdk-rzv2h/src/spi.cpp"
/* board_common.h is shimmed on the host; mirror its non-manifest bus contract. */
#ifdef BOARD_HAS_BUS_MANIFEST
#error "the host bus contract assumes every configured SPI bus is present"
#endif
enum board_bus_types { BOARD_INVALID_BUS = 0, BOARD_SPI_BUS = 1 };
#define board_has_bus(t, b) true
#include "../platforms/common/spi.cpp"

#define UNUSED(x) ((void)(x))
#define spiinfo(...) ((void)0)
#define spiwarn(...) ((void)0)
#define SPI_STATUS_PRESENT 1
#define OK 0

struct spi_dev_s { int port; };
extern "C" {
	int rzv_gpioconfig(uint32_t pin);
	int rzv_gpiowrite(uint32_t pin, bool high);
	spi_dev_s * rzv_spibus_initialize(int port);
	int spi_register(spi_dev_s * dev, int port);
#include "board-select-under-test.inc"
}

static spi_dev_s controller{0};
static bool levels[] = {true, true, true};
static bool configured[3];
static unsigned configs, writes, starts;
static unsigned fail_config;
static bool fail_start;
static bool checking_early_gpio;
static unsigned early_gpio_calls;
#define px4_arch_configgpio rzv_gpioconfig
#include "board-gpio-under-test.inc"

int rzv_gpioconfig(uint32_t pin)
{
	if (checking_early_gpio) {
		assert((pin & (GPIO_PORT_MASK | GPIO_PIN_MASK)) != (uint32_t(PORT9) | PIN4));
		++early_gpio_calls;
		return 0;
	}

	++configs;

	if (fail_config == configs) { return -EIO; }

	const unsigned index = (pin & GPIO_PIN_MASK) >> GPIO_PIN_SHIFT;
	assert((pin & GPIO_PORT_MASK) == uint32_t(PORT9));

	if (index >= 3 && index <= 5) {
		assert((pin & GPIO_MODE_MASK) == RZV_GPIO_OUTPUT);
		assert(pin & RZV_GPIO_INITIAL_HIGH);
		configured[index - 3] = true;

	} else {
		assert(index < 3 && configured[0] && configured[1] && configured[2]);
		assert(levels[0] && levels[1] && levels[2]);
	}

	return 0;
}

int rzv_gpiowrite(uint32_t pin, bool high)
{
	const unsigned index = (pin & GPIO_PIN_MASK) >> GPIO_PIN_SHIFT;
	assert(index >= 3 && index <= 5 && configured[index - 3]);
	levels[index - 3] = high;
	++writes;
	assert(unsigned(!levels[0]) + unsigned(!levels[1]) + unsigned(!levels[2]) <= 1);
	return 0;
}

spi_dev_s *rzv_spibus_initialize(int port)
{
	assert(port == 0 && configured[0] && configured[1] && configured[2]);
	assert(levels[0] && levels[1] && levels[2]);
	++starts;
	return fail_start ? nullptr : &controller;
}

int spi_register(spi_dev_s *dev, int port)
{
	assert(dev == &controller && port == 0);
	return 0;
}

/* Resolve each `-c <pin>` the startup script passes through the production
 * PX4 bus iterator; every pin must select exactly its own descriptor. */
static int iterate_chip_selects(int count, char **pins)
{
	for (int i = 0; i < count; ++i) {
		const int pin = std::atoi(pins[i]);
		SPIBusIterator iterator(SPIBusIterator::FilterType::InternalBus, DRV_IMU_DEVTYPE_ICM45686, pin, 0);
		assert(iterator.next());
		assert(iterator.bus().bus == 0 && !iterator.external());
		const int index = iterator.busDeviceIndex();
		assert(spi_cs_pin(px4_spi_buses[0].devices[index].cs_gpio) == pin);
		assert(!iterator.next());
		std::printf("cs %d -> device %d\n", pin, index);
	}

	SPIBusIterator all(SPIBusIterator::FilterType::InternalBus, DRV_IMU_DEVTYPE_ICM45686, -1, 0);
	int matches = 0;

	while (all.next()) { ++matches; }

	assert(matches == 3);
	SPIBusIterator absent(SPIBusIterator::FilterType::InternalBus, DRV_IMU_DEVTYPE_ICM45686, 6, 0);
	assert(!absent.next());
	return 0;
}

int main(int argc, char **argv)
{
	if (argc >= 2 && !std::strcmp(argv[1], "iterate")) { return iterate_chip_selects(argc - 2, argv + 2); }

	assert(argc == 2);
	const char *scenario = argv[1];
	checking_early_gpio = true;
	rdk_rzv2h_gpio_initialize();
	assert(early_gpio_calls > 0);
	checking_early_gpio = false;
	rzv_spi_select(nullptr, 0, true);
	assert(writes == 0);
	uint32_t ids[3];

	for (unsigned i = 0; i < 3; ++i) {
		const auto &device = px4_spi_buses[0].devices[i];
		ids[i] = device.devid;
		assert(device.drdy_gpio == 0);
		assert(device.devtype_driver == DRV_IMU_DEVTYPE_ICM45686);
		assert((device.cs_gpio & GPIO_PORT_MASK) == uint32_t(PORT9));
		assert((device.cs_gpio & GPIO_PIN_MASK) == ((i + 3) << GPIO_PIN_SHIFT));
		assert(ids[i] == PX4_SPIDEV_ID(PX4_SPI_DEVICE_ID, DRV_IMU_DEVTYPE_ICM45686 | (i << 8)));
	}

	assert(px4_spi_buses[0].devices[3].cs_gpio == 0);
	assert(board_spi_initialize() == -EINVAL && starts == 0 && configs == 0);
	assert(board_spi_configure_device_ids(nullptr, 3) == -EINVAL);
	assert(board_spi_configure_device_ids(ids, 2) == -EINVAL);
	uint32_t duplicate[3] = {ids[0], ids[0], ids[2]};
	assert(board_spi_configure_device_ids(duplicate, 3) == -EINVAL);
	uint32_t zero[3] = {ids[0], 0, ids[2]};
	assert(board_spi_configure_device_ids(zero, 3) == -EINVAL);
	assert(board_spi_initialize() == -EINVAL && configs == 0);
	assert(rdk_rzv2h_configure_sensor_cs() == 0);

	if (!std::strcmp(scenario, "pin-retry")) { fail_config = 2; }

	if (!std::strcmp(scenario, "controller-retry")) { fail_start = true; }

	if (fail_config || fail_start) {
		assert(board_spi_initialize() < 0);
		const auto before = writes;
		rzv_spi_select(&controller, ids[0], true);
		assert(writes == before && rzv_spi_status(&controller, ids[0]) == 0);
		fail_config = 0;
		fail_start = false;
	}

	assert(board_spi_initialize() == 0);
	const auto before = configs;
	assert(board_spi_initialize() == 0 && configs == before);
	assert(rdk_rzv2h_configure_sensor_cs() == 0);
	uint32_t changed[3] = {ids[0], ids[1], ids[2] + 1};
	assert(board_spi_configure_device_ids(changed, 3) == -EBUSY);

	for (unsigned repeat = 0; repeat < 3; ++repeat) {
		for (unsigned i = 0; i < 3; ++i) {
			rzv_spi_select(&controller, ids[i], true);

			for (unsigned j = 0; j < 3; ++j) { assert(levels[j] == (i != j)); }

			assert(rzv_spi_status(&controller, ids[i]) == SPI_STATUS_PRESENT);
		}
	}

	for (uint32_t invalid : {0u, 0x12345678u, changed[2]}) {
		rzv_spi_select(&controller, invalid, true);
		assert(levels[0] && levels[1] && levels[2]);
		assert(rzv_spi_status(&controller, invalid) == 0);
	}
	rzv_spi_select(&controller, ids[1], true);
	rzv_spi_select(&controller, ids[1], false);
	assert(levels[0] && levels[1] && levels[2]);
	spi_dev_s foreign{1};
	const auto before_foreign = writes;
	rzv_spi_select(&foreign, ids[0], true);
	assert(writes == before_foreign && rzv_spi_status(&foreign, ids[0]) == 0);
	return 0;
}
