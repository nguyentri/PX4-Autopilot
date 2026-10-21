// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "output-snapshot.hpp"
#include <string.h>

namespace rzv2h
{
namespace demo
{

enum class BenchFault : uint32_t { None, ProducerPause, HeartbeatDrop, CorruptFrame, ControlPause, BackendFail, StatusDrop };

// One CLI writer, concurrent bounded readers. A module restart is required
// before another injection; restart also requires the ordinary disarmed handshake.
class BenchFaultSchedule
{
public:
	bool schedule(BenchFault kind, uint64_t now, uint32_t delay_ms, uint32_t duration_ms)
	{
		const bool once = kind == BenchFault::CorruptFrame || kind == BenchFault::BackendFail;
		const uint32_t window_ms = once ? 5000 : duration_ms;

		if (kind == BenchFault::None || uint32_t(kind) > uint32_t(BenchFault::StatusDrop)
		    || delay_ms < 5000 || delay_ms > 60000 || !duration_ms || duration_ms > 5000
		    || (once && duration_ms != 1) || now > UINT64_MAX - uint64_t(delay_ms + window_ms) * 1000) { return false; }

		uint32_t expected = 0;

		if (!_invoked.compare_exchange(&expected, 1)) { return false; }

		const uint64_t begin = now + uint64_t(delay_ms) * 1000;
		const uint64_t end = begin + uint64_t(window_ms) * 1000;
		const uint32_t words[5] {uint32_t(kind), uint32_t(begin), uint32_t(begin >> 32), uint32_t(end), uint32_t(end >> 32)};
		return _record.publish(words);
	}

	bool active(BenchFault kind, uint64_t now)
	{
		uint32_t words[5] {};

		if (_completed.load() || !_record.read(words) || words[0] != uint32_t(kind)) { return false; }

		const uint64_t begin = uint64_t(words[1]) | uint64_t(words[2]) << 32;
		const uint64_t end = uint64_t(words[3]) | uint64_t(words[4]) << 32;

		if (now < begin) { return false; }

		if (now >= end) { _completed.store(1); return false; }

		_started.store(1);
		return true;
	}

	bool consume(BenchFault kind, uint64_t now)
	{
		// A counted one-shot waits at most five seconds for its owning operation,
		// rather than being lost between scheduler ticks or firing much later.
		uint32_t words[5] {};

		if (!_record.read(words) || words[0] != uint32_t(kind)
		    || now < (uint64_t(words[1]) | uint64_t(words[2]) << 32)) { return false; }

		if (_completed.load() || now >= (uint64_t(words[3]) | uint64_t(words[4]) << 32)) {
			_completed.store(1);
			return false;
		}

		uint32_t expected = 0;

		if (!_started.compare_exchange(&expected, 1)) { return false; }

		_completed.store(1);
		return true;
	}
	uint32_t invoked() const { return _invoked.load(); }
	uint32_t started() const { return _started.load(); }
	uint32_t completed() const { return _completed.load(); }
private:
	AtomicRecord<5> _record;
	px4::atomic<uint32_t> _invoked{0}, _started{0}, _completed{0};
};

inline bool fault_number(const char *text, uint32_t &value)
{
	if (!text || !*text) { return false; }

	value = 0;

	for (const char *p = text; *p; ++p) {
		if (*p < '0' || *p > '9' || value > 60000 / 10) { return false; }

		value = value * 10 + uint32_t(*p - '0');

		if (value > 60000) { return false; }
	}

	return true;
}

inline bool schedule_fault(BenchFaultSchedule &schedule, bool io, int argc, char *argv[], uint64_t now)
{
	if (argc != 6 || strcmp(argv[0], "fault") || strcmp(argv[2], "--delay-ms")) { return false; }

	BenchFault kind = BenchFault::None;

	if (!io && !strcmp(argv[1], "producer-pause")) { kind = BenchFault::ProducerPause; }

	if (!io && !strcmp(argv[1], "heartbeat-drop")) { kind = BenchFault::HeartbeatDrop; }

	if (!io && !strcmp(argv[1], "corrupt-next-frame")) { kind = BenchFault::CorruptFrame; }

	if (io && !strcmp(argv[1], "control-loop-pause")) { kind = BenchFault::ControlPause; }

	if (io && !strcmp(argv[1], "backend-fail")) { kind = BenchFault::BackendFail; }

	if (io && !strcmp(argv[1], "status-drop")) { kind = BenchFault::StatusDrop; }

	const bool once = kind == BenchFault::CorruptFrame || kind == BenchFault::BackendFail;
	uint32_t delay = 0, amount = 0;

	return !strcmp(argv[4], once ? "--count" : "--duration-ms") && fault_number(argv[3], delay)
	       && fault_number(argv[5], amount) && schedule.schedule(kind, now, delay, amount);
}

}
}
