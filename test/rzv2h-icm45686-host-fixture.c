/* Scenario-driven host fixture for the RZ/V2H ICM-45686 FIFO diagnostic.
 *
 * The real helper and command sources are compiled in this translation unit
 * against a register-level sensor model: a 128-byte bank-0 register file,
 * soft-reset behaviour, the double-read FIFO count, a 6400 Hz packet
 * producer driven by a fake monotonic clock, and per-frame traffic checks
 * (one SPI exchange per lock, never longer than 241 bytes).
 */
#include "rzv2h-icm45686-host-stubs.h"
#include "icm45686-spi-under-test.c"
#include "icm45686-test-under-test.c"

#define NS_PER_MS 1000000ull
#define HEADER_OK 0x78 /* ACCEL | GYRO | HDR_20 | TMST_ODR */
#define INTF_SAVED 0x15
#define DRIVE_SAVED 0x2a
#define MAX_LOG 8192

struct write_log_s { uint8_t reg, value; uint64_t ns; };

static struct spi_dev_s controller = {0};
static struct spi_dev_s *published = &controller;
static uint8_t regs[128];
static bool locked, selected, in_critical;
static unsigned int locks, unlocks, exchanges, writes, frame_exchanges;
static unsigned int fail_lock_at, fail_unlock_at;
static int lock_error = -EIO, unlock_error = -EIO, board_init_error;
static uint32_t actual_frequency = 8000000;
static size_t max_len, last_len;
static uint8_t last_tx[ICM45686_MAX_TRANSFER];
static struct write_log_s write_log[MAX_LOG];
static unsigned int write_count;

/* Clock: usleep and each exchange advance it. */
static uint64_t now_ns = 1000 * NS_PER_MS;
static uint64_t exchange_ns = 2000;

/* Sensor model state. */
static uint8_t identity = ICM45686_WHOAMI;
static unsigned int reset_busy_polls = 3, reset_polls_left;
static bool reset_done, reset_never_clears, suppress_reset_done;
static int stuck_reg = -1, stuck_shutdown_reg = -1;
static bool fifo_running, fifo_ever_ran, trickle;
static uint64_t fifo_start_ns, produced_extra;
static unsigned int consumed, bad_index = UINT32_MAX;
static bool producer_off, force_full_status;
static int forced_count = -1, stale_count = 0;
static unsigned int count_reads;

/* Post-reset values with every configured field nonzero, so each
 * read-modify-write must clear as well as set; the interface and drive
 * overrides reset to zero so only the restore sequence brings them back.
 */
static void load_reset_defaults(void)
{
	memset(regs, 0, sizeof(regs));
	regs[ICM45686_ACCEL_CONFIG0] = 0x66;
	regs[ICM45686_GYRO_CONFIG0] = 0x96;
	regs[ICM45686_FIFO_CONFIG0] = 0x07;
	regs[ICM45686_FIFO_CONFIG3] = 0x31;
	regs[ICM45686_FIFO_CONFIG4] = 0x04;
	regs[ICM45686_RTC_CONFIG] = 0x23;
}

static void reset_model(void)
{
	load_reset_defaults();
	regs[ICM45686_INTF_CONFIG1_OVRD] = INTF_SAVED;
	regs[ICM45686_DRIVE_CONFIG0] = DRIVE_SAVED;
	fifo_ever_ran = false;
	locks = unlocks = exchanges = writes = write_count = 0;
	max_len = last_len = 0;
	fifo_running = false;
	consumed = 0;
	count_reads = 0;
}

static void encode_axis(uint8_t *packet, unsigned int lo, unsigned int nib,
                        bool high_nibble, int32_t value)
{
	int32_t low = value & 0x0f; /* two's complement host */
	int32_t high = (value - low) / 16;
	uint16_t raw = (uint16_t)high;

	packet[lo] = raw & 0xff;
	packet[lo + 1] = raw >> 8;
	packet[nib] |= high_nibble ? (uint8_t)(low << 4) : (uint8_t)low;
}

static int32_t axis_value(unsigned int index, unsigned int axis)
{
	/* Spread across the full signed 20-bit range, skipping the sentinel. */
	int32_t v = (int32_t)((index * 7919u + axis * 104729u) % 1048575u)
	            - 524287;
	return v;
}

