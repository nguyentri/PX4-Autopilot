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
#include "hardware/ra_pinmap.h"

extern const io_timers_t io_timers[MAX_IO_TIMERS];
extern const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS];

/* External GPT capture functions from io_timer_impl.c */
extern int gpt_configure_input_capture(unsigned channel, bool rising_edge, bool falling_edge);
extern uint32_t gpt_read_capture(unsigned channel);
extern bool gpt_capture_ready(unsigned channel);
extern void gpt_capture_clear(unsigned channel);
extern uint32_t gpt_get_capture_clock(unsigned channel);

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

/* DShot Protocol Timing Constants
 * Per DShot specification:
 * - Bit 0: 37.5% duty cycle (T0H = 0.375 * bit_period)
 * - Bit 1: 75.0% duty cycle (T1H = 0.750 * bit_period)
 * The remaining time in each bit period is low.
 */
#define DSHOT_T0H_PERCENT        37.5f   /* Bit '0' high time as percentage */
#define DSHOT_T1H_PERCENT        75.0f   /* Bit '1' high time as percentage */

/* Use board-defined PCLKD frequency (250MHz for RA8P1, 120MHz for RA8E1) */
#ifdef BOARD_PCLKD_FREQUENCY
#  define PCLKD_FREQUENCY        BOARD_PCLKD_FREQUENCY
#else
#  if defined(CONFIG_RA8P1_GROUP)
#    define PCLKD_FREQUENCY      250000000u  /* 250MHz for RA8P1 */
#  else
#    define PCLKD_FREQUENCY      120000000u  /* 120MHz for RA8E1 */
#  endif
#endif

#define BDSHOT_OFFLINE_COUNT     400

/* DShot frame timeout in microseconds (with margin) */
#define DSHOT_FRAME_TIMEOUT_US   500

/* BDShot Telemetry Protocol Constants
 * BDShot (Bidirectional DShot) allows ESCs to send telemetry back.
 * After sending a DShot frame, the flight controller switches the
 * signal line to input mode to receive GCR-encoded eRPM data.
 *
 * Timing requirements:
 * - Response delay: ESC needs ~30µs to switch from RX to TX mode
 * - Response length: 21 bits GCR encoded (16-bit data + 5-bit CRC)
 * - Capture window: Must complete within 100µs for reliable operation
 */
#define BDSHOT_RESPONSE_DELAY_US  30   /* Time for ESC to respond after frame TX */
#define BDSHOT_RESPONSE_BITS      21   /* GCR encoded response: 4 nibbles + CRC */
#define BDSHOT_CAPTURE_TIMEOUT_US 100  /* Max time to wait for response capture */

/* Most hobby brushless motors operate in the range 0-100,000 eRPM.
 * Values above 200,000 are likely decoding errors.
*/
#define BDSHOT_MAX_VALID_ERPM  200000u

  /* PFS Write Protection Control
   * PWPR register bits:
   *   Bit 6 (PFSWE): PFS Write Enable - must be set to modify PFS registers
   *   Bit 7 (B0WI):  PFSWE Write Disable - prevents accidental changes
   * Unlock sequence: Clear B0WI first, then set PFSWE
   * Lock sequence: Clear PFSWE (optional), then set B0WI
   */
#define PWPR_PFSWE_BIT  (1 << 6)  /* PFS Write Enable */
#define PWPR_B0WI_BIT   (1 << 7)  /* PFSWE Write Disable */

#define GCR_INVALID  0xFF  /* Marker for invalid GCR symbols */

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

  /* DMA completion tracking */
  volatile bool dma_complete;

  /* BDShot telemetry */
  uint16_t erpm;
  uint32_t last_erpm_update;
  uint32_t crc_error_count;
  uint32_t frame_error_count;
  uint32_t no_response_count;

  /* BDShot capture state */
  bool     capture_enabled;
  uint32_t capture_buffer[BDSHOT_RESPONSE_BITS];
  uint8_t  capture_count;
  uint32_t last_capture_time;
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

/****************************************************************************
 * BDShot GCR (Golay-Corrected Reverse) Decoding
 *
 * BDShot telemetry uses a 21-bit GCR encoded response from the ESC.
 * The response contains eRPM data that needs to be decoded.
 *
 * GCR Encoding: 5-bit symbols mapped to 4-bit nibbles
 * The ESC sends pulses where bit timing encodes data.
 ****************************************************************************/

