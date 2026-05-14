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
 * @file io_timer.h
 *
 * IO Timer interface for RZV2H GPT timers
 */

#pragma once

#include <px4_platform_common/px4_config.h>
#include <nuttx/config.h>
#include <stdint.h>
#include <stdbool.h>

/* Maximum number of IO timers and channels */
#ifndef MAX_IO_TIMERS
#  ifdef BOARD_NUM_IO_TIMERS
#    define MAX_IO_TIMERS       BOARD_NUM_IO_TIMERS
#  else
#    define MAX_IO_TIMERS       8
#  endif
#endif

#ifndef MAX_TIMER_IO_CHANNELS
#  ifdef DIRECT_PWM_OUTPUT_CHANNELS
#    define MAX_TIMER_IO_CHANNELS DIRECT_PWM_OUTPUT_CHANNELS
#  else
#    define MAX_TIMER_IO_CHANNELS 8
#  endif
#endif

/* Timer channel modes */
typedef enum io_timer_channel_mode_t {
	IOTimerChanMode_NotUsed = 0,
	IOTimerChanMode_PWMOut  = 1,
	IOTimerChanMode_PWMIn   = 2,
	IOTimerChanMode_Capture = 3,
	IOTimerChanMode_OneShot = 4,
	IOTimerChanMode_Trigger = 5,
	IOTimerChanMode_Dshot   = 6,
	IOTimerChanMode_LED     = 7,
	IOTimerChanModeSize
} io_timer_channel_mode_t;

/* Timer allocation type */
typedef uint16_t io_timer_channel_allocation_t;

/* Timer configuration structure */
typedef struct io_timers_t {
	uint32_t base;                  /* Base address (0 for HAL-based) */
	uint32_t timer_id;              /* GPT channel number */
	uint32_t vectorno;              /* Interrupt vector */
	uint8_t  first_channel_index;   /* First channel index */
	uint8_t  last_channel_index;    /* Last channel index */
} io_timers_t;

/* DShot configuration */
typedef struct dshot_conf_t {
	uint8_t timer;
	uint8_t channel;
	int8_t  dma_channel;
	int8_t  dma_stream;
} dshot_conf_t;

/* Frequency basis */
typedef enum {
	IOTimerFrequencyBasis_PWM = 0,
	IOTimerFrequencyBasis_Capture = 1,
} IOTimerFrequencyBasis;

/* Timer channel configuration structure */
typedef struct timer_io_channels_t {
	uint32_t gpio_out;              /* GPIO output configuration */
	uint32_t gpio_in;               /* GPIO input configuration */
	uint8_t  timer_index;           /* Timer index in io_timers array */
	uint8_t  timer_channel;         /* Timer channel (A=1, B=2) */
	IOTimerFrequencyBasis freq_basis; /* Frequency basis */
	dshot_conf_t dshot;             /* DShot configuration */
} timer_io_channels_t;

#ifdef __cplusplus
/* Helper macro for DShot configuration */
static inline constexpr dshot_conf_t makeDshotConf(uint8_t timer, uint8_t channel,
		int8_t dma_channel = -1, int8_t dma_stream = -1)
{
	return dshot_conf_t{timer, channel, dma_channel, dma_stream};
}
#endif

__BEGIN_DECLS

/* IO Timer API */
int io_timer_init(void);
int io_timer_validate_channel_index(unsigned channel);
int io_timer_allocate_channel(unsigned channel, io_timer_channel_mode_t mode);
int io_timer_unallocate_channel(unsigned channel);
int io_timer_get_channel_mode(unsigned channel);
int io_timer_allocate_timer(unsigned timer, io_timer_channel_mode_t mode);
int io_timer_unallocate_timer(unsigned timer);
int io_timer_set_pwm_rate(unsigned channel, unsigned rate);
int io_timer_set_enable(bool enable, io_timer_channel_mode_t mode, io_timer_channel_allocation_t masks);
int io_timer_set_ccr(unsigned channel, uint16_t value);
uint16_t io_timer_get_ccr(unsigned channel);
uint32_t io_timer_get_group(unsigned timer);
int io_timer_channel_init(unsigned channel, io_timer_channel_mode_t mode,
			  void (*callback)(void *, uint32_t, uint64_t, uint32_t), void *context);
int io_timer_set_dshot_mode(uint8_t timer, unsigned dshot_pwm_freq, uint8_t dma_burst_length);

/* External declarations */
extern const io_timers_t io_timers[MAX_IO_TIMERS];
extern const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS];

__END_DECLS
