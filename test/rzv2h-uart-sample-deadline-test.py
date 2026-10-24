#!/usr/bin/env python3
"""Run the production UART sample receiver against clock/poll/read boundaries.

The C function is extracted unchanged from the apps source. Scripted boundary
events advance a monotonic clock without sleeping or accessing a serial port.
"""

from dataclasses import dataclass
from pathlib import Path
import errno
import re
import select
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "platforms/nuttx/NuttX/apps"
SOURCE = APPS / "testing/rzv_hwtest/uart/uart_loopback_test.c"


def receiver(source: str) -> str:
    match = re.search(r"static int uart_rx_blocking\([^;{]*\)\s*\{", source)
    if match is None:
        raise AssertionError("production uart_rx_blocking definition missing")
    start = source.index("{", match.start())
    depth = 1
    end = start + 1
    while depth:
        if end >= len(source):
            raise AssertionError("unterminated production uart_rx_blocking")
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


BOUNDARIES = r"""
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define LIMIT 64u
struct step_s {
  unsigned int delay_ms;
  int poll_result, poll_error, events, read_result, read_error;
  unsigned int read_delay_ms;
};
static struct step_s steps[LIMIT], *active;
static unsigned int step_count, clock_fail_at, clock_calls, poll_calls, read_calls;
static unsigned int read_delays;
static int clock_error, timeouts[LIMIT];
static size_t read_sizes[LIMIT], offsets[LIMIT], requested, received;
static uint8_t storage[258], *destination = storage + 1;
static uint64_t now_ms;

int test_clock_gettime(clockid_t id, struct timespec *ts)
{
  assert(id == CLOCK_MONOTONIC);
  clock_calls++;
  if (clock_calls == clock_fail_at) {
    errno = clock_error;
    return -1;
  }
  ts->tv_sec = now_ms / 1000u;
  ts->tv_nsec = (now_ms % 1000u) * 1000000u;
  return 0;
}

int test_poll(struct pollfd *fds, nfds_t count, int timeout_ms)
{
  assert(count == 1 && fds[0].fd == 17 && fds[0].events == POLLIN);
  assert(timeout_ms > 0 && poll_calls < LIMIT);
  timeouts[poll_calls] = timeout_ms;
  active = poll_calls < step_count ? &steps[poll_calls] : NULL;
  poll_calls++;
  fds[0].revents = 0;
  /* A wait cannot outlive its requested timeout. Missing events mean silence. */
  if (!active || active->poll_result == 0 ||
      active->delay_ms > (unsigned int)timeout_ms) {
    now_ms += (unsigned int)timeout_ms;
    active = NULL;
    return 0;
  }
  now_ms += active->delay_ms;
  if (active->poll_result < 0) {
    errno = active->poll_error;
    return -1;
  }
  fds[0].revents = active->events;
  return active->poll_result;
}

ssize_t test_read(int fd, void *buffer, size_t count)
{
  assert(fd == 17 && active && read_calls < LIMIT);
  assert(buffer == destination + received && count == requested - received);
  offsets[read_calls] = (uint8_t *)buffer - destination;
  read_sizes[read_calls++] = count;
  now_ms += active->read_delay_ms;
  read_delays += active->read_delay_ms;
  if (active->read_result < 0) {
    errno = active->read_error;
    return -1;
  }
  assert((size_t)active->read_result <= count);
  for (int i = 0; i < active->read_result; i++) {
    ((uint8_t *)buffer)[i] = (uint8_t)(0x20u + received + i);
  }
  received += (unsigned int)active->read_result;
  return active->read_result;
}

#define clock_gettime test_clock_gettime
#define poll test_poll
#define read test_read
"""

