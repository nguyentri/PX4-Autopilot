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
 * Forwards the bench ADS1115 channel voltages to the GCS.
 *
 * The NAMED_VALUE_FLOAT stream sends at most one debug_key_value sample per
 * stream interval and the topic holds a single sample, so the channels are
 * published one at a time in turn. Publishing every 125 ms while the stream
 * runs at 10 Hz delivers every sample: each channel reaches QGC at 2 Hz as
 * ADS_A0..ADS_A3, in volts, and can be plotted in the MAVLink Inspector.
 * Nothing is published while the ADC data is missing or stale.
 */

#include <drivers/drv_hrt.h>
#include <px4_platform_common/module.h>
#include <px4_platform_common/px4_work_queue/ScheduledWorkItem.hpp>
#include <uORB/Publication.hpp>
#include <uORB/Subscription.hpp>
#include <uORB/topics/adc_report.h>
#include <uORB/topics/debug_key_value.h>

#include <stdio.h>
#include <string.h>

using namespace time_literals;

class AdcTelemetry final : public ModuleBase<AdcTelemetry>, public px4::ScheduledWorkItem
{
public:
	AdcTelemetry() : ScheduledWorkItem(MODULE_NAME, px4::wq_configurations::lp_default) {}

	static int task_spawn(int, char *[])
	{
		AdcTelemetry *instance = new AdcTelemetry();

		if (instance == nullptr) {
			return -ENOMEM;
		}

		_object.store(instance);
		_task_id = task_id_is_work_queue;
		instance->ScheduleOnInterval(PUBLISH_INTERVAL);
		return 0;
	}

	static int custom_command(int, char *[]) { return print_usage("unknown command"); }

	static int print_usage(const char *reason = nullptr)
	{
		if (reason) { PX4_WARN("%s", reason); }

		PRINT_MODULE_DESCRIPTION("Forwards ADS1115 channel voltages as debug_key_value ADS_A0..ADS_A3 "
					 "for the MAVLink NAMED_VALUE_FLOAT stream.");
		PRINT_MODULE_USAGE_NAME("rzv2h_adc_telemetry", "driver");
		PRINT_MODULE_USAGE_COMMAND("start");
		PRINT_MODULE_USAGE_DEFAULT_COMMANDS();
		return 0;
	}

	int print_status() override
	{
		PX4_INFO("published %lu, skipped stale %lu", (unsigned long)_published, (unsigned long)_stale);
		return 0;
	}

private:
	static constexpr hrt_abstime PUBLISH_INTERVAL{125_ms};
	// A complete ADS1115 four-channel set arrives several times per second.
	static constexpr hrt_abstime STALE_TIMEOUT{1_s};
	static constexpr unsigned CHANNELS{4};

	void Run() override
	{
		if (should_exit()) {
			ScheduleClear();
			exit_and_cleanup();
			return;
		}

		_adc_report_sub.update(&_adc_report);
		const unsigned channel = _next_channel;
		_next_channel = (_next_channel + 1) % CHANNELS;

		if (_adc_report.timestamp == 0 || hrt_elapsed_time(&_adc_report.timestamp) > STALE_TIMEOUT
		    || _adc_report.channel_id[channel] < 0 || _adc_report.resolution == 0) {
			_stale++;
			return;
		}

		debug_key_value_s sample{};
		snprintf(sample.key, sizeof(sample.key), "ADS_A%u", channel);
		sample.value = _adc_report.raw_data[channel] * _adc_report.v_ref / _adc_report.resolution;
		sample.timestamp = hrt_absolute_time();
		_debug_key_value_pub.publish(sample);
		_published++;
	}

	uORB::Subscription _adc_report_sub{ORB_ID(adc_report)};
	uORB::Publication<debug_key_value_s> _debug_key_value_pub{ORB_ID(debug_key_value)};
	adc_report_s _adc_report{};
	unsigned _next_channel{0};
	uint32_t _published{0};
	uint32_t _stale{0};
};

extern "C" __EXPORT int rzv2h_adc_telemetry_main(int argc, char *argv[])
{
	return AdcTelemetry::main(argc, argv);
}
