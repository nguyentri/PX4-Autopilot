/****************************************************************************
 *
 *   Copyright (C) 2025-2026 PX4 Development Team. All rights reserved.
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
 * AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF
 * THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
 * DAMAGE.
 *
 ****************************************************************************/

/**
 * @file dshot.c
 *
 * RZ/V2H DShot TX using one GPT output and one hardware-triggered DMAC
 * channel per motor. Bidirectional telemetry remains unsupported until a
 * bounded interrupt or capture-DMA receive path is implemented.
 */

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>

#include <nuttx/config.h>
#include <nuttx/arch.h>

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/log.h>
#include <px4_arch/io_timer.h>
#include <drivers/drv_dshot.h>

#include "dshot.h"
#include "arm_internal.h"
#include "rzv_clock.h"
#include "rzv_dmac.h"
#include "hardware/rzv_dmac.h"
#include "hardware/rzv_gpt.h"

#define DSHOT_MAX_CHANNELS        4u
#define DSHOT_FRAME_BITS          16u
#define DSHOT_DMA_WORDS           17u
#define DSHOT_DMA_ALIGN           64u
#define DSHOT_FRAME_TIMEOUT_US    20u

#define DSHOT150_FREQ             150000u
#define DSHOT300_FREQ             300000u
#define DSHOT600_FREQ             600000u
#define DSHOT1200_FREQ            1200000u

/* DMkSEL uses the DMAC activation-source numbering from Renesas bsp_dmac.h,
 * not the ELC interrupt numbering in rzv2h_irq.h. */

#define DSHOT_GPT_OVF_EVENT_U0_BASE  257u
#define DSHOT_GPT_OVF_EVENT_U1_BASE  321u

typedef struct
{
  uint8_t logical_channel;
  uint8_t timer_index;
  uint8_t gpt_channel;
  bool channel_b;
  int8_t dma_channel;
  uintptr_t gpt_base;
  uint32_t active_compare_offset;
  uint32_t buffer_compare_offset;
  uint32_t bit_period_ticks;
  uint32_t t0h_compare;
  uint32_t t1h_compare;
  uint32_t first_compare;
  uint32_t second_compare;
  uint16_t throttle_value;
  bool telemetry_request;
  uint32_t dma_buffer[DSHOT_DMA_WORDS]
    __attribute__((aligned(DSHOT_DMA_ALIGN)));
} __attribute__((aligned(DSHOT_DMA_ALIGN))) dshot_channel_t;

static dshot_channel_t g_channels[DSHOT_MAX_CHANNELS];
static uint32_t g_active_channels;
static uint32_t g_frame_timeout_us;
static bool g_armed;

static inline void gpt_putreg32(const dshot_channel_t *channel,
                                uint32_t offset, uint32_t value)
{
  putreg32(value, channel->gpt_base + offset);
}

static inline uint32_t gpt_getreg32(const dshot_channel_t *channel,
                                    uint32_t offset)
{
  return getreg32(channel->gpt_base + offset);
}

static int dshot_gpt_overflow_event(uint8_t gpt_channel)
{
  if (gpt_channel < 8u)
    {
      return (int)(DSHOT_GPT_OVF_EVENT_U0_BASE + gpt_channel);
    }

  if (gpt_channel < 16u)
    {
      return (int)(DSHOT_GPT_OVF_EVENT_U1_BASE + gpt_channel - 8u);
    }

  return -EINVAL;
}

