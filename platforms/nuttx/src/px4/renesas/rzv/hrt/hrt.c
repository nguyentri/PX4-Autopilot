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
 * PX4 high-resolution timer for RZ/V2H — queue manager only.
 *
 * All register access to the timer counter lives in
 * arch/arm/src/rzv/rzv_hrt.c (GTM7 free-run at P1CLK, runtime clock
 * lookup). This file keeps the PX4 hrt_call queue and delegates
 * counter reads and one-shot arming to the arch driver via
 * rzv_hrt_absolute_time() and rzv_hrt_call_after().
 *
 * Requires CONFIG_RZV_HRT=y so the arch shim is linked.
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

#include "rzv_hrt.h"

#ifndef USEC_PER_SEC
#define USEC_PER_SEC 1000000ULL
#endif

/* Minimum re-arm delay in microseconds. rzv_hrt applies its own tick-level
 * floor (HRT_MIN_TICKS = 10 ticks ≈ 100 ns at P1CLK 100 MHz); the µs-level
 * floor here just avoids scheduling storms when many callouts land in the
 * same tick.
 */
#define HRT_MIN_DELAY_US    1U

static sq_queue_t g_callout_queue;
static bool       g_initialized;

static void hrt_dispatch(void *arg);
static void hrt_call_invoke(void);
static void hrt_schedule_locked(void);

static inline struct hrt_call *entry_to_call(struct sq_entry_s *entry)
{
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcast-align"
	return (struct hrt_call *)entry;
#pragma GCC diagnostic pop
}

hrt_abstime hrt_absolute_time(void)
{
	return (hrt_abstime)rzv_hrt_absolute_time();
}

hrt_abstime hrt_us_to_ticks(hrt_abstime us)
{
	return us;
}

hrt_abstime hrt_ticks_to_us(hrt_abstime ticks)
{
	return ticks;
}

void hrt_store_absolute_time(volatile hrt_abstime *now)
{
	irqstate_t flags = enter_critical_section();
	*now = hrt_absolute_time();
	leave_critical_section(flags);
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

/* Program the arch HRT to fire when the next queued callout is due.
 * Caller holds the critical section. Cancels any previous one-shot
 * before scheduling so the dispatch fires against the current head.
 */
static void hrt_schedule_locked(void)
{
	struct hrt_call *next = entry_to_call(g_callout_queue.head);

	rzv_hrt_cancel();

	if (!next || next->deadline == 0) {
		return;
	}

	hrt_abstime now = hrt_absolute_time();
	uint32_t delay_us;

	if (next->deadline <= now) {
		delay_us = HRT_MIN_DELAY_US;

	} else {
		hrt_abstime diff = next->deadline - now;
		delay_us = (diff > UINT32_MAX) ? UINT32_MAX : (uint32_t)diff;

		if (delay_us < HRT_MIN_DELAY_US) {
			delay_us = HRT_MIN_DELAY_US;
		}
	}

	(void)rzv_hrt_call_after(delay_us, hrt_dispatch, NULL);
}

static void hrt_schedule(void)
{
	irqstate_t flags = enter_critical_section();
	hrt_schedule_locked();
	leave_critical_section(flags);
}

/* Called from rzv_hrt ISR context via rzv_hrt_call_after. Runs the
 * expired head callouts, requeues periodic ones, and reprograms the
 * arch HRT for the next deadline.
 */
static void hrt_dispatch(void *arg)
{
	(void)arg;
	hrt_call_invoke();

	irqstate_t flags = enter_critical_section();
	hrt_schedule_locked();
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
	hrt_schedule_locked();
	leave_critical_section(flags);
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
	hrt_schedule_locked();
	leave_critical_section(flags);
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

	hrt_schedule_locked();
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

	hrt_schedule_locked();
	leave_critical_section(flags);
}

void hrt_init(void)
{
	if (g_initialized) {
		return;
	}

	sq_init(&g_callout_queue);

	/* rzv_hrt_initialize is idempotent (returns OK if already up).
	 * If the arch shim is not built (CONFIG_RZV_HRT=n), the symbol
	 * will not link — that is the intended build-time enforcement.
	 */
	(void)rzv_hrt_initialize();

	g_initialized = true;
}

void hrt_work(void)
{
	hrt_call_invoke();
}

const uint16_t latency_bucket_count = LATENCY_BUCKET_COUNT;
const uint16_t latency_buckets[LATENCY_BUCKET_COUNT] = { 1, 2, 5, 10, 20, 50, 100, 1000 };
__EXPORT uint32_t latency_counters[LATENCY_BUCKET_COUNT + 1] = {0};
