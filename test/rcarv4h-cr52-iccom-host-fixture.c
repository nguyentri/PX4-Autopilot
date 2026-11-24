/* Host fixture for the R-Car V4H CR52-0 ICCOM protocol engine.
 *
 * Compiled with arch/arm/src/rcar/rcar_iccom_proto.c by
 * rcarv4h-cr52-iccom-protocol-test.py.  It simulates the two MFIS
 * register pairs, the four CTA slots and the clock, plays the CA76 peer
 * by hand and checks the words the engine posts.
 */

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "rcar_iccom_proto.h"

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL %s:%d: %s\n", \
                      __func__, __LINE__, #c); return 1; } } while (0)

enum access_e
{
  RD_XCTRL = 1,
  RD_XLEN,
  CLR_XINT,
};

static struct
{
  uint32_t x_ctrl;                  /* CA76 -> CR52-0 */
  uint32_t x_len;
  uint32_t y_ctrl;                  /* CR52-0 -> CA76 */
  uint32_t y_len;
  uint32_t posts;                   /* Words posted on y */
  uint8_t rx[ICCOM_NSLOTS][ICCOM_MSG_MAX];
  uint8_t tx[ICCOM_NSLOTS][ICCOM_MSG_MAX];
  uint32_t now;
  int log[16];
  int nlog;
} g;

static void log_access(int a)
{
  if (g.nlog < (int)(sizeof(g.log) / sizeof(g.log[0])))
    {
      g.log[g.nlog++] = a;
    }
}

static uint32_t sim_in_ctrl(void *arg)
{
  (void)arg;
  log_access(RD_XCTRL);
  return g.x_ctrl;
}

static uint32_t sim_in_len(void *arg)
{
  (void)arg;
  log_access(RD_XLEN);
  return g.x_len;
}

static void sim_in_clear(void *arg, uint32_t ctrl)
{
  (void)arg;
  log_access(CLR_XINT);
  g.x_ctrl = ctrl & ~ICCOM_CTRL_INT;
}

static uint32_t sim_out_ctrl(void *arg)
{
  (void)arg;
  return g.y_ctrl;
}

static void sim_out_post(void *arg, uint32_t ctrl, uint32_t len)
{
  (void)arg;
  g.y_len = len;
  g.y_ctrl = ctrl;
  g.posts++;
}

static void sim_rx_copy(void *arg, unsigned int slot, void *dst, size_t len)
{
  (void)arg;
  memcpy(dst, g.rx[slot], len);
}

static void sim_tx_copy(void *arg, unsigned int slot, const void *src,
                        size_t len)
{
  (void)arg;
  memcpy(g.tx[slot], src, len);
}

static uint32_t sim_now_ms(void *arg)
{
  (void)arg;
  return g.now;
}

static const struct rcar_iccom_ops_s g_ops =
{
  sim_in_ctrl, sim_in_len, sim_in_clear, sim_out_ctrl, sim_out_post,
  sim_rx_copy, sim_tx_copy, sim_now_ms,
};

/* Peer side */

static void peer_post(uint32_t ctrl, uint32_t len)
{
  g.x_ctrl = ctrl;
  g.x_len = len;
}

/* Peer reads and INT-clears y; returns the control word it saw */

static uint32_t peer_take(void)
{
  uint32_t ctrl = g.y_ctrl;

  g.y_ctrl &= ~ICCOM_CTRL_INT;
  return ctrl;
}

#define TIMEOUT 100u

static void reset_sim(uint32_t now)
{
  memset(&g, 0, sizeof(g));
  g.now = now;
}

/* Bring an engine to READY: local INITEND first, then the peer's */

static int bring_up(struct rcar_iccom_s *e, uint32_t now)
{
  reset_sim(now);
  rcar_iccom_start(e, &g_ops, NULL, TIMEOUT);
  CHECK(peer_take() == ICCOM_WIRE_INITEND);
  peer_post(ICCOM_WIRE_INITEND, 0);
  CHECK(rcar_iccom_incoming(e) & ICCOM_EV_STATE);
  CHECK(rcar_iccom_link(e) == 0);
  return 0;
}

