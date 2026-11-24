/* Host checks of the PMSAv8-32 encode/validate helpers in armv8-r/mpu.h and
 * of the production R-Car V4H CR52 region table.  The driver script
 * generates rcarv4h-mpu-table.h with the table, the memory-map constants
 * and the PRBAR/PRLAR values each region must encode to.
 */
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#define MPU_HOST_TEST 1
#include "mpu.h"
#include "rcarv4h-mpu-table.h"

#define COUNT(a) (sizeof(a) / sizeof((a)[0]))
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL %s:%d: %s\n", \
                      __FILE__, __LINE__, #c); return 1; } } while (0)

static int encode(uint32_t base, uint32_t size, uint8_t attr, uint8_t ap,
                  uint8_t sh, bool xn, uint32_t *prbar, uint32_t *prlar)
{
  const struct mpu_region_s r = { base, size, attr, ap, sh, xn };
  return mpu_region_encode(&r, prbar, prlar);
}

int main(void)
{
  uint32_t prbar;
  uint32_t prlar;
  unsigned int i;

  /* Fixed MAIR0: Device-nGnRnE, Device-nGnRE, Normal WB RWA, Normal NC */

  CHECK(MPU_MAIR0_VALUE == 0x44ff0400u);

  /* Production table: count, validation, exact encodings */

  CHECK(COUNT(g_rcar_mpu_table) == COUNT(g_expect_prbar));
  CHECK(mpu_table_validate(g_rcar_mpu_table, COUNT(g_rcar_mpu_table),
                           16) == 0);
  for (i = 0; i < COUNT(g_rcar_mpu_table); i++)
    {
      CHECK(mpu_region_encode(&g_rcar_mpu_table[i], &prbar, &prlar) == 0);
      if (prbar != g_expect_prbar[i] || prlar != g_expect_prlar[i])
        {
          fprintf(stderr, "FAIL region %u: PRBAR 0x%08" PRIx32
                  " PRLAR 0x%08" PRIx32 ", expected 0x%08" PRIx32
                  " 0x%08" PRIx32 "\n", i, prbar, prlar,
                  g_expect_prbar[i], g_expect_prlar[i]);
          return 1;
        }
    }

  /* The table must not reach another image's window */

  CHECK(mpu_region_last(&g_rcar_mpu_table[0]) == EXPECT_WINDOW_LAST);

  /* Field placement */

  CHECK(encode(0x40000000, 0x40, MPU_ATTR_NORMAL_NC, MPU_AP_RO,
               MPU_SH_INNER, true, &prbar, &prlar) == 0);
  CHECK(prbar == (0x40000000u | (3u << 3) | (3u << 1) | 1u));
  CHECK(prlar == (0x40000000u | (3u << 1) | 1u));

  /* The last granule of the address space is valid, one more wraps */

  CHECK(encode(0xffffffc0u, 0x40, MPU_ATTR_DEVICE_NGNRNE, MPU_AP_EL1_RW,
               MPU_SH_NONE, true, &prbar, &prlar) == 0);
  CHECK(prlar == (0xffffffc0u | 1u));
  CHECK(encode(0xffffffc0u, 0x80, 0, 0, 0, true, &prbar, &prlar)
        == -EINVAL);

  /* Refusals: alignment, zero size, bad attribute/AP/SH */

  CHECK(encode(0x40100020, 0x40, 0, 0, 0, false, &prbar, &prlar)
        == -EINVAL);
  CHECK(encode(0x40100000, 0x30, 0, 0, 0, false, &prbar, &prlar)
        == -EINVAL);
  CHECK(encode(0x40100000, 0, 0, 0, 0, false, &prbar, &prlar) == -EINVAL);
  CHECK(encode(0x40100000, 0x40, MPU_ATTR_COUNT, 0, 0, false, &prbar,
               &prlar) == -EINVAL);
  CHECK(encode(0x40100000, 0x40, 0, 4, 0, false, &prbar, &prlar)
        == -EINVAL);
  CHECK(encode(0x40100000, 0x40, 0, 0, 1, false, &prbar, &prlar)
        == -EINVAL);

  /* Overlap: one shared granule refuses, adjacency is fine */

  {
    const struct mpu_region_s overlap[] =
    {
      { 0x40100000, 0x300000, MPU_ATTR_NORMAL_WB, 0, 0, false },
      { 0x403fffc0, 0x40, MPU_ATTR_DEVICE_NGNRE, 0, 0, true },
    };

    const struct mpu_region_s adjacent[] =
    {
      { 0x40100000, 0x300000, MPU_ATTR_NORMAL_WB, 0, 0, false },
      { 0x40400000, 0x40, MPU_ATTR_DEVICE_NGNRE, 0, 0, true },
    };

    CHECK(mpu_table_validate(overlap, 2, 16) == -EEXIST);
    CHECK(mpu_table_validate(adjacent, 2, 16) == 0);
    CHECK(mpu_table_validate(adjacent, 2, 1) == -E2BIG);
  }

  printf("PASS %s\n", IMAGE_NAME);
  return 0;
}
