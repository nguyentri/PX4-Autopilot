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
 * @file pwm_out.cpp
 *
 * PWM and DShot output driver for RA8P1 CM33 IO processor.
 * Uses GPT timers (GPT3, GPT5, GPT11, GPT13) for motor control.
 * Supports both standard PWM (400Hz-490Hz) and DShot (150-1200).
 * Uses DMAC1 channels 10-17 for DShot frame generation.
 *
 * @author PX4 Development Team
 */

#include <px4_platform_common/px4_config.h>
#include <nuttx/config.h>
#include <nuttx/arch.h>
#include <nuttx/irq.h>

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <syslog.h>

#include <drivers/drv_hrt.h>
#include <arch/board/board.h>

#include "px4io.h"
#include "board_config.h"

#ifdef CONFIG_RA_DMAC
#include "ra_dmac.h"
#endif

#ifdef CONFIG_RA_GPT
#include "ra_gpt.h"
#include "hardware/ra8p1/ra_gpt32.h"
#include "hardware/ra8p1/ra_gpt_poeg.h"
#endif

#include "arm_internal.h"
#include "ra_mstp.h"

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

/* Number of motor output channels */
#define PWM_OUT_MAX_CHANNELS    4

/* GPT timer assignments for motors (CM33 uses GPT3, GPT5, GPT11, GPT13) */
#define MOTOR1_GPT_CHANNEL      3
#define MOTOR2_GPT_CHANNEL      5
#define MOTOR3_GPT_CHANNEL      11
#define MOTOR4_GPT_CHANNEL      13

/* DMAC1 channels for CM33 DShot (channels 10-17 available) */
#define DSHOT_DMA_CH_MOTOR1     10
#define DSHOT_DMA_CH_MOTOR2     11
#define DSHOT_DMA_CH_MOTOR3     12
#define DSHOT_DMA_CH_MOTOR4     13

/* GPT clock frequency (PCLKD = 250MHz for CM33) */
#ifndef BOARD_PCLKD_FREQUENCY
#define BOARD_PCLKD_FREQUENCY   250000000u
#endif

/* PWM frequency range */
#define PWM_FREQ_MIN            50      /* Hz */
#define PWM_FREQ_MAX            500     /* Hz */
#define PWM_FREQ_DEFAULT        400     /* Hz */

/* PWM pulse width range (microseconds) */
#define PWM_PULSE_MIN           800     /* us - minimum pulse */
#define PWM_PULSE_MAX           2200    /* us - maximum pulse */
#define PWM_PULSE_DISARMED      900     /* us - disarmed pulse */
#define PWM_PULSE_FAILSAFE      900     /* us - failsafe pulse */

/* DShot protocol definitions */
#define DSHOT_FRAME_BITS        16
#define DSHOT_THROTTLE_BITS     11
#define DSHOT_TELEMETRY_BIT     1
#define DSHOT_CHECKSUM_BITS     4

#define DSHOT150_FREQ           150000u
#define DSHOT300_FREQ           300000u
#define DSHOT600_FREQ           600000u
#define DSHOT1200_FREQ          1200000u

/* DShot timing (percentage of bit period) */
#define DSHOT_T0H_PERCENT       37.5f   /* Bit '0' high time */
#define DSHOT_T1H_PERCENT       75.0f   /* Bit '1' high time */

/* DShot special commands (0-47 when motor is stopped) */
#define DSHOT_CMD_MOTOR_STOP            0
#define DSHOT_CMD_BEEP1                 1
#define DSHOT_CMD_BEEP2                 2
#define DSHOT_CMD_BEEP3                 3
#define DSHOT_CMD_BEEP4                 4
#define DSHOT_CMD_BEEP5                 5
#define DSHOT_CMD_ESC_INFO              6
#define DSHOT_CMD_SPIN_DIRECTION_1      7
#define DSHOT_CMD_SPIN_DIRECTION_2      8
#define DSHOT_CMD_3D_MODE_OFF           9
#define DSHOT_CMD_3D_MODE_ON            10
#define DSHOT_CMD_SETTINGS_REQUEST      11
#define DSHOT_CMD_SAVE_SETTINGS         12
#define DSHOT_CMD_SPIN_DIRECTION_NORMAL 20
#define DSHOT_CMD_SPIN_DIRECTION_REV    21
#define DSHOT_CMD_LED0_ON               22
#define DSHOT_CMD_LED1_ON               23
#define DSHOT_CMD_LED2_ON               24
#define DSHOT_CMD_LED3_ON               25
#define DSHOT_CMD_LED0_OFF              26
#define DSHOT_CMD_LED1_OFF              27
#define DSHOT_CMD_LED2_OFF              28
#define DSHOT_CMD_LED3_OFF              29

