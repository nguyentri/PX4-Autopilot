/****************************************************************************
 *
 * Copyright (C) 2025 PX4 Development Team. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in
 *    the documentation and/or other materials provided with the
 *    distribution.
 * 3. Neither the name PX4 nor the names of its contributors may be
 *    used to endorse or promote products derived from this software
 *    without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 * FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
 * BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
 * OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
 * AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 * ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 *
 ****************************************************************************/

/**
 * @file dshot.c
 *
 * Hardware-accelerated DShot implementation for Renesas RA8
 * Uses GPT timers with DMA for efficient bit-level protocol generation
 */

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <syslog.h>

#include <nuttx/config.h>
#include <nuttx/arch.h>
#include <nuttx/irq.h>
#include <arch/board/board.h>

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/log.h>
#include <px4_arch/io_timer.h>
#include <drivers/drv_dshot.h>

#include "dshot.h"

#include "arm_internal.h"
#include "ra_dmac.h"
#include "ra_gpt.h"
#include "ra_gpio.h"
#include "ra_mstp.h"
#include <arch/ra8/ra8p1_irq.h>
#include "hardware/ra8p1/ra_gpt32.h"

extern const io_timers_t io_timers[MAX_IO_TIMERS];
extern const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS];

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

#define DSHOT_MAX_CHANNELS       4
#define DSHOT_FRAME_BITS         16
#define DSHOT_THROTTLE_BITS      11
#define DSHOT_TELEMETRY_BIT      1
#define DSHOT_CHECKSUM_BITS      4

#define DSHOT150_FREQ            150000u
#define DSHOT300_FREQ            300000u
#define DSHOT600_FREQ            600000u
#define DSHOT1200_FREQ           1200000u

#define DSHOT_T0H_PERCENT        37.5f
#define DSHOT_T1H_PERCENT        75.0f

/* Use board-defined PCLKD frequency (250MHz for RA8P1) */
#ifdef BOARD_PCLKD_FREQUENCY
#  define PCLKD_FREQUENCY        BOARD_PCLKD_FREQUENCY
#else
#  define PCLKD_FREQUENCY        250000000u  /* Default to 250MHz for RA8P1 */
#endif

#define BDSHOT_OFFLINE_COUNT     400

/****************************************************************************
 * Private Types
 ****************************************************************************/

typedef struct
{
  bool     initialized;
  uint8_t  io_channel;
  uint8_t  timer_index;
  uint8_t  gpt_channel;
  uint8_t  gpt_output;
  uint32_t gpio_pin;
  int8_t   dma_channel;
  ra_dmac_handle_t dma_handle;
  uint32_t dma_dest;
  uint32_t bit_period_ticks;
  uint32_t t0h_ticks;
  uint32_t t1h_ticks;
  uint16_t current_frame;
  uint32_t dma_buffer[DSHOT_FRAME_BITS];

  /* BDShot telemetry */

  uint16_t erpm;
  uint32_t crc_error_count;
  uint32_t frame_error_count;
  uint32_t no_response_count;
} dshot_channel_t;

/****************************************************************************
 * Private Data
 ****************************************************************************/

static bool g_dma_available =
#ifdef CONFIG_RA_DMAC
  true;
#else
  false;
#endif

static bool g_bdshot_enabled = false;
static uint32_t g_active_channels = 0;
static uint32_t g_dshot_frequency = 0;
static bool g_dmac_initialized = false;

static dshot_channel_t g_channels[DSHOT_MAX_CHANNELS];

static const ra_mstp_module_t kGptMstpMap[] = {
  RA_MSTP_GPT0,  RA_MSTP_GPT1,  RA_MSTP_GPT2,  RA_MSTP_GPT3,
  RA_MSTP_GPT4,  RA_MSTP_GPT5,  RA_MSTP_GPT6,  RA_MSTP_GPT7,
  RA_MSTP_GPT8,  RA_MSTP_GPT9,  RA_MSTP_GPT10, RA_MSTP_GPT11,
  RA_MSTP_GPT12, RA_MSTP_GPT13
};