static void gpt_set_selected_duty(const dshot_channel_t *channel,
                                  uint32_t duty_mode)
{
  uint32_t duty = gpt_getreg32(channel, RZV_GPT_GTUDDTYC_OFFSET);
  uint32_t mask = channel->channel_b ? GPT_GTUDDTYC_OBDTY_MASK :
                  GPT_GTUDDTYC_OADTY_MASK;
  uint32_t shift = channel->channel_b ? GPT_GTUDDTYC_OBDTY_SHIFT :
                   GPT_GTUDDTYC_OADTY_SHIFT;

  duty &= ~mask;
  duty |= (duty_mode << shift) & mask;

  /* Latch the direction/duty update using the sequence required by GPT. */

  gpt_putreg32(channel, RZV_GPT_GTUDDTYC_OFFSET,
               duty | GPT_GTUDDTYC_UD | GPT_GTUDDTYC_UDF);
  gpt_putreg32(channel, RZV_GPT_GTUDDTYC_OFFSET,
               duty | GPT_GTUDDTYC_UD);
}

static void gpt_force_safe_low(const dshot_channel_t *channel)
{
  uint32_t mask = RZV_GPT_LOGICAL_UNIT_BIT(channel->gpt_channel);
  uint32_t gtior;

  gpt_putreg32(channel, RZV_GPT_GTWP_OFFSET, GPT_GTWP_UNLOCK);
  gpt_set_selected_duty(channel, GPT_UDDTYC_DTY_0_PERCENT);
  gpt_putreg32(channel, RZV_GPT_GTSTP_OFFSET, mask);

  gtior = gpt_getreg32(channel, RZV_GPT_GTIOR_OFFSET);
  gtior &= channel->channel_b ? ~GPT_GTIOR_OBE : ~GPT_GTIOR_OAE;
  gpt_putreg32(channel, RZV_GPT_GTIOR_OFFSET, gtior);
  gpt_putreg32(channel, RZV_GPT_GTWP_OFFSET, GPT_GTWP_LOCK);
}

static void gpt_setup_channel(const dshot_channel_t *channel)
{
  uint32_t mask = RZV_GPT_LOGICAL_UNIT_BIT(channel->gpt_channel);
  uint32_t gtior;
  uint32_t gtber;

  gpt_putreg32(channel, RZV_GPT_GTWP_OFFSET, GPT_GTWP_UNLOCK);
  gpt_putreg32(channel, RZV_GPT_GTSTP_OFFSET, mask);
  gpt_putreg32(channel, RZV_GPT_GTCR_OFFSET,
               GPT_GTCR_MD_SAW | (GPT_TPCS_DIV1 << GPT_GTCR_TPCS_SHIFT));
  gpt_putreg32(channel, RZV_GPT_GTPR_OFFSET,
               channel->bit_period_ticks - 1u);
  gpt_putreg32(channel, RZV_GPT_GTPBR_OFFSET,
               channel->bit_period_ticks - 1u);

  gtior = gpt_getreg32(channel, RZV_GPT_GTIOR_OFFSET);
  gtber = gpt_getreg32(channel, RZV_GPT_GTBER_OFFSET);

  if (channel->channel_b)
    {
      gtior &= ~(GPT_GTIOR_GTIOB_MASK | GPT_GTIOR_OBE);
      gtior |= GPT_GTIOR_GTIOB_HIGH_CMP_LOW | GPT_GTIOR_OBE;
      gtber &= ~GPT_GTBER_CCRB_MASK;
      gtber |= 1u << GPT_GTBER_CCRB_SHIFT;
    }
  else
    {
      gtior &= ~(GPT_GTIOR_GTIOA_MASK | GPT_GTIOR_OAE);
      gtior |= GPT_GTIOR_GTIOA_HIGH_CMP_LOW | GPT_GTIOR_OAE;
      gtber &= ~GPT_GTBER_CCRA_MASK;
      gtber |= 1u << GPT_GTBER_CCRA_SHIFT;
    }

  gpt_putreg32(channel, RZV_GPT_GTIOR_OFFSET, gtior);
  gpt_putreg32(channel, RZV_GPT_GTBER_OFFSET, gtber);
  gpt_putreg32(channel, channel->active_compare_offset, 0);
  gpt_putreg32(channel, channel->buffer_compare_offset, 0);
  gpt_set_selected_duty(channel, GPT_UDDTYC_DTY_0_PERCENT);
  gpt_putreg32(channel, RZV_GPT_GTST_OFFSET, 0);
  gpt_putreg32(channel, RZV_GPT_GTWP_OFFSET, GPT_GTWP_LOCK);
}

