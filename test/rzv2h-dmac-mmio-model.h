/* Host hardware/cache boundary; production driver is compiled unchanged. */

#include <nuttx/irq.h>
#include "arm_internal.h"
#include "hardware/rzv_dmac.h"
#include "hardware/rzv_intc.h"
#include "rzv_clock.h"

#define SOURCE 0x40810000u
#define SOURCE_NEXT 0x40811000u
#define DESTINATION 0x40820000u
#define LENGTH 64u

struct host_register_s
{
  uintptr_t address;
  uint32_t value;
};

static struct host_register_s registers[2048];
static unsigned int register_count;
static unsigned int writes;
static unsigned int reset_calls;
static int clock_error;
static int reset_error;
static unsigned int cache_calls;
static unsigned int destination_invalidations;
static unsigned int peripheral_cache_calls;
static unsigned int unmasked_starts;
static unsigned int barriers;
static bool destination_dirty;
static bool destination_corrupted;
static bool suppress_enable;

static uint32_t *register_value(uintptr_t address)
{
  for (unsigned int index = 0; index < register_count; index++)
    {
      if (registers[index].address == address)
        {
          return &registers[index].value;
        }
    }

  if (register_count == sizeof(registers) / sizeof(registers[0]))
    {
      abort();
    }

  registers[register_count].address = address;
  return &registers[register_count++].value;
}

uint32_t getreg32(uintptr_t address)
{
  return *register_value(address);
}

static void complete_channel(int channel)
{
  unsigned int unit = RZV_DMAC_UNIT(channel);
  unsigned int local = channel % RZV_DMAC_CHANNELS_PER_UNIT;
  *register_value(RZV_DMAC_CHSTAT(unit, local)) = DMAC_CHSTAT_TC;
  *register_value(RZV_DMAC_CHCFG(unit, local)) &= ~DMAC_CHCFG_DEM;
  *register_value(RZV_DMAC_CRTB(unit, local)) = 0;
}

void putreg32(uint32_t value, uintptr_t address)
{
  writes++;
  *register_value(address) = value;

  for (unsigned int channel = 0; channel < RZV_DMAC_MAX_CHANNELS; channel++)
    {
      unsigned int unit = RZV_DMAC_UNIT(channel);
      unsigned int local = channel % RZV_DMAC_CHANNELS_PER_UNIT;
      if (address != RZV_DMAC_CHCTRL(unit, local))
        {
          continue;
        }

      uint32_t *status = register_value(RZV_DMAC_CHSTAT(unit, local));
      if (value & DMAC_CHCTRL_SWRST)
        {
          *status = 0;
        }

      if (value & DMAC_CHCTRL_CLREN)
        {
          *status &= ~(DMAC_CHSTAT_EN | DMAC_CHSTAT_TACT);
        }

      if (value & DMAC_CHCTRL_CLREND)
        {
          *status &= ~DMAC_CHSTAT_END;
        }

      if (value & DMAC_CHCTRL_CLRTC)
        {
          *status &= ~DMAC_CHSTAT_TC;
        }

      if (value & DMAC_CHCTRL_SETEN)
        {
          if (!(getreg32(RZV_DMAC_CHCFG(unit, local)) & DMAC_CHCFG_DEM))
            {
              unmasked_starts++;
            }

          if (!suppress_enable)
            {
              *status |= DMAC_CHSTAT_EN;
            }
        }

      if (value & DMAC_CHCTRL_STG)
        {
          /* A dirty CPU destination line can evict after DMA writes it.
           * Final invalidation cannot repair the overwritten physical data.
           */
          destination_corrupted |= destination_dirty;
          complete_channel(channel);
        }
    }
}

void modifyreg32(uintptr_t address, uint32_t clear, uint32_t set)
{
  putreg32((getreg32(address) & ~clear) | set, address);
}

void up_clean_dcache(uintptr_t start, uintptr_t end)
{
  (void)end;
  cache_calls++;
  if (start >= 0x10000000u && start < 0x20000000u)
    {
      peripheral_cache_calls++;
    }
}

void up_invalidate_dcache(uintptr_t start, uintptr_t end)
{
  cache_calls++;
  if (start >= 0x10000000u && start < 0x20000000u)
    {
      peripheral_cache_calls++;
    }

  if (start == DESTINATION && end == DESTINATION + LENGTH)
    {
      destination_dirty = false;
      destination_invalidations++;
    }
}

void up_udelay(unsigned int usec)
{
  (void)usec;
}

irqstate_t enter_critical_section(void)
{
  return 0;
}

void leave_critical_section(irqstate_t flags)
{
  (void)flags;
}

void host_dsb(void)
{
  barriers++;
}

int rzv_clock_enable(uint32_t clock)
{
  (void)clock;
  return clock_error;
}

int rzv_module_unreset(uint32_t clock)
{
  (void)clock;
  reset_calls++;
  return reset_error;
}
