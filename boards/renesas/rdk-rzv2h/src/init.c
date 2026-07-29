/****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in
 *    the documentation and/or other materials provided with the
 *    distribution.
 * 3. Neither the name PX4 nor the names of its contributors may be
 *    used to endorse or promote products derived from this software
 *    without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 * FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
 * BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
 * OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
 * AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 * ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 *
 ****************************************************************************/

/**
 * @file init.c
 *
 * RDK-RZV2H board early initialization
 */

#include <px4_platform_common/init.h>
#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/console_buffer.h>
#include <px4_arch/io_timer.h>

#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <debug.h>
#include <syslog.h>

/* Hardware version definition */
static const char hw_type[] = "RDK-RZV2H";

#if defined(__PX4_NUTTX)
#include <nuttx/board.h>
#include <nuttx/i2c/i2c_master.h>
#include <drivers/drv_sensor.h>
#include "rzv_gpio.h"
#include <arch/board/board.h>
#ifdef CONFIG_RZV_OPENAMP
#include "rzv_ipc.h"
#endif
#endif

#include "board_config.h"
/* board_config.h includes board_common.h at the end, so redundant include removed */
/* Undefine macros from board_common.h so we can implement the functions */
#undef board_get_hw_type_name

/* External function declarations */
extern struct i2c_master_s *px4_i2cbus_initialize(int bus);
#ifdef CONFIG_RDK_RZV2H_XSPI_PARAMFS
extern int rzv2h_xspi_paramfs_initialize(void);
#endif
#ifdef CONFIG_RDK_RZV2H_VOLATILE_PARAMFS
extern int rzv2h_volatile_paramfs_initialize(void);
#endif

#if defined(__PX4_NUTTX)
void rzv2h_serial_setup(void)
{
	/* Board SCI macros own the complete PORT|PIN|PSEL|RZV_GPIO_PERIPH
	 * configuration. This function is invoked from the arch serial driver's
	 * rzv_setup() on first console/port open.
	 */
#if defined(CONFIG_RZV_SCI3) || defined(CONFIG_SCI3_SERIAL_CONSOLE)
	px4_arch_configgpio(BOARD_SCI3_TXD_GPIO);
	px4_arch_configgpio(BOARD_SCI3_RXD_GPIO);
#endif

#if defined(CONFIG_RZV_SCI4)
	px4_arch_configgpio(BOARD_P7_0_GPIO);
	px4_arch_configgpio(BOARD_P7_1_GPIO);
#endif

#if defined(CONFIG_RZV_SCI5)
	px4_arch_configgpio(BOARD_P7_2_GPIO);
	px4_arch_configgpio(BOARD_P7_3_GPIO);
#endif

#if defined(CONFIG_RZV_SCI6)
	px4_arch_configgpio(BOARD_P7_5_GPIO);
#endif

#if defined(CONFIG_RZV_SCI9)
	px4_arch_configgpio(BOARD_P8_2_GPIO);
	px4_arch_configgpio(BOARD_P8_3_GPIO);
#endif
}
#endif

#if defined(CONFIG_RZV_OPENAMP)
static int rdk_rzv2h_openamp_initialize(void)
{
	int ret = rzv_ipc_initialize();

	if (ret < 0) {
		syslog(LOG_ERR, "board_app_initialize: rzv_ipc_initialize() failed: %d\n", ret);
		return ret;
	}

#if defined(CONFIG_RZV_IPC_IPCC)
	ret = rzv_ipcc_initialize();

	if (ret < 0) {
		syslog(LOG_ERR, "board_app_initialize: rzv_ipcc_initialize() failed: %d\n", ret);
		return ret;
	}

	syslog(LOG_INFO, "board_app_initialize: RZ/V2H OpenAMP IPCC ready at /dev/ipcc0\n");
#endif

	return OK;
}
#endif

/****************************************************************************
 * Protected Functions
 ****************************************************************************/

/****************************************************************************
 * Public Functions
 ****************************************************************************/

/************************************************************************************
 * Name: board_peripheral_reset
 *
 * Description:
 *   Called to reset peripherals on the board.
 *
 ************************************************************************************/

__EXPORT void board_peripheral_reset(int ms)
{
	/* set the peripheral rails off */

	/* wait for the peripheral rail to reach GND */
	usleep(ms * 1000);

	/* re-enable power */

	/* switch the peripheral rail back on */
}

/************************************************************************************
 * Name: board_on_reset
 *
 * Description:
 *   Optionally provided function called on entry to board_system_reset
 *   It should perform any house keeping prior to the rest.
 *
 * Input Parameters:
 *   status - 1 if resetting to boot loader
 *            0 if just resetting
 *
 ************************************************************************************/

__EXPORT void board_on_reset(int status)
{
	/* configure the GPIO pins to outputs and keep them low */

	if (status >= 0) {
		up_mdelay(6);
	}
}

/************************************************************************************
 * Name: rdk_rzv2h_gpio_initialize
 *
 * Description:
 *   Called to configure all GPIOs for the board except those controlled by NuttX Drivers
 *
 ************************************************************************************/

static void rdk_rzv2h_gpio_initialize(void)
{
	/* Configure LEDs */
#ifdef GPIO_nLED_1
	px4_arch_configgpio(GPIO_nLED_1);
#endif
#ifdef GPIO_nLED_2
	px4_arch_configgpio(GPIO_nLED_2);
#endif
#ifdef GPIO_nLED_3
	px4_arch_configgpio(GPIO_nLED_3);
#endif
#ifdef GPIO_nLED_4
	px4_arch_configgpio(GPIO_nLED_4);
#endif

	/* Configure MPU9250 DRDY only when the payload driver is linked. */
#if defined(CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250) && defined(BOARD_MPU9250_DRDY_GPIO)
	px4_arch_configgpio(BOARD_MPU9250_DRDY_GPIO);
#endif

	/* Serial pins are owned by the NuttX RZ/V2H board serial setup.
	 * Do not configure stale low-numbered SCI macros here: the first
	 * channel's TX alternate overlaps MPU9250 DRDY on P50, and the PX4
	 * flight UART map uses sparse SCI4/5/6/9.
	 */

	/* SCI7-I2C pins are owned and configured by the NuttX lower-half. */
}

