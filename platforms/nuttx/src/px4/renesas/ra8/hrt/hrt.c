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
 * @file hrt.c
 *
 * GPT0-based high-resolution timer for Renesas RA8.
 * - Free-running counter at PCLKD/64.
 * - Compare A interrupt drives PX4 HRT scheduling.
 */

#include <px4_platform_common/px4_config.h>
#include <drivers/drv_hrt.h>

#include <nuttx/arch.h>
#include <nuttx/irq.h>
#include <queue.h>

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "arm_internal.h"
#include "ra_icu.h"
#include "ra_gpt.h"
#include "ra_mstp.h"
#include "hardware/ra8p1/ra_gpt32.h"
#include <arch/ra8/ra8p1_irq.h>
#include "board_config.h"

#ifndef LATENCY_BUCKET_COUNT
#define LATENCY_BUCKET_COUNT 8
#endif

#define HRT_PCLKD_HZ            HRT_TIMER_FREQUENCY
#define HRT_PRESCALER_DIV       64u
#define HRT_TIMER_FREQ_HZ       (HRT_PCLKD_HZ / HRT_PRESCALER_DIV)
#define HRT_MIN_DELTA_US        5u

#ifdef CONFIG_DEBUG_HRT
#  define hrtinfo _info
#else
#  define hrtinfo(x...)
#endif

static sq_queue_t g_callout_queue;
static volatile uint32_t g_last_counter;
static volatile uint64_t g_accumulated_counts;
static int g_hrt_irq = -1;

__attribute__((always_inline))
static inline struct hrt_call *entry_to_call(struct sq_entry_s *entry)
{
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcast-align"
	return (struct hrt_call *)entry;
#pragma GCC diagnostic pop
}

static inline uint32_t gpt_getreg(unsigned int offset)
{
	return getreg32(R_GPT32_CH_BASE(HRT_TIMER) + offset);
}

static inline void gpt_putreg(uint32_t val, unsigned int offset)
{
	putreg32(val, R_GPT32_CH_BASE(HRT_TIMER) + offset);
}

static inline uint64_t counts_to_time_us(uint64_t counts)
{
	return (counts * 1000000ULL) / HRT_TIMER_FREQ_HZ;
}

static inline uint32_t time_to_counts(hrt_abstime us)
{
	const uint64_t ticks = (us * (uint64_t)HRT_TIMER_FREQ_HZ + 500000ULL) / 1000000ULL;
	return (ticks > UINT32_MAX) ? UINT32_MAX : (uint32_t)ticks;
}

static inline uint32_t hrt_read_count(void)
{
	return gpt_getreg(R_GPT32_GTCNT_OFFSET);
}

static void hrt_schedule(void);
static void hrt_call_invoke(void);

static inline void hrt_enable_clock(void)
{
	uint32_t reg = getreg32(R_MSTP_MSTPCRE);
	reg &= ~R_MSTP_MSTPCRE_GPT0;
	putreg32(reg, R_MSTP_MSTPCRE);
}

hrt_abstime hrt_absolute_time(void)
{
	irqstate_t flags = enter_critical_section();

	const uint32_t now = hrt_read_count();
	const uint32_t last = g_last_counter;
	g_last_counter = now;

	const uint32_t delta = now - last;
	g_accumulated_counts += delta;
	const uint64_t counts = g_accumulated_counts;

	leave_critical_section(flags);
	return counts_to_time_us(counts);
}

hrt_abstime hrt_us_to_ticks(hrt_abstime us)
{
	return time_to_counts(us);
}

hrt_abstime hrt_ticks_to_us(hrt_abstime ticks)
{
	return counts_to_time_us(ticks);
}

void hrt_store_absolute_time(volatile hrt_abstime *time_ptr)
{
	irqstate_t flags = enter_critical_section();
	*time_ptr = hrt_absolute_time();
	leave_critical_section(flags);
}

void hrt_cancel_all(void)
{
	while (!sq_empty(&g_callout_queue)) {
		struct sq_entry_s *entry = sq_remfirst(&g_callout_queue);
		if (entry != NULL) {
			struct hrt_call *call = entry_to_call(entry);
			call->deadline = 0;
			call->period = 0;
			call->callout = NULL;
			call->arg = NULL;
		}
	}
}

