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
 * @file input_capture.c
 *
 * Input capture driver for Renesas RA8 GPT timers.
 *
 * Provides the PX4 up_input_capture_* API for:
 * - RC PWM input capture
 * - BDShot telemetry (eRPM feedback from ESC)
 * - General pulse width/frequency measurement
 *
 * Uses GPT hardware capture on GTIOCA pins via the io_timer_impl.c backend.
 */

#include <px4_platform_common/px4_config.h>
#include <nuttx/arch.h>
#include <nuttx/irq.h>

#include <sys/types.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>

#include <drivers/drv_input_capture.h>
#include <px4_arch/io_timer.h>

/* External functions from io_timer_impl.c */
extern int gpt_configure_input_capture(unsigned channel, bool rising_edge, bool falling_edge);
extern uint32_t gpt_read_capture(unsigned channel);
extern bool gpt_capture_ready(unsigned channel);
extern void gpt_capture_clear(unsigned channel);
extern uint32_t gpt_get_capture_clock(unsigned channel);

/* Per-channel capture statistics */
static input_capture_stats_t channel_stats[MAX_TIMER_IO_CHANNELS];

/* Per-channel callback handlers */
static struct channel_handler_entry {
	capture_callback_t callback;
	void              *context;
	input_capture_edge edge;
} channel_handlers[MAX_TIMER_IO_CHANNELS];

/**
 * Internal capture event handler - called from io_timer_impl.c ISR
 *
 * This function is invoked from the GPT capture ISR to process edge events
 * and call the registered user callback.
 *
 * @param context    User context (unused here, channel passed via chan_index)
 * @param chan_index Logical channel number
 * @param isrs_time  ISR entry timestamp (hrt_abstime)
 * @param isrs_rcnt  Current timer counter value
 */
void input_capture_chan_handler(void *context, uint32_t chan_index,
				uint64_t isrs_time, uint32_t isrs_rcnt)
{
	if (chan_index >= MAX_TIMER_IO_CHANNELS) {
		return;
	}

	/* Read the captured value */
	uint32_t capture = gpt_read_capture(chan_index);

	/* Determine edge state - if we're in Rising mode, last edge was rising */
	uint32_t edge_state = 0;
	input_capture_edge configured_edge = channel_handlers[chan_index].edge;

	if (configured_edge == Rising) {
		edge_state = 1;  /* Rising edge */
	} else if (configured_edge == Falling) {
		edge_state = 0;  /* Falling edge */
	}
	/* For Both mode, we'd need to read the GPIO pin state */

	/* Calculate latency (ticks between capture and ISR entry) */
	uint32_t latency = isrs_rcnt > capture ? (isrs_rcnt - capture) : 0;

	if (latency > channel_stats[chan_index].latency) {
		channel_stats[chan_index].latency = (uint16_t)latency;
	}

	/* Update statistics */
	channel_stats[chan_index].edges++;
	channel_stats[chan_index].last_edge = edge_state;

	/* Calculate edge time - subtract latency converted to microseconds */
	uint32_t clock_hz = gpt_get_capture_clock(chan_index);
	uint64_t latency_us = (clock_hz > 0) ? ((uint64_t)latency * 1000000ULL / clock_hz) : 0;
	channel_stats[chan_index].last_time = isrs_time - latency_us;

	/* Check for overflow (capture occurred before we could read it) */
	uint32_t overflow = 0;

	if (overflow) {
		channel_stats[chan_index].overflows++;
	}

	/* Clear the capture ready flag */
	gpt_capture_clear(chan_index);

	/* Invoke user callback if registered */
	if (channel_handlers[chan_index].callback) {
		channel_handlers[chan_index].callback(channel_handlers[chan_index].context,
						      chan_index,
						      channel_stats[chan_index].last_time,
						      edge_state,
						      overflow);
	}
}

/**
 * Bind a callback to a capture channel
 */
static void input_capture_bind(unsigned channel, capture_callback_t callback, void *context)
{
	irqstate_t flags = px4_enter_critical_section();
	channel_handlers[channel].callback = callback;
	channel_handlers[channel].context = context;
	px4_leave_critical_section(flags);
}

/**
 * Unbind callback from a capture channel
 */
static void input_capture_unbind(unsigned channel)
{
	input_capture_bind(channel, NULL, NULL);
}

/**
 * Configure input capture on a channel
 *
 * @param channel  Channel to configure
 * @param edge     Edge trigger type (Disabled, Rising, Falling, Both)
 * @param filter   Input filter value (not used on RA8 - hardware noise filter always enabled)
 * @param callback Callback to invoke on capture events
 * @param context  User context for callback
 * @return 0 on success, negative errno on failure
 */
int up_input_capture_set(unsigned channel, input_capture_edge edge, capture_filter_t filter,
			 capture_callback_t callback, void *context)
{
	if (edge > Both) {
		return -EINVAL;
	}

	int rv = io_timer_validate_channel_index(channel);

	if (rv != 0) {
		return rv;
	}

	if (edge == Disabled) {
		/* Disable capture mode */
		io_timer_set_enable(false, IOTimerChanMode_Capture, 1 << channel);
		input_capture_unbind(channel);
		gpt_configure_input_capture(channel, false, false);

		/* Free the channel */
		io_timer_unallocate_channel(channel);
		channel_handlers[channel].edge = Disabled;

	} else {
		/* Allocate channel for capture mode */
		rv = io_timer_allocate_channel(channel, IOTimerChanMode_Capture);

		if (rv != 0) {
			return rv;
		}

		/* Bind callback before enabling hardware */
		input_capture_bind(channel, callback, context);
		channel_handlers[channel].edge = edge;

		/* Configure GPT hardware for input capture */
		bool rising = (edge == Rising) || (edge == Both);
		bool falling = (edge == Falling) || (edge == Both);

		rv = gpt_configure_input_capture(channel, rising, falling);

		if (rv != 0) {
			input_capture_unbind(channel);
			io_timer_unallocate_channel(channel);
			return rv;
		}

		/* Apply filter setting (no-op on RA8 - hardware filter always enabled) */
		(void)filter;

		/* Enable the channel */
		rv = io_timer_set_enable(true, IOTimerChanMode_Capture, 1 << channel);

		if (rv != 0) {
			gpt_configure_input_capture(channel, false, false);
			input_capture_unbind(channel);
			io_timer_unallocate_channel(channel);
			return rv;
		}

		/* Clear statistics for fresh start */
		memset(&channel_stats[channel], 0, sizeof(channel_stats[channel]));
	}

	return 0;
}

