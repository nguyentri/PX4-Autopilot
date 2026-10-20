/* Execute the complete real DMAC driver against observable host boundaries. */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>

#include "rzv_dmac.h"
#include "rzv2h-dmac-mmio-model.h"

#define CHECK(condition, message) \
  do \
    { \
      if (!(condition)) \
        { \
          fprintf(stderr, "FAIL: %s\n", message); \
          return 1; \
        } \
    } \
  while (0)

static char error_log[8192];

void host_dma_error(const char *format, ...)
{
  size_t used = strlen(error_log);
  va_list args;
  va_start(args, format);
  vsnprintf(error_log + used, sizeof(error_log) - used, format, args);
  va_end(args);
}

static struct rzv_dmac_config_s configuration(bool hardware)
{
  struct rzv_dmac_config_s config =
  {
    .src_size = RZV_DMAC_SIZE_4BYTE,
    .dst_size = RZV_DMAC_SIZE_4BYTE,
    .src_addr_mode = RZV_DMAC_ADDR_INCREMENT,
    .dst_addr_mode = hardware ? RZV_DMAC_ADDR_FIXED : RZV_DMAC_ADDR_INCREMENT,
    .trigger = hardware ? RZV_DMAC_TRIGGER_HW : RZV_DMAC_TRIGGER_SW,
    .src_addr = SOURCE,
    .dst_addr = hardware ? 0x13014054u : DESTINATION,
    .length = LENGTH,
    .irq_sel = hardware ? 263 : -1
  };
  return config;
}

static void callback(int channel, int event, void *data)
{
  (void)channel;
  (void)event;
  (void)data;
}

