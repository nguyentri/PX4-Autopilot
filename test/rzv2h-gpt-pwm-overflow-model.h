/* RZ/V2H R01UH1032EJ0140: BD0 gates compare and BD1 gates period buffers
 * (§5.7.2.2.17 p1351, §5.7.8.2 p1481). This saw-wave, single-buffer model
 * checks numeric period/compare coherence only. GTUDDTYC endpoint mode has
 * independent latch timing; no physical waveform or mode atomicity is claimed.
 */

static bool live_model;
static int overflow_after_access;
static unsigned int mmio_accesses;
static unsigned int mixed_transfers;
static unsigned int forbidden_writes;
static enum rzv_gpt_output_e selected_output;
static bool pending_update;
static uint32_t expected_tuple[3][3];

static bool active_matches(unsigned int version)
{
  bool matches = registers[RZV_GPT_GTPR_OFFSET / 4] ==
                 expected_tuple[version][0];

#ifdef CONFIG_PWM_MULTICHAN
  matches &= registers[RZV_GPT_GTCCRA_OFFSET / 4] ==
             expected_tuple[version][1];
  matches &= registers[RZV_GPT_GTCCRB_OFFSET / 4] ==
             expected_tuple[version][2];
#else
  unsigned int index = selected_output == RZV_GPT_OUTPUT_A ? 1 : 2;
  unsigned int offset = index == 1 ? RZV_GPT_GTCCRA_OFFSET :
                                   RZV_GPT_GTCCRB_OFFSET;
  matches &= registers[offset / 4] == expected_tuple[version][index];
#endif
  return matches;
}

static void model_overflow(void)
{
  uint32_t gtber = registers[RZV_GPT_GTBER_OFFSET / 4];

  if (!(gtber & (1u << 1)) && ((gtber >> 20) & 3u) == 1u)
    {
      registers[RZV_GPT_GTPR_OFFSET / 4] =
        registers[RZV_GPT_GTPBR_OFFSET / 4];
    }

  if (!(gtber & (1u << 0)))
    {
      if (((gtber >> 16) & 3u) == 1u)
        {
          registers[RZV_GPT_GTCCRA_OFFSET / 4] =
            registers[RZV_GPT_GTCCRC_OFFSET / 4];
        }

      if (((gtber >> 18) & 3u) == 1u)
        {
          registers[RZV_GPT_GTCCRB_OFFSET / 4] =
            registers[RZV_GPT_GTCCRE_OFFSET / 4];
        }
    }

  if (!active_matches(0) && !active_matches(2) &&
      !(pending_update && active_matches(1)))
    {
      mixed_transfers++;
    }
}

static void model_after_access(void)
{
  mmio_accesses++;
  if (overflow_after_access == -1 ||
      (int)mmio_accesses == overflow_after_access)
    {
      model_overflow();
    }
}

static void model_after_write(unsigned int offset, uint32_t value)
{
  if (offset == RZV_GPT_GTSTP_OFFSET || offset == RZV_GPT_GTCLR_OFFSET ||
      offset == RZV_GPT_GTSTR_OFFSET || offset == RZV_GPT_GTPR_OFFSET ||
      offset == RZV_GPT_GTCCRA_OFFSET || offset == RZV_GPT_GTCCRB_OFFSET ||
      offset == RZV_GPT_GTCNT_OFFSET ||
      (offset == RZV_GPT_GTBER_OFFSET && (value & GPT_GTBER_CCRSWT)))
    {
      forbidden_writes++;
    }

  model_after_access();
}
