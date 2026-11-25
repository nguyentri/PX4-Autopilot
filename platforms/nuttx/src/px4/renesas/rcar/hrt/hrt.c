/****************************************************************************
 *
 *   Copyright (c) 2026 PX4 Development Team. All rights reserved.
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
 * High-resolution timer for the R-Car V4H Cortex-R52 on the EL1 virtual
 * generic timer.
 *
 * Time base: CNTVCT, the 64-bit virtual count.  The EL2 boot code zeroes
 * CNTVOFF, so it equals the physical count that NuttX uses for its tick
 * (the EL1 physical timer, PPI 30) and never wraps in practice.  The
 * frequency is read from CNTFRQ once (16.666667 MHz on R-Car V4H, so one
 * tick is 60 ns).
 *
 * Callouts: one sorted queue of hrt_call entries.  The head deadline is
 * converted to an absolute count and written to CNTV_CVAL; the virtual
 * timer interrupt (PPI 27, level) runs the expired entries and re-arms the
 * compare.  An empty queue disables the timer, which also drops the level
 * interrupt.  Converting a deadline rounds up, so the interrupt never comes
 * before the deadline it was armed for.
 */

#include <px4_platform_common/px4_config.h>
#include <drivers/drv_hrt.h>

#include <nuttx/arch.h>
#include <nuttx/irq.h>
#include <arch/irq.h>

#include <queue.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "rcar_irq.h"

#define HRT_USEC_PER_SEC    1000000ULL

/* CNTV_CTL bits */
#define CNTV_CTL_ENABLE     (1u << 0)
#define CNTV_CTL_IMASK      (1u << 1)

static sq_queue_t g_callout_queue;
static bool       g_initialized;
static uint32_t   g_cntfrq;

static void hrt_call_invoke(void);
static void hrt_schedule_locked(void);

/* Generic timer access (AArch32 CP15, armv8-r/cp15.h encodings) */

static inline uint32_t cntfrq_read(void)
{
	uint32_t v;
	__asm__ volatile("mrc p15, 0, %0, c14, c0, 0" : "=r"(v));
	return v;
}

static inline uint64_t cntvct_read(void)
{
	uint32_t lo;
	uint32_t hi;
	__asm__ volatile("isb\n\tmrrc p15, 1, %0, %1, c14" : "=r"(lo), "=r"(hi) :: "memory");
	return ((uint64_t)hi << 32) | lo;
}

static inline void cntv_cval_write(uint64_t cval)
{
	__asm__ volatile("mcrr p15, 3, %0, %1, c14\n\tisb"
			 :: "r"((uint32_t)cval), "r"((uint32_t)(cval >> 32)) : "memory");
}

static inline void cntv_ctl_write(uint32_t ctl)
{
	__asm__ volatile("mcr p15, 0, %0, c14, c3, 1\n\tisb" :: "r"(ctl) : "memory");
}

/* Count <-> microsecond conversion.  Split at whole seconds so that the
 * 64-bit products cannot overflow for any count the timer reaches.
 */

static inline uint64_t count_to_us(uint64_t count)
{
	return (count / g_cntfrq) * HRT_USEC_PER_SEC
	       + ((count % g_cntfrq) * HRT_USEC_PER_SEC) / g_cntfrq;
}

static inline uint64_t us_to_count_ceil(uint64_t us)
{
	return (us / HRT_USEC_PER_SEC) * g_cntfrq
	       + ((us % HRT_USEC_PER_SEC) * g_cntfrq + HRT_USEC_PER_SEC - 1) / HRT_USEC_PER_SEC;
}

static inline struct hrt_call *entry_to_call(struct sq_entry_s *entry)
{
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcast-align"
	return (struct hrt_call *)entry;
#pragma GCC diagnostic pop
}