static void gpt_prime_frame(const dshot_channel_t *channel)
{
  uint32_t gtior;

  gpt_putreg32(channel, RZV_GPT_GTWP_OFFSET, GPT_GTWP_UNLOCK);
  gpt_putreg32(channel, RZV_GPT_GTSTP_OFFSET,
               RZV_GPT_LOGICAL_UNIT_BIT(channel->gpt_channel));
  gpt_putreg32(channel, RZV_GPT_GTCLR_OFFSET,
               RZV_GPT_LOGICAL_UNIT_BIT(channel->gpt_channel));
  gpt_putreg32(channel, channel->active_compare_offset,
               channel->first_compare);
  gpt_putreg32(channel, channel->buffer_compare_offset,
               channel->second_compare);
  gpt_set_selected_duty(channel, GPT_UDDTYC_DTY_REGISTER);

  /* Disarm forces the selected pin low and disables its GPT output. Restore
   * only that output after the first two compare values are safely primed. */

  gtior = gpt_getreg32(channel, RZV_GPT_GTIOR_OFFSET);
  gtior |= channel->channel_b ? GPT_GTIOR_OBE : GPT_GTIOR_OAE;
  gpt_putreg32(channel, RZV_GPT_GTIOR_OFFSET, gtior);
  gpt_putreg32(channel, RZV_GPT_GTWP_OFFSET, GPT_GTWP_LOCK);
}

static void gpt_start(const dshot_channel_t *channel)
{
  gpt_putreg32(channel, RZV_GPT_GTSTR_OFFSET,
               RZV_GPT_LOGICAL_UNIT_BIT(channel->gpt_channel));
}

static uint16_t dshot_encode_frame(uint16_t throttle, bool telemetry)
{
  uint16_t payload = (uint16_t)(((throttle & 0x7ffu) << 1) |
                                (telemetry ? 1u : 0u));
  uint16_t checksum = (uint16_t)((payload ^ (payload >> 4) ^
                                  (payload >> 8)) & 0x0fu);

  return (uint16_t)((payload << 4) | checksum);
}

static void dshot_prepare_frame(dshot_channel_t *channel)
{
  uint16_t frame = dshot_encode_frame(channel->throttle_value,
                                      channel->telemetry_request);
  uint32_t compare[DSHOT_FRAME_BITS + 2u];
  unsigned int i;

  for (i = 0; i < DSHOT_FRAME_BITS; i++)
    {
      compare[i] = (frame & (1u << (15u - i))) != 0u ?
                   channel->t1h_compare : channel->t0h_compare;
    }

  compare[DSHOT_FRAME_BITS] = 0;
  compare[DSHOT_FRAME_BITS + 1u] = 0;
  /* GTIOR 0x09 starts low and only drives high at the first cycle end. Use
   * that initial cycle as a low preamble; bit 0 is transferred into the
   * active compare register at the first overflow. */

  channel->first_compare = 0;
  channel->second_compare = compare[0];

  for (i = 0; i < DSHOT_DMA_WORDS; i++)
    {
      channel->dma_buffer[i] = compare[i + 1u];
    }
}

