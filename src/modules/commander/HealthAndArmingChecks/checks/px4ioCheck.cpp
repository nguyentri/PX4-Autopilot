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


#include "px4ioCheck.hpp"

using namespace time_literals;

void Px4ioChecks::checkAndReport(const Context &context, Report &reporter)
{
	/* A publisher that exits unadvertises the topic and copy() then fails:
	 * keep checking the last sample, whose timestamp goes stale.
	 */
	if (_px4io_status_sub.copy(&_status)) {
		_status_seen = true;

	} else if (!_status_seen) {
#ifndef CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS
		return;
#endif
	}

	const px4io_status_s &status = _status;

	/* The remote producer can block on a raw write. Commander must age its
	 * last status independently instead of retaining READY during that wait.
	 */
#ifdef CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS
	static constexpr hrt_abstime status_timeout = 50_ms;
#else
	/* Legacy publishers send px4io_status at least once per second. */
	static constexpr hrt_abstime status_timeout = 2_s;
#endif

	if (!_status_seen || hrt_elapsed_time(&status.timestamp) > status_timeout) {
		/* EVENT
		 * @description
		 * The output I/O processor stopped reporting its status.
		 */
		reporter.healthFailure(NavModes::All, health_component_t::motors_escs, events::ID("check_px4io_lost"),
				       events::Log::Critical, "I/O processor not responding");

		if (reporter.mavlink_log_pub()) {
			mavlink_log_critical(reporter.mavlink_log_pub(), "Preflight Fail: I/O processor not responding");
		}

	} else if (status.status_failsafe) {
		/* EVENT
		 * @description
		 * The output I/O processor holds its outputs in failsafe. It needs a fresh disarmed
		 * command from the FMU before outputs can be armed again.
		 */
		reporter.healthFailure(NavModes::All, health_component_t::motors_escs, events::ID("check_px4io_failsafe"),
				       events::Log::Critical, "I/O processor in failsafe");

		if (reporter.mavlink_log_pub()) {
			mavlink_log_critical(reporter.mavlink_log_pub(), "Preflight Fail: I/O processor in failsafe");
		}

	} else if (!status.status_fmu_ok
#ifdef CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS
		   || !status.arming_io_arm_ok || status.alarm_pwm_error
#endif
		  ) {
		/* EVENT
		 * @description
		 * The output I/O processor does not receive fresh FMU outputs, so it keeps its outputs off.
		 */
		reporter.healthFailure(NavModes::All, health_component_t::motors_escs, events::ID("check_px4io_fmu_lost"),
				       events::Log::Critical, "I/O processor not receiving FMU outputs");

		if (reporter.mavlink_log_pub()) {
			mavlink_log_critical(reporter.mavlink_log_pub(), "Preflight Fail: I/O processor not receiving FMU outputs");
		}
	}
}
