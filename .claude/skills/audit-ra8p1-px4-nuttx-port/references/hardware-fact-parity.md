# Hardware-fact parity

Load when a finding depends on a register definition, IRQ/event/vector ID,
channel or instance count, or which units support a feature. The collector's
`hardware-fact parity:` sections print the first three facts for a topic.

## Source order per fact

| Fact | Primary source | Cross-check | NuttX side |
|---|---|---|---|
| Base address, NS alias | `R7KA8P1KF_core0.h` (CM85) / `R7KA8P1KF_core1.h` (CM33) `R_<IP>n_BASE` | FSP `r_<module>` use | `hardware/ra8p1/ra_<ip>.h` `R_<IP>_BASE` |
| Register layout | `R_<IP>0_Type` struct (offset, width, `__IM/__OM/__IOM`, reserved arrays, bitfield `_Pos/_Msk`) | FSP driver access order | `R_<IP>_<REG>_OFFSET`, bit macros |
| Instance count | count of `R_<IP>n_BASE`; struct-type sharing (`R_GPT1` is `R_GPT0_Type`) | sample `configuration.xml` channels | channel tables, `RA_ELC_<IP>n_*` instance set |
| Event number | FSP `bsp_elc.h` `ELC_EVENT_*` (ELSR indices: `ELC_PERIPHERAL_*`) | sample `vector_data.c` `EVENT_<IP>n_*` names | `ra8p1_irq.h` `RA_ELC_<IP>n_*` |
| Vector slot | sample `ra_gen/vector_data.{c,h}` (`[slot] = BSP_PRV_VECT_ENUM(EVENT_..., GROUPk)`) | `VECTOR_NUMBER_*` in `vector_data.h` | `RA_IRQ_IELSRn = RA_IRQ_FIRST + n` (`irq.h:63` sets `RA_IRQ_FIRST` 16) |
| Per-unit features | FSP `bsp_feature.h` `BSP_FEATURE_<IP>_*` | FSP driver `*_VALID_CHANNEL_MASK` / feature checks | Kconfig channel options, driver guards |
| Clock / MSTP / reset | device header `R_MSTP` / `R_SYSTEM` members | FSP `R_BSP_MODULE_START` use, `bsp_clock_cfg.h` | `ra_mstp.h`, `hardware/ra8p1/ra_clock.c` |

## Rules

- Count instances from the device header; never from a name pattern or a
  sibling family. A NuttX channel option, event macro or table entry for an
  instance the header does not define is a finding candidate.
- Prove stride from every base, not the first two. A `*_CH_BASE(ch)` macro is
  valid only over the index domain where the stride holds.
- Event numbers are per group: the same `RA_ELC_*` name has different values
  in `ra8p1_irq.h` and `ra8e1_irq.h`. Shared `ra_*.c` code must take them from
  the header selected by `RA8P1_GROUP`.
- A vector slot is a per-image choice. Compare NuttX attach/IELSR writes with
  the slot the FSP sample uses only as behavior evidence; collisions across
  CM85 and CM33 images are the real check.
- Feature support (32-bit vs 16-bit counter, complementary PWM, FIFO depth,
  DMA/DTC trigger) varies by unit. Cite the `bsp_feature.h` mask; when the
  table does not encode the fact, cite the manual section or mark it
  `validation gap`, Medium confidence at most.
- `ELC_PERIPHERAL_*` in `bsp_elc.h` is the ELSR index map. It is sparse; a
  NuttX enum that numbers ELSR slots consecutively is a defect.
- Take facts from the audited core's header. Peripheral bases match in both
  headers (the collector prints any exception, currently `R_CACHE_BASE`, core1
  only); core-private facts (revision, cache, PMU, SAU, FPU/DSP) differ and
  never transfer between cores. Bitfield `_Pos/_Msk` macros are richer in
  core1; using them to prove a CM85 field is valid because layouts match.

## Worked examples from the current tree

- GPT: 14 instances, `R_GPT0_BASE`..`R_GPT13_BASE` at `0x40322000 + n*0x100`
  (`R7KA8P1KF_core0.h:64728-64741`), all `R_GPT0_Type` (`:64898-64911`).
  `ra8p1_irq.h` defines 14 `RA_ELC_GPT<n>` instances; RA8E1 defines 10.
- Event numbers differ by group: `RA_ELC_GPT0_COUNTER_OVERFLOW` is `0x187` in
  `ra8p1_irq.h:303` and `0x0A7` in `ra8e1_irq.h:236`.
- SPI: `R_SPI0_BASE` `0x4035C000`, `R_SPI1_BASE` `0x4035C100`, but
  `R_SPI2_BASE` `0x40072200` (`R7KA8P1KF_core0.h:64789-64791`).
  `hardware/ra8p1/ra_spi_b.h:42-43` uses a fixed `0x100` stride, so
  `R_SPI_B_CH_BASE(2)` resolves the wrong address. Candidate finding: confirm
  whether any config can select channel 2.
- SCI: both headers define SCI0..SCI9 (`R_SCI9_BASE` at core0 `:64786`,
  core1 `:64988`). The `RA_ELC_SCI10/11_*` events in `ra8p1_irq.h` are out of
  scope by user decision; do not report them.
- CM33 cache: core1 `__ICACHE_PRESENT 0` / `__DCACHE_PRESENT 0` while
  `RA8_CM33_FAMILY` selects `ARMV8M_HAVE_ICACHE/DCACHE`
  (`arch/arm/src/ra8/Kconfig:685-686`). Candidate finding: confirm which
  cache-maintenance code those options enable on CM33.
- ADC_B: one unit, `R_ADC_B0_BASE` (`:64802`) aliased as `R_ADC_B`; NuttX
  events use `RA_ELC_ADC_*` without an instance number.

## Record per fact

Record the device-header line, FSP or sample line, NuttX line, and the verdict:
match, mismatch (finding), NuttX-only (no reference), or unverified (manual
needed).
