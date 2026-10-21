// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "output-worker.hpp"

namespace rzv2h
{
namespace demo
{

// The controller owns lease/token state. A separate reporter merges this
// bounded snapshot with the worker's live receipt, even if control is paused.
class OutputStatusStore
{
public:
	bool publish(const Status &status, uint32_t epoch, uint64_t now)
	{
		Context context{};
		context.source = 1; context.sequence = 1; context.epoch = epoch; context.publication_us = now;
		const Frame frame = encode(status, context);
		uint32_t words[EntrySize / 4] {};

		for (unsigned i = 0; i < EntrySize / 4; ++i) { words[i] = read32(frame.bytes + i * 4); }

		return _record.publish(words);
	}
	bool read(Status &status, uint32_t &epoch, uint64_t &updated) const
	{
		uint32_t words[EntrySize / 4] {};

		if (!_record.read(words)) { return false; }

		Frame frame{};

		for (unsigned i = 0; i < EntrySize / 4; ++i) { write32(frame.bytes + i * 4, words[i]); }

		epoch = read32(frame.bytes + 16);
		updated = read64(frame.bytes + 20);
		status = demo::status(frame);
		return true;
	}
private:
	AtomicRecord < EntrySize / 4 > _record;
};

inline Status supervised_status(Status control, uint32_t epoch, uint64_t updated,
				const OutputWorkerReport &worker, uint64_t now)
{
	const bool worker_current = worker.current(epoch, now);
	const bool controller_current = updated && now >= updated && now - updated < ActuatorFreshnessUs;
	const uint8_t flags = worker_current ? uint8_t(worker.flags) : uint8_t(Inhibited);
	const bool ready = controller_current && worker_current && (control.backend & ArmReady)
			   && (flags & Initialized) && !(flags & FaultLatched) && !control.faults;
	control.backend = flags | (ready ? ArmReady : 0) | (control.backend & RotateSession);
	control.applied_sequence = worker_current ? worker.sequence : 0;
	control.applied_generation = worker_current ? worker.generation : 0;

	if (!controller_current) { control.faults |= ActuatorLease::CommandLost; }

	if (!worker_current || (flags & FaultLatched)) { control.faults |= ActuatorLease::BackendFailed; }

	return control;
}

}
}
