/* SPDX-License-Identifier: Apache-2.0 */

/* Execute the complete production driver. Clock/IRQ/MMIO instrumentation
 * supplies host observations, not simulated proof of physical hardware.
 */

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <nuttx/irq.h>
#include <nuttx/timers/pwm.h>
#include "hardware/rzv_gpt.h"

#define __ARCH_ARM_SRC_RZV_CLOCK_H
#define __ARCH_ARM_SRC_RZV_ICU_H

typedef int (*test_isr_t)(int, void *, void *);

static uint32_t getreg32(uintptr_t address);
static void putreg32(uint32_t value, uintptr_t address);
static irqstate_t enter_critical_section(void);
static void leave_critical_section(irqstate_t flags);
static int rzv_gpt_module_start(unsigned int channel);
static int rzv_gpt_module_stop(unsigned int channel);
static uint32_t rzv_get_gpt_clock_hz(void);
#ifdef CONFIG_PWM_PULSECOUNT
static int rzv_icu_attach(uint16_t event, test_isr_t handler, void *arg,
                          bool enable);
static void rzv_icu_detach(int irq);
static void rzv_gic_set_irq_type(int irq, bool edge);
static void up_enable_irq(int irq);
static void up_disable_irq(int irq);
#endif

#include "rzv_gpt.c"

static uint32_t registers[16][64];
static unsigned int reads;
static unsigned int writes;
static unsigned int commands;
static unsigned int period_writes;
static unsigned int start_calls[16];
static unsigned int stop_calls[16];
static unsigned int references[2];
static bool acquired[16];
static int setup_error;
static unsigned int critical_depth;
static unsigned int expected_channel;
static bool interrupt_context;

static unsigned int decode(uintptr_t address, unsigned int *offset)
{
  unsigned int channel;
  uintptr_t unit;

  if (address >= 0x13010000u && address < 0x13010800u)
    {
      unit = 0x13010000u;
      channel = (address - unit) / 0x100u;
    }
  else
    {
      assert(address >= 0x13020000u && address < 0x13020800u);
      unit = 0x13020000u;
      channel = 8u + (address - unit) / 0x100u;
    }

  *offset = (address - unit) % 0x100u;
  assert((*offset % 4u) == 0);
  assert(channel == expected_channel);
  assert(acquired[channel]);
  return channel;
}

static uint32_t getreg32(uintptr_t address)
{
  unsigned int offset;
  unsigned int channel = decode(address, &offset);
  reads++;
  return registers[channel][offset / 4u];
}

static void putreg32(uint32_t value, uintptr_t address)
{
  unsigned int offset;
  unsigned int channel = decode(address, &offset);
  uint32_t *reg = registers[channel];

  assert(critical_depth > 0 || interrupt_context);
  writes++;
  reg[offset / 4u] = value;
  if (offset == RZV_GPT_GTSTR_OFFSET || offset == RZV_GPT_GTSTP_OFFSET ||
      offset == RZV_GPT_GTCLR_OFFSET)
    {
      /* Literal expected local index, independent of the driver's macro. */

      assert(value == (1u << (channel % 8u)));
      commands++;
      if (offset == RZV_GPT_GTSTR_OFFSET &&
          (reg[RZV_GPT_GTSSR_OFFSET / 4u] & (1u << 31)))
        {
          reg[RZV_GPT_GTCR_OFFSET / 4u] |= GPT_GTCR_CST;
        }
      else if (offset == RZV_GPT_GTSTP_OFFSET &&
               (reg[RZV_GPT_GTPSR_OFFSET / 4u] & (1u << 31)))
        {
          reg[RZV_GPT_GTCR_OFFSET / 4u] &= ~GPT_GTCR_CST;
        }
      else if (offset == RZV_GPT_GTCLR_OFFSET &&
               (reg[RZV_GPT_GTCSR_OFFSET / 4u] & (1u << 31)))
        {
          reg[RZV_GPT_GTCNT_OFFSET / 4u] = 0;
        }
    }

  if (offset == RZV_GPT_GTPR_OFFSET)
    {
      period_writes++;
    }
}

static irqstate_t enter_critical_section(void)
{
  return critical_depth++;
}

static void leave_critical_section(irqstate_t flags)
{
  assert(critical_depth == flags + 1u);
  critical_depth--;
}