static void make_packet(uint8_t *packet, unsigned int index)
{
	memset(packet, 0, ICM45686_PACKET_SIZE);
	packet[0] = index == bad_index ? 0x7a : HEADER_OK;
	for (unsigned int a = 0; a < 3; a++) {
		encode_axis(packet, 1 + 2 * a, 17 + a, true, axis_value(index, a));
		encode_axis(packet, 7 + 2 * a, 17 + a, false,
		            axis_value(index, a + 3));
	}
	packet[13] = (uint8_t)index;
	packet[14] = 0x01;
	packet[15] = (uint8_t)(index * 3);
	packet[16] = (uint8_t)((index * 3) >> 8);
}

static unsigned int fifo_available(bool *full)
{
	uint64_t produced;

	*full = false;
	if (!fifo_running || producer_off) {
		return 0;
	}
	produced = (now_ns - fifo_start_ns) * 6400 / 1000000000ull + produced_extra;
	if (trickle && produced > consumed + 1) {
		produced = consumed + 1; /* at most one packet per count */
	}
	if (produced - consumed >= ICM45686_FIFO_CAPACITY) {
		*full = true; /* stop-on-full: count saturates at capacity */
		return ICM45686_FIFO_CAPACITY;
	}
	return (unsigned int)(produced - consumed);
}

static void update_fifo_state(void)
{
	bool running = (regs[ICM45686_FIFO_CONFIG3] & 0x01) != 0 &&
	               (regs[ICM45686_FIFO_CONFIG0] & 0xc0) == 0x80 &&
	               (regs[ICM45686_PWR_MGMT0] & 0x0f) == 0x0f;
	if (running && !fifo_running) {
		fifo_start_ns = now_ns;
		consumed = 0;
		fifo_ever_ran = true;
	}
	fifo_running = running;
}

static void sensor_write(uint8_t reg, uint8_t value)
{
	assert(write_count < MAX_LOG);
	write_log[write_count++] = (struct write_log_s){reg, value, now_ns};
	writes++;
	/* A shutdown-stuck register ignores writes only after the FIFO ran, so
	 * configuration succeeds and the failure lands in cleanup.
	 */
	if (reg == stuck_reg || (fifo_ever_ran && reg == stuck_shutdown_reg)) {
		return;
	}
	if (reg == ICM45686_REG_MISC2 && (value & ICM45686_MISC2_SOFT_RST)) {
		load_reset_defaults();
		regs[ICM45686_REG_MISC2] = ICM45686_MISC2_SOFT_RST;
		reset_polls_left = reset_busy_polls;
		reset_done = !suppress_reset_done;
		fifo_running = false;
		return;
	}
	regs[reg] = value;
	update_fifo_state();
}

static uint8_t sensor_read(uint8_t reg)
{
	bool full;

	if (reg == ICM45686_WHO_AM_I) {
		if (regs[ICM45686_REG_MISC2] & ICM45686_MISC2_SOFT_RST) {
			if (reset_polls_left > 0 || reset_never_clears) {
				if (reset_polls_left > 0) { reset_polls_left--; }
				return 0x00; /* not yet responsive */
			}
			regs[ICM45686_REG_MISC2] = 0;
		}
		return identity;
	}
	if (reg == ICM45686_INT1_STATUS0) {
		uint8_t status = 0;
		(void)fifo_available(&full);
		if (reset_done) { status |= ICM45686_INT1_RESET_DONE; }
		if (full || force_full_status) { status |= ICM45686_INT1_FIFO_FULL; }
		reset_done = false; /* read-to-clear */
		return status;
	}
	return regs[reg];
}

/* ---- NuttX boundary ---- */

irqstate_t enter_critical_section(void)
{
	assert(!in_critical);
	in_critical = true;
	return 0x5a;
}

void leave_critical_section(irqstate_t flags)
{
	assert(in_critical && flags == 0x5a);
	in_critical = false;
}

int board_spi_initialize(void) { return board_init_error; }

struct spi_dev_s *rzv_spibus_initialize(int port)
{
	assert(port == 0);
	return published;
}

int host_lock(struct spi_dev_s *dev, bool lock)
{
	assert(dev == &controller);
	if (lock) {
		assert(!locked);
		locks++;
		if (fail_lock_at && locks == fail_lock_at) { return lock_error; }
		locked = true;
		frame_exchanges = 0;
		return 0;
	}
	assert(locked);
	assert(frame_exchanges <= 1); /* one complete frame per lock */
	unlocks++;
	locked = false;
	if (fail_unlock_at && unlocks == fail_unlock_at) { return unlock_error; }
	return 0;
}

