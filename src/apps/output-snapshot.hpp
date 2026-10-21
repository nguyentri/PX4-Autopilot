// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

#pragma once

#include "protocol.hpp"
#include <px4_platform_common/atomic.h>

namespace rzv2h
{
namespace demo
{

// One writer, bounded readers. Atomic payload words avoid a C++ data race during
// a failed seqlock read. A failed read grants no new output authority.
template<size_t Words>
class AtomicRecord
{
public:
	AtomicRecord()
	{
		for (auto &word : _words) { word.store(0); }
	}

	bool publish(const uint32_t (&words)[Words])
	{
		const uint32_t sequence = _sequence.load();

		if ((sequence & 1) || sequence >= CounterLimit - 2) { return false; }

		_sequence.store(sequence + 1);

		for (size_t i = 0; i < Words; ++i) { _words[i].store(words[i]); }

		_sequence.store(sequence + 2);
		return true;
	}

	bool read(uint32_t (&words)[Words]) const
	{
		for (unsigned attempt = 0; attempt < 3; ++attempt) {
			const uint32_t before = _sequence.load();

			if (!before || (before & 1)) { continue; }

			for (size_t i = 0; i < Words; ++i) { words[i] = _words[i].load(); }

			if (_sequence.load() == before) { return true; }
		}

		return false;
	}

private:
	px4::atomic<uint32_t> _sequence{0};
	px4::atomic<uint32_t> _words[Words];
};

struct OutputSnapshot {
	Command command{};
	uint32_t epoch{0};
	uint32_t configuration_id{0};
	uint64_t control_us{0};
	uint64_t token_received_us{0};
	bool control_updated{false};

	bool eligible(uint32_t current_epoch, uint32_t current_token) const
	{
		if (!epoch || epoch != current_epoch || !current_token || command.token != current_token
		    || !command.generation || command.produced_us < token_received_us
		    || command.produced_us - token_received_us >= ActuatorFreshnessUs) { return false; }

		const bool active = (command.state & Armed)
				    && !(command.state & (StopMotors | Lockdown | ManualLockdown | Termination));
		return !active || (control_updated && control_us > token_received_us && control_us <= command.produced_us);
	}
};

class SnapshotStore
{
public:
	bool publish(const OutputSnapshot &snapshot)
	{
		const Command &command = snapshot.command;
		const uint32_t words[15] {
			snapshot.epoch, command.generation, command.state_generation,
			uint32_t(command.produced_us), uint32_t(command.produced_us >> 32),
			uint32_t(snapshot.control_us), uint32_t(snapshot.control_us >> 32),
			uint32_t(snapshot.token_received_us), uint32_t(snapshot.token_received_us >> 32),
			uint32_t(command.outputs[0]) | uint32_t(command.outputs[1]) << 16,
					uint32_t(command.outputs[2]) | uint32_t(command.outputs[3]) << 16,
					uint32_t(command.state) | uint32_t(command.rate_hz) << 16,
					command.token, snapshot.control_updated ? 1u : 0u, snapshot.configuration_id
		};
		return _record.publish(words);
	}

	bool read(OutputSnapshot &snapshot) const
	{
		uint32_t words[15] {};

		if (!_record.read(words)) { return false; }

		snapshot.epoch = words[0];
		snapshot.command.generation = words[1];
		snapshot.command.state_generation = words[2];
		snapshot.command.produced_us = uint64_t(words[3]) | uint64_t(words[4]) << 32;
		snapshot.control_us = uint64_t(words[5]) | uint64_t(words[6]) << 32;
		snapshot.token_received_us = uint64_t(words[7]) | uint64_t(words[8]) << 32;

		for (unsigned i = 0; i < 4; ++i) { snapshot.command.outputs[i] = uint16_t(words[9 + i / 2] >> (16 * (i % 2))); }

		snapshot.command.state = uint16_t(words[11]);
		snapshot.command.rate_hz = uint16_t(words[11] >> 16);
		snapshot.command.token = words[12];
		snapshot.control_updated = words[13] != 0;
		snapshot.configuration_id = words[14];
		return true;
	}

private:
	AtomicRecord<15> _record;
};

} // namespace demo
} // namespace rzv2h
