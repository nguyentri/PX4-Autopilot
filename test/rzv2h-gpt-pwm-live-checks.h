/* Seed coherent active/pending tuples, then execute the real update. */

static int run_live_update(char **argv)
{
  selected_output = strtoul(argv[2], NULL, 0);
  overflow_after_access = strtol(argv[3], NULL, 0);
  uint32_t old_period = strtoul(argv[4], NULL, 0);
  uint32_t new_period = strtoul(argv[5], NULL, 0);
  unsigned int options = strtoul(argv[6], NULL, 0);
  pending_update = (options & 2u) != 0;

  expected_tuple[0][0] = old_period - 1u;
  expected_tuple[0][1] = old_period * 3u / 4u - 1u;
  expected_tuple[0][2] = old_period / 4u ? old_period / 4u - 1u : 0u;
  uint32_t pending_period = old_period + 137u;
  expected_tuple[1][0] = pending_period - 1u;
  expected_tuple[1][1] = pending_period / 2u - 1u;
  expected_tuple[1][2] = pending_period / 3u - 1u;
  uint32_t new_a = new_period * 3u / 4u;
  uint32_t new_b = new_period / 4u ? new_period / 4u : 1u;
  expected_tuple[2][0] = new_period - 1u;
  expected_tuple[2][1] = new_a - 1u;
  expected_tuple[2][2] = new_b - 1u;

  registers[RZV_GPT_GTPR_OFFSET / 4] = expected_tuple[0][0];
  registers[RZV_GPT_GTCCRA_OFFSET / 4] = expected_tuple[0][1];
  registers[RZV_GPT_GTCCRB_OFFSET / 4] = expected_tuple[0][2];
  unsigned int buffer_version = pending_update ? 1 : 0;
  registers[RZV_GPT_GTPBR_OFFSET / 4] = expected_tuple[buffer_version][0];
  registers[RZV_GPT_GTCCRC_OFFSET / 4] = expected_tuple[buffer_version][1];
  registers[RZV_GPT_GTCCRE_OFFSET / 4] = expected_tuple[buffer_version][2];

  /* CCRSWT force-transfer self-clears after stopped initialization. Preserve
   * unrelated ADC buffer configuration and BD2 through the live transaction. */
  uint32_t gtber = 0x150000u | (1u << 2) | (1u << 24);
  registers[RZV_GPT_GTBER_OFFSET / 4] = gtber;
  struct rzv_gpt_lowerhalf_s priv =
  {
    .period = old_period,
    .running = true,
    .initialized = true,
    .output = selected_output,
    .divsel = 0
  };

  live_model = true;
  int ret = rzv_gpt_update(&priv, new_period, options & 1u, new_a, new_b);
  model_overflow();
  printf("%d %u %u %u %u %u %u %u\n", ret, writes, mmio_accesses,
         mixed_transfers, forbidden_writes, active_matches(2),
         registers[RZV_GPT_GTBER_OFFSET / 4] == gtber, priv.period);
  return 0;
}