/* Throttle value range for DShot */
#define DSHOT_THROTTLE_MIN      48      /* First valid throttle value */
#define DSHOT_THROTTLE_MAX      2047    /* Maximum throttle value */

/* GPT register base calculation */
#define GPT_CH_BASE(ch)         (R_GPT32_BASE + ((ch) * R_GPT32_CH_STRIDE))

/* GPT register access macros */
#define GPT_GETREG(ch, offset)  getreg32(GPT_CH_BASE(ch) + (offset))
#define GPT_PUTREG(ch, offset, val) putreg32((val), GPT_CH_BASE(ch) + (offset))

/* POEG (Port Output Enable for GPT) for emergency stop */
#define POEG_GROUP_A            0
#define POEG_GROUP_B            1

/****************************************************************************
 * Private Types
 ****************************************************************************/

/* Output mode enumeration */
typedef enum {
	OUTPUT_MODE_NONE = 0,
	OUTPUT_MODE_PWM,
	OUTPUT_MODE_DSHOT150,
	OUTPUT_MODE_DSHOT300,
	OUTPUT_MODE_DSHOT600,
	OUTPUT_MODE_DSHOT1200,
} output_mode_t;

/* Motor channel state */
typedef struct {
	uint8_t         gpt_channel;        /* GPT timer channel */
	uint8_t         dma_channel;        /* DMA channel for DShot */
	bool            enabled;            /* Channel enabled */
	bool            armed;              /* Channel armed for output */
	uint16_t        value;              /* Current output value (PWM us or DShot throttle) */
	uint16_t        disarmed_value;     /* Disarmed output value */
	uint16_t        failsafe_value;     /* Failsafe output value */
	uint32_t        period_ticks;       /* PWM period in timer ticks */
	uint32_t        duty_ticks;         /* Current duty cycle in timer ticks */

	/* DShot specific */
	uint32_t        dshot_buffer[DSHOT_FRAME_BITS + 1]; /* DMA buffer for DShot frame */
	bool            telemetry_request;  /* Request telemetry on next frame */

#ifdef CONFIG_RA_DMAC
	ra_dmac_handle_t dma_handle;        /* DMA handle for DShot */
#endif
} motor_channel_t;

/* PWM output driver state */
typedef struct {
	output_mode_t   mode;               /* Current output mode */
	uint32_t        pwm_freq;           /* PWM frequency (Hz) */
	uint32_t        dshot_freq;         /* DShot bit frequency */
	bool            initialized;        /* Driver initialized */
	bool            outputs_armed;      /* Outputs armed */
	bool            emergency_stop;     /* Emergency stop active (POEG) */
	motor_channel_t channels[PWM_OUT_MAX_CHANNELS];
} pwm_out_state_t;

/****************************************************************************
 * Private Data
 ****************************************************************************/

static pwm_out_state_t g_pwm_state = {
	.mode = OUTPUT_MODE_NONE,
	.pwm_freq = PWM_FREQ_DEFAULT,
	.dshot_freq = DSHOT600_FREQ,
	.initialized = false,
	.outputs_armed = false,
	.emergency_stop = false,
};

/* GPT channel mapping for motors */
static const uint8_t g_motor_gpt_map[PWM_OUT_MAX_CHANNELS] = {
	MOTOR1_GPT_CHANNEL,
	MOTOR2_GPT_CHANNEL,
	MOTOR3_GPT_CHANNEL,
	MOTOR4_GPT_CHANNEL,
};

/* DMA channel mapping for motors (DMAC1 channels 10-17) */
static const uint8_t g_motor_dma_map[PWM_OUT_MAX_CHANNELS] = {
	DSHOT_DMA_CH_MOTOR1,
	DSHOT_DMA_CH_MOTOR2,
	DSHOT_DMA_CH_MOTOR3,
	DSHOT_DMA_CH_MOTOR4,
};

/* MSTP module IDs for GPT channels */
static const ra_mstp_module_t g_gpt_mstp_map[] = {
	[0]  = RA_MSTP_GPT0,
	[1]  = RA_MSTP_GPT1,
	[2]  = RA_MSTP_GPT2,
	[3]  = RA_MSTP_GPT3,
	[4]  = RA_MSTP_GPT4,
	[5]  = RA_MSTP_GPT5,
	[6]  = RA_MSTP_GPT6,
	[7]  = RA_MSTP_GPT7,
	[8]  = RA_MSTP_GPT8,
	[9]  = RA_MSTP_GPT9,
	[10] = RA_MSTP_GPT10,
	[11] = RA_MSTP_GPT11,
	[12] = RA_MSTP_GPT12,
	[13] = RA_MSTP_GPT13,
};

