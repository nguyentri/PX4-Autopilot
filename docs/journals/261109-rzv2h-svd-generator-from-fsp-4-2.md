# 2026-11-09 — rzv2h.svd generated from the FSP 4.2.0 CMSIS headers

## What happened
`generate-rzv2h-svd.py` (repo root) now writes `rzv2h.svd`. It reads the CR8
`iodefine.h`, the per-IP `iodefines/` headers (including `cr8/`) and
`R9A09G057H.h` from `refs/rz-fsp-4.2.0`, and uses the `iobitmasks/` headers
to cross-check every field. `--check` reports when the committed SVD is out of
date. It produces 33 peripherals plus 186 derived instances, and 2239
registers. Compared with the old hand-made SVD:
- R_GBETH0/1 are new.
- Every other register keeps its offset, size and access.
- The SPIBSC/SSI `L/H/L_1` registers are now `*_hword`/`*_byte` clusters, and
  PTISR_CLR/WDISR_CLR are now CLR fields. No consumer used the old names.

Running the generator on the FSP 3.0.0 EVK headers reproduces the old SVD
exactly, apart from those renames.

Later on the same day, the SVD gained a `<cpu>` element and 478 interrupts
from the CR8 `IRQn_Type` enum (`bsp_irq_id.h`). The enum values agree with
NuttX `rzv2h_irq.h` (the NuttX number is the enum value + 32), and the output
validates against the CMSIS-SVD 1.3 schema.

## Lessons
- The CMSIS-SVD 1.3 `cpuNameType` has no Cortex-R names, so the CPU name is
  `other`. The FSP headers have no CR8 revision either; the read-only
  `monitor cp15 0, 0, 0, 0` on CR8-0 returned MIDR 0x410FC183 (r0p3).
- FSP 4.2.0 `i3c_b_iodefine.h` puts DATBAS1–7 on an 8-byte stride with
  EXDATBAS at 0x2A0. The hardware manual, the FSP 3.0.0 headers and the
  `rzv_i3c.h` driver use 0x224+4n and 0x310. The generator applies a guarded
  erratum: it does nothing if the header is already fixed, and stops with an
  error if the header offset is anything else.
- `svd_register_tool` flattens `X[%s]` into `X0`, which is not valid C. To
  check against C, the test walks the SVD itself and compiles
  `_Static_assert(offsetof(...))` with cc and arm-none-eabi-gcc. To keep the
  test runtime bounded, it keeps one static object per peripheral, not one per
  field.
- Some instance pointers use a *_BASE macro with a different name
  (R_POEGA → R_POEG0A_BASE). The test therefore compares bases at run time
  through the pointer, not by building the macro name.
- The remaining FSP quirks are reported as warnings: the CANFD size comment
  is 80 KiB but the layout is 112 KiB, CFDTMIEC[12] has only a 4-element _b
  view, and the iobitmask for SCI RDR_BY_RDAT is wrong.