void host_mode(struct spi_dev_s *dev, int mode)
{
	assert(dev == &controller && locked && mode == SPIDEV_MODE3);
}

void host_bits(struct spi_dev_s *dev, int bits)
{
	assert(dev == &controller && locked && bits == 8);
}

uint32_t host_frequency(struct spi_dev_s *dev, uint32_t frequency)
{
	assert(dev == &controller && locked && frequency == ICM45686_FREQUENCY);
	return actual_frequency;
}

void host_select(struct spi_dev_s *dev, uint32_t id, bool active)
{
	assert(dev == &controller && locked);
	assert(id == SPIDEV_ACCELEROMETER(0));
	assert(selected != active);
	selected = active;
}

void host_exchange(struct spi_dev_s *dev, const void *txv, void *rxv,
                   size_t len)
{
	const uint8_t *tx = txv;
	uint8_t *rx = rxv;
	uint8_t reg = tx[0] & 0x7f;
	bool full;

	assert(dev == &controller && locked && selected && tx != NULL);
	assert(len >= 2 && len <= ICM45686_MAX_TRANSFER);
	frame_exchanges++;
	exchanges++;
	last_len = len;
	memcpy(last_tx, tx, len);
	if (len > max_len) { max_len = len; }
	now_ns += exchange_ns;

	if ((tx[0] & ICM45686_READ) == 0) {
		assert(len == 2 && rx == NULL);
		sensor_write(reg, tx[1]);
		return;
	}
	assert(rx != NULL);
	memset(rx, 0xa5, len);
	if (reg == ICM45686_FIFO_COUNT_0) {
		unsigned int value;
		assert(len == 3 && tx[1] == 0 && tx[2] == 0);
		count_reads++;
		if (count_reads % 2) {
			value = (unsigned int)stale_count; /* stale first read */
		} else if (forced_count >= 0) {
			value = (unsigned int)forced_count;
		} else {
			value = fifo_available(&full);
		}
		rx[1] = value & 0xff;
		rx[2] = (value >> 8) & 0xff;
		return;
	}
	if (reg == ICM45686_FIFO_DATA) {
		unsigned int n = (unsigned int)(len - 1) / ICM45686_PACKET_SIZE;
		assert((len - 1) % ICM45686_PACKET_SIZE == 0);
		for (size_t i = 1; i < len; i++) { assert(tx[i] == 0); }
		assert(n <= fifo_available(&full));
		for (unsigned int i = 0; i < n; i++) {
			make_packet(rx + 1 + i * ICM45686_PACKET_SIZE, consumed++);
		}
		return;
	}
	assert(len == 2);
	rx[1] = sensor_read(reg);
}

int host_clock_gettime(clockid_t clock, struct timespec *now)
{
	assert(clock == CLOCK_MONOTONIC && now != NULL);
	now->tv_sec = (time_t)(now_ns / 1000000000ull);
	now->tv_nsec = (long)(now_ns % 1000000000ull);
	return 0;
}

int host_usleep(useconds_t usec)
{
	now_ns += (uint64_t)usec * 1000;
	return 0;
}

/* ---- helpers ---- */

static int run_command(int argc, const char *a1, const char *a2)
{
	char name[] = "icm45686_test";
	char arg1[32], arg2[32];
	char *argv[4] = {name, NULL, NULL, NULL};

	if (argc > 1) { snprintf(arg1, sizeof(arg1), "%s", a1); argv[1] = arg1; }
	if (argc > 2) { snprintf(arg2, sizeof(arg2), "%s", a2); argv[2] = arg2; }
	return rzv2h_icm45686_main(argc, argv);
}

static const struct write_log_s *last_write_of(uint8_t reg)
{
	for (unsigned int i = write_count; i > 0; i--) {
		if (write_log[i - 1].reg == reg) { return &write_log[i - 1]; }
	}
	return NULL;
}

static void assert_bus_idle(void)
{
	assert(!locked && !selected && !in_critical);
	assert(max_len <= ICM45686_MAX_TRANSFER);
	assert(!g_busy);
}

