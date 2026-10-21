// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

// Host-only boundary setup; the firmware has no counter mutation interface.
#define private public
#include <apps/actuator-lease.hpp>
#undef private
#include <assert.h>
#include <stdio.h>

using namespace rzv2h::demo;

struct Fixture {
	// Synthetic contracts exist only in this fixture, never in a hardware registry.
	Hello contract;
	ActuatorLease lease;
	Context context;
	Command value;
	uint64_t now{1000000};
	uint32_t sequence{0};

	static Hello test_contract()
	{
		Hello result{};
		result.board = 1;
		result.resources = 2;
		result.profile = 3;
		result.output_config = 4;
		return result;
	}

	Fixture() : contract(test_contract()), lease(contract, 400)
	{
		context.epoch = 7;
		context.sequence = 1;
		lease.session(7);
		assert(lease.receive_hello(encode(contract, context), now));
		lease.backend(true, false);
		Frame heartbeat = begin(Type::Heartbeat, context);
		finish(heartbeat);
		assert(lease.receive_heartbeat(heartbeat, now));
		value.rate_hz = 400;
		value.token = lease.issue_token(now);
		value.state_generation = 1;
		assert(send());
		assert(lease.state() == ActuatorLease::State::Ready);
		lease.backend(true, true);
		assert(!lease.ready()); // Receipt alone is not a worker acknowledgement.
		Command premature = value;
		premature.state = Armed | SafetyOff;
		++premature.generation;
		++premature.state_generation;
		Context attempt = context;
		++attempt.sequence;
		assert(!lease.receive_command(encode(premature, attempt), now));
		lease.acknowledge(context.epoch, sequence, value.generation, false);
		lease.backend(true, true);
		assert(!lease.ready()); // The worker must have completed inhibition.
		lease.acknowledge(6, sequence, value.generation, true);
		lease.backend(true, true);
		assert(!lease.ready()); // An old worker epoch cannot grant READY.
		lease.acknowledge(context.epoch, sequence, value.generation, true);
		lease.backend(true, true);
		assert(lease.ready());
	}

	bool send()
	{
		context.sequence = ++sequence;
		++value.generation;
		// Source time is deliberately unrelated to receiver time.
		value.produced_us = UINT64_MAX - value.generation;
		return lease.receive_command(encode(value, context), now);
	}

	void arm()
	{
		value.state = Armed | SafetyOff;
		++value.state_generation;
		value.outputs[0] = 1200;
		assert(send());
		assert(lease.output(now).enabled);
	}
};

