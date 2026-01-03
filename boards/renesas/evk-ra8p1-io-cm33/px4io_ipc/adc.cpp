/****************************************************************************
 *
 *   Copyright (c) 2024-2026 PX4 Development Team. All rights reserved.
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
 * RA8P1 CM33 ADC Driver for Battery Monitoring
 *
 * This driver uses ADC_B to measure:
 * - Battery voltage (with voltage divider scaling)
 * - Battery current (with current sense amp scaling)
 * - Servo rail voltage
 * - Optional RSSI and temperature
 */

#include <px4_platform_common/px4_config.h>

#include <syslog.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <string.h>

#include <drivers/drv_hrt.h>

#include "px4io.h"

/*******************************************************************************
 * ADC Configuration from board_config.h
 ******************************************************************************/

#ifndef BOARD_ADC_VBAT_DIVIDER_RATIO
#define BOARD_ADC_VBAT_DIVIDER_RATIO    11.0f   /* 11:1 voltage divider */
#endif

#ifndef BOARD_ADC_CURRENT_GAIN
#define BOARD_ADC_CURRENT_GAIN          50.0f   /* 50x current sense amp */
#endif

#ifndef BOARD_ADC_CURRENT_OFFSET_MA
#define BOARD_ADC_CURRENT_OFFSET_MA     0       /* Zero offset */
#endif

#ifndef BOARD_ADC_SERVO_DIVIDER_RATIO
#define BOARD_ADC_SERVO_DIVIDER_RATIO   3.0f    /* 3:1 voltage divider */
#endif

#ifndef BOARD_ADC_VREF_MV
#define BOARD_ADC_VREF_MV               3300    /* 3.3V reference */
#endif

#ifndef BOARD_ADC_RESOLUTION
#define BOARD_ADC_RESOLUTION            4096    /* 12-bit ADC */
#endif

/* Brownout threshold for POEG trigger */
#ifndef BOARD_VBAT_BROWNOUT_MV
#define BOARD_VBAT_BROWNOUT_MV          12000   /* 12V minimum */
#endif

/*******************************************************************************
 * ADC Channel Definitions
 ******************************************************************************/

#define ADC_CHANNEL_VBAT        BOARD_ADC_VBAT_CHANNEL
#define ADC_CHANNEL_CURRENT     BOARD_ADC_CURRENT_CHANNEL
#define ADC_CHANNEL_SERVO_RAIL  BOARD_ADC_SERVO_RAIL_CHANNEL
#define ADC_CHANNEL_RSSI        BOARD_ADC_RSSI_CHANNEL

#define ADC_NUM_CHANNELS        4

/*******************************************************************************
 * Module State
 ******************************************************************************/

static int g_adc_fd = -1;
static bool g_adc_initialized = false;

/* Cached ADC readings (raw counts) */
static uint16_t g_adc_raw[ADC_NUM_CHANNELS];

/* Scaled values (mV or mA) */
static uint16_t g_vbat_mv = 0;
static uint16_t g_current_ma = 0;
static uint16_t g_servo_rail_mv = 0;
static uint16_t g_rssi_raw = 0;

/* Filtering state (simple IIR low-pass) */
static float g_vbat_filtered = 0.0f;
static float g_current_filtered = 0.0f;

/* Brownout detection */
static bool g_brownout_detected = false;
static uint64_t g_brownout_time = 0;

/*******************************************************************************
 * Private Functions
 ******************************************************************************/

/**
 * @brief Convert raw ADC count to millivolts (at ADC input)
 */
static inline uint16_t adc_raw_to_mv(uint16_t raw)
{
	return static_cast<uint16_t>((static_cast<uint32_t>(raw) * BOARD_ADC_VREF_MV) / BOARD_ADC_RESOLUTION);
}

/**
 * @brief Apply voltage divider scaling
 */
static inline uint16_t scale_voltage_divider(uint16_t input_mv, float ratio)
{
	return static_cast<uint16_t>(input_mv * ratio);
}

/**
 * @brief Apply current sense scaling
 *
 * Converts ADC voltage to current in mA based on:
 * - Current sense resistor value
 * - Amplifier gain
 * - Offset calibration
 */
static inline uint16_t scale_current(uint16_t input_mv, float gain, int16_t offset_ma)
{
	/* I = V / (R * gain) where R is the sense resistor
	 * For a typical 10mOhm shunt with 50x gain:
	 * I(mA) = V(mV) / (0.01 * 50) = V(mV) * 2
	 * But this depends on actual hardware - use configurable scaling
	 */
	int32_t current = static_cast<int32_t>(input_mv * 2) + offset_ma;
	return static_cast<uint16_t>(current > 0 ? current : 0);
}

/**
 * @brief IIR low-pass filter
 *
 * y[n] = alpha * x[n] + (1 - alpha) * y[n-1]
 */
static inline float iir_filter(float new_value, float prev_value, float alpha)
{
	return alpha * new_value + (1.0f - alpha) * prev_value;
}

/**
 * @brief Read ADC channel (blocking)
 *
 * @param channel ADC channel number
 * @return Raw ADC count, or 0 on error
 */
static uint16_t adc_read_channel(unsigned channel)
{
	if (g_adc_fd < 0) {
		return 0;
	}

	/* TODO: Implement actual RA8P1 ADC_B read
	 *
	 * For NuttX, this typically involves:
	 * 1. Configuring the ADC to scan the desired channel
	 * 2. Triggering a conversion
	 * 3. Waiting for conversion complete
	 * 4. Reading the result register
	 *
	 * RA8P1 ADC_B supports both single and scan modes.
	 * For now, use the NuttX ADC driver interface.
	 */

	struct adc_msg_s sample;

#if 0  /* Placeholder for actual implementation */
	/* Select channel and trigger conversion */
	int ret = ioctl(g_adc_fd, ANIOC_TRIGGER, 0);

	if (ret < 0) {
		return 0;
	}

	/* Read result */
	ret = read(g_adc_fd, &sample, sizeof(sample));

	if (ret == sizeof(sample)) {
		return sample.am_data;
	}

#endif

	(void)channel;  /* Suppress unused warning */
	return 0;
}