static void assert_shutdown_state(void)
{
	assert((regs[ICM45686_FIFO_CONFIG3] & ICM45686_FIFO3_ALL) == 0);
	assert((regs[ICM45686_FIFO_CONFIG0] & ICM45686_FIFO_MODE_MASK) == 0);
	assert((regs[ICM45686_PWR_MGMT0] & ICM45686_PWR_LOW_NOISE) == 0);
	assert(!fifo_running);
}

/* ---- scenarios ---- */

static void scenario_decode(void)
{
	struct icm45686_sample_s s, keep;
	uint8_t p[ICM45686_PACKET_SIZE];
	static const uint8_t bad_headers[] = {
		0xf8, 0x38, 0x58, 0x68, 0x74, 0x7c, 0x70, 0x79, 0x7a, 0x7b, 0x80,
	};

	memset(p, 0, sizeof(p));
	p[0] = HEADER_OK;
	assert(icm45686_decode(p, &s) == 0);
	for (int a = 0; a < 3; a++) { assert(s.accel[a] == 0 && s.gyro[a] == 0); }
	assert(s.temperature == 0 && s.timestamp == 0);

	/* Extremes: +524287 and -524287 (0x80000 is the invalid sentinel). */
	memset(p, 0, sizeof(p));
	p[0] = HEADER_OK;
	encode_axis(p, 1, 17, true, 524287);
	encode_axis(p, 7, 17, false, -524287);
	encode_axis(p, 3, 18, true, -1);
	encode_axis(p, 9, 18, false, -1);
	assert(p[1] == 0xff && p[2] == 0x7f && p[7] == 0x00 && p[8] == 0x80);
	assert(p[17] == 0xf1 && p[18] == 0xff);
	assert(icm45686_decode(p, &s) == 0);
	assert(s.accel[0] == 524287 && s.gyro[0] == -524287);
	assert(s.accel[1] == -1 && s.gyro[1] == -1);

	/* Nibble ownership: accel = high nibble, gyro = low nibble. */
	memset(p, 0, sizeof(p));
	p[0] = HEADER_OK;
	p[17] = 0xa5;
	p[19] = 0x3c;
	assert(icm45686_decode(p, &s) == 0);
	assert(s.accel[0] == 10 && s.gyro[0] == 5);
	assert(s.accel[2] == 3 && s.gyro[2] == 12);

	/* Endian trap: low byte first for axes, temperature and timestamp. */
	memset(p, 0, sizeof(p));
	p[0] = HEADER_OK;
	p[1] = 0x34; p[2] = 0x12;
	p[11] = 0x01; p[12] = 0x80;
	p[13] = 0xff; p[14] = 0x7f;
	p[15] = 0x34; p[16] = 0x12;
	assert(icm45686_decode(p, &s) == 0);
	assert(s.accel[0] == 0x1234 * 16);
	assert(s.gyro[2] == (0x8001 - 0x10000) * 16);
	assert(s.temperature == 32767 && s.timestamp == 0x1234);

	/* Sentinels and header faults leave the output untouched. */
	memset(&keep, 0x6b, sizeof(keep));
	for (unsigned int i = 0; i < 7; i++) {
		memset(p, 0, sizeof(p));
		p[0] = HEADER_OK;
		if (i < 6) {
			unsigned int lo = i < 3 ? 1 + 2 * i : 7 + 2 * (i - 3);
			p[lo + 1] = 0x80; /* -32768 * 16 + 0 = -524288 */
		} else {
			p[14] = 0x80; /* temperature -32768 */
		}
		s = keep;
		assert(icm45686_decode(p, &s) == -ENODATA);
		assert(!memcmp(&s, &keep, sizeof(s)));
	}
	memset(p, 0, sizeof(p));
	p[0] = HEADER_OK;
	p[2] = 0x80; p[17] = 0x10; /* -524287 accel is valid */
	assert(icm45686_decode(p, &s) == 0 && s.accel[0] == -524287);
	for (unsigned int i = 0; i < sizeof(bad_headers); i++) {
		memset(p, 0, sizeof(p));
		p[0] = bad_headers[i];
		s = keep;
		assert(icm45686_decode(p, &s) == -EPROTO);
		assert(!memcmp(&s, &keep, sizeof(s)));
	}
	assert(icm45686_decode(NULL, &s) == -EINVAL);
	assert(icm45686_decode(p, NULL) == -EINVAL);

	/* Model packets round-trip through the decoder. */
	for (unsigned int i = 0; i < 2000; i++) {
		make_packet(p, i);
		assert(icm45686_decode(p, &s) == 0);
		for (unsigned int a = 0; a < 3; a++) {
			assert(s.accel[a] == axis_value(i, a));
			assert(s.gyro[a] == axis_value(i, a + 3));
		}
	}
}

