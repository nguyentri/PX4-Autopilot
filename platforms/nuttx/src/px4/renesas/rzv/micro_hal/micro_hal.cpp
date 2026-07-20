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

/* External NuttX RZV driver functions.
 *
 * RDK-RZ/V2H I2C buses are SCI-mode simple-I2C (rzv_sci_i2c.c), not the RIIC
 * native controller. The SCI-I2C initializer is only linked when
 * CONFIG_RZV_SCI_I2C is enabled; guard every reference accordingly.
 */
extern "C" {
	struct spi_dev_s *rzv_spibus_initialize(int bus);
#ifdef CONFIG_RZV_SCI_I2C
	struct i2c_master_s *rzv_sci_i2c_initialize(int channel);
#endif
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
#ifdef CONFIG_RZV_SCI_I2C
	/* The PX4 logical bus number maps directly to the SCI channel:
	 * bus 7 == SCI7 == BMP280 barometer on RDK-RZ/V2H.
	 */
	return rzv_sci_i2c_initialize(bus);
#else
	(void)bus;
	return nullptr;
#endif
}

/**
 * Uninitialize I2C bus
 *
 * SCI-I2C masters use static per-channel state and are never torn down, so
 * there is no lower-half uninitialize to call.
 */
int px4_i2cbus_uninitialize(struct i2c_master_s *dev)
{
	(void)dev;
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