static int rzv_gpt_module_start(unsigned int channel)
{
  assert(channel < 16 && channel == expected_channel && !acquired[channel]);
  start_calls[channel]++;
  if (setup_error)
    {
      return setup_error;
    }

  acquired[channel] = true;
  references[channel / 8u]++;
  return 0;
}

static int rzv_gpt_module_stop(unsigned int channel)
{
  assert(channel < 16 && channel == expected_channel && acquired[channel]);
  assert(references[channel / 8u] > 0);
  stop_calls[channel]++;
  acquired[channel] = false;
  references[channel / 8u]--;
  return 0;
}

static uint32_t rzv_get_gpt_clock_hz(void)
{
  return 200000000u;
}

#ifdef CONFIG_PWM_PULSECOUNT
struct test_irq_s
{
  test_isr_t handler;
  void *arg;
  bool enabled;
};

static struct test_irq_s irqs[16];
static int attach_error;
static unsigned int attaches;
static unsigned int detaches;
static unsigned int expirations;
static int completion_handle;

static int rzv_icu_attach(uint16_t event, test_isr_t handler, void *arg,
                          bool enable)
{
  struct rzv_gpt_lowerhalf_s *priv = arg;
  unsigned int channel = priv->channel;
  /* IRQSEL identifiers from the CR8 source table, not ELC event IDs. */

  unsigned int base = channel < 8 ? 115u : 219u;
  if (priv->output == RZV_GPT_OUTPUT_B)
    {
      base += 8u;
    }

  assert(event == base + channel % 8u && !enable);
  assert(handler && !irqs[channel].handler && !irqs[channel].enabled);
  attaches++;
  if (attach_error)
    {
      return attach_error;
    }

  irqs[channel].handler = handler;
  irqs[channel].arg = arg;
  return 385 + channel;
}

static void rzv_icu_detach(int irq)
{
  unsigned int channel = irq - 385;
  assert(channel < 16 && irqs[channel].handler && !irqs[channel].enabled);
  memset(&irqs[channel], 0, sizeof(irqs[channel]));
  detaches++;
}

static void rzv_gic_set_irq_type(int irq, bool edge)
{
  assert(irq >= 385 && irq < 401 && edge);
}

static void up_enable_irq(int irq)
{
  unsigned int channel = irq - 385;
  struct rzv_gpt_lowerhalf_s *priv = irqs[channel].arg;
  assert(channel < 16 && priv && priv->running && priv->oneshot);
  assert(priv->remaining && priv->handle && !priv->pulse_started);
  irqs[channel].enabled = true;
}

static void up_disable_irq(int irq)
{
  unsigned int channel = irq - 385;
  assert(channel < 16 && irqs[channel].handler);
  irqs[channel].enabled = false;
}

void pwm_expired(void *handle)
{
  assert(handle == &completion_handle);
  expirations++;
}

#ifndef CONFIG_PWM_MULTICHAN
static void fire_compare(struct rzv_gpt_lowerhalf_s *priv)
{
  unsigned int channel = priv->channel;
  assert(irqs[channel].enabled && irqs[channel].handler);
  assert(!interrupt_context && !critical_depth);
  interrupt_context = true;
  assert(irqs[channel].handler(priv->irq, NULL, priv) == 0);
  interrupt_context = false;
  assert(!critical_depth);
}
#endif
#endif

static int start(struct pwm_lowerhalf_s *dev, uint32_t frequency,
                 unsigned int count)
{
  struct pwm_info_s info = {.frequency = frequency};
#ifdef CONFIG_PWM_MULTICHAN
  info.channels[0].channel = 1;
  info.channels[0].duty = 0x4000;
  info.channels[1].channel = 2;
  info.channels[1].duty = 0xc000;
  info.channels[2].channel = -1;
#else
  info.duty = 0x4000;
#  ifdef CONFIG_PWM_PULSECOUNT
  info.count = count;
#  endif
#endif
#ifdef CONFIG_PWM_PULSECOUNT
  return dev->ops->start(dev, &info, count ? &completion_handle : NULL);
#else
  (void)count;
  return dev->ops->start(dev, &info);
#endif
}

