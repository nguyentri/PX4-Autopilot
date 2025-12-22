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
 * @file hrt.c
 *
 * High-resolution timer for RZV2H using GTM0 (OSTM0) as a free-running
 * counter plus compare-driven interrupts for PX4 call scheduling.
 *
 * This closely mirrors the FreeRTOS/FSP implementation (rzv_hrt.cpp) but
 * uses the NuttX GTM/ICU primitives.
 */

#include <px4_platform_common/px4_config.h>
#include <drivers/drv_hrt.h>

#include <nuttx/arch.h>
#include <nuttx/irq.h>

#include <queue.h>
#include <nuttx/clock.h>
#include <nuttx/kmalloc.h>
#include <nuttx/wqueue.h>

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "hardware/rzv_gtm.h"
#include "rzv_clock.h"
#include "rzv_icu.h"
#include "arm_internal.h"

#ifndef CONFIG_RZV_GTM_CLOCK_FREQUENCY
#  define CONFIG_RZV_GTM_CLOCK_FREQUENCY 120000000 /* match PCLKD default */
#endif

#define RZV_HRT_CHANNEL             0
#define RZV_HRT_BASE                RZV_GTM0_BASE
#define RZV_HRT_ELC_EVENT           RZV_ELC_GTM0_GTMTINT
#define RZV_HRT_MIN_TICKS           10U

#ifndef USEC_PER_SEC
#define USEC_PER_SEC                1000000ULL
#endif

#ifndef getreg32
#  define getreg32(a)    (*(volatile uint32_t *)(a))
#endif
#ifndef putreg32
#  define putreg32(v,a)  (*(volatile uint32_t *)(a) = (v))
#endif
#ifndef putreg8
#  define putreg8(v,a)   (*(volatile uint8_t *)(a) = (v))
#endif

static sq_queue_t g_callout_queue;
static volatile uint32_t g_last_counter;
static volatile uint64_t g_accumulated_counts;
static uint32_t g_timer_freq_hz = CONFIG_RZV_GTM_CLOCK_FREQUENCY;
static int g_hrt_irq = -1;
static bool g_initialized = false;

static inline uint32_t gtm_getreg32(unsigned int offset)
{
	return getreg32(RZV_HRT_BASE + offset);
}

static inline void gtm_putreg32(uint32_t val, unsigned int offset)
{
	putreg32(val, RZV_HRT_BASE + offset);
}

static inline void gtm_putreg8(uint8_t val, unsigned int offset)
{
	putreg8(val, RZV_HRT_BASE + offset);
}

static inline uint32_t gtm_read_counter(void)
{
	return gtm_getreg32(RZV_GTM_OSTMCNT_OFFSET);
}

static inline void gtm_start(void)
{
	gtm_putreg8(GTM_OSTMTS_OSTMTS, RZV_GTM_OSTMTS_OFFSET);
}

static inline void gtm_stop(void)
{
	gtm_putreg8(GTM_OSTMTT_OSTMTT, RZV_GTM_OSTMTT_OFFSET);
}

static inline uint64_t counts_to_time_us(uint64_t counts)
{
	if (g_timer_freq_hz == 0) {
		return 0;
	}

	const uint64_t seconds = counts / g_timer_freq_hz;
	const uint64_t remainder = counts % g_timer_freq_hz;
	const uint64_t rounded = (remainder * USEC_PER_SEC + (g_timer_freq_hz / 2U)) / g_timer_freq_hz;
	return seconds * USEC_PER_SEC + rounded;
}

static inline uint32_t time_to_ticks(hrt_abstime delta_us)
{
	if (g_timer_freq_hz == 0) {
		return 0;
	}

	const uint64_t ticks = (delta_us * (uint64_t)g_timer_freq_hz + USEC_PER_SEC / 2ULL) / USEC_PER_SEC;
	return (ticks > UINT32_MAX) ? UINT32_MAX : (uint32_t)ticks;
}

static void hrt_schedule(void);
static void hrt_call_invoke(void);

static inline struct hrt_call *entry_to_call(struct sq_entry_s *entry)
{
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcast-align"
	return (struct hrt_call *)entry;
#pragma GCC diagnostic pop
}

hrt_abstime hrt_absolute_time(void)
{
	irqstate_t flags = enter_critical_section();

	const uint32_t now = gtm_read_counter();
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
	return time_to_ticks(us);
}

hrt_abstime hrt_ticks_to_us(hrt_abstime ticks)
{
	return counts_to_time_us(ticks);
}

void hrt_store_absolute_time(volatile hrt_abstime *now)
{
	irqstate_t flags = enter_critical_section();
	*now = hrt_absolute_time();
	leave_critical_section(flags);
}