static void hrt_program_compare(hrt_abstime deadline)
{
	hrt_abstime now = hrt_absolute_time();

	if (deadline <= now) {
		deadline = now + HRT_MIN_DELTA_US;
	}

	const hrt_abstime delta_us = deadline - now;
	uint32_t next_ticks = time_to_counts(delta_us);
	const uint32_t min_ticks = time_to_counts(HRT_MIN_DELTA_US);

	if (next_ticks < min_ticks) {
		next_ticks = min_ticks;
	}

	irqstate_t flags = enter_critical_section();
	const uint32_t current = hrt_read_count();
	const uint32_t compare = current + next_ticks;

	gpt_putreg(GPT_GTWP_PRKEY, R_GPT32_GTWP_OFFSET);
	gpt_putreg(compare, R_GPT32_GTCCRA_OFFSET);
	gpt_putreg(GPT_GTINTAD_GTINTA, R_GPT32_GTINTAD_OFFSET);
	gpt_putreg(GPT_GTWP_PRKEY | R_GPT32_GTWP_WP | R_GPT32_GTWP_CMNWP, R_GPT32_GTWP_OFFSET);

	leave_critical_section(flags);
}

static void hrt_schedule(void)
{
	struct hrt_call *next = entry_to_call(g_callout_queue.head);

	if (next != NULL) {
		hrt_program_compare(next->deadline);
	}
}

static void hrt_call_invoke(void)
{
	hrt_abstime now = hrt_absolute_time();
	struct hrt_call *call = NULL;

	irqstate_t flags = enter_critical_section();

	while ((call = entry_to_call(g_callout_queue.head)) != NULL) {
		if (call->deadline > now) {
			break;
		}

		sq_remfirst(&g_callout_queue);
		hrt_abstime deadline = call->deadline;
		call->deadline = 0;

		leave_critical_section(flags);

		if (call->callout) {
			call->callout(call->arg);
		}

		flags = enter_critical_section();

		if (call->period != 0) {
			call->deadline = deadline + call->period;

			struct hrt_call *pos = entry_to_call(g_callout_queue.head);
			struct hrt_call *prev = NULL;

			while (pos && pos->deadline <= call->deadline) {
				prev = pos;
				pos = entry_to_call(pos->link.flink);
			}

			if (prev) {
				call->link.flink = prev->link.flink;
				prev->link.flink = &call->link;
				if (!call->link.flink) {
					g_callout_queue.tail = &call->link;
				}
			} else {
				call->link.flink = g_callout_queue.head;
				g_callout_queue.head = &call->link;
				if (!g_callout_queue.tail) {
					g_callout_queue.tail = &call->link;
				}
			}
		}
	}

	leave_critical_section(flags);
	hrt_schedule();
}

static int hrt_interrupt(int irq, void *context, void *arg)
{
	(void)irq;
	(void)arg;

	gpt_putreg(GPT_GTWP_PRKEY, R_GPT32_GTWP_OFFSET);
	const uint32_t status = gpt_getreg(R_GPT32_GTST_OFFSET);
	gpt_putreg(status & ~(GPT_GTST_TCFA), R_GPT32_GTST_OFFSET);
	gpt_putreg(GPT_GTWP_PRKEY | R_GPT32_GTWP_WP | R_GPT32_GTWP_CMNWP, R_GPT32_GTWP_OFFSET);

	if (status & GPT_GTST_TCFA) {
		hrt_call_invoke();
	}

	return OK;
}

static void hrt_gpt_start(void)
{
	irqstate_t flags = enter_critical_section();

	hrt_enable_clock();

	gpt_putreg(GPT_GTWP_PRKEY, R_GPT32_GTWP_OFFSET);

	/* Stop and reset */
	uint32_t regval = gpt_getreg(R_GPT32_GTCR_OFFSET);
	regval &= ~GPT_GTCR_CST;
	gpt_putreg(regval, R_GPT32_GTCR_OFFSET);

	gpt_putreg(0, R_GPT32_GTCNT_OFFSET);
	gpt_putreg(0xFFFFFFFF, R_GPT32_GTPR_OFFSET);

	/* Set prescaler and sawtooth up mode */
	regval = GPT_GTCR_MD_SAW_WAVE_UP | GPT_GTCR_TPCS_PCLKD_64;
	gpt_putreg(regval, R_GPT32_GTCR_OFFSET);

	/* Disable compare outputs */
	gpt_putreg(0, R_GPT32_GTIOR_OFFSET);

	/* Enable compare A interrupt */
	gpt_putreg(GPT_GTINTAD_GTINTA, R_GPT32_GTINTAD_OFFSET);

	/* Start */
	regval = gpt_getreg(R_GPT32_GTCR_OFFSET);
	regval |= GPT_GTCR_CST;
	gpt_putreg(regval, R_GPT32_GTCR_OFFSET);

	gpt_putreg(GPT_GTWP_PRKEY | R_GPT32_GTWP_WP | R_GPT32_GTWP_CMNWP, R_GPT32_GTWP_OFFSET);

	leave_critical_section(flags);
}