/************************************************************************************
 * Name: board_app_initialize
 *
 * Description:
 *   Perform application specific initialization.  This function is never called
 *   directly from application code, but only indirectly via the (non-standard)
 *   boardctl() interface using the command BOARDIOC_INIT.
 *
 * Input Parameters:
 *   arg - The boardctl() argument is passed to the board_app_initialize()
 *         implementation without modification.  The argument has no
 *         meaning to NuttX; the meaning of the argument is a contract
 *         between the board-specific initialization logic and the
 *         matching application logic.  The value could be such things as a
 *         mode enumeration value, a set of DIP switch settings, a pointer
 *         to other configuration data read from a file or serial FLASH, or
 *         whatever you would like to do with it.  Every implementation
 *         should accept zero/NULL as a default configuration.
 *
 * Returned Value:
 *   Zero (OK) is returned on success; a negated errno value is returned on
 *   any failure to indicate the nature of the failure.
 *
 ************************************************************************************/

__EXPORT int board_app_initialize(uintptr_t arg)
{
	int ret;

	/* Initialize the CR8-0-local PX4 platform first. Optional remote cores and
	 * transports must never gate HRT, work queues, parameters, uORB, or the
	 * local sensor/actuator path.
	 */
	ret = px4_platform_init();

	if (ret != OK) {
		syslog(LOG_ERR, "board_app_initialize: px4_platform_init() failed with error %d\n", ret);
		return ret;
	}

#ifdef CONFIG_RDK_RZV2H_XSPI_PARAMFS
	ret = rzv2h_xspi_paramfs_initialize();

	if (ret != OK) {
		syslog(LOG_WARNING,
		       "board_app_initialize: optional XSPI paramfs unavailable (%d); continuing\n",
		       ret);
	}
#endif

#ifdef CONFIG_RDK_RZV2H_VOLATILE_PARAMFS
	ret = rzv2h_volatile_paramfs_initialize();

	if (ret != OK) {
		syslog(LOG_WARNING,
		       "board_app_initialize: volatile paramfs unavailable (%d); continuing\n",
		       ret);
	}
#endif

#if defined(CONFIG_RZV_OPENAMP)
	/* OpenAMP is opt-in and best-effort. A missing CA55 endpoint must not
	 * prevent the standalone CR8-0 PX4 image from starting.
	 */
	ret = rdk_rzv2h_openamp_initialize();

	if (ret != OK) {
		syslog(LOG_WARNING,
		       "board_app_initialize: optional OpenAMP unavailable (%d); continuing CR8-0 standalone\n",
		       ret);
	}
#endif

	/* configure LEDs */
	board_autoled_initialize();

	/* configure pins */
	rdk_rzv2h_gpio_initialize();

	/* The core-only image must not mux or initialize actuator outputs. HRT is
	 * already initialized by px4_platform_init() and is independent of these
	 * output timers.
	 */
#if defined(CONFIG_DRIVERS_PWM_OUT) || defined(CONFIG_DRIVERS_DSHOT)
	ret = rdk_rzv2h_timer_initialize();

	if (ret != OK) {
		syslog(LOG_ERR, "board_app_initialize: timer initialization failed with error %d\n", ret);
		return ret;
	}
#endif

	/* Initialize the board-owned SPI path for the IMU. This configures the
	 * SPI0 pinmux and GPIO chip select before the PX4 sensor driver obtains
	 * the idempotent lower-half through px4_spibus_initialize().
	 */
#ifdef CONFIG_RZV_SPI
	ret = board_spi_initialize();

	if (ret != OK) {
		syslog(LOG_ERR, "board_app_initialize: board_spi_initialize() failed with error %d\n", ret);
		return ret;
	}
#endif

	/* Initialize I2C bus for barometer sensor (SCI-mode simple-I2C).
	 * Gated on CONFIG_RZV_SCI_I2C so it activates only when the SCI-I2C
	 * lower-half is enabled.
	 */
#ifdef CONFIG_RZV_SCI_I2C
	struct i2c_master_s *i2c7 = px4_i2cbus_initialize(PX4_I2C_BUS_EXPANSION);
	if (i2c7 == NULL) {
		syslog(LOG_ERR, "board_app_initialize: px4_i2cbus_initialize(%d) returned NULL!\n", PX4_I2C_BUS_EXPANSION);
	}
#endif

	/* Reset SPI buses to ensure clean state for sensor communication. */
#ifdef CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250
	board_spi_reset(10, 0xffff);
#endif

	return OK;
}

/************************************************************************************
 * Name: rzv_board_initialize
 *
 * Description:
 *   All RZV architectures must provide the following entry point.  This entry point
 *   is called early in the initialization -- after all memory has been configured
 *   and mapped but before any devices have been initialized.
 *
 ************************************************************************************/

__EXPORT void rzv_board_initialize(void)
{
	/* Reset PWM first thing */
	board_on_reset(-1);

	/* Configure GPIOs */
	rdk_rzv2h_gpio_initialize();
}

__EXPORT const char *board_get_hw_type_name(void)
{
	return (const char *) hw_type;
}