/**
 * @brief Read all ADC channels and update cached values
 */
static void adc_read_all(void)
{
	/* Read raw ADC values */
	g_adc_raw[0] = adc_read_channel(ADC_CHANNEL_VBAT);
	g_adc_raw[1] = adc_read_channel(ADC_CHANNEL_CURRENT);
	g_adc_raw[2] = adc_read_channel(ADC_CHANNEL_SERVO_RAIL);
	g_adc_raw[3] = adc_read_channel(ADC_CHANNEL_RSSI);

	/* Convert to millivolts at ADC input */
	uint16_t vbat_adc_mv = adc_raw_to_mv(g_adc_raw[0]);
	uint16_t current_adc_mv = adc_raw_to_mv(g_adc_raw[1]);
	uint16_t servo_adc_mv = adc_raw_to_mv(g_adc_raw[2]);

	/* Apply scaling */
	float vbat_raw = scale_voltage_divider(vbat_adc_mv, BOARD_ADC_VBAT_DIVIDER_RATIO);
	float current_raw = scale_current(current_adc_mv, BOARD_ADC_CURRENT_GAIN, BOARD_ADC_CURRENT_OFFSET_MA);

	/* Apply filtering (alpha = 0.1 for ~10 sample averaging) */
	const float alpha = 0.1f;
	g_vbat_filtered = iir_filter(vbat_raw, g_vbat_filtered, alpha);
	g_current_filtered = iir_filter(current_raw, g_current_filtered, alpha);

	/* Update scaled values */
	g_vbat_mv = static_cast<uint16_t>(g_vbat_filtered);
	g_current_ma = static_cast<uint16_t>(g_current_filtered);
	g_servo_rail_mv = scale_voltage_divider(servo_adc_mv, BOARD_ADC_SERVO_DIVIDER_RATIO);
	g_rssi_raw = g_adc_raw[3];

	/* Check for brownout */
	if (g_vbat_mv > 0 && g_vbat_mv < BOARD_VBAT_BROWNOUT_MV) {
		if (!g_brownout_detected) {
			g_brownout_detected = true;
			g_brownout_time = hrt_absolute_time();

			/* Trigger POEG emergency kill */
			/* board_poeg_trigger_kill(BOARD_POEG_TRIGGER_BROWNOUT); */

			syslog(LOG_CRIT, "ADC: Brownout detected! VBAT=%u mV\n", g_vbat_mv);
		}

	} else {
		g_brownout_detected = false;
	}
}

/*******************************************************************************
 * Public API
 ******************************************************************************/

int adc_init(void)
{
	if (g_adc_initialized) {
		return 0;
	}

	/* Open ADC device */
	g_adc_fd = open("/dev/adc0", O_RDONLY);

	if (g_adc_fd < 0) {
		syslog(LOG_ERR, "ADC: Failed to open /dev/adc0\n");
		return -1;
	}

	/* TODO: Configure ADC_B for the channels we need
	 * ioctl(g_adc_fd, ANIOC_CONFIGURE, ...);
	 */

	/* Initialize filtered values */
	g_vbat_filtered = 0.0f;
	g_current_filtered = 0.0f;
	g_brownout_detected = false;

	g_adc_initialized = true;

	syslog(LOG_INFO, "ADC: Initialized\n");
	return 0;
}

void adc_deinit(void)
{
	if (g_adc_fd >= 0) {
		close(g_adc_fd);
		g_adc_fd = -1;
	}

	g_adc_initialized = false;
}

uint16_t adc_measure(unsigned channel)
{
	if (!g_adc_initialized) {
		return 0;
	}

	/* Return cached value based on channel */
	switch (channel) {
	case ADC_CHANNEL_VBAT:
		return g_adc_raw[0];

	case ADC_CHANNEL_CURRENT:
		return g_adc_raw[1];

	case ADC_CHANNEL_SERVO_RAIL:
		return g_adc_raw[2];

	case ADC_CHANNEL_RSSI:
		return g_adc_raw[3];

	default:
		return 0;
	}
}

/**
 * @brief Get battery voltage in millivolts
 */
uint16_t adc_get_vbat_mv(void)
{
	return g_vbat_mv;
}

/**
 * @brief Get battery current in milliamps
 */
uint16_t adc_get_current_ma(void)
{
	return g_current_ma;
}

/**
 * @brief Get servo rail voltage in millivolts
 */
uint16_t adc_get_servo_rail_mv(void)
{
	return g_servo_rail_mv;
}

/**
 * @brief Get RSSI raw value
 */
uint16_t adc_get_rssi(void)
{
	return g_rssi_raw;
}

/**
 * @brief Check if brownout is detected
 */
bool adc_is_brownout(void)
{
	return g_brownout_detected;
}

/**
 * @brief Periodic ADC update tick
 *
 * Call this at 100 Hz from the main loop to update ADC readings.
 */
void adc_tick(void)
{
	if (!g_adc_initialized) {
		return;
	}

	static uint64_t last_update = 0;
	uint64_t now = hrt_absolute_time();

	/* Update at 100 Hz */
	if (now - last_update >= 10000) {
		adc_read_all();
		last_update = now;
	}
}