static const uint16_t kGptElcCaptureA[] = {
  RA_ELC_GPT0_CAPTURE_COMPARE_A,
  RA_ELC_GPT1_CAPTURE_COMPARE_A,
  RA_ELC_GPT2_CAPTURE_COMPARE_A,
  RA_ELC_GPT3_CAPTURE_COMPARE_A,
  RA_ELC_GPT4_CAPTURE_COMPARE_A,
  RA_ELC_GPT5_CAPTURE_COMPARE_A,
  RA_ELC_GPT6_CAPTURE_COMPARE_A,
  RA_ELC_GPT7_CAPTURE_COMPARE_A,
  RA_ELC_GPT8_CAPTURE_COMPARE_A,
  RA_ELC_GPT9_CAPTURE_COMPARE_A,
  RA_ELC_GPT10_CAPTURE_COMPARE_A,
  RA_ELC_GPT11_CAPTURE_COMPARE_A,
  RA_ELC_GPT12_CAPTURE_COMPARE_A,
  RA_ELC_GPT13_CAPTURE_COMPARE_A
};

static bool dshot_map_channel(uint8_t logical_channel, dshot_channel_t *ch)
{
  if (logical_channel >= MAX_TIMER_IO_CHANNELS)
    {
      PX4_ERR("DShot channel %u exceeds timer IO channels (%u)",
              logical_channel, MAX_TIMER_IO_CHANNELS);
      return false;
    }

  const timer_io_channels_t *cfg = &timer_io_channels[logical_channel];

  if (cfg->timer_index >= MAX_IO_TIMERS)
    {
      PX4_ERR("DShot channel %u invalid timer index %u",
              logical_channel, cfg->timer_index);
      return false;
    }

  const io_timers_t *timer = &io_timers[cfg->timer_index];
  uint8_t gpt_channel = (cfg->dshot.gpt_channel != 0) ? cfg->dshot.gpt_channel : timer->timer_id;

  if (gpt_channel == 0xFF || gpt_channel > 13)
    {
      PX4_ERR("Timer %u lacks valid GPT channel id", cfg->timer_index);
      return false;
    }

  ch->io_channel = logical_channel;
  ch->timer_index = cfg->timer_index;
  ch->gpt_channel = gpt_channel;
  ch->gpt_output = (cfg->timer_channel == 1) ? 0 : 1;
  ch->gpio_pin = cfg->gpio_out;
  ch->dma_channel = cfg->dshot.dma_channel;
  ch->dma_handle = NULL;

  const uint32_t compare_offset = (ch->gpt_output == 0)
                                  ? R_GPT32_GTCCRA_OFFSET
                                  : R_GPT32_GTCCRB_OFFSET;
  ch->dma_dest = R_GPT32_CH_BASE(ch->gpt_channel) + compare_offset;

  return true;
}

/****************************************************************************
 * Private Functions
 ****************************************************************************/

static inline void gpt_putreg32(uint8_t ch, uint32_t offset, uint32_t val)
{
  putreg32(val, R_GPT32_CH_BASE(ch) + offset);
}

static inline uint32_t gpt_getreg32(uint8_t ch, uint32_t offset)
{
  return getreg32(R_GPT32_CH_BASE(ch) + offset);
}

static void dshot_calculate_timing(uint32_t frequency, uint32_t *bit_period,
                                    uint32_t *t0h, uint32_t *t1h)
{
  *bit_period = PCLKD_FREQUENCY / frequency;
  *t0h = (uint32_t)(*bit_period * DSHOT_T0H_PERCENT / 100.0f);
  *t1h = (uint32_t)(*bit_period * DSHOT_T1H_PERCENT / 100.0f);
}

