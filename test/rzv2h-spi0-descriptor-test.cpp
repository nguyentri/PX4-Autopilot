/* Compile the actual board table and descriptor helpers with host declarations.
 * Expected pin values are independent literals from the GPIO descriptor ABI.
 */

#include <cassert>
#include <unistd.h>
#include "../boards/renesas/rdk-rzv2h/src/spi.cpp"

int main()
{
	static_assert(getGPIOPort(GPIO::Port9) == 0x90000000u, "GPIO port ABI");
	static_assert(getGPIOPin(GPIO::Pin4) == 0x04000000u, "GPIO pin ABI");
	static_assert((BOARD_ICM20948_DRDY_GPIO | RZV_GPIO_PULLUP) == 0x94000120u, "shared P94 plus PX4 pullup");
	constexpr auto no_drdy = initSPIDevice(DRV_IMU_DEVTYPE_ICM20948,
					       SPI::CS{GPIO::Port9, GPIO::Pin3});
	static_assert(no_drdy.cs_gpio == 0x93811000u, "P93 output/high/normal drive");
	static_assert(no_drdy.drdy_gpio == 0, "omitted DRDY must not configure P00");
	constexpr auto absent = initSPIBus(SPI::SPI0, {no_drdy});
	static_assert(absent.power_enable_gpio == 0, "omitted power must not drive P00");
	constexpr auto explicit_power = initSPIBus(SPI::SPI0, {no_drdy},
					GPIO::GPIOPin{GPIO::PortA, GPIO::Pin2});
	static_assert(explicit_power.power_enable_gpio == 0xa2010000u, "power output/LOW");
	constexpr auto explicit_drdy = initSPIDevice(DRV_IMU_DEVTYPE_ICM20948,
				       SPI::CS{GPIO::Port9, GPIO::Pin3}, SPI::DRDY{GPIO::Port9, GPIO::Pin4});
	static_assert(explicit_drdy.drdy_gpio == 0x94000120u, "P94 input/pullup/TINT");
	constexpr auto invalid_drdy = initSPIDevice(DRV_IMU_DEVTYPE_ICM20948,
				      SPI::CS{GPIO::Port9, GPIO::Pin3}, SPI::DRDY{GPIO::Port9, GPIO::PinInvalid});
	static_assert(invalid_drdy.drdy_gpio == 0, "invalid DRDY pin must remain absent");
	constexpr auto invalid_power = initSPIBus(SPI::SPI0, {no_drdy},
				       GPIO::GPIOPin{GPIO::PortInvalid, GPIO::Pin2});
	static_assert(invalid_power.power_enable_gpio == 0, "invalid power port must remain absent");
	static_assert(validateSPIConfig(px4_spi_buses), "actual board SPI bus map");

	unsigned active_devices = 0;
	unsigned active_buses = 0;

	for (const auto &bus : px4_spi_buses) {
		if (bus.bus < 0) {
			continue;
		}

		++active_buses;
		assert(bus.bus == 0 && !bus.is_external && !bus.requires_locking);
		assert(bus.power_enable_gpio == 0);

		for (const auto &device : bus.devices) {
			if (device.cs_gpio == 0) {
				continue;
			}

			++active_devices;
			assert(device.cs_gpio == 0x93811000u && device.drdy_gpio == 0x94000120u);
			assert(((device.cs_gpio >> 28) & 0xf) == 9 && ((device.cs_gpio >> 24) & 0xf) == 3);
			assert(((device.drdy_gpio >> 28) & 0xf) == 9 && ((device.drdy_gpio >> 24) & 0xf) == 4);
			assert(PX4_SPIDEVID_TYPE(device.devid) == PX4_SPI_DEVICE_ID);
#ifdef CONFIG_DRIVERS_IMU_INVENSENSE_ICM20948
			assert(device.devtype_driver == DRV_IMU_DEVTYPE_ICM20948);
			assert(PX4_SPI_DEV_ID(device.devid) == DRV_IMU_DEVTYPE_ICM20948);
#else
			assert(device.devtype_driver == DRV_IMU_DEVTYPE_MPU9250);
			assert(PX4_SPI_DEV_ID(device.devid) == DRV_IMU_DEVTYPE_MPU9250);
#endif
		}
	}

	assert(active_buses == 1 && active_devices == 1);
	return 0;
}
