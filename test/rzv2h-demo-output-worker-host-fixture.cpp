// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#include <apps/output-producer.hpp>
#include <apps/output-worker.hpp>
#include <apps/output-status.hpp>
#include <cassert>

using namespace rzv2h::demo;

struct CapturedHardware {
	unsigned initialization{0}, inhibitions{0}, writes{0};
	bool healthy{true};
	uint16_t last[4] {};
	bool initialize() { ++initialization; return healthy; }
	bool inhibit() { ++inhibitions; return healthy; }
	bool apply(const uint16_t (&values)[4]) { ++writes; for (unsigned i = 0; i < 4; ++i) { last[i] = values[i]; } return healthy; }
};

int main()
{
	ProducerPeer peer{}; peer.epoch = 7; peer.token = 1; peer.received_us = 1000; peer.compatible = true;
	ProducerInput input{}; input.count = 4; input.rate_hz = 400; input.now = 2000;
	input.active_mask = 3;
	input.values[0] = input.values[1] = 1234;
	input.values[2] = input.values[3] = 1000; // Unassigned channels may still carry mixer DIS internally.
	OutputProducer producer;
	OutputSnapshot snapshot{};
	assert(producer.produce(peer, input, snapshot));
	assert(snapshot.command.outputs[0] == 0); // Explicit recovery handshake.
	peer.ready = true;
	assert(producer.produce(peer, input, snapshot));
	assert(snapshot.command.outputs[0] == 1234); // Stored DIS preserved.
	assert(snapshot.command.outputs[2] == 0 && snapshot.command.outputs[3] == 0);
	input.state = Armed | SafetyOff; input.control_us = 1100; input.updated = true;
	assert(producer.produce(peer, input, snapshot));
	assert(!producer.produce(peer, input, snapshot)); // Repeated cached control.
	peer.token = 2; peer.received_us = 1200;
	assert(!producer.produce(peer, input, snapshot)); // Token-only refresh.
	input.control_us = 3000;
	assert(!producer.produce(peer, input, snapshot)); // Rejected future source time cannot poison later progress.
	input.control_us = 1300;
	assert(producer.produce(peer, input, snapshot));
	input.updated = false; input.state |= ManualLockdown;
	assert(producer.produce(peer, input, snapshot)); // Kill does not await control progress.
	input.state = Armed | SafetyOff | ForceFailsafe | Termination;
	assert(producer.produce(peer, input, snapshot)); // Termination does not await control progress either.
	input.count = 5;
	assert(!producer.produce(peer, input, snapshot));

	OutputPlan plan{}; plan.compatible = true; plan.output.epoch = 7; plan.updated_us = 1000;
	CapturedHardware absent;
	OutputWorker<CapturedHardware> unconfigured(absent, false);

	for (unsigned i = 1000; i < 100000; i += 2500) { plan.updated_us = i; unconfigured.step(plan, i); }

	unconfigured.stop();
	assert(absent.initialization == 0 && absent.inhibitions == 0 && absent.writes == 0);
	CapturedHardware hardware;
	OutputWorker<CapturedHardware> worker(hardware, true);
	plan.updated_us = 1000;
	worker.step(plan, 1000);
	assert(worker.initialized() && hardware.initialization == 1 && hardware.writes == 0);
	plan.output.enabled = true; plan.output.generation = plan.output.sequence = 1;
	plan.output.deadline_us = 51000; plan.output.values[0] = 1300;
	worker.step(plan, 2000);
	assert(hardware.writes == 1 && hardware.last[0] == 1300);
	worker.step(plan, 51000); // No transport progress: independent worker cuts off.
	assert(worker.faulted() && (worker.flags() & Inhibited));
	plan.updated_us = 52000; plan.output.deadline_us = 102000;
	worker.step(plan, 52000); // Resumed cached armed publication cannot clear fault.
	assert(worker.faulted() && hardware.writes == 1);
	plan.output.generation = 2; plan.output.enabled = false; plan.recovery = true;
	worker.step(plan, 53000);
	assert(!worker.faulted());
	plan.output.enabled = true; plan.recovery = false; plan.output.generation = 3;
	worker.step(plan, 54000);
	assert(hardware.writes == 2);
	plan.output.enabled = false; plan.recovery = true; plan.output.generation = 4;
	worker.step(plan, 55000); // Ordinary disarm inhibits without a spurious fault.
	assert(!worker.faulted() && (worker.flags() & Inhibited));
	assert(worker.applied_generation() == 4); // Safe inhibition also has a worker receipt.
	plan.output.enabled = true; plan.recovery = false; plan.output.generation = 5;
	worker.step(plan, 56000);
	plan.output.epoch = 8;
	worker.step(plan, 57000);
	assert(worker.faulted() && (worker.flags() & Inhibited));
	plan.output.enabled = false; plan.recovery = true; plan.output.generation = 6;
	worker.step(plan, 58000);
	assert(!worker.faulted());
	hardware.healthy = false; plan.output.enabled = true; plan.recovery = false;
	worker.step(plan, 59000);
	assert(worker.faulted() && !worker.initialized());
	hardware.healthy = true; plan.output.enabled = false; plan.recovery = true; ++plan.output.generation;
	worker.step(plan, 60000);
	assert(worker.faulted() && !worker.initialized()); // Hardware error survives resumed control.

	CapturedHardware restarted_hardware;
	OutputWorker<CapturedHardware> restarted(restarted_hardware, true);
	OutputPlan restart{};
	restart.compatible = true; restart.output.epoch = 7; restart.updated_us = 1000;
	restarted.step(restart, 1000);
	restart.output.enabled = true; restart.output.generation = restart.output.sequence = 100000;
	restart.output.deadline_us = 51000;
	restarted.step(restart, 2000);
	restarted.step(restart, 51000);
	assert(restarted.faulted());
	restart.updated_us = 52000; restart.output.deadline_us = 102000;
	restart.output.epoch = 8; restart.output.generation = restart.output.sequence = 1;
	restarted.step(restart, 52000); // A new epoch alone cannot restore armed output.
	assert(restarted.faulted() && restarted_hardware.writes == 1);
	restart.output.enabled = false; restart.recovery = true; restart.output.generation = 0;
	restarted.step(restart, 53000);
	assert(restarted.faulted()); // A real current-session handshake is still required.
	restart.output.generation = restart.output.sequence = 1;
	restarted.step(restart, 54000);
	assert(!restarted.faulted() && (restarted.flags() & Inhibited));
	restart.output.enabled = true; restart.recovery = false; restart.output.generation = 2;
	restarted.step(restart, 55000);
	assert(restarted_hardware.writes == 2);
	restarted_hardware.healthy = false;
	restarted.step(restart, 56000);
	restarted_hardware.healthy = true;
	restart.output.epoch = 9; restart.output.enabled = false; restart.recovery = true; restart.output.generation = 1;
	restarted.step(restart, 57000);
	assert(restarted.faulted() && !restarted.initialized()); // Epoch changes cannot clear hardware errors.

	OutputPlanStore store;
	assert(store.publish(plan));
	OutputPlan read{};
	assert(store.read(read) && read.output.epoch == plan.output.epoch && read.recovery == plan.recovery);
	OutputWorkerReportStore reports;
	const OutputWorkerReport report = worker.report(0x100000005ULL, 123);
	assert(reports.publish(report));
	OutputWorkerReport observed{};
	assert(reports.read(observed));
	assert(observed.epoch == worker.epoch() && observed.sequence == worker.applied_sequence());
	assert(observed.generation == worker.applied_generation() && observed.flags == worker.flags() && observed.loops == 123);
	assert(observed.current(8, report.time_us) && observed.current(8, report.time_us + 9999));
	assert(!observed.current(7, report.time_us) && !observed.current(0, report.time_us));
	assert(!observed.current(8, report.time_us - 1) && !observed.current(8, report.time_us + 10000));

	Status status{};
	status.token = 42; status.backend = ArmReady; status.rate_hz = 400;
	OutputStatusStore control;
	assert(control.publish(status, 8, 100000));
	uint32_t control_epoch = 0;
	uint64_t control_updated = 0;
	Status restored{};
	assert(control.read(restored, control_epoch, control_updated));
	assert(restored.token == 42 && control_epoch == 8 && control_updated == 100000);
	observed.epoch = 8; observed.time_us = 100000; observed.flags = Initialized | Inhibited;
	Status merged = supervised_status(status, 8, 100000, observed, 100001);
	assert((merged.backend & ArmReady) && !merged.faults);
	observed.flags |= FaultLatched;
	merged = supervised_status(status, 8, 100000, observed, 100001);
	assert(!(merged.backend & ArmReady) && (merged.faults & ActuatorLease::BackendFailed));
	observed.flags = Initialized | Inhibited;
	merged = supervised_status(status, 8, 100000, observed, 110000);
	assert(!(merged.backend & ArmReady) && (merged.faults & ActuatorLease::BackendFailed));
	observed.time_us = 150000;
	merged = supervised_status(status, 8, 100000, observed, 150000);
	assert(!(merged.backend & ArmReady) && (merged.faults & ActuatorLease::CommandLost));
	assert(merged.token == 42); // Reporter progress never reissues freshness authority.

	CapturedHardware failed_init;
	failed_init.healthy = false;
	OutputWorker<CapturedHardware> initializing(failed_init, true);
	plan.output.enabled = false;
	initializing.step(plan, plan.updated_us);
	assert(failed_init.initialization == 1 && failed_init.inhibitions == 1 && initializing.faulted());
	CapturedHardware injected_hardware;
	OutputWorker<CapturedHardware> injected(injected_hardware, false);
	injected.fail(1);
	injected.stop();
	assert(injected.faulted() && !injected_hardware.initialization && !injected_hardware.inhibitions);
	return 0;
}
