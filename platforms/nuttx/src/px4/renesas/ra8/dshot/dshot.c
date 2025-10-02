/****************************************************************************
 *
 * Copyright (C) 2025 PX4 Development Team. All rights reserved.
 * Author: Peter van der Perk <peter.vanderperk@nxp.com>
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *	notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *	notice, this list of conditions and the following disclaimer in
 *	the documentation and/or other materials provided with the
 *	distribution.
 * 3. Neither the name PX4 nor the names of its contributors may be
 *	used to endorse or promote products derived from this software
 *	without specific prior written permission.
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

#include <nuttx/config.h>
#include <nuttx/arch.h>
#include <nuttx/irq.h>
#include <nuttx/spinlock.h>
#include <debug.h>
#include <errno.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/micro_hal.h>
#include <px4_platform_common/log.h>
#include <px4_arch/dshot.h>
#include <px4_arch/io_timer.h>
#include <drivers/drv_dshot.h>

#include "arm_internal.h"
#include "chip.h"
#include "hardware/ra_gpt.h"
#include "hardware/ra_memorymap.h"
#include "ra_pinmap.h"
#include "ra_gpt.h"
#include "ra_mstp.h"
#include "ra_icu.h"
#include "ra_gpio.h"

/* Include arch-specific headers for ELC constants */
#include <arch/irq.h>
#include <arch/board/board.h>

/* DShot configuration constants */
#define DSHOT_MAX_CHANNELS      4      /* Maximum number of DShot channels on RA8E1 board */
#define DSHOT_THROTTLE_POSITION 5u     /* Throttle value bit position */
#define DSHOT_TELEMETRY_POSITION 4u    /* Telemetry request bit position */
#define DSHOT_CHECKSUM_BITS     4u     /* Number of checksum bits */
#define DSHOT_FRAME_SIZE        16u    /* DShot frame size in bits */
#define DSHOT_NIBBLES_SIZE      4u     /* Nibble size for checksum calculation */
#define DSHOT_NUMBER_OF_NIBBLES 3u     /* Number of nibbles for checksum */

#define BDSHOT_OFFLINE_COUNT    400    /* ESC offline threshold count */

/* DShot timing parameters (based on PCLKD = 120MHz) */
#define DSHOT150_FREQ           150000  /* 150 kHz */
#define DSHOT300_FREQ           300000  /* 300 kHz */
#define DSHOT600_FREQ           600000  /* 600 kHz */

/* DShot bit encoding timing */
#define DSHOT_T0H_RATIO         37.5f   /* Bit 0 high time percentage */
#define DSHOT_T1H_RATIO         75.0f   /* Bit 1 high time percentage */

/* GPT channel mapping for DShot on FPB-RA8E1 board */
static struct {
    uint8_t gpt_channel;
    uint32_t gpio_pin;
    ra_mstp_module_t mstp_module;
    int elc_compare; /* ELC event for compare match */
    int elc_overflow; /* ELC event for overflow (BDShot timing) */
} dshot_channel_map[DSHOT_MAX_CHANNELS] = {
    {3, GPIO_GTIOC0A_3, RA_MSTP_GPT3,  RA_ELC_GPT3_CAPTURE_COMPARE_A, RA_ELC_GPT3_CAPTURE_OVERFLOW_A},  /* Motor 1: P300 (GPT3A) */
    {0, GPIO_GTIOC2A_2, RA_MSTP_GPT0,  RA_ELC_GPT0_CAPTURE_COMPARE_A, RA_ELC_GPT0_CAPTURE_OVERFLOW_A},  /* Motor 2: P415 (GPT0A) */
    {2, GPIO_GTIOC3A_1, RA_MSTP_GPT2,  RA_ELC_GPT2_CAPTURE_COMPARE_A, RA_ELC_GPT2_CAPTURE_OVERFLOW_A},  /* Motor 3: P113 (GPT2A) */
    {4, GPIO_GTIOC4A_2, RA_MSTP_GPT4,  RA_ELC_GPT4_CAPTURE_COMPARE_A, RA_ELC_GPT4_CAPTURE_OVERFLOW_A},  /* Motor 4: P302 (GPT4A) */
};

/* DShot state enumeration */
typedef enum {
    DSHOT_STATE_IDLE = 0,
    DSHOT_STATE_SENDING,
    DSHOT_STATE_COMPLETE,
    BDSHOT_STATE_RECEIVING,
    BDSHOT_STATE_COMPLETE
} dshot_state_t;

