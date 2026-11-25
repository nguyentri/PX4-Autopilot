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
 * @file init.c
 *
 * Sparrow Hawk CR52-0 PX4 start-up: report the arch boot state, start the
 * PX4 platform and mount the volatile parameter file system.
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/init.h>

#include <nuttx/board.h>
#include <nuttx/fs/fs.h>

#include <errno.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <syslog.h>

#include "rcar_irq.h"
#include "rcar_start.h"

#include "board_config.h"

#define PARAMFS_MOUNTPOINT "/fs"

/* Print what the arch start-up could not print itself.  With no debug probe
 * on this board, the console log is the only boot diagnostic.
 */
static void sparrow_hawk_report_boot(void)
{
	const struct rcar_irq_status_s *irq = rcar_irq_status();

	syslog(LOG_INFO, "rcar: CR52-%d mpu=%d dcache=%d console=%d\n",
	       CONFIG_RCAR_CORE_ID, g_rcar_boot_status.mpu_result,
	       g_rcar_boot_status.dcache_enabled, g_rcar_boot_status.console_result);
	syslog(LOG_INFO, "rcar: ICC_SRE=0x%08lx GICR=%d\n",
	       (unsigned long)irq->icc_sre, irq->gicr_index);

	if (irq->gicr_index < 0) {
		syslog(LOG_ERR, "rcar: no redistributor matches MPIDR.Aff0\n");
	}

	if (irq->gicr_wake_timeout) {
		syslog(LOG_ERR, "rcar: GICR_WAKER.ChildrenAsleep stuck at 1\n");
	}
}

/* Mount TMPFS on /fs for parameters.  An existing TMPFS mount is accepted;
 * anything else is an error.  The contents are lost at every reset.
 */
static int sparrow_hawk_paramfs_initialize(void)
{
	struct statfs state;
	int ret = mkdir(PARAMFS_MOUNTPOINT, 0777);

	if (ret < 0 && errno != EEXIST) {
		return -errno;
	}

	ret = nx_mount(NULL, PARAMFS_MOUNTPOINT, "tmpfs", 0, NULL);

	if (ret < 0 && ret != -EBUSY && ret != -ENOTDIR) {
		return ret;
	}

	if (statfs(PARAMFS_MOUNTPOINT, &state) < 0) {
		return -errno;
	}

	return (state.f_type == TMPFS_MAGIC) ? OK : -EBUSY;
}

/* Early arch hook, called from arm_boot() before the OS starts.  PX4 does
 * not link the NuttX board library, so the hook lives here.  The HSCIF pin
 * functions are set by the arch serial code, so nothing is left to do.
 */
__EXPORT void rcar_boardinitialize(void)
{
}

__EXPORT int board_app_initialize(uintptr_t arg)
{
	(void)arg;

	sparrow_hawk_report_boot();

	int ret = px4_platform_init();

	if (ret != OK) {
		syslog(LOG_ERR, "board_app_initialize: px4_platform_init() failed: %d\n", ret);
		return ret;
	}

	ret = sparrow_hawk_paramfs_initialize();

	if (ret != OK) {
		/* Parameters then fall back to defaults and cannot be saved */
		syslog(LOG_ERR, "board_app_initialize: TMPFS on %s failed: %d\n", PARAMFS_MOUNTPOINT, ret);
	}

	return OK;
}