static void hrt_program_compare(hrt_abstime deadline)
{
	hrt_abstime now = hrt_absolute_time();

	if (deadline <= now) {
		deadline = now + 1;
	}

	const hrt_abstime delta_us = deadline - now;
	uint32_t ticks = time_to_ticks(delta_us);

	if (ticks < RZV_HRT_MIN_TICKS) {
		ticks = RZV_HRT_MIN_TICKS;
	}

	const uint32_t current = gtm_read_counter();
	gtm_putreg32(current + ticks, RZV_GTM_OSTMCMP_OFFSET);
}

static int hrt_interrupt(int irq, void *context, void *arg)
{
	(void)arg;
	rzv_icu_clear_irq(irq);
	hrt_call_invoke();
	hrt_schedule();
	return OK;
}

static void hrt_call_insert(struct hrt_call *entry)
{
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
}

static void hrt_schedule(void)
{
	irqstate_t flags = enter_critical_section();

	struct hrt_call *next = entry_to_call(g_callout_queue.head);

	if (next && next->deadline != 0) {
		hrt_program_compare(next->deadline);
	} else {
		/* No pending callbacks: park the compare far in the future */
		gtm_putreg32(UINT32_MAX, RZV_GTM_OSTMCMP_OFFSET);
	}

	leave_critical_section(flags);
}

static void hrt_call_invoke(void)
{
	hrt_abstime now = hrt_absolute_time();

	for (;;) {
		irqstate_t flags = enter_critical_section();
		struct hrt_call *call = entry_to_call(g_callout_queue.head);

		if (!call || call->deadline > now) {
			leave_critical_section(flags);
			break;
		}

		/* Pop from queue */
		sq_remfirst(&g_callout_queue);
		call->link.flink = NULL;
		hrt_abstime deadline = call->deadline;
		call->deadline = 0;
		leave_critical_section(flags);

		if (call->callout) {
			call->callout(call->arg);
		}

		/* Requeue periodic calls */
		if (call->period != 0) {
			call->deadline = deadline + call->period;

			flags = enter_critical_section();
			hrt_call_insert(call);
			leave_critical_section(flags);
		}

		now = hrt_absolute_time();
	}
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

	hrt_call_insert(entry);
	leave_critical_section(flags);

	hrt_schedule();
}

void hrt_call_at(struct hrt_call *entry, hrt_abstime calltime, hrt_callout callout, void *arg)
{
	hrt_abstime now = hrt_absolute_time();
	hrt_abstime delay = (calltime > now) ? (calltime - now) : 0;
	hrt_call_after(entry, delay, callout, arg);
}

void hrt_call_every(struct hrt_call *entry, hrt_abstime delay, hrt_abstime interval,
		    hrt_callout callout, void *arg)
{
	irqstate_t flags = enter_critical_section();

	if (entry->deadline != 0) {
		sq_rem(&entry->link, &g_callout_queue);
	}

	entry->deadline = hrt_absolute_time() + delay;
	entry->period = interval;
	entry->callout = callout;
	entry->arg = arg;

	hrt_call_insert(entry);
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
		entry->callout = NULL;
		entry->arg = NULL;
	}

	leave_critical_section(flags);
	hrt_schedule();
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
	hrt_schedule();
}

void hrt_init(void)
{
	if (g_initialized) {
		return;
	}

	sq_init(&g_callout_queue);
	g_last_counter = 0;
	g_accumulated_counts = 0;

	/* Enable clock and configure GTM0 as free-running up-counter */
	(void)rzv_clock_enable(RZV_CPG_CLK_GTM0);
	gtm_stop();
	gtm_putreg8(GTM_MODE_FREERUN, RZV_GTM_OSTMCTL_OFFSET);
	g_last_counter = gtm_read_counter();
	g_accumulated_counts = 0;
	gtm_putreg32(UINT32_MAX, RZV_GTM_OSTMCMP_OFFSET);

	/* Attach interrupt */
	g_hrt_irq = rzv_icu_attach(RZV_HRT_ELC_EVENT, hrt_interrupt, NULL, true);

	if (g_hrt_irq < 0) {
		/* Fail-safe: leave HRT initialized but without IRQ */
		g_hrt_irq = -1;
	}

	gtm_start();
	g_initialized = true;

	/* Default to no pending callbacks */
	hrt_schedule();
}

void hrt_work(void)
{
	hrt_call_invoke();
}

const uint16_t latency_bucket_count = LATENCY_BUCKET_COUNT;
const uint16_t latency_buckets[LATENCY_BUCKET_COUNT] = { 1, 2, 5, 10, 20, 50, 100, 1000 };
EXPORT uint32_t latency_counters[LATENCY_BUCKET_COUNT + 1] = {0};