static void snapshot(struct rzv_gpt_lowerhalf_s *priv)
{
#ifdef CONFIG_RZV2H_SAMPLE_TEST_API
  struct rzv_gpt_sample_state_s state;
  unsigned int writes_before = writes;
  unsigned int reads_before = reads;
  unsigned int starts_before = start_calls[priv->channel];
  unsigned int stops_before = stop_calls[priv->channel];
  assert(rzv_gpt_sample_state(priv->channel, &state) == 0);
  assert(state.identity == (uintptr_t)&priv->dev);
  assert(state.base == priv->base && state.channel == priv->channel);
  assert(state.unit == priv->channel / 8u && state.output == priv->output);
  assert(state.initialized == priv->initialized && state.running == priv->running);
  assert(writes == writes_before && reads == reads_before);
  assert(start_calls[priv->channel] == starts_before);
  assert(stop_calls[priv->channel] == stops_before);
#else
  (void)priv;
#endif
}

static void quiescent(struct rzv_gpt_lowerhalf_s *priv)
{
  uint32_t *reg = registers[priv->channel];
  assert(!priv->running);
  assert(!(reg[RZV_GPT_GTCR_OFFSET / 4u] & GPT_GTCR_CST));
  assert(!reg[RZV_GPT_GTINTAD_OFFSET / 4u]);
  assert(!reg[RZV_GPT_GTIOR_OFFSET / 4u]);
  assert(!reg[RZV_GPT_GTCNT_OFFSET / 4u]);
  assert(!reg[RZV_GPT_GTCCRA_OFFSET / 4u]);
  assert(!reg[RZV_GPT_GTCCRB_OFFSET / 4u]);
  assert(!reg[RZV_GPT_GTCCRC_OFFSET / 4u]);
  assert(!reg[RZV_GPT_GTCCRE_OFFSET / 4u]);
#ifdef CONFIG_PWM_PULSECOUNT
  assert(!priv->oneshot && !priv->pulse_started && !priv->handle);
  assert(priv->remaining == 0);
#endif
}