static uint16_t dshot_encode_frame(uint16_t throttle, bool telemetry)
{
  uint16_t frame = 0;
  uint16_t checksum = 0;
  uint16_t checksum_data;

  frame = (throttle & 0x7FFu) << 5;
  frame |= (telemetry ? 1u : 0u) << 4;

  checksum_data = frame >> 4;

  for (int i = 0; i < 3; i++)
    {
      checksum ^= (checksum_data & 0xFu);
      checksum_data >>= 4;
    }

  frame |= (checksum & 0xFu);
  return frame;
}

/**
 * Configure GPT channel for DShot PWM output with saw-wave mode
 */

static int gpt_setup_channel(uint8_t gpt_channel,
                              uint32_t bit_period_ticks)
{
  /* Unlock write protection */

  gpt_putreg32(gpt_channel, R_GPT32_GTWP_OFFSET, GPT_GTWP_PRKEY);

  /* Stop and clear */

  gpt_putreg32(gpt_channel, R_GPT32_GTSTP_OFFSET, 1u << gpt_channel);
  gpt_putreg32(gpt_channel, R_GPT32_GTCLR_OFFSET, 1u << gpt_channel);

  /* Saw-wave up-count, prescaler = PCLKD/1 */

  uint32_t gtcr = GPT_GTCR_MD_SAW_WAVE_UP | GPT_GTCR_TPCS_PCLKD_1;
  gpt_putreg32(gpt_channel, R_GPT32_GTCR_OFFSET, gtcr);

  /* Set period (GTPR counts from 0..GTPR) */

  uint32_t period = (bit_period_ticks > 0) ? (bit_period_ticks - 1u) : 0u;
  gpt_putreg32(gpt_channel, R_GPT32_GTPR_OFFSET, period);

  /* Initial low, go high at compare, go low at overflow
   * This produces: |<-- low -->|<-- high -->|
   * Where high time = GTCCRA, total period = GTPR
   */

  gpt_putreg32(gpt_channel, R_GPT32_GTIOR_OFFSET, GPT_GTIOR_PWM_HIGH_A);

  /* Enable buffer for GTCCRA for glitch-free duty updates */

  gpt_putreg32(gpt_channel, R_GPT32_GTBER_OFFSET, GPT_GTBER_CCRA);

  /* Re-enable write protection */

  gpt_putreg32(gpt_channel, R_GPT32_GTWP_OFFSET,
               GPT_GTWP_PRKEY | GPT_GTWP_WP);

  return 0;
}

static void gpt_start(uint8_t gpt_channel)
{
  gpt_putreg32(gpt_channel, R_GPT32_GTWP_OFFSET, GPT_GTWP_PRKEY);
  gpt_putreg32(gpt_channel, R_GPT32_GTSTR_OFFSET, 1u << gpt_channel);
  gpt_putreg32(gpt_channel, R_GPT32_GTWP_OFFSET,
               GPT_GTWP_PRKEY | GPT_GTWP_WP);
}

static void gpt_stop(uint8_t gpt_channel)
{
  gpt_putreg32(gpt_channel, R_GPT32_GTWP_OFFSET, GPT_GTWP_PRKEY);
  gpt_putreg32(gpt_channel, R_GPT32_GTSTP_OFFSET, 1u << gpt_channel);
  gpt_putreg32(gpt_channel, R_GPT32_GTWP_OFFSET,
               GPT_GTWP_PRKEY | GPT_GTWP_WP);
}


static inline uint16_t dshot_get_elc_event(uint8_t gpt_channel)
{
  if (gpt_channel < (sizeof(kGptElcCaptureA) / sizeof(kGptElcCaptureA[0])))
    {
      return kGptElcCaptureA[gpt_channel];
    }

  return RA_ELC_GPT0_CAPTURE_COMPARE_A;
}