static int dshot_map_channel(unsigned int logical_channel,
                             dshot_channel_t *channel)
{
  const timer_io_channels_t *timer_channel;
  const io_timers_t *timer;

  if (logical_channel >= MAX_TIMER_IO_CHANNELS || channel == NULL)
    {
      return -EINVAL;
    }

  timer_channel = &timer_io_channels[logical_channel];
  if (timer_channel->timer_index >= MAX_IO_TIMERS ||
      (timer_channel->timer_channel != 1u &&
       timer_channel->timer_channel != 2u))
    {
      return -EINVAL;
    }

  timer = &io_timers[timer_channel->timer_index];
  if (!RZV_GPT_LOGICAL_CHANNEL_VALID(timer->timer_id) ||
      timer_channel->dshot.timer != timer->timer_id ||
      timer_channel->dshot.channel != timer_channel->timer_channel - 1u ||
      timer_channel->dshot.dma_channel < 0 ||
      timer_channel->dshot.dma_channel >= RZV_DMAC_CHANNEL_COUNT)
    {
      return -EINVAL;
    }

  memset(channel, 0, sizeof(*channel));
  channel->logical_channel = (uint8_t)logical_channel;
  channel->timer_index = timer_channel->timer_index;
  channel->gpt_channel = (uint8_t)timer->timer_id;
  channel->channel_b = timer_channel->timer_channel == 2u;
  channel->dma_channel = timer_channel->dshot.dma_channel;
  channel->gpt_base = RZV_GPT_LOGICAL_BASE(timer->timer_id);
  channel->active_compare_offset = channel->channel_b ?
                                   RZV_GPT_GTCCRB_OFFSET :
                                   RZV_GPT_GTCCRA_OFFSET;
  channel->buffer_compare_offset = channel->channel_b ?
                                   RZV_GPT_GTCCRE_OFFSET :
                                   RZV_GPT_GTCCRC_OFFSET;
  return dshot_gpt_overflow_event(channel->gpt_channel) < 0 ? -EINVAL : OK;
}

static int dshot_dma_setup(dshot_channel_t *channel)
{
  struct rzv_dmac_config_s config;

  memset(&config, 0, sizeof(config));
  config.src_size = RZV_DMAC_SIZE_4BYTE;
  config.dst_size = RZV_DMAC_SIZE_4BYTE;
  config.src_addr_mode = RZV_DMAC_ADDR_INCREMENT;
  config.dst_addr_mode = RZV_DMAC_ADDR_FIXED;
  config.trigger = RZV_DMAC_TRIGGER_HW;
  config.src_addr = (uintptr_t)channel->dma_buffer;
  config.dst_addr = channel->gpt_base + channel->buffer_compare_offset;
  config.length = sizeof(channel->dma_buffer);
  config.elc_event = dshot_gpt_overflow_event(channel->gpt_channel);

  return rzv_dmac_channel_configure(channel->dma_channel, &config);
}

static void dshot_cleanup(uint32_t allocated_mask, uint32_t gpt_mask,
                          uint32_t dma_mask)
{
  unsigned int i;

  for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
    {
      uint32_t bit = 1u << i;

      if ((dma_mask & bit) != 0u)
        {
          rzv_dmac_channel_stop(g_channels[i].dma_channel);
        }

      if ((gpt_mask & bit) != 0u)
        {
          gpt_force_safe_low(&g_channels[i]);
        }

      if ((allocated_mask & bit) != 0u)
        {
          io_timer_unallocate_channel(i);
        }

      if ((allocated_mask & bit) != 0u || (gpt_mask & bit) != 0u ||
          (dma_mask & bit) != 0u)
        {
          memset(&g_channels[i], 0, sizeof(g_channels[i]));
        }
    }
}

static void dshot_release_active(void)
{
  uint32_t active = g_active_channels;

  dshot_cleanup(active, active, active);
  g_active_channels = 0;
  g_frame_timeout_us = 0;
  g_armed = false;
}

