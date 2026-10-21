// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

#include <lib/mixer_module/mixer_module.hpp>
#include <apps/hardware-contract.hpp>
#include <apps/output-producer.hpp>
#include <apps/raw-link.hpp>
#include <drivers/drv_hrt.h>
#include <px4_platform_common/module.h>
#include <px4_platform_common/tasks.h>
#include <uORB/Publication.hpp>
#include <uORB/PublicationMulti.hpp>
#include <uORB/Subscription.hpp>
#include <uORB/topics/vehicle_status.h>
#include <uORB/topics/parameter_update.h>
#include <uORB/topics/px4io_status.h>
#include <uORB/topics/battery_status.h>
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)
#include <apps/bench-fault.hpp>
#endif

using namespace rzv2h::demo;

class RemoteOutputs final : public ModuleBase<RemoteOutputs>, public OutputModuleInterface
{
public:
	RemoteOutputs() : OutputModuleInterface(MODULE_NAME, px4::wq_configurations::hp_default)
	{
		_mixing.setMaxNumOutputs(4);
		_mixing.setMaxTopicUpdateRate(2500);
		_mixing.setLowrateSchedulingInterval(10000);
	}
	static int task_spawn(int argc, char *argv[]);
	static int custom_command(int argc, char *argv[])
	{
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)
		RemoteOutputs *instance = _object.load();
		const bool accepted = instance && schedule_fault(instance->_fault, false, argc, argv, hrt_absolute_time());
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

		PRINT_MODULE_USAGE_NAME("rzv2h_outputs", "driver");
		PRINT_MODULE_USAGE_COMMAND("start");
		PRINT_MODULE_USAGE_DEFAULT_COMMANDS();
		return 0;
	}
	int print_status() override
	{
		PX4_INFO("v3 PWM_MAIN producer, hardware contract: %s",
			 hardware_identity().configured() ? "configured" : "UNCONFIGURED");
		PX4_INFO("sender running: %s", _sender_done.load() ? "no" : "yes");
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)
		PX4_INFO("fault invoked %lu started %lu completed %lu", (unsigned long)_fault.invoked(),
			 (unsigned long)_fault.started(), (unsigned long)_fault.completed());
#endif
		_mixing.printStatus();
		return 0;
	}
	bool updateOutputs(bool stop_motors, uint16_t outputs[MAX_ACTUATORS], unsigned count, unsigned updates) override;

private:
	void Run() override;
	void send_loop();
	void publish_battery_status(const BatteryTelemetry &measured, uint64_t now);
	static int sender(int, char *[]) { _object.load()->send_loop(); return 0; }
	MixingOutput _mixing{"PWM_MAIN", 4, *this, MixingOutput::SchedulingPolicy::Auto, true};
	SnapshotStore _snapshot;
	AtomicRecord<6> _peer;
	uORB::Subscription _vehicle{ORB_ID(vehicle_status)};
	uORB::Subscription _parameters{ORB_ID(parameter_update)};
	uORB::Publication<px4io_status_s> _health{ORB_ID(px4io_status)};
	uORB::PublicationMulti<battery_status_s> _battery{ORB_ID(battery_status)};
	px4::atomic<bool> _sender_stop{false};
	px4::atomic<bool> _sender_done{false};
	px4::atomic<bool> _exhausted{false};
	OutputProducer _producer;
	px4::atomic<uint32_t> _configuration_id{0};
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)
	BenchFaultSchedule _fault;
#endif
	DEFINE_PARAMETERS((ParamInt<px4::params::SYS_AUTOSTART>) _param_sys_autostart)
};

bool RemoteOutputs::updateOutputs(bool stop_motors, uint16_t outputs[MAX_ACTUATORS], unsigned count, unsigned updates)
{
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)

	if (_fault.active(BenchFault::ProducerPause, hrt_absolute_time())) { return false; }

