// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
//
// rzv2h_heartbeat: heartbeat-only exchange between CR8-0 (raw IPC initiator)
// and CR8-1 (responder) over /dev/ipcc1. CR8-0 sends one v3 heartbeat frame
// every 100 ms and CR8-1 replies to each one it accepts (never both writing at
// once; see ipc-heartbeat-monitor.hpp). Both track the peer and report alive/lost.
// "ping" and "say <text>" exchange a display-only text message with the peer
// in the same write slots. The only uORB outputs are the display-only
// debug_vect "CR80-CR81" and mavlink_log text (never the PX4IO status), so it
// cannot gate arming, and it never sends commands or touches actuators.

#include "ipc-heartbeat-monitor.hpp"

#include <apps/raw-link.hpp>
#include <drivers/drv_hrt.h>
#include <px4_platform_common/atomic.h>
#include <px4_platform_common/module.h>
#include <px4_platform_common/tasks.h>
#include <uORB/Publication.hpp>
#include <uORB/topics/debug_vect.h>
#include <systemlib/mavlink_log.h>

#include <string.h>

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
		_task_id = px4_task_spawn_cmd("rzv2h_heartbeat", SCHED_DEFAULT, SCHED_PRIORITY_DEFAULT, 2560,
					      (px4_main_t)&run_trampoline, argv);
		return _task_id < 0 ? -errno : 0;
	}
	static IpcHeartbeat *instantiate(int, char *[]) { return new IpcHeartbeat(); }
	static int custom_command(int argc, char *argv[])
	{
		if (argc >= 1 && (!strcmp(argv[0], "ping") || (!strcmp(argv[0], "say") && argc >= 2))) {
			return text_command(argc, argv);
		}

		print_usage("unknown command");
		return -EINVAL;
	}
	static int print_usage(const char *reason = nullptr)
	{
		if (reason) { PX4_WARN("%s", reason); }

		PRINT_MODULE_DESCRIPTION(R"DESCR_STR(
Heartbeat-only CR8-0 <-> CR8-1 liveness over the raw IPC link /dev/ipcc1.
The initiator (CR8-0) beats every 100 ms and the responder (CR8-1) replies
to each accepted beat; the peer is lost after 500 ms without one.
Every 500 ms it publishes debug_vect CR80-CR81 for the GCS (MAVLink DEBUG_VECT):
x = ms since the last peer beat (-1 before the first), y = peer sequence,
z = 1 while the peer is alive, 0 when lost.

ping / say send one text message to the other core, which prints it on its
console (CR8-0 also forwards it to the GCS as a notification) and replies
"hello from CR8-x"; the sender prints the reply and the round-trip time.
Run on CR8-0 from NSH or the MAVLink console, or on CR8-1 from its RTT NSH.
)DESCR_STR");
		PRINT_MODULE_USAGE_NAME("rzv2h_heartbeat", "driver");
		PRINT_MODULE_USAGE_COMMAND("start");
		PRINT_MODULE_USAGE_COMMAND_DESCR("ping", "Ping the other core and print its reply and round trip");
		PRINT_MODULE_USAGE_COMMAND_DESCR("say", "Send a text message (max 24 chars) to the other core");
		PRINT_MODULE_USAGE_ARG("<text>", "Message for say", false);
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
		PX4_INFO("text: sent %lu received %lu", (unsigned long)c.tx_text, (unsigned long)c.rx_text);

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

			handle_text();
			const uint64_t now = hrt_absolute_time();

			if (online && _monitor.send_due(now)) {
				const Frame frame = _monitor.next_frame(now, uint32_t(now / 1000), _loop_count);
				_monitor.sent(_link.send(frame));

			} else if (!online && _monitor.recover_due(now)) {
				// Only the initiator owns raw session recovery.
				_link.recover();
			}

			publish_peer(now);
			px4_usleep(10000);
		}
	}