/* DShot channel instance */
typedef struct {
    bool initialized;
    bool bdshot_enabled;
    uint8_t gpt_channel;
    uint32_t gpio_pin;
    uint32_t mstp_module;

    /* DShot protocol state */
    dshot_state_t state;
    uint16_t current_frame;
    uint8_t bit_index;
    uint32_t bit_period;
    uint32_t t0h_period;
    uint32_t t1h_period;

    /* BDShot telemetry */
    uint32_t raw_response;
    uint16_t erpm;
    uint32_t crc_error_count;
    uint32_t frame_error_count;
    uint32_t no_response_count;
    uint32_t last_no_response_count;

    /* ICU interrupt management */
    int icu_compare_irq;
    int icu_overflow_irq;
    uint32_t telemetry_capture_start;
    uint32_t telemetry_bits[32]; /* Buffer for captured telemetry bits */
    uint8_t telemetry_bit_count;
} dshot_channel_t;

/* Global DShot state */
static struct {
    bool initialized;
    uint32_t frequency;
    bool bidirectional_enabled;
    uint32_t active_channels;
    dshot_channel_t channels[DSHOT_MAX_CHANNELS];
    bool lock;
} g_dshot;

/* Forward declarations */
static int dshot_gpt_interrupt(int irq, void *context, void *arg);
static int dshot_bdshot_overflow_interrupt(int irq, void *context, void *arg);
static void dshot_configure_channel(uint8_t channel);
static void dshot_configure_bdshot_capture(uint8_t channel);
static void dshot_send_bit(uint8_t channel, bool bit_value);
static void dshot_start_frame(uint8_t channel);
static void dshot_complete_frame(uint8_t channel);
static uint32_t dshot_calculate_periods(uint32_t frequency, uint32_t *t0h, uint32_t *t1h);
static uint16_t dshot_encode_frame(uint16_t throttle, bool telemetry, bool bdshot);
static void bdshot_decode_response(uint8_t channel, uint32_t raw_data);

/****************************************************************************
 * Private Functions
 ****************************************************************************/

/**
 * Calculate timer periods for DShot bit timing
 */
static uint32_t dshot_calculate_periods(uint32_t frequency, uint32_t *t0h, uint32_t *t1h)
{
    /* Get PCLKD frequency from board configuration */
    uint32_t pclkd_freq = BOARD_PCLKD_FREQUENCY;

    /* Calculate bit period in timer counts */
    uint32_t bit_period = pclkd_freq / frequency;

    /* Calculate high periods for bit 0 and bit 1 */
    *t0h = (uint32_t)(bit_period * DSHOT_T0H_RATIO / 100.0f);
    *t1h = (uint32_t)(bit_period * DSHOT_T1H_RATIO / 100.0f);

    return bit_period;
}

/**
 * Encode DShot frame with throttle value, telemetry request and checksum
 */
static uint16_t dshot_encode_frame(uint16_t throttle, bool telemetry, bool bdshot)
{
    uint16_t packet = 0;
    uint16_t checksum = 0;
    uint16_t csum_data;

    /* Build packet: 11 bits throttle + 1 bit telemetry */
    packet |= (throttle & 0x7FF) << DSHOT_THROTTLE_POSITION;
    packet |= (telemetry ? 1 : 0) << DSHOT_TELEMETRY_POSITION;

    /* Calculate checksum */
    csum_data = bdshot ? ~packet : packet;
    csum_data >>= DSHOT_NIBBLES_SIZE;

    for (unsigned i = 0; i < DSHOT_NUMBER_OF_NIBBLES; i++) {
        checksum ^= (csum_data & 0x0F);
        csum_data >>= DSHOT_NIBBLES_SIZE;
    }

    /* Add checksum to packet */
    packet |= (checksum & 0x0F);

    return packet;
}

/**
 * Configure GPT channel for DShot output
 */