int up_dshot_init(uint32_t channel_mask, unsigned int dshot_pwm_freq,
                  bool enable_bidirectional_dshot)
{
  uint32_t allocated_mask = 0;
  uint32_t gpt_mask = 0;
  uint32_t dma_mask = 0;
  uint32_t clock_hz;
  uint32_t bit_period;
  uint32_t t0h_ticks;
  uint32_t t1h_ticks;
  unsigned int i;
  int ret;

  if (enable_bidirectional_dshot)
    {
      PX4_ERR("BDShot is not supported on RZ/V2H");
      return -ENOTSUP;
    }

  if (g_active_channels != 0u)
    {
      if (g_armed)
        {
          return -EBUSY;
        }

      dshot_release_active();
    }

  if (channel_mask == 0u ||
      (channel_mask & ~((1u << DSHOT_MAX_CHANNELS) - 1u)) != 0u)
    {
      return -EINVAL;
    }

  if (dshot_pwm_freq != DSHOT150_FREQ && dshot_pwm_freq != DSHOT300_FREQ &&
      dshot_pwm_freq != DSHOT600_FREQ && dshot_pwm_freq != DSHOT1200_FREQ)
    {
      PX4_ERR("Invalid DShot frequency: %u", dshot_pwm_freq);
      return -EINVAL;
    }

  clock_hz = rzv_get_gpt_clock_hz();
  bit_period = clock_hz / dshot_pwm_freq;
  t0h_ticks = (bit_period * 3u) / 8u;
  t1h_ticks = (bit_period * 3u) / 4u;

  if (clock_hz == 0u || bit_period < 4u || t0h_ticks == 0u ||
      t1h_ticks == 0u)
    {
      return -ERANGE;
    }

  for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
    {
      unsigned int j;

      if ((channel_mask & (1u << i)) == 0u)
        {
          continue;
        }

      ret = dshot_map_channel(i, &g_channels[i]);
      if (ret < 0)
        {
          PX4_ERR("Invalid DShot channel %u", i);
          goto fail;
        }

      g_channels[i].bit_period_ticks = bit_period;
      g_channels[i].t0h_compare = t0h_ticks - 1u;
      g_channels[i].t1h_compare = t1h_ticks - 1u;

      for (j = 0; j < i; j++)
        {
          if ((channel_mask & (1u << j)) != 0u &&
              (g_channels[j].gpt_channel == g_channels[i].gpt_channel ||
               g_channels[j].dma_channel == g_channels[i].dma_channel))
            {
              PX4_ERR("Duplicate DShot resource on channel %u", i);
              ret = -EINVAL;
              goto fail;
            }
        }
    }

  for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
    {
      uint32_t bit = 1u << i;

      if ((channel_mask & bit) == 0u)
        {
          continue;
        }

      ret = io_timer_allocate_channel(i, IOTimerChanMode_Dshot);
      if (ret < 0)
        {
          goto fail;
        }

      allocated_mask |= bit;
    }

  for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
    {
      uint32_t bit = 1u << i;

      if ((channel_mask & bit) == 0u)
        {
          continue;
        }

      gpt_setup_channel(&g_channels[i]);
      gpt_mask |= bit;

      ret = dshot_dma_setup(&g_channels[i]);
      if (ret < 0)
        {
          PX4_ERR("DShot DMA setup failed on channel %u: %d", i, ret);
          goto fail;
        }

      dma_mask |= bit;
    }

  g_active_channels = channel_mask;
  g_frame_timeout_us =
    (((DSHOT_FRAME_BITS + 2u) * 1000000u) + dshot_pwm_freq - 1u) /
    dshot_pwm_freq + DSHOT_FRAME_TIMEOUT_US;
  g_armed = false;
  PX4_INFO("DShot TX initialized: %u Hz, channels 0x%lx",
           dshot_pwm_freq, (unsigned long)channel_mask);
  return (int)channel_mask;

fail:
  dshot_cleanup(allocated_mask, gpt_mask, dma_mask);
  return ret;
}

void dshot_motor_data_set(unsigned int channel, uint16_t throttle,
                          bool telemetry)
{
  if (channel >= DSHOT_MAX_CHANNELS ||
      (g_active_channels & (1u << channel)) == 0u)
    {
      return;
    }

  g_channels[channel].throttle_value = throttle;
  g_channels[channel].telemetry_request = telemetry;
}

