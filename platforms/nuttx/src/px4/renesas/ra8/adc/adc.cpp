/****************************************************************************
 *
 *   Copyright (C) 2025 PX4 Development Team. All rights reserved.
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
 * @file adc.cpp
 *
 * RA8 ADC-B driver for PX4
 *
 * This provides the PX4 architecture ADC interface for the Renesas RA8P1
 * MCU's ADC-B (Advanced ADC with FIFO) peripheral.
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/micro_hal.h>
#include <px4_platform_common/log.h>

#include <drivers/drv_adc.h>
#include <drivers/drv_hrt.h>

#include <sys/types.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <errno.h>
#include <stdio.h>

#include <arch/board/board.h>
#include <nuttx/analog/adc.h>
#include <nuttx/arch.h>
#include "arm_internal.h"

#include <board_config.h>

#ifdef CONFIG_ADC

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

/* Register bit definitions */
#define ADCLKENR_CLKEN          (1 << 0)
#define ADCLKSR_CLKSR           (1 << 0)
#define ADCALSTR_ADCALST0       (1 << 0)
#define ADCALSTR_ADCALST1       (1 << 8)
#define ADCALENDSR_CALENDF0     (1 << 0)
#define ADCALENDSR_CALENDF1     (1 << 1)
#define ADSTR_ADST              (1 << 0)

/* Timeout values */
#define ADC_CLOCK_TIMEOUT_US    1000
#define ADC_CAL_TIMEOUT_US      100000
#define ADC_CONV_TIMEOUT_US     10000

/* Default timing */
#define ADC_DEFAULT_SAMPLING    24
#define ADC_DEFAULT_CONVERSION  18

/****************************************************************************
 * Private Types
 ****************************************************************************/

/* ADC driver state */
struct ra8_adc_state_s
{
	bool     initialized;
	bool     calibrated;
	uint32_t base_address;
	uint8_t  resolution;      /* 0=16bit, 1=14bit, 2=12bit, 3=10bit */
};

/****************************************************************************
 * Private Data
 ****************************************************************************/

static struct ra8_adc_state_s g_adc_state = {
	.initialized = false,
	.calibrated = false,
	.base_address = R_ADC_B_BASE,
	.resolution = 2,  /* 12-bit default */
};

/****************************************************************************
 * Private Functions
 ****************************************************************************/

static inline void adc_putreg(uint32_t offset, uint32_t value)
{
	putreg32(value, g_adc_state.base_address + offset);
}

static inline uint32_t adc_getreg(uint32_t offset)
{
	return getreg32(g_adc_state.base_address + offset);
}

/**
 * Enable ADC clock
 */
static int adc_clock_enable(void)
{
	uint32_t timeout = ADC_CLOCK_TIMEOUT_US;

	/* Configure clock source (PCLKC / 1) */
	adc_putreg(R_ADC_B_ADCLKCR_OFFSET, 0);

	/* Enable clock */
	adc_putreg(R_ADC_B_ADCLKENR_OFFSET, ADCLKENR_CLKEN);

	/* Wait for clock to stabilize */
	while (timeout > 0) {
		if (adc_getreg(R_ADC_B_ADCLKSR_OFFSET) & ADCLKSR_CLKSR) {
			return 0;
		}

		up_udelay(1);
		timeout--;
	}

	return -ETIMEDOUT;
}

/**
 * Perform ADC calibration
 */
static int adc_calibrate(void)
{
	uint32_t timeout = ADC_CAL_TIMEOUT_US;
	uint32_t regval;

	/* Start calibration for both ADC units */
	adc_putreg(R_ADC_B_ADCALSTR_OFFSET, ADCALSTR_ADCALST0 | ADCALSTR_ADCALST1);

	/* Wait for calibration to complete */
	while (timeout > 0) {
		regval = adc_getreg(R_ADC_B_ADCALENDSR_OFFSET);

		if ((regval & (ADCALENDSR_CALENDF0 | ADCALENDSR_CALENDF1)) ==
		    (ADCALENDSR_CALENDF0 | ADCALENDSR_CALENDF1)) {
			/* Clear calibration end flags */
			adc_putreg(R_ADC_B_ADCALENDSCR_OFFSET,
				   ADCALENDSR_CALENDF0 | ADCALENDSR_CALENDF1);
			return 0;
		}

		up_udelay(1);
		timeout--;
	}

	return -ETIMEDOUT;
}

/**
 * Configure a single ADC channel for conversion
 */