int main()
{
	Fixture monotonic_monitor;
	monotonic_monitor.lease.update(monotonic_monitor.now + 1);
	monotonic_monitor.lease.update(monotonic_monitor.now);
	assert(monotonic_monitor.lease.faults() & ActuatorLease::ClockFault);
	Hello missing{};
	ActuatorLease unavailable(missing, 0);
	unavailable.session(7);
	Context context{};
	context.epoch = 7;
	context.sequence = 1;
	assert(!unavailable.receive_hello(encode(missing, context), 0));
	unavailable.backend(true, true);
	assert(!unavailable.compatible() && !unavailable.ready() && !unavailable.issue_token(1));
	assert(!unavailable.output(1).enabled);

	Fixture original;
	original.arm();
	assert(original.lease.output(original.now).values[0] == 1200);
	const Frame replay = encode(original.value, original.context);
	assert(!original.lease.receive_command(replay, original.now));
	original.now += 49999;
	assert(original.lease.output(original.now).enabled);
	assert(original.send());
	assert(original.lease.output(original.now).deadline_us == 1050000);
	++original.now;
	assert(!original.lease.output(original.now).enabled);
	assert(!original.send());
	assert(original.lease.state() == ActuatorLease::State::Fault);
	const uint32_t first_fault = original.lease.first_fault();
	original.lease.fault(ActuatorLease::BackendFailed);
	assert(original.lease.first_fault() == first_fault);

	// New tokens/heartbeat cannot turn cached armed values into a recovery handshake.
	original.value.token = original.lease.issue_token(original.now);
	assert(!original.send());
	original.value.state = StopMotors;
	++original.value.state_generation;
	original.value.outputs[0] = 0;
	assert(original.send());
	assert(!original.lease.ready() && !original.lease.output(original.now).enabled);
	original.lease.acknowledge(original.context.epoch, original.sequence, original.value.generation, true);
	original.lease.backend(true, true);
	original.arm();

	// An unchanged epoch must not clear anti-replay state; a changed one invalidates everything.
	original.lease.session(7);
	assert(!original.lease.receive_command(encode(original.value, original.context), original.now));
	original.lease.session(8);
	assert(!original.lease.compatible() && !original.lease.ready());
	assert(!original.lease.output(original.now).enabled);
	assert(!original.lease.receive_command(replay, original.now));

	Fixture disarmed;
	disarmed.value.state = 0;
	++disarmed.value.state_generation;
	disarmed.value.outputs[0] = 1000; // A configured DIS pulse remains stored on the wire.
	assert(disarmed.send());
	const ActuatorLease::Output inhibited = disarmed.lease.output(disarmed.now);
	assert(!inhibited.enabled && inhibited.values[0] == 0);
	assert(command(encode(disarmed.value, disarmed.context)).outputs[0] == 1000);

	Fixture disarm_transition;
	disarm_transition.arm();
	disarm_transition.value.state = StopMotors;
	++disarm_transition.value.state_generation;
	disarm_transition.value.outputs[0] = 1000;
	assert(disarm_transition.send());
	assert(!disarm_transition.lease.ready());
	disarm_transition.lease.acknowledge(disarm_transition.context.epoch, disarm_transition.sequence,
					    disarm_transition.value.generation, true);
	disarm_transition.lease.backend(true, true);
	assert(disarm_transition.lease.ready() && !disarm_transition.lease.output(disarm_transition.now).enabled);
	disarm_transition.arm();

	Fixture queued_kill;
	queued_kill.arm();
	queued_kill.value.state |= ManualLockdown;
	++queued_kill.value.state_generation;
	assert(queued_kill.send());
	assert(!queued_kill.lease.ready());
	queued_kill.value.state = Armed | SafetyOff;
	++queued_kill.value.state_generation;
	assert(!queued_kill.send()); // A later queued arm cannot erase the inhibit transaction.

	Fixture state_change;
	state_change.arm();
	state_change.value.state |= Lockdown;
	assert(!state_change.send()); // Changed state without its coherent generation is invalid.
	++state_change.value.state_generation;
	assert(state_change.send());
	assert(!state_change.lease.output(state_change.now).enabled);

	Fixture termination;
	termination.arm();
	termination.value.state |= ForceFailsafe | Termination;
	++termination.value.state_generation;
	assert(termination.send());
	assert(!termination.lease.output(termination.now).enabled && !termination.lease.ready());

	Fixture tokens;
	assert(tokens.lease.issue_token(tokens.now + 1) == 1);
	tokens.now += 20000;
	assert(tokens.lease.issue_token(tokens.now) == 2);
	tokens.now += 20000;
	assert(tokens.lease.issue_token(tokens.now) == 3);
	tokens.now += 10000;
	assert(tokens.lease.issue_token(tokens.now) == 3);
	tokens.value.token = 1;
	assert(!tokens.send()); // Exactly token issue+50 ms is expired, even with a fresh receive.

	Fixture backend;
	backend.arm();
	backend.lease.backend(false, false);
	assert(backend.lease.state() == ActuatorLease::State::Fault && !backend.lease.output(backend.now).enabled);
	backend.lease.backend(true, false);
	assert(!backend.send());
	backend.value.state = StopMotors;
	++backend.value.state_generation;
	backend.value.outputs[0] = 0;
	assert(backend.send());
	assert(!backend.lease.ready());

	Fixture clock;
	clock.arm();
	assert(!clock.lease.issue_token(clock.now - 1));
	assert(clock.lease.faults() & ActuatorLease::ClockFault);
	assert(!clock.lease.output(clock.now).enabled);

	Fixture wrap;
	wrap.arm();
	wrap.lease._token = CounterLimit - 1;
	wrap.now += 20000;
	assert(!wrap.lease.issue_token(wrap.now));
	assert(wrap.lease.rotation_requested() && !wrap.lease.output(wrap.now).enabled);
	assert(wrap.lease.faults() & ActuatorLease::CounterExhausted);

	Fixture heartbeat;
	heartbeat.arm();

	for (unsigned i = 1; i < 25; ++i) {
		heartbeat.now += 20000;
		heartbeat.value.token = heartbeat.lease.issue_token(heartbeat.now);
		assert(heartbeat.send());
	}

	heartbeat.now = 1500000;
	assert(!heartbeat.lease.output(heartbeat.now).enabled);
	heartbeat.context.sequence = 2;
	Frame late = begin(Type::Heartbeat, heartbeat.context);
	finish(late);
	assert(heartbeat.lease.receive_heartbeat(late, heartbeat.now));
	assert(heartbeat.lease.state() == ActuatorLease::State::Fault);
	assert(!heartbeat.send());

	puts("causal token, replay, inhibit, recovery, clock and wrap lease checks passed");
	return 0;
}
