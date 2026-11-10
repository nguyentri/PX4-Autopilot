// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
//
// Host fixture for the rzv2h_heartbeat liveness state. Drives both roles with
// synthetic time and frames built by the production v3 codec.

#include "../boards/renesas/rdk-rzv2h/ipc_heartbeat/ipc-heartbeat-monitor.hpp"
#include <assert.h>
#include <stdio.h>
#include <string.h>

using namespace rzv2h::demo;

static Frame beat(uint8_t source, uint32_t epoch, uint32_t sequence, uint32_t uptime_ms, uint32_t loops = 0)
{
	Context context{};
	context.source = source;
	context.epoch = epoch;
	context.sequence = sequence;
	context.publication_us = 1000;
	return encode_heartbeat(context, 1, uptime_ms, loops);
}

static void roles()
{
	HeartbeatMonitor initiator(true), responder(false);
	assert(initiator.local_source() == 0 && initiator.peer_source() == 1);
	assert(responder.local_source() == 1 && responder.peer_source() == 0);
}

static void exchange_both_directions()
{
	HeartbeatMonitor cr8_0(true), cr8_1(false);
	assert(cr8_0.session(true, 7) && cr8_1.session(true, 7));
	assert(!cr8_0.session(true, 7));

	uint64_t now = 1000000;

	for (unsigned i = 0; i < 20; ++i, now += 100000) {
		// The responder never beats on its own: it only replies.
		assert(cr8_0.send_due(now) && !cr8_1.send_due(now));
		const Frame a = cr8_0.next_frame(now, uint32_t(now / 1000), i);
		cr8_0.sent(true);
		assert(!cr8_0.send_due(now + 50000));
		assert(cr8_1.receive(a.bytes, EntrySize, now) == Error::None);
		assert(cr8_1.send_due(now));
		const Frame b = cr8_1.next_frame(now, uint32_t(now / 1000), i);
		cr8_1.sent(true);
		assert(!cr8_1.send_due(now + 10 * HeartbeatMonitor::TxPeriodUs));
		assert(cr8_0.receive(b.bytes, EntrySize, now) == Error::None);
		assert(cr8_0.alive(now) && cr8_1.alive(now));
	}

	assert(cr8_0.counters().rx_valid == 20 && cr8_1.counters().tx_sent == 20);
	assert(cr8_0.peer().sequence == 20 && cr8_0.peer().loop_count == 19 && cr8_0.peer().state == 1);
	// Own frames echoed back are rejected by source.
	const Frame own = cr8_0.next_frame(now, 0, 0);
	assert(cr8_0.receive(own.bytes, EntrySize, now) == Error::Source);
}

static void loss_after_timeout()
{
	HeartbeatMonitor monitor(true);
	monitor.session(true, 3);
	assert(!monitor.alive(0) && monitor.age_us(0) == UINT64_MAX);
	const Frame b = beat(1, 3, 1, 10);
	assert(monitor.receive(b.bytes, EntrySize, 2000000) == Error::None);
	assert(monitor.alive(2000000 + HeartbeatMonitor::PeerTimeoutUs - 1));
	assert(!monitor.alive(2000000 + HeartbeatMonitor::PeerTimeoutUs));
	assert(monitor.age_us(2600000) == 600000);
	// A fresh beat brings it back.
	const Frame c = beat(1, 3, 2, 700);
	assert(monitor.receive(c.bytes, EntrySize, 2700000) == Error::None && monitor.alive(2700000));
}

static void epoch_change_resets_session()
{
	HeartbeatMonitor monitor(false);
	monitor.session(true, 5);
	monitor.next_frame(100, 0, 0);
	monitor.next_frame(200000, 0, 0);
	assert(monitor.sequence() == 2);
	const Frame b = beat(0, 5, 9, 1);
	assert(monitor.receive(b.bytes, EntrySize, 300) == Error::None);

	assert(monitor.session(true, 6));
	assert(monitor.sequence() == 0 && !monitor.alive(300) && monitor.counters().sessions == 2);
	// Old-epoch frame rejected, new epoch accepted from sequence 1.
	assert(monitor.receive(b.bytes, EntrySize, 400) == Error::Epoch);
	const Frame c = beat(0, 6, 1, 2);
	assert(monitor.receive(c.bytes, EntrySize, 400) == Error::None);
	const Frame first = monitor.next_frame(500, 0, 0);
	assert(read32(first.bytes + 12) == 1 && read32(first.bytes + 16) == 6);

	// Offline: nothing due, every frame rejected.
	assert(monitor.session(false, 6) && monitor.epoch() == 0);
	assert(!monitor.send_due(10000000));
	assert(monitor.receive(c.bytes, EntrySize, 500) == Error::Epoch);
	assert(monitor.counters().rejects[uint8_t(Error::Epoch)] == 2);
}