EXERCISE = r"""
int main(void)
{
  uint64_t initial_ms;
  int timeout_ms;
  assert(scanf("%" SCNu64 " %u %d %zu %d %u", &initial_ms, &clock_fail_at,
               &clock_error, &requested, &timeout_ms, &step_count) == 6);
  assert(requested <= 256 && step_count < LIMIT);
  for (unsigned int i = 0; i < step_count; i++) {
    struct step_s *s = &steps[i];
    assert(scanf("%u %d %d %d %d %d %u", &s->delay_ms, &s->poll_result,
                 &s->poll_error, &s->events, &s->read_result, &s->read_error,
                 &s->read_delay_ms) == 7);
  }
  memset(storage, 0xa5, sizeof(storage));
  now_ms = initial_ms;
  int result = uart_rx_blocking(17, destination, requested, timeout_ms);
  assert(storage[0] == 0xa5 && storage[requested + 1] == 0xa5);
  printf("%d %" PRIu64 " %u %u %u %zu %u|", result, now_ms - initial_ms,
         clock_calls, poll_calls, read_calls, received, read_delays);
  for (unsigned int i = 0; i < poll_calls; i++) printf("%d ", timeouts[i]);
  putchar('|');
  for (unsigned int i = 0; i < read_calls; i++) printf("%zu ", read_sizes[i]);
  putchar('|');
  for (unsigned int i = 0; i < read_calls; i++) printf("%zu ", offsets[i]);
  putchar('|');
  for (size_t i = 0; i < requested; i++) printf("%02x", destination[i]);
  putchar('\n');
  return 0;
}
"""


@dataclass(frozen=True)
class Step:
    delay_ms: int = 0
    poll_result: int = 1
    poll_error: int = 0
    events: int = select.POLLIN
    read_result: int = 0
    read_error: int = 0
    read_delay_ms: int = 0

    def encode(self) -> str:
        return " ".join(map(str, (self.delay_ms, self.poll_result, self.poll_error,
                                  self.events, self.read_result, self.read_error,
                                  self.read_delay_ms)))


