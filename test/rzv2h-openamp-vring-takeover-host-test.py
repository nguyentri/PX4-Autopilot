#!/usr/bin/env python3
"""Host test of the CR8-0 OpenAMP takeover watch and ring adoption.

Compiles the real arch/arm/src/rzv/rzv_openamp.c against stub NuttX headers,
maps the shared window at its target addresses (0x42F00000, 0x43000000) and
drives it with a simulated CA55 master:

- one master session, including a 16-bit ring-index wrap, never looks like
  a takeover;
- a successor that posts fresh buffers while DRIVER_OK stays set is seen
  after its first post, and adoption renumbers both rings so a fresh CR8-0
  device (ring cursors at 0) sends into the successor's buffers in order;
- a successor that restarts avail.idx from its own cursor is seen and
  adopted the same way;
- vrings_reset() zeroes both table-0 rings.

Skips when no host C compiler is available or the fixed mapping fails.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RZV = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"

STUBS = {
    "nuttx/config.h": "#define CONFIG_RZV_OPENAMP 1\n",
    "nuttx/compiler.h": "#define FAR\n",
    "nuttx/arch.h": "",
    "nuttx/cache.h": (
        "#include <stdint.h>\n"
        "static inline void up_clean_dcache(uintptr_t a, uintptr_t b)\n"
        "{ (void)a; (void)b; }\n"),
    "arm_internal.h": "",
    "barriers.h": (
        "#define ARM_DMB() __sync_synchronize()\n"
        "#define ARM_DSB() __sync_synchronize()\n"),
}

DRIVER = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include "rzv_openamp.h"

#define N       1024u
#define V0      RZV_OPENAMP_VRING0_BASE
#define V1      RZV_OPENAMP_VRING1_BASE
#define AVAIL   (N * 16u)
#define USED    ((AVAIL + 4u + N * 2u + 2u + 0xffu) & ~0xffu)
#define U16(a)  (*(volatile uint16_t *)(uintptr_t)(a))
#define U32(a)  (*(volatile uint32_t *)(uintptr_t)(a))
#define BUF(i)  (RZV_OPENAMP_SHM_BASE + (uint32_t)(i) * 512u)

#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d %s\n", __FILE__, \
                      __LINE__, #c); return 1; } } while (0)

static uint16_t g_cr8_avail;   /* CR8-0 vq_available_idx */
static uint16_t g_master_cons; /* master vq_used_cons_idx */
static uint16_t g_master_shadow;

/* Master posts desc to vring 0.  memory_idx: OpenAMP 2022.04 style
 * (increment the shared word); otherwise an own shadow cursor.
 */

static void master_post(uint16_t desc, int memory_idx)
{
  uint16_t idx = memory_idx ? U16(V0 + AVAIL + 2u) : g_master_shadow;

  U32(V0 + desc * 16u) = BUF(desc);
  U32(V0 + desc * 16u + 4u) = 0;
  U32(V0 + desc * 16u + 8u) = 512u;
  U16(V0 + AVAIL + 4u + (idx & (N - 1u)) * 2u) = desc;
  U16(V0 + AVAIL + 2u) = (uint16_t)(idx + 1u);
  g_master_shadow = (uint16_t)(idx + 1u);
}

static void master_init(int memory_idx)
{
  uint16_t i;

  g_master_cons = 0;
  g_master_shadow = 0;
  for (i = 0; i < N; i++)
    {
      memset((void *)(uintptr_t)BUF(i), 0, 512);
      master_post(i, memory_idx);
    }
}

/* CR8-0 sends one message from vring 0 (device role, OpenAMP 2022.04) */

static int cr8_send(uint16_t *desc_out)
{
  uint16_t desc;
  uint16_t used;

  if (g_cr8_avail == U16(V0 + AVAIL + 2u))
    {
      return -1;
    }

  desc = U16(V0 + AVAIL + 4u + (g_cr8_avail++ & (N - 1u)) * 2u);
  U32(BUF(desc) + 0u) = 1024u;      /* src */
  U32(BUF(desc) + 4u) = 1025u;      /* dst */
  U16(BUF(desc) + 12u) = 10u;       /* len */
  used = U16(V0 + USED + 2u);
  U32(V0 + USED + 4u + (used & (N - 1u)) * 8u) = desc;
  U16(V0 + USED + 2u) = (uint16_t)(used + 1u);
  *desc_out = desc;
  return 0;
}

/* Master consumes one used buffer and re-posts it without zeroing */

static int master_recycle(int memory_idx)
{
  uint16_t desc;

  if (g_master_cons == U16(V0 + USED + 2u))
    {
      return -1;
    }

  desc = U32(V0 + USED + 4u + (g_master_cons++ & (N - 1u)) * 8u);
  master_post(desc, memory_idx);
  return 0;
}

int main(void)
{
  uint16_t desc;
  uint32_t i;
  void *p;

  p = mmap((void *)(uintptr_t)RZV_OPENAMP_RESOURCE_TABLE_BASE, 0x00900000,
           PROT_READ | PROT_WRITE,
           MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
  if (p != (void *)(uintptr_t)RZV_OPENAMP_RESOURCE_TABLE_BASE)
    {
      printf("SKIP mmap\n");
      return 77;
    }

  /* Power-on garbage, then the boot-time reset */

  memset((void *)(uintptr_t)V0, 0xa5, 0x60000);
  rzv_openamp_vrings_reset();
  CHECK(U16(V0 + AVAIL + 2u) == 0 && U16(V0 + USED + 2u) == 0);
  CHECK(U16(V1 + AVAIL + 2u) == 0 && U16(V1 + USED + 2u) == 0);

  /* Master A: one long session across the 16-bit index wrap.  Most of its
   * initial zeroed buffers stay unsent for a while.
   */

  master_init(1);
  g_cr8_avail = 0;
  rzv_openamp_link_arm();
  CHECK(!rzv_openamp_master_replaced());
  for (i = 0; i < 70000u; i++)
    {
      CHECK(cr8_send(&desc) == 0);
      CHECK(!rzv_openamp_master_replaced());
      if (i >= 500u)
        {
          CHECK(master_recycle(1) == 0);
        }

      CHECK(!rzv_openamp_master_replaced());
    }

  while (master_recycle(1) == 0)
    {
      CHECK(!rzv_openamp_master_replaced());
    }

  /* A dies holding 600 sent buffers, so avail - used stays in range and
   * only the zero-header scan can see B's first post.
   */

  for (i = 0; i < 600u; i++)
    {
      CHECK(cr8_send(&desc) == 0);
    }

  CHECK(!rzv_openamp_master_replaced());

  /* A killed: DRIVER_OK stays, rings keep A's indices.  B starts with the
   * shared-word (OpenAMP 2022.04) posting style.
   */

  memset((void *)(uintptr_t)BUF(0), 0, 512);
  master_post(0, 1);
  CHECK(rzv_openamp_master_replaced());
  for (i = 1; i < N; i++)
    {
      memset((void *)(uintptr_t)BUF(i), 0, 512);
      master_post((uint16_t)i, 1);
    }

  g_master_cons = 0;
  CHECK(rzv_openamp_link_adopt() == N);
  CHECK(U16(V0 + AVAIL + 2u) == N && U16(V0 + USED + 2u) == 0);
  CHECK(U16(V1 + AVAIL + 2u) == 0 && U16(V1 + USED + 2u) == 0);
  CHECK(!rzv_openamp_master_replaced());

  /* Fresh CR8-0 device: cursor 0 must see B's buffers in post order and B
   * must find each one at its own used cursor.
   */

  g_cr8_avail = 0;
  for (i = 0; i < 3000u; i++)
    {
      CHECK(cr8_send(&desc) == 0);
      CHECK(i >= N || desc == i);
      CHECK(master_recycle(1) == 0);
      CHECK(!rzv_openamp_master_replaced());
    }

  /* B killed mid-session; C posts from its own cursor 0 */

  master_init(0);
  CHECK(rzv_openamp_master_replaced());
  CHECK(rzv_openamp_link_adopt() == N);
  CHECK(U16(V0 + AVAIL + 2u) == N && U16(V0 + USED + 2u) == 0);
  g_cr8_avail = 0;
  for (i = 0; i < N; i++)
    {
      CHECK(cr8_send(&desc) == 0 && desc == i);
      CHECK(master_recycle(0) == 0);
      CHECK(!rzv_openamp_master_replaced());
    }

  /* No fresh buffers: adoption refuses and leaves the rings alone */

  i = U16(V0 + AVAIL + 2u);
  CHECK(rzv_openamp_link_adopt() == 0);
  CHECK(U16(V0 + AVAIL + 2u) == i);

  rzv_openamp_vrings_reset();
  CHECK(U16(V0 + AVAIL + 2u) == 0 && U16(V1 + USED + 2u) == 0);
  CHECK(!rzv_openamp_master_replaced());

  printf("PASS\n");
  return 0;
}
"""


class VringTakeoverHostTest(unittest.TestCase):
    def test_takeover_watch_and_adoption(self) -> None:
        cc = shutil.which("cc") or shutil.which("gcc")
        if cc is None:
            self.skipTest("no host C compiler")

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            for name, text in STUBS.items():
                path = work / "stub" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            (work / "driver.c").write_text(DRIVER, encoding="utf-8")
            exe = work / "vring-test"
            build = subprocess.run(
                [cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror",
                 "-Wno-unused-function", "-I", str(work / "stub"),
                 "-I", str(RZV), str(RZV / "rzv_openamp.c"),
                 str(work / "driver.c"), "-o", str(exe)],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0,
                             build.stdout + build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True,
                                 timeout=60)
            if run.returncode == 77:
                self.skipTest("cannot map the shared window at its address")
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("PASS", run.stdout)


if __name__ == "__main__":
    unittest.main()
