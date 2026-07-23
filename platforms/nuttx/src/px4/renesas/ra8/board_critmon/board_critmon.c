/************************************************************************************
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
 ************************************************************************************/

/************************************************************************************
 * Included Files
 ************************************************************************************/

#include <nuttx/config.h>

#include <time.h>
#include <fixedmath.h>

#include "arm_internal.h"

#include <nuttx/clock.h>

#include <arch/board/board.h>

#if defined(CONFIG_SCHED_CRITMONITOR) || defined(CONFIG_SCHED_IRQMONITOR)

/************************************************************************************
 * Pre-processor Definitions
 ************************************************************************************/

/* DWT (Debug Watch and Trace) registers for Cortex-M85 */
#ifndef DWT_CYCCNT
#define DWT_CYCCNT      0xE0001004  /* DWT Cycle Count Register */
#endif

#ifndef DWT_CTRL
#define DWT_CTRL        0xE0001000  /* DWT Control Register */
#endif

#ifndef DWT_CTRL_CYCCNTENA
#define DWT_CTRL_CYCCNTENA  (1 << 0)  /* Enable cycle counter */
#endif

/************************************************************************************
 * Public Functions
 ************************************************************************************/

/************************************************************************************
 * Name: up_critmon_gettime
 *
 * Description:
 *   Get the current time from the CPU cycle counter for critical section monitoring.
 *   For RA8 (Cortex-M85), we use the DWT cycle counter.
 *
 ************************************************************************************/

uint32_t up_critmon_gettime(void)
{
	/* Ensure DWT cycle counter is enabled */
	static bool dwt_enabled = false;
	if (!dwt_enabled) {
		/* Enable DWT cycle counter if not already enabled */
		uint32_t dwt_ctrl = getreg32(DWT_CTRL);
		if (!(dwt_ctrl & DWT_CTRL_CYCCNTENA)) {
			putreg32(dwt_ctrl | DWT_CTRL_CYCCNTENA, DWT_CTRL);
		}
		dwt_enabled = true;
	}

	return getreg32(DWT_CYCCNT);
}

/************************************************************************************
 * Name: up_critmon_convert
 *
 * Description:
 *   Convert elapsed CPU cycles to time specification.
 *   For RA8, convert cycles to time using the system clock frequency.
 *
 ************************************************************************************/

void up_critmon_convert(uint32_t elapsed, FAR struct timespec *ts)
{
	b32_t b32elapsed;

	/* Convert cycles to seconds using RA8 system clock frequency */
	b32elapsed  = itob32(elapsed) / CONFIG_RA_MCU_CLOCK_FREQUENCY;
	ts->tv_sec  = b32toi(b32elapsed);
	ts->tv_nsec = NSEC_PER_SEC * b32frac(b32elapsed) / b32ONE;
}

#endif /* CONFIG_SCHED_CRITMONITOR || CONFIG_SCHED_IRQMONITOR */