int main(int argc, char **argv)
{
  CHECK(argc == 2, "scenario required");
  const char *scenario = argv[1];
  struct rzv_dmac_config_s config = configuration(false);

  if (strcmp(scenario, "stale-route") == 0)
    {
      uintptr_t route = RZV_INTC_BASE + RZV_INTC_DM4SEL0_OFFSET;
      *register_value(route) = 215u | (224u << 16) | (1u << 15);
      CHECK(rzv_dmac_channel_configure(0, &config) == 0,
            "software configure with stale route failed");
      CHECK((getreg32(route) & 0x3ffu) == 0x3ffu,
            "software owner inherited a peripheral activation route");
      CHECK((getreg32(route) >> 16) == 224u,
            "software configure changed its sibling route");
      CHECK(rzv_dmac_channel_stop(0) == 0, "software release failed");
      config = configuration(true);
      CHECK(rzv_dmac_channel_configure(0, &config) == 0,
            "hardware configure failed");
      CHECK((getreg32(route) & (1u << 15)) == 0,
            "polling owner inherited route auto-clear");
      *register_value(route) |= 0x3ffu;
      CHECK(rzv_dmac_channel_start(0) == 0, "hardware start failed");
      CHECK((getreg32(route) & 0x3ffu) == 263u,
            "start did not restore its activation route");
      CHECK(rzv_dmac_channel_stop(0) == 0, "hardware release failed");
      suppress_route_write = true;
      CHECK(rzv_dmac_channel_configure(0, &config) == -EIO,
            "ignored route write was reported as successful");
      suppress_route_write = false;
      CHECK(rzv_dmac_channel_configure(0, &config) == 0,
            "rejected route leaked a configuration claim");
      return 0;
    }

  if (strcmp(scenario, "warm-configure") == 0)
    {
      *register_value(RZV_DMAC_CHSTAT(0, 0)) =
        DMAC_CHSTAT_ER | DMAC_CHSTAT_END | DMAC_CHSTAT_TC;
      CHECK(rzv_dmac_channel_configure(0, &config) == 0,
            "inactive channel with stale error could not configure");
      CHECK(getreg32(RZV_DMAC_CHSTAT(0, 0)) == 0,
            "new owner inherited completion/error from previous image");
      for (unsigned int active = DMAC_CHSTAT_EN;
           active <= DMAC_CHSTAT_TACT; active = DMAC_CHSTAT_TACT)
        {
          *register_value(RZV_DMAC_CHSTAT(0, 1)) = active;
          *register_value(RZV_DMAC_N0SA(0, 1)) = 0xfeed0000;
          unsigned int before = writes;
          CHECK(rzv_dmac_channel_configure(1, &config) == -EBUSY,
                "new owner overwrote a live hardware channel");
          CHECK(writes == before &&
                getreg32(RZV_DMAC_N0SA(0, 1)) == 0xfeed0000,
                "busy rejection reset or changed live hardware");
          if (active == DMAC_CHSTAT_TACT)
            {
              break;
            }
        }

      *register_value(RZV_DMAC_CHSTAT(0, 1)) = 0;
      CHECK(rzv_dmac_channel_configure(1, &config) == 0,
            "busy configure left a leaked software claim");
      return 0;
    }

  if (strcmp(scenario, "priority-protection") == 0)
    {
      config.priority = 1;
      CHECK(rzv_dmac_channel_configure(0, &config) == -ENOTSUP,
            "arbitration priority silently changed AXI protection");
      CHECK(writes == 0 && cache_calls == 0,
            "unsupported priority touched hardware");

      config.priority = 0;
      config.src_prot = 8;
      CHECK(rzv_dmac_channel_configure(0, &config) == -EINVAL,
            "out-of-range source protection accepted");
      config.src_prot = 0;
      config.dst_prot = 8;
      CHECK(rzv_dmac_channel_configure(0, &config) == -EINVAL,
            "out-of-range destination protection accepted");
      CHECK(writes == 0 && cache_calls == 0,
            "invalid protection touched hardware");

      for (int unit = 0; unit < 5; unit++)
        {
          int channel = unit * 16 + 8;
          config.src_prot = 1;
          config.dst_prot = 2;
          CHECK(rzv_dmac_channel_configure(channel, &config) == 0,
                "explicit protection configure failed");
          CHECK(getreg32(RZV_DMAC_CHEXT(unit, 8)) == 0x201,
                "source/destination protection not independent");
          CHECK(rzv_dmac_channel_stop(channel) == 0,
                "protection channel release failed");
          config.src_prot = 0;
          config.dst_prot = 0;
          CHECK(rzv_dmac_channel_configure(channel, &config) == 0,
                "default protection configure failed");
          CHECK(getreg32(RZV_DMAC_CHEXT(unit, 8)) == 0,
                "explicit protection leaked into next owner");
        }

      return 0;
    }

  if (strcmp(scenario, "error-diagnostics") == 0)
    {
      CHECK(RZV_INTC_BEISR(0) == 0x10400070u &&
            RZV_INTC_BEISR(3) == 0x1040007cu,
            "bus-error diagnostics use incorrect register offsets");
      for (int unit = 0; unit < 3; unit++)
        {
          int channel = unit * 16 + 8;
          char identity[64];
          CHECK(rzv_dmac_channel_configure(channel, &config) == 0,
                "diagnostic configure failed");
          CHECK(rzv_dmac_channel_start(channel) == 0,
                "diagnostic start failed");
          *register_value(RZV_DMAC_CHSTAT(unit, 8)) = DMAC_CHSTAT_ER;
          *register_value(RZV_DMAC_CRTB(unit, 8)) = LENGTH - 4;
          error_log[0] = '\0';
          restrict_diagnostic_reads = true;
          CHECK(rzv_dmac_channel_disable(channel) == -EIO,
                "diagnostic error was discarded");
          restrict_diagnostic_reads = false;
          CHECK(getreg32(RZV_DMAC_CHSTAT(unit, 8)) == 0,
                "diagnostics prevented normal reset cleanup");
          snprintf(identity, sizeof(identity), "DMAC%d group1 ch0 global%d",
                   unit, channel);
          CHECK(strstr(error_log, identity) != NULL,
                "error log lost unit/group/channel identity");
          CHECK(strstr(error_log, "CHSTAT=0x00000010") != NULL,
                "error status was not logged before reset");
          CHECK(strstr(error_log, "CRTB=60") != NULL,
                "error log lost the failure byte count");
          *register_value(RZV_DMAC_CHSTAT(unit, 8)) = DMAC_CHSTAT_ER;
          error_log[0] = '\0';
          CHECK(rzv_dmac_channel_disable(channel) == -EIO,
                "repeated error was discarded");
          CHECK(error_log[0] == '\0',
                "repeated frames flooded the error log");
          CHECK(rzv_dmac_channel_stop(channel) == 0,
                "diagnostic release failed");
          CHECK(rzv_dmac_channel_configure(channel, &config) == 0,
                "diagnostic reconfigure failed");
          *register_value(RZV_DMAC_CHSTAT(unit, 8)) = DMAC_CHSTAT_ER;
          CHECK(rzv_dmac_channel_disable(channel) == -EIO,
                "new owner error was discarded");
          CHECK(strstr(error_log, identity) != NULL,
                "new owner could not report its first error");
        }

      return 0;
    }

  if (strcmp(scenario, "enable-diagnostics") == 0)
    {
      suppress_enable = true;
      for (int unit = 0; unit < 3; unit++)
        {
          int channel = unit * 16 + 8;
          char identity[64];
          CHECK(rzv_dmac_channel_configure(channel, &config) == 0,
                "enable diagnostic configure failed");
          error_log[0] = '\0';
          CHECK(rzv_dmac_channel_start(channel) == -ETIMEDOUT,
                "missing enable did not time out");
          snprintf(identity, sizeof(identity), "DMAC%d group1 ch0 global%d",
                   unit, channel);
          CHECK(strstr(error_log, identity) != NULL,
                "enable failure lost unit/group/channel identity");
          CHECK(strstr(error_log, "N0TB=64") != NULL,
                "enable failure lost descriptor readback");
          CHECK(rzv_dmac_channel_stop(channel) == 0,
                "enable failure prevented release");
        }

      return 0;
    }

  if (strcmp(scenario, "clock-failure") == 0 ||
      strcmp(scenario, "reset-failure") == 0)
    {
      bool clock_fails = strcmp(scenario, "clock-failure") == 0;
      clock_error = clock_fails ? -ETIMEDOUT : 0;
      reset_error = clock_fails ? 0 : -EIO;
      CHECK(rzv_dmac_channel_initialize(0) ==
            (clock_fails ? -ETIMEDOUT : -EIO),
            "initialization error was discarded");
      CHECK(writes == 0, "DMAC registers written after clock/reset error");
      CHECK(reset_calls == (clock_fails ? 0 : 1),
            "reset attempted after clock failure");
      clock_error = 0;
      reset_error = 0;
      CHECK(rzv_dmac_channel_initialize(0) == 0,
            "failed initialization could not be retried");
      CHECK(writes > 0, "retry did not initialize hardware");
      return 0;
    }

  if (strcmp(scenario, "invalid") == 0)
    {
      config.callback = callback;
      CHECK(rzv_dmac_channel_configure(0, &config) == -ENOTSUP,
            "callback accepted");
      config.callback = NULL;
      config.src_addr = 0x1ffe0u;
      CHECK(rzv_dmac_channel_configure(0, &config) == -EINVAL,
            "cross-TCM range accepted");
      config = configuration(true);
      config.irq_sel = 0x3ff;
      CHECK(rzv_dmac_channel_configure(0, &config) == -EINVAL,
            "disabled route accepted");
      config = configuration(false);
      config.length = 0;
      CHECK(rzv_dmac_channel_configure(0, &config) == -EINVAL,
            "zero length accepted");
      config = configuration(true);
      config.src_addr_mode = RZV_DMAC_ADDR_FIXED;
      config.src_addr = 0x12800054u;
      CHECK(rzv_dmac_channel_configure(0, &config) == -ENOTSUP,
            "peripheral-to-peripheral accepted");
      config = configuration(false);
      config.ack_mode = 4;
      CHECK(rzv_dmac_channel_configure(0, &config) == -ENOTSUP,
            "software trigger accepted DACK mode");
      config = configuration(true);
      config.ack_mode = 8;
      CHECK(rzv_dmac_channel_configure(0, &config) == -ENOTSUP,
            "out-of-range DACK mode accepted");
      config = configuration(false);
      CHECK(rzv_dmac_channel_start(-1) == -EINVAL, "negative channel accepted");
      CHECK(rzv_dmac_channel_start(80) == -EINVAL, "out-of-range channel accepted");
      CHECK(writes == 0 && cache_calls == 0, "invalid config touched hardware");
      return 0;
    }

  if (strcmp(scenario, "routing") == 0)
    {
      config = configuration(true);
      CHECK(rzv_dmac_channel_configure(8, &config) == 0, "route 8 configure");
      config.irq_sel = 264;
      CHECK(rzv_dmac_channel_configure(9, &config) == 0, "route 9 configure");
      uintptr_t route = RZV_INTC_BASE + RZV_INTC_DM4SEL0_OFFSET + 16u;
      CHECK((getreg32(route) & 0x3ffu) == 263, "route 8 overwritten");
      CHECK(rzv_dmac_channel_disable(8) == 0, "disable route 8");
      CHECK((getreg32(route) & 0x3ffu) == 263, "disable lost retained route");
      CHECK(rzv_dmac_channel_stop(8) == 0, "release route 8");
      CHECK((getreg32(route) & 0x3ffu) == 0x3ffu, "release kept route");
      CHECK(((getreg32(route) >> 16) & 0x3ffu) == 264, "sibling route lost");
      return 0;
    }

  if (strcmp(scenario, "peripheral-source") == 0)
    {
      config = configuration(true);
      config.src_addr_mode = RZV_DMAC_ADDR_FIXED;
      config.dst_addr_mode = RZV_DMAC_ADDR_INCREMENT;
      config.src_addr = 0x12800054u;
      config.dst_addr = DESTINATION;
      config.ack_mode = 4;
      CHECK(rzv_dmac_channel_configure(1, &config) == 0,
            "peripheral-to-memory configure");
      uint32_t chcfg = getreg32(RZV_DMAC_CHCFG(0, 1));
      CHECK((chcfg & DMAC_CHCFG_AM_MASK) == (4u << DMAC_CHCFG_AM_SHIFT),
            "DACK mode not programmed");
      CHECK((chcfg & (DMAC_CHCFG_REQD | DMAC_CHCFG_SAD | DMAC_CHCFG_HIEN)) ==
            (DMAC_CHCFG_REQD | DMAC_CHCFG_SAD | DMAC_CHCFG_HIEN),
            "receive requester or fixed source not programmed");
      CHECK((chcfg & DMAC_CHCFG_DAD) == 0, "memory destination fixed");

      unsigned int saved_invalidations = destination_invalidations;
      destination_dirty = true;
      CHECK(rzv_dmac_channel_start(1) == 0, "peripheral-to-memory start");
      CHECK(destination_invalidations == saved_invalidations + 1,
            "start did not prepare memory destination");
      CHECK(!destination_dirty, "dirty destination survived start");
      complete_channel(1);
      CHECK(rzv_dmac_channel_set_buffer(1, SOURCE_NEXT, LENGTH) == -ENOTSUP,
            "peripheral source replaced after completion");
      saved_invalidations = destination_invalidations;
      CHECK(rzv_dmac_channel_stop(1) == 0, "peripheral-to-memory stop");
      CHECK(destination_invalidations == saved_invalidations + 1,
            "stop did not invalidate memory destination");
      CHECK(peripheral_cache_calls == 0, "peripheral source cache-maintained");

      config = configuration(true);
      config.ack_mode = 4;
      config.source_request = true;
      CHECK(rzv_dmac_channel_configure(0, &config) == 0,
            "source-requested transmit configure");
      CHECK((getreg32(RZV_DMAC_CHCFG(0, 0)) & DMAC_CHCFG_REQD) == 0,
            "source requester not programmed");
      return 0;
    }

  bool hardware = strcmp(scenario, "enabled-start") == 0 ||
                  strcmp(scenario, "enabled-buffer") == 0 ||
                  strcmp(scenario, "hardware-mask") == 0 ||
                  strcmp(scenario, "active") == 0;
  config = configuration(hardware);
  CHECK(rzv_dmac_channel_configure(0, &config) == 0, "configure failed");

  if (strcmp(scenario, "cleanup") == 0)
    {
      suppress_enable = true;
      CHECK(rzv_dmac_channel_start(0) == -ETIMEDOUT, "missing enable timeout");
      CHECK(rzv_dmac_channel_stop(0) == 0, "timeout release failed");
      suppress_enable = false;
      CHECK(rzv_dmac_channel_configure(0, &config) == 0, "timeout reuse failed");
      *register_value(RZV_DMAC_CHSTAT(0, 0)) = DMAC_CHSTAT_ER;
      CHECK(rzv_dmac_channel_stop(0) == -EIO, "error not propagated");
      CHECK(rzv_dmac_channel_configure(0, &config) == 0, "error release failed");
      *register_value(RZV_DMAC_DSTAT_ER(0, 0)) = 1;
      CHECK(rzv_dmac_channel_stop(0) == -EIO, "group error not propagated");
      *register_value(RZV_DMAC_DSTAT_ER(0, 0)) = 0;
      CHECK(rzv_dmac_channel_start(0) == -EINVAL, "released channel started");
      CHECK(rzv_dmac_channel_configure(0, &config) == 0, "group-error reuse failed");
      return 0;
    }

  if (strcmp(scenario, "cached-first") != 0)
    {
      CHECK(rzv_dmac_channel_start(0) == 0, "first start failed");
    }

  if (strcmp(scenario, "enabled-start") == 0 ||
      strcmp(scenario, "enabled-buffer") == 0 ||
      strcmp(scenario, "active") == 0)
    {
      if (strcmp(scenario, "active") == 0)
        {
          *register_value(RZV_DMAC_CHSTAT(0, 0)) = DMAC_CHSTAT_TACT;
        }

      unsigned int saved_writes = writes;
      unsigned int saved_cache = cache_calls;
      if (strcmp(scenario, "enabled-buffer") == 0)
        {
          CHECK(rzv_dmac_channel_set_buffer(0, SOURCE_NEXT, LENGTH) == -EBUSY,
                "enabled hardware channel accepted buffer replacement");
        }
      else
        {
          CHECK(rzv_dmac_channel_start(0) == -EBUSY,
                "enabled or bus-active channel accepted restart");
        }

      CHECK(writes == saved_writes && cache_calls == saved_cache,
            "busy rejection modified hardware or cache");
      return 0;
    }

  if (strcmp(scenario, "cached-restart") == 0 ||
      strcmp(scenario, "cached-first") == 0)
    {
      if (strcmp(scenario, "cached-restart") == 0)
        {
          CHECK(rzv_dmac_channel_disable(0) == 0, "retained disable failed");
        }

      unsigned int saved_invalidations = destination_invalidations;
      destination_dirty = true;
      CHECK(rzv_dmac_channel_start(0) == 0, "cached start failed");
      CHECK(!destination_corrupted, "dirty destination overwrote DMA data");
      CHECK(destination_invalidations == saved_invalidations + 1,
            "start did not prepare destination cache");
      return 0;
    }

  if (hardware)
    {
      CHECK(peripheral_cache_calls == 0, "peripheral destination invalidated");
      complete_channel(0);
    }

  CHECK(rzv_dmac_channel_set_buffer(0, SOURCE_NEXT, LENGTH - 32) == -ENOTSUP,
        "replacement changed destination extent");
  CHECK(rzv_dmac_channel_set_buffer(0, SOURCE_NEXT, LENGTH) == 0,
        "disabled completed channel rejected replacement");
  uint32_t saved_configuration = getreg32(RZV_DMAC_CHCFG(0, 0));
  CHECK(rzv_dmac_channel_start(0) == 0, "completed one-shot did not rearm");
  CHECK(getreg32(RZV_DMAC_N0SA(0, 0)) == SOURCE_NEXT,
        "replacement source not retained across restart");
  CHECK((getreg32(RZV_DMAC_CHCFG(0, 0)) & ~DMAC_CHCFG_DEM) ==
        (saved_configuration & ~DMAC_CHCFG_DEM), "start changed transfer mode");
  if (strcmp(scenario, "complete-rearm") != 0)
    {
      CHECK(unmasked_starts == 0, "repeated start enabled completion interrupt");
    }

  CHECK(barriers >= 2, "descriptor publication barrier missing");
  CHECK(peripheral_cache_calls == 0, "restart invalidated peripheral destination");
  return 0;
}
