// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
//
// Heartbeat-only liveness for the CR8-0 <-> CR8-1 raw IPC link. Pure state:
// no HRT, no file descriptors, so the host test drives it with synthetic time.
// The caller reports the link state and every received frame; the monitor
// decides what is accepted, when the next heartbeat is due, and (initiator
// only) when a raw session recovery may be requested.
//
// Only the initiator beats on a timer; the responder sends one heartbeat in
// reply to each accepted initiator heartbeat. A raw write blocks until the
// peer's read acknowledges it, so two timer-driven writers could each wait for
// the other's read and both time out (the driver then degrades the link). The
// reply arrives within one loop of the initiator's write, long before its next
// beat, so the two cores never write at the same time in normal operation.

#pragma once

#include <apps/protocol.hpp>

namespace rzv2h
{
namespace demo
{

struct HeartbeatCounters {
	uint32_t sessions{0};          // link epochs adopted (online with a new epoch)
	uint32_t tx_sent{0};
	uint32_t tx_failed{0};
	uint32_t rx_valid{0};          // valid peer heartbeats
	uint32_t rx_ignored{0};        // valid frames of another type; never acted on
	uint32_t rx_stale{0};          // valid heartbeat with a non-increasing sequence
	uint32_t peer_restarts{0};     // sequence restarted near 1 with lower uptime in one epoch
	uint32_t recover_requests{0};
	uint32_t rejects[uint8_t(Error::Semantic) + 1] {};
};

struct HeartbeatPeer {
	uint32_t sequence{0};
	uint32_t uptime_ms{0};
	uint32_t loop_count{0};
	uint8_t state{0};
};

class HeartbeatMonitor
{
public:
	static constexpr uint64_t TxPeriodUs = 100000;      // initiator beat, 10 Hz
	static constexpr uint64_t PeerTimeoutUs = 500000;   // peer lost after 5 missed beats
	static constexpr uint64_t RecoverPeriodUs = 1000000; // initiator recovery rate limit
	static constexpr uint8_t StateRunning = 1;
	static constexpr uint32_t RestartWindow = 3;        // a reloaded peer restarts at sequence 1

	explicit HeartbeatMonitor(bool initiator) : _initiator(initiator), _local(initiator ? 0 : 1),
		_peer_source(initiator ? 1 : 0) {}

	bool initiator() const { return _initiator; }
	uint8_t local_source() const { return _local; }
	uint8_t peer_source() const { return _peer_source; }

	// Report the current link state. Offline or a new epoch drops liveness and
	// restarts the local sequence. Returns true when the session changed.
	bool session(bool online, uint32_t epoch)
	{
		const uint32_t current = online ? epoch : 0;

		if (current == _epoch) { return false; }

		_epoch = current;
		_sequence = 0;
		_last_tx_us = 0;
		_last_rx_us = 0;
		_have_peer = false;
		_reply_pending = false;
		_peer = HeartbeatPeer{};

		if (current) { ++_counters.sessions; }

		return true;
	}

	// Classify one received frame. Only a valid, newer peer heartbeat of the
	// current epoch refreshes liveness.
	Error receive(const uint8_t *bytes, size_t size, uint64_t now)
	{
		const Error error = validate(bytes, size, _peer_source, _epoch);

		if (error != Error::None) {
			++_counters.rejects[uint8_t(error)];
			return error;
		}

		if (Type(bytes[6]) != Type::Heartbeat) { ++_counters.rx_ignored; return Error::None; }

		HeartbeatPeer peer{};
		peer.sequence = read32(bytes + 12);
		peer.state = bytes[32];
		peer.uptime_ms = read32(bytes + 36);
		peer.loop_count = read32(bytes + 40);

		if (_have_peer && peer.sequence <= _peer.sequence) {
			// A peer reloaded inside an unchanged epoch restarts at sequence 1
			// with a smaller uptime; any other non-increasing frame is stale.
			if (peer.sequence > RestartWindow || peer.uptime_ms >= _peer.uptime_ms) {
				++_counters.rx_stale;
				return Error::Sequence;
			}

			++_counters.peer_restarts;
		}

		_peer = peer;
		_have_peer = true;
		_last_rx_us = now;
		_reply_pending = !_initiator;
		++_counters.rx_valid;
		return Error::None;
	}

	bool alive(uint64_t now) const { return _have_peer && now >= _last_rx_us && now - _last_rx_us < PeerTimeoutUs; }

	// Microseconds since the last accepted heartbeat; UINT64_MAX when none.
	uint64_t age_us(uint64_t now) const { return _have_peer && now >= _last_rx_us ? now - _last_rx_us : UINT64_MAX; }

	// Initiator: every TxPeriodUs. Responder: once per accepted initiator beat.
	bool send_due(uint64_t now) const
	{
		if (!_epoch || _sequence + 1 >= CounterLimit) { return false; }

		return _initiator ? !_last_tx_us || now - _last_tx_us >= TxPeriodUs : _reply_pending;
	}

	// Build the next heartbeat. The caller sends it and reports the result.
	Frame next_frame(uint64_t now, uint32_t uptime_ms, uint32_t loop_count)
	{
		Context context{};
		context.source = _local;
		context.sequence = ++_sequence;
		context.epoch = _epoch;
		context.publication_us = now;
		_last_tx_us = now;
		_reply_pending = false;
		return encode_heartbeat(context, StateRunning, uptime_ms, loop_count);
	}

	void sent(bool ok) { ok ? ++_counters.tx_sent : ++_counters.tx_failed; }

	// Initiator only: true at most once per RecoverPeriodUs while offline.
	bool recover_due(uint64_t now)
	{
		if (!_initiator || _epoch) { return false; }

		if (_recover_requested && now - _last_recover_us < RecoverPeriodUs) { return false; }

		_recover_requested = true;
		_last_recover_us = now;
		++_counters.recover_requests;
		return true;
	}

	uint32_t epoch() const { return _epoch; }
	uint32_t sequence() const { return _sequence; }
	const HeartbeatPeer &peer() const { return _peer; }
	const HeartbeatCounters &counters() const { return _counters; }

private:
	bool _initiator;
	uint8_t _local;
	uint8_t _peer_source;
	uint32_t _epoch{0};
	uint32_t _sequence{0};
	uint64_t _last_tx_us{0};
	uint64_t _last_rx_us{0};
	uint64_t _last_recover_us{0};
	bool _recover_requested{false};
	bool _have_peer{false};
	bool _reply_pending{false};
	HeartbeatPeer _peer{};
	HeartbeatCounters _counters{};
};

inline const char *error_name(Error error)
{
	static const char *const names[] = {"none", "length", "magic", "version", "type", "source", "reserved",
					    "epoch", "sequence", "crc", "padding", "semantic"
					   };
	return uint8_t(error) < sizeof(names) / sizeof(names[0]) ? names[uint8_t(error)] : "?";
}

} // namespace demo
} // namespace rzv2h