static int test_wire_values(void)
{
  /* Golden words, independent of the header's bit names */

  CHECK(ICCOM_WIRE_DATA_UPPER == 0x03);
  CHECK(ICCOM_WIRE_DATA_BOTTOM == 0x07);
  CHECK(ICCOM_WIRE_ACK_UPPER == 0x01);
  CHECK(ICCOM_WIRE_ACK_BOTTOM == 0x09);
  CHECK(ICCOM_WIRE_INITEND == 0x11);
  CHECK(ICCOM_CTRL_FATAL == 0x20);
  CHECK(ICCOM_MSG_MAX == 2048);
  return 0;
}

static int test_init_local_first(void)
{
  struct rcar_iccom_s e;

  reset_sim(0);
  CHECK(rcar_iccom_start(&e, &g_ops, NULL, TIMEOUT) & ICCOM_EV_STATE);
  CHECK(g.y_ctrl == ICCOM_WIRE_INITEND);
  CHECK(rcar_iccom_link(&e) == -ENOTCONN);
  CHECK(rcar_iccom_send(&e, "x", 1) == -ENOTCONN);
  peer_take();
  peer_post(ICCOM_WIRE_INITEND, 0);
  CHECK(rcar_iccom_incoming(&e) & ICCOM_EV_STATE);
  CHECK(e.chan == ICCOM_CHAN_READY);
  CHECK(g.posts == 1);                     /* No INITEND echo */
  return 0;
}

static int test_init_peer_first(void)
{
  struct rcar_iccom_s e;

  /* Peer INITEND already waiting, and y still holds an unread word */

  reset_sim(0);
  peer_post(ICCOM_WIRE_INITEND, 0);
  g.y_ctrl = ICCOM_CTRL_INT;
  rcar_iccom_start(&e, &g_ops, NULL, TIMEOUT);
  CHECK(g.posts == 0);
  CHECK(e.stats.out_busy == 1);

  rcar_iccom_service(&e);
  CHECK(e.chan == ICCOM_CHAN_READY);
  CHECK(g.posts == 0);                     /* y still busy */

  peer_take();
  rcar_iccom_service(&e);
  CHECK(g.posts == 1 && g.y_ctrl == ICCOM_WIRE_INITEND);
  return 0;
}

static int test_int_cleared_after_reads(void)
{
  struct rcar_iccom_s e;

  if (bring_up(&e, 0))
    {
      return 1;
    }

  memcpy(g.rx[ICCOM_SLOT_UPPER], "abcd", 4);
  peer_post(ICCOM_WIRE_DATA_UPPER, 4);
  g.nlog = 0;
  rcar_iccom_incoming(&e);
  CHECK(g.nlog == 3);
  CHECK(g.log[0] == RD_XCTRL && g.log[1] == RD_XLEN &&
        g.log[2] == CLR_XINT);
  CHECK(g.x_ctrl == (ICCOM_WIRE_DATA_UPPER & ~ICCOM_CTRL_INT));

  /* Nothing pending: only the control register is read */

  g.nlog = 0;
  rcar_iccom_incoming(&e);
  CHECK(g.nlog == 1 && g.log[0] == RD_XCTRL);
  return 0;
}

static int test_send_golden(void)
{
  struct rcar_iccom_s e;

  if (bring_up(&e, 0))
    {
      return 1;
    }

  CHECK(rcar_iccom_send(&e, "hello", 5) == 0);
  CHECK(g.y_ctrl == 0x03 && g.y_len == 5);
  CHECK(memcmp(g.tx[ICCOM_SLOT_UPPER], "hello", 5) == 0);
  CHECK(e.send == ICCOM_SEND_WAITACK);
  CHECK(rcar_iccom_send(&e, "x", 1) == -EBUSY);

  peer_take();
  peer_post(ICCOM_WIRE_ACK_UPPER, 0);
  CHECK(rcar_iccom_incoming(&e) & ICCOM_EV_TXDONE);
  CHECK(rcar_iccom_send_result(&e) == 0 && e.send == ICCOM_SEND_IDLE);

  /* The next send takes the bottom slot */

  CHECK(rcar_iccom_send(&e, "abc", 3) == 0);
  CHECK(g.y_ctrl == 0x07 && g.y_len == 3);
  CHECK(memcmp(g.tx[ICCOM_SLOT_BOTTOM], "abc", 3) == 0);
  peer_take();
  peer_post(ICCOM_WIRE_ACK_BOTTOM, 0);
  CHECK(rcar_iccom_incoming(&e) & ICCOM_EV_TXDONE);
  CHECK(e.stats.tx_msgs == 2 && e.stats.ack_late == 0);

  /* Length limits */

  CHECK(rcar_iccom_send(&e, "", 0) == -EINVAL);
  CHECK(rcar_iccom_send(&e, g.rx[0], ICCOM_MSG_MAX + 1) == -EINVAL);
  CHECK(rcar_iccom_send(&e, g.rx[0], ICCOM_MSG_MAX) == 0);
  return 0;
}

