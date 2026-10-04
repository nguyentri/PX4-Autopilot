/* SPDX-License-Identifier: BSD-3-Clause
 * Bounded GPT saw-wave/DMAC model. Independent of driver frame preparation.
 * Event IDs: checked-in FSP bsp_dmac.h. Selectors/WP/GTIOR: GPT registers.
 * DMA executes one word per event; real bus latency is outside this model.
 */
#ifndef RZV2H_DSHOT_GPT_MODEL_H
#define RZV2H_DSHOT_GPT_MODEL_H
static unsigned decode_gpt(uintptr_t address, unsigned *offset)
{
  for (unsigned ch=0; ch<16; ch++) {
    uintptr_t base=RZV_GPT_LOGICAL_BASE(ch);
    if (address >= base && address < base+0x100) {
      *offset=(unsigned)(address-base);
      return ch;
    }
  }
  CHECK(false, "unexpected MMIO address (sparse GPT map)");
  return 0;
}
static void set_level(unsigned ch, unsigned output, bool level)
{
  struct host_gpt *gpt=&model_gpt[ch];
  if (gpt->level[output] == level) return;
  unsigned edge=gpt->edges[output]++;
  CHECK(edge < 128, "unexpected unbounded output edges");
  gpt->edge_time[output][edge]=model_ticks;
  gpt->edge_level[output][edge]=level;
  gpt->level[output]=level;
}
static unsigned output_mode(struct host_gpt *gpt, unsigned output)
{
  return (gpt->reg[RZV_GPT_GTIOR_OFFSET/4] >> (output*16)) & 31u;
}
static bool output_enabled(struct host_gpt *gpt, unsigned output)
{
  return (gpt->reg[RZV_GPT_GTIOR_OFFSET/4] & (1u<<(8+output*16))) != 0;
}
static uint32_t getreg32(uintptr_t address)
{
  unsigned offset;
  unsigned ch=decode_gpt(address, &offset);
  return model_gpt[ch].reg[offset/4];
}
static void putreg32(uint32_t value, uintptr_t address)
{
  unsigned offset;
  unsigned ch=decode_gpt(address, &offset);
  struct host_gpt *gpt=&model_gpt[ch];
  if (offset == RZV_GPT_GTWP_OFFSET) {
    if ((value & GPT_GTWP_PRKEY_MASK) == GPT_GTWP_PRKEY)
      gpt->reg[offset/4]=value;
    return;
  }
  if (offset == RZV_GPT_GTSTR_OFFSET || offset == RZV_GPT_GTSTP_OFFSET ||
      offset == RZV_GPT_GTCLR_OFFSET) {
    unsigned selector=offset == RZV_GPT_GTSTR_OFFSET ? RZV_GPT_GTSSR_OFFSET :
      offset == RZV_GPT_GTSTP_OFFSET ? RZV_GPT_GTPSR_OFFSET : RZV_GPT_GTCSR_OFFSET;
    /* Group commands are independent of ordinary GTWP.WP protection. */
    unsigned first=ch < 8 ? 0 : 8;
    for (unsigned target=first; target<first+8; target++) {
      struct host_gpt *other=&model_gpt[target];
      if (!(value & RZV_GPT_LOGICAL_UNIT_BIT(target)) ||
          (!bypass_selectors && !(other->reg[selector/4] & (1u<<31)))) continue;
      if (offset == RZV_GPT_GTSTR_OFFSET) {
        other->running=true;
        other->reg[RZV_GPT_GTCR_OFFSET/4] |= GPT_GTCR_CST;
        other->starts++;
      } else if (offset == RZV_GPT_GTSTP_OFFSET) {
        other->running=false;
        other->reg[RZV_GPT_GTCR_OFFSET/4] &= ~GPT_GTCR_CST;
        for (unsigned output=0; output<2; output++) {
          uint32_t gtior=other->reg[RZV_GPT_GTIOR_OFFSET/4];
          if (output_enabled(other, output) && !(gtior & (1u<<(7+output*16))))
            set_level(target,output,(gtior & (1u<<(6+output*16))) != 0);
        }
      } else {
        other->reg[RZV_GPT_GTCNT_OFFSET/4]=0;
      }
    }
    return;
  }
  if (gpt->reg[RZV_GPT_GTWP_OFFSET/4] & GPT_GTWP_WP) return;
  if (gpt->running && (offset == RZV_GPT_GTUDDTYC_OFFSET ||
      offset == RZV_GPT_GTCR_OFFSET || offset == RZV_GPT_GTBER_OFFSET))
    illegal_running_writes++;
  if (offset == RZV_GPT_GTIOR_OFFSET) {
    for (unsigned output=0; output<2; output++)
      if (output_enabled(gpt,output) && !(value & (1u<<(8+output*16))))
        CHECK(!gpt->running && !gpt->level[output],
              "GPT output disabled before timer stopped with driven low level");
  }
  gpt->reg[offset/4]=value;
  if (offset == RZV_GPT_GTCR_OFFSET)
    gpt->running=(value & GPT_GTCR_CST) != 0;
  if (offset == RZV_GPT_GTUDDTYC_OFFSET && !gpt->running &&
      (value & GPT_GTUDDTYC_UDF))
    gpt->up=(value & GPT_GTUDDTYC_UD) != 0;
  if (offset == RZV_GPT_GTUDDTYC_OFFSET && !gpt->running) {
    /* OADTYF/OBDTYF apply duty at the next start; clearing UDF/F releases
     * force control without undoing the latched stopped update. */
    for (unsigned output=0; output<2; output++)
      if (value & (1u<<(18+output*8)))
        gpt->duty[output]=(value >> (16+output*8)) & 3u;
  }
  if (offset == RZV_GPT_GTIOR_OFFSET || offset == RZV_GPT_GTUDDTYC_OFFSET) {
    for (unsigned output=0; output<2; output++) {
      unsigned duty=gpt->duty[output];
      if (output_enabled(gpt, output) && !gpt->running && duty == 2)
        set_level(ch, output, false);
    }
  }
}
static void dma_event(int event)
{
  if (suppress_dma) return;
  for (unsigned ch=0; ch<4; ch++) {
    struct host_dma *dma=&model_dma[ch];
    if (!dma->enabled || dma->config.elc_event != event) continue;
    unsigned offset;
    unsigned target=decode_gpt(dma->config.dst_addr, &offset);
    if (!bypass_dma_wp &&
        (model_gpt[target].reg[RZV_GPT_GTWP_OFFSET/4] & GPT_GTWP_WP))
      blocked_dma_writes++;
    else {
      uint32_t wp=model_gpt[target].reg[RZV_GPT_GTWP_OFFSET/4];
      if (bypass_dma_wp) model_gpt[target].reg[RZV_GPT_GTWP_OFFSET/4]=0;
      putreg32(((const uint32_t *)dma->config.src_addr)[dma->words],
               dma->config.dst_addr);
      model_gpt[target].reg[RZV_GPT_GTWP_OFFSET/4]=wp;
    }
    dma->words++;
    if (dma->words*4 == dma->config.length) {
      dma->enabled=false;
      dma->status=DMAC_CHSTAT_TC; /* DEM masks END in the real polling driver. */
      dma->completed=model_ticks;
    }
  }
}
static void model_tick(void)
{
  model_ticks++;
  for (unsigned ch=0; ch<16; ch++) {
    struct host_gpt *gpt=&model_gpt[ch];
    if (!gpt->running || !gpt->up) continue;
    uint32_t count=++gpt->reg[RZV_GPT_GTCNT_OFFSET/4];
    if (count > gpt->reg[RZV_GPT_GTPR_OFFSET/4]) {
      count=0;
      gpt->reg[RZV_GPT_GTCNT_OFFSET/4]=0;
      for (unsigned output=0; output<2; output++) {
        gpt->duty[output]=(gpt->reg[RZV_GPT_GTUDDTYC_OFFSET/4] >> (16+output*8)) & 3u;
        unsigned mode=output_mode(gpt, output);
        if (output_enabled(gpt, output))
          set_level(ch, output, mode == 0x09);
        unsigned shift=16+output*2;
        if ((gpt->reg[RZV_GPT_GTBER_OFFSET/4] >> shift) & 3)
          gpt->reg[(RZV_GPT_GTCCRA_OFFSET+output*4)/4]=
            gpt->reg[(output ? RZV_GPT_GTCCRE_OFFSET : RZV_GPT_GTCCRC_OFFSET)/4];
      }
      if (bypass_requests ||
          (gpt->reg[RZV_GPT_GTINTAD_OFFSET/4] & GPT_GTINTAD_ENABLE_OVF))
        dma_event((ch < 8 ? 257 : 321)+(int)(ch%8));
    }
    for (unsigned output=0; output<2; output++) {
      unsigned compare=RZV_GPT_GTCCRA_OFFSET+output*4;
      if (gpt->reg[compare/4] != count ||
          gpt->reg[(output ? RZV_GPT_GTICBSR_OFFSET : RZV_GPT_GTICASR_OFFSET)/4])
        continue;
      unsigned duty=gpt->duty[output];
      if (output_enabled(gpt, output) && duty == 0) {
        if (output_mode(gpt, output) == 0x07)
          set_level(ch, output, !gpt->level[output]);
        else if (output_mode(gpt, output) == 0x09)
          set_level(ch, output, false);
      }
      if (bypass_requests || (gpt->reg[RZV_GPT_GTINTAD_OFFSET/4] & (1u<<output)))
        dma_event((ch < 8 ? 209 : 273)+(int)(ch%8)+(int)(output*8));
    }
  }
}
static void up_udelay(unsigned usec)
{
  for (uint64_t i=0; i<(uint64_t)usec*96; i++) model_tick();
}
#endif
