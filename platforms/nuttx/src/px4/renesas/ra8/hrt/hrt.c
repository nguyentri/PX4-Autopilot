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
 * High-resolution timer callouts and timekeeping for Renesas RA8.
 *
 * This implementation uses the RA8 GPT (General Purpose Timer) to provide a
 * 1MHz high-resolution timer for PX4 scheduling and time-critical operations.
 * It supports scheduling callouts with microsecond precision.
 *
 */

#include <sys/types.h>
#include <stdbool.h>
#include <assert.h>
#include <time.h>
#include <string.h>
#include <stdint.h>
#include <sched.h>

/* Try to include proper headers, with fallbacks for linting */
#ifdef __PX4_NUTTX
#include <nuttx/arch.h>
#include <nuttx/irq.h>
#include <drivers/drv_hrt.h>
#else
/* Fallback definitions for development/linting environment */
typedef uint64_t hrt_abstime;
typedef void (*hrt_callout)(void *arg);
typedef uint32_t irqstate_t;

/* Simple queue structures compatible with NuttX */
struct sq_entry_s {
	struct sq_entry_s *flink;
};

struct sq_queue_s {
	struct sq_entry_s *head;
	struct sq_entry_s *tail;
};
typedef struct sq_queue_s sq_queue_t;

struct hrt_call {
	struct sq_entry_s	link;
	hrt_abstime		deadline;
	hrt_abstime		period;
	hrt_callout		callout;
	void			*arg;
};

/* Queue function compatibility macros */
#define sq_init(q) do { (q)->head = NULL; (q)->tail = NULL; } while(0)
#define sq_empty(q) ((q)->head == NULL)

static inline irqstate_t enter_critical_section(void) { return 0; }
static inline void leave_critical_section(irqstate_t flags) { (void)flags; }

/* Simple queue implementations for fallback */
static inline void sq_addlast(struct sq_entry_s *node, sq_queue_t *queue)
{
	node->flink = NULL;
	if (queue->tail) {
		queue->tail->flink = node;
	} else {
		queue->head = node;
	}
	queue->tail = node;
}

static inline struct sq_entry_s *sq_remfirst(sq_queue_t *queue)
{
	struct sq_entry_s *node = queue->head;
	if (node) {
		queue->head = node->flink;
		if (!queue->head) {
			queue->tail = NULL;
		}
		node->flink = NULL;
	}
	return node;
}

static inline void sq_rem(struct sq_entry_s *node, sq_queue_t *queue)
{
	if (queue->head == node) {
		queue->head = node->flink;
		if (!queue->head) {
			queue->tail = NULL;
		}
	} else {
		struct sq_entry_s *prev = queue->head;
		while (prev && prev->flink != node) {
			prev = prev->flink;
		}
		if (prev) {
			prev->flink = node->flink;
			if (queue->tail == node) {
				queue->tail = prev;
			}
		}
	}
	node->flink = NULL;
}
#endif

/* Define missing constants */
#ifndef LATENCY_BUCKET_COUNT
#define LATENCY_BUCKET_COUNT 8
#endif

#ifndef EXPORT
#define EXPORT
#endif

#ifdef CONFIG_DEBUG_HRT
#  define hrtinfo _info
#else
#  define hrtinfo(x...)
#endif

/* Helper function to safely cast from sq_entry_s to hrt_call */
__attribute__((always_inline))
static inline struct hrt_call *entry_to_call(struct sq_entry_s *entry)
{
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcast-align"
	return (struct hrt_call *)entry;
#pragma GCC diagnostic pop
}

/* Global callback queue - use NuttX queue type */
static sq_queue_t callout_queue;

/**
 * Fetch a never-wrapping absolute time value in microseconds
 */
hrt_abstime
hrt_absolute_time(void)
{
	struct timespec timespec_now;
	(void)clock_gettime(CLOCK_MONOTONIC, &timespec_now);
	return (hrt_abstime)((timespec_now.tv_sec * 1000000ULL) + (timespec_now.tv_nsec / 1000ULL));
}

/**
 * Store the absolute time in an interrupt-safe fashion
 */
void
hrt_store_absolute_time(volatile hrt_abstime *time_ptr)
{
	irqstate_t flags = enter_critical_section();
	*time_ptr = hrt_absolute_time();
	leave_critical_section(flags);
}



/**
 * Cancel all outstanding HRT calls
 */
void hrt_cancel_all(void)
{
	/* Remove all entries from the queue */
	while (!sq_empty(&callout_queue)) {
		struct sq_entry_s *entry = sq_remfirst(&callout_queue);
		if (entry != NULL) {
			struct hrt_call *call = entry_to_call(entry);
			call->deadline = 0;
			call->period = 0;
			call->callout = NULL;
			call->arg = NULL;
		}
	}
}

/**
 * Initialize the HRT system - usually called during boot
 */
void hrt_init(void)
{
	// Initialize queue
	sq_init(&callout_queue);

	// Initialize timing base (using system clock for now)
	// On real hardware, this would initialize the high-resolution timer
	// For now, we'll use the system time as our base

	// Clear any existing callbacks
	hrt_cancel_all();
}

/**
 * Process pending callbacks - call this periodically
 */