void hrt_init(void)
{
	sq_init(&g_callout_queue);
	hrt_cancel_all();

	/* Attach ICU interrupt for GPT0 compare A */
	g_hrt_irq = ra_icu_attach(RA_ELC_GPT0_CAPTURE_COMPARE_A, hrt_interrupt, NULL, true);
	DEBUGASSERT(g_hrt_irq >= 0);

	g_last_counter = hrt_read_count();
	g_accumulated_counts = 0;

	hrt_gpt_start();
	hrt_schedule();
}

void hrt_call_after(struct hrt_call *entry, hrt_abstime delay, hrt_callout callout, void *arg)
{
	irqstate_t flags = enter_critical_section();

	if (entry->deadline != 0) {
		sq_rem(&entry->link, &g_callout_queue);
	}

	entry->deadline = hrt_absolute_time() + delay;
	entry->period = 0;
	entry->callout = callout;
	entry->arg = arg;

	struct hrt_call *pos = entry_to_call(g_callout_queue.head);
	struct hrt_call *prev = NULL;

	while (pos && pos->deadline <= entry->deadline) {
		prev = pos;
		pos = entry_to_call(pos->link.flink);
	}

	if (prev) {
		entry->link.flink = prev->link.flink;
		prev->link.flink = &entry->link;
		if (!entry->link.flink) {
			g_callout_queue.tail = &entry->link;
		}
	} else {
		entry->link.flink = g_callout_queue.head;
		g_callout_queue.head = &entry->link;
		if (!g_callout_queue.tail) {
			g_callout_queue.tail = &entry->link;
		}
	}

	leave_critical_section(flags);
	hrt_schedule();
}

void hrt_call_at(struct hrt_call *entry, hrt_abstime calltime, hrt_callout callout, void *arg)
{
	hrt_abstime now = hrt_absolute_time();
	hrt_abstime delay = (calltime > now) ? (calltime - now) : 0;
	hrt_call_after(entry, delay, callout, arg);
}

void hrt_call_every(struct hrt_call *entry, hrt_abstime delay, hrt_abstime interval, hrt_callout callout, void *arg)
{
	irqstate_t flags = enter_critical_section();

	if (entry->deadline != 0) {
		sq_rem(&entry->link, &g_callout_queue);
	}

	entry->deadline = hrt_absolute_time() + delay;
	entry->period = interval;
	entry->callout = callout;
	entry->arg = arg;

	struct hrt_call *pos = entry_to_call(g_callout_queue.head);
	struct hrt_call *prev = NULL;

	while (pos && pos->deadline <= entry->deadline) {
		prev = pos;
		pos = entry_to_call(pos->link.flink);
	}

	if (prev) {
		entry->link.flink = prev->link.flink;
		prev->link.flink = &entry->link;
		if (!entry->link.flink) {
			g_callout_queue.tail = &entry->link;
		}
	} else {
		entry->link.flink = g_callout_queue.head;
		g_callout_queue.head = &entry->link;
		if (!g_callout_queue.tail) {
			g_callout_queue.tail = &entry->link;
		}
	}

	leave_critical_section(flags);
	hrt_schedule();
}

bool hrt_called(struct hrt_call *entry)
{
	return (entry->deadline == 0);
}

void hrt_cancel(struct hrt_call *entry)
{
	irqstate_t flags = enter_critical_section();

	if (entry->deadline != 0) {
		sq_rem(&entry->link, &g_callout_queue);
		entry->deadline = 0;
		entry->period = 0;
	}

	leave_critical_section(flags);
}

void hrt_call_init(struct hrt_call *entry)
{
	memset(entry, 0, sizeof(*entry));
}

void hrt_call_delay(struct hrt_call *entry, hrt_abstime delay)
{
	irqstate_t flags = enter_critical_section();
	if (entry->deadline != 0) {
		entry->deadline += delay;
	}
	leave_critical_section(flags);
}

void hrt_work(void)
{
	hrt_call_invoke();
}

const uint16_t latency_bucket_count = LATENCY_BUCKET_COUNT;
const uint16_t latency_buckets[LATENCY_BUCKET_COUNT] = { 1, 2, 5, 10, 20, 50, 100, 1000 };
__EXPORT uint32_t latency_counters[LATENCY_BUCKET_COUNT + 1] = {0};