/****************************************************************************
 * Private Functions
 ****************************************************************************/

/**
 * @brief Enable GPT module clock via MSTP
 */
static void gpt_enable_clock(uint8_t channel)
{
	if (channel < 14) {
		ra_mstp_enable(g_gpt_mstp_map[channel]);
	}
}

/**
 * @brief Disable GPT module clock via MSTP
 */
static void gpt_disable_clock(uint8_t channel)
{
	if (channel < 14) {
		ra_mstp_disable(g_gpt_mstp_map[channel]);
	}
}

/**
 * @brief Calculate prescaler for desired frequency
 */
static uint32_t gpt_calculate_prescaler(uint32_t frequency)
{
	static const uint32_t prescalers[] = {1, 4, 16, 64, 256, 1024};
	uint32_t period;

	for (int i = 0; i < 6; i++) {
		period = BOARD_PCLKD_FREQUENCY / (prescalers[i] * frequency);

		if (period <= 0xFFFFFFFF) { /* 32-bit timer */
			return i; /* Return prescaler index */
		}
	}

	return 5; /* Use maximum prescaler */
}

/**
 * @brief Configure GPT channel for PWM output
 */
static int gpt_configure_pwm(uint8_t channel, uint32_t frequency)
{
	if (channel >= 14) {
		return -EINVAL;
	}

	/* Enable module clock */
	gpt_enable_clock(channel);

	/* Stop the timer */
	GPT_PUTREG(channel, R_GPT32_GTSTP_OFFSET, (1 << channel));

	/* Clear counter */
	GPT_PUTREG(channel, R_GPT32_GTCLR_OFFSET, (1 << channel));

	/* Unlock write protection */
	GPT_PUTREG(channel, R_GPT32_GTWP_OFFSET, 0xA500);

	/* Calculate prescaler and period */
	uint32_t prescaler_idx = gpt_calculate_prescaler(frequency);
	static const uint32_t prescaler_vals[] = {1, 4, 16, 64, 256, 1024};
	uint32_t prescaler = prescaler_vals[prescaler_idx];
	uint32_t period = (BOARD_PCLKD_FREQUENCY / (prescaler * frequency)) - 1;

	/* Store period for duty cycle calculation */
	for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
		if (g_pwm_state.channels[i].gpt_channel == channel) {
			g_pwm_state.channels[i].period_ticks = period;
			break;
		}
	}

	/* Configure timer control register
	 * - Saw-wave PWM mode
	 * - Count up
	 * - Prescaler from calculation
	 */
	uint32_t gtcr = (prescaler_idx << 24) |  /* TPCS - prescaler */
			(0 << 16) |              /* MD - saw-wave mode */
			(0 << 0);                /* CST - count stop */
	GPT_PUTREG(channel, R_GPT32_GTCR_OFFSET, gtcr);

	/* Set period register */
	GPT_PUTREG(channel, R_GPT32_GTPR_OFFSET, period);

	/* Configure I/O control for GTIOCA output
	 * - Initial output low
	 * - Output high on compare match
	 * - Output low on cycle end
	 */
	uint32_t gtior = (0x09 << 0) |  /* GTIOA: Initial low, high on match */
			 (1 << 8);      /* OAE: Enable GTIOCA output */
	GPT_PUTREG(channel, R_GPT32_GTIOR_OFFSET, gtior);

	/* Enable buffer operation */
	GPT_PUTREG(channel, R_GPT32_GTBER_OFFSET,
		   (1 << 0) |   /* CCRA buffer enable */
		   (1 << 16));  /* PR buffer enable */

	/* Set count direction to up */
	GPT_PUTREG(channel, R_GPT32_GTUDDTYC_OFFSET, 0x01);

	/* Clear counter */
	GPT_PUTREG(channel, R_GPT32_GTCNT_OFFSET, 0);

	/* Set initial duty to 0 */
	GPT_PUTREG(channel, R_GPT32_GTCCRA_OFFSET, 0);
	GPT_PUTREG(channel, R_GPT32_GTCCRC_OFFSET, 0);

	/* Lock write protection */
	GPT_PUTREG(channel, R_GPT32_GTWP_OFFSET, 0);

	syslog(LOG_DEBUG, "GPT%d: PWM configured, freq=%lu, period=%lu\n",
	       channel, (unsigned long)frequency, (unsigned long)period);

	return 0;
}

/**
 * @brief Configure GPT channel for DShot output
 */
