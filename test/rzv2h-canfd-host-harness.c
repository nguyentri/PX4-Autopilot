/* Execute the production lower half and upper-half queue/close functions. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <semaphore.h>

#define CONFIG_RZV_CANFD 1
#define CONFIG_RZV_CANFD_IRQ_PRIORITY 5
#ifndef TEST_CHANNEL_MASK
#  define TEST_CHANNEL_MASK 9
#endif
#if TEST_CHANNEL_MASK & (1 << 0)
#  define CONFIG_RZV_CANFD0 1
#endif
#if TEST_CHANNEL_MASK & (1 << 1)
#  define CONFIG_RZV_CANFD1 1
#endif
#if TEST_CHANNEL_MASK & (1 << 2)
#  define CONFIG_RZV_CANFD2 1
#endif
#if TEST_CHANNEL_MASK & (1 << 3)
#  define CONFIG_RZV_CANFD3 1
#endif
#if TEST_CHANNEL_MASK & (1 << 4)
#  define CONFIG_RZV_CANFD4 1
#endif
#if TEST_CHANNEL_MASK & (1 << 5)
#  define CONFIG_RZV_CANFD5 1
#endif
#define CONFIG_CAN_FD 1
#define CONFIG_CAN_EXTID 1
#define CONFIG_CAN_FIFOSIZE TEST_FIFO
#ifdef TEST_LOOPBACK
#  define CONFIG_RZV_CANFD_BOOT_LOOPBACK 1
#endif
#define CONFIG_CAN_NPENDINGRTR 4
#define CONFIG_CAN_NPOLLWAITERS 4
#define CAN_MAXDATALEN 64
#define CAN_FIRST 1
#define CAN_NCMDS 12
#define _CANIOC(n) (0x1000 + (n))
#define FAR
#define CODE
#define OK 0
#define begin_packed_struct
#define end_packed_struct __attribute__((packed))
#define DEBUGASSERT assert
#define caninfo(...) ((void)0)
#define canerr(...) ((void)0)
#define MSEC2TICK(ms) ((uint64_t)(ms) * 1000)
#define HALF_SECOND_USEC 500000
#define RZV_CPG_CLK_CANFD 1
#define RZV_ELC_CANFD_GLERR 366
#define RZV_ELC_CANFD_RXFINT 367
#define RZV_ELC_CANFD_CH1_TRX 369
#define RZV_ELC_CANFD_CH1_ERR 355
#define RZV_ELC_CANFD_CH2_TRX 370
#define RZV_ELC_CANFD_CH2_ERR 356
#define RZV_ELC_CANFD_CH4_TRX 372
#define RZV_ELC_CANFD_CH4_ERR 358
#define RZV_ELC_CANFD_CH5_TRX 373
#define RZV_ELC_CANFD_CH5_ERR 359
#define RZV_ELC_CANFD_CH0_TRX 368
#define RZV_ELC_CANFD_CH0_ERR 354
#define RZV_ELC_CANFD_CH3_TRX 371
#define RZV_ELC_CANFD_CH3_ERR 357
#define RZV_INTC_GIC_GICD_ICDICPR(n) (0x13000000u + (n) * 4)
struct list_node { struct list_node *next; struct list_node *prev; };
#include "canfd-contract.inc"

_Static_assert(sizeof(struct rzv_canfd_tx_status_s) == 32, "status ABI");
_Static_assert(sizeof(struct rzv_canfd_cancel_s) == 16, "cancel ABI");

struct inode { void *i_private; };
struct file { struct inode *f_inode; int f_oflags; void *f_priv; };
typedef unsigned int irqstate_t;
typedef int (*xcpt_t)(int, void *, void *);
static unsigned int critical;
static uint8_t registers[0x20000];
static bool reset_stuck[6], standby[6] = {true,true,true,true,true,true};
static bool enabled[1024], allocated[1024];
static bool fifo_stuck[6];
static bool loopback_stuck[6], require_priority;
static int priorities[1024], priority_calls, priority_failure;
static unsigned int fifo_pops[6];
static int attaches, attach_failure, registrations, register_failure;
static int removals, transmitted, received, received_channel;
static int standby_order, retired_order, event_order, config_calls;
static uint64_t ticks;
static unsigned int mmio_reads, gic_clears;
static struct can_hdr_s received_header;
static uint8_t received_data[64];

static irqstate_t enter_critical_section(void) { return critical++; }
static void leave_critical_section(irqstate_t old) { critical = old; }
static void up_udelay(unsigned int us) { ticks += us; }
static uint64_t clock_systime_ticks(void) { return ticks; }
static int nxsig_usleep(unsigned int us)
{
  assert(!critical);
  assert(us != HALF_SECOND_USEC); /* close must never enter a drain wait */
  ticks += us;
  return 0;
}
static int up_interrupt_context(void) { return 0; }
static int rzv_clock_enable(int id) { (void)id; return 0; }
static int rzv_clock_disable(int id) { (void)id; return 0; }
static int rzv_module_unreset(int id) { (void)id; return 0; }
static int rzv_module_reset(int id) { (void)id; return 0; }
static void up_enable_irq(int irq)
{
  assert(irq >= 0);
  if (require_priority) assert(priorities[irq] == CONFIG_RZV_CANFD_IRQ_PRIORITY);
  enabled[irq] = true;
}
static void up_disable_irq(int irq) { assert(irq >= 0); enabled[irq] = false; }
static int rzv_icu_attach(int event, int (*fn)(int, void *, void *),
                          void *arg, bool enable)
{
  int irq = 400 + ++attaches;
  (void)event; (void)fn; (void)arg;
  if (attaches == attach_failure) return -ENOMEM;
  allocated[irq] = true;
  if (enable) up_enable_irq(irq);
  return irq;
}
static int rzv_icu_set_priority(int irq, int priority)
{
  assert(allocated[irq] && !enabled[irq]);
  assert(priority == CONFIG_RZV_CANFD_IRQ_PRIORITY);
  if (++priority_calls == priority_failure) return -EACCES;
  priorities[irq] = priority;
  return 0;
}
static void rzv_icu_detach(int irq)
{
  assert(irq >= 0 && allocated[irq]);
  allocated[irq] = false; enabled[irq] = false;
}
static unsigned int index_of(uintptr_t address)
{
  assert(address >= RZV_CANFD_BASE && address < RZV_CANFD_BASE + sizeof(registers));
  return address - RZV_CANFD_BASE;
}
static uint32_t getreg32(uintptr_t address)
{
  uint32_t value; ++mmio_reads;
  memcpy(&value, registers + index_of(address), sizeof(value));
  return value;
}
static uint8_t getreg8(uintptr_t address)
{
  ++mmio_reads; return registers[index_of(address)];
}
static void raw32(uintptr_t address, uint32_t value)
{
  memcpy(registers + index_of(address), &value, sizeof(value));
}
static void putreg32(uint32_t value, uintptr_t address)
{
  if (address >= 0x13000000u && address < 0x13000100u)
    { ++gic_clears; return; }
  for (unsigned int fifo=0;fifo<6;++fifo)
    if (address==RZV_CANFD_CFDRFSTS(fifo))
      value=(value & ~CANFD_RFSTS_RFEMP) |
            (getreg32(address) & CANFD_RFSTS_RFEMP);
  raw32(address, value);
  for (unsigned int ch = 0; ch < 6; ++ch)
    {
      if (address == RZV_CANFD_CFDC_CTR(ch))
        {
          uint32_t mode = value & CANFD_CFDC_CTR_CHMDC_MASK;
          if (mode == CANFD_CFDC_CTR_CHMDC_RESET)
            {
              if (!reset_stuck[ch])
                {
                  raw32(RZV_CANFD_CFDC_STS(ch), CANFD_CFDC_STS_CRSTSTS);
                  registers[index_of(RZV_CANFD_CFDTMSTS(ch * 64))] = 0;
                }
            }
          else if (mode == CANFD_CFDC_CTR_CHMDC_HALT)
            raw32(RZV_CANFD_CFDC_STS(ch), CANFD_CFDC_STS_CHLTSTS);
          else raw32(RZV_CANFD_CFDC_STS(ch), 0);
        }
    }
  if (address == RZV_CANFD_CFDGCTR)
    raw32(RZV_CANFD_CFDGSTS,
      (value & CANFD_GCTR_GMDC_MASK) == CANFD_GCTR_GMDC_RESET ? CANFD_GSTS_GRSTSTS : 0);
  for (unsigned int fifo = 0; fifo < 6; ++fifo)
    if (address == RZV_CANFD_CFDRFPCTR(fifo))
      {
        fifo_pops[fifo]++;
        if (!fifo_stuck[fifo])
          raw32(RZV_CANFD_CFDRFSTS(fifo), CANFD_RFSTS_RFEMP);
      }
}
/* Apply the configured channel's AFL DLC check/replacement before FIFO storage. */
static bool receive_frame(unsigned int channel, uint32_t id, uint8_t dlc,
                          uint32_t options, const uint8_t *data)
{
  static const uint8_t lengths[] = {0,1,2,3,4,5,6,7,8,12,16,20,24,32,48,64};
  unsigned int rule = 0;
  for (unsigned int ch = 0; ch < channel; ++ch)
    rule += (getreg32(RZV_CANFD_CFDGAFLCFG(ch / 2)) >> ((ch & 1) ? 0 : 16)) & 0xff;
  uint32_t minimum = getreg32(RZV_CANFD_BASE + RZV_CANFD_CFDGAFL_P0_OFFSET(rule)) & 15;
  uint32_t global = getreg32(RZV_CANFD_CFDGCFG);
  if (global & CANFD_GCFG_DCE)
    {
      if (dlc < minimum) return false;
      if (global & CANFD_GCFG_DRE) dlc = minimum;
    }
  uint32_t routes = getreg32(RZV_CANFD_BASE + RZV_CANFD_CFDGAFL_P1_OFFSET(rule));
  for (unsigned int fifo = 0; fifo < 6; ++fifo)
    if (routes & (1u << fifo))
      {
        raw32(RZV_CANFD_BASE + RZV_CANFD_CFDRFID_OFFSET(fifo), id);
        raw32(RZV_CANFD_BASE + RZV_CANFD_CFDRFPTR_OFFSET(fifo), dlc << CANFD_RFPTR_RFDLC_SHIFT);
        raw32(RZV_CANFD_BASE + RZV_CANFD_CFDRFFDSTS_OFFSET(fifo), options);
        memcpy(registers + RZV_CANFD_CFDRFDF_OFFSET(fifo, 0), data, lengths[dlc]);
        raw32(RZV_CANFD_CFDRFSTS(fifo), CANFD_RFSTS_RFIF);
      }
  return true;
}
static void putreg8(uint8_t value, uintptr_t address)
{
  unsigned int index = index_of(address);
  for (unsigned int ch = 0; ch < 6; ++ch)
    {
      uintptr_t status = RZV_CANFD_CFDTMSTS(ch * 64);
      if (address == status)
        {
          registers[index] = (registers[index] & CANFD_TMSTS_TMTRM) |
                             (value & CANFD_TMSTS_TMTRF_MASK);
          return;
        }
      if (address == RZV_CANFD_CFDTMC(ch * 64))
        {
          if (value & CANFD_TMC_TMTR)
            {
              bool loop = (getreg32(RZV_CANFD_CFDC_CTR(ch)) & CANFD_CFDC_CTR_CTME) != 0;
              assert(!standby[ch] || loop); ++transmitted;
              registers[index_of(status)] = CANFD_TMSTS_TMTRM;
              if (loop && !loopback_stuck[ch])
                {
                  receive_frame(ch, getreg32(RZV_CANFD_BASE + RZV_CANFD_CFDTMID_OFFSET(ch * 64)),
                    getreg32(RZV_CANFD_BASE + RZV_CANFD_CFDTMPTR_OFFSET(ch * 64)) >> CANFD_TMPTR_TMDLC_SHIFT,
                    getreg32(RZV_CANFD_BASE + RZV_CANFD_CFDTMFDCTR_OFFSET(ch * 64)),
                    registers + RZV_CANFD_CFDTMDF_OFFSET(ch * 64, 0));
                  registers[index_of(status)] = CANFD_TMSTS_TMTRF_TX_OK;
                }
            }
          if ((value & CANFD_TMC_TMTAR) && !reset_stuck[ch])
            registers[index_of(status)] = CANFD_TMSTS_TMTRF_ABORT;
        }
    }
  registers[index] = value;
}
static int can_register(const char *path, struct can_dev_s *dev)
{
  (void)path; (void)dev;
  return ++registrations == register_failure ? -EIO : 0;
}
static int unregister_driver(const char *path)
{
  (void)path; ++removals; return 0;
}
static int can_txdone(struct can_dev_s *dev);
static int can_receive(struct can_dev_s *dev, struct can_hdr_s *hdr, uint8_t *data);
#include "canfd-driver.inc"
static int can_receive(struct can_dev_s *dev, struct can_hdr_s *hdr, uint8_t *data)
{
  ++received; received_channel = ((struct rzv_canfd_s *)dev->cd_priv)->channel;
  received_header = *hdr;
  memcpy(received_data, data, g_dlc_to_bytes[hdr->ch_dlc]);
  return 0;
}