static void scenario_fifo_count(void)
{
	static const int values[] = {0, 1, 12, 13, 0x0102, 408};
	unsigned int count;

	reset_model();
	for (unsigned int i = 0; i < sizeof(values) / sizeof(values[0]); i++) {
		forced_count = values[i];
		stale_count = 0x0155; /* would be rejected if the first read won */
		count = 0xdead;
		assert(icm45686_fifo_count(&controller, &count) == 0);
		assert(count == (unsigned int)values[i]);
	}
	assert(exchanges == 6 * 3);

	/* Capacity and the FIFO_FULL status bit both mean overflow. */
	stale_count = 0;
	forced_count = 409;
	count = 77;
	assert(icm45686_fifo_count(&controller, &count) == -EOVERFLOW);
	assert(count == 77);
	forced_count = 0xffff;
	assert(icm45686_fifo_count(&controller, &count) == -EOVERFLOW);
	forced_count = 5;
	force_full_status = true;
	assert(icm45686_fifo_count(&controller, &count) == -EOVERFLOW);
	assert(count == 77);
	force_full_status = false;
	assert(icm45686_fifo_count(&controller, NULL) == -EINVAL);
	forced_count = -1;
	assert_bus_idle();
}

static void scenario_lengths(void)
{
	uint8_t packets[13 * ICM45686_PACKET_SIZE];
	uint8_t value = 0;

	reset_model();
	assert(icm45686_read(&controller, ICM45686_WHO_AM_I, &value) == 0);
	assert(value == ICM45686_WHOAMI && last_len == 2 && last_tx[0] == 0xf2);
	assert(icm45686_write(&controller, ICM45686_RTC_CONFIG, 0x5c) == 0);
	assert(last_len == 2 && last_tx[0] == 0x26 && last_tx[1] == 0x5c);

	produced_extra = 100;
	fifo_running = true;
	fifo_start_ns = now_ns;
	assert(icm45686_fifo_read(&controller, packets, 1) == 0);
	assert(last_len == 21 && last_tx[0] == 0x94);
	assert(icm45686_fifo_read(&controller, packets, 12) == 0);
	assert(last_len == 241 && max_len == 241);
	assert(packets[0] == HEADER_OK && packets[11 * 20] == HEADER_OK);
	unsigned int before = exchanges;
	assert(icm45686_fifo_read(&controller, packets, 13) == -EINVAL);
	assert(icm45686_fifo_read(&controller, packets, 0) == -EINVAL);
	assert(icm45686_fifo_read(&controller, NULL, 1) == -EINVAL);
	assert(exchanges == before);
	produced_extra = 0;
	fifo_running = false;
	assert_bus_idle();
}

static void scenario_invalid(void)
{
	uint8_t tx[ICM45686_MAX_TRANSFER + 1] = {0x80};
	uint8_t value = 0x33;

	reset_model();
	assert(icm45686_transfer(NULL, tx, NULL, 2) == -EINVAL);
	assert(icm45686_transfer(&controller, NULL, NULL, 2) == -EINVAL);
	assert(icm45686_transfer(&controller, tx, NULL, 0) == -EINVAL);
	assert(icm45686_transfer(&controller, tx, NULL, 242) == -EINVAL);
	assert(icm45686_read(&controller, 0x80, &value) == -EINVAL);
	assert(icm45686_read(&controller, 0x10, NULL) == -EINVAL);
	assert(icm45686_write(&controller, 0x90, 1) == -EINVAL);
	assert(icm45686_modify(&controller, 0x10, 0x03, 0x01) == -EINVAL);
	assert(icm45686_configure(&controller, NULL) == -EINVAL);
	assert(value == 0x33 && locks == 0 && exchanges == 0);
}