static int test_ack_wrong_slot(void)
{
  struct rcar_iccom_s e;

  if (bring_up(&e, 0))
    {
      return 1;
    }

  CHECK(rcar_iccom_send(&e, "a", 1) == 0);
  peer_take();
  peer_post(ICCOM_WIRE_ACK_BOTTOM, 0);
  CHECK((rcar_iccom_incoming(&e) & ICCOM_EV_TXDONE) == 0);
  CHECK(e.stats.ack_late == 1);
  CHECK(e.send == ICCOM_SEND_WAITACK);
  return 0;
}

static int test_timeout_then_late_ack(void)
{
  struct rcar_iccom_s e;

  /* Start near the clock wrap so the deadline wraps too */

  if (bring_up(&e, 0xffffffc0u))
    {
      return 1;
    }

  CHECK(rcar_iccom_send(&e, "a", 1) == 0);
  peer_take();
  g.now += TIMEOUT - 1;
  CHECK((rcar_iccom_service(&e) & ICCOM_EV_TXDONE) == 0);
  g.now += 1;
  CHECK(rcar_iccom_service(&e) & ICCOM_EV_TXDONE);
  CHECK(rcar_iccom_send_result(&e) == -ETIMEDOUT);
  CHECK(e.send == ICCOM_SEND_TIMEOUT && e.stats.tx_timeouts == 1);

  /* The late ACK is dropped and counted */

  peer_post(ICCOM_WIRE_ACK_UPPER, 0);
  CHECK((rcar_iccom_incoming(&e) & ICCOM_EV_TXDONE) == 0);
  CHECK(e.stats.ack_late == 1);

  /* The next send uses the other slot, so the old ACK cannot match it */

  CHECK(rcar_iccom_send(&e, "b", 1) == 0);
  CHECK(g.y_ctrl == ICCOM_WIRE_DATA_BOTTOM);
  return 0;
}

static int test_two_timeouts_never_reuse_unacked_slot(void)
{
  struct rcar_iccom_s e;
  uint32_t ev;

  if (bring_up(&e, 0))
    {
      return 1;
    }

  /* Two sends, upper then bottom, both posted and never ACKed */

  CHECK(rcar_iccom_send(&e, "a", 1) == 0);
  CHECK(g.y_ctrl == ICCOM_WIRE_DATA_UPPER);
  peer_take();
  g.now += TIMEOUT;
  CHECK(rcar_iccom_service(&e) & ICCOM_EV_TXDONE);

  CHECK(rcar_iccom_send(&e, "b", 1) == 0);
  CHECK(g.y_ctrl == ICCOM_WIRE_DATA_BOTTOM);
  peer_take();
  g.now += TIMEOUT;
  CHECK(rcar_iccom_service(&e) & ICCOM_EV_TXDONE);
  CHECK(e.stats.tx_timeouts == 2);

  /* The peer may still read both slots: a third send must not touch them */

  CHECK(!rcar_iccom_slot_free(&e));
  CHECK(rcar_iccom_send(&e, "c", 1) == -ETIMEDOUT);
  CHECK(!(e.send == ICCOM_SEND_REQUEST || e.send == ICCOM_SEND_WAITACK));

  /* A late upper ACK frees only the upper slot, does not complete a send,
   * and reports the state change so poll() can offer POLLOUT again.
   */

  peer_post(ICCOM_WIRE_ACK_UPPER, 0);
  ev = rcar_iccom_incoming(&e);
  CHECK((ev & ICCOM_EV_TXDONE) == 0 && (ev & ICCOM_EV_STATE) != 0);
  CHECK(e.stats.ack_late == 1 && rcar_iccom_slot_free(&e));

  CHECK(rcar_iccom_send(&e, "d", 1) == 0);
  CHECK(g.y_ctrl == ICCOM_WIRE_DATA_UPPER);
  peer_take();

  /* The bottom slot's late ACK must not complete the upper send */

  peer_post(ICCOM_WIRE_ACK_BOTTOM, 0);
  CHECK((rcar_iccom_incoming(&e) & ICCOM_EV_TXDONE) == 0);
  CHECK(e.send == ICCOM_SEND_WAITACK && e.stats.ack_late == 2);

  peer_post(ICCOM_WIRE_ACK_UPPER, 0);
  CHECK(rcar_iccom_incoming(&e) & ICCOM_EV_TXDONE);
  CHECK(rcar_iccom_send_result(&e) == 0);
  return 0;
}