static int can_takesem(sem_t *sem) { (void)sem; return 0; }
static int can_givesem(sem_t *sem) { (void)sem; return 0; }
static void can_pollnotify(struct can_dev_s *dev, short events)
{ (void)dev; (void)events; retired_order = ++event_order; }
#define kmm_free free
#define list_for_every_safe(list,node,tmp) \
  for ((node)=NULL,(tmp)=NULL; (node)!=NULL; (node)=(tmp))
#define list_delete(node) ((void)(node))
static int can_xmit(struct can_dev_s *dev);
#include "canfd-upper.inc"

#define BOARD_CANFD0_TX_GPIO 10
#define BOARD_CANFD0_RX_GPIO 11
#define BOARD_CANFD1_TX_GPIO 12
#define BOARD_CANFD1_RX_GPIO 13
#define BOARD_CANFD2_TX_GPIO 14
#define BOARD_CANFD2_RX_GPIO 15
#define BOARD_CANFD4_TX_GPIO 18
#define BOARD_CANFD4_RX_GPIO 19
#define BOARD_CANFD5_TX_GPIO 20
#define BOARD_CANFD5_RX_GPIO 21
#define BOARD_CANFD3_TX_GPIO 16
#define BOARD_CANFD3_RX_GPIO 17
#define BOARD_CANFD0_STB_GPIO 100
#define BOARD_CANFD3_STB_GPIO 103
#define LOG_INFO 0
#define syslog(...) ((void)0)
static void rzv_gpiowrite(uint32_t pin, bool value)
{
  unsigned int channel = pin == 100 ? 0 : 3;
  assert(pin == 100 || pin == 103);
  standby[channel] = value;
  if (value) standby_order = ++event_order;
}
static int rzv_gpioconfig(uint32_t pin)
{
  ++config_calls;
  if (pin == 100 || pin == 103) rzv_gpiowrite(pin, true);
  else assert(standby[0] && standby[3]);
  return 0;
}
#include "canfd-board.inc"