static void gpt_enable_overflow_dma_request(uint8_t gpt_channel)
{
  irqstate_t flags = enter_critical_section();

  gpt_putreg32(gpt_channel, R_GPT32_GTWP_OFFSET, GPT_GTWP_PRKEY);

  uint32_t gtintad = gpt_getreg32(gpt_channel, R_GPT32_GTINTAD_OFFSET);
  gtintad |= GPT_GTINTAD_ADTRAUEN;

  gpt_putreg32(gpt_channel, R_GPT32_GTADTRA_OFFSET,
               gpt_getreg32(gpt_channel, R_GPT32_GTPR_OFFSET));
  gpt_putreg32(gpt_channel, R_GPT32_GTINTAD_OFFSET, gtintad);

  gpt_putreg32(gpt_channel, R_GPT32_GTWP_OFFSET,
               GPT_GTWP_PRKEY | GPT_GTWP_WP | GPT_GTWP_CMNWP);

  leave_critical_section(flags);
}

static int dshot_dma_setup(dshot_channel_t *ch)
{
#ifdef CONFIG_RA_DMAC
  if (!g_dma_available)
    {
      return -ENODEV;
    }

  if (!g_dmac_initialized)
    {
      if (ra_dmac_initialize() < 0)
        {
          g_dma_available = false;
          return -ENODEV;
        }

      g_dmac_initialized = true;
    }

  if (ch->dma_handle != NULL)
    {
      return OK;
    }

  gpt_enable_overflow_dma_request(ch->gpt_channel);

  ra_dmac_config_t dma_config;
  memset(&dma_config, 0, sizeof(dma_config));

  dma_config.mode = RA_DMAC_MODE_REPEAT;
  dma_config.repeat_area = RA_DMAC_REPEAT_AREA_SRC;
  dma_config.size = RA_DMAC_SIZE_32BIT;
  dma_config.src_addr_mode = RA_DMAC_ADDR_INCR;
  dma_config.dest_addr_mode = RA_DMAC_ADDR_FIXED;
  dma_config.trigger = RA_DMAC_TRIGGER_HW;
  dma_config.src_addr = (uint32_t)ch->dma_buffer;
  dma_config.dest_addr = ch->dma_dest;
  dma_config.transfer_count = DSHOT_FRAME_BITS;
  dma_config.block_count = 1;
  dma_config.elc_src = dshot_get_elc_event(ch->gpt_channel);

  int ret;

  if (ch->dma_channel >= 0)
    {
      ret = ra_dmac_open_channel(&ch->dma_handle, &dma_config, ch->dma_channel);
    }
  else
    {
      ret = ra_dmac_open(&ch->dma_handle, &dma_config);
    }

  if (ret < 0)
    {
      PX4_ERR("Failed to open DMAC for GPT%u (%d)", ch->gpt_channel, ret);
      ch->dma_handle = NULL;
      return ret;
    }

  return OK;
#else
  return -ENODEV;
#endif
}

static inline void dshot_prepare_buffer(dshot_channel_t *ch)
{
  for (int bit = DSHOT_FRAME_BITS - 1; bit >= 0; bit--)
    {
      const bool one = (ch->current_frame >> bit) & 1u;
      const uint32_t high_ticks = one ? ch->t1h_ticks : ch->t0h_ticks;
      ch->dma_buffer[DSHOT_FRAME_BITS - 1 - bit] = high_ticks;
    }
}

static int dshot_dma_start(dshot_channel_t *ch)
{
#ifdef CONFIG_RA_DMAC
  if (dshot_dma_setup(ch) < 0 || ch->dma_handle == NULL)
    {
      return -ENODEV;
    }

  int ret = ra_dmac_reset(ch->dma_handle,
                          (uint32_t)ch->dma_buffer,
                          ch->dma_dest,
                          DSHOT_FRAME_BITS);

  if (ret < 0)
    {
      PX4_ERR("DMAC reset failed (GPT%u): %d", ch->gpt_channel, ret);
      return ret;
    }

  ret = ra_dmac_enable(ch->dma_handle);

  if (ret < 0)
    {
      PX4_ERR("DMAC enable failed (GPT%u): %d", ch->gpt_channel, ret);
      return ret;
    }

  return OK;
#else
  return -ENODEV;
#endif
}