def compile_receiver(directory: Path, source: str) -> Path:
    compiler = shutil.which("cc")
    if compiler is None:
        raise RuntimeError("a host C compiler (cc) is required")
    translation = directory / "uart-deadline.c"
    translation.write_text(BOUNDARIES + receiver(source) + EXERCISE, encoding="utf-8")
    binary = directory / "uart-deadline"
    result = subprocess.run(
        [compiler, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra",
         "-Werror", str(translation), "-o", str(binary)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise AssertionError(f"UART host compilation failed:\n{result.stderr}")
    return binary


def receive(binary: Path, steps: list[Step], want: int, timeout_ms: int,
            *, initial_ms: int = 1997, clock_fail_at: int = 0,
            clock_error: int = errno.EIO) -> dict:
    script = (f"{initial_ms} {clock_fail_at} {clock_error} {want} {timeout_ms} "
              f"{len(steps)}\n") + "\n".join(step.encode() for step in steps)
    result = subprocess.run([str(binary)], input=script, capture_output=True,
                            text=True, check=False, timeout=5)
    if result.returncode:
        raise AssertionError(f"UART boundary failed:\n{result.stderr}")
    summary, timeouts, sizes, offsets, data = result.stdout.strip().split("|")
    code, elapsed, clocks, polls, reads, received, read_delays = map(int, summary.split())
    return {"result": code, "elapsed": elapsed, "clocks": clocks, "polls": polls,
            "reads": reads, "received": received, "read_delays": read_delays,
            "timeouts": list(map(int, timeouts.split())),
            "sizes": list(map(int, sizes.split())),
            "offsets": list(map(int, offsets.split())), "data": bytes.fromhex(data)}


class UARTSampleDeadline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="rzv2h-uart-deadline-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = compile_receiver(Path(cls.temporary.name), SOURCE.read_text(encoding="utf-8"))

    def run_receive(self, steps: list[Step], want: int = 1, timeout_ms: int = 50,
                    **kwargs) -> dict:
        return receive(self.binary, steps, want, timeout_ms, **kwargs)

    def test_partial_reads_share_one_absolute_deadline(self) -> None:
        actual = self.run_receive([Step(delay_ms=30, read_result=1)] * 8, want=8,
                                  timeout_ms=100)
        self.assertEqual((actual["result"], actual["elapsed"]), (-errno.ETIMEDOUT, 100))
        self.assertEqual(actual["timeouts"], [100, 70, 40, 10])
        self.assertEqual(actual["sizes"], [8, 7, 6])
        self.assertEqual(actual["offsets"], [0, 1, 2])
        self.assertEqual(actual["data"], b"\x20\x21\x22" + b"\xa5" * 5)

    def test_partial_success_appends_without_overwriting(self) -> None:
        actual = self.run_receive([Step(delay_ms=5, read_result=2),
                                   Step(delay_ms=8, read_result=1),
                                   Step(delay_ms=7, read_result=3)], want=6)
        self.assertEqual((actual["result"], actual["elapsed"]), (6, 20))
        self.assertEqual(actual["timeouts"], [50, 45, 37])
        self.assertEqual(actual["sizes"], [6, 4, 3])
        self.assertEqual(actual["offsets"], [0, 2, 3])
        self.assertEqual(actual["data"], bytes(range(0x20, 0x26)))

    def test_zero_progress_read_cannot_renew_timeout(self) -> None:
        actual = self.run_receive([Step(delay_ms=20)] * 8)
        self.assertEqual((actual["result"], actual["elapsed"]), (-errno.ETIMEDOUT, 50))
        self.assertEqual(actual["timeouts"], [50, 30, 10])
        self.assertEqual((actual["reads"], actual["data"]), (2, b"\xa5"))

    def test_repeated_poll_eintr_uses_remaining_time(self) -> None:
        actual = self.run_receive([Step(delay_ms=10, poll_result=-1,
                                        poll_error=errno.EINTR)] * 5)
        self.assertEqual((actual["result"], actual["elapsed"]), (-errno.ETIMEDOUT, 50))
        self.assertEqual(actual["timeouts"], [50, 40, 30, 20, 10])
        self.assertEqual(actual["reads"], 0)

    def test_repeated_read_eintr_and_eagain_use_remaining_time(self) -> None:
        for error in (errno.EINTR, errno.EAGAIN):
            with self.subTest(error=error):
                actual = self.run_receive([Step(delay_ms=10, read_result=-1,
                                                read_error=error)] * 5)
                self.assertEqual((actual["result"], actual["elapsed"]),
                                 (-errno.ETIMEDOUT, 50))
                self.assertEqual(actual["timeouts"], [50, 40, 30, 20, 10])
                self.assertEqual(actual["offsets"], [0] * 5)
                self.assertEqual(actual["data"], b"\xa5")

    def test_retryable_errors_preserve_partial_data_and_can_recover(self) -> None:
        actual = self.run_receive([
            Step(delay_ms=10, read_result=2),
            Step(delay_ms=10, read_result=-1, read_error=errno.EINTR),
            Step(delay_ms=10, poll_result=-1, poll_error=errno.EINTR),
            Step(delay_ms=5, read_result=-1, read_error=errno.EAGAIN),
            Step(delay_ms=5, read_result=2),
        ], want=4)
        self.assertEqual((actual["result"], actual["elapsed"]), (4, 40))
        self.assertEqual(actual["timeouts"], [50, 40, 30, 20, 15])
        self.assertEqual(actual["offsets"], [0, 2, 2, 2])
        self.assertEqual(actual["sizes"], [4, 2, 2, 2])
        self.assertEqual(actual["data"], bytes(range(0x20, 0x24)))

    def test_read_processing_time_consumes_the_same_budget(self) -> None:
        actual = self.run_receive([Step(delay_ms=5, read_result=1, read_delay_ms=15),
                                   Step(delay_ms=10, read_result=1)], want=2,
                                  timeout_ms=25)
        self.assertEqual((actual["result"], actual["elapsed"]), (-errno.ETIMEDOUT, 25))
        self.assertEqual(actual["timeouts"], [25, 5])
        self.assertEqual((actual["received"], actual["read_delays"]), (1, 15))

    def test_poll_timeout_is_reported_without_reading(self) -> None:
        actual = self.run_receive([])
        self.assertEqual((actual["result"], actual["elapsed"]), (-errno.ETIMEDOUT, 50))
        self.assertEqual((actual["polls"], actual["reads"]), (1, 0))

    def test_poll_errors_preserve_errno(self) -> None:
        for error in (errno.EBADF, errno.EIO, errno.EAGAIN):
            with self.subTest(error=error):
                actual = self.run_receive([Step(poll_result=-1, poll_error=error)])
                self.assertEqual(actual["result"], -error)
                self.assertEqual(actual["reads"], 0)

    def test_poll_device_fault_flags_return_eio_without_reading(self) -> None:
        for events in (select.POLLERR, select.POLLHUP, select.POLLNVAL,
                       select.POLLIN | select.POLLHUP):
            with self.subTest(events=events):
                actual = self.run_receive([Step(events=events, read_result=1)])
                self.assertEqual(actual["result"], -errno.EIO)
                self.assertEqual((actual["reads"], actual["data"]), (0, b"\xa5"))

    def test_nonretryable_read_error_preserves_errno_and_partial_data(self) -> None:
        for error in (errno.EIO, errno.EBADF):
            with self.subTest(error=error):
                actual = self.run_receive([Step(read_result=1),
                                           Step(read_result=-1, read_error=error)], want=2)
                self.assertEqual(actual["result"], -error)
                self.assertEqual(actual["offsets"], [0, 1])
                self.assertEqual(actual["data"], b"\x20\xa5")

    def test_clock_failure_before_and_during_receive_preserves_errno(self) -> None:
        for fail_at, error in ((1, errno.ENOSYS), (2, errno.EIO), (3, errno.EOVERFLOW)):
            with self.subTest(fail_at=fail_at):
                actual = self.run_receive([Step(delay_ms=5, read_result=1)], want=2,
                                          clock_fail_at=fail_at, clock_error=error)
                self.assertEqual(actual["result"], -error)
                self.assertEqual(actual["polls"], int(fail_at == 3))
                self.assertEqual(actual["reads"], int(fail_at == 3))
                self.assertEqual(actual["data"], b"\x20\xa5" if fail_at == 3 else b"\xa5\xa5")

    def test_negative_timeout_is_rejected_before_clock_or_io(self) -> None:
        actual = self.run_receive([], timeout_ms=-1)
        self.assertEqual(actual["result"], -errno.EINVAL)
        self.assertEqual((actual["clocks"], actual["polls"], actual["reads"]), (0, 0, 0))

    def test_expired_zero_timeout_performs_no_poll_or_read(self) -> None:
        actual = self.run_receive([], timeout_ms=0)
        self.assertEqual(actual["result"], -errno.ETIMEDOUT)
        self.assertEqual((actual["elapsed"], actual["polls"], actual["reads"]), (0, 0, 0))

    def test_empty_receive_performs_no_io(self) -> None:
        actual = self.run_receive([], want=0)
        self.assertEqual(actual["result"], 0)
        self.assertEqual((actual["polls"], actual["reads"], actual["data"]), (0, 0, b""))

    def test_large_monotonic_time_and_maximum_timeout_do_not_wrap(self) -> None:
        actual = self.run_receive([Step(delay_ms=0x7ffffffe, read_result=1)],
                                  timeout_ms=0x7fffffff, initial_ms=(1 << 40) - 3)
        self.assertEqual(actual["result"], 1)
        self.assertEqual(actual["elapsed"], 0x7ffffffe)
        self.assertEqual(actual["timeouts"], [0x7fffffff])
        self.assertEqual(actual["data"], b"\x20")


if __name__ == "__main__":
    unittest.main()