static void dshot_configure_channel(uint8_t channel)
{
    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];
    uint8_t gpt_ch = dshot_ch->gpt_channel;

    /* Enable module stop control */
    ra_mstp_start(dshot_ch->mstp_module);

    /* Disable write protection */
    putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP, RA_GPT_GTWP(gpt_ch));

    /* Stop timer if running */
    putreg32(0, RA_GPT_GTCR(gpt_ch));

    /* Configure GPT for PWM mode with saw-wave up counting */
    uint32_t gtcr = GPT_GTCR_MD_SAW_WAVE_UP | GPT_GTCR_TPCS_PCLKD_1;
    putreg32(gtcr, RA_GPT_GTCR(gpt_ch));

    /* Set period register */
    putreg32(dshot_ch->bit_period - 1, RA_GPT_GTPR(gpt_ch));

    /* Configure GTIOA pin for PWM output (initial low, compare match high) */
    uint32_t gtior = GPT_GTIOR_GTIOA_INITIAL_LOW;
    putreg32(gtior, RA_GPT_GTIOR(gpt_ch));

    /* Enable Compare A interrupt */
    putreg32(GPT_GTINTAD_GTINTA, RA_GPT_GTINTAD(gpt_ch));

    /* Enable buffer for period and compare registers */
    /* Configure GPT buffer registers for smooth PWM transitions */
    uint32_t gtber = (1 << 2) | (1 << 1); /* Enable CCRA and PR buffer */
    putreg32(gtber, RA_GPT_GTBER(gpt_ch));

    /* Configure buffer operation - single buffer mode */
    uint32_t gtbdr = 0; /* Disable double buffer for simplicity */
    putreg32(gtbdr, RA_GPT_GTBDR(gpt_ch));

    /* Enable write protection */
    putreg32(GPT_GTWP_PRKEY, RA_GPT_GTWP(gpt_ch));

    PX4_DEBUG("DShot channel %d: GPT%d configured, period=%lu",
              channel, gpt_ch, dshot_ch->bit_period);
}

/**
 * Configure GPIO pin for DShot output
 */
static void dshot_configure_gpio(uint8_t channel)
{
    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];
    uint8_t gpt_ch = dshot_ch->gpt_channel;

    /* Configure GPIO pin for GPT function */
    /* This needs to be board-specific based on pin mapping */
    switch (gpt_ch) {
        case 0: /* GPT0A - P415 */
            ra_gpio_config(dshot_ch->gpio_pin);
            break;
        case 2: /* GPT2A - P113 */
            ra_gpio_config(dshot_ch->gpio_pin);
            break;
        case 3: /* GPT3A - P300 */
            ra_gpio_config(dshot_ch->gpio_pin);
            break;
        case 4: /* GPT4A - P302 */
            ra_gpio_config(dshot_ch->gpio_pin);
            break;
        default:
            PX4_ERR("Unsupported GPT channel %d for DShot", gpt_ch);
            break;
    }
}

/**
 * Start sending a DShot frame
 */
static void dshot_start_frame(uint8_t channel)
{
    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];
    uint8_t gpt_ch = dshot_ch->gpt_channel;

    /* Reset state */
    dshot_ch->state = DSHOT_STATE_SENDING;
    dshot_ch->bit_index = 0;

    /* Send first bit */
    bool first_bit = (dshot_ch->current_frame >> (DSHOT_FRAME_SIZE - 1)) & 1;
    dshot_send_bit(channel, first_bit);

    /* Start timer */
    putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP, RA_GPT_GTWP(gpt_ch));
    uint32_t gtcr = getreg32(RA_GPT_GTCR(gpt_ch)) | GPT_GTCR_CST;
    putreg32(gtcr, RA_GPT_GTCR(gpt_ch));
    putreg32(GPT_GTWP_PRKEY, RA_GPT_GTWP(gpt_ch));

    dshot_ch->bit_index = 1;
}

/**
 * Send a single DShot bit
 */
static void dshot_send_bit(uint8_t channel, bool bit_value)
{
    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];
    uint8_t gpt_ch = dshot_ch->gpt_channel;
    uint32_t compare_value;

    /* Set compare value based on bit value */
    if (bit_value) {
        compare_value = dshot_ch->t1h_period;  /* Bit 1: 75% high */
    } else {
        compare_value = dshot_ch->t0h_period;  /* Bit 0: 37.5% high */
    }

    /* Disable write protection and update compare register */
    putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP, RA_GPT_GTWP(gpt_ch));
    putreg32(compare_value, RA_GPT_GTCCRA(gpt_ch));
    putreg32(GPT_GTWP_PRKEY, RA_GPT_GTWP(gpt_ch));
}

/**
 * Complete DShot frame transmission
 */
