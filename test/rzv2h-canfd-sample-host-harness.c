/* Execute the production rzv_canfd application against deterministic I/O. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define CONFIG_CAN_FD 1
#define CONFIG_CAN_EXTID 1
#define begin_packed_struct
#define end_packed_struct __attribute__((packed))
#include "canfd-contract.inc"

enum scenario_e
{
  SC_SUCCESS,
  SC_WRITE_EAGAIN,
  SC_WRITE_EINTR,
  SC_READ_EAGAIN,
  SC_READ_EINTR,
  SC_SHORT_WRITE,
  SC_SHORT_READ,
  SC_BAD_FLAGS,
  SC_BAD_ID,
  SC_BAD_DLC,
  SC_BAD_PAYLOAD,
  SC_ERROR_FRAME,
  SC_POLL_ERROR,
  SC_POLL_HANGUP,
  SC_MISSING_ACK,
  SC_MISSING_IRQ,
  SC_STALE_IRQ,
  SC_CANCEL_TIMEOUT,
  SC_OPEN_SECOND,
};

struct port_s
{
  bool opened;
  bool has_rx;
  struct can_msg_s rx;
  size_t rx_size;
  struct rzv_canfd_tx_status_s status;
};

static struct port_s g_port[2];
static enum scenario_e g_scenario;
static uint64_t g_now_ns;
static unsigned int g_open_calls;
static unsigned int g_close_calls;
static unsigned int g_write_attempts;
static unsigned int g_read_attempts;
static unsigned int g_poll_calls;
static unsigned int g_cancel_calls;
static unsigned int g_accepted;
static bool g_injected;
static bool g_fail_reopen;

static const uint8_t g_bytes[16] =
  {0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64};

static void reset_model(bool preserve_sequences)
{
  uint32_t seq[2] = {g_port[0].status.submitted_seq,
                     g_port[1].status.submitted_seq};
  memset(g_port, 0, sizeof(g_port));
  for (unsigned int i = 0; i < 2; i++)
    {
      g_port[i].status.abi_version = RZV_CANFD_ABI_VERSION;
      g_port[i].status.flags = RZV_CANFD_TX_CANCEL_SUPPORTED;
      g_port[i].status.submitted_seq = preserve_sequences ? seq[i] : 0;
    }

  g_now_ns = 1000000000ull;
  g_open_calls = 0;
  g_close_calls = 0;
  g_write_attempts = 0;
  g_read_attempts = 0;
  g_poll_calls = 0;
  g_cancel_calls = 0;
  g_accepted = 0;
  g_injected = false;
}

static int model_open(const char *path, int flags, ...)
{
  unsigned int port;
  assert(flags == (O_RDWR | O_NONBLOCK));
  assert(g_open_calls < 2);
  port = g_open_calls++;
  assert(strcmp(path, port == 0 ? "/dev/can0" : "/dev/can1") == 0);
  if ((g_scenario == SC_OPEN_SECOND && port == 1) ||
      (g_fail_reopen && port == 0))
    {
      errno = EIO;
      return -1;
    }

  assert(!g_port[port].opened);
  g_port[port].opened = true;
  g_port[port].status.open_count = 1;
  g_port[port].status.flags &= ~(RZV_CANFD_TX_ISOLATED |
                                 RZV_CANFD_TX_FAULTED);
  return 10 + (int)port;
}

static int model_close(int fd)
{
  unsigned int port = (unsigned int)(fd - 10);
  assert(port < 2 && g_port[port].opened);
  assert((g_port[port].status.flags & RZV_CANFD_TX_PENDING) == 0);
  g_port[port].opened = false;
  g_port[port].status.open_count = 0;
  g_close_calls++;
  return 0;
}

static void verify_frame(const struct can_msg_s *frame, size_t count,
                         unsigned int port)
{
  unsigned int within = g_accepted % 82;
  unsigned int round = g_accepted / 82 + 1;
  unsigned int direction = within / 41;
  unsigned int index = within % 41;
  unsigned int dlc = index < 9 ? index : (index - 9) % 16;
  unsigned int length = g_bytes[dlc];
  uint32_t sequence = g_port[port].status.submitted_seq + 1;
  uint32_t seed = sequence ^ (round * 0x9e3779b9u) ^
                  (direction * 0x85ebca6bu) ^ (index * 0xc2b2ae35u);

  assert(port == direction);
  assert(count == CAN_MSGLEN(length));
  assert(frame->cm_hdr.ch_id == (0x10000000u | ((round - 1) << 8) |
                                 (direction << 7) | index));
  assert(frame->cm_hdr.ch_dlc == dlc);
  assert(frame->cm_hdr.ch_extid == 1);
  assert(frame->cm_hdr.ch_rtr == 0);
#ifdef CONFIG_CAN_ERRORS
  assert(frame->cm_hdr.ch_error == 0);
#endif
  assert(frame->cm_hdr.ch_edl == (index >= 9));
  assert(frame->cm_hdr.ch_brs == (index >= 25));
  assert(frame->cm_hdr.ch_esi == 0);
  for (unsigned int i = 0; i < length; i++)
    {
      seed = seed * 1664525u + 1013904223u;
      assert(frame->cm_data[i] == (uint8_t)(seed >> 24));
    }
}

static ssize_t model_write(int fd, const void *buffer, size_t count)
{
  unsigned int port = (unsigned int)(fd - 10);
  unsigned int peer = 1 - port;
  const struct can_msg_s *frame = buffer;
  g_write_attempts++;
  assert(port < 2 && g_port[port].opened);
  assert(g_port[0].opened && g_port[1].opened);

  if (!g_injected && (g_scenario == SC_WRITE_EAGAIN ||
                      g_scenario == SC_WRITE_EINTR ||
                      g_scenario == SC_POLL_ERROR ||
                      g_scenario == SC_POLL_HANGUP))
    {
      g_injected = true;
      errno = g_scenario == SC_WRITE_EINTR ? EINTR : EAGAIN;
      return -1;
    }

  verify_frame(frame, count, port);
  if (!g_injected && g_scenario == SC_SHORT_WRITE)
    {
      g_injected = true;
      return (ssize_t)count - 1;
    }

  g_port[port].status.submitted_seq++;
  g_port[port].status.active_seq = g_port[port].status.submitted_seq;
  g_port[port].status.flags |= RZV_CANFD_TX_PENDING;
  g_port[port].status.last_result = -EINPROGRESS;
  g_port[peer].rx = *frame;
  g_port[peer].rx_size = count;
  g_port[peer].has_rx = true;

  if (!g_injected)
    {
      if (g_scenario == SC_BAD_FLAGS)
        {
          g_port[peer].rx.cm_hdr.ch_extid = 0;
          g_injected = true;
        }
      else if (g_scenario == SC_BAD_ID)
        {
          g_port[peer].rx.cm_hdr.ch_id ^= 1;
          g_injected = true;
        }
      else if (g_scenario == SC_BAD_DLC)
        {
          g_port[peer].rx.cm_hdr.ch_dlc = 1;
          g_injected = true;
        }
      else if (g_scenario == SC_BAD_PAYLOAD && count > CAN_MSGLEN(0))
        {
          g_port[peer].rx.cm_data[0] ^= 0xff;
          g_injected = true;
        }
      else if (g_scenario == SC_ERROR_FRAME)
        {
#ifdef CONFIG_CAN_ERRORS
          g_port[peer].rx.cm_hdr.ch_error = 1;
#else
          g_port[peer].rx.cm_hdr.ch_rtr = 1;
#endif
          g_injected = true;
        }
    }

  if (g_scenario == SC_MISSING_ACK || g_scenario == SC_CANCEL_TIMEOUT)
    g_port[peer].has_rx = false;
  else if (g_scenario != SC_MISSING_IRQ && g_scenario != SC_STALE_IRQ)
    {
      g_port[port].status.irq_completed_seq =
        g_port[port].status.submitted_seq;
      g_port[port].status.active_seq = 0;
      g_port[port].status.flags &= ~RZV_CANFD_TX_PENDING;
      g_port[port].status.last_result = 0;
    }
  else if (g_scenario == SC_STALE_IRQ)
    {
      g_port[port].status.irq_completed_seq =
        g_port[port].status.submitted_seq - 1;
    }

  g_accepted++;
  return (ssize_t)count;
}

static ssize_t model_read(int fd, void *buffer, size_t count)
{
  unsigned int port = (unsigned int)(fd - 10);
  size_t actual;
  g_read_attempts++;
  assert(port < 2 && count >= sizeof(struct can_msg_s));
  if (g_scenario == SC_READ_EINTR && g_read_attempts == 1)
    {
      errno = EINTR;
      return -1;
    }

  if ((g_scenario == SC_READ_EAGAIN && g_read_attempts == 1) ||
      !g_port[port].has_rx)
    {
      errno = EAGAIN;
      return -1;
    }

  actual = g_port[port].rx_size;
  memcpy(buffer, &g_port[port].rx, actual);
  g_port[port].has_rx = false;
  if (g_scenario == SC_SHORT_READ && !g_injected)
    {
      g_injected = true;
      return (ssize_t)actual - 1;
    }

  return (ssize_t)actual;
}

static int model_ioctl(int fd, unsigned long request, ...)
{
  unsigned int port = (unsigned int)(fd - 10);
  unsigned long argument;
  va_list ap;
  assert(port < 2 && g_port[port].opened);
  va_start(ap, request);
  argument = va_arg(ap, unsigned long);
  va_end(ap);

  if (request == CANIOC_RZV_GET_TX_STATUS)
    {
      *(struct rzv_canfd_tx_status_s *)(uintptr_t)argument =
        g_port[port].status;
      return 0;
    }

  assert(request == CANIOC_RZV_CANCEL_TX);
  struct rzv_canfd_cancel_s *cancel = (void *)(uintptr_t)argument;
  assert(cancel->abi_version == RZV_CANFD_ABI_VERSION);
  assert(cancel->sequence == g_port[port].status.active_seq);
  assert(cancel->timeout_ms >= 1 && cancel->timeout_ms <= 1000);
  assert(cancel->reserved == 0);
  g_cancel_calls++;
  g_port[port].status.failed_seq = cancel->sequence;
  g_port[port].status.active_seq = 0;
  g_port[port].status.flags &= ~RZV_CANFD_TX_PENDING;
  g_port[port].status.flags |= RZV_CANFD_TX_ISOLATED;
  g_port[port].status.last_result = -ECANCELED;
  if (g_scenario == SC_CANCEL_TIMEOUT)
    {
      errno = ETIMEDOUT;
      return -1;
    }

  return 0;
}

static int model_poll(struct pollfd *fds, nfds_t count, int timeout)
{
  g_poll_calls++;
  assert(count == 1 && timeout >= 0 && timeout <= 5);
  g_now_ns += (uint64_t)(timeout == 0 ? 1 : timeout) * 1000000ull;
  fds[0].revents = 0;
  if (g_scenario == SC_POLL_ERROR)
    fds[0].revents = POLLERR;
  else if (g_scenario == SC_POLL_HANGUP)
    fds[0].revents = POLLHUP;
  return fds[0].revents == 0 ? 0 : 1;
}

static int model_clock_gettime(clockid_t clock_id, struct timespec *ts)
{
  assert(clock_id == CLOCK_MONOTONIC);
  ts->tv_sec = (time_t)(g_now_ns / 1000000000ull);
  ts->tv_nsec = (long)(g_now_ns % 1000000000ull);
  return 0;
}

static int model_printf(const char *format, ...)
{
  (void)format;
  return 0;
}

static int model_fprintf(FILE *stream, const char *format, ...)
{
  (void)stream;
  (void)format;
  return 0;
}

#define open model_open
#define close model_close
#define read model_read
#define write model_write
#define ioctl model_ioctl
#define poll model_poll
#define clock_gettime model_clock_gettime
#define printf model_printf
#define fprintf model_fprintf
#define main rzv_canfd_production_main
#include "canfd-app.inc"
#undef main
#undef fprintf
#undef printf
#undef clock_gettime
#undef poll
#undef ioctl
#undef write
#undef read
#undef close
#undef open

static int invoke(int argc, char **argv)
{
  return rzv_canfd_production_main(argc, argv);
}

static void production_short_vectors(void)
{
  struct can_msg_s frame;

  assert(make_frame(&frame, 1, 0, 0, 1) == 0);
  assert(frame.cm_hdr.ch_dlc == 0);
  assert(make_frame(&frame, 1, 0, 1, 2) == 1);
  assert(frame.cm_hdr.ch_dlc == 1 && frame.cm_data[0] == 0x4f);
  assert(make_frame(&frame, 1, 0, 2, 3) == 2);
  assert(frame.cm_hdr.ch_dlc == 2 && frame.cm_data[0] == 0x0b &&
         frame.cm_data[1] == 0xcb);
}

static enum scenario_e scenario_from_name(const char *name)
{
  struct mapping_s { const char *name; enum scenario_e scenario; };
  static const struct mapping_s map[] =
  {
    {"success", SC_SUCCESS}, {"eagain", SC_WRITE_EAGAIN},
    {"write-eintr", SC_WRITE_EINTR}, {"read-eagain", SC_READ_EAGAIN},
    {"read-eintr", SC_READ_EINTR}, {"short-write", SC_SHORT_WRITE},
    {"short-read", SC_SHORT_READ}, {"bad-flags", SC_BAD_FLAGS},
    {"bad-id", SC_BAD_ID}, {"bad-dlc", SC_BAD_DLC},
    {"bad-payload", SC_BAD_PAYLOAD}, {"error-frame", SC_ERROR_FRAME},
    {"poll-error", SC_POLL_ERROR}, {"poll-hangup", SC_POLL_HANGUP},
    {"missing-ack", SC_MISSING_ACK}, {"missing-irq", SC_MISSING_IRQ},
    {"stale-irq", SC_STALE_IRQ}, {"cancel-timeout", SC_CANCEL_TIMEOUT},
    {"open-second", SC_OPEN_SECOND},
  };
  for (unsigned int i = 0; i < sizeof(map) / sizeof(map[0]); i++)
    if (strcmp(name, map[i].name) == 0) return map[i].scenario;
  assert(false);
  return SC_SUCCESS;
}

static void invalid_arguments(void)
{
  char *cases[][5] =
  {
    {"rzv_canfd", "-n"}, {"rzv_canfd", "-n0"},
    {"rzv_canfd", "-n", "257"}, {"rzv_canfd", "-n-1"},
    {"rzv_canfd", "-n1x"}, {"rzv_canfd", "-t"},
    {"rzv_canfd", "-t0"}, {"rzv_canfd", "-t5001"},
    {"rzv_canfd", "+n1"}, {"rzv_canfd", "--n", "1"},
    {"rzv_canfd", "-x1"}, {"rzv_canfd", "1"},
  };
  const int argc[] = {2, 2, 3, 2, 2, 2, 2, 2, 2, 3, 2, 2};
  for (unsigned int i = 0; i < sizeof(argc) / sizeof(argc[0]); i++)
    {
      reset_model(false);
      assert(invoke(argc[i], cases[i]) != 0);
      assert(g_open_calls == 0 && g_close_calls == 0);
    }
}

int main(int argc, char **argv)
{
  char *one[] = {"rzv_canfd", "-n1", "-t20"};
  char *split[] = {"rzv_canfd", "-n", "1", "-t", "20"};
  char *attached_32[] = {"rzv_canfd", "-n32", "-t20"};
  char *split_32[] = {"rzv_canfd", "-n", "32", "-t", "20"};
  char *defaults[] = {"rzv_canfd"};
  int ret;
  assert(argc == 2);
  if (strcmp(argv[1], "vectors") == 0)
    {
      production_short_vectors();
      return 0;
    }

  if (strcmp(argv[1], "invalid") == 0)
    {
      invalid_arguments();
      return 0;
    }

  reset_model(false);
  if (strcmp(argv[1], "default") != 0 && strcmp(argv[1], "rerun") != 0 &&
      strcmp(argv[1], "isolated-reopen") != 0 &&
      strcmp(argv[1], "argument-forms") != 0)
    g_scenario = scenario_from_name(argv[1]);
  if (strcmp(argv[1], "success") == 0)
    {
      ret = invoke(5, split);
      assert(ret == 0 && g_accepted == 82 && g_open_calls == 2 &&
             g_close_calls == 2 && g_cancel_calls == 0);
    }
  else if (strcmp(argv[1], "default") == 0)
    {
      g_scenario = SC_SUCCESS;
      ret = invoke(1, defaults);
      assert(ret == 0 && g_accepted == 2624 && g_close_calls == 2);
      assert(g_port[0].status.submitted_seq == 1312);
      assert(g_port[1].status.submitted_seq == 1312);
    }
  else if (strcmp(argv[1], "argument-forms") == 0)
    {
      g_scenario = SC_SUCCESS;
      assert(invoke(3, attached_32) == 0 && g_accepted == 2624);
      reset_model(true);
      assert(invoke(5, split_32) == 0 && g_accepted == 2624);
    }
  else if (strcmp(argv[1], "rerun") == 0)
    {
      g_scenario = SC_MISSING_IRQ;
      assert(invoke(3, one) != 0 && g_cancel_calls == 1);
      reset_model(true);
      g_scenario = SC_SUCCESS;
      assert(invoke(3, one) == 0 && g_accepted == 82);
    }
  else if (strcmp(argv[1], "isolated-reopen") == 0)
    {
      g_scenario = SC_CANCEL_TIMEOUT;
      assert(invoke(3, one) != 0 && g_cancel_calls == 1);
      reset_model(true);
      g_fail_reopen = true;
      assert(invoke(3, one) != 0 && g_open_calls == 1 && g_close_calls == 0);
    }
  else
    {
      ret = invoke(3, one);
      if (g_scenario == SC_WRITE_EAGAIN || g_scenario == SC_WRITE_EINTR ||
          g_scenario == SC_READ_EAGAIN || g_scenario == SC_READ_EINTR)
        assert(ret == 0 && g_accepted == 82 && g_poll_calls > 0);
      else
        assert(ret != 0 && g_close_calls ==
               g_open_calls - (g_scenario == SC_OPEN_SECOND ? 1u : 0u));

      if (g_scenario == SC_MISSING_ACK || g_scenario == SC_MISSING_IRQ ||
          g_scenario == SC_STALE_IRQ || g_scenario == SC_CANCEL_TIMEOUT)
        assert(g_cancel_calls == 1 && g_poll_calls > 0 && g_poll_calls < 20);
    }

  return 0;
}
