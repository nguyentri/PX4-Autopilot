// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
//
// rzv2h_heartbeat: heartbeat-only exchange between CR8-0 (raw IPC initiator)
// and CR8-1 (responder) over /dev/ipcc1. CR8-0 sends one v3 heartbeat frame
// every 100 ms and CR8-1 replies to each one it accepts (never both writing at
// once; see ipc-heartbeat-monitor.hpp). Both track the peer and report alive/lost. It publishes no
// uORB topic (in particular never px4io_status), so it cannot gate arming, and
// it never sends commands or touches actuators.

#include "ipc-heartbeat-monitor.hpp"

#include <apps/raw-link.hpp>
#include <drivers/drv_hrt.h>
#include <px4_platform_common/module.h>
#include <px4_platform_common/tasks.h>

using namespace rzv2h::demo;

#if defined(CONFIG_RZV_IPC_ROLE_INITIATOR)
static constexpr bool LinkInitiator = true;
#else
static constexpr bool LinkInitiator = false;
#endif

class IpcHeartbeat final : public ModuleBase<IpcHeartbeat>
{
public:
	static int task_spawn(int, char *argv[])
	{
		_task_id = px4_task_spawn_cmd("rzv2h_heartbeat", SCHED_DEFAULT, SCHED_PRIORITY_DEFAULT, 2048,
					      (px4_main_t)&run_trampoline, argv);
		return _task_id < 0 ? -errno : 0;
	}
	static IpcHeartbeat *instantiate(int, char *[]) { return new IpcHeartbeat(); }
	static int custom_command(int, char *[]) { print_usage("unknown command"); return -EINVAL; }
	static int print_usage(const char *reason = nullptr)
	{
		if (reason) { PX4_WARN("%s", reason); }

		PRINT_MODULE_DESCRIPTION(R"DESCR_STR(
Heartbeat-only CR8-0 <-> CR8-1 liveness over the raw IPC link /dev/ipcc1.
The initiator (CR8-0) beats every 100 ms and the responder (CR8-1) replies
to each accepted beat; the peer is lost after 500 ms without one.
)DESCR_STR");
		PRINT_MODULE_USAGE_NAME("rzv2h_heartbeat", "driver");
		PRINT_MODULE_USAGE_COMMAND("start");
		PRINT_MODULE_USAGE_DEFAULT_COMMANDS();
		return 0;
	}

	// Runs in the caller's task; the 32-bit counters are read without a lock,
	// which is sufficient for diagnostics.
	int print_status() override
	{
		const uint64_t now = hrt_absolute_time();
		const HeartbeatCounters &c = _monitor.counters();
		const HeartbeatPeer &peer = _monitor.peer();
		const uint64_t age = _monitor.age_us(now);

		PX4_INFO("role: %s (source %u, peer %u)", _monitor.initiator() ? "initiator" : "responder",
			 _monitor.local_source(), _monitor.peer_source());
		PX4_INFO("link: %s epoch 0x%08lx sessions %lu", _monitor.epoch() ? "online" : "offline",
			 (unsigned long)_monitor.epoch(), (unsigned long)c.sessions);
		PX4_INFO("peer: %s age_ms %ld seq %lu uptime_ms %lu loops %lu state %u", _monitor.alive(now) ? "alive" : "lost",
			 age == UINT64_MAX ? -1L : long(age / 1000), (unsigned long)peer.sequence, (unsigned long)peer.uptime_ms,
			 (unsigned long)peer.loop_count, peer.state);
		PX4_INFO("tx: sent %lu failed %lu seq %lu", (unsigned long)c.tx_sent, (unsigned long)c.tx_failed,
			 (unsigned long)_monitor.sequence());
		PX4_INFO("rx: valid %lu ignored %lu stale %lu restarts %lu", (unsigned long)c.rx_valid,
			 (unsigned long)c.rx_ignored, (unsigned long)c.rx_stale, (unsigned long)c.peer_restarts);

		for (unsigned i = 1; i < sizeof(c.rejects) / sizeof(c.rejects[0]); ++i) {
			if (c.rejects[i]) { PX4_INFO("rx reject %s: %lu", error_name(Error(i)), (unsigned long)c.rejects[i]); }
		}

		PX4_INFO("raw: tx %lu rx %lu timeouts %lu stale_acks %lu bad_hdr %lu bad_entry %lu recoveries %lu ready %u degraded %u",
			 (unsigned long)_stats.tx_messages, (unsigned long)_stats.rx_messages, (unsigned long)_stats.tx_timeouts,
			 (unsigned long)_stats.stale_acks, (unsigned long)_stats.invalid_headers,
			 (unsigned long)_stats.invalid_entries, (unsigned long)_stats.recoveries, unsigned(_stats.ready),
			 unsigned(_stats.degraded));

		if (_monitor.initiator()) { PX4_INFO("recover requests: %lu", (unsigned long)c.recover_requests); }

		PX4_INFO("loops: %lu", (unsigned long)_loop_count);
		return 0;
	}

	void run() override
	{
		while (!should_exit()) {
			++_loop_count;
			bool online = refresh();

			// Drain a bounded burst. The responder reads even while offline:
			// a nonblocking read is what adopts a fresh initiator epoch after a
			// quarantine; GET_STATS alone cannot rejoin the link.
			for (unsigned i = 0; i < 8 && (online || !_monitor.initiator()); ++i) {
				Frame frame{};

				if (!_link.receive(frame)) { break; }

				const uint64_t received = hrt_absolute_time();
				online = refresh();

				if (online) { _monitor.receive(frame.bytes, EntrySize, received); }
			}

			const uint64_t now = hrt_absolute_time();

			if (online && _monitor.send_due(now)) {
				const Frame frame = _monitor.next_frame(now, uint32_t(now / 1000), _loop_count);
				_monitor.sent(_link.send(frame));

			} else if (!online && _monitor.recover_due(now)) {
				// Only the initiator owns raw session recovery.
				_link.recover();
			}

			px4_usleep(10000);
		}
	}

private:
	// Read the raw link state and hand it to the monitor; true when online.
	bool refresh()
	{
		const bool online = _link.open_link() && _link.state(_stats) && _stats.ready && !_stats.degraded;
		_monitor.session(online, _stats.epoch);
		return online;
	}

	RawLink _link{};
	rzv_ipc_raw_stats_s _stats{};
	HeartbeatMonitor _monitor{LinkInitiator};
	uint32_t _loop_count{0};
};

extern "C" __EXPORT int rzv2h_heartbeat_main(int argc, char *argv[]) { return IpcHeartbeat::main(argc, argv); }