static void init(void)
{
  for (unsigned int i=0; i<6; ++i)
    raw32(RZV_CANFD_CFDRFSTS(i), CANFD_RFSTS_RFEMP);
  assert(board_canfd_initialize() == 0);
  assert(standby[0] && standby[3]);
}
static int open_port(struct rzv_canfd_s *priv)
{
  irqstate_t flags = enter_critical_section();
  int ret = rzv_canfd_setup(&priv->dev);
  if (!ret)
    {
      memset(&priv->dev.cd_xmit, 0, sizeof(priv->dev.cd_xmit));
      priv->dev.cd_crefs=1;
      rzv_canfd_rxint(&priv->dev,true);
    }
  leave_critical_section(flags);
  return ret;
}
static ssize_t send_frame(struct rzv_canfd_s *priv)
{
  struct inode inode={.i_private=&priv->dev};
  struct file file={.f_inode=&inode,.f_oflags=O_RDWR|O_NONBLOCK};
  struct can_msg_s message={0};
  message.cm_hdr.ch_id=0x1234567; message.cm_hdr.ch_dlc=15;
  message.cm_hdr.ch_edl=1; message.cm_hdr.ch_brs=1;
  message.cm_hdr.ch_extid=1;
  for (unsigned int i=0;i<64;++i) message.cm_data[i]=i;
  return can_write(&file,(const char *)&message,CAN_MSGLEN(64));
}
static void complete(struct rzv_canfd_s *priv)
{
  assert(enabled[priv->tx_irq]);
  registers[index_of(RZV_CANFD_CFDTMSTS(TXMB0(priv->channel)))]=CANFD_TMSTS_TMTRF_TX_OK;
  irqstate_t flags=enter_critical_section();
  rzv_canfd_tx_isr(priv->tx_irq,NULL,priv);
  leave_critical_section(flags);
}
static int cancel(struct rzv_canfd_s *priv,uint32_t seq)
{
  struct rzv_canfd_cancel_s request={1,seq,5,0};
  return rzv_canfd_ioctl(&priv->dev,CANIOC_RZV_CANCEL_TX,(uintptr_t)&request);
}
static void close_port(struct rzv_canfd_s *priv)
{
  struct inode inode={.i_private=&priv->dev};
  struct file file={.f_inode=&inode};
  assert(can_close(&file)==0);
  if (priv->set_standby != NULL) assert(standby[priv->channel]);
  assert(!priv->initialized && priv->dev.cd_crefs==0);
}
static void drained(struct rzv_canfd_s *priv)
{
  assert(!priv->pending);
  assert(priv->dev.cd_xmit.tx_head==priv->dev.cd_xmit.tx_tail);
  assert(priv->dev.cd_xmit.tx_head==priv->dev.cd_xmit.tx_queue);
  assert(rzv_canfd_txempty(&priv->dev));
}
static void payloads(void)
{
  init();
  for (unsigned int port = 0; port < RZV_CANFD_NPORTS; ++port)
    {
      struct rzv_canfd_s *priv = g_ports[port];
      assert(open_port(priv) == 0);
      for (unsigned int format = 0; format < 3; ++format)
        for (unsigned int dlc = 0; dlc < (format ? 16 : 9); ++dlc)
          {
            struct can_msg_s frame = {0};
            unsigned int length = g_dlc_to_bytes[dlc], previous = received;
            uint32_t options = format ? CANFD_RFFDSTS_RFFDF : 0;
            if (format == 2) options |= CANFD_RFFDSTS_RFBRS;
            frame.cm_hdr.ch_id = 0x100 + priv->channel;
            frame.cm_hdr.ch_dlc = dlc;
            frame.cm_hdr.ch_edl = format != 0;
            frame.cm_hdr.ch_brs = format == 2;
            for (unsigned int byte = 0; byte < length; ++byte)
              frame.cm_data[byte] = byte ^ dlc ^ priv->channel;
            if (priv->loopback)
              {
                struct inode inode = {.i_private = &priv->dev};
                struct file file = {.f_inode = &inode, .f_oflags = O_RDWR | O_NONBLOCK};
                assert(can_write(&file, (const char *)&frame, CAN_MSGLEN(length)) == CAN_MSGLEN(length));
                drained(priv);
              }
            else
              {
                assert(receive_frame(priv->channel, frame.cm_hdr.ch_id, dlc, options, frame.cm_data));
                rzv_canfd_rx_isr(g_rxf_irq, NULL, NULL);
              }
            assert(received == previous + 1 && received_channel == priv->channel);
            assert(received_header.ch_dlc == dlc);
            assert(received_header.ch_edl == (format != 0));
            assert(received_header.ch_brs == (format == 2));
            assert(memcmp(received_data, frame.cm_data, length) == 0);
          }
      close_port(priv);
    }
}
static void loopback_failure(void)
{
  struct rzv_canfd_s *priv = g_ports[RZV_CANFD_NPORTS - 1];
  struct rzv_canfd_s *sibling = g_ports[0];
  unsigned int count = TEST_FIFO - 1;
  init(); assert(open_port(sibling) == 0 && open_port(priv) == 0);
  loopback_stuck[priv->channel] = reset_stuck[priv->channel] = true;
  for (unsigned int i = 0; i < count; ++i)
    {
      struct can_msg_s *frame = &priv->dev.cd_xmit.tx_buffer[i];
      frame->cm_hdr.ch_id = 0x123;
      frame->cm_hdr.ch_dlc = 15;
      frame->cm_hdr.ch_edl = 1;
    }
  priv->dev.cd_xmit.tx_tail = count;
  irqstate_t flags = enter_critical_section();
  can_xmit(&priv->dev);
  leave_critical_section(flags);
  assert(getreg8(RZV_CANFD_CFDTMSTS(TXMB0(priv->channel))) & CANFD_TMSTS_TMTRM);
  assert(!enabled[priv->tx_irq] && !enabled[priv->err_irq]);
  assert(!(getreg32(RZV_CANFD_CFDRFCC(priv->config->rxfifo)) & CANFD_RFCC_RFIE));
  assert(rzv_canfd_ioctl(&priv->dev, CANIOC_RZV_LOOPBACK, 0) == -EBUSY);
  assert(send_frame(priv) == CAN_MSGLEN(64));
  assert(priv->last_result == -EIO);
  registers[index_of(RZV_CANFD_CFDTMSTS(TXMB0(priv->channel)))] |= CANFD_TMSTS_TMTRF_TX_OK;
  rzv_canfd_tx_isr(priv->tx_irq, NULL, priv);
  close_port(priv); /* Executes the real upper-half drain-before-shutdown path. */
  assert(priv->faulted && priv->isolated && !priv->pending);
  assert(priv->submitted_seq == count + 1 && priv->failed_seq == count + 1);
  assert(priv->irq_completed_seq == 0 && transmitted == 1);
  assert(open_port(priv) == -ETIMEDOUT);
  loopback_stuck[priv->channel] = reset_stuck[priv->channel] = false;
  assert(open_port(priv) == 0);
  assert(send_frame(priv) == CAN_MSGLEN(64)); drained(priv); close_port(priv);
  assert(send_frame(sibling) == CAN_MSGLEN(64)); drained(sibling); close_port(sibling);
}
static unsigned int allocated_irqs(void)
{
  unsigned int count = 0;
  for (unsigned int irq = 0; irq < 1024; ++irq) count += allocated[irq];
  return count;
}
static void irq_priorities(void)
{
  require_priority = true;
  init(); assert(priority_calls == 2);
  for (unsigned int i = 0; i < RZV_CANFD_NPORTS; ++i)
    assert(open_port(g_ports[i]) == 0);
  assert(priority_calls == 2 + 2 * RZV_CANFD_NPORTS);
  for (unsigned int i = 0; i < RZV_CANFD_NPORTS; ++i) close_port(g_ports[i]);
  assert(allocated_irqs() == 2);
}
#if (TEST_CHANNEL_MASK & 9) == 9
static void priority_failure_case(unsigned int step)
{
  require_priority = true;
  if (step == 0)
    {
      priority_failure = 2;
      assert(board_canfd_initialize() == -EACCES);
      assert(!allocated_irqs() && g_rxf_irq < 0 && g_glerr_irq < 0);
      priority_failure = 0;
      init();
    }
  else
    {
      init(); assert(open_port(&g_rzv_canfd0_priv) == 0);
      priority_failure = priority_calls + step;
      assert(open_port(&g_rzv_canfd3_priv) == -EACCES);
      assert(allocated_irqs() == 4 && !g_priv_by_fifo[1]);
      assert(g_rzv_canfd3_priv.tx_irq < 0 && g_rzv_canfd3_priv.err_irq < 0);
      assert(g_rzv_canfd0_priv.initialized && !standby[0] && standby[3]);
      priority_failure = 0;
      assert(open_port(&g_rzv_canfd3_priv) == 0);
      close_port(&g_rzv_canfd3_priv); close_port(&g_rzv_canfd0_priv);
    }
}
static void priority_global_error_failure(void)
{
  require_priority = true;
  priority_failure = 1;
  init();
  assert(g_glerr_irq < 0 && g_rxf_irq >= 0 && allocated_irqs() == 1);
  assert(open_port(&g_rzv_canfd0_priv) == 0);
  close_port(&g_rzv_canfd0_priv);
  assert(allocated_irqs() == 1);
}
#endif
#if (TEST_CHANNEL_MASK & 9) == 9
static void routing(void)
{
  init();
  assert(getreg32(RZV_CANFD_CFDGAFLCFG(0))==(1u<<16));
  assert(getreg32(RZV_CANFD_CFDGAFLCFG(1))==1);
  assert(getreg32(RZV_CANFD_CFDRFCC(1)) & CANFD_RFCC_RFIM);
  assert(open_port(&g_rzv_canfd0_priv)==0);
  assert(open_port(&g_rzv_canfd3_priv)==0);
  assert(!standby[0] && !standby[3]);
  assert(g_priv_by_fifo[1]==&g_rzv_canfd3_priv);
  assert(getreg32(RZV_CANFD_CFDTMIEC(6))==1);
  assert(send_frame(&g_rzv_canfd3_priv)==CAN_MSGLEN(64));
  if (TEST_FIFO==2) assert(send_frame(&g_rzv_canfd3_priv)==-EAGAIN);
  assert(getreg32(0x12456000)==(0x1234567|CANFD_TMID_TMIDE));
  assert(getreg32(0x1245600c)==0x03020100);
  complete(&g_rzv_canfd3_priv); drained(&g_rzv_canfd3_priv);
  raw32(RZV_CANFD_BASE+RZV_CANFD_CFDRFID_OFFSET(1),0x1234567|CANFD_RFID_RFIDE);
  raw32(RZV_CANFD_BASE+RZV_CANFD_CFDRFPTR_OFFSET(1),15u<<CANFD_RFPTR_RFDLC_SHIFT);
  raw32(RZV_CANFD_BASE+RZV_CANFD_CFDRFFDSTS_OFFSET(1),CANFD_RFFDSTS_RFFDF|CANFD_RFFDSTS_RFBRS);
  for(unsigned int i=0;i<16;++i) raw32(RZV_CANFD_BASE+RZV_CANFD_CFDRFDF_OFFSET(1,i),0x03020100+i*0x04040404);
  raw32(RZV_CANFD_CFDRFSTS(1),0);
  rzv_canfd_rx_isr(g_rxf_irq,NULL,NULL);
  assert(received==1 && received_channel==3 && received_header.ch_dlc==15);
  assert(received_header.ch_edl && received_header.ch_brs && received_header.ch_extid);
  for(unsigned int i=0;i<64;++i) assert(received_data[i]==i);
  close_port(&g_rzv_canfd3_priv);
  assert(g_rzv_canfd0_priv.initialized && !standby[0]);
  assert(send_frame(&g_rzv_canfd0_priv)==CAN_MSGLEN(64));
  complete(&g_rzv_canfd0_priv); close_port(&g_rzv_canfd0_priv);
}
static void recovery(bool stuck)
{
  struct rzv_canfd_s *priv=&g_rzv_canfd3_priv;
  struct rzv_canfd_tx_status_s status;
  init(); assert(open_port(priv)==0);
  assert(send_frame(priv)==CAN_MSGLEN(64));
  unsigned int reads=mmio_reads;
  assert(rzv_canfd_ioctl(&priv->dev,CANIOC_RZV_GET_TX_STATUS,(uintptr_t)&status)==0);
  assert(mmio_reads==reads && status.active_seq==1 && status.open_count==1);
  reset_stuck[3]=stuck;
  assert(cancel(priv,1)==(stuck?-ETIMEDOUT:0));
  assert(standby[3] && standby_order<retired_order);
  assert(!enabled[priv->tx_irq] && !enabled[priv->err_irq]);
  assert(priv->irq_completed_seq==0 && priv->failed_seq==1);
  drained(priv); assert(cancel(priv,1)==-EALREADY);
  int requests=transmitted;
  assert(send_frame(priv)==CAN_MSGLEN(64));
  assert(priv->last_result==-EIO && priv->failed_seq==2);
  assert(!enabled[priv->tx_irq] && !enabled[priv->err_irq]);
  assert(transmitted==requests); drained(priv); close_port(priv);
  if(stuck) { assert(open_port(priv)==-ETIMEDOUT); assert(standby[3]); }
  reset_stuck[3]=false;
  raw32(RZV_CANFD_CFDRFSTS(1),0); /* stale data survives last close */
  unsigned int pops=fifo_pops[1];
  unsigned int clears=gic_clears;
  assert(open_port(priv)==0 && gic_clears>clears);
  assert(fifo_pops[1]==pops+1);
  assert(send_frame(priv)==CAN_MSGLEN(64));
  uint32_t next=priv->active_seq;
  rzv_canfd_tx_isr(priv->tx_irq,NULL,priv); /* stale IRQ, no mailbox result */
  assert(priv->pending && priv->active_seq==next);
  complete(priv); assert(priv->irq_completed_seq==next);
  unsigned int head=priv->dev.cd_xmit.tx_head;
  rzv_canfd_tx_isr(priv->tx_irq,NULL,priv); /* duplicate IRQ */
  assert(priv->dev.cd_xmit.tx_head==head);
  close_port(priv);
}
static void setup_failure(void)
{
  init(); attach_failure=attaches+2;
  assert(open_port(&g_rzv_canfd0_priv)==-ENOMEM);
  assert(standby[0] && !g_priv_by_fifo[0]);
  assert(g_rzv_canfd0_priv.tx_irq==-1 && g_rzv_canfd0_priv.err_irq==-1);
  assert(open_port(&g_rzv_canfd3_priv)==0);
  attach_failure=0;
  assert(open_port(&g_rzv_canfd0_priv)==0);
  close_port(&g_rzv_canfd0_priv);
  assert(g_priv_by_fifo[1]==&g_rzv_canfd3_priv);
  close_port(&g_rzv_canfd3_priv);
}
static void rollback(void)
{
  register_failure=2;
  assert(board_canfd_initialize()==-EIO);
  assert(removals==1 && !g_rzv_canfd0_priv.registered);
  assert(!g_rzv_canfd3_priv.registered && standby[0] && standby[3]);
  register_failure=0; assert(board_canfd_initialize()==0);
  int calls=config_calls; assert(board_canfd_initialize()==0);
  assert(config_calls==calls && attaches==2);
}
static void exhaustion(void)
{
  struct rzv_canfd_s *priv=&g_rzv_canfd3_priv;
  init(); assert(open_port(priv)==0); priv->submitted_seq=UINT32_MAX-1;
  assert(send_frame(priv)==CAN_MSGLEN(64)); complete(priv);
  assert(priv->submitted_seq==UINT32_MAX);
  assert(send_frame(priv)==CAN_MSGLEN(64));
  assert(priv->sequence_exhausted && priv->last_result==-EOVERFLOW);
  assert(standby[3]); drained(priv); close_port(priv);
  assert(open_port(priv)==-EOVERFLOW && standby[3]);
}
static void loopback(void)
{
  init();
  assert(open_port(&g_rzv_canfd0_priv)==0);
  assert(open_port(&g_rzv_canfd3_priv)==0);
  assert(standby[0] && standby[3]);
  assert(send_frame(&g_rzv_canfd0_priv)==CAN_MSGLEN(64));
  drained(&g_rzv_canfd0_priv);
  assert(send_frame(&g_rzv_canfd3_priv)==CAN_MSGLEN(64));
  drained(&g_rzv_canfd3_priv);
  assert(received==2 && received_channel==3);
  assert(g_rzv_canfd3_priv.irq_completed_seq==0);
  assert(standby[0] && standby[3]);
  close_port(&g_rzv_canfd0_priv);
  close_port(&g_rzv_canfd3_priv);
}
static void arguments(void)
{
  struct rzv_canfd_s *priv=&g_rzv_canfd3_priv;
  struct rzv_canfd_cancel_s req={0,1,1,0};
  init(); assert(open_port(priv)==0);
  assert(rzv_canfd_ioctl(&priv->dev,CANIOC_RZV_GET_TX_STATUS,0)==-EINVAL);
  assert(rzv_canfd_ioctl(&priv->dev,CANIOC_RZV_CANCEL_TX,0)==-EINVAL);
  assert(rzv_canfd_ioctl(&priv->dev,CANIOC_RZV_CANCEL_TX,(uintptr_t)&req)==-EINVAL);
  assert(send_frame(priv)==CAN_MSGLEN(64));
  if(TEST_FIFO!=2) { assert(cancel(priv,1)==-ENOTSUP); complete(priv); }
  else { assert(cancel(priv,99)==-ENOENT); assert(cancel(priv,1)==0); }
  drained(priv); close_port(priv);
}
static void stale_rx(void)
{
  init(); assert(open_port(&g_rzv_canfd0_priv)==0);
  raw32(RZV_CANFD_CFDRFSTS(1),0); fifo_stuck[1]=true;
  assert(open_port(&g_rzv_canfd3_priv)==-EIO);
  assert(fifo_pops[1]==8 && standby[3] && !standby[0]);
  fifo_stuck[1]=false;
  assert(open_port(&g_rzv_canfd3_priv)==0);
  assert(fifo_pops[1]==9);
  close_port(&g_rzv_canfd3_priv); close_port(&g_rzv_canfd0_priv);
}
static void tx_abort(void)
{
  struct rzv_canfd_s *priv=&g_rzv_canfd3_priv;
  init(); assert(open_port(priv)==0);
  assert(send_frame(priv)==CAN_MSGLEN(64));
  registers[index_of(RZV_CANFD_CFDTMSTS(TXMB0(3)))]=CANFD_TMSTS_TMTRF_ABORT;
  rzv_canfd_tx_isr(priv->tx_irq,NULL,priv);
  assert(priv->failed_seq==1 && priv->last_result==-EIO);
  assert(priv->irq_completed_seq==0); drained(priv);
  rzv_canfd_tx_isr(priv->tx_irq,NULL,priv); drained(priv);
  assert(send_frame(priv)==CAN_MSGLEN(64));
  complete(priv); assert(priv->irq_completed_seq==2);
  close_port(priv);
}
#endif
static void all_channels(void)
{
  uint32_t expected_counts[3]={0};
  unsigned int expected_ports=0, seen=0;
  init();
  for(unsigned int ch=0;ch<6;++ch)
    {
      bool configured=(TEST_CHANNEL_MASK & (1u<<ch))!=0;
      assert((rzv_canfd_port(ch)!=NULL)==configured);
      assert(rzv_canfd_initialize(ch)==(configured ? 0 : -ENODEV));
      if(configured) { expected_ports++; expected_counts[ch/2] |= 1u<<((ch&1)?0:16); }
    }
  assert(RZV_CANFD_NPORTS==expected_ports);
  for(unsigned int i=0;i<3;++i) assert(getreg32(RZV_CANFD_CFDGAFLCFG(i))==expected_counts[i]);
  assert(rzv_canfd_initialize(-1)==-EINVAL && rzv_canfd_initialize(6)==-EINVAL);
  for(unsigned int i=0;i<RZV_CANFD_NPORTS;++i)
    {
      struct rzv_canfd_s *priv=g_ports[i];
      unsigned int ch=priv->channel;
      unsigned int fifo=ch==3?1:(ch==1 && (TEST_CHANNEL_MASK & 8))?3:ch;
      char path[16]; snprintf(path,sizeof(path),"/dev/can%u",fifo);
      assert(priv->config->rxfifo==fifo);
      assert(strcmp(priv->devpath,path)==0);
      assert(!(seen & (1u<<fifo))); seen|=1u<<fifo;
      assert(priv->config->tx_source==368+(int)ch);
      assert(priv->config->err_source==354+(int)ch);
      assert(getreg32(RZV_CANFD_BASE+RZV_CANFD_CFDGAFL_P1_OFFSET(i))==(1u<<fifo));
      if(ch!=0 && ch!=3) standby[ch]=false; /* externally managed transceiver */
      assert(open_port(priv)==0);
      assert(g_priv_by_fifo[fifo]==priv);
      assert(getreg32(RZV_CANFD_CFDTMIEC(ch*2)) & 1u);
      assert(send_frame(priv)==CAN_MSGLEN(64));
      assert(getreg32(RZV_CANFD_BASE+RZV_CANFD_CFDTMID_OFFSET(ch*64))==(0x1234567|CANFD_TMID_TMIDE));
    }
  for(unsigned int i=0;i<RZV_CANFD_NPORTS;++i)
    {
      struct rzv_canfd_s *priv=g_ports[i]; unsigned int fifo=priv->config->rxfifo;
#ifdef TEST_LOOPBACK
      drained(priv); assert(priv->irq_completed_seq==0);
#else
      complete(priv); drained(priv); assert(priv->irq_completed_seq==1);
#endif
      if(priv->channel!=0 && priv->channel!=3) assert(cancel(priv,1)==-ENOTSUP);
      raw32(RZV_CANFD_BASE+RZV_CANFD_CFDRFID_OFFSET(fifo),0x120+priv->channel);
      raw32(RZV_CANFD_BASE+RZV_CANFD_CFDRFPTR_OFFSET(fifo),15u<<CANFD_RFPTR_RFDLC_SHIFT);
      raw32(RZV_CANFD_BASE+RZV_CANFD_CFDRFFDSTS_OFFSET(fifo),CANFD_RFFDSTS_RFFDF|CANFD_RFFDSTS_RFBRS);
      for(unsigned int word=0;word<16;++word)
        raw32(RZV_CANFD_BASE+RZV_CANFD_CFDRFDF_OFFSET(fifo,word),
              (0x03020100+word*0x04040404) ^ (priv->channel*0x01010101));
      raw32(RZV_CANFD_CFDRFSTS(fifo),0);
      unsigned int previous=received;
      rzv_canfd_rx_isr(g_rxf_irq,NULL,NULL);
      assert(received==previous+1 && received_channel==priv->channel);
      assert(received_header.ch_id==0x120+priv->channel);
      assert(received_header.ch_dlc==15 && received_header.ch_edl && received_header.ch_brs);
      for(unsigned int byte=0;byte<64;++byte)
        assert(received_data[byte]==(byte ^ priv->channel));
    }
  for(unsigned int i=0;i<RZV_CANFD_NPORTS;++i)
    {
      bool irq_enabled[6];
      for(unsigned int j=i+1;j<RZV_CANFD_NPORTS;++j)
        irq_enabled[j]=enabled[g_ports[j]->tx_irq];
      struct rzv_canfd_s *priv=g_ports[i]; close_port(priv);
      for(unsigned int j=i+1;j<RZV_CANFD_NPORTS;++j)
        assert(g_ports[j]->initialized && allocated[g_ports[j]->tx_irq] &&
               enabled[g_ports[j]->tx_irq]==irq_enabled[j]);
      assert(open_port(priv)==0); close_port(priv);
    }
}
int main(int argc,char **argv)
{
  assert(argc==2);
  if(!strcmp(argv[1],"all_channels")) all_channels();
  else if(!strcmp(argv[1],"payloads")) payloads();
  else if(!strcmp(argv[1],"loopback_failure")) loopback_failure();
  else if(!strcmp(argv[1],"priorities")) irq_priorities();
#if (TEST_CHANNEL_MASK & 9) == 9
  else if(!strcmp(argv[1],"priority_shared_failure")) priority_failure_case(0);
  else if(!strcmp(argv[1],"priority_tx_failure")) priority_failure_case(1);
  else if(!strcmp(argv[1],"priority_error_failure")) priority_failure_case(2);
  else if(!strcmp(argv[1],"priority_global_error_failure")) priority_global_error_failure();
  else if(!strcmp(argv[1],"loopback")) loopback();
  else if(!strcmp(argv[1],"routing")) routing();
  else if(!strcmp(argv[1],"cancel")) recovery(false);
  else if(!strcmp(argv[1],"stuck")) recovery(true);
  else if(!strcmp(argv[1],"setup")) setup_failure();
  else if(!strcmp(argv[1],"rollback")) rollback();
  else if(!strcmp(argv[1],"exhaustion")) exhaustion();
  else if(!strcmp(argv[1],"arguments")) arguments();
  else if(!strcmp(argv[1],"stale_rx")) stale_rx();
  else if(!strcmp(argv[1],"tx_abort")) tx_abort();

#endif
  else abort();
  return 0;
}
