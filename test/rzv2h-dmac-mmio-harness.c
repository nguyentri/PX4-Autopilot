/* Execute the complete real DMAC driver against observable host boundaries. */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

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
    .elc_event = hardware ? 263 : -1
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
      config.elc_event = 0x3ff;
      CHECK(rzv_dmac_channel_configure(0, &config) == -EINVAL,
            "disabled route accepted");
      config = configuration(false);
      config.length = 0;
      CHECK(rzv_dmac_channel_configure(0, &config) == -EINVAL,
            "zero length accepted");
      CHECK(rzv_dmac_channel_start(-1) == -EINVAL, "negative channel accepted");
      CHECK(rzv_dmac_channel_start(80) == -EINVAL, "out-of-range channel accepted");
      CHECK(writes == 0 && cache_calls == 0, "invalid config touched hardware");
      return 0;
    }

  if (strcmp(scenario, "routing") == 0)
    {
      config = configuration(true);
      CHECK(rzv_dmac_channel_configure(8, &config) == 0, "route 8 configure");
      config.elc_event = 264;
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