static void adc_configure_channel(unsigned channel)
{
	/* Configure channel control register */
	uint32_t regval = (0 << 0) |           /* Scan group 0 */
			  (channel << 8) |     /* Physical channel */
			  (0 << 16);           /* Sampling table 0 */
	adc_putreg(R_ADC_B_ADCHCR_OFFSET(0), regval);

	/* No digital filter */
	adc_putreg(R_ADC_B_ADDOPCRA_OFFSET(0), 0);

	/* No averaging */
	adc_putreg(R_ADC_B_ADDOPCRB_OFFSET(0), 0);

	/* Set resolution (12-bit = 0x20000) */
	adc_putreg(R_ADC_B_ADDOPCRC_OFFSET(0), (g_adc_state.resolution << 16));
}

/****************************************************************************
 * Public Functions
 ****************************************************************************/

int px4_arch_adc_init(uint32_t base_address)
{
	int ret;

	if (g_adc_state.initialized) {
		return 0;
	}

	if (base_address != 0) {
		g_adc_state.base_address = base_address;
	}

	/* Enable ADC clock */
	ret = adc_clock_enable();

	if (ret < 0) {
		PX4_ERR("ADC clock enable failed: %d", ret);
		return ret;
	}

	/* Set SAR single scan mode */
	adc_putreg(R_ADC_B_ADMDR_OFFSET, 0);

	/* Configure sampling time */
	adc_putreg(R_ADC_B_ADSSTR0_OFFSET, ADC_DEFAULT_SAMPLING);

	/* Configure conversion time */
	adc_putreg(R_ADC_B_ADCNVSTR_OFFSET, ADC_DEFAULT_CONVERSION);

	/* Perform calibration */
	if (!g_adc_state.calibrated) {
		ret = adc_calibrate();

		if (ret < 0) {
			PX4_ERR("ADC calibration failed: %d", ret);
			return ret;
		}

		g_adc_state.calibrated = true;
	}

	/* Enable scan group 0 */
	adc_putreg(R_ADC_B_ADSGER_OFFSET, 1);

	/* Configure scan group 0 to use ADC0 */
	adc_putreg(R_ADC_B_ADSGCR0_OFFSET, 0);

	g_adc_state.initialized = true;

	PX4_INFO("RA8 ADC-B initialized");

	return 0;
}

void px4_arch_adc_uninit(uint32_t base_address)
{
	if (!g_adc_state.initialized) {
		return;
	}

	/* Stop any ongoing conversion */
	adc_putreg(R_ADC_B_ADSTOPR_OFFSET, 0x0101);

	/* Disable scan groups */
	adc_putreg(R_ADC_B_ADSGER_OFFSET, 0);

	/* Disable clock */
	adc_putreg(R_ADC_B_ADCLKENR_OFFSET, 0);

	g_adc_state.initialized = false;
	g_adc_state.calibrated = false;
}

uint32_t px4_arch_adc_sample(unsigned channel)
{
	uint32_t timeout = ADC_CONV_TIMEOUT_US;
	uint32_t regval;

	if (!g_adc_state.initialized) {
		if (px4_arch_adc_init(0) < 0) {
			return 0;
		}
	}

	/* Configure the channel */
	adc_configure_channel(channel);

	/* Start conversion */
	adc_putreg(R_ADC_B_ADSTR_OFFSET(0), ADSTR_ADST);

	/* Wait for conversion to complete */
	while (timeout > 0) {
		regval = adc_getreg(R_ADC_B_ADSCANENDSR_OFFSET);

		if (regval & 1) {
			/* Clear scan end flag */
			adc_putreg(R_ADC_B_ADSCANENDSCR_OFFSET, 1);

			/* Read result */
			regval = adc_getreg(R_ADC_B_ADDR_OFFSET(0));

			/* Check for error */
			if (regval & (1U << 31)) {
				PX4_WARN("ADC conversion error on channel %u", channel);
				return 0;
			}

			return regval & 0xFFFF;
		}

		up_udelay(1);
		timeout--;
	}

	PX4_WARN("ADC conversion timeout on channel %u", channel);
	return 0;
}

float px4_arch_adc_reference_v()
{
	/* Return ADC reference voltage for RA8 (typically 3.3V) */
	return 3.3f;
}

uint32_t px4_arch_adc_temp_sensor_mask()
{
	/* Return temperature sensor channel mask (channel 32) - not supported */
    return 0;
}

uint32_t px4_arch_adc_dn_fullcount()
{
	/* Return full-scale ADC count based on resolution */
	switch (g_adc_state.resolution) {
	case 0:
		return 65535;  /* 16-bit */

	case 1:
		return 16383;  /* 14-bit */

	case 2:
		return 4095;   /* 12-bit */

	case 3:
		return 1023;   /* 10-bit */

	default:
		return 4095;
	}
}

#endif /* CONFIG_ADC */