/* GCR (Golay-Corrected Reverse) 5-to-4 Bit Decoding Table
 *
 * BDShot telemetry uses GCR encoding to improve signal integrity.
 * Each 4-bit nibble is encoded as a 5-bit GCR symbol for transmission.
 *
 * GCR Encoding Mapping (4-bit value -> 5-bit symbol):
 *   0x0 -> 0x19 (11001)    0x8 -> 0x1A (11010)
 *   0x1 -> 0x1B (11011)    0x9 -> 0x09 (01001)
 *   0x2 -> 0x12 (10010)    0xA -> 0x0A (01010)
 *   0x3 -> 0x13 (10011)    0xB -> 0x0B (01011)
 *   0x4 -> 0x1D (11101)    0xC -> 0x1E (11110)
 *   0x5 -> 0x15 (10101)    0xD -> 0x0D (01101)
 *   0x6 -> 0x16 (10110)    0xE -> 0x0E (01110)
 *   0x7 -> 0x17 (10111)    0xF -> 0x0F (01111)
 *
 * This table provides reverse lookup: 5-bit symbol -> 4-bit value
 * Invalid symbols (not in the encoding) map to 0xFF (GCR_INVALID)
 */

static const uint8_t gcr_decode_table[32] = {
  /* 0x00-0x07: All invalid (no valid GCR symbols in this range) */
  GCR_INVALID, GCR_INVALID, GCR_INVALID, GCR_INVALID,
  GCR_INVALID, GCR_INVALID, GCR_INVALID, GCR_INVALID,
  /* 0x08-0x0F: 0x09=9, 0x0A=A, 0x0B=B, 0x0D=D, 0x0E=E, 0x0F=F */
  GCR_INVALID, 0x09, 0x0A, 0x0B, GCR_INVALID, 0x0D, 0x0E, 0x0F,
  /* 0x10-0x17: 0x12=2, 0x13=3, 0x15=5, 0x16=6, 0x17=7 */
  GCR_INVALID, GCR_INVALID, 0x02, 0x03, GCR_INVALID, 0x05, 0x06, 0x07,
  /* 0x18-0x1F: 0x19=0, 0x1A=8, 0x1B=1, 0x1D=4, 0x1E=C */
  GCR_INVALID, 0x00, 0x08, 0x01, GCR_INVALID, 0x04, 0x0C, GCR_INVALID
};

/**
 * Decode GCR 21-bit value to 16-bit data
 *
 * @param gcr_value  21-bit GCR encoded value
 * @param decoded    Output: 16-bit decoded value
 * @return 0 on success, -1 on CRC error, -2 on invalid GCR symbol
 */
static int bdshot_gcr_decode(uint32_t gcr_value, uint16_t *decoded)
{
  uint16_t result = 0;
  uint8_t nibble;

  /* GCR value is 21 bits: 4 nibbles (16 bits) + 5-bit checksum
   * Extract from MSB to LSB: [20:16][15:11][10:6][5:1][0] with overlap
   * Actually it's: nibble3[20:16], nibble2[15:11], nibble1[10:6], nibble0[5:1], crc[4:0]
   */

  /* Extract and decode each 5-bit GCR symbol */
  for (int i = 3; i >= 0; i--)
    {
      uint8_t gcr_symbol = (gcr_value >> (i * 5 + 1)) & 0x1F;
      nibble = gcr_decode_table[gcr_symbol];

      if (nibble == GCR_INVALID)
        {
          return -2;  /* Invalid GCR symbol */
        }

      result = (result << 4) | nibble;
    }

  /* Extract 4-bit CRC from the last 5 bits (with some overlap handling) */
  uint8_t received_crc = gcr_value & 0x0F;

  /* Calculate CRC: XOR of all nibbles */
  uint8_t calculated_crc = (result >> 12) ^ ((result >> 8) & 0xF) ^
                           ((result >> 4) & 0xF) ^ (result & 0xF);

  if (received_crc != calculated_crc)
    {
      return -1;  /* CRC error */
    }

  *decoded = result;
  return 0;
}

/**
 * Convert decoded BDShot telemetry to eRPM
 *
 * The decoded value format:
 * - Bits [15:9]: Period base (7 bits)
 * - Bits [8:5]: Exponent (4 bits)
 * - Bits [4:1]: Extended period (4 bits)
 * - Bit [0]: Reserved
 *
 * eRPM calculation: period_us = (period_base << exponent) / 2
 *                   eRPM = 60000000 / (period_us * motor_poles)
 *
 * @param decoded     16-bit decoded telemetry value
 * @param motor_poles Number of motor poles (typically 14 for brushless)
 * @return eRPM value, or 0 on error
 */