static void stale_restart_and_other_types()
{
	HeartbeatMonitor monitor(true);
	monitor.session(true, 4);
	const Frame b5 = beat(1, 4, 5, 5000);
	assert(monitor.receive(b5.bytes, EntrySize, 10) == Error::None);
	// Replay of the same sequence is stale and does not refresh liveness.
	assert(monitor.receive(b5.bytes, EntrySize, 600000) == Error::Sequence);
	assert(monitor.counters().rx_stale == 1 && !monitor.alive(600000));
	// A reloaded responder restarts at sequence 1 with a smaller uptime.
	const Frame restart = beat(1, 4, 1, 20);
	assert(monitor.receive(restart.bytes, EntrySize, 700000) == Error::None);
	assert(monitor.counters().peer_restarts == 1 && monitor.peer().sequence == 1 && monitor.alive(700000));
	// An older frame far from a restart is stale even with a lower uptime.
	const Frame b50 = beat(1, 4, 50, 3000);
	const Frame b40 = beat(1, 4, 40, 2000);
	assert(monitor.receive(b50.bytes, EntrySize, 710000) == Error::None);
	assert(monitor.receive(b40.bytes, EntrySize, 720000) == Error::Sequence);
	assert(monitor.counters().rx_stale == 2 && monitor.peer().sequence == 50);

	// A valid non-heartbeat frame from the peer is counted and ignored.
	Status status{};
	Context context{};
	context.source = 1;
	context.epoch = 4;
	context.sequence = 2;
	const Frame s = encode(status, context);

	if (validate(s.bytes, EntrySize, 1, 4) == Error::None) {
		assert(monitor.receive(s.bytes, EntrySize, 800000) == Error::None);
		assert(monitor.counters().rx_ignored == 1 && monitor.peer().sequence == 50);
	}

	// Corruption is rejected by CRC.
	Frame bad = beat(1, 4, 9, 30000);
	bad.bytes[37] ^= 0x40;
	assert(monitor.receive(bad.bytes, EntrySize, 900000) == Error::Crc);
	assert(monitor.receive(bad.bytes, 10, 900000) == Error::Length);
}

static void recovery_rate_limit()
{
	HeartbeatMonitor initiator(true), responder(false);
	assert(!responder.recover_due(0) && !responder.recover_due(5000000));
	assert(initiator.recover_due(0));
	assert(!initiator.recover_due(HeartbeatMonitor::RecoverPeriodUs - 1));
	assert(initiator.recover_due(HeartbeatMonitor::RecoverPeriodUs));
	initiator.session(true, 2);
	assert(!initiator.recover_due(10 * HeartbeatMonitor::RecoverPeriodUs));
	initiator.session(false, 2);
	assert(initiator.recover_due(10 * HeartbeatMonitor::RecoverPeriodUs));
	assert(initiator.counters().recover_requests == 3);
}

static void responder_replies_once_and_resets_with_session()
{
	HeartbeatMonitor responder(false);
	responder.session(true, 8);
	assert(!responder.send_due(0));
	// A burst of beats drained in one loop yields one reply.
	const Frame b1 = beat(0, 8, 1, 10), b2 = beat(0, 8, 2, 20);
	assert(responder.receive(b1.bytes, EntrySize, 100) == Error::None);
	assert(responder.receive(b2.bytes, EntrySize, 110) == Error::None);
	assert(responder.send_due(120));
	responder.next_frame(120, 0, 0);
	assert(!responder.send_due(130));
	// A rejected or stale beat does not ask for a reply.
	assert(responder.receive(b2.bytes, EntrySize, 140) == Error::Sequence && !responder.send_due(150));
	// A session change drops a pending reply.
	const Frame b3 = beat(0, 8, 3, 30);
	assert(responder.receive(b3.bytes, EntrySize, 160) == Error::None && responder.send_due(170));
	responder.session(true, 9);
	assert(!responder.send_due(180));
}

static void counter_limit_stops_sending()
{
	HeartbeatMonitor monitor(true);
	monitor.session(true, 1);
	uint64_t now = 1;

	for (uint32_t i = 0; i < 4; ++i, now += HeartbeatMonitor::TxPeriodUs) { monitor.next_frame(now, 0, 0); }

	assert(monitor.send_due(now));
	assert(strcmp(error_name(Error::Crc), "crc") == 0 && strcmp(error_name(Error::Semantic), "semantic") == 0);
}