static inline void dshot_dma_stop(dshot_channel_t *ch)
{
#ifdef CONFIG_RA_DMAC
  if (ch->dma_handle != NULL)
    {
      ra_dmac_disable(ch->dma_handle);
    }
#else
  (void)ch;
#endif
}

/****************************************************************************
 * Public Functions
 ****************************************************************************/

/**
 * Initialize DShot driver
 */

int up_dshot_init(uint32_t channel_mask, unsigned dshot_pwm_freq,
                  bool enable_bidirectional_dshot)
{
  if (dshot_pwm_freq != DSHOT150_FREQ &&
      dshot_pwm_freq != DSHOT300_FREQ &&
      dshot_pwm_freq != DSHOT600_FREQ &&
      dshot_pwm_freq != DSHOT1200_FREQ)
    {
      return -EINVAL;
    }

  g_dshot_frequency = dshot_pwm_freq;
  g_bdshot_enabled = enable_bidirectional_dshot;
  g_active_channels = 0;

  for (uint8_t ch_idx = 0; ch_idx < DSHOT_MAX_CHANNELS; ch_idx++)
    {
      if (!(channel_mask & (1u << ch_idx)))
        {
          continue;
        }

      dshot_channel_t *ch = &g_channels[ch_idx];

      if (!dshot_map_channel(ch_idx, ch))
        {
          PX4_ERR("Skipping DShot channel %u (no mapping)", ch_idx);
          continue;
        }

      if (ch->gpio_pin != 0)
        {
          ra_gpioconfig(ch->gpio_pin);
        }

      if (ch->gpt_channel < (sizeof(kGptMstpMap) / sizeof(kGptMstpMap[0])))
        {
          ra_mstp_start(kGptMstpMap[ch->gpt_channel]);
        }

      dshot_calculate_timing(dshot_pwm_freq, &ch->bit_period_ticks,
                             &ch->t0h_ticks, &ch->t1h_ticks);

      gpt_setup_channel(ch->gpt_channel, ch->bit_period_ticks);

      if (g_dma_available)
        {
          dshot_dma_setup(ch);
        }

      ch->current_frame = 0;
      memset(ch->dma_buffer, 0, sizeof(ch->dma_buffer));
      ch->erpm = 0;
      ch->crc_error_count = 0;
      ch->frame_error_count = 0;
      ch->no_response_count = 0;
      ch->initialized = true;
      g_active_channels |= (1u << ch_idx);
    }

  if (!g_dma_available)
    {
      syslog(LOG_WARNING,
             "DShot: DMA not available, using software fallback\n");
    }

  return (int)g_active_channels;
}

/**
 * Set motor throttle data
 */

void dshot_motor_data_set(unsigned channel, uint16_t throttle,
                          bool telemetry)
{
  if (channel >= DSHOT_MAX_CHANNELS)
    {
      return;
    }

  dshot_channel_t *ch = &g_channels[channel];
  if (!ch->initialized)
    {
      return;
    }

  ch->current_frame = dshot_encode_frame(throttle, telemetry);
}

/**
 * Trigger transmission of DShot frames
 */

void up_dshot_trigger(void)
{
#ifdef CONFIG_RA_DMAC
  if (g_dma_available)
    {
      for (uint8_t ch_idx = 0; ch_idx < DSHOT_MAX_CHANNELS; ch_idx++)
        {
          if (!(g_active_channels & (1u << ch_idx)))
            {
              continue;
            }

          dshot_channel_t *ch = &g_channels[ch_idx];
          if (!ch->initialized || ch->current_frame == 0)
            {
              continue;
            }

          dshot_prepare_buffer(ch);

          if (dshot_dma_start(ch) < 0)
            {
              continue;
            }

          /* Start timer - DMA will automatically update GTCCRA */

          gpt_start(ch->gpt_channel);

          /* Wait for frame completion
           * Each bit takes (1/frequency) seconds
           * Total frame time = 16 bits + small margin
           */

          uint32_t bit_time_us = (1000000u + g_dshot_frequency / 2u) /
                                 g_dshot_frequency;
          up_udelay(bit_time_us * DSHOT_FRAME_BITS + 10u);

          /* Stop timer */

          gpt_stop(ch->gpt_channel);

          /* Disable DMA for next cycle */

          dshot_dma_stop(ch);
        }
    }
  else
#endif
    {
      /* Software fallback if DMA not available
       * Note: This is a simplified implementation
       * Full bit-banging would be CPU-intensive
       */

      syslog(LOG_WARNING,
             "DShot: Software bit-banging not fully implemented\n");
    }
}