static void lifecycle(struct pwm_lowerhalf_s *dev)
{
  struct rzv_gpt_lowerhalf_s *priv = (struct rzv_gpt_lowerhalf_s *)dev;
  unsigned int channel = priv->channel;
  uint32_t *reg = registers[channel];
  unsigned int before;
  unsigned int starts = start_calls[channel];
  unsigned int stops = stop_calls[channel];

  expected_channel = channel;
  before = writes;
  setup_error = -ETIMEDOUT;
  assert(dev->ops->setup(dev) == -ETIMEDOUT);
  assert(start(dev, 1000, 0) == -ETIMEDOUT);
  assert(writes == before && !priv->initialized && !acquired[channel]);
  setup_error = 0;
  reg[RZV_GPT_GTCNT_OFFSET / 4u] = 123;
  assert(dev->ops->setup(dev) == 0 && priv->initialized);
  assert(reg[RZV_GPT_GTCNT_OFFSET / 4u] == 0);
  snapshot(priv);
  before = writes;
  assert(dev->ops->setup(dev) == 0 && writes == before);
  assert(start_calls[channel] == starts + 3u && acquired[channel]);
  assert(start(dev, 1000, 0) == 0);
  assert(priv->running && priv->period == 200000u);
  snapshot(priv);
  assert(reg[RZV_GPT_GTCR_OFFSET / 4u] & GPT_GTCR_CST);
  assert(reg[RZV_GPT_GTPR_OFFSET / 4u] == 199999u);
#ifdef CONFIG_PWM_MULTICHAN
  assert(reg[RZV_GPT_GTCCRA_OFFSET / 4u] == 49999u);
  assert(reg[RZV_GPT_GTCCRB_OFFSET / 4u] == 149999u);
  assert((reg[RZV_GPT_GTIOR_OFFSET / 4u] &
          (GPT_GTIOR_OAE | GPT_GTIOR_OBE)) ==
         (GPT_GTIOR_OAE | GPT_GTIOR_OBE));
#else
  unsigned int compare = priv->output == RZV_GPT_OUTPUT_A ?
                          RZV_GPT_GTCCRA_OFFSET : RZV_GPT_GTCCRB_OFFSET;
  unsigned int other = priv->output == RZV_GPT_OUTPUT_A ?
                        RZV_GPT_GTCCRB_OFFSET : RZV_GPT_GTCCRA_OFFSET;
  assert(reg[compare / 4u] == 49999u && reg[other / 4u] == 0);
  assert((reg[RZV_GPT_GTIOR_OFFSET / 4u] &
          (GPT_GTIOR_OAE | GPT_GTIOR_OBE)) ==
         (priv->output == RZV_GPT_OUTPUT_A ? GPT_GTIOR_OAE : GPT_GTIOR_OBE));
#endif

  /* Ownership checks may not disturb an active waveform. */

  before = writes;
  assert(rzv_gpt_initialize_output(channel, priv->output) == dev);
  assert(rzv_gpt_initialize_output(channel, 1 - priv->output) == NULL);
  assert(writes == before && priv->running);
  before = commands;
  unsigned int periods_before = period_writes;
  assert(start(dev, 2000, 0) == 0);
  assert(commands == before && period_writes == periods_before);
  assert(priv->period == 100000u);
  assert(reg[RZV_GPT_GTPR_OFFSET / 4u] == 199999u);
  assert(reg[RZV_GPT_GTPBR_OFFSET / 4u] == 99999u);
#ifdef CONFIG_PWM_MULTICHAN
  assert(reg[RZV_GPT_GTCCRC_OFFSET / 4u] == 24999u);
  assert(reg[RZV_GPT_GTCCRE_OFFSET / 4u] == 74999u);
#endif
  reg[RZV_GPT_GTCNT_OFFSET / 4u] = 456;
  assert(dev->ops->stop(dev) == 0);
  quiescent(priv);
  snapshot(priv);
  assert(dev->ops->ioctl(dev, 0, 0) == -ENOTTY);

#if defined(CONFIG_PWM_PULSECOUNT) && !defined(CONFIG_PWM_MULTICHAN)
  attach_error = -ENOMEM;
  assert(start(dev, 1000, 3) == -ENOMEM);
  assert(priv->irq == -1);
  quiescent(priv);
  attach_error = 0;
  before = expirations;
  assert(start(dev, 1000, 3) == 0);
  assert(reg[RZV_GPT_GTINTAD_OFFSET / 4u] ==
         (priv->output == RZV_GPT_OUTPUT_A ?
           GPT_GTINTAD_GTINTA : GPT_GTINTAD_GTINTB));
  assert(priv->irq == 385 + (int)channel && irqs[channel].enabled);
  fire_compare(priv);
  assert(priv->remaining == 3 && priv->pulse_started);
  for (unsigned int pulse = 0; pulse < 3; pulse++)
    {
      fire_compare(priv);
      assert(priv->remaining == 2u - pulse);
    }

  assert(expirations == before + 1 && !irqs[channel].enabled);
  quiescent(priv);
  before = attaches;
  assert(start(dev, 1000, 2) == 0);
  assert(attaches == before);
#endif

  assert(dev->ops->shutdown(dev) == 0 && !priv->initialized);
  assert(!acquired[channel] && stop_calls[channel] == stops + 1);
  quiescent(priv);
  snapshot(priv);
#ifdef CONFIG_PWM_PULSECOUNT
  assert(priv->irq == -1 && !irqs[channel].handler);
#endif
  before = writes;
  assert(dev->ops->shutdown(dev) == 0 && writes == before);
  assert(stop_calls[channel] == stops + 1);

  /* Reopen preserves output identity and clears finite-pulse state. */

  assert(rzv_gpt_initialize_output(channel, priv->output) == dev);
  assert(rzv_gpt_initialize_output(channel, 1 - priv->output) == NULL);
  assert(dev->ops->setup(dev) == 0 && acquired[channel]);
#ifdef CONFIG_PWM_PULSECOUNT
  assert(priv->irq == -1 && !priv->oneshot && !priv->pulse_started);
  assert(!priv->handle && !priv->remaining);
#endif
#if defined(CONFIG_PWM_PULSECOUNT) && !defined(CONFIG_PWM_MULTICHAN)
  before = expirations;
  assert(start(dev, 1000, 1) == 0);
  assert(priv->irq == 385 + (int)channel && !priv->pulse_started);
  fire_compare(priv);
  assert(priv->remaining == 1);
  fire_compare(priv);
  assert(expirations == before + 1);
  quiescent(priv);
#else
  assert(start(dev, 1000, 0) == 0);
#endif
  assert(dev->ops->shutdown(dev) == 0);
  assert(stop_calls[channel] == stops + 2 && !acquired[channel]);
  quiescent(priv);
}