static void ping_and_say_ride_the_existing_slots()
{
	HeartbeatMonitor cr8_0(true), cr8_1(false);
	cr8_0.session(true, 7);
	cr8_1.session(true, 7);
	assert(!cr8_0.queue_text(0, "x"));
	uint64_t now = 1000000;
	TextMessage message{};
	uint64_t rtt = 0;

	// CR8-0 pings: the request replaces its next beat; CR8-1 replies at once.
	assert(cr8_0.queue_text(1, "ping from CR8-0") && cr8_0.send_due(now));
	Frame a = cr8_0.next_frame(now, 1, 1);
	assert(a.bytes[6] == uint8_t(Type::Text) && validate(a.bytes, EntrySize, 0, 7) == Error::None);
	assert(cr8_1.receive(a.bytes, EntrySize, now + 3000) == Error::None);
	assert(cr8_1.take_request(message) && message.kind == TextKind::Request && message.id == 1);
	assert(!strcmp(message.text, "ping from CR8-0") && !cr8_1.take_request(message));
	assert(cr8_1.send_due(now + 3000));
	Frame b = cr8_1.next_frame(now + 3000, 1, 1);
	assert(b.bytes[6] == uint8_t(Type::Text) && validate(b.bytes, EntrySize, 1, 7) == Error::None);
	assert(cr8_0.receive(b.bytes, EntrySize, now + 4500) == Error::None);
	assert(cr8_0.take_reply(message, rtt) && message.kind == TextKind::Reply && message.id == 1);
	assert(!strcmp(message.text, "hello from CR8-1") && rtt == 4500 && !cr8_0.take_reply(message, rtt));
	// A late duplicate reply no longer matches.
	assert(cr8_0.receive(b.bytes, EntrySize, now + 5000) == Error::Sequence);
	// Heartbeats resume; the responder still only replies.
	now += HeartbeatMonitor::TxPeriodUs;
	a = cr8_0.next_frame(now, 2, 2);
	assert(a.bytes[6] == uint8_t(Type::Heartbeat) && !cr8_1.send_due(now));

	// CR8-1 says hello: its request waits for its reply slot, never a timer.
	assert(cr8_1.queue_text(5, "hello CR8-0") && !cr8_1.send_due(now + 50000));
	assert(cr8_1.receive(a.bytes, EntrySize, now) == Error::None && cr8_1.send_due(now));
	b = cr8_1.next_frame(now + 1000, 2, 2);
	assert(b.bytes[6] == uint8_t(Type::Text));
	assert(cr8_0.receive(b.bytes, EntrySize, now + 2000) == Error::None);
	assert(cr8_0.take_request(message) && message.id == 5 && !strcmp(message.text, "hello CR8-0"));
	// CR8-0 answers in its next timer slot, not immediately.
	assert(!cr8_0.send_due(now + 50000) && cr8_0.send_due(now + HeartbeatMonitor::TxPeriodUs));
	now += HeartbeatMonitor::TxPeriodUs;
	a = cr8_0.next_frame(now, 3, 3);
	assert(a.bytes[6] == uint8_t(Type::Text));
	assert(cr8_1.receive(a.bytes, EntrySize, now + 500) == Error::None);
	assert(cr8_1.take_reply(message, rtt) && message.id == 5 && !strcmp(message.text, "hello from CR8-0"));
	assert(rtt == now + 500 - (now - HeartbeatMonitor::TxPeriodUs + 1000));
	// The responder replies to the initiator's text frame with a heartbeat.
	assert(cr8_1.send_due(now + 500));
	b = cr8_1.next_frame(now + 500, 3, 3);
	assert(b.bytes[6] == uint8_t(Type::Heartbeat));
	assert(cr8_0.counters().tx_text == 2 && cr8_0.counters().rx_text == 2);
	assert(cr8_1.counters().tx_text == 2 && cr8_1.counters().rx_text == 2);

	// A queued request is dropped with the session; its late reply is stale.
	assert(cr8_0.queue_text(9, "lost"));
	cr8_0.session(true, 8);
	assert(cr8_0.next_frame(now, 0, 0).bytes[6] == uint8_t(Type::Heartbeat));
}

int main()
{
	roles();
	exchange_both_directions();
	loss_after_timeout();
	epoch_change_resets_session();
	stale_restart_and_other_types();
	recovery_rate_limit();
	responder_replies_once_and_resets_with_session();
	counter_limit_stops_sending();
	ping_and_say_ride_the_existing_slots();
	puts("ipc heartbeat monitor: ok");
	return 0;
}