static int test_send_timeout_while_y_busy(void)
{
  struct rcar_iccom_s e;

  if (bring_up(&e, 0))
    {
      return 1;
    }

  g.y_ctrl = ICCOM_CTRL_INT;               /* Peer never reads y */
  CHECK(rcar_iccom_send(&e, "a", 1) == 0);
  CHECK(e.send == ICCOM_SEND_REQUEST && g.posts == 1);
  g.now += TIMEOUT;
  CHECK(rcar_iccom_service(&e) & ICCOM_EV_TXDONE);
  CHECK(rcar_iccom_send_result(&e) == -ETIMEDOUT);
  return 0;
}

static int test_bad_lengths(void)
{
  static const uint32_t bad[] =
  {
    0, ICCOM_MSG_MAX + 1, 0x10000
  };

  struct rcar_iccom_s e;
  unsigned int i;

  if (bring_up(&e, 0))
    {
      return 1;
    }

  for (i = 0; i < sizeof(bad) / sizeof(bad[0]); i++)
    {
      uint32_t posts = g.posts;

      peer_post(ICCOM_WIRE_DATA_UPPER, bad[i]);
      CHECK((rcar_iccom_incoming(&e) & ICCOM_EV_RX) == 0);
      CHECK(e.stats.rx_bad == i + 1);
      CHECK(rcar_iccom_peek(&e) == 0);
      CHECK(g.posts == posts + 1 && peer_take() == ICCOM_WIRE_ACK_UPPER);
    }

  /* A full slot is fine */

  peer_post(ICCOM_WIRE_DATA_BOTTOM, ICCOM_MSG_MAX);
  CHECK(rcar_iccom_incoming(&e) & ICCOM_EV_RX);
  CHECK(rcar_iccom_peek(&e) == ICCOM_MSG_MAX);
  return 0;
}

static int test_rx_slots_hold_ack(void)
{
  struct rcar_iccom_s e;
  char buf[ICCOM_MSG_MAX];
  uint32_t posts;

  if (bring_up(&e, 0))
    {
      return 1;
    }

  posts = g.posts;
  memcpy(g.rx[ICCOM_SLOT_UPPER], "one", 3);
  memcpy(g.rx[ICCOM_SLOT_BOTTOM], "second", 6);
  peer_post(ICCOM_WIRE_DATA_UPPER, 3);
  CHECK(rcar_iccom_incoming(&e) & ICCOM_EV_RX);
  peer_post(ICCOM_WIRE_DATA_BOTTOM, 6);
  CHECK(rcar_iccom_incoming(&e) & ICCOM_EV_RX);
  CHECK(g.posts == posts);                 /* No ACK while held */
  CHECK(e.recv == ICCOM_RECV_REQUEST);

  /* A third message into a held slot is a peer error, not an ACK */

  peer_post(ICCOM_WIRE_DATA_UPPER, 1);
  rcar_iccom_incoming(&e);
  CHECK(e.stats.rx_bad == 1 && g.posts == posts);

  /* Too small a buffer keeps the message */

  CHECK(rcar_iccom_recv(&e, buf, 2) == -EMSGSIZE);
  CHECK(rcar_iccom_peek(&e) == 3);

  /* Arrival order; the ACK follows the copy */

  CHECK(rcar_iccom_recv(&e, buf, sizeof(buf)) == 3);
  CHECK(memcmp(buf, "one", 3) == 0);
  CHECK(g.posts == posts + 1 && g.y_ctrl == ICCOM_WIRE_ACK_UPPER);

  /* y not read yet: the second ACK waits */

  CHECK(rcar_iccom_recv(&e, buf, sizeof(buf)) == 6);
  CHECK(memcmp(buf, "second", 6) == 0);
  CHECK(g.posts == posts + 1 && e.recv == ICCOM_RECV_SNDACK);
  peer_take();
  rcar_iccom_service(&e);
  CHECK(g.posts == posts + 2 && g.y_ctrl == ICCOM_WIRE_ACK_BOTTOM);
  CHECK(e.recv == ICCOM_RECV_IDLE && e.stats.rx_msgs == 2);
  CHECK(rcar_iccom_recv(&e, buf, sizeof(buf)) == -EAGAIN);
  return 0;
}

