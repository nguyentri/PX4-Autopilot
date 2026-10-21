// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

#include <apps/output-snapshot.hpp>
#include <assert.h>
#include <thread>
#include <atomic>
#include <stdio.h>

using namespace rzv2h::demo;

int main()
{
	SnapshotStore store;
	OutputSnapshot value{}, copied{};
	assert(!store.read(copied));
	value.epoch = 7;
	value.command.token = 3;
	value.command.generation = 1;
	value.command.state_generation = 1;
	value.command.produced_us = 100;
	value.token_received_us = 90;
	assert(value.eligible(7, 3));
	value.command.state = Armed | SafetyOff;
	assert(!value.eligible(7, 3));
	value.control_updated = true;
	value.control_us = 90;
	assert(!value.eligible(7, 3));
	value.control_us = 95;
	assert(value.eligible(7, 3));
	assert(!value.eligible(8, 3) && !value.eligible(7, 4));
	value.control_us = 101;
	assert(!value.eligible(7, 3));
	value.control_us = 95;
	value.command.produced_us = value.token_received_us + ActuatorFreshnessUs;
	assert(!value.eligible(7, 3));

	std::atomic<bool> done{false};
	std::thread writer([&]() {
		for (uint32_t generation = 1; generation <= 100000; ++generation) {
			OutputSnapshot next{};
			next.epoch = generation;
			next.configuration_id = generation ^ 0x12345678;
			next.command.generation = generation;
			next.command.state_generation = generation;
			next.command.token = generation;
			next.command.state = generation & 0x7f;
			next.command.rate_hz = 50 + generation % 451;
			next.command.produced_us = uint64_t(generation) << 32 | generation;
			next.control_us = next.command.produced_us;
			next.token_received_us = next.command.produced_us - 1;
			next.control_updated = generation & 1;

			for (unsigned i = 0; i < 4; ++i) { next.command.outputs[i] = uint16_t(generation + i); }

			assert(store.publish(next));
		}

		done.store(true);
	});

	unsigned consistent = 0;

	do {
		if (store.read(copied)) {
			const uint32_t generation = copied.command.generation;
			assert(copied.epoch == generation && copied.command.token == generation);
			assert(copied.configuration_id == (generation ^ 0x12345678));
			assert(copied.command.state_generation == generation);
			assert(copied.command.state == (generation & 0x7f));
			assert(copied.command.rate_hz == 50 + generation % 451);
			assert(copied.control_updated == bool(generation & 1));
			assert(copied.command.produced_us == (uint64_t(generation) << 32 | generation));
			assert(copied.control_us == copied.command.produced_us);
			assert(copied.token_received_us + 1 == copied.command.produced_us);

			for (unsigned i = 0; i < 4; ++i) { assert(copied.command.outputs[i] == uint16_t(generation + i)); }

			++consistent;
		}
	} while (!done.load());

	writer.join();
	assert(store.read(copied) && copied.command.generation == 100000);
	printf("100000 concurrent snapshot commits, %u coherent reads, freshness gates passed\n", consistent);
	return 0;
}
