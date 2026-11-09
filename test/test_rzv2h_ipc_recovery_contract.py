#!/usr/bin/env python3
"""Executable recovery and readiness contracts for the RZ/V2H IPC demo."""

from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "platforms/nuttx/NuttX/apps/examples/rzv_ipc_demo/rzv_ipc_demo_main.c"
)


HARNESS = r"""
#define main ipctest_program_main
#define poll mock_poll
#define read mock_read
#define write mock_write
#define ioctl mock_ioctl
#define open mock_open
#define close mock_close
#include "rzv_ipc_demo_main.c"
#undef main
#undef poll
#undef read
#undef write
#undef ioctl
#undef open
#undef close

#include <stdarg.h>

enum test_scenario_e
{
  TEST_RECOVER_NOT_READY,
  TEST_RECOVER_STATS_ERROR,
  TEST_READY_DEGRADED,
  TEST_READY_CLEAN
};

static enum test_scenario_e g_scenario;
static int g_write_error;
static int g_write_calls;
static int g_recover_calls;
static int g_stats_calls;
static bool g_poll_eintr;

int mock_poll(struct pollfd *fds, nfds_t nfds, int timeout)
{
  (void)nfds;
  (void)timeout;
  if (g_poll_eintr)
    {
      errno = EINTR;
      return -1;
    }

  fds[0].revents = POLLIN;
  return 1;
}

ssize_t mock_read(int fd, void *buffer, size_t size)
{
  (void)fd;
  memset(buffer, 0x5a, size);
  return (ssize_t)size;
}

ssize_t mock_write(int fd, const void *buffer, size_t size)
{
  (void)fd;
  (void)buffer;
  g_write_calls++;
  if (g_write_error != 0 && g_write_calls == 1)
    {
      errno = g_write_error;
      return -1;
    }

  return (ssize_t)size;
}

int mock_ioctl(int fd, unsigned long request, ...)
{
  va_list ap;
  struct rzv_ipc_raw_stats_s *stats;

  (void)fd;
  if (request == RZV_IPC_RAWIOC_RECOVER)
    {
      g_recover_calls++;
      return 0;
    }

  if (request != RZV_IPC_RAWIOC_GET_STATS)
    {
      errno = EINVAL;
      return -1;
    }

  g_stats_calls++;
  if (g_scenario == TEST_RECOVER_STATS_ERROR && g_stats_calls == 2)
    {
      errno = EIO;
      return -1;
    }

  va_start(ap, request);
  stats = (struct rzv_ipc_raw_stats_s *)(uintptr_t)va_arg(ap, unsigned long);
  va_end(ap);
  memset(stats, 0, sizeof(*stats));

  if (g_scenario == TEST_READY_CLEAN ||
      (g_scenario == TEST_RECOVER_STATS_ERROR && g_stats_calls == 1))
    {
      stats->ready = true;
    }
  else if (g_scenario == TEST_READY_DEGRADED)
    {
      stats->ready = true;
      stats->degraded = true;
    }

  return 0;
}

int mock_open(const char *path, int flags, ...)
{
  (void)path;
  (void)flags;
  return 3;
}

int mock_close(int fd)
{
  (void)fd;
  return 0;
}

static void reset_scenario(enum test_scenario_e scenario)
{
  g_scenario = scenario;
  g_write_error = 0;
  g_write_calls = 0;
  g_recover_calls = 0;
  g_stats_calls = 0;
  g_poll_eintr = false;
}

/* Run run_echo with captured stdout and require its exit code, write count
 * and exact IPCTEST_RESULT tail.  bounded selects --auto-echo -n count;
 * write_error fails the first write; poll_eintr makes poll report a signal.
 */

static int check_echo(bool bounded, int count, int write_error,
                      bool poll_eintr, int expected_ret, int expected_writes,
                      const char *expected_result)
{
  struct ipctest_args_s args;
  FILE *capture;
  int saved_stdout;
  char output[2048];
  char result[256];
  size_t length;
  int ret;

  memset(&args, 0, sizeof(args));
  args.dev = "/dev/ipcc-test";
  args.count = count;
  args.msgsize = RZV_IPC_RAW_PAYLOAD_SIZE;
  args.timeout_ms = 1;
  args.echo_mode = true;
  args.bounded_echo = bounded;

  capture = tmpfile();
  if (capture == NULL)
    {
      return 1;
    }

  fflush(stdout);
  saved_stdout = dup(STDOUT_FILENO);
  if (saved_stdout < 0 || dup2(fileno(capture), STDOUT_FILENO) < 0)
    {
      fclose(capture);
      return 1;
    }

  reset_scenario(TEST_READY_CLEAN);
  g_write_error = write_error;
  g_poll_eintr = poll_eintr;
  ret = run_echo(3, &args);
  fflush(stdout);
  dup2(saved_stdout, STDOUT_FILENO);
  mock_close(saved_stdout);
  rewind(capture);
  length = fread(output, 1, sizeof(output) - 1, capture);
  output[length] = '\0';
  fclose(capture);

  snprintf(result, sizeof(result),
           "IPCTEST_RESULT core=TEST mode=%s dev=/dev/ipcc-test %s\n",
           bounded ? "auto-echo" : "echo", expected_result);
  return ret == expected_ret && g_recover_calls == 0 &&
         g_write_calls == expected_writes &&
         strstr(output, result) != NULL ? 0 : 1;
}

int main(void)
{
  struct ipctest_args_s args;

  memset(&args, 0, sizeof(args));
  args.dev = "/dev/ipcc-test";
  args.msgsize = RZV_IPC_RAW_PAYLOAD_SIZE;

  if (check_echo(true, 1, ETIMEDOUT, false, 2, 1,
                 "status=timeout echoed=0 expected=1") != 0 ||
      check_echo(true, 1, EPROTO, false, 1, 1,
                 "status=error echoed=0 expected=1") != 0 ||
      check_echo(true, 1, ENOLINK, false, 1, 1,
                 "status=error echoed=0 expected=1") != 0)
    {
      return 1;
    }

  /* A bounded auto-echo passes only after its full count; one stopped by
   * a signal first is an error.  Unbounded echo stopped by a signal passes.
   */

  if (check_echo(true, 3, 0, false, 0, 3,
                 "status=pass echoed=3 expected=3") != 0 ||
      check_echo(true, 100, 0, true, 1, 0,
                 "status=error echoed=0 expected=100") != 0 ||
      check_echo(false, 0, 0, true, 0, 0,
                 "status=pass echoed=0 expected=0") != 0)
    {
      return 7;
    }

  reset_scenario(TEST_READY_CLEAN);
  if (run_recover(3, &args) != 0 || g_recover_calls != 1)
    {
      return 2;
    }

  reset_scenario(TEST_RECOVER_NOT_READY);
  if (run_recover(3, &args) == 0)
    {
      return 3;
    }

  reset_scenario(TEST_RECOVER_STATS_ERROR);
  if (run_recover(3, &args) == 0)
    {
      return 4;
    }

  reset_scenario(TEST_READY_DEGRADED);
  if (ipctest_report_ready(3, &args, "recover"))
    {
      return 5;
    }

  reset_scenario(TEST_READY_CLEAN);
  if (!ipctest_report_ready(3, &args, "recover"))
    {
      return 6;
    }

  return 0;
}
"""


