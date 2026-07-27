/****************************************************************************
 *
 *   Copyright (c) 2020 PX4 Development Team. All rights reserved.
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

#include <px4_platform_common/module.h>
#include <px4_platform_common/atomic.h>
#include <px4_platform_common/time.h>
#include <drivers/drv_hrt.h>

#include <stdlib.h>

using namespace time_literals;

static void	usage();

namespace
{

struct HrtTestState {
	px4::atomic<bool> running{false};
	px4::atomic<bool> poisoned{false};
	px4::atomic<uint32_t> callback_count{0};
	hrt_abstime callback_time{0};
	struct hrt_call call {};
};

HrtTestState hrt_test_state;

void hrt_test_callback(void *arg)
{
	auto *state = static_cast<HrtTestState *>(arg);
	state->callback_time = hrt_absolute_time();
	state->callback_count.fetch_add(1);
}

int hrt_test()
{
	constexpr hrt_abstime sleep_delay = 10_ms;
	constexpr hrt_abstime callback_delay = 20_ms;
	constexpr hrt_abstime maximum_delay = 100_ms;
	constexpr unsigned timeout_polls = 200;

	bool expected_running = false;

	if (!hrt_test_state.running.compare_exchange(&expected_running, true)) {
		PX4_ERR("HRT test already running");
		return PX4_ERROR;
	}

	if (hrt_test_state.poisoned.load()) {
		hrt_test_state.running.store(false);
		PX4_ERR("HRT test unavailable after a callback timeout; reboot before retrying");
		return PX4_ERROR;
	}

	hrt_abstime previous = hrt_absolute_time();

	for (unsigned i = 0; i < 1024; ++i) {
		const hrt_abstime now = hrt_absolute_time();

		if (now < previous) {
			PX4_ERR("HRT moved backwards: %" PRIu64 " -> %" PRIu64, previous, now);
			hrt_test_state.running.store(false);
			return PX4_ERROR;
		}

		previous = now;
	}

	const hrt_abstime sleep_start = hrt_absolute_time();
	px4_usleep(sleep_delay);
	const hrt_abstime sleep_elapsed = hrt_absolute_time() - sleep_start;

	hrt_test_state.callback_count.store(0);
	hrt_test_state.callback_time = 0;
	hrt_call_init(&hrt_test_state.call);
	hrt_call_after(&hrt_test_state.call, callback_delay, hrt_test_callback, &hrt_test_state);
	const hrt_abstime callback_deadline = hrt_test_state.call.deadline;

	for (unsigned i = 0; i < timeout_polls && hrt_test_state.callback_count.load() == 0; ++i) {
		px4_usleep(1_ms);
	}

	hrt_cancel(&hrt_test_state.call);
	const uint32_t callback_count = hrt_test_state.callback_count.load();

	if (callback_count != 1) {
		// A protected NuttX build can already have queued the user callback
		// when hrt_cancel() runs. Keep the static storage alive and prohibit
		// reuse until reboot so that a late dispatch cannot target a new test.
		hrt_test_state.poisoned.store(true);
		hrt_test_state.running.store(false);
		PX4_ERR("HRT callback missing or early: count=%" PRIu32, callback_count);
		return PX4_ERROR;
	}

	if (sleep_elapsed < sleep_delay || sleep_elapsed > maximum_delay) {
		PX4_ERR("HRT sleep out of bounds: %" PRIu64 " us", sleep_elapsed);
		hrt_test_state.running.store(false);
		return PX4_ERROR;
	}

	if (hrt_test_state.callback_time < callback_deadline) {
		hrt_test_state.running.store(false);
		PX4_ERR("HRT callback ran early");
		return PX4_ERROR;
	}

	const hrt_abstime callback_latency = hrt_test_state.callback_time - callback_deadline;

	if (callback_latency > maximum_delay) {
		PX4_ERR("HRT callback late: %" PRIu64 " us", callback_latency);
		hrt_test_state.running.store(false);
		return PX4_ERROR;
	}

	PX4_INFO("HRT test PASS: sleep=%" PRIu64 " us, callback latency=%" PRIu64 " us",
		 sleep_elapsed, callback_latency);
	hrt_test_state.running.store(false);
	return PX4_OK;
}

} // namespace

extern "C" {
	__EXPORT int system_time_main(int argc, char *argv[]);
}

int
system_time_main(int argc, char *argv[])
{
	if (argc >= 2) {
		if (!strcmp(argv[1], "hrt-test")) {
			return hrt_test();
		}

		if (!strcmp(argv[1], "get")) {
			//get system time
			struct timespec ts = {};
			px4_clock_gettime(CLOCK_REALTIME, &ts);
			time_t utc_time_sec = ts.tv_sec + (ts.tv_nsec / 1e9);

			//convert to date time
			char buf[80];
			struct tm date_time;
			localtime_r(&utc_time_sec, &date_time);
			strftime(buf, sizeof(buf), "%a %Y-%m-%d %H:%M:%S %Z", &date_time);

			//get time since boot
			hrt_abstime since_boot_sec = hrt_absolute_time() / 1_s;

			PX4_INFO("Unix epoch time: %ld", (long)utc_time_sec);
			PX4_INFO("System time: %s", buf);
			PX4_INFO("Uptime (since boot): %" PRIu64 " s", since_boot_sec);
			return 0;
		}

		if (!strcmp(argv[1], "set")) {
			if (argc == 3) {
				//set system time
				struct timespec ts = {};
				ts.tv_sec = (time_t)strtoul(argv[2], nullptr, 0);
				ts.tv_nsec = 0.0;

				int res = px4_clock_settime(CLOCK_REALTIME, &ts);

				if (res == 0) {
					PX4_INFO("Successfully set system time");
					return 0;

				} else {
					PX4_ERR("Failed to set system time (%i)", res);
					return 1;
				}

			} else {
				usage();
				return 1;
			}
		}

		//unknown command
		PX4_ERR("system_time: Unknown subcommand");
		usage();
		return 1;
	}

	//not enough arguments
	PX4_ERR("system_time: not enough arguments");
	usage();
	return 1;
}

static void
usage()
{

	PRINT_MODULE_DESCRIPTION(
		R"DESCR_STR(
### Description

Command-line tool to set and get system time.

### Examples

Set the system time and read it back
$ system_time set 1600775044
$ system_time get
)DESCR_STR");

	PRINT_MODULE_USAGE_NAME("system_time", "command");
	PRINT_MODULE_USAGE_COMMAND_DESCR("set", "Set the system time, provide time in unix epoch time format");
	PRINT_MODULE_USAGE_COMMAND_DESCR("get", "Get the system time");
	PRINT_MODULE_USAGE_COMMAND_DESCR("hrt-test", "Run a bounded HRT monotonicity and callback test");

}
