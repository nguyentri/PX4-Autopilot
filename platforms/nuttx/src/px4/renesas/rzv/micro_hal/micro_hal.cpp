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
 * Default RDK bus7 is SCI7 simple-I2C. Native RIIC0..8 are opt-in and do not
 * add board routes. Guard each provider by its actual compilation gate.
 */
extern "C" {
	struct spi_dev_s *rzv_spibus_initialize(int bus);
#ifdef CONFIG_RZV_I2C
	struct i2c_master_s *board_i2c_initialize(int channel);
#endif
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
#if defined(CONFIG_RZV_I2C7) && defined(CONFIG_RZV_SCI7_I2C)

	if (bus == 7) {
		return nullptr;
	}

#endif

#ifdef CONFIG_RZV_I2C

	switch (bus) {
#ifdef CONFIG_RZV_I2C0

	case 0:
		return board_i2c_initialize(0);
#endif
#ifdef CONFIG_RZV_I2C1

	case 1:
		return board_i2c_initialize(1);
#endif
#ifdef CONFIG_RZV_I2C2

	case 2:
		return board_i2c_initialize(2);
#endif
#ifdef CONFIG_RZV_I2C3

	case 3:
		return board_i2c_initialize(3);
#endif
#ifdef CONFIG_RZV_I2C4

	case 4:
		return board_i2c_initialize(4);
#endif
#ifdef CONFIG_RZV_I2C5

	case 5:
		return board_i2c_initialize(5);
#endif
#ifdef CONFIG_RZV_I2C6

	case 6:
		return board_i2c_initialize(6);
#endif
#ifdef CONFIG_RZV_I2C7

	case 7:
		return board_i2c_initialize(7);
#endif
#ifdef CONFIG_RZV_I2C8

	case 8:
		return board_i2c_initialize(8);
#endif

	default:
		break;
	}

#endif

#ifdef CONFIG_RZV_SCI_I2C

	switch (bus) {
#ifdef CONFIG_RZV_SCI0_I2C

	case 0:
		return rzv_sci_i2c_initialize(0);
#endif
#ifdef CONFIG_RZV_SCI1_I2C

	case 1:
		return rzv_sci_i2c_initialize(1);
#endif
#ifdef CONFIG_RZV_SCI2_I2C

	case 2:
		return rzv_sci_i2c_initialize(2);
#endif
#ifdef CONFIG_RZV_SCI3_I2C

	case 3:
		return rzv_sci_i2c_initialize(3);
#endif
#ifdef CONFIG_RZV_SCI4_I2C

	case 4:
		return rzv_sci_i2c_initialize(4);
#endif
#ifdef CONFIG_RZV_SCI5_I2C

	case 5:
		return rzv_sci_i2c_initialize(5);
#endif
#ifdef CONFIG_RZV_SCI6_I2C

	case 6:
		return rzv_sci_i2c_initialize(6);
#endif
#ifdef CONFIG_RZV_SCI7_I2C

	case 7:
		return rzv_sci_i2c_initialize(7);
#endif
#ifdef CONFIG_RZV_SCI8_I2C

	case 8:
		return rzv_sci_i2c_initialize(8);
#endif
#ifdef CONFIG_RZV_SCI9_I2C

	case 9:
		return rzv_sci_i2c_initialize(9);
#endif

	default:
		break;
	}

#endif

	(void)bus;
	return nullptr;
}

/**
 * Uninitialize I2C bus
 *
 * Board RIIC and SCI masters retain one static board-lifetime owner.
 * PX4 borrows those pointers and must not release the board's cached owner.
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