/**
 * Arm/disarm DShot outputs
 */

int up_dshot_arm(bool armed)
{
  if (!armed)
    {
      /* Send zero throttle to all channels */

      for (uint8_t ch = 0; ch < DSHOT_MAX_CHANNELS; ch++)
        {
          if (g_active_channels & (1u << ch))
            {
              dshot_motor_data_set(ch, 0, false);
            }
        }

      up_dshot_trigger();
    }

  return 0;
}

/**
 * BDShot telemetry functions
 */

int up_bdshot_num_erpm_ready(void)
{
  if (!g_bdshot_enabled)
    {
      return 0;
    }

  int count = 0;
  for (uint8_t ch = 0; ch < DSHOT_MAX_CHANNELS; ch++)
    {
      if ((g_active_channels & (1u << ch)) &&
          g_channels[ch].erpm > 0)
        {
          count++;
        }
    }

  return count;
}

int up_bdshot_get_erpm(uint8_t channel, int *erpm)
{
  if (channel >= DSHOT_MAX_CHANNELS || !erpm)
    {
      return -EINVAL;
    }

  if (!g_channels[channel].initialized)
    {
      return -ENODEV;
    }

  *erpm = (int)g_channels[channel].erpm;

  /* Check for offline ESC */

  if (g_channels[channel].no_response_count > BDSHOT_OFFLINE_COUNT)
    {
      return -ETIMEDOUT;
    }

  return 0;
}

int up_bdshot_channel_status(uint8_t channel)
{
  if (channel >= DSHOT_MAX_CHANNELS)
    {
      return -EINVAL;
    }

  if (!g_channels[channel].initialized)
    {
      return -ENODEV;
    }

  /* Return -1 if ESC is offline */

  if (g_channels[channel].no_response_count > BDSHOT_OFFLINE_COUNT)
    {
      return -1;
    }

  return 0;
}

void up_bdshot_status(void)
{
  syslog(LOG_INFO, "DShot Status:\n");
  syslog(LOG_INFO, "  Frequency: %u Hz\n", (unsigned int)g_dshot_frequency);
  syslog(LOG_INFO, "  Active channels: 0x%x\n",
         (unsigned int)g_active_channels);
  syslog(LOG_INFO, "  BDShot: %s\n",
         g_bdshot_enabled ? "enabled" : "disabled");
  syslog(LOG_INFO, "  DMA: %s\n",
         g_dma_available ? "available" : "unavailable");

  for (uint8_t ch = 0; ch < DSHOT_MAX_CHANNELS; ch++)
    {
      if (g_active_channels & (1u << ch))
        {
          dshot_channel_t *chan = &g_channels[ch];
          syslog(LOG_INFO, "  Channel %u (GPT%u):\n", ch,
                 chan->gpt_channel);
          syslog(LOG_INFO, "    eRPM: %u\n", chan->erpm);
          syslog(LOG_INFO, "    CRC errors: %lu\n",
                 (unsigned long)chan->crc_error_count);
          syslog(LOG_INFO, "    Frame errors: %lu\n",
                 (unsigned long)chan->frame_error_count);
          syslog(LOG_INFO, "    No response: %lu\n",
                 (unsigned long)chan->no_response_count);
        }
    }
}