static int dshot_wait_frame_complete(void)
{
  uint32_t elapsed_us;

  for (elapsed_us = 0; elapsed_us < g_frame_timeout_us; elapsed_us++)
    {
      bool all_complete = true;
      unsigned int i;

      for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
        {
          uint32_t status;

          if ((g_active_channels & (1u << i)) == 0u)
            {
              continue;
            }

          status = rzv_dmac_channel_status(g_channels[i].dma_channel);
          if ((status & DMAC_CHSTAT_ER) != 0u)
            {
              return -EIO;
            }

          if ((status & DMAC_CHSTAT_END) == 0u)
            {
              all_complete = false;
            }
        }

      if (all_complete)
        {
          return OK;
        }

      up_udelay(1);
    }

  return -ETIMEDOUT;
}

void up_dshot_trigger(void)
{
  uint32_t armed_mask = 0;
  unsigned int i;
  int ret;

  if (!g_armed)
    {
      return;
    }

  for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
    {
      if ((g_active_channels & (1u << i)) == 0u)
        {
          continue;
        }

      if (rzv_dmac_channel_disable(g_channels[i].dma_channel) < 0)
        {
          goto fail;
        }

      dshot_prepare_frame(&g_channels[i]);
      gpt_prime_frame(&g_channels[i]);
    }

  for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
    {
      uint32_t bit = 1u << i;

      if ((g_active_channels & bit) == 0u)
        {
          continue;
        }

      if (rzv_dmac_channel_start(g_channels[i].dma_channel) < 0)
        {
          goto fail;
        }

      armed_mask |= bit;
    }

  for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
    {
      if ((g_active_channels & (1u << i)) != 0u)
        {
          gpt_start(&g_channels[i]);
        }
    }

  ret = dshot_wait_frame_complete();

  /* A zero compare still produces a one-clock pulse in buffered saw-wave
   * mode. Once the complete data frame and tail values have transferred,
   * stop and force the pins low so the inter-frame gap cannot contain narrow
   * pulses. */

  for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
    {
      if ((g_active_channels & (1u << i)) != 0u)
        {
          gpt_force_safe_low(&g_channels[i]);
          rzv_dmac_channel_disable(g_channels[i].dma_channel);
        }
    }

  if (ret < 0)
    {
      PX4_ERR("DShot frame completion failed: %d", ret);
    }

  return;

fail:
  PX4_ERR("DShot frame arm failed");

  for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
    {
      uint32_t bit = 1u << i;

      if ((armed_mask & bit) != 0u)
        {
          rzv_dmac_channel_disable(g_channels[i].dma_channel);
        }

      if ((g_active_channels & bit) != 0u)
        {
          gpt_force_safe_low(&g_channels[i]);
        }
    }
}

int up_dshot_arm(bool armed)
{
  unsigned int i;

  if (g_active_channels == 0u)
    {
      return -ENODEV;
    }

  if (!armed)
    {
      for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
        {
          if ((g_active_channels & (1u << i)) != 0u)
            {
              g_channels[i].throttle_value = DSHOT_DISARM_MOTOR;
              rzv_dmac_channel_disable(g_channels[i].dma_channel);
              gpt_force_safe_low(&g_channels[i]);
            }
        }
    }
  else
    {
      for (i = 0; i < DSHOT_MAX_CHANNELS; i++)
        {
          if ((g_active_channels & (1u << i)) != 0u)
            {
              g_channels[i].throttle_value = DSHOT_DISARM_MOTOR;
            }
        }
    }

  g_armed = armed;
  return OK;
}

int up_bdshot_num_erpm_ready(void)
{
  return -ENOTSUP;
}

int up_bdshot_get_erpm(uint8_t channel, int *erpm)
{
  (void)channel;
  (void)erpm;
  return -ENOTSUP;
}

int up_bdshot_channel_status(uint8_t channel)
{
  (void)channel;
  return -ENOTSUP;
}

void up_bdshot_status(void)
{
  PX4_INFO("BDShot is not supported on RZ/V2H");
}