static int gpt_configure_dshot(uint8_t channel, uint32_t dshot_freq)
{
	if (channel >= 14) {
		return -EINVAL;
	}

	/* Enable module clock */
	gpt_enable_clock(channel);

	/* Stop the timer */
	GPT_PUTREG(channel, R_GPT32_GTSTP_OFFSET, (1 << channel));

	/* Clear counter */
	GPT_PUTREG(channel, R_GPT32_GTCLR_OFFSET, (1 << channel));

	/* Unlock write protection */
	GPT_PUTREG(channel, R_GPT32_GTWP_OFFSET, 0xA500);

	/* For DShot, each bit needs precise timing
	 * Period = 1 / dshot_freq (one bit period)
	 */
	uint32_t prescaler_idx = 0; /* No prescaler for DShot */
	uint32_t period = (BOARD_PCLKD_FREQUENCY / dshot_freq) - 1;

	/* Store period */
	for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
		if (g_pwm_state.channels[i].gpt_channel == channel) {
			g_pwm_state.channels[i].period_ticks = period;
			break;
		}
	}

	/* Configure timer control register for DShot
	 * - One-shot mode (DMA will restart for each bit)
	 * - Count up
	 * - No prescaler for maximum resolution
	 */
	uint32_t gtcr = (prescaler_idx << 24) |
			(0 << 16) |  /* MD - saw-wave mode */
			(0 << 0);
	GPT_PUTREG(channel, R_GPT32_GTCR_OFFSET, gtcr);

	/* Set period register */
	GPT_PUTREG(channel, R_GPT32_GTPR_OFFSET, period);

	/* Configure I/O control */
	uint32_t gtior = (0x09 << 0) |  /* GTIOA: Initial low, high on match */
			 (1 << 8);      /* OAE: Enable GTIOCA output */
	GPT_PUTREG(channel, R_GPT32_GTIOR_OFFSET, gtior);

	/* Enable buffer operation for seamless updates */
	GPT_PUTREG(channel, R_GPT32_GTBER_OFFSET, (1 << 0) | (1 << 16));

	/* Set count direction */
	GPT_PUTREG(channel, R_GPT32_GTUDDTYC_OFFSET, 0x01);

	/* Clear counter */
	GPT_PUTREG(channel, R_GPT32_GTCNT_OFFSET, 0);

	/* Lock write protection */
	GPT_PUTREG(channel, R_GPT32_GTWP_OFFSET, 0);

	syslog(LOG_DEBUG, "GPT%d: DShot configured, freq=%lu, period=%lu\n",
	       channel, (unsigned long)dshot_freq, (unsigned long)period);

	return 0;
}

/**
 * @brief Start GPT timer
 */
static void gpt_start(uint8_t channel)
{
	if (channel < 14) {
		GPT_PUTREG(channel, R_GPT32_GTSTR_OFFSET, (1 << channel));
	}
}

/**
 * @brief Stop GPT timer
 */
static void gpt_stop(uint8_t channel)
{
	if (channel < 14) {
		GPT_PUTREG(channel, R_GPT32_GTSTP_OFFSET, (1 << channel));
	}
}

/**
 * @brief Set PWM duty cycle
 */
static void gpt_set_duty(uint8_t channel, uint32_t duty_ticks)
{
	if (channel < 14) {
		/* Write to buffer register for glitch-free update */
		GPT_PUTREG(channel, R_GPT32_GTCCRC_OFFSET, duty_ticks);
	}
}

/**
 * @brief Convert PWM microseconds to timer ticks
 */
static uint32_t pwm_us_to_ticks(uint32_t period_ticks, uint32_t pwm_freq, uint32_t pulse_us)
{
	/* duty_ticks = (pulse_us / period_us) * period_ticks
	 * period_us = 1,000,000 / pwm_freq
	 */
	uint64_t duty = ((uint64_t)pulse_us * pwm_freq * period_ticks) / 1000000ULL;
	return (uint32_t)duty;
}

/**
 * @brief Calculate DShot checksum (XOR of nibbles)
 */
static uint8_t dshot_checksum(uint16_t packet)
{
	uint8_t csum = 0;
	csum ^= (packet >> 0) & 0xF;
	csum ^= (packet >> 4) & 0xF;
	csum ^= (packet >> 8) & 0xF;
	return csum;
}

/**
 * @brief Build DShot frame
 */