class Rzv2hIpcRecoveryContractTest(unittest.TestCase):
    def test_boot_peer_recovers_degraded_link_and_keeps_deadline(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
        boundary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(boundary)
        code = boundary.PRELUDE + r"""
#define FAR
#define CONFIG_RZV_IPC_RAW 1
#define CONFIG_EXAMPLES_RZV_IPC_DEMO_BOOT_READY_WAIT_MS 100
#define IPCTEST_DEFAULT_DEV "/dev/ipcc1"
#define IPCTEST_CORE_NAME "TEST"
#define O_RDWR 0
#define O_NONBLOCK 1
#define RZV_IPC_RAWIOC_GET_STATS 1
#define RZV_IPC_RAWIOC_RECOVER 2
struct rzv_ipc_raw_stats_s { bool ready, degraded; };
static uint64_t time_ms;
static int recoveries, closes, permanently_bad;
static uint64_t now_ms(void) { return time_ms; }
static void usleep(unsigned us) { time_ms+=us/1000; }
static int open(const char *p,int f) { (void)p; (void)f; return 3; }
static int close(int fd) { (void)fd; closes++; return 0; }
static int ioctl(int fd,int request,unsigned long arg)
{
 (void)fd;
 if (request==RZV_IPC_RAWIOC_RECOVER) { recoveries++; time_ms+=10; return permanently_bad?-1:0; }
 struct rzv_ipc_raw_stats_s *s=(void *)(uintptr_t)arg;
 s->ready=recoveries>0 && !permanently_bad; s->degraded=!s->ready; return 0;
}
#define printf(...) ((void)0)
""" + boundary.EXTRACT.definition(SOURCE.read_text(), 'static int ipctest_wait_for_boot_ready(') + r"""
int main(void)
{
#ifdef CONFIG_RZV2H_BUILD_CR8_1
 assert(ipctest_wait_for_boot_ready()==0 && recoveries>=1 && closes>=1);
 time_ms=0;recoveries=0;closes=0;permanently_bad=1;
 assert(ipctest_wait_for_boot_ready()==1 && time_ms>=100 && time_ms<=120);
 assert(recoveries>0 && closes>0);
#else
 assert(ipctest_wait_for_boot_ready()==1 && recoveries==0 && closes>0);
#endif
 return 0;
}
"""
        boundary.compile_run('#define CONFIG_RZV2H_BUILD_CR8_1 1\n' + code)
        boundary.compile_run(code)

    def test_recovery_paths_execute_in_host_harness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            nuttx = temporary / "nuttx"
            ipc = nuttx / "ipc"
            ipc.mkdir(parents=True)
            (nuttx / "config.h").write_text(
                textwrap.dedent(
                    """
                    #define FAR
                    #define CONFIG_RZV_IPC_RAW 1
                    #define CONFIG_EXAMPLES_RZV_IPC_DEMO_DEFAULT_DEVICE "/dev/ipcc-test"
                    #define CONFIG_EXAMPLES_RZV_IPC_DEMO_DEFAULT_COUNT 1
                    #define CONFIG_EXAMPLES_RZV_IPC_DEMO_DEFAULT_SIZE 64
                    #define CONFIG_EXAMPLES_RZV_IPC_DEMO_DEFAULT_TIMEOUT 1
                    #define CONFIG_EXAMPLES_RZV_IPC_DEMO_CORE_NAME "TEST"
                    """
                ),
                encoding="utf-8",
            )
            (ipc / "rzv_ipc_raw.h").write_text(
                textwrap.dedent(
                    """
                    #pragma once
                    #include <stdbool.h>
                    #include <stdint.h>
                    #define RZV_IPC_RAW_PAYLOAD_SIZE 64
                    #define RZV_IPC_RAWIOC_GET_STATS 0x1001
                    #define RZV_IPC_RAWIOC_RECOVER 0x1002
                    struct rzv_ipc_raw_stats_s
                    {
                      bool ready;
                      bool degraded;
                      uint32_t epoch;
                      uint32_t tx_sequence;
                      uint32_t rx_sequence;
                      uint32_t tx_messages;
                      uint32_t rx_messages;
                      uint32_t tx_timeouts;
                      uint32_t stale_acks;
                      uint32_t invalid_headers;
                      uint32_t invalid_entries;
                      uint32_t recoveries;
                    };
                    """
                ),
                encoding="utf-8",
            )
            harness = temporary / "recovery_harness.c"
            harness.write_text(HARNESS, encoding="utf-8")
            executable = temporary / "recovery_harness"

            compile_result = subprocess.run(
                [
                    "cc",
                    "-std=c11",
                    "-D_GNU_SOURCE",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    f"-I{temporary}",
                    f"-I{SOURCE.parent}",
                    str(harness),
                    "-o",
                    str(executable),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)

            run_result = subprocess.run(
                [str(executable)], check=False, capture_output=True, text=True
            )
            self.assertEqual(
                run_result.returncode,
                0,
                f"stdout:\n{run_result.stdout}\nstderr:\n{run_result.stderr}",
            )

    def test_armed_and_ready_marker_contract_remains_explicit(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        echo_start = source.index("static int run_echo")
        loop_start = source.index("for (;;)", echo_start)
        startup = source[echo_start:loop_start]

        armed = startup.index("IPCTEST_ARMED core=%s")
        ready_check = startup.index("ipctest_report_ready", armed)
        self.assertLess(armed, ready_check)
        self.assertNotIn("IPCTEST_READY core=%s", startup[:ready_check])
        self.assertIn("stats.ready && !stats.degraded", source)

    def test_poll_error_path_terminates_before_reading_payload(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        poll_error = source.index("if ((pfd.revents & POLLERR) != 0)")
        read_call = source.index("nr = read(fd, buf, (size_t)a->msgsize);")
        self.assertLess(poll_error, read_call)
        self.assertIn('print_echo_result(a, "error", echoed);',
                      source[poll_error:read_call])
        self.assertIn("return 1;", source[poll_error:read_call])

    def test_runtime_echo_never_recovers_implicitly(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        echo_start = source.index("static int run_echo")
        echo_end = source.index("int main(int argc", echo_start)
        echo = source[echo_start:echo_end]

        self.assertNotIn("RZV_IPC_RAWIOC_RECOVER", echo)
        # Boot code (auto-echo, then peer/showcase) starts at the first boot
        # guard; only the CLI code before it must stay recover-free apart
        # from the explicit --recover mode.
        runtime = source.split("#ifdef CONFIG_EXAMPLES_RZV_IPC_DEMO_BOOT_AUTOECHO", 1)[0]
        self.assertEqual(runtime.count("RZV_IPC_RAWIOC_RECOVER"), 1)
        recover_start = source.index("static int run_recover")
        recover_end = source.index("#endif", recover_start)
        self.assertIn("RZV_IPC_RAWIOC_RECOVER",
                      source[recover_start:recover_end])


if __name__ == "__main__":
    unittest.main()
