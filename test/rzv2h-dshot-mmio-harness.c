/* SPDX-License-Identifier: BSD-3-Clause
 * Executes the entire real driver through its public API and host boundaries.
 */
#include "rzv2h-dshot-boundary.h"
#include "rzv2h-dshot-gpt-model.h"
#include "dshot-driver.inc"
#include "rzv2h-dshot-waveform-checks.h"

static void verify_requests(void)
{
  const int events[4]={215,224,274,283};
  for (unsigned i=0; i<4; i++) {
    unsigned ch=io_timers[i].timer_id;
    unsigned output=timer_io_channels[i].timer_channel-1;
    struct host_gpt *gpt=&model_gpt[ch];
    CHECK(model_dma[i].armed_gtintad == (1u<<output),
          "compare DMA request disabled or wrong output selected");
    CHECK(model_dma[i].config.irq_sel == events[i], "wrong DMA event route");
    CHECK(model_dma[i].config.dst_addr == RZV_GPT_LOGICAL_BASE(ch)+
          RZV_GPT_GTCCRA_OFFSET+output*4, "DMA destination not active selected compare");
    CHECK(gpt->reg[RZV_GPT_GTBER_OFFSET/4] == 0 &&
          gpt->reg[RZV_GPT_GTICASR_OFFSET/4] == 0 &&
          gpt->reg[RZV_GPT_GTICBSR_OFFSET/4] == 0,
          "buffer/capture mode conflicts with compare schedule");
  }
}
static void rollback(bool allocation_failure)
{
  if (allocation_failure) fail_allocate=2;
  else fail_configure=2;
  CHECK(up_dshot_init(15,600000,false) < 0, "fault injection did not reject init");
  CHECK(allocated == 0, "initialization leaked timer allocations");
  for (unsigned i=0; i<4; i++)
    CHECK(!model_dma[i].configured && !model_dma[i].enabled,
          "initialization leaked DMA ownership");
  assert_low();
  fail_allocate=fail_configure=-1;
  initialize(600000,15);
  errors=0;
  send_frame();
  verify_frame(600000,15);
}
int main(int argc, char **argv)
{
  CHECK(argc >= 2, "scenario required");
  const char *scenario=argv[1];
  unsigned frequency=argc > 2 ? (unsigned)strtoul(argv[2],NULL,0) : 600000;
  if (!strcmp(scenario,"invalid")) {
    CHECK(up_dshot_arm(true) == -ENODEV, "arm without initialized channels accepted");
    CHECK(up_dshot_init(15,600000,true) == -ENOTSUP, "BDShot init accepted");
    CHECK(up_bdshot_num_erpm_ready() == -ENOTSUP &&
          up_bdshot_get_erpm(0,NULL) == -ENOTSUP &&
          up_bdshot_channel_status(0) == -ENOTSUP, "BDShot API accepted");
    CHECK(up_dshot_init(0,600000,false) == -EINVAL &&
          up_dshot_init(16,600000,false) == -EINVAL &&
          up_dshot_init(15,123,false) == -EINVAL, "invalid initialization accepted");
    clock_hz=0;
    CHECK(up_dshot_init(15,600000,false) == -ERANGE, "zero GPT clock accepted");
    CHECK(allocated == 0, "invalid init allocated timers");
    return 0;
  }
  if (!strcmp(scenario,"allocation-failure") || !strcmp(scenario,"configure-failure")) {
    rollback(!strcmp(scenario,"allocation-failure"));
    return 0;
  }
  unsigned mask=!strcmp(scenario,"subset") ? 5 : 15;
  if (!strcmp(scenario,"stale-registers")) {
    for (unsigned i=0;i<4;i++) {
      struct host_gpt *gpt=&model_gpt[io_timers[i].timer_id];
      unsigned output=timer_io_channels[i].timer_channel-1;
      gpt->duty[output]=GPT_UDDTYC_DTY_0_PERCENT;
      gpt->reg[RZV_GPT_GTUDDTYC_OFFSET/4]=2u<<(16+output*8);
      gpt->reg[RZV_GPT_GTIOR_OFFSET/4]=(1u<<6 | 1u<<7) << (output*16);
      gpt->reg[RZV_GPT_GTBER_OFFSET/4]=UINT32_MAX;
      gpt->reg[RZV_GPT_GTICASR_OFFSET/4]=UINT32_MAX;
      gpt->reg[RZV_GPT_GTICBSR_OFFSET/4]=UINT32_MAX;
    }
  }
  initialize(frequency,mask);
  if (!strcmp(scenario,"cleanup-retry") || !strcmp(scenario,"stop-error")) {
    CHECK(up_dshot_arm(false) == 0, "disarm before cleanup failed");
    bool retry=!strcmp(scenario,"cleanup-retry");
    if (retry) fail_disable=2;
    else fail_stop=2;
    CHECK(up_dshot_init(15,300000,false) == -EIO, "cleanup failure was ignored");
    if (retry) {
      CHECK(allocated == 4 && model_dma[2].configured,
            "failed DMA disable released descriptor/timer ownership");
      CHECK(!(model_gpt[9].reg[RZV_GPT_GTWP_OFFSET/4] & GPT_GTWP_WP),
            "failed DMA disable relocked writable destination");
      CHECK(up_dshot_arm(true) < 0, "incomplete cleanup allowed rearming");
    } else {
      CHECK(allocated == 0, "quiescent stop error leaked timer allocation");
      for (unsigned i=0;i<4;i++)
        CHECK(!model_dma[i].configured, "stop error leaked DMA ownership");
    }
    assert_low();
    fail_disable=fail_stop=-1;
    initialize(300000,15);
    errors=0;
    send_frame();
    verify_frame(300000,15);
    return 0;
  }
  if (!strcmp(scenario,"request")) {
    send_frame();
    verify_requests();
    return 0;
  }
  if (!strcmp(scenario,"disarmed")) {
    CHECK(up_dshot_arm(false) == 0, "disarm failed");
    send_frame();
    assert_low();
    for (unsigned i=0;i<4;i++)
      CHECK(model_dma[i].starts == 0, "disarmed trigger started DMA");
    return 0;
  }
  if (!strcmp(scenario,"reinitialize")) {
    CHECK(up_dshot_init(3,300000,false) == -EBUSY, "armed reinitialization accepted");
    CHECK(up_dshot_arm(false) == 0, "disarm failed");
    initialize(300000,3);
    send_frame();
    verify_frame(300000,3);
    return 0;
  }
  if (!strcmp(scenario,"delay")) completion_delay=96u*10u;
  if (!strcmp(scenario,"timeout")) suppress_dma=true;
  if (!strcmp(scenario,"error")) error_dma=2;
  if (!strcmp(scenario,"start-failure")) fail_start=2;
  if (!strcmp(scenario,"disable-failure")) fail_disable=2;
  if (!strcmp(scenario,"protection") || !strcmp(scenario,"terminal-count")) {
    /* Diagnostic scenarios bypass earlier blockers in the OLD driver only at
     * host boundaries. Full-frame scenarios have no overrides. This isolates
     * WP and TC handling without changing the source under test. */
    bypass_selectors=bypass_requests=true;
    bypass_dma_wp=!strcmp(scenario,"terminal-count");
  }
  send_frame();
  if (!strcmp(scenario,"start-selector")) {
    CHECK(model_gpt[6].starts != 0, "GPT did not start");
    return 0;
  }
  if (!strcmp(scenario,"protection")) {
    CHECK(blocked_dma_writes == 0, "DMA compare writes blocked");
    return 0;
  }
  if (!strcmp(scenario,"terminal-count")) {
    CHECK(model_dma[0].words*4 == model_dma[0].config.length,
          "terminal-count scenario did not actually complete DMA");
    CHECK(errors == 0, "terminal count treated as timeout");
    return 0;
  }
  if (!strcmp(scenario,"timeout") || !strcmp(scenario,"error") ||
      !strcmp(scenario,"start-failure") || !strcmp(scenario,"disable-failure")) {
    CHECK(errors > 0, "DMA fault did not report frame failure");
    assert_low();
    CHECK(illegal_running_writes == 0, "fault cleanup changed running GPT duty");
    for (unsigned i=0;i<4;i++) {
      if ((int)i != fail_disable)
        CHECK(!model_dma[i].enabled, "fault cleanup left DMA enabled");
    }
    unsigned fault_errors=errors;
    unsigned fault_starts[4];
    for (unsigned i=0;i<4;i++) fault_starts[i]=model_dma[i].starts;
    send_frame();
    CHECK(errors == fault_errors, "failed frame kept retrying and flooding logs");
    for (unsigned i=0;i<4;i++)
      CHECK(model_dma[i].starts == fault_starts[i],
            "failed frame rearmed without explicit recovery");
    suppress_dma=false;
    error_dma=fail_start=fail_disable=-1;
    CHECK(up_dshot_arm(false) == 0, "fault recovery disarm failed");
    CHECK(up_dshot_arm(true) == 0, "fault recovery rearm failed");
    clear_waveforms();
    errors=0;
    send_frame();
    verify_frame(frequency,mask);
    return 0;
  }
  verify_frame(frequency,mask);
  if (!strcmp(scenario,"repeat")) {
    for (unsigned i=0; i<3; i++) {
      CHECK(up_dshot_arm(false) == 0, "disarm failed");
      assert_low();
      CHECK(up_dshot_arm(true) == 0, "rearm failed");
      clear_waveforms();
      send_frame();
      verify_frame(frequency,mask);
    }
  }
  return 0;
}