static void scenario_frequency(void)
{
	static const uint32_t rejected[] = {0, 1999999, 24000001, 50000000};
	static const uint32_t accepted[] = {2000000, 8000000, 12500000, 24000000};
	uint8_t value;

	reset_model();
	for (unsigned int i = 0; i < 4; i++) {
		actual_frequency = rejected[i];
		value = 0x44;
		assert(icm45686_read(&controller, ICM45686_WHO_AM_I, &value)
		       == -ERANGE);
		assert(value == 0x44 && exchanges == 0);
		assert(locks == i + 1 && unlocks == i + 1);
	}
	for (unsigned int i = 0; i < 4; i++) {
		actual_frequency = accepted[i];
		assert(icm45686_read(&controller, ICM45686_WHO_AM_I, &value) == 0);
		assert(value == ICM45686_WHOAMI);
	}
	assert(exchanges == 4);
	actual_frequency = 8000000;
	assert_bus_idle();
}

static void scenario_lock(void)
{
	uint8_t value = 0x44;

	reset_model();
	fail_lock_at = 1;
	assert(icm45686_read(&controller, ICM45686_WHO_AM_I, &value) == -EIO);
	assert(value == 0x44 && exchanges == 0 && unlocks == 0);
	fail_lock_at = 0;

	/* Unlock failure after a completed frame is reported and the read
	 * buffer is not published.
	 */
	reset_model();
	fail_unlock_at = 1;
	unlock_error = -EPERM;
	assert(icm45686_read(&controller, ICM45686_WHO_AM_I, &value) == -EPERM);
	assert(value == 0x44 && exchanges == 1);
	fail_unlock_at = 0;

	/* ERANGE wins over a later unlock error. */
	reset_model();
	actual_frequency = 1;
	fail_unlock_at = 1;
	assert(icm45686_read(&controller, ICM45686_WHO_AM_I, &value) == -ERANGE);
	actual_frequency = 8000000;
	fail_unlock_at = 0;
	unlock_error = -EIO;
	assert_bus_idle();
}

static void check_configured_sequence(void)
{
	const struct write_log_s *pwr = NULL, *ifen = NULL, *stop = NULL;
	const struct write_log_s *reset = NULL, *drive = NULL, *intf = NULL;

	for (unsigned int i = 0; i < write_count; i++) {
		const struct write_log_s *w = &write_log[i];
		if (!reset && w->reg == ICM45686_REG_MISC2) { reset = w; }
		if (reset && !drive && w->reg == ICM45686_DRIVE_CONFIG0) { drive = w; }
		if (reset && !intf && w->reg == ICM45686_INTF_CONFIG1_OVRD) { intf = w; }
		if (!pwr && w->reg == ICM45686_PWR_MGMT0 && w->value == 0x0f) { pwr = w; }
		if (!stop && w->reg == ICM45686_FIFO_CONFIG0 && (w->value & 0xc0) == 0x80) {
			stop = w;
		}
		if (!ifen && w->reg == ICM45686_FIFO_CONFIG3 && (w->value & 0x01)) {
			ifen = w;
		}
	}
	/* Reset first; restore drive before interface, with saved values. */
	assert(write_log[0].reg == ICM45686_REG_MISC2 &&
	       write_log[0].value == ICM45686_MISC2_SOFT_RST);
	assert(drive && intf && drive < intf);
	assert(drive->value == DRIVE_SAVED && intf->value == INTF_SAVED);
	/* Power and 30 ms settle precede stop-on-full and FIFO enable. */
	assert(pwr && stop && ifen && pwr < stop && stop < ifen);
	assert(stop->ns - pwr->ns >= ICM45686_STARTUP_US * 1000ull);
}

static void scenario_run(unsigned int count, const char *arg)
{
	reset_model();
	assert(run_command(arg ? 2 : 1, arg, NULL) == 0);
	assert(consumed == count);
	assert(max_len <= ICM45686_MAX_TRANSFER);
	check_configured_sequence();
	/* Configuration observed before shutdown. */
	assert(regs[ICM45686_ACCEL_CONFIG0] == ICM45686_ACCEL_32G_6400HZ);
	assert(regs[ICM45686_GYRO_CONFIG0] == ICM45686_GYRO_4000_6400HZ);
	assert((regs[ICM45686_FIFO_CONFIG4] & 0x06) == ICM45686_FIFO4_TMST_EN);
	assert((regs[ICM45686_RTC_CONFIG] & ICM45686_RTC_MODE) == 0);
	assert((regs[ICM45686_FIFO_CONFIG0] & 0x3f) == ICM45686_FIFO_DEPTH_8K);
	assert_shutdown_state();
	assert_bus_idle();
}