static uint16_t dshot_build_frame(uint16_t throttle, bool telemetry)
{
	/* DShot frame format:
	 * Bits 15-5: 11-bit throttle (0-2047)
	 * Bit 4: Telemetry request
	 * Bits 3-0: CRC (XOR of nibbles)
	 */
	uint16_t packet = (throttle << 5) | (telemetry ? (1 << 4) : 0);
	packet |= dshot_checksum(packet >> 4);
	return packet;
}

/**
 * @brief Fill DMA buffer with DShot timing values
 */
static void dshot_fill_buffer(motor_channel_t *ch, uint16_t frame)
{
	uint32_t period = ch->period_ticks;
	uint32_t t0h = (uint32_t)(period * DSHOT_T0H_PERCENT / 100.0f);
	uint32_t t1h = (uint32_t)(period * DSHOT_T1H_PERCENT / 100.0f);

	/* Fill buffer with compare values for each bit (MSB first) */
	for (int i = 0; i < DSHOT_FRAME_BITS; i++) {
		if (frame & (1 << (15 - i))) {
			ch->dshot_buffer[i] = t1h;  /* Bit 1: long pulse */
		} else {
			ch->dshot_buffer[i] = t0h;  /* Bit 0: short pulse */
		}
	}

	/* Final entry: 0 to end the frame */
	ch->dshot_buffer[DSHOT_FRAME_BITS] = 0;
}

#ifdef CONFIG_RA_DMAC
/**
 * @brief DMA completion callback for DShot
 */
static void dshot_dma_callback(ra_dmac_handle_t handle, void *arg, int result)
{
	motor_channel_t *ch = (motor_channel_t *)arg;

	if (result == 0) {
		/* Frame transmitted successfully */
		gpt_stop(ch->gpt_channel);
	} else {
		syslog(LOG_ERR, "DShot DMA error on channel %d\n", ch->gpt_channel);
	}
}

/**
 * @brief Configure DMA for DShot frame transmission
 */
static int dshot_configure_dma(motor_channel_t *ch)
{
	ra_dmac_config_t config;
	int ret;

	memset(&config, 0, sizeof(config));

	config.channel = ch->dma_channel;
	config.src_addr = (uint32_t)ch->dshot_buffer;
	config.dst_addr = GPT_CH_BASE(ch->gpt_channel) + R_GPT32_GTCCRA_OFFSET;
	config.transfer_size = DSHOT_FRAME_BITS + 1;
	config.src_width = RA_DMAC_WIDTH_32BIT;
	config.dst_width = RA_DMAC_WIDTH_32BIT;
	config.src_inc = RA_DMAC_ADDR_INC;
	config.dst_inc = RA_DMAC_ADDR_FIXED;
	config.mode = RA_DMAC_MODE_BLOCK;
	config.callback = dshot_dma_callback;
	config.arg = ch;

	ret = ra_dmac_open(&ch->dma_handle, &config);

	if (ret < 0) {
		syslog(LOG_ERR, "Failed to configure DMA for DShot ch%d: %d\n",
		       ch->gpt_channel, ret);
		return ret;
	}

	return 0;
}

/**
 * @brief Trigger DShot frame transmission via DMA
 */
static void dshot_trigger_dma(motor_channel_t *ch)
{
	if (ch->dma_handle != NULL) {
		/* Reset source address */
		ra_dmac_reload(ch->dma_handle, (uint32_t)ch->dshot_buffer,
			       GPT_CH_BASE(ch->gpt_channel) + R_GPT32_GTCCRA_OFFSET,
			       DSHOT_FRAME_BITS + 1);

		/* Start DMA transfer */
		ra_dmac_start(ch->dma_handle);

		/* Start GPT timer */
		gpt_start(ch->gpt_channel);
	}
}
#endif /* CONFIG_RA_DMAC */

/**
 * @brief Configure POEG for emergency motor stop
 */
static void poeg_configure(uint8_t group)
{
	/* Enable POEG module clock */
	ra_mstp_enable(RA_MSTP_POEG);

	uint32_t poegg = R_GPT_POEG_POEGG_PIDE |   /* Port input detection enable */
			 R_GPT_POEG_POEGG_IOCE |   /* GPT output disable enable */
			 R_GPT_POEG_POEGG_NFEN |   /* Noise filter enable */
			 R_GPT_POEG_POEGG_NFCS_01; /* PCLK/8 noise filter */

	putreg32(poegg, R_GPT_POEG_POEGG(group));

	syslog(LOG_INFO, "POEG Group %d configured for emergency stop\n", group);
}

/**
 * @brief Trigger POEG emergency stop
 */