static uint32_t bdshot_decode_erpm(uint16_t decoded, uint8_t motor_poles)
{
  /* Extract fields from decoded value */
  uint32_t period_base = (decoded >> 9) & 0x7F;
  uint32_t exponent = (decoded >> 5) & 0x0F;
  uint32_t extended = (decoded >> 1) & 0x0F;

  if (period_base == 0)
    {
      return 0;  /* Motor not spinning or invalid */
    }

  /* Calculate period in timer ticks */
  uint32_t period = ((period_base << 4) | extended) << exponent;

  /* Convert to microseconds (assuming timer runs at 1MHz after prescaling) */
  /* period is already in a scaled unit, convert to eRPM */
  /* eRPM = (60 * 1000000) / (period * motor_poles / 2) */
  /* Simplified: eRPM = 120000000 / (period * motor_poles) */

  if (period == 0 || motor_poles == 0)
    {
      return 0;
    }

  uint32_t erpm = 120000000u / (period * motor_poles);

  /* Sanity check: typical brushless motor eRPM range */
  if (erpm > BDSHOT_MAX_VALID_ERPM)
    {
      return 0;  /* Invalid reading - likely decode error */
    }

  return erpm;
}

/**
 * Configure GPIO for input mode (BDShot receive)
 */
static void bdshot_gpio_set_input(dshot_channel_t *ch)
{
  if (ch->gpio_pin == 0)
    {
      return;
    }

  /* Reconfigure GPIO for input mode
   * Clear PMR (peripheral mode) and set as input
   */
  uint8_t port = (ch->gpio_pin >> 28) & 0xF;
  uint8_t pin = (ch->gpio_pin >> 24) & 0xF;
  uint32_t pfs_addr = R_PFS_BASE + (port * R_PFS_PSEL_PORT_OFFSET) +
                      (pin * R_PFS_PSEL_PIN_OFFSET);

  /* Enable PFS write access */
  putreg8(0, R_PFS_PWPR);               /* Clear B0WI to allow PFSWE change */
  putreg8(PWPR_PFSWE_BIT, R_PFS_PWPR);  /* Enable PFS register writes */

  /* Configure as input with noise filter */
  uint32_t pfs_value = getreg32(pfs_addr);
  pfs_value &= ~(R_PFS_PDR | R_PFS_PMR);  /* Clear direction and peripheral mode */
  putreg32(pfs_value, pfs_addr);

  /* Disable PFS write access */
  putreg8(0, R_PFS_PWPR);              /* Clear PFSWE */
  putreg8(PWPR_B0WI_BIT, R_PFS_PWPR);  /* Lock PFS registers */
}

/**
 * Configure GPIO for output mode (DShot transmit)
 */