static void dshot_complete_frame(uint8_t channel)
{
    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];
    uint8_t gpt_ch = dshot_ch->gpt_channel;

    /* Stop timer */
    putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP, RA_GPT_GTWP(gpt_ch));
    uint32_t gtcr = getreg32(RA_GPT_GTCR(gpt_ch)) & ~GPT_GTCR_CST;
    putreg32(gtcr, RA_GPT_GTCR(gpt_ch));
    putreg32(GPT_GTWP_PRKEY, RA_GPT_GTWP(gpt_ch));

    /* Set output low */
    putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP, RA_GPT_GTWP(gpt_ch));
    putreg32(0, RA_GPT_GTCCRA(gpt_ch));
    putreg32(GPT_GTWP_PRKEY, RA_GPT_GTWP(gpt_ch));

    dshot_ch->state = DSHOT_STATE_COMPLETE;

    /* Start bidirectional reception if enabled */
    if (dshot_ch->bdshot_enabled) {
        dshot_ch->state = BDSHOT_STATE_RECEIVING;
        /* Setup input capture for BDShot telemetry */
        dshot_configure_bdshot_capture(channel);

        /* Reset GPT counter for telemetry timing */
        putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP, RA_GPT_GTWP(gpt_ch));
        putreg32(0, RA_GPT_GTCNT(gpt_ch));
        putreg32(GPT_GTWP_PRKEY, RA_GPT_GTWP(gpt_ch));
    }
}

/**
 * GPT interrupt handler for DShot bit timing
 */
static int dshot_gpt_interrupt(int irq, void *context, void *arg)
{
    uint8_t channel = (uintptr_t)arg;
    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];
    uint8_t gpt_ch = dshot_ch->gpt_channel;

    /* Clear interrupt flag */
    uint32_t gtst = getreg32(RA_GPT_GTST_REG(gpt_ch));
    putreg32(gtst & ~GPT_GTST_TCFA, RA_GPT_GTST_REG(gpt_ch));

    if (dshot_ch->state == DSHOT_STATE_SENDING) {
        if (dshot_ch->bit_index < DSHOT_FRAME_SIZE) {
            /* Send next bit */
            bool bit_value = (dshot_ch->current_frame >> (DSHOT_FRAME_SIZE - 1 - dshot_ch->bit_index)) & 1;
            dshot_send_bit(channel, bit_value);
            dshot_ch->bit_index++;
        } else {
            /* Frame complete */
            dshot_complete_frame(channel);
        }
    }

    return OK;
}

/**
 * BDShot overflow interrupt handler for telemetry timing
 */
static int dshot_bdshot_overflow_interrupt(int irq, void *context, void *arg)
{
    uint8_t channel = (uintptr_t)arg;
    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];
    uint8_t gpt_ch = dshot_ch->gpt_channel;

    /* Clear overflow interrupt flag */
    uint32_t gtst = getreg32(RA_GPT_GTST_REG(gpt_ch));
    putreg32(gtst & ~GPT_GTST_TCFPO, RA_GPT_GTST_REG(gpt_ch));

    if (dshot_ch->state == BDSHOT_STATE_RECEIVING) {
        /* Start telemetry capture - switch to input mode */
        dshot_configure_bdshot_capture(channel);

        /* Implement telemetry bit capture using input capture */
        uint32_t current_time = getreg32(RA_GPT_GTCNT(gpt_ch));
        uint32_t bit_time = current_time - dshot_ch->telemetry_capture_start;

        /* BDShot uses inverted timing: short pulse = 1, long pulse = 0 */
        /* Threshold at 50% of bit period for bit detection */
        uint32_t bit_threshold = dshot_ch->bit_period / 2;
        bool bit_value = (bit_time < bit_threshold) ? 1 : 0;

        /* Store captured bit if we have room */
        if (dshot_ch->telemetry_bit_count < 32) {
            dshot_ch->telemetry_bits[dshot_ch->telemetry_bit_count] = bit_value;
            dshot_ch->telemetry_bit_count++;
        }

        /* Check if we've captured a complete telemetry frame (21 bits for BDShot) */
        if (dshot_ch->telemetry_bit_count >= 21) {
            /* Reconstruct telemetry data from captured bits */
            uint32_t raw_data = 0;
            for (int i = 0; i < 21; i++) {
                raw_data = (raw_data << 1) | dshot_ch->telemetry_bits[i];
            }

            /* Decode the telemetry response */
            bdshot_decode_response(channel, raw_data);
            dshot_ch->state = BDSHOT_STATE_COMPLETE;
        } else {
            /* Update capture start for next bit */
            dshot_ch->telemetry_capture_start = current_time;
        }
    }

    return OK;
}