static void poeg_emergency_stop(uint8_t group)
{
	uint32_t poegg = getreg32(R_GPT_POEG_POEGG(group));
	poegg |= R_GPT_POEG_POEGG_SSF;  /* Set software stop flag */
	putreg32(poegg, R_GPT_POEG_POEGG(group));

	g_pwm_state.emergency_stop = true;
	syslog(LOG_WARNING, "POEG emergency stop triggered!\n");
}

/**
 * @brief Clear POEG emergency stop
 */
static void poeg_clear_stop(uint8_t group)
{
	uint32_t poegg = getreg32(R_GPT_POEG_POEGG(group));
	poegg &= ~R_GPT_POEG_POEGG_SSF;  /* Clear software stop flag */
	putreg32(poegg, R_GPT_POEG_POEGG(group));

	g_pwm_state.emergency_stop = false;
	syslog(LOG_INFO, "POEG emergency stop cleared\n");
}

/****************************************************************************
 * Public Functions
 ****************************************************************************/

/**
 * @brief Initialize PWM/DShot output driver
 */
int pwm_out_init(void)
{
	if (g_pwm_state.initialized) {
		return 0;
	}

	syslog(LOG_INFO, "PWM output driver initializing...\n");

	/* Initialize channel state */
	for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
		g_pwm_state.channels[i].gpt_channel = g_motor_gpt_map[i];
		g_pwm_state.channels[i].dma_channel = g_motor_dma_map[i];
		g_pwm_state.channels[i].enabled = false;
		g_pwm_state.channels[i].armed = false;
		g_pwm_state.channels[i].value = PWM_PULSE_DISARMED;
		g_pwm_state.channels[i].disarmed_value = PWM_PULSE_DISARMED;
		g_pwm_state.channels[i].failsafe_value = PWM_PULSE_FAILSAFE;
		g_pwm_state.channels[i].period_ticks = 0;
		g_pwm_state.channels[i].duty_ticks = 0;
		g_pwm_state.channels[i].telemetry_request = false;
#ifdef CONFIG_RA_DMAC
		g_pwm_state.channels[i].dma_handle = NULL;
#endif
	}

	/* Configure POEG for emergency stop */
	poeg_configure(POEG_GROUP_A);

	g_pwm_state.initialized = true;
	syslog(LOG_INFO, "PWM output driver initialized\n");

	return 0;
}

/**
 * @brief Set output mode (PWM or DShot)
 */
int pwm_out_set_mode(output_mode_t mode)
{
	if (!g_pwm_state.initialized) {
		return -ENODEV;
	}

	if (g_pwm_state.outputs_armed) {
		syslog(LOG_ERR, "Cannot change mode while armed\n");
		return -EBUSY;
	}

	int ret = 0;

	switch (mode) {
	case OUTPUT_MODE_PWM:
		g_pwm_state.dshot_freq = 0;

		for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
			ret = gpt_configure_pwm(g_pwm_state.channels[i].gpt_channel,
						g_pwm_state.pwm_freq);

			if (ret < 0) {
				syslog(LOG_ERR, "Failed to configure PWM channel %d\n", i);
				return ret;
			}

			g_pwm_state.channels[i].enabled = true;
		}

		break;

	case OUTPUT_MODE_DSHOT150:
		g_pwm_state.dshot_freq = DSHOT150_FREQ;
		break;

	case OUTPUT_MODE_DSHOT300:
		g_pwm_state.dshot_freq = DSHOT300_FREQ;
		break;

	case OUTPUT_MODE_DSHOT600:
		g_pwm_state.dshot_freq = DSHOT600_FREQ;
		break;

	case OUTPUT_MODE_DSHOT1200:
		g_pwm_state.dshot_freq = DSHOT1200_FREQ;
		break;

	default:
		return -EINVAL;
	}

	/* Configure DShot modes */
	if (mode >= OUTPUT_MODE_DSHOT150) {
#ifdef CONFIG_RA_DMAC
		/* Initialize DMAC */
		ra_dmac_initialize();
#endif

		for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
			ret = gpt_configure_dshot(g_pwm_state.channels[i].gpt_channel,
						  g_pwm_state.dshot_freq);

			if (ret < 0) {
				syslog(LOG_ERR, "Failed to configure DShot channel %d\n", i);
				return ret;
			}

#ifdef CONFIG_RA_DMAC
			ret = dshot_configure_dma(&g_pwm_state.channels[i]);

			if (ret < 0) {
				syslog(LOG_ERR, "Failed to configure DMA for channel %d\n", i);
				return ret;
			}

#endif
			g_pwm_state.channels[i].enabled = true;
		}
	}

	g_pwm_state.mode = mode;
	syslog(LOG_INFO, "Output mode set to %d\n", mode);

	return 0;
}

