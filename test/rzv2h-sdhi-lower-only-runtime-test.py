#!/usr/bin/env python3
"""Execute idle/repeated SDHI cancellation and safe snapshot contracts."""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'sdhi_model', ROOT / 'test/rzv2h-sdhi-command-data-runtime-test.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class SdhiRuntime(unittest.TestCase):
    def test_idle_cancel_does_not_post_or_attach(self):
        M.run(r'''
  struct rzv2h_sdhi_sample_state_s state;
  assert(rzv2h_sdhi_sample_state(NULL) == -EINVAL);
  assert(rzv2h_sdhi_sample_state(&state) == -EAGAIN && operations == 0);
  setup();
  assert(rzv_sdhi_cancel(&p->dev) == OK);
  assert(rzv_sdhi_cancel(&p->dev) == OK && posts == 0);
  assert(rzv2h_sdhi_sample_state(&state) == OK);
  assert(!state.irq_attached && !state.watchdog_active && !state.buffer_present);
  assert(state.interrupts_masked && !state.semaphore_count && !state.waitevents);
  for (unsigned bit = 0; bit < 32; bit++)
    {
      uint32_t flag = 1u << bit;
      if ((RZV_SDHI_SD_INFO1_MASK_INIT & flag) != 0)
        {
          REG(RZV_SDHI_SD_INFO1_MASK_OFFSET) &= ~flag;
          assert(rzv2h_sdhi_sample_state(&state) == OK && !state.interrupts_masked);
          REG(RZV_SDHI_SD_INFO1_MASK_OFFSET) |= flag;
        }
      if ((RZV_SDHI_SD_INFO2_MASK_INIT & flag) != 0)
        {
          REG(RZV_SDHI_SD_INFO2_MASK_OFFSET) &= ~flag;
          assert(rzv2h_sdhi_sample_state(&state) == OK && !state.interrupts_masked);
          REG(RZV_SDHI_SD_INFO2_MASK_OFFSET) |= flag;
        }
    }

  /* A pending data wait is released once with an error. */
  p->waitevents = SDIOWAIT_TRANSFERDONE;
  p->waitwdog.active = true;
  p->buffer = buffer;
  p->remaining = 4;
  assert(rzv_sdhi_cancel(&p->dev) == OK && posts == 1);
  assert(!p->buffer && !p->remaining && !p->waitevents && !p->waitwdog.active);
  assert(p->wkupevent == SDIOWAIT_ERROR);
  assert(rzv_sdhi_cancel(&p->dev) == OK && posts == 1);

  /* A pending command wait is released too and reports an I/O error. */
  assert(rzv_sdhi_sendcmd(&p->dev, MMCSD_CMD0, 0) == OK);
  assert(rzv_sdhi_cancel(&p->dev) == OK && posts == 2);
  assert(p->cmdsem.count == 1 && p->cmdevent == SDIOWAIT_ERROR);
  assert(rzv_sdhi_waitresponse(&p->dev, MMCSD_CMD0) == -EIO);
  assert(rzv_sdhi_cancel(&p->dev) == OK && posts == 2);
''')


if __name__ == '__main__':
    unittest.main()