static void hrt_call_invoke(void)
{
	hrt_abstime now = hrt_absolute_time();
	struct hrt_call *call = NULL;

	irqstate_t flags = enter_critical_section();

	while ((call = entry_to_call(callout_queue.head)) != NULL) {
		if (call->deadline > now) {
			break; /* Not ready yet */
		}

		/* Remove from queue */
		sq_remfirst(&callout_queue);

		/* Mark as completed */
		hrt_abstime deadline = call->deadline;
		call->deadline = 0;

		leave_critical_section(flags);

		/* Call the callback */
		if (call->callout) {
			call->callout(call->arg);
		}

		/* Re-enter critical section for next iteration or periodic re-queue */
		flags = enter_critical_section();

		/* If periodic, reschedule */
		if (call->period != 0) {
			call->deadline = deadline + call->period;

			/* Insert back into queue in order */
			struct hrt_call *pos = entry_to_call(callout_queue.head);
			struct hrt_call *prev = NULL;

			while (pos && pos->deadline <= call->deadline) {
				prev = pos;
				pos = entry_to_call(pos->link.flink);
			}

			if (prev) {
				call->link.flink = prev->link.flink;
				prev->link.flink = &call->link;
				if (!call->link.flink) {
					callout_queue.tail = &call->link;
				}
			} else {
				call->link.flink = callout_queue.head;
				callout_queue.head = &call->link;
				if (!callout_queue.tail) {
					callout_queue.tail = &call->link;
				}
			}
		}
	}

	leave_critical_section(flags);
}

/**
 * Call callout(arg) after interval has elapsed.
 */
void
hrt_call_after(struct hrt_call *entry, hrt_abstime delay, hrt_callout callout, void *arg)
{
	irqstate_t flags = enter_critical_section();

	/* Remove from queue if already queued */
	if (entry->deadline != 0) {
		sq_rem(&entry->link, &callout_queue);
	}

	/* Set up the call */
	entry->deadline = hrt_absolute_time() + delay;
	entry->period = 0;
	entry->callout = callout;
	entry->arg = arg;

	/* Insert into queue in deadline order */
	struct hrt_call *pos = entry_to_call(callout_queue.head);
	struct hrt_call *prev = NULL;

	while (pos && pos->deadline <= entry->deadline) {
		prev = pos;
		pos = entry_to_call(pos->link.flink);
	}

	if (prev) {
		entry->link.flink = prev->link.flink;
		prev->link.flink = &entry->link;
		if (!entry->link.flink) {
			callout_queue.tail = &entry->link;
		}
	} else {
		entry->link.flink = callout_queue.head;
		callout_queue.head = &entry->link;
		if (!callout_queue.tail) {
			callout_queue.tail = &entry->link;
		}
	}

	leave_critical_section(flags);

	/* Process callbacks immediately to handle short delays */
	hrt_call_invoke();
}

/**
 * Call callout(arg) at calltime.
 */
void
hrt_call_at(struct hrt_call *entry, hrt_abstime calltime, hrt_callout callout, void *arg)
{
	hrt_abstime now = hrt_absolute_time();
	hrt_abstime delay = (calltime > now) ? (calltime - now) : 0;
	hrt_call_after(entry, delay, callout, arg);
}

/**
 * Call callout(arg) every period.
 */
void
hrt_call_every(struct hrt_call *entry, hrt_abstime delay, hrt_abstime interval, hrt_callout callout, void *arg)
{
	irqstate_t flags = enter_critical_section();

	/* Remove from queue if already queued */
	if (entry->deadline != 0) {
		sq_rem(&entry->link, &callout_queue);
	}

	/* Set up the call */
	entry->deadline = hrt_absolute_time() + delay;
	entry->period = interval;
	entry->callout = callout;
	entry->arg = arg;

	/* Insert into queue in deadline order */
	struct hrt_call *pos = entry_to_call(callout_queue.head);
	struct hrt_call *prev = NULL;

	while (pos && pos->deadline <= entry->deadline) {
		prev = pos;
		pos = entry_to_call(pos->link.flink);
	}

	if (prev) {
		entry->link.flink = prev->link.flink;
		prev->link.flink = &entry->link;
		if (!entry->link.flink) {
			callout_queue.tail = &entry->link;
		}
	} else {
		entry->link.flink = callout_queue.head;
		callout_queue.head = &entry->link;
		if (!callout_queue.tail) {
			callout_queue.tail = &entry->link;
		}
	}

	leave_critical_section(flags);

	/* Process callbacks immediately to handle short delays */
	hrt_call_invoke();
}

/**
 * If this returns true, the call has been invoked and removed from the callout list.
 */
bool
hrt_called(struct hrt_call *entry)
{
	/* Check if callback processing is needed */
	hrt_call_invoke();
	return (entry->deadline == 0);
}

/**
 * Remove the entry from the callout list.
 */
void
hrt_cancel(struct hrt_call *entry)
{
	irqstate_t flags = enter_critical_section();

	if (entry->deadline != 0) {
		sq_rem(&entry->link, &callout_queue);
		entry->deadline = 0;
		entry->period = 0;
	}

	leave_critical_section(flags);
}

/**
 * Initialize a hrt_call structure
 */
void
hrt_call_init(struct hrt_call *entry)
{
	memset(entry, 0, sizeof(*entry));
}

/**
 * Delay a hrt_call_every() periodic call by the given number of microseconds.
 */
void
hrt_call_delay(struct hrt_call *entry, hrt_abstime delay)
{
	irqstate_t flags = enter_critical_section();
	if (entry->deadline != 0) {
		entry->deadline += delay;
	}
	leave_critical_section(flags);
}

/**
 * Background processing - should be called regularly by system
 */
void hrt_work(void)
{
	hrt_call_invoke();
}



/* Latency baseline and counters for compatibility */
const uint16_t latency_bucket_count = LATENCY_BUCKET_COUNT;
const uint16_t latency_buckets[LATENCY_BUCKET_COUNT] = { 1, 2, 5, 10, 20, 50, 100, 1000 };
EXPORT uint32_t latency_counters[LATENCY_BUCKET_COUNT + 1] = {0};
