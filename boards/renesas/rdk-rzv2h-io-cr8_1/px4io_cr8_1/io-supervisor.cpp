// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

#include <apps/hardware-contract.hpp>
#include <apps/output-worker.hpp>
#include <apps/output-status.hpp>
#include <apps/raw-link.hpp>
#include <px4_platform_common/module.h>
#include <px4_platform_common/tasks.h>
#include <drivers/drv_hrt.h>
#include <drivers/drv_pwm_output.h>
#include <px4_arch/io_timer.h>
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)
#include <apps/bench-fault.hpp>
#endif

using namespace rzv2h::demo;

class PwmHardware
{
public:
	bool initialize()
	{
		// The candidate table contains four resources. A partial mask must not
		// initialize the unclaimed remainder through io_timer_init().
		if (!hardware_identity().configured() || OutputMask != 0xf || OutputRateHz < 50 || OutputRateHz > 500) { return false; }

		if (io_timer_init() != 0 || up_pwm_servo_init(OutputMask) != int(OutputMask)) { return false; }

		return up_pwm_servo_set_rate(OutputRateHz) == 0;
	}
	bool inhibit()
	{
		bool ok = io_timer_set_enable(false, IOTimerChanMode_PWMOut, OutputMask) == 0;

		for (unsigned i = 0; i < 4; ++i) {
			if ((OutputMask & (1u << i)) && up_pwm_servo_set(i, 0) != 0) { ok = false; }
		}

		_enabled = 0;
		return ok;
	}
	bool apply(const uint16_t (&values)[4])
	{
		uint32_t desired = 0;

		for (unsigned i = 0; i < 4; ++i) { if (values[i]) { desired |= 1u << i; } }

		desired &= OutputMask;

		if ((_enabled & ~desired) && io_timer_set_enable(false, IOTimerChanMode_PWMOut, _enabled & ~desired) != 0) { return false; }

		for (unsigned i = 0; i < 4; ++i) {
			if ((OutputMask & (1u << i)) && up_pwm_servo_set(i, values[i]) != 0) { return false; }
		}

		if ((desired & ~_enabled) && io_timer_set_enable(true, IOTimerChanMode_PWMOut, desired & ~_enabled) != 0) { return false; }

		_enabled = desired;
		return true;
	}
private:
	uint32_t _enabled{0};
};

class IoSupervisor final : public ModuleBase<IoSupervisor>
{
public:
	static int task_spawn(int, char *argv[])
	{
		_task_id = px4_task_spawn_cmd("rzv2h_io", SCHED_DEFAULT, SCHED_PRIORITY_DEFAULT + 20, 3072,
					      (px4_main_t)&run_trampoline, argv);
		return _task_id < 0 ? -errno : 0;
	}
	static IoSupervisor *instantiate(int, char *[]) { return new IoSupervisor(); }
	static int custom_command(int argc, char *argv[])
	{
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)
		IoSupervisor *instance = _object.load();
		const bool accepted = instance && schedule_fault(instance->_fault, true, argc, argv, hrt_absolute_time());
		return accepted ? 0 : -EINVAL;
#else
		(void)argc; (void)argv;
		print_usage("unknown command");
		return -EINVAL;
#endif
	}
	static int print_usage(const char *reason = nullptr)
	{
		if (reason) { PX4_WARN("%s", reason); }

		PRINT_MODULE_USAGE_NAME("rzv2h_io", "driver");
		PRINT_MODULE_USAGE_COMMAND("start");
		PRINT_MODULE_USAGE_DEFAULT_COMMANDS();
		return 0;
	}
	int print_status() override
	{
		OutputWorkerReport worker{};
		_worker_status.read(worker);
		PX4_INFO("v3 supervisor, contract %u (%s), backend 0x%02lx, worker loops %lu",
			 unsigned(HardwareContract), hardware_identity().configured() ? "configured" : "UNCONFIGURED",
			 (unsigned long)worker.flags, (unsigned long)worker.loops);
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)
		PX4_INFO("fault invoked %lu started %lu completed %lu", (unsigned long)_fault.invoked(),
			 (unsigned long)_fault.started(), (unsigned long)_fault.completed());
#endif
		return 0;
	}
	void run() override;
private:
	void work();
	void report();
	static int worker(int, char *[]) { _object.load()->work(); return 0; }
	static int reporter(int, char *[]) { _object.load()->report(); return 0; }
	OutputPlanStore _plan;
	OutputWorkerReportStore _worker_status;
	OutputStatusStore _control_status;
	px4::atomic<bool> _reporter_done{true}, _rotate{false};
	px4::atomic<bool> _worker_stop{false}, _worker_done{false};
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)
	BenchFaultSchedule _fault;
#endif
};

void IoSupervisor::work()
{
	PwmHardware hardware;
	OutputWorker<PwmHardware> output(hardware, hardware_identity().configured() && HardwareContract && OutputMask == 0xf);
	uint32_t loops = 0;

	while (!_worker_stop.load()) {
		OutputPlan plan{};
		_plan.read(plan); // Failed bounded read revokes authority for this tick.
		const uint64_t now = hrt_absolute_time();
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)

		if (_fault.consume(BenchFault::BackendFail, now)) { output.fail(plan.output.generation); }

#endif
		output.step(plan, now);
		_worker_status.publish(output.report(now, ++loops));
		px4_usleep(2500);
	}

	output.stop();
	_worker_done.store(true);
}

