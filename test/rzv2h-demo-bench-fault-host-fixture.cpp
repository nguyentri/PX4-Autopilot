// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#include <apps/bench-fault.hpp>
#include <cassert>
#include <thread>
#include <initializer_list>

using namespace rzv2h::demo;

int main()
{
	BenchFaultSchedule pause;
	assert(!pause.schedule(BenchFault::ProducerPause, 100, 4999, 100));
	assert(!pause.schedule(BenchFault::ProducerPause, 100, 5000, 0));
	assert(!pause.schedule(BenchFault::ProducerPause, 100, 5000, 5001));
	assert(!pause.schedule(BenchFault::ProducerPause, UINT64_MAX - 10, 5000, 100));
	assert(pause.schedule(BenchFault::ProducerPause, 100, 5000, 100));
	assert(pause.invoked() == 1 && !pause.started() && !pause.completed());
	assert(!pause.active(BenchFault::ProducerPause, 5000099));
	assert(!pause.active(BenchFault::StatusDrop, 5000100));
	assert(pause.active(BenchFault::ProducerPause, 5000100));
	assert(pause.active(BenchFault::ProducerPause, 5100099));
	assert(!pause.active(BenchFault::ProducerPause, 5100100));
	assert(pause.started() == 1 && pause.completed() == 1);
	assert(!pause.active(BenchFault::ProducerPause, 5000100)); // Completion cannot reactivate on a backward clock.
	assert(!pause.schedule(BenchFault::ProducerPause, 6000000, 5000, 100));

	BenchFaultSchedule corruption;
	assert(!corruption.schedule(BenchFault::CorruptFrame, 0, 5000, 2));
	assert(corruption.schedule(BenchFault::CorruptFrame, 0, 5000, 1));
	assert(!corruption.consume(BenchFault::CorruptFrame, 4999999));
	assert(corruption.consume(BenchFault::CorruptFrame, 6000000));
	assert(!corruption.consume(BenchFault::CorruptFrame, 6000001));
	assert(corruption.started() == 1 && corruption.completed() == 1);
	BenchFaultSchedule missed;
	assert(missed.schedule(BenchFault::CorruptFrame, 0, 5000, 1));
	assert(!missed.consume(BenchFault::CorruptFrame, 10000000));
	assert(!missed.started() && missed.completed());

	uint32_t number = 0;

	for (const char *bad : {"", "-1", "+5000", "5000ms", "60001", "4294967295"}) { assert(!fault_number(bad, number)); }
	assert(fault_number("5000", number) && number == 5000);
	char a[] = "fault", b[] = "control-loop-pause", c[] = "--delay-ms", d[] = "5000", e[] = "--duration-ms", f[] = "100";
	char *args[] {a, b, c, d, e, f};
	BenchFaultSchedule cli;
	assert(!schedule_fault(cli, false, 6, args, 1));
	assert(!schedule_fault(cli, true, 5, args, 1));
	assert(schedule_fault(cli, true, 6, args, 1));

	BenchFaultSchedule race;
	unsigned accepted[2] {};
	std::thread first([&]() { accepted[0] = race.schedule(BenchFault::StatusDrop, 0, 5000, 100); });
	std::thread second([&]() { accepted[1] = race.schedule(BenchFault::StatusDrop, 0, 5000, 100); });
	first.join(); second.join();
	assert(accepted[0] + accepted[1] == 1);
	return 0;
}
