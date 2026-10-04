/* SPDX-License-Identifier: BSD-3-Clause
 * Protocol oracle: decode observed high widths, independent of DMA payload.
 */
#ifndef RZV2H_DSHOT_WAVEFORM_CHECKS_H
#define RZV2H_DSHOT_WAVEFORM_CHECKS_H
static const uint16_t motor_throttle[4]={0,48,1049,2047};
static const bool motor_telemetry[4]={false,true,false,true};
static void assert_low(void)
{
  for (unsigned ch=0; ch<16; ch++) {
    CHECK(!model_gpt[ch].running, "GPT still running after cleanup");
    CHECK(!model_gpt[ch].level[0] && !model_gpt[ch].level[1],
          "output not low after cleanup");
  }
}
static void clear_waveforms(void)
{
  for (unsigned ch=0; ch<16; ch++)
    memset(model_gpt[ch].edges,0,sizeof(model_gpt[ch].edges));
}
static void send_frame(void)
{
  for (unsigned i=0; i<4; i++)
    dshot_motor_data_set(i,motor_throttle[i],motor_telemetry[i]);
  up_dshot_trigger();
}
static void verify_frame(unsigned frequency, unsigned mask)
{
  uint32_t period=96000000u/frequency;
  for (unsigned i=0; i<4; i++) {
    unsigned ch=io_timers[i].timer_id;
    unsigned output=timer_io_channels[i].timer_channel-1;
    struct host_gpt *gpt=&model_gpt[ch];
    if (!(mask & (1u<<i))) {
      CHECK(gpt->starts == 0 && !model_dma[i].configured,
            "unselected channel resources touched");
      continue;
    }
    CHECK(gpt->starts != 0, "GPT did not start");
    if (gpt->edges[output] != 32)
      fprintf(stderr,"GPT%u%c edges=%u\n",ch,'A'+output,gpt->edges[output]);
    CHECK(gpt->edges[output] == 32, "frame must have exactly 32 edges");
    CHECK(gpt->edges[output^1] == 0, "unselected GPT output emitted edges");
    uint16_t received=0;
    for (unsigned bit=0; bit<16; bit++) {
      unsigned edge=bit*2;
      CHECK(gpt->edge_level[output][edge] && !gpt->edge_level[output][edge+1],
            "DShot edges do not alternate high/low");
      uint64_t high=gpt->edge_time[output][edge+1]-gpt->edge_time[output][edge];
      CHECK(high == period*3/8 || high == period*3/4,
            "DShot high width does not encode zero or one");
      received=(uint16_t)((received<<1)|(high == period*3/4));
      if (bit)
        CHECK(gpt->edge_time[output][edge]-gpt->edge_time[output][edge-2] == period,
              "DShot bit period incorrect");
    }
    uint16_t payload=received>>4;
    CHECK(payload == (uint16_t)((motor_throttle[i]<<1)|motor_telemetry[i]),
          "observed throttle/telemetry payload incorrect");
    CHECK((received&15) == ((payload^(payload>>4)^(payload>>8))&15),
          "observed DShot checksum incorrect");
    CHECK(model_dma[i].words*4 == model_dma[i].config.length,
          "DMA did not transfer complete frame");
    CHECK(gpt->reg[RZV_GPT_GTWP_OFFSET/4] & GPT_GTWP_WP,
          "GPT remained writable after quiescent DMA cleanup");
  }
  CHECK(errors == 0, "complete frame was reported as failure");
  CHECK(blocked_dma_writes == 0, "DMA compare writes blocked");
  CHECK(illegal_running_writes == 0, "GPT direction/duty changed while running");
  assert_low();
  up_udelay(20);
  for (unsigned i=0; i<4; i++)
    if (mask & (1u<<i))
      CHECK(model_gpt[io_timers[i].timer_id].edges[i%2] == 32,
            "inter-frame gap emitted extra edges");
}
static void initialize(unsigned frequency, unsigned mask)
{
  CHECK(up_dshot_init(mask,frequency,false) == (int)mask, "DShot initialization failed");
  CHECK(allocated == mask, "timer allocation mask incorrect");
  assert_low();
  CHECK(up_dshot_arm(true) == 0, "DShot arm failed");
}
#endif