hrt_abstime hrt_absolute_time(void)
{
	/* Callers may ask for the time before hrt_init() */
	if (g_cntfrq == 0) {
		g_cntfrq = cntfrq_read();
	}

	return (hrt_abstime)count_to_us(cntvct_read());
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

/* Arm the virtual timer for the head callout, or disable it when the queue
 * is empty.  Caller holds the critical section.  A deadline already in the
 * past gives a compare at or below the count: the interrupt is then raised
 * at once, so no minimum delay is needed.
 */
static void hrt_schedule_locked(void)
{
	struct hrt_call *next = entry_to_call(g_callout_queue.head);

	if (!g_initialized) {
		return;
	}

	if (!next || next->deadline == 0) {
		cntv_ctl_write(CNTV_CTL_IMASK);
		return;
	}

	cntv_cval_write(us_to_count_ceil(next->deadline));
	cntv_ctl_write(CNTV_CTL_ENABLE);
}

static int hrt_tim_isr(int irq, void *context, void *arg)
{
	(void)irq;
	(void)context;
	(void)arg;

	hrt_call_invoke();

	irqstate_t flags = enter_critical_section();
	hrt_schedule_locked();
	leave_critical_section(flags);
	return 0;
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

		sq_remfirst(&g_callout_queue);
		call->link.flink = NULL;
		hrt_abstime deadline = call->deadline;
		call->deadline = 0;
		leave_critical_section(flags);

		if (call->callout) {
			call->callout(call->arg);
		}

		/* Requeue periodic calls.  hrt_call_delay() may have set a new
		 * deadline from inside the callback; hrt_cancel() may have cleared
		 * the period to suppress this requeue.
		 */
		if (call->period != 0) {
			flags = enter_critical_section();

			if (call->deadline <= now) {
				call->deadline = deadline + call->period;
			}

			hrt_call_insert(call);
			leave_critical_section(flags);
		}

		now = hrt_absolute_time();
	}
}

static void hrt_call_internal(struct hrt_call *entry, hrt_abstime deadline, hrt_abstime interval,
			      hrt_callout callout, void *arg)
{
	irqstate_t flags = enter_critical_section();

	if (entry->deadline != 0) {
		sq_rem(&entry->link, &g_callout_queue);
	}

	entry->deadline = deadline;
	entry->period = interval;
	entry->callout = callout;
	entry->arg = arg;

	hrt_call_insert(entry);
	hrt_schedule_locked();
	leave_critical_section(flags);
}

void hrt_call_after(struct hrt_call *entry, hrt_abstime delay, hrt_callout callout, void *arg)
{
	hrt_call_internal(entry, hrt_absolute_time() + delay, 0, callout, arg);
}

void hrt_call_at(struct hrt_call *entry, hrt_abstime calltime, hrt_callout callout, void *arg)
{
	hrt_call_internal(entry, calltime, 0, callout, arg);
}

void hrt_call_every(struct hrt_call *entry, hrt_abstime delay, hrt_abstime interval,
		    hrt_callout callout, void *arg)
{
	hrt_call_internal(entry, hrt_absolute_time() + delay, interval, callout, arg);
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
	}

	entry->link.flink = NULL;
	entry->deadline = 0;
	entry->period = 0;
	entry->callout = NULL;
	entry->arg = NULL;

	hrt_schedule_locked();
	leave_critical_section(flags);
}

void hrt_call_init(struct hrt_call *entry)
{
	memset(entry, 0, sizeof(*entry));
}

void hrt_call_delay(struct hrt_call *entry, hrt_abstime delay)
{
	/* Only valid from inside the entry's own callout, where the entry is
	 * off the queue: the dispatcher then requeues it at this deadline.
	 */
	entry->deadline = hrt_absolute_time() + delay;
}

void hrt_init(void)
{
	if (g_initialized) {
		return;
	}

	sq_init(&g_callout_queue);

	g_cntfrq = cntfrq_read();

	if (g_cntfrq == 0) {
		/* CNTFRQ is written by the boot image; without it there is no time base */
		PANIC();
	}

	cntv_ctl_write(CNTV_CTL_IMASK);
	irq_attach(RCAR_IRQ_VTIMER, hrt_tim_isr, NULL);
	rcar_irq_set_type(RCAR_IRQ_VTIMER, false);
	g_initialized = true;
	up_enable_irq(RCAR_IRQ_VTIMER);
}

void hrt_work(void)
{
	hrt_call_invoke();
}

const uint16_t latency_bucket_count = LATENCY_BUCKET_COUNT;
const uint16_t latency_buckets[LATENCY_BUCKET_COUNT] = { 1, 2, 5, 10, 20, 50, 100, 1000 };
__EXPORT uint32_t latency_counters[LATENCY_BUCKET_COUNT + 1] = {0};
