/* Host boundary for the real start/update functions extracted by Python. */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#include "hardware/rzv_gpt.h"

#define FAR
#define OK 0
#define UNUSED(value) ((void)(value))
#define nitems(values) (sizeof(values) / sizeof((values)[0]))
#define b16ONE 0x10000u
#define CONFIG_PWM_NCHANNELS 3

typedef uint32_t ub16_t;
typedef unsigned int irqstate_t;

enum rzv_gpt_output_e
{
  RZV_GPT_OUTPUT_A,
  RZV_GPT_OUTPUT_B
};

struct pwm_lowerhalf_s
{
  void *ops;
};

struct pwm_info_s
{
  uint32_t frequency;
  ub16_t duty;
  uint32_t count;
  struct
  {
    int channel;
    ub16_t duty;
  } channels[CONFIG_PWM_NCHANNELS];
};

#include "gpt-driver-types.inc"

static uint32_t registers[64];
static unsigned int writes;
static unsigned int setups;
static unsigned int irq_enabled;

#include "rzv2h-gpt-pwm-overflow-model.h"

static uint32_t gpt_getreg(struct rzv_gpt_lowerhalf_s *priv,
                           unsigned int offset)
{
  UNUSED(priv);
  if (live_model)
    {
      model_after_access();
    }
  return registers[offset / 4];
}

static void gpt_putreg(struct rzv_gpt_lowerhalf_s *priv,
                       unsigned int offset, uint32_t value)
{
  UNUSED(priv);
  registers[offset / 4] = value;
  writes++;
  if (live_model)
    {
      model_after_write(offset, value);
    }
}

static irqstate_t enter_critical_section(void)
{
  return 0;
}

static void leave_critical_section(irqstate_t flags)
{
  UNUSED(flags);
}

static int rzv_gpt_setup(struct pwm_lowerhalf_s *dev)
{
  struct rzv_gpt_lowerhalf_s *priv = (struct rzv_gpt_lowerhalf_s *)dev;
  setups++;
  priv->initialized = true;
  return OK;
}

#ifdef CONFIG_PWM_PULSECOUNT
static int rzv_gpt_attach_irq(struct rzv_gpt_lowerhalf_s *priv)
{
  priv->irq = 1;
  return OK;
}

static void up_enable_irq(int irq)
{
  UNUSED(irq);
  irq_enabled++;
}
#endif

#include "gpt-driver-functions.inc"
#include "rzv2h-gpt-pwm-live-checks.h"

int main(int argc, char **argv)
{
  if (argc != 7)
    {
      return 2;
    }

  if (strcmp(argv[1], "live") == 0)
    {
      return run_live_update(argv);
    }

  struct rzv_gpt_lowerhalf_s priv =
  {
    .pclk = 1000000,
    .initialized = strtoul(argv[5], NULL, 0),
    .output = strtoul(argv[3], NULL, 0)
  };
  struct pwm_info_s info =
  {
    .frequency = 1000,
    .duty = strtoul(argv[2], NULL, 0),
    .count = strtoul(argv[4], NULL, 0),
    .channels = {{1, 0}, {2, 0}, {-1, 0}}
  };
  info.channels[priv.output].duty = info.duty;
#ifdef CONFIG_PWM_PULSECOUNT
  void *handle = strtoul(argv[6], NULL, 0) ? &info : NULL;
  int ret = rzv_gpt_start(&priv.dev, &info, handle);
#else
  int ret = rzv_gpt_start(&priv.dev, &info);
#endif

  /* Reading through the same MMIO boundary also keeps the update dependency
   * available for fixes that inspect the existing buffer configuration. */
  (void)gpt_getreg(&priv, RZV_GPT_GTBER_OFFSET);
  printf("%d %u %u %u %u\n", ret, writes, setups,
         priv.running, irq_enabled);
  return 0;
}
