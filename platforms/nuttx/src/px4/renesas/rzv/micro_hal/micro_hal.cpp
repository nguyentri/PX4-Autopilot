/****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
 *
 ****************************************************************************/

/**
 * @file micro_hal.cpp
 *
 * RZV2H micro HAL implementation
 */

#include <px4_platform_common/px4_config.h>
#include <nuttx/config.h>
#include <nuttx/spi/spi.h>
#include <nuttx/i2c/i2c_master.h>

#include "../include/px4_arch/micro_hal.h"
#include "board_config.h"

/* External NuttX RZV driver functions */
extern "C" {
	struct spi_dev_s *rzv_spibus_initialize(int bus);
	struct i2c_master_s *rzv_i2cbus_initialize(int bus);
	int rzv_i2cbus_uninitialize(struct i2c_master_s *dev);
}

/**
 * Initialize SPI bus
 */
struct spi_dev_s *px4_spibus_initialize(int bus)
{
#ifdef CONFIG_RZV_SPI
	return rzv_spibus_initialize(bus);
#else
	return nullptr;
#endif
}

/**
 * Initialize I2C bus
 */
struct i2c_master_s *px4_i2cbus_initialize(int bus)
{
#ifdef CONFIG_RZV_I2C
	return rzv_i2cbus_initialize(bus);
#else
	return nullptr;
#endif
}

/**
 * Uninitialize I2C bus
 */
int px4_i2cbus_uninitialize(struct i2c_master_s *dev)
{
#ifdef CONFIG_RZV_I2C
	return rzv_i2cbus_uninitialize(dev);
#else
	return -ENODEV;
#endif
}

/**
 * Set I2C bus frequency
 */
int px4_i2cbus_set_bus_frequency(struct i2c_master_s *dev, uint32_t frequency)
{
	/* Frequency is typically set during I2C transfer configuration */
	(void)dev;
	(void)frequency;
	return 0;
}

/**
 * Scan I2C bus for devices
 */
int px4_i2cbus_scan(int bus, uint8_t *devices, int max_devices)
{
	/* I2C scan not implemented - would require probing addresses */
	(void)bus;
	(void)devices;
	(void)max_devices;
	return 0;
}

/**
 * Save panic information
 */
__attribute__((weak)) void rzv_save_panic(int fileno, void *context, int length)
{
	/* Panic save not implemented - could save to backup RAM or flash */
	(void)fileno;
	(void)context;
	(void)length;
}
