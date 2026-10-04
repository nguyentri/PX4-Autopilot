/* SPDX-License-Identifier: BSD-3-Clause
 * Minimal host boundaries. Register/API contracts come from public headers.
 */
#ifndef RZV2H_DSHOT_BOUNDARY_H
#define RZV2H_DSHOT_BOUNDARY_H
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
#define MAX_IO_TIMERS 4
#define MAX_TIMER_IO_CHANNELS 4
#include "px4_arch/io_timer.h"
#include "dshot.h"
#include "rzv_dmac.h"
#include "hardware/rzv_dmac.h"
#include "hardware/rzv_gpt.h"
#define CHECK(condition, message) do { if (!(condition)) { \
  fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, message); exit(1); \
} } while (0)
#define PX4_INFO(...) ((void)0)
#define PX4_ERR(...) host_error(__VA_ARGS__)

/* RDK timer_config.cpp and dshot defconfig: GPT6A, 7B, logical9A,10B. */
const io_timers_t io_timers[4] = {
  {.timer_id=6}, {.timer_id=7}, {.timer_id=9}, {.timer_id=10}
};
const timer_io_channels_t timer_io_channels[4] = {
  {.timer_index=0, .timer_channel=1, .dshot={6,0,0,-1}},
  {.timer_index=1, .timer_channel=2, .dshot={7,1,1,-1}},
  {.timer_index=2, .timer_channel=1, .dshot={9,0,2,-1}},
  {.timer_index=3, .timer_channel=2, .dshot={10,1,3,-1}}
};
struct host_dma {
  struct rzv_dmac_config_s config;
  bool configured, enabled;
  unsigned words, starts;
  uint32_t armed_gtintad;
  uint32_t status;
  uint64_t completed;
};
struct host_gpt {
  uint32_t reg[64];
  bool running, up, level[2];
  unsigned starts, edges[2], duty[2];
  uint64_t edge_time[2][128];
  bool edge_level[2][128];
};
static struct host_gpt model_gpt[16];
static struct host_dma model_dma[4];
static uint64_t model_ticks;
static uint32_t clock_hz=96000000;
static unsigned allocated, errors, illegal_running_writes, blocked_dma_writes;
static char last_error[200];
static int fail_allocate=-1, fail_configure=-1, fail_start=-1, fail_disable=-1;
static bool suppress_dma, suppress_status;
/* Diagnostic isolation overrides, used only by protection/TC scenarios. */
static bool bypass_selectors, bypass_requests, bypass_dma_wp;
static uint64_t completion_delay;
static int error_dma=-1, fail_stop=-1;
static void host_error(const char *format, ...)
{
  va_list args;
  va_start(args, format);
  vsnprintf(last_error, sizeof(last_error), format, args);
  va_end(args);
  errors++;
}
static uint32_t rzv_get_gpt_clock_hz(void) { return clock_hz; }
static uint32_t getreg32(uintptr_t address);
static void putreg32(uint32_t value, uintptr_t address);
static void up_udelay(unsigned usec);
int io_timer_allocate_channel(unsigned channel, io_timer_channel_mode_t mode)
{
  CHECK(mode == IOTimerChanMode_Dshot, "unexpected timer allocation mode");
  if ((int)channel == fail_allocate) return -EBUSY;
  CHECK(!(allocated & (1u<<channel)), "timer double allocation");
  allocated |= 1u<<channel;
  return 0;
}
int io_timer_unallocate_channel(unsigned channel)
{
  CHECK(allocated & (1u<<channel), "unallocated timer released");
  allocated &= ~(1u<<channel);
  return 0;
}
int rzv_dmac_channel_configure(int channel, const struct rzv_dmac_config_s *config)
{
  if (channel == fail_configure) return -EIO;
  CHECK(channel >= 0 && channel < 4, "invalid DMA channel");
  CHECK(!model_dma[channel].configured, "DMA configured without release");
  CHECK(config->src_size == RZV_DMAC_SIZE_4BYTE &&
        config->dst_size == RZV_DMAC_SIZE_4BYTE &&
        config->src_addr_mode == RZV_DMAC_ADDR_INCREMENT &&
        config->dst_addr_mode == RZV_DMAC_ADDR_FIXED &&
        config->trigger == RZV_DMAC_TRIGGER_HW,
        "DMA peripheral transfer contract invalid");
  CHECK(config->src_addr % 64 == 0 && config->length % 4 == 0,
        "unaligned DMA source or word count");
  model_dma[channel].config=*config;
  model_dma[channel].configured=true;
  return 0;
}
int rzv_dmac_channel_start(int channel)
{
  struct host_dma *dma=&model_dma[channel];
  if (channel == fail_start) return -EIO;
  CHECK(dma->configured && !dma->enabled, "DMA started while unowned or enabled");
  dma->enabled=true;
  dma->words=0;
  dma->status=DMAC_CHSTAT_EN;
  dma->starts++;
  uintptr_t base=dma->config.dst_addr & ~(uintptr_t)0xff;
  dma->armed_gtintad=getreg32(base+RZV_GPT_GTINTAD_OFFSET);
  return 0;
}
int rzv_dmac_channel_disable(int channel)
{
  if (!bypass_selectors)
    for (unsigned ch=0;ch<16;ch++)
      CHECK(!model_gpt[ch].running, "DMA disable polling began before all GPT outputs stopped");
  if (channel == fail_disable) return -EIO;
  model_dma[channel].enabled=false;
  model_dma[channel].status &= ~DMAC_CHSTAT_EN;
  return 0;
}
int rzv_dmac_channel_stop(int channel)
{
  model_dma[channel].enabled=false;
  model_dma[channel].configured=false;
  model_dma[channel].status=0;
  /* Actual stop releases software ownership even when bus disable fails. */
  return channel == fail_disable || channel == fail_stop ? -EIO : 0;
}
uint32_t rzv_dmac_channel_status(int channel)
{
  struct host_dma *dma=&model_dma[channel];
  if (channel == error_dma && model_ticks > 96u*5u) return DMAC_CHSTAT_ER;
  if (suppress_status || (dma->status == DMAC_CHSTAT_TC &&
      model_ticks < dma->completed+completion_delay)) return DMAC_CHSTAT_EN;
  return dma->status;
}
#endif