/**
 * Configure GPT channel for BDShot input capture (telemetry)
 */
static void dshot_configure_bdshot_capture(uint8_t channel)
{
    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];
    uint8_t gpt_ch = dshot_ch->gpt_channel;

    /* Disable write protection */
    putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP, RA_GPT_GTWP(gpt_ch));

    /* Configure GTIOA pin for input capture mode */
    uint32_t gtior = getreg32(RA_GPT_GTIOR(gpt_ch));
    gtior &= ~(0x1F << 0); /* Clear GTIOA bits */
    gtior |= (0x09 << 0);  /* Set GTIOA for rising edge capture */
    putreg32(gtior, RA_GPT_GTIOR(gpt_ch));

    /* Enable capture interrupt */
    putreg32(GPT_GTINTAD_GTINTA, RA_GPT_GTINTAD(gpt_ch));

    /* Re-enable write protection */
    putreg32(GPT_GTWP_PRKEY, RA_GPT_GTWP(gpt_ch));

    /* Initialize telemetry capture state */
    dshot_ch->telemetry_bit_count = 0;
    dshot_ch->telemetry_capture_start = getreg32(RA_GPT_GTCNT(gpt_ch));
}

/**
 * Decode BDShot telemetry response
 */
static void bdshot_decode_response(uint8_t channel, uint32_t raw_data)
{
    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];

    /* Implement BDShot GCR (Generic Cyclic Redundancy) decoding */
    dshot_ch->raw_response = raw_data;

    /* BDShot telemetry format: 21-bit GCR encoded frame */
    /* GCR decoding: convert 21 bits to 16 bits of data */
    uint16_t decoded_data = 0;
    bool decode_success = true;

    /* Simple GCR decode - extract data bits from 21-bit frame */
    /* This is a simplified implementation - full GCR requires lookup table */
    for (int i = 0; i < 16; i++) {
        /* Extract every 4th bit starting from bit 2 (simplified) */
        if (i * 21 / 16 < 21) {
            decoded_data |= ((raw_data >> (20 - (i * 21 / 16))) & 1) << (15 - i);
        }
    }

    if (decode_success) {
        /* Extract eRPM from decoded data (bits 11-4) */
        uint16_t erpm_raw = (decoded_data >> 4) & 0xFF;

        /* Convert to actual eRPM value */
        /* eRPM = (raw_value * 100) / poles (assuming 14 poles) */
        dshot_ch->erpm = (erpm_raw * 100) / 14;

        /* Reset no-response counter on successful decode */
        dshot_ch->no_response_count = 0;
    } else {
        /* Decoding failed */
        dshot_ch->crc_error_count++;
        dshot_ch->erpm = 0;
    }

    dshot_ch->state = BDSHOT_STATE_COMPLETE;
}

/****************************************************************************
 * Public Functions - DShot API Implementation
 ****************************************************************************/

/**
 * Initialize DShot system
 */