static int test_fatal(void)
{
  struct rcar_iccom_s e;
  char buf[8];
  uint32_t ev;

  if (bring_up(&e, 0))
    {
      return 1;
    }

  peer_post(ICCOM_WIRE_DATA_UPPER, 2);
  rcar_iccom_incoming(&e);
  CHECK(rcar_iccom_send(&e, "a", 1) == 0);
  peer_take();

  peer_post(ICCOM_CTRL_INT | ICCOM_CTRL_FATAL, 0);
  ev = rcar_iccom_incoming(&e);
  CHECK(ev & ICCOM_EV_STATE && ev & ICCOM_EV_TXDONE);
  CHECK(e.chan == ICCOM_CHAN_WAITINIT && e.stats.fatal == 1);
  CHECK(rcar_iccom_send_result(&e) == -ECONNRESET);
  CHECK(rcar_iccom_peek(&e) == 0);
  CHECK(rcar_iccom_link(&e) == -ECONNRESET);
  CHECK(rcar_iccom_send(&e, "a", 1) == -ECONNRESET);
  CHECK(rcar_iccom_recv(&e, buf, sizeof(buf)) == -ECONNRESET);

  /* The restarted peer's INITEND brings the link back and is answered */

  peer_post(ICCOM_WIRE_INITEND, 0);
  CHECK(rcar_iccom_incoming(&e) & ICCOM_EV_STATE);
  CHECK(rcar_iccom_link(&e) == 0);
  CHECK(g.y_ctrl == ICCOM_WIRE_INITEND);
  return 0;
}

static int test_repeat_initend(void)
{
  struct rcar_iccom_s e;
  uint32_t posts;

  if (bring_up(&e, 0))
    {
      return 1;
    }

  CHECK(rcar_iccom_send(&e, "a", 1) == 0);
  peer_take();
  posts = g.posts;
  peer_post(ICCOM_WIRE_INITEND, 0);
  CHECK(rcar_iccom_incoming(&e) & ICCOM_EV_TXDONE);
  CHECK(rcar_iccom_send_result(&e) == -ECONNRESET);
  CHECK(e.chan == ICCOM_CHAN_READY && g.posts == posts);
  return 0;
}

static int test_data_before_init(void)
{
  struct rcar_iccom_s e;

  reset_sim(0);
  rcar_iccom_start(&e, &g_ops, NULL, TIMEOUT);
  peer_take();
  peer_post(ICCOM_WIRE_DATA_BOTTOM, 4);
  CHECK((rcar_iccom_incoming(&e) & ICCOM_EV_RX) == 0);
  CHECK(e.stats.rx_bad == 1);
  CHECK(peer_take() == ICCOM_WIRE_ACK_BOTTOM);
  return 0;
}

int main(void)
{
  static int (*const tests[])(void) =
  {
    test_wire_values, test_init_local_first, test_init_peer_first,
    test_int_cleared_after_reads, test_send_golden, test_ack_wrong_slot,
    test_timeout_then_late_ack, test_two_timeouts_never_reuse_unacked_slot,
    test_send_timeout_while_y_busy,
    test_bad_lengths, test_rx_slots_hold_ack, test_fatal,
    test_repeat_initend, test_data_before_init,
  };

  unsigned int i;

  for (i = 0; i < sizeof(tests) / sizeof(tests[0]); i++)
    {
      if (tests[i]())
        {
          return 1;
        }
    }

  printf("PASS %u cases\n", i);
  return 0;
}