#endif

	// This transaction owns values, armed state, source progress and token. No
	// raw write, ioctl, log, allocation or physical-output access belongs here.
	if (count != 4) { _configuration_id.store(0); return false; }

	OutputConfiguration actual{};
	actual.airframe_id = _param_sys_autostart.get();
	actual.rate_hz = OutputRateHz;
	actual.range_reverse_mask = _mixing.rangeReverseOutputs();
	actual.reversible_motor_mask = _mixing.reversibleOutputs();

	for (unsigned i = 0; i < 4; ++i) {
		auto &channel = actual.channels[i];
		channel.function = uint16_t(_mixing.outputFunction(i));
		channel.minimum = _mixing.minValue(i);
		channel.maximum = _mixing.maxValue(i);
		channel.disarmed = _mixing.disarmedValue(i);
		channel.failsafe = _mixing.actualFailsafeValue(i);
	}

	size_t profile_count = 0;
	const OutputProfile *profiles = output_profiles(profile_count);
	const uint32_t configuration_id = identify_output_configuration(profiles, profile_count, actual);
	_configuration_id.store(configuration_id);

	if (!configuration_id) { return false; }

	uint32_t peer[6] {};

	if (!_peer.read(peer) || !peer[0] || !peer[1] || !peer[5] || count > 4) { return false; }

	const uint64_t now = hrt_absolute_time();
	vehicle_status_s vehicle{};
	_vehicle.copy(&vehicle);
	const auto &armed = _mixing.armed();
	ProducerPeer remote{};
	remote.epoch = peer[0]; remote.token = peer[1];
	remote.received_us = uint64_t(peer[2]) | uint64_t(peer[3]) << 32;
	remote.compatible = peer[5]; remote.ready = peer[4] & ArmReady;
	ProducerInput input{};
	input.configuration_id = configuration_id;
	input.count = count; input.now = now;
	input.updated = updates != 0; input.rate_hz = OutputRateHz;
	input.state = (armed.armed ? Armed : 0) | (vehicle.safety_off ? SafetyOff : 0)
		      | (armed.force_failsafe ? ForceFailsafe | Termination : 0) | (armed.lockdown ? Lockdown : 0)
		      | (armed.manual_lockdown ? ManualLockdown : 0) | (stop_motors ? StopMotors : 0);

	hrt_abstime control_us = 0;
	bool coherent = true;

	for (unsigned i = 0; i < count; ++i) {
		input.values[i] = outputs[i];

		if (_mixing.isFunctionSet(i)) {
			input.active_mask |= 1u << i;
			hrt_abstime publication_us = 0;

			if (!_mixing.getOutputPublicationTimestamp(i, publication_us)
			    || (control_us && publication_us != control_us)) { coherent = false; }

			control_us = publication_us;
		}
	}

	// Values and progress come from the same consumed publication. Missing or
	// mixed progress denies active authority without delaying a stop/disarm.
	input.control_us = coherent ? control_us : 0;
	OutputSnapshot next{};
	const bool produced = _producer.produce(remote, input, next);
	_exhausted.store(_producer.exhausted());
	return produced && _snapshot.publish(next);
}

void RemoteOutputs::Run()
{
	if (should_exit()) {
		_sender_stop.store(true);

		if (!_sender_done.load()) { ScheduleDelayed(10000); return; }

		ScheduleClear();
		_mixing.unregister();
		exit_and_cleanup();
		return;
	}

	if (_parameters.updated()) {
		parameter_update_s update{};
		_parameters.copy(&update);
		updateParams();
	}

	_mixing.update();
	_mixing.updateSubscriptions(true);
}

void RemoteOutputs::publish_battery_status(const BatteryTelemetry &measured, uint64_t now)
{
	battery_status_s battery{};
	battery.timestamp = now; battery.connected = measured.connected; battery.is_required = true;
	battery.source = battery_status_s::SOURCE_EXTERNAL; battery.id = 1;
	battery.voltage_v = measured.voltage_v; battery.current_a = measured.current_a;
	battery.current_average_a = battery.discharged_mah = battery.scale = -1;
	battery.remaining = measured.remaining; battery.temperature = measured.temperature_c;
	battery.cell_count = measured.cells; battery.warning = measured.warning;
	battery.capacity = measured.capacity_mah; battery.interface_error = measured.errors;
	battery.max_cell_voltage_delta = measured.cell_delta_v;
	battery.time_remaining_s = battery.full_charge_capacity_wh = battery.remaining_capacity_wh = NAN;
	battery.nominal_voltage = battery.internal_resistance_estimate = battery.ocv_estimate = NAN;
	battery.ocv_estimate_filtered = battery.volt_based_soc_estimate = battery.voltage_prediction = NAN;
	battery.prediction_error = battery.estimation_covariance_norm = NAN;
	_battery.publish(battery);
}