/**
 * @brief Set PWM frequency (PWM mode only)
 */
int pwm_out_set_frequency(uint32_t freq_hz)
{
	if (freq_hz < PWM_FREQ_MIN || freq_hz > PWM_FREQ_MAX) {
		return -EINVAL;
	}

	g_pwm_state.pwm_freq = freq_hz;

	/* Reconfigure if in PWM mode */
	if (g_pwm_state.mode == OUTPUT_MODE_PWM) {
		for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
			gpt_configure_pwm(g_pwm_state.channels[i].gpt_channel, freq_hz);
		}
	}

	return 0;
}

/**
 * @brief Arm/disarm motor outputs
 */
int pwm_out_arm(bool arm)
{
	if (!g_pwm_state.initialized) {
		return -ENODEV;
	}

	if (g_pwm_state.emergency_stop && arm) {
		syslog(LOG_ERR, "Cannot arm while emergency stop active\n");
		return -EPERM;
	}

	if (arm && !g_pwm_state.outputs_armed) {
		/* Arming - start all timers */
		for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
			if (g_pwm_state.channels[i].enabled) {
				g_pwm_state.channels[i].armed = true;

				if (g_pwm_state.mode == OUTPUT_MODE_PWM) {
					/* Set disarmed value and start timer */
					uint32_t duty = pwm_us_to_ticks(
								g_pwm_state.channels[i].period_ticks,
								g_pwm_state.pwm_freq,
								g_pwm_state.channels[i].disarmed_value);
					gpt_set_duty(g_pwm_state.channels[i].gpt_channel, duty);
					gpt_start(g_pwm_state.channels[i].gpt_channel);
				}
			}
		}

		g_pwm_state.outputs_armed = true;
		syslog(LOG_INFO, "Motor outputs armed\n");

	} else if (!arm && g_pwm_state.outputs_armed) {
		/* Disarming - stop all timers */
		for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
			g_pwm_state.channels[i].armed = false;
			gpt_stop(g_pwm_state.channels[i].gpt_channel);
		}

		g_pwm_state.outputs_armed = false;
		syslog(LOG_INFO, "Motor outputs disarmed\n");
	}

	return 0;
}

/**
 * @brief Set motor output value
 * @param channel Motor channel (0-3)
 * @param value PWM pulse width in us (PWM mode) or throttle 0-2047 (DShot mode)
 */
int pwm_out_set(unsigned channel, uint16_t value)
{
	if (channel >= PWM_OUT_MAX_CHANNELS) {
		return -EINVAL;
	}

	motor_channel_t *ch = &g_pwm_state.channels[channel];

	if (!ch->enabled || !ch->armed) {
		return -EPERM;
	}

	if (g_pwm_state.emergency_stop) {
		return -EPERM;
	}

	ch->value = value;

	if (g_pwm_state.mode == OUTPUT_MODE_PWM) {
		/* PWM mode: value is pulse width in microseconds */
		if (value < PWM_PULSE_MIN) {
			value = PWM_PULSE_MIN;
		}

		if (value > PWM_PULSE_MAX) {
			value = PWM_PULSE_MAX;
		}

		uint32_t duty = pwm_us_to_ticks(ch->period_ticks, g_pwm_state.pwm_freq, value);
		ch->duty_ticks = duty;
		gpt_set_duty(ch->gpt_channel, duty);

	} else if (g_pwm_state.mode >= OUTPUT_MODE_DSHOT150) {
		/* DShot mode: value is throttle 0-2047 */
		if (value > DSHOT_THROTTLE_MAX) {
			value = DSHOT_THROTTLE_MAX;
		}

		/* Build and buffer DShot frame */
		uint16_t frame = dshot_build_frame(value, ch->telemetry_request);
		dshot_fill_buffer(ch, frame);
		ch->telemetry_request = false;  /* Clear after use */
	}

	return 0;
}

/**
 * @brief Trigger DShot frame transmission for all channels
 */
void pwm_out_trigger_dshot(void)
{
	if (g_pwm_state.mode < OUTPUT_MODE_DSHOT150 || !g_pwm_state.outputs_armed) {
		return;
	}

#ifdef CONFIG_RA_DMAC

	for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
		if (g_pwm_state.channels[i].enabled && g_pwm_state.channels[i].armed) {
			dshot_trigger_dma(&g_pwm_state.channels[i]);
		}
	}

#endif
}

/**
 * @brief Set disarmed value for channel
 */
void pwm_out_set_disarmed(unsigned channel, uint16_t value)
{
	if (channel < PWM_OUT_MAX_CHANNELS) {
		g_pwm_state.channels[channel].disarmed_value = value;
	}
}

