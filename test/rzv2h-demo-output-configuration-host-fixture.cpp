// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#include <apps/actuator-lease.hpp>
#include <apps/hardware-contract.hpp>
#include <cassert>

using namespace rzv2h::demo;

static OutputProfile synthetic(uint32_t identity, unsigned motors)
{
	OutputProfile profile{};
	profile.identity = identity;
	profile.configuration.airframe_id = motors == 4 ? 4014 : 22001;
	profile.configuration.rate_hz = 400;

	for (unsigned i = 0; i < 4; ++i) {
		auto &channel = profile.configuration.channels[i];
		channel.function = i < motors ? 101 + i : 0;
		channel.minimum = 1100; channel.maximum = 1900;
		channel.disarmed = channel.failsafe = 1000;
	}

	return profile;
}

int main()
{
	// Synthetic identities exercise contracts; none is installed in firmware.
	OutputProfile profiles[2] {synthetic(7, 4), synthetic(8, 2)};
	assert(profiles[0].configuration.valid() && profiles[1].configuration.valid());
	assert(identify_output_configuration(profiles, 2, profiles[0].configuration) == 7);
	assert(identify_output_configuration(profiles, 2, profiles[1].configuration) == 8);

	for (unsigned field = 0; field < 9; ++field) {
		OutputConfiguration changed = profiles[0].configuration;

		switch (field) {
		case 0: ++changed.channels[0].function; break;

		case 1: ++changed.channels[0].minimum; break;

		case 2: --changed.channels[0].maximum; break;

		case 3: ++changed.channels[0].disarmed; break;

		case 4: ++changed.channels[0].failsafe; break;

		case 5: changed.range_reverse_mask = 1; break;

		case 6: changed.reversible_motor_mask = 1; break;

		case 7: changed.rate_hz = 50; break;

		case 8: changed.airframe_id = 22001; break;
		}

		assert(identify_output_configuration(profiles, 2, changed) == 0);
	}

	OutputProfile duplicate[2] {profiles[0], profiles[0]};
	assert(!find_output_profile(duplicate, 2, 7));
	size_t count = 0;
	const OutputProfile *unconfigured = output_profiles(count);
	assert(!hardware_identity().configured());
	assert(!identify_output_configuration(unconfigured, count, profiles[0].configuration));
	assert(!find_output_profile(profiles, 2, 0));

	Hello expected{};
	expected.board = 1; expected.resources = 2; expected.profile = 3; expected.output_config = 7;
	ActuatorLease lease(expected, 400, profiles, 2);
	Context context{}; context.epoch = 5; context.sequence = 1;
	lease.session(5);
	assert(lease.receive_hello(encode(expected, context), 1000));
	lease.backend(true, false);
	context.sequence = 2;
	assert(lease.receive_heartbeat(encode_heartbeat(context, 0, 1, 1), 1000));
	Command command{};
	command.rate_hz = 400; command.generation = command.state_generation = 1;
	command.token = lease.issue_token(1000); context.sequence = 3;
	assert(lease.receive_command(encode(command, context), 1000));
	lease.acknowledge(5, 3, 1, true); lease.backend(true, true);
	command.state = Armed | SafetyOff; ++command.generation; ++command.state_generation;

	for (auto &pulse : command.outputs) { pulse = 1200; }

	context.sequence = 4;
	assert(lease.receive_command(encode(command, context), 1100));
	assert(lease.output(1100).enabled);
	command.outputs[0] = 2000; ++command.generation; context.sequence = 5;
	assert(!lease.receive_command(encode(command, context), 1200)); // Below wire max but above selected ESC range.
	expected.output_config = 8; context.sequence = 6;
	assert(!lease.receive_hello(encode(expected, context), 1300));
	assert(lease.rotation_requested() && !lease.output(1300).enabled);
	lease.session(6); context.epoch = 6; context.sequence = 1;
	assert(lease.receive_hello(encode(expected, context), 2000));
	lease.backend(true, false); context.sequence = 2;
	assert(lease.receive_heartbeat(encode_heartbeat(context, 0, 2, 2), 2000));
	command = Command{}; command.rate_hz = 400; command.generation = command.state_generation = 1;
	command.token = lease.issue_token(2000); context.sequence = 3;
	assert(lease.receive_command(encode(command, context), 2000));
	lease.acknowledge(6, 3, 1, true); lease.backend(true, true);
	command.state = Armed | SafetyOff; ++command.generation; ++command.state_generation;
	command.outputs[0] = command.outputs[1] = command.outputs[2] = 1200; context.sequence = 4;
	assert(!lease.receive_command(encode(command, context), 2100)); // Disabled fixture channel is forbidden.
	command.outputs[2] = 0;
	assert(lease.receive_command(encode(command, context), 2100));
	assert(lease.output(2100).values[2] == 0);
	return 0;
}