int up_dshot_init(uint32_t channel_mask, unsigned dshot_pwm_freq, bool enable_bidirectional_dshot)
{
    irqstate_t flags;
    int ret = OK;

    PX4_INFO("Initializing DShot: mask=0x%lx, freq=%u, bdshot=%s",
             channel_mask, dshot_pwm_freq, enable_bidirectional_dshot ? "yes" : "no");

    /* Validate frequency */
    if (dshot_pwm_freq != DSHOT150_FREQ &&
        dshot_pwm_freq != DSHOT300_FREQ &&
        dshot_pwm_freq != DSHOT600_FREQ) {
        PX4_ERR("Unsupported DShot frequency: %u", dshot_pwm_freq);
        return -EINVAL;
    }

    flags = enter_critical_section();

    /* Initialize global state */
    if (!g_dshot.initialized) {
        memset(&g_dshot, 0, sizeof(g_dshot));
        g_dshot.lock = false;
        g_dshot.initialized = true;
    }

    g_dshot.frequency = dshot_pwm_freq;
    g_dshot.bidirectional_enabled = enable_bidirectional_dshot;
    g_dshot.active_channels = 0;

    /* Initialize requested channels */
    for (uint8_t channel = 0; channel < DSHOT_MAX_CHANNELS; channel++) {
        if (!(channel_mask & (1 << channel))) {
            continue;
        }

        dshot_channel_t *dshot_ch = &g_dshot.channels[channel];

        /* Copy configuration from channel map */
        dshot_ch->gpt_channel = dshot_channel_map[channel].gpt_channel;
        dshot_ch->gpio_pin = dshot_channel_map[channel].gpio_pin;
        dshot_ch->mstp_module = dshot_channel_map[channel].mstp_module;

        /* Enable GPT module clock - simplified approach */
        ra_mstp_start(dshot_ch->gpt_channel); /* Use channel number as MSTP ID */

        /* Calculate timing parameters */
        dshot_ch->bit_period = dshot_calculate_periods(dshot_pwm_freq,
                                                       &dshot_ch->t0h_period,
                                                       &dshot_ch->t1h_period);

        /* Initialize state */
        dshot_ch->bdshot_enabled = enable_bidirectional_dshot;
        dshot_ch->state = DSHOT_STATE_IDLE;
        dshot_ch->current_frame = 0;
        dshot_ch->bit_index = 0;

        /* Reset telemetry counters */
        dshot_ch->crc_error_count = 0;
        dshot_ch->frame_error_count = 0;
        dshot_ch->no_response_count = 0;
        dshot_ch->last_no_response_count = 0;

        /* Configure hardware */
        dshot_configure_gpio(channel);
        dshot_configure_channel(channel);

        /* Setup ICU interrupt for compare match (DShot bit timing) */
        int icu_irq = ra_icu_attach(dshot_channel_map[channel].elc_compare,
                                   dshot_gpt_interrupt,
                                   (void *)(uintptr_t)channel,
                                   true);
        if (icu_irq < 0) {
            PX4_ERR("Failed to attach ICU compare IRQ for channel %d: %d", channel, icu_irq);
            ret = icu_irq;
            break;
        }

        dshot_ch->icu_compare_irq = icu_irq;
        dshot_channel_map[channel].icu_irq = icu_irq;

        /* Setup ICU interrupt for overflow (BDShot telemetry timing) if bidirectional enabled */
        if (enable_bidirectional_dshot) {
            int overflow_irq = ra_icu_attach(dshot_channel_map[channel].elc_overflow,
                                           dshot_bdshot_overflow_interrupt,
                                           (void *)(uintptr_t)channel,
                                           true);
            if (overflow_irq < 0) {
                PX4_ERR("Failed to attach ICU overflow IRQ for channel %d: %d", channel, overflow_irq);
                /* Non-fatal for DShot-only operation */
                dshot_ch->icu_overflow_irq = -1;
            } else {
                dshot_ch->icu_overflow_irq = overflow_irq;
            }
        } else {
            dshot_ch->icu_overflow_irq = -1;
        }

        dshot_ch->initialized = true;
        g_dshot.active_channels |= (1 << channel);

        PX4_DEBUG("DShot channel %d initialized: GPT%d, period=%lu",
                  channel, dshot_ch->gpt_channel, dshot_ch->bit_period);
    }

    spin_unlock_irqrestore(&g_dshot.lock, flags);

    if (ret < 0) {
        PX4_ERR("DShot initialization failed");
        return ret;
    }

    PX4_INFO("DShot initialized successfully: %d channels active",
             __builtin_popcount(g_dshot.active_channels));

    return g_dshot.active_channels;
}

/**
 * Set DShot motor data for a channel
 */
void dshot_motor_data_set(unsigned channel, uint16_t throttle, bool telemetry)
{
    if (channel >= DSHOT_MAX_CHANNELS || !g_dshot.initialized) {
        return;
    }

    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];

    if (!dshot_ch->initialized) {
        return;
    }

    /* Encode DShot frame */
    dshot_ch->current_frame = dshot_encode_frame(throttle, telemetry, dshot_ch->bdshot_enabled);

    PX4_DEBUG("DShot channel %d: throttle=%u, tel=%s, frame=0x%04x",
              channel, throttle, telemetry ? "yes" : "no", dshot_ch->current_frame);
}

/**
 * Trigger DShot data transmission for all channels
 */
void up_dshot_trigger(void)
{
    if (!g_dshot.initialized) {
        return;
    }

    irqstate_t flags = enter_critical_section();

    /* Start transmission on all active channels */
    for (uint8_t channel = 0; channel < DSHOT_MAX_CHANNELS; channel++) {
        if (!(g_dshot.active_channels & (1 << channel))) {
            continue;
        }

        dshot_channel_t *dshot_ch = &g_dshot.channels[channel];

        /* Only start if not already sending and have data */
        if (dshot_ch->state == DSHOT_STATE_IDLE && dshot_ch->current_frame != 0) {
            dshot_start_frame(channel);
        }
    }

    leave_critical_section(flags);
}

