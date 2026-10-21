// SPDX-License-Identifier: BSD-3-Clause
#include <apps/battery.hpp>
#include <cassert>
#include <cstdio>
#include <cstring>

using namespace rzv2h::demo;

// Unit-test ICD only. These values are not installed or accepted hardware IDs.
static BatteryPolicy policy()
{
	BatteryPolicy p{};
	p.contract = 1; p.source = 3; p.maximum_age_us = 100000; p.transit_bound_us = 1000;
	p.minimum_voltage_mv = 10000; p.maximum_voltage_mv = 17000; p.maximum_current_ma = 100000;
	p.maximum_capacity_mah = 20000; p.cell_count = 4; p.healthy_state = 7;
	p.voltage = 1; p.current = 2; p.remaining = 4; p.cells = 8; p.warning = 16;
	p.temperature = 1; p.cell_range = 2; p.charge = 4; p.capacity = 8; p.faults = 16;
	p.required_base = p.voltage | p.current | p.remaining;

	for (unsigned i = 0; i < 5; ++i) { p.warning_values[i] = 20 + i; }

	return p;
}

int main(int argc, char *argv[])
{
	auto p = policy();
	assert(p.configured() && !BatteryPolicy{}.configured());
	BatteryBase b{};
	b.source = 3; b.valid = 31; b.generation = 1; b.age_us = 100; b.voltage_mv = 16000;
	b.current_ma = -1234; b.remaining_permille = 800; b.warning = 20; b.cells = 4; b.state = 7;
	BatteryDetail d{};
	d.source = 3; d.valid = 31; d.generation = 1; d.age_us = 200;
	d.temperature_centic = -1234; d.min_cell_mv = 3990; d.max_cell_mv = 4010;
	d.remaining_mah = 8000; d.capacity_mah = 10000;
	Context c{}; c.source = 1; c.epoch = 7; c.sequence = 1; c.publication_us = UINT64_MAX;

	if (argc > 1) {
		const Frame f = std::strcmp(argv[1], "--detail") == 0 ? encode(d, c) : encode(b, c);

		for (uint8_t byte : f.bytes) { std::printf("%02x", byte); }

		std::puts(""); return 0;
	}

	BatteryReceiver disabled(BatteryPolicy{});
	disabled.session(7);
	assert(!disabled.receive(encode(b, c), 1000) && !disabled.observation(1000).connected);
	BatteryReceiver r(p);
	r.session(7);
	assert(!r.observation(100).connected);
	assert(r.receive(encode(b, c), 1000));
	auto o = r.observation(1000);
	assert(o.connected && o.age_upper_us == 1100 && o.base.current_ma == -1234 && !o.detail_available);
	++c.sequence;
	assert(r.receive(encode(d, c), 1100));
	o = r.observation(1100);
	assert(o.connected && o.detail_available && o.detail.temperature_centic == -1234);
	BatteryThresholds thresholds{}; thresholds.low = 0.3f; thresholds.critical = 0.2f; thresholds.emergency = 0.1f;
	auto telemetry = battery_telemetry(o, p, thresholds);
	assert(telemetry.connected && telemetry.remaining > 0.79f && telemetry.remaining < 0.81f);
	assert(telemetry.current_a < -1.23f && telemetry.current_a > -1.24f && telemetry.temperature_c < -12.3f);
	assert(telemetry.capacity_mah == 10000 && telemetry.cells == 4 && !telemetry.warning);
	assert(!battery_telemetry(o, p, BatteryThresholds{}).connected);
	auto missing = o; missing.base.valid &= ~p.remaining;
	assert(!battery_telemetry(missing, p, thresholds).connected);
	auto low_sample = o; low_sample.base.remaining_permille = 50;
	assert(battery_telemetry(low_sample, p, thresholds).warning == 3);
	low_sample.base.remaining_permille = 250; low_sample.warning = 4;
	assert(battery_telemetry(low_sample, p, thresholds).warning == 4);

	// Transport/source clocks have arbitrary offsets. Only source age, qualified
	// transit bound and local elapsed time are used.
	for (unsigned i = 0; i < 10; ++i) {
		++c.sequence; c.publication_us = i;
		assert(r.receive(encode(b, c), 2000 + i * 10000));
	}

	assert(!r.observation(99900).connected); // first age+transit+local elapsed = 100000
	telemetry = battery_telemetry(r.observation(99900), p, thresholds);
	assert(!telemetry.connected && telemetry.voltage_v == 0 && telemetry.current_a == -1 && telemetry.remaining == -1);
	++b.generation; b.current_ma = 0; ++c.sequence;
	assert(r.receive(encode(b, c), 100000));
	o = r.observation(100000);
	assert(o.connected && o.base.current_ma == 0 && !o.detail_available);
	telemetry = battery_telemetry(o, p, thresholds);
	assert(telemetry.connected && telemetry.current_a == 0);
	++c.sequence;
	assert(!r.receive(encode(d, c), 100001)); // old detail never joins new base
	d.generation = b.generation; ++c.sequence;
	assert(r.receive(encode(d, c), 100002));
	++c.sequence; b.valid &= ~p.current;
	assert(r.receive(encode(b, c), 100003));
	assert(!r.observation(100003).connected); // invalidity revokes immediately
	++c.sequence; b.valid |= p.current;
	assert(!r.receive(encode(b, c), 100004)); // same generation cannot restore validity
	++b.generation; ++c.sequence;
	assert(r.receive(encode(b, c), 100005) && r.observation(100005).connected);
	++c.sequence; b.state = 8;
	assert(r.receive(encode(b, c), 100006) && !r.observation(100006).connected);
	++c.sequence; b.state = 7;
	assert(r.receive(encode(b, c), 100007) && !r.observation(100007).connected);
	++b.generation; ++c.sequence;
	assert(r.receive(encode(b, c), 100008) && r.observation(100008).connected);
	BatteryBase bad = b; bad.current_ma = INT32_MIN; ++c.sequence;
	assert(!r.receive(encode(bad, c), 100009));
	bad = b; bad.remaining_permille = 1001;
	assert(!r.receive(encode(bad, c), 100009));
	bad = b; bad.valid |= 0x8000;
	assert(!r.receive(encode(bad, c), 100009));
	bad = b; bad.source = 4;
	assert(!r.receive(encode(bad, c), 100009));
	bad = b; bad.warning = 0;
	assert(!r.receive(encode(bad, c), 100009));
	bad = b; ++bad.generation; bad.age_us = UINT32_MAX;
	assert(r.receive(encode(bad, c), 100009) && !r.observation(100009).connected);
	r.session(8); c.epoch = 7; ++c.sequence;
	assert(!r.receive(encode(b, c), 100010));
	c.epoch = 8;
	assert(r.receive(encode(b, c), 100011));
	assert(!r.observation(100010).connected); // clock regression latches
	++b.generation; ++c.sequence;
	assert(!r.receive(encode(b, c), 100012));
	r.session(9); c.epoch = 9;
	assert(r.receive(encode(b, c), UINT64_MAX - 1));
	assert(r.observation(UINT64_MAX).connected);
	r.session(10); c.epoch = 10;
	assert(r.receive(encode(b, c), 1));
	assert(!r.observation(UINT64_MAX).connected); // saturation, never overflow to fresh
	p.required_detail = p.temperature;
	BatteryReceiver complete(p); complete.session(10);
	assert(complete.receive(encode(b, c), 100));
	assert(!complete.observation(100).connected);
	d.generation = b.generation; ++c.sequence;
	assert(complete.receive(encode(d, c), 200) && complete.observation(200).connected);
	d.faults = 1; ++c.sequence;
	assert(complete.receive(encode(d, c), 300) && !complete.observation(300).connected);
	p.current = p.voltage; assert(!p.configured());
	p = policy(); p.transit_bound_us = 0; assert(!p.configured());
	// Fuzz the actual codec/receiver with valid CRCs and malformed semantics.
	r.session(11); uint32_t random = 0x1234abcd;

	for (unsigned i = 0; i < 100000; ++i) {
		c.epoch = 11; c.sequence = i + 1;
		Frame f = encode(b, c);
		random ^= random << 13; random ^= random >> 17; random ^= random << 5;
		f.bytes[32 + (random % 32)] ^= uint8_t(random >> 16);
		write16(f.bytes + 58, 0); finish(f);
		r.receive(f, i + 1);
	}

	return 0;
}