int main(int argc, char **argv)
{
  struct pwm_lowerhalf_s *devices[16] = {0};
  assert(argc == 2);
  enum rzv_gpt_output_e output = atoi(argv[1]);
  assert(output == RZV_GPT_OUTPUT_A || output == RZV_GPT_OUTPUT_B);
  assert(g_rzv_gpt_ops.setup != NULL);

  const int invalid[] = {-1, INT_MIN, 16, 17, INT_MAX};
  for (unsigned int i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++)
    {
      assert(rzv_gpt_initialize_output(invalid[i], output) == NULL);
      assert(rzv_gpt_initialize(invalid[i]) == NULL);
#ifdef CONFIG_RZV2H_SAMPLE_TEST_API
      struct rzv_gpt_sample_state_s state;
      memset(&state, 0xa5, sizeof(state));
      struct rzv_gpt_sample_state_s saved = state;
      assert(rzv_gpt_sample_state(invalid[i], &state) == -EINVAL);
      assert(memcmp(&state, &saved, sizeof(state)) == 0);
#endif
    }

  for (unsigned int channel = 0; channel < 16; channel++)
    {
#ifdef CONFIG_RZV2H_SAMPLE_TEST_API
      struct rzv_gpt_sample_state_s state;
      assert(rzv_gpt_sample_state(channel, NULL) == -EINVAL);
      memset(&state, 0xa5, sizeof(state));
      struct rzv_gpt_sample_state_s saved = state;
      int ret = rzv_gpt_sample_state(channel, &state);
      if (TEST_ENABLED_MASK & (1u << channel))
        {
          assert(ret == 0 && state.identity && state.base);
          assert(!state.initialized && !state.running);
          /* Reading an unselected timer must not claim its default A output. */

          assert(state.output == RZV_GPT_OUTPUT_A);
        }
      else
        {
          assert(ret == -EINVAL && memcmp(&state, &saved, sizeof(state)) == 0);
        }
#endif
      assert(rzv_gpt_initialize_output(channel, -1) == NULL);
      assert(rzv_gpt_initialize_output(channel, 2) == NULL);
      devices[channel] = rzv_gpt_initialize_output(channel, output);
      if (!(TEST_ENABLED_MASK & (1u << channel)))
        {
          assert(devices[channel] == NULL);
          continue;
        }

      assert(devices[channel] != NULL);
      struct rzv_gpt_lowerhalf_s *priv =
        (struct rzv_gpt_lowerhalf_s *)devices[channel];
      uintptr_t base = channel < 8 ? 0x13010000u + 0x100u * channel :
                                   0x13020000u + 0x100u * (channel - 8u);
      assert(priv->base == base && priv->channel == channel);
      assert(priv->hw_ch == channel % 8u && priv->output == output);
      assert(!priv->initialized && !priv->running);
      snapshot(priv);
      assert(rzv_gpt_initialize_output(channel, output) == devices[channel]);
      assert(rzv_gpt_initialize_output(channel, 1 - output) == NULL);
      assert(rzv_gpt_initialize(channel) ==
             (output == RZV_GPT_OUTPUT_A ? devices[channel] : NULL));
      for (unsigned int previous = 0; previous < channel; previous++)
        {
          assert(devices[previous] != devices[channel]);
        }
    }

  assert(!writes && !reads && !references[0] && !references[1]);
  assert(RZV_GPT_MAX_CHANNELS == 16);
  for (unsigned int channel = 0; channel < 16; channel++)
    {
      assert(!start_calls[channel] && !stop_calls[channel]);
      if (devices[channel])
        {
          lifecycle(devices[channel]);
        }
    }

  /* Hold all selected channels simultaneously, then interleave units while
   * closing them. Clock tests independently own the CPG release behavior.
   */

  for (unsigned int channel = 0; channel < 16; channel++)
    {
      if (devices[channel])
        {
          expected_channel = channel;
          assert(devices[channel]->ops->setup(devices[channel]) == 0);
          assert(start(devices[channel], 1000, 0) == 0);
        }
    }

  for (unsigned int local = 0; local < 8; local++)
    {
      for (unsigned int unit = 0; unit < 2; unit++)
        {
          unsigned int channel = unit * 8u + local;
          if (devices[channel])
            {
              expected_channel = channel;
              assert(devices[channel]->ops->shutdown(devices[channel]) == 0);
            }
        }
    }

  assert(!critical_depth && !references[0] && !references[1]);
#if defined(CONFIG_PWM_PULSECOUNT) && !defined(CONFIG_PWM_MULTICHAN)
  unsigned int enabled = 0;
  for (unsigned int channel = 0; channel < 16; channel++)
    {
      enabled += devices[channel] != NULL;
    }

  assert(attaches == enabled * 3u && detaches == enabled * 2u);
#endif
  return 0;
}