void IoSupervisor::report()
{
	RawLink link;
	uint32_t epoch = 0, sequence = 0;

	while (!_worker_stop.load()) {
		rzv_ipc_raw_stats_s stats{};
		Status control{};
		uint32_t control_epoch = 0;
		uint64_t updated = 0;
		const bool online = link.open_link() && link.state(stats) && stats.ready && !stats.degraded;

		if (!online || epoch != stats.epoch) { epoch = online ? stats.epoch : 0; sequence = 0; _rotate.store(false); }

		const uint64_t now = hrt_absolute_time();
		OutputWorkerReport worker_report{};
		_worker_status.read(worker_report);
		const bool have_control = _control_status.read(control, control_epoch, updated);

		if (online && have_control && epoch == control_epoch) {
			Status status = supervised_status(control, epoch, updated, worker_report, now);

			if (sequence + 2 >= CounterLimit) { _rotate.store(true); }

			if (_rotate.load()) { status.backend |= RotateSession; }

			if (sequence + 1 < CounterLimit) {
				Context context{};
				context.source = 1; context.sequence = ++sequence; context.epoch = epoch; context.publication_us = now;
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)

				if (!_fault.active(BenchFault::StatusDrop, now)) { link.send(encode(status, context)); }

#else
				link.send(encode(status, context));
#endif
			}
		}

		px4_usleep(10000);
	}

	_reporter_done.store(true);
}

void IoSupervisor::run()
{
	if (px4_task_spawn_cmd("rzv2h_output", SCHED_DEFAULT, SCHED_PRIORITY_ACTUATOR_OUTPUTS, 2048, worker, nullptr) < 0) {
		PX4_ERR("output worker spawn failed");
		return;
	}

	_reporter_done.store(false);

	if (px4_task_spawn_cmd("rzv2h_io_status", SCHED_DEFAULT, SCHED_PRIORITY_DEFAULT + 10, 2048, reporter, nullptr) < 0) {
		_worker_stop.store(true);

		while (!_worker_done.load()) { px4_usleep(2500); }

		PX4_ERR("status reporter spawn failed");
		return;
	}

	RawLink link;
	size_t profile_count = 0;
	const OutputProfile *profiles = output_profiles(profile_count);
	ActuatorLease lease(hardware_identity(), OutputRateHz, profiles, profile_count);
	uint32_t epoch = 0, loops = 0;

	while (!should_exit()) {
		rzv_ipc_raw_stats_s stats{};
		const bool opened = link.open_link();
		bool online = opened && link.state(stats) && stats.ready && !stats.degraded;

		if (!online || stats.epoch != epoch) {
			epoch = online ? stats.epoch : 0;
			lease.session(epoch);
		}

		const uint64_t now = hrt_absolute_time();
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)

		if (_fault.active(BenchFault::ControlPause, now)) { px4_usleep(2500); continue; }

#endif

		if (_rotate.load()) { lease.fault(ActuatorLease::CounterExhausted); }

		OutputWorkerReport worker_report{};
		const bool have_worker = _worker_status.read(worker_report);
		bool worker_current = have_worker && worker_report.current(epoch, now);
		uint8_t backend = worker_current ? uint8_t(worker_report.flags) : uint8_t(Inhibited);

		if (worker_current && !(backend & FaultLatched)) {
			lease.acknowledge(worker_report.epoch, worker_report.sequence, worker_report.generation, backend & Inhibited);
		}

		if (backend & FaultLatched) { lease.fault(ActuatorLease::BackendFailed); }

		lease.backend(backend & Initialized, !(backend & FaultLatched));
		Frame frame{};

		for (unsigned drained = 0; opened && drained < 8; ++drained) {
			// Nonblocking read also adopts a fresh initiator epoch while this
			// responder is quarantined. GET_STATS alone cannot rejoin the link.
			const bool received_frame = link.receive(frame);
			online = link.state(stats) && stats.ready && !stats.degraded;

			if (!online || stats.epoch != epoch) {
				epoch = online ? stats.epoch : 0;
				lease.session(epoch);
				worker_current = false;
				backend = Inhibited;
			}

			if (!online || !received_frame) { break; }

			if (validate(frame.bytes, EntrySize, 0, epoch) != Error::None) { continue; }

			const uint64_t received = hrt_absolute_time();

			switch (Type(frame.bytes[6])) {
			case Type::Hello: lease.receive_hello(frame, received); break;

			case Type::Heartbeat: lease.receive_heartbeat(frame, received); break;

			case Type::Command: lease.receive_command(frame, received); break;

			default: break;
			}
		}

		const uint64_t current = hrt_absolute_time();
		lease.update(current);
		OutputPlan plan{};
		plan.output = lease.output(current);
		plan.updated_us = current;
		plan.compatible = online && lease.compatible();
		plan.recovery = lease.state() == ActuatorLease::State::Ready;
		_plan.publish(plan);
		++loops;

		if (online) {
			Status report{};
			report.capabilities = RequiredActuatorCapabilities;
			report.accepted_sequence = lease.accepted_sequence();
			report.applied_sequence = worker_current ? worker_report.sequence : 0;
			report.applied_generation = worker_current ? worker_report.generation : 0;
			report.token = lease.issue_token(current);
			report.faults = lease.faults();
			report.rate_hz = OutputRateHz;
			report.hardware_contract = HardwareContract;
			report.lease_state = uint8_t(lease.state());
			report.backend = backend | (lease.ready() ? ArmReady : 0) | (lease.rotation_requested() ? RotateSession : 0);
			report.loop_count = loops;

			_control_status.publish(report, epoch, current);
		}

		px4_usleep(2500);
	}

	_worker_stop.store(true);

	while (!_worker_done.load() || !_reporter_done.load()) { px4_usleep(2500); }
}

extern "C" __EXPORT int rzv2h_io_main(int argc, char *argv[]) { return IoSupervisor::main(argc, argv); }