private:
	static constexpr uint64_t PeerPublishPeriodUs = 500000;
	static constexpr unsigned TextPollUs = 10000;

	// Shell side of ping/say: hand the text to the module task, then wait for
	// the reply. One request at a time; a newer one replaces an unanswered one.
	static int text_command(int argc, char *argv[])
	{
		IpcHeartbeat *self = get_instance();

		if (!self) { PX4_ERR("not running"); return -1; }

		char text[TextMax + 1] {};

		if (!strcmp(argv[0], "ping")) {
			snprintf(text, sizeof(text), "ping from %s", self->_monitor.local_name());

		} else {
			for (int i = 1; i < argc; ++i) {
				const size_t used = strlen(text);
				snprintf(text + used, sizeof(text) - used, "%s%s", i > 1 ? " " : "", argv[i]);
			}
		}

		// Publish the text before the id: the module task reads the id first.
		const uint32_t id = self->_next_text_id.fetch_add(1) + 1;
		memcpy(self->_shell_text, text, sizeof(text));
		self->_shell_request.store(id);
		PX4_INFO("%s -> %s: \"%s\" (#%lu)", self->_monitor.local_name(), self->_monitor.peer_name(), text,
			 (unsigned long)id);

		for (uint64_t waited = 0; waited < HeartbeatMonitor::TextTimeoutUs; waited += TextPollUs) {
			if (self->_shell_reply.load() == id) {
				const uint32_t rtt = self->_shell_reply_rtt_us;
				PX4_INFO("%s -> %s: \"%s\" (#%lu) round trip %lu.%03lu ms", self->_monitor.peer_name(),
					 self->_monitor.local_name(), self->_shell_reply_text, (unsigned long)id,
					 (unsigned long)(rtt / 1000), (unsigned long)(rtt % 1000));
				return 0;
			}

			px4_usleep(TextPollUs);
		}

		PX4_WARN("no reply from %s within %lu ms (link %s)", self->_monitor.peer_name(),
			 (unsigned long)(HeartbeatMonitor::TextTimeoutUs / 1000), self->_monitor.epoch() ? "online" : "offline");
		return -1;
	}

	// Module task: queue a new shell request, print peer requests, and pass
	// the reply back to the waiting shell.
	void handle_text()
	{
		const uint32_t id = _shell_request.load();

		if (id && id != _taken_request) {
			_taken_request = id;
			char text[TextMax + 1] {};
			memcpy(text, _shell_text, sizeof(text));
			text[TextMax] = '\0';
			_monitor.queue_text(id, text);
		}

		TextMessage message{};
		uint64_t rtt_us = 0;

		if (_monitor.take_request(message)) {
			// Shown on this core's console; on CR8-0 also a GCS notification.
			mavlink_log_info(&_mavlink_log_pub, "%s says: \"%s\" (#%lu)", _monitor.peer_name(), message.text,
					 (unsigned long)message.id);
		}

		if (_monitor.take_reply(message, rtt_us)) {
			memcpy(_shell_reply_text, message.text, sizeof(_shell_reply_text));
			_shell_reply_rtt_us = rtt_us > UINT32_MAX ? UINT32_MAX : uint32_t(rtt_us);
			_shell_reply.store(message.id);
		}
	}

	// Display-only peer view for the GCS; 2 Hz matches the DEBUG_VECT stream rate.
	void publish_peer(uint64_t now)
	{
		if (now - _last_peer_publish < PeerPublishPeriodUs) { return; }

		_last_peer_publish = now;
		const uint64_t age = _monitor.age_us(now);
		debug_vect_s v{};
		v.timestamp = now;
		strncpy(v.name, "CR80-CR81", sizeof(v.name) - 1);
		v.x = age == UINT64_MAX ? -1.f : float(age / 1000);
		v.y = float(_monitor.peer().sequence);
		v.z = _monitor.alive(now) ? 1.f : 0.f;
		_peer_pub.publish(v);
	}

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
	uint64_t _last_peer_publish{0};
	uORB::Publication<debug_vect_s> _peer_pub{ORB_ID(debug_vect)};
	orb_advert_t _mavlink_log_pub{nullptr};

	// Shell <-> module task handoff for ping/say.
	px4::atomic<uint32_t> _next_text_id{0};
	px4::atomic<uint32_t> _shell_request{0};
	px4::atomic<uint32_t> _shell_reply{0};
	char _shell_text[TextMax + 1] {};
	char _shell_reply_text[TextMax + 1] {};
	uint32_t _shell_reply_rtt_us{0};
	uint32_t _taken_request{0};
};

extern "C" __EXPORT int rzv2h_heartbeat_main(int argc, char *argv[]) { return IpcHeartbeat::main(argc, argv); }
