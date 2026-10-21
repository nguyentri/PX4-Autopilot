// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "output-snapshot.hpp"

namespace rzv2h
{
namespace demo
{

struct ProducerPeer {
	uint32_t epoch{0};
	uint32_t token{0};
	uint64_t received_us{0};
	bool compatible{false};
	bool ready{false};
};
struct ProducerInput {
	uint32_t configuration_id{0};
	uint16_t values[4] {};
	uint16_t state{StopMotors};
	uint16_t rate_hz{0};
	uint16_t active_mask{0};
	unsigned count{0};
	uint64_t now{0};
	uint64_t control_us{0};
	bool updated{false};
};

class OutputProducer
{
public:
	bool produce(const ProducerPeer &peer, const ProducerInput &input, OutputSnapshot &next)
	{
		if (!peer.compatible || !peer.epoch || !peer.token || input.count > 4 || input.now < peer.received_us
		    || input.now - peer.received_us >= ActuatorFreshnessUs
		    || (input.active_mask & ~uint16_t((1u << input.count) - 1u))
		    || input.rate_hz < 50 || input.rate_hz > 500 || (input.state & ~uint16_t(0x7f))) { return false; }

		if (peer.epoch != _epoch) {
			_epoch = peer.epoch;
			_generation = 0;
			_state_generation = 0;
			_last_state = UINT16_MAX;
			_last_control = 0;
		}

		if (_generation + 1 >= CounterLimit || _state_generation + 1 >= CounterLimit) { return false; }

		next = OutputSnapshot{};
		next.epoch = peer.epoch;
		next.configuration_id = input.configuration_id;
		next.command.token = peer.token;
		next.token_received_us = peer.received_us;
		next.control_us = input.control_us;
		next.control_updated = input.updated && input.control_us > _last_control;
		next.command.produced_us = input.now;
		next.command.rate_hz = input.rate_hz;
		next.command.state = input.state;

		const bool active = (input.state & Armed) && !(input.state & (StopMotors | Lockdown | ManualLockdown | Termination));

		if (active && (!next.control_updated || input.control_us <= peer.received_us || input.control_us > input.now)) {
			return false;
		}

		if (input.control_us <= input.now && input.control_us > _last_control) {
			_last_control = input.control_us;
		}

		next.command.generation = ++_generation;

		if (input.state != _last_state) {
			++_state_generation;
			_last_state = input.state;
		}

		next.command.state_generation = _state_generation;

		for (unsigned i = 0; i < input.count; ++i) {
			if (input.active_mask & (1u << i)) {
				next.command.outputs[i] = input.values[i];
			}
		}

		if (!(input.state & Armed) && (input.state & StopMotors) && !peer.ready) {
			for (auto &pulse : next.command.outputs) {
				pulse = 0;
			}
		}

		return next.eligible(peer.epoch, peer.token);
	}
	bool exhausted() const { return _generation + 1 >= CounterLimit || _state_generation + 1 >= CounterLimit; }
private:
	uint32_t _epoch{0};
	uint32_t _generation{0};
	uint32_t _state_generation{0};
	uint16_t _last_state{UINT16_MAX};
	uint64_t _last_control{0};
};

}
}