static void bdshot_gpio_set_output(dshot_channel_t *ch)
{
  if (ch->gpio_pin == 0)
    {
      return;
    }

  /* Reconfigure GPIO for peripheral (GPT) output mode */
  ra_gpioconfig(ch->gpio_pin);
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

/**
 * DMA completion callback - called from interrupt context when DMA transfer completes
 */
#ifdef CONFIG_RA_DMAC
static void dshot_dma_callback(void *handle, int event, void *user_data)
{
  dshot_channel_t *ch = (dshot_channel_t *)user_data;

  if (ch != NULL)
    {
      ch->dma_complete = true;

      /* Stop the timer immediately after DMA completes */
      gpt_stop(ch->gpt_channel);
    }
}
#endif

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

  /* Register DMA completion callback for interrupt-driven completion */
  dma_config.callback = dshot_dma_callback;
  dma_config.user_data = ch;

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
      ch->dma_complete = false;
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
 *
 * This function starts all DShot frame transmissions in parallel using DMA.
 * It uses interrupt-driven DMA completion for efficiency, with a timeout
 * fallback to ensure forward progress.
 */

void up_dshot_trigger(void)
{
#ifdef CONFIG_RA_DMAC
  if (g_dma_available)
    {
      /* Calculate timeout based on DShot frequency */
      uint32_t bit_time_us = (1000000u + g_dshot_frequency / 2u) /
                             g_dshot_frequency;
      uint32_t frame_time_us = bit_time_us * DSHOT_FRAME_BITS;

      /* Start all channels in parallel */
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

          /* Clear completion flag before starting */
          ch->dma_complete = false;

          dshot_prepare_buffer(ch);

          if (dshot_dma_start(ch) < 0)
            {
              continue;
            }

          /* Start timer - DMA will automatically update GTCCRA */
          gpt_start(ch->gpt_channel);
        }

      /* Wait for all channels to complete (with timeout) */
      uint32_t timeout_us = frame_time_us + DSHOT_FRAME_TIMEOUT_US;
      uint32_t elapsed_us = 0;
      const uint32_t poll_interval_us = 10;

      while (elapsed_us < timeout_us)
        {
          bool all_complete = true;

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

              if (!ch->dma_complete)
                {
                  all_complete = false;
                  break;
                }
            }

          if (all_complete)
            {
              break;
            }

          up_udelay(poll_interval_us);
          elapsed_us += poll_interval_us;
        }

      /* Stop any channels that didn't complete and cleanup */
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

          /* Force stop timer if DMA didn't complete (callback stops it normally) */
          if (!ch->dma_complete)
            {
              gpt_stop(ch->gpt_channel);
            }

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
 *
 * BDShot (Bidirectional DShot) provides eRPM telemetry from ESCs.
 *
 * Implementation:
 * 1. After transmitting DShot frame, reconfigure pin as input
 * 2. Use GPT input capture to measure response pulse timing
 * 3. Decode 21-bit GCR (Golay-Corrected Reverse) encoded telemetry
 * 4. Extract eRPM from decoded value
 *
 * Note: Full BDShot requires precise timing. The current implementation
 * provides the decoding infrastructure but may need tuning for specific
 * ESC timing characteristics.
 */

/**
 * Process BDShot telemetry capture for a single channel
 * Called after DShot frame transmission completes
 *
 * @param ch_idx Channel index
 * @return 0 on success, negative on error
 */
int bdshot_process_telemetry(uint8_t ch_idx)
{
  if (!g_bdshot_enabled || ch_idx >= DSHOT_MAX_CHANNELS)
    {
      return -EINVAL;
    }

  dshot_channel_t *ch = &g_channels[ch_idx];
  if (!ch->initialized || !ch->capture_enabled)
    {
      return -ENODEV;
    }

  /* Check if capture is ready */
  if (!gpt_capture_ready(ch->io_channel))
    {
      ch->no_response_count++;
      return -EAGAIN;
    }

  /* Read captured timing values */
  uint32_t capture = gpt_read_capture(ch->io_channel);
  gpt_capture_clear(ch->io_channel);

  /* Convert capture to GCR bits based on pulse widths
   * This is a simplified version - full implementation would
   * capture multiple edges and decode pulse widths
   */

  /* For now, just store the capture value for debugging */
  ch->last_capture_time = capture;

  /* Attempt GCR decoding (placeholder - needs edge timing array) */
  uint16_t decoded;
  int ret = bdshot_gcr_decode(capture, &decoded);

  if (ret == -1)
    {
      ch->crc_error_count++;
      return -EBADMSG;
    }
  else if (ret == -2)
    {
      ch->frame_error_count++;
      return -EPROTO;
    }

  /* Decode eRPM from telemetry value
   * Assuming 14-pole motor (typical for brushless)
   */
  uint32_t erpm = bdshot_decode_erpm(decoded, 14);

  if (erpm > 0)
    {
      ch->erpm = (uint16_t)(erpm > 65535 ? 65535 : erpm);
      ch->last_erpm_update = 0;  /* Would use hrt_absolute_time() */
      ch->no_response_count = 0;
    }

  return 0;
}

/**
 * Enable BDShot telemetry capture for a channel
 */
int bdshot_enable_capture(uint8_t ch_idx)
{
  if (ch_idx >= DSHOT_MAX_CHANNELS)
    {
      return -EINVAL;
    }

  dshot_channel_t *ch = &g_channels[ch_idx];
  if (!ch->initialized)
    {
      return -ENODEV;
    }

  /* Configure GPIO for input mode */
  bdshot_gpio_set_input(ch);

  /* Configure GPT for input capture on both edges */
  int ret = gpt_configure_input_capture(ch->io_channel, true, true);
  if (ret < 0)
    {
      /* Restore GPIO to output mode */
      bdshot_gpio_set_output(ch);
      return ret;
    }

  ch->capture_enabled = true;
  return 0;
}

/**
 * Disable BDShot telemetry capture for a channel
 */
void bdshot_disable_capture(uint8_t ch_idx)
{
  if (ch_idx >= DSHOT_MAX_CHANNELS)
    {
      return;
    }

  dshot_channel_t *ch = &g_channels[ch_idx];
  if (!ch->initialized)
    {
      return;
    }

  /* Disable input capture */
  gpt_configure_input_capture(ch->io_channel, false, false);

  /* Restore GPIO to output (peripheral) mode */
  bdshot_gpio_set_output(ch);

  ch->capture_enabled = false;
}

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
          g_channels[ch].erpm > 0 &&
          g_channels[ch].no_response_count < BDSHOT_OFFLINE_COUNT)
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
          syslog(LOG_INFO, "    Capture enabled: %s\n",
                 chan->capture_enabled ? "yes" : "no");
          syslog(LOG_INFO, "    CRC errors: %lu\n",
                 (unsigned long)chan->crc_error_count);
          syslog(LOG_INFO, "    Frame errors: %lu\n",
                 (unsigned long)chan->frame_error_count);
          syslog(LOG_INFO, "    No response: %lu\n",
                 (unsigned long)chan->no_response_count);
        }
    }
}
