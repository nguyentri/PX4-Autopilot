/* Execute helpers extracted verbatim from rzv_gpt.c by the Python test. */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "hardware/rzv_gpt.h"

#define UNUSED(value) ((void)(value))
#define b16ONE 0x10000u

typedef uint32_t ub16_t;

enum rzv_gpt_output_e
{
  RZV_GPT_OUTPUT_A,
  RZV_GPT_OUTPUT_B
};

#include "gpt-driver-functions.inc"

int main(int argc, char **argv)
{
  if (argc != 5)
    {
      return 2;
    }

  uint32_t period = strtoul(argv[1], NULL, 0);
  ub16_t duty = strtoul(argv[2], NULL, 0);
  enum rzv_gpt_output_e output = strtoul(argv[3], NULL, 0);
  uint32_t counts = gpt_duty_to_counts(period, duty);
  uint32_t other_counts = gpt_duty_to_counts(period, strtoul(argv[4], NULL, 0));
  uint32_t mode = gpt_compute_gtuddtyc(output,
                                     output == RZV_GPT_OUTPUT_A ? counts : other_counts,
                                     output == RZV_GPT_OUTPUT_B ? counts : other_counts,
                                     period);
  uint32_t mode_a = (mode & GPT_GTUDDTYC_OADTY_MASK) >>
                   GPT_GTUDDTYC_OADTY_SHIFT;
  uint32_t mode_b = (mode & GPT_GTUDDTYC_OBDTY_MASK) >>
                   GPT_GTUDDTYC_OBDTY_SHIFT;

  printf("%u %u %u\n", counts,
         output == RZV_GPT_OUTPUT_A ? mode_a : mode_b,
         output == RZV_GPT_OUTPUT_A ? mode_b : mode_a);
  return 0;
}