/**
 * Arm or disarm DShot outputs
 */
int up_dshot_arm(bool armed)
{
    if (!g_dshot.initialized) {
        return -ENODEV;
    }

    PX4_INFO("DShot %s", armed ? "armed" : "disarmed");

    if (!armed) {
        /* Disarm: Set all channels to DSHOT_DISARM_VALUE */
        for (uint8_t channel = 0; channel < DSHOT_MAX_CHANNELS; channel++) {
            if (g_dshot.active_channels & (1 << channel)) {
                dshot_motor_data_set(channel, 0, false); /* DSHOT_DISARM_VALUE = 0 */
            }
        }

        /* Trigger to send disarm values */
        up_dshot_trigger();
    }

    return OK;
}

/**
 * Get number of BDShot channels ready for telemetry
 */
int up_bdshot_num_erpm_ready(void)
{
    if (!g_dshot.initialized || !g_dshot.bidirectional_enabled) {
        return 0;
    }

    int ready_count = 0;

    for (uint8_t channel = 0; channel < DSHOT_MAX_CHANNELS; channel++) {
        if (!(g_dshot.active_channels & (1 << channel))) {
            continue;
        }

        dshot_channel_t *dshot_ch = &g_dshot.channels[channel];

        if (dshot_ch->state == BDSHOT_STATE_COMPLETE) {
            ready_count++;
        }
    }

    return ready_count;
}

/**
 * Get BDShot eRPM for a channel
 */
int up_bdshot_get_erpm(uint8_t channel, int *erpm)
{
    if (channel >= DSHOT_MAX_CHANNELS || !g_dshot.initialized ||
        !g_dshot.bidirectional_enabled || erpm == NULL) {
        return -EINVAL;
    }

    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];

    if (!dshot_ch->initialized || dshot_ch->state != BDSHOT_STATE_COMPLETE) {
        return -ENODATA;
    }

    *erpm = dshot_ch->erpm;
    dshot_ch->state = DSHOT_STATE_IDLE; /* Reset state after reading */

    return OK;
}

/**
 * Get BDShot channel status
 */
int up_bdshot_channel_status(uint8_t channel)
{
    if (channel >= DSHOT_MAX_CHANNELS || !g_dshot.initialized || !g_dshot.bidirectional_enabled) {
        return -1;
    }

    dshot_channel_t *dshot_ch = &g_dshot.channels[channel];

    if (!dshot_ch->initialized) {
        return -1;
    }

    /* Check if ESC is responding (online if response count delta is less than offline threshold) */
    uint32_t response_delta = dshot_ch->no_response_count - dshot_ch->last_no_response_count;
    dshot_ch->last_no_response_count = dshot_ch->no_response_count;

    return (response_delta < BDSHOT_OFFLINE_COUNT) ? 1 : 0;
}

/**
 * Print BDShot status for all channels
 */
void up_bdshot_status(void)
{
    if (!g_dshot.initialized) {
        PX4_INFO("DShot not initialized");
        return;
    }

    PX4_INFO("DShot Status: freq=%lu Hz, bdshot=%s, channels=0x%lx",
             g_dshot.frequency, g_dshot.bidirectional_enabled ? "enabled" : "disabled",
             g_dshot.active_channels);

    for (uint8_t channel = 0; channel < DSHOT_MAX_CHANNELS; channel++) {
        if (!(g_dshot.active_channels & (1 << channel))) {
            continue;
        }

        dshot_channel_t *dshot_ch = &g_dshot.channels[channel];
        int status = up_bdshot_channel_status(channel);

        PX4_INFO("Channel %d: GPT%d %s, eRPM=%u",
                 channel, dshot_ch->gpt_channel,
                 (status > 0) ? "online" : (status == 0) ? "offline" : "N/A",
                 dshot_ch->erpm);

        if (g_dshot.bidirectional_enabled) {
            PX4_INFO("  CRC errors: %lu, Frame errors: %lu, No response: %lu",
                     dshot_ch->crc_error_count, dshot_ch->frame_error_count,
                     dshot_ch->no_response_count);
        }
    }
}