static void scenario_success(void)
{
	scenario_run(10, NULL);
	scenario_run(1, "1");
	scenario_run(20, "20");
	scenario_run(20, "20"); /* repeated invocation re-runs from reset */
	scenario_run(1000, "1000");
}

static void scenario_identity(void)
{
	reset_model();
	identity = 0xe5;
	assert(run_command(2, "5", NULL) == -ENODEV);
	assert(writes == 0 && exchanges == 1);
	identity = ICM45686_WHOAMI;
	assert_bus_idle();

	reset_model();
	fail_lock_at = 1;
	assert(run_command(2, "5", NULL) == -EIO);
	assert(writes == 0 && exchanges == 0);
	fail_lock_at = 0;
	assert_bus_idle();

	reset_model();
	board_init_error = -EIO;
	assert(run_command(1, NULL, NULL) == -EIO && locks == 0);
	board_init_error = 0;
	published = NULL;
	assert(run_command(1, NULL, NULL) == -ENODEV && locks == 0);
	published = &controller;
	assert_bus_idle();
}

static void scenario_reset_failures(void)
{
	/* Soft reset never completes: bounded at 1 s, then cleanup runs. */
	reset_model();
	reset_never_clears = true;
	uint64_t start = now_ns;
	assert(run_command(2, "5", NULL) == -ETIMEDOUT);
	assert(now_ns - start >= ICM45686_RESET_TIMEOUT_MS * NS_PER_MS);
	assert(now_ns - start < 1200 * NS_PER_MS);
	reset_never_clears = false;
	assert(last_write_of(ICM45686_PWR_MGMT0) != NULL);
	assert_bus_idle();

	/* Missing RESET_DONE status. */
	reset_model();
	suppress_reset_done = true;
	assert(run_command(2, "5", NULL) == -EIO);
	suppress_reset_done = false;
	assert_shutdown_state();
	assert_bus_idle();

	/* Readback mismatch of a configuration register. */
	reset_model();
	stuck_reg = ICM45686_GYRO_CONFIG0;
	assert(run_command(2, "5", NULL) == -EIO);
	stuck_reg = -1;
	assert(consumed == 0);
	assert_shutdown_state();
	assert_bus_idle();
}

static void scenario_deadlines(void)
{
	/* No packets: 500 ms no-progress deadline. */
	reset_model();
	producer_off = true;
	uint64_t start = now_ns;
	assert(run_command(2, "5", NULL) == -ETIMEDOUT);
	uint64_t elapsed = now_ns - start;
	assert(elapsed >= (500 + 30) * NS_PER_MS && elapsed < 700 * NS_PER_MS);
	producer_off = false;
	assert(consumed == 0);
	assert_shutdown_state();
	assert_bus_idle();

	/* Slow progress: one packet per 160 ms loop (four 40 ms frames) keeps
	 * resetting the 500 ms window, so only the 2 s cap ends the run.
	 */
	reset_model();
	trickle = true;
	exchange_ns = 40 * NS_PER_MS;
	assert(run_command(2, "1000", NULL) == -ETIMEDOUT);
	exchange_ns = 2000;
	trickle = false;
	assert(consumed >= 10 && consumed <= 14);
	assert_shutdown_state();
	assert_bus_idle();
}

static void scenario_overflow_and_bad_packet(void)
{
	reset_model();
	produced_extra = 500; /* FIFO already full when first counted */
	assert(run_command(2, "5", NULL) == -EOVERFLOW);
	produced_extra = 0;
	assert(consumed == 0);
	assert_shutdown_state();
	assert_bus_idle();

	reset_model();
	bad_index = 7;
	assert(run_command(2, "20", NULL) == -EPROTO);
	bad_index = UINT32_MAX;
	assert(consumed >= 8);
	assert_shutdown_state();
	assert_bus_idle();
}