/**
 * @brief Set failsafe value for channel
 */
void pwm_out_set_failsafe(unsigned channel, uint16_t value)
{
	if (channel < PWM_OUT_MAX_CHANNELS) {
		g_pwm_state.channels[channel].failsafe_value = value;
	}
}

/**
 * @brief Apply failsafe values to all channels
 */
void pwm_out_failsafe(void)
{
	for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
		if (g_pwm_state.channels[i].enabled) {
			pwm_out_set(i, g_pwm_state.channels[i].failsafe_value);
		}
	}
}

/**
 * @brief Trigger emergency stop via POEG
 */
void pwm_out_emergency_stop(void)
{
	poeg_emergency_stop(POEG_GROUP_A);

	/* Also stop all GPT timers */
	for (int i = 0; i < PWM_OUT_MAX_CHANNELS; i++) {
		gpt_stop(g_pwm_state.channels[i].gpt_channel);
	}
}

/**
 * @brief Clear emergency stop
 */
void pwm_out_clear_emergency(void)
{
	poeg_clear_stop(POEG_GROUP_A);
}

/**
 * @brief Check if emergency stop is active
 */
bool pwm_out_is_emergency(void)
{
	return g_pwm_state.emergency_stop;
}

/**
 * @brief Get current mode
 */
output_mode_t pwm_out_get_mode(void)
{
	return g_pwm_state.mode;
}

/**
 * @brief Check if outputs are armed
 */
bool pwm_out_is_armed(void)
{
	return g_pwm_state.outputs_armed;
}

/**
 * @brief Request telemetry on next DShot frame
 */
void pwm_out_request_telemetry(unsigned channel)
{
	if (channel < PWM_OUT_MAX_CHANNELS) {
		g_pwm_state.channels[channel].telemetry_request = true;
	}
}

/**
 * @brief Send DShot command (special command 0-47)
 */
int pwm_out_dshot_command(unsigned channel, uint8_t command, bool telemetry)
{
	if (channel >= PWM_OUT_MAX_CHANNELS) {
		return -EINVAL;
	}

	if (command > 47) {
		return -EINVAL;
	}

	if (g_pwm_state.mode < OUTPUT_MODE_DSHOT150) {
		return -ENOTSUP;
	}

	motor_channel_t *ch = &g_pwm_state.channels[channel];

	/* Build command frame */
	uint16_t frame = dshot_build_frame(command, telemetry);
	dshot_fill_buffer(ch, frame);

#ifdef CONFIG_RA_DMAC
	dshot_trigger_dma(ch);
#endif

	return 0;
}

/*
 * PX4IO interface compatibility functions
 */

/**
 * @brief up_pwm_servo_init - Initialize PWM outputs (PX4IO interface)
 */
unsigned up_pwm_servo_init(uint32_t channel_mask)
{
	int ret = pwm_out_init();

	if (ret < 0) {
		return 0;
	}

	ret = pwm_out_set_mode(OUTPUT_MODE_PWM);

	if (ret < 0) {
		return 0;
	}

	return PWM_OUT_MAX_CHANNELS;
}

/**
 * @brief up_pwm_servo_deinit - Deinitialize PWM outputs (PX4IO interface)
 */
void up_pwm_servo_deinit(uint32_t channel_mask)
{
	pwm_out_arm(false);
}

/**
 * @brief up_pwm_servo_arm - Arm/disarm PWM outputs (PX4IO interface)
 */
int up_pwm_servo_arm(bool arm, uint32_t channel_mask)
{
	return pwm_out_arm(arm);
}

/**
 * @brief up_pwm_servo_set - Set PWM value (PX4IO interface)
 */
int up_pwm_servo_set(unsigned channel, uint16_t value)
{
	return pwm_out_set(channel, value);
}

/**
 * @brief up_pwm_servo_get - Get current PWM value (PX4IO interface)
 */
uint16_t up_pwm_servo_get(unsigned channel)
{
	if (channel < PWM_OUT_MAX_CHANNELS) {
		return g_pwm_state.channels[channel].value;
	}

	return 0;
}

/**
 * @brief up_pwm_servo_set_rate - Set PWM frequency (PX4IO interface)
 */
int up_pwm_servo_set_rate(unsigned rate)
{
	return pwm_out_set_frequency(rate);
}

/**
 * @brief up_pwm_servo_get_rate_group - Get rate group (PX4IO interface)
 */
uint32_t up_pwm_servo_get_rate_group(unsigned group)
{
	/* All channels use same rate group on CM33 */
	return 0x0F; /* Channels 0-3 */
}