void RemoteOutputs::send_loop()
{
	RawLink link;
	const BatteryPolicy power_policy = battery_policy();
	BatteryReceiver power(power_policy);
	const param_t low = param_find("BAT_LOW_THR"), critical = param_find("BAT_CRIT_THR"),
		      emergency = param_find("BAT_EMERGEN_THR");
	uint64_t battery_time = 0;
	uint32_t epoch = 0, sequence = 0, received = 0, token = 0, sent_generation = 0, loops = 0;
	uint32_t bound_profile = 0;
	uint64_t token_time = 0, status_time = 0, hello_time = 0, heartbeat_time = 0, recovery_time = 0;
	Status peer_status{};

	while (!_sender_stop.load()) {
		if (loops != UINT32_MAX) { ++loops; }

		const uint64_t now = hrt_absolute_time();
		rzv_ipc_raw_stats_s stats {};
		const uint32_t configured_profile = _configuration_id.load();
		const bool online = link.open_link() && link.state(stats) && stats.ready && !stats.degraded;

		if (!online) { power.session(0); epoch = 0; }

		if (online && stats.epoch != epoch) {
			epoch = stats.epoch;
			power.session(epoch);
			bound_profile = configured_profile;
			sequence = received = token = sent_generation = 0;
			token_time = status_time = hello_time = heartbeat_time = 0;
			peer_status = Status{};
			_exhausted.store(false);
			const uint32_t unavailable[6] {};
			_peer.publish(unavailable);
		}

		const uint64_t power_now = hrt_absolute_time();

		if (!battery_time || power_now - battery_time >= 100000) {
			BatteryThresholds thresholds{};
			param_get(low, &thresholds.low); param_get(critical, &thresholds.critical); param_get(emergency, &thresholds.emergency);
			publish_battery_status(battery_telemetry(power.observation(power_now), power_policy, thresholds), power_now);
			battery_time = power_now;
		}

		if (!bound_profile) { bound_profile = configured_profile; }

		const bool profile_changed = bound_profile && configured_profile != bound_profile;

		if (!online || profile_changed || _exhausted.load() || sequence + 4 >= CounterLimit
		    || (peer_status.backend & RotateSession)) {
			const uint32_t unavailable[6] {};
			_peer.publish(unavailable);
			px4io_status_s health{};
			health.timestamp = now;
			health.status_failsafe = true;
			_health.publish(health);

			if (now - recovery_time >= 1000000) {
				recovery_time = now;
				link.recover(); // Only CR8-0 owns raw session recovery.
			}

			px4_usleep(10000);
			continue;
		}

		Frame frame{};

		for (unsigned drained = 0; drained < 8 && link.receive(frame); ++drained) {
			if (validate(frame.bytes, EntrySize, 1, epoch) != Error::None) { continue; }

			if (Type(frame.bytes[6]) == Type::Battery || Type(frame.bytes[6]) == Type::BatteryDetail) {
				power.receive(frame, hrt_absolute_time());
				continue; // Power observations cannot refresh actuator status or lease.
			}

			if (Type(frame.bytes[6]) != Type::Status || read32(frame.bytes + 12) <= received) { continue; }

			received = read32(frame.bytes + 12);
			peer_status = status(frame);
			status_time = hrt_absolute_time();

			if (peer_status.token != token) { token = peer_status.token; token_time = status_time; }
		}

		const uint64_t current = hrt_absolute_time();
		const bool fresh = status_time && current >= status_time && current - status_time < 50000;
		const bool compatible = bound_profile && bound_profile == configured_profile && hardware_identity().configured()
					&& fresh && peer_status.rate_hz == OutputRateHz
					&& HardwareContract && peer_status.hardware_contract == HardwareContract
					&& peer_status.capabilities == RequiredActuatorCapabilities;
		const uint32_t peer[6] {epoch, token, uint32_t(token_time), uint32_t(token_time >> 32), peer_status.backend,
					compatible ? 1u : 0u
				       };
		_peer.publish(peer);
		Context context{};
		context.epoch = epoch;
		context.publication_us = current;

		if (!hello_time || current - hello_time >= 100000) {
			context.sequence = ++sequence;

			Hello selected_identity = hardware_identity();
			selected_identity.output_config = bound_profile;

			if (link.send(encode(selected_identity, context))) { hello_time = current; }
		}

		if (!heartbeat_time || current - heartbeat_time >= 100000) {
			context.sequence = ++sequence;
			const uint32_t uptime_ms = current / 1000 > UINT32_MAX ? UINT32_MAX : uint32_t(current / 1000);
			const Frame heartbeat = encode_heartbeat(context, 0, uptime_ms, loops);

#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)

			if (!_fault.active(BenchFault::HeartbeatDrop, current)) {
				if (link.send(heartbeat)) { heartbeat_time = current; }
			}

#else

			if (link.send(heartbeat)) { heartbeat_time = current; }

#endif
		}

		OutputSnapshot snapshot{};
		const uint64_t sending = hrt_absolute_time();

		if (compatible && _snapshot.read(snapshot) && snapshot.eligible(epoch, token)
		    && snapshot.configuration_id == bound_profile && _configuration_id.load() == bound_profile
		    && snapshot.command.generation > sent_generation && sending >= token_time
		    && sending - token_time < ActuatorFreshnessUs) {
			context.sequence = ++sequence;
			context.publication_us = hrt_absolute_time();

			Frame command_frame = encode(snapshot.command, context);
#if defined(CONFIG_RZV2H_DUALCR8_FAULT_INJECTION)

			if (_fault.consume(BenchFault::CorruptFrame, sending)) { command_frame.bytes[28] ^= 1; }

#endif

			if (link.send(command_frame)) { sent_generation = snapshot.command.generation; }
		}

		px4io_status_s health{};
		health.timestamp = hrt_absolute_time();
		const bool health_fresh = compatible && _configuration_id.load() == bound_profile && health.timestamp >= status_time
					  && health.timestamp - status_time < ActuatorFreshnessUs;
		health.status_fmu_initialized = health_fresh && (peer_status.backend & Initialized);
		health.status_fmu_ok = health_fresh && (peer_status.backend & Initialized) && (peer_status.backend & ArmReady)
				       && !(peer_status.backend & (FaultLatched | RotateSession)) && !peer_status.faults;
		health.status_init_ok = health.status_fmu_ok;
		health.arming_io_arm_ok = health.status_fmu_ok;
		health.alarm_pwm_error = !health_fresh || peer_status.faults || (peer_status.backend & FaultLatched)
					 || !(peer_status.backend & Initialized);

		for (unsigned i = 0; i < 4; ++i) { health.pwm_rate_hz[i] = health_fresh ? peer_status.rate_hz : 0; }

		health.status_outputs_armed = health_fresh && peer_status.lease_state == 2 && !(peer_status.backend & Inhibited);
		health.status_failsafe = !health.status_fmu_ok;
		_health.publish(health);
		px4_usleep(2500);
	}

	_sender_done.store(true);
}

int RemoteOutputs::task_spawn(int, char *argv[])
{
	RemoteOutputs *instance = new RemoteOutputs();

	if (!instance) { return -ENOMEM; }

	_object.store(instance);
	const int sender_task = px4_task_spawn_cmd("rzv2h_output_tx", SCHED_DEFAULT, SCHED_PRIORITY_ACTUATOR_OUTPUTS,
				3072, sender, argv);

	if (sender_task < 0) { _object.store(nullptr); delete instance; return -errno; }

	_task_id = task_id_is_work_queue;
	instance->ScheduleNow();
	return 0;
}

extern "C" __EXPORT int rzv2h_outputs_main(int argc, char *argv[]) { return RemoteOutputs::main(argc, argv); }