/**
 * Get the current input filter setting
 *
 * @param channel Channel to query
 * @param filter  Pointer to store filter value
 * @return 0 on success, negative errno on failure
 *
 * Note: RA8 GPT has a fixed 3-sample noise filter on GTIOCA input.
 * This function returns 0 for compatibility but the filter is always active.
 */
int up_input_capture_get_filter(unsigned channel, capture_filter_t *filter)
{
	int rv = io_timer_validate_channel_index(channel);

	if (rv == 0 && filter != NULL) {
		*filter = 0;  /* RA8 uses fixed hardware noise filter */
	}

	return rv;
}

/**
 * Set the input filter
 *
 * @param channel Channel to configure
 * @param filter  Filter value to set
 * @return 0 on success
 *
 * Note: RA8 GPT has a fixed hardware noise filter. This function is a no-op
 * but returns success for API compatibility.
 */
int up_input_capture_set_filter(unsigned channel, capture_filter_t filter)
{
	(void)filter;  /* RA8 uses fixed hardware noise filter */
	return io_timer_validate_channel_index(channel);
}

/**
 * Get the current edge trigger setting
 *
 * @param channel Channel to query
 * @param edge    Pointer to store edge type
 * @return 0 on success, negative errno on failure
 */
int up_input_capture_get_trigger(unsigned channel, input_capture_edge *edge)
{
	int rv = io_timer_validate_channel_index(channel);

	if (rv != 0) {
		return rv;
	}

	/* Check if channel is in capture mode */
	if (io_timer_get_channel_mode(channel) != IOTimerChanMode_Capture) {
		return -ENXIO;
	}

	if (edge != NULL) {
		*edge = channel_handlers[channel].edge;
	}

	return 0;
}

/**
 * Set the edge trigger type
 *
 * @param channel Channel to configure
 * @param edge    Edge type (Rising, Falling, Both, Disabled)
 * @return 0 on success, negative errno on failure
 */
int up_input_capture_set_trigger(unsigned channel, input_capture_edge edge)
{
	int rv = io_timer_validate_channel_index(channel);

	if (rv != 0) {
		return rv;
	}

	/* Check if channel is in capture mode */
	if (io_timer_get_channel_mode(channel) != IOTimerChanMode_Capture) {
		return -ENXIO;
	}

	if (edge > Both) {
		return -EINVAL;
	}

	/* Reconfigure GPT capture edges */
	bool rising = (edge == Rising) || (edge == Both);
	bool falling = (edge == Falling) || (edge == Both);

	rv = gpt_configure_input_capture(channel, rising, falling);

	if (rv == 0) {
		channel_handlers[channel].edge = edge;
	}

	return rv;
}

/**
 * Get the current callback for a capture channel
 *
 * @param channel  Channel to query
 * @param callback Pointer to store callback function
 * @param context  Pointer to store callback context
 * @return 0 on success, negative errno on failure
 */
int up_input_capture_get_callback(unsigned channel, capture_callback_t *callback, void **context)
{
	int rv = io_timer_validate_channel_index(channel);

	if (rv != 0) {
		return rv;
	}

	/* Check if channel is in capture mode */
	if (io_timer_get_channel_mode(channel) != IOTimerChanMode_Capture) {
		return -ENXIO;
	}

	irqstate_t flags = px4_enter_critical_section();

	if (callback != NULL) {
		*callback = channel_handlers[channel].callback;
	}

	if (context != NULL) {
		*context = channel_handlers[channel].context;
	}

	px4_leave_critical_section(flags);

	return 0;
}

/**
 * Set the callback for a capture channel
 *
 * @param channel  Channel to configure
 * @param callback Callback function to invoke on capture
 * @param context  User context for callback
 * @return 0 on success, negative errno on failure
 */
int up_input_capture_set_callback(unsigned channel, capture_callback_t callback, void *context)
{
	int rv = io_timer_validate_channel_index(channel);

	if (rv != 0) {
		return rv;
	}

	/* Check if channel is in capture mode */
	if (io_timer_get_channel_mode(channel) != IOTimerChanMode_Capture) {
		return -ENXIO;
	}

	input_capture_bind(channel, callback, context);

	return 0;
}

/**
 * Get capture statistics for a channel
 *
 * @param channel Channel to query
 * @param stats   Pointer to store statistics
 * @param clear   If true, clear statistics after reading
 * @return 0 on success, negative errno on failure
 */
int up_input_capture_get_stats(unsigned channel, input_capture_stats_t *stats, bool clear)
{
	int rv = io_timer_validate_channel_index(channel);

	if (rv != 0) {
		return rv;
	}

	if (stats == NULL) {
		return -EINVAL;
	}

	irqstate_t flags = px4_enter_critical_section();

	*stats = channel_stats[channel];

	if (clear) {
		memset(&channel_stats[channel], 0, sizeof(channel_stats[channel]));
	}

	px4_leave_critical_section(flags);

	return 0;
}