static void scenario_cleanup(void)
{
	/* Success followed by a failing cleanup step returns that error, and
	 * every later shutdown step is still attempted.
	 */
	reset_model();
	stuck_shutdown_reg = ICM45686_FIFO_CONFIG0;
	assert(run_command(2, "3", NULL) == -EIO);
	assert(consumed == 3);
	assert((regs[ICM45686_FIFO_CONFIG0] & ICM45686_FIFO_MODE_MASK) != 0);
	assert((regs[ICM45686_FIFO_CONFIG3] & ICM45686_FIFO3_ALL) == 0);
	assert((regs[ICM45686_PWR_MGMT0] & ICM45686_PWR_LOW_NOISE) == 0);
	assert_bus_idle();

	/* A primary acquisition error is preserved over a cleanup error. */
	reset_model();
	stuck_shutdown_reg = ICM45686_PWR_MGMT0;
	producer_off = true;
	assert(run_command(2, "3", NULL) == -ETIMEDOUT);
	producer_off = false;
	stuck_shutdown_reg = -1;
	assert_bus_idle();
}

static void scenario_busy(void)
{
	reset_model();
	g_busy = true;
	assert(run_command(1, NULL, NULL) == -EBUSY);
	assert(locks == 0);
	assert(g_busy);
	g_busy = false;
	assert(run_command(2, "2", NULL) == 0);
	assert(run_command(2, "2", NULL) == 0);
	assert_bus_idle();
}

static void scenario_cli(void)
{
	static const char *const invalid[] = {
		"0", "1001", "abc", "", "-1", "+5", "1e3", "12a", "4294967297",
		"99999999999999999999",
	};
	unsigned int count;

	reset_model();
	for (unsigned int i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
		assert(run_command(2, invalid[i], NULL) == -EINVAL);
	}
	assert(run_command(3, "5", "5") == -EINVAL);
	assert(locks == 0 && !g_busy);

	char name[] = "x", one[] = "1", max[] = "1000", padded[] = "0007";
	char *argv1[] = {name, NULL};
	char *argv2[] = {name, one, NULL};
	char *argv3[] = {name, max, NULL};
	char *argv4[] = {name, padded, NULL};
	char *argv5[] = {name, NULL, NULL};
	assert(icm45686_parse_count(1, argv1, &count) == 0 && count == 10);
	assert(icm45686_parse_count(2, argv2, &count) == 0 && count == 1);
	assert(icm45686_parse_count(2, argv3, &count) == 0 && count == 1000);
	assert(icm45686_parse_count(2, argv4, &count) == 0 && count == 7);
	assert(icm45686_parse_count(2, argv5, &count) == -EINVAL);
	assert(icm45686_parse_count(2, NULL, &count) == -EINVAL);
}

static void scenario_elapsed(void)
{
	struct timespec a = {10, 999999999}, b = {11, 0}, c = {9, 0};
	struct timespec far = {(time_t)5000000000LL, 0}, zero = {0, 0};

	assert(icm45686_elapsed_ms(&a, &b) == 0);
	b.tv_nsec = 1000000;
	assert(icm45686_elapsed_ms(&a, &b) == 1);
	assert(icm45686_elapsed_ms(&a, &c) == 0);
	assert(icm45686_elapsed_ms(&zero, &far) == UINT32_MAX);
}

int main(int argc, char **argv)
{
	assert(argc == 2);
	const char *s = argv[1];

	if (!strcmp(s, "decode")) { scenario_decode(); }
	else if (!strcmp(s, "fifo-count")) { scenario_fifo_count(); }
	else if (!strcmp(s, "lengths")) { scenario_lengths(); }
	else if (!strcmp(s, "invalid")) { scenario_invalid(); }
	else if (!strcmp(s, "frequency")) { scenario_frequency(); }
	else if (!strcmp(s, "lock")) { scenario_lock(); }
	else if (!strcmp(s, "success")) { scenario_success(); }
	else if (!strcmp(s, "identity")) { scenario_identity(); }
	else if (!strcmp(s, "reset-failures")) { scenario_reset_failures(); }
	else if (!strcmp(s, "deadlines")) { scenario_deadlines(); }
	else if (!strcmp(s, "overflow-bad-packet")) {
		scenario_overflow_and_bad_packet();
	}
	else if (!strcmp(s, "cleanup")) { scenario_cleanup(); }
	else if (!strcmp(s, "busy")) { scenario_busy(); }
	else if (!strcmp(s, "cli")) { scenario_cli(); }
	else if (!strcmp(s, "elapsed")) { scenario_elapsed(); }
	else { fprintf(stderr, "unknown scenario %s\n", s); return 2; }
	puts("PASS");
	return 0;
}
