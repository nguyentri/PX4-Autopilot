// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "actuator-lease.hpp"
#include "output-snapshot.hpp"

namespace rzv2h
{
namespace demo
{

struct OutputPlan {
	ActuatorLease::Output output{};
	uint64_t updated_us{0};
	bool compatible{false};
	bool recovery{false};
};

struct OutputWorkerReport {
	uint32_t flags{Inhibited}, sequence{0}, generation{0}, loops{0}, epoch{0};
	uint64_t time_us{0};
	bool current(uint32_t expected_epoch, uint64_t now) const
	{
		return expected_epoch && epoch == expected_epoch && time_us && now >= time_us && now - time_us < 10000;
	}
};

class OutputWorkerReportStore
{
public:
	bool publish(const OutputWorkerReport &report)
	{
		const uint32_t words[7] {report.flags, report.sequence, report.generation, report.loops,
					 uint32_t(report.time_us), uint32_t(report.time_us >> 32), report.epoch
					};
		return _record.publish(words);
	}
	bool read(OutputWorkerReport &report) const
	{
		uint32_t words[7] {};

		if (!_record.read(words)) { return false; }

		report.flags = words[0]; report.sequence = words[1]; report.generation = words[2]; report.loops = words[3];
		report.time_us = uint64_t(words[4]) | uint64_t(words[5]) << 32; report.epoch = words[6];
		return true;
	}
private:
	AtomicRecord<7> _record;
};

class OutputPlanStore
{
public:
	bool publish(const OutputPlan &plan)
	{
		const auto &o = plan.output;
		const uint32_t words[11] {o.epoch, o.sequence, o.generation, uint32_t(o.deadline_us), uint32_t(o.deadline_us >> 32),
					  uint32_t(plan.updated_us), uint32_t(plan.updated_us >> 32),
					  uint32_t(o.values[0]) | uint32_t(o.values[1]) << 16, uint32_t(o.values[2]) | uint32_t(o.values[3]) << 16,
					  o.enabled ? 1u : 0u, (plan.compatible ? 1u : 0u) | (plan.recovery ? 2u : 0u)
					 };
		return _record.publish(words);
	}
	bool read(OutputPlan &plan) const
	{
		uint32_t words[11] {};

		if (!_record.read(words)) { return false; }

		auto &o = plan.output;
		o.epoch = words[0]; o.sequence = words[1]; o.generation = words[2];
		o.deadline_us = uint64_t(words[3]) | uint64_t(words[4]) << 32;
		plan.updated_us = uint64_t(words[5]) | uint64_t(words[6]) << 32;

		for (unsigned i = 0; i < 4; ++i) { o.values[i] = uint16_t(words[7 + i / 2] >> (16 * (i % 2))); }

		o.enabled = words[9] != 0; plan.compatible = words[10] & 1; plan.recovery = words[10] & 2;
		return true;
	}
private:
	AtomicRecord<11> _record;
};

// Sole physical-output owner. The transport/controller cannot clear this
// worker's fault by resuming an old armed snapshot. Hardware errors require
// reinitialization; ordinary expiry requires a newer disarmed handshake.
template<class Hardware>
class OutputWorker
{
public:
	OutputWorker(Hardware &hardware, bool configured) : _hardware(hardware), _configured(configured) {}
	void step(const OutputPlan &plan, uint64_t now)
	{
		if (_have_time && now < _last_time) { _hardware_fault = true; latch(plan.output.generation); }

		_have_time = true;
		_last_time = now;
		const bool current = plan.compatible && plan.output.epoch && now >= plan.updated_us
				     && now - plan.updated_us < ActuatorLease::LeaseUs;

		if (!current || !_configured) {
			const bool was_enabled = _enabled;

			if (_claimed) { inhibit(); }

			if (was_enabled) { latch(plan.output.generation); }

			return;
		}

		if (_epoch != plan.output.epoch) {
			const bool was_enabled = _enabled;

			if (_claimed) { inhibit(); }

			// Producer generations restart per epoch. Keep inhibition latched,
			// but compare recovery progress only within the new session.
			_epoch = plan.output.epoch;
			_fault_generation = 0;

			if (was_enabled) { latch(plan.output.generation); }
		}

		if (_hardware_fault && !_claimed) { return; }

		if (!_claimed) {
			_claimed = true; // Ownership precedes even partial initialization.

			if (!_hardware.initialize()) { _hardware_fault = true; latch(plan.output.generation); inhibit(); return; }

			if (!_hardware.inhibit()) { _hardware_fault = true; latch(plan.output.generation); return; }

			_initialized = true;
		}

		if (_hardware_fault || !_initialized) { inhibit(); return; }

		if (_fault && plan.recovery && !plan.output.enabled && plan.output.generation > _fault_generation) {
			_fault = false;
		}

		if (_fault || !plan.output.enabled || !plan.output.deadline_us || now >= plan.output.deadline_us) {
			const bool was_enabled = _enabled;
			inhibit();

			if (was_enabled && !plan.recovery) { latch(plan.output.generation); }

			if (!_hardware_fault) {
				_applied_sequence = plan.output.sequence;
				_applied_generation = plan.output.generation;
			}

			return;
		}

		if (!_hardware.apply(plan.output.values)) { _hardware_fault = true; latch(plan.output.generation); inhibit(); return; }

		_enabled = true;
		_applied_sequence = plan.output.sequence;
		_applied_generation = plan.output.generation;
	}
	void stop() { if (_claimed) { inhibit(); } }
	void fail(uint32_t generation)
	{
		_hardware_fault = true;
		latch(generation);

		if (_claimed) { inhibit(); }
	}
	bool initialized() const { return _initialized && !_hardware_fault; }
	bool faulted() const { return _fault; }
	uint32_t applied_sequence() const { return _applied_sequence; }
	uint32_t applied_generation() const { return _applied_generation; }
	uint32_t epoch() const { return _epoch; }
	OutputWorkerReport report(uint64_t now, uint32_t loops) const
	{
		OutputWorkerReport result{};
		result.flags = flags(); result.sequence = _applied_sequence; result.generation = _applied_generation;
		result.loops = loops; result.time_us = now; result.epoch = _epoch;
		return result;
	}
	uint8_t flags() const
	{
		return (_claimed ? Claimed : 0) | (initialized() ? Initialized : 0) | (!_enabled ? Inhibited : 0)
		       | (_fault ? FaultLatched : 0) | (initialized() && !_enabled && !_hardware_fault ? RecoveryEligible : 0);
	}
private:
	void latch(uint32_t generation) { _fault = true; _fault_generation = generation; }
	void inhibit()
	{
		if (!_hardware.inhibit()) { _hardware_fault = true; _fault = true; }

		_enabled = false;
	}
	Hardware &_hardware;
	const bool _configured;
	uint64_t _last_time{0};
	uint32_t _epoch{0}, _fault_generation{0}, _applied_sequence{0}, _applied_generation{0};
	bool _have_time{false}, _claimed{false}, _initialized{false}, _enabled{false}, _fault{false}, _hardware_fault{false};
};

}
}
