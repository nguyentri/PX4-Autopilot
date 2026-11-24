# Audit EVT: RA8P1 ICU / ELC / DTC / DMAC (CM85)

## 1. Scope, core, baseline

- Phase 3 (`phase-03-interrupts-events-dma.md`), static audit only, no builds/hardware.
- Core: CM85 (EVK-RA8P1). CM33 noted only for shared-peripheral ownership.
- Baseline: PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- Prefixes: A = `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8`, E = `.../boards/arm/ra8/evk-ra8p1`, F = `.../boards/arm/ra8/fpb-ra8e1`.
- Hardware authority: `refs/ra8p1/R7KA8P1KF_core0.h` (device header), FSP `e2studio/ra/fsp/src/bsp/mcu/ra8p1/{bsp_elc.h,bsp_feature.h}`, FSP `r_dmac`, `r_dtc`, `r_elc`.
- Files: `A/ra_icu.c`, `A/ra_elc.{c,h}`, `A/ra_dtc.c`, `A/ra_dmac.c`, `A/hardware/ra8p1/{ra_icu,ra_elc,ra_dma,ra_dmac,ra_dtc}.h`, `arch/arm/include/ra8/ra8p1_irq.h`, `E/src/ra8p1_elc.c`.
- ELF layer: only `adc-b` / `adc-b-hwtrigger` built (E2). All other configs: "not built (user declined builds)".

## 2. Per-core trace matrix (CM85)

| Layer | Anchor | Status | FSP sample |
|---|---|---|---|
| IRQ numbering | `ra8p1_irq.h` (498/500 events), `RA_IRQ_IELSR_SIZE 96` | E1 match; CEU_CEUI missing | `bsp_elc.h` (33 identical copies), all 97 sample `vector_data.c` names present |
| ICU attach/detach | `A/ra_icu.c:167-268` | E2 linked in both adc-b images | `ek_ra8p1/*/vector_data.c` |
| ICU DMAC link | `A/ra_icu.c:591-634` (R_ICU DELSR) | E1, matches FSP (`BSP_FEATURE_DMAC_HAS_DELSR 0`) | `r_dmac.c:518-530` |
| ELC | `A/ra_elc.c`, `A/ra_elc.h:50-81` | E2 (hwtrigger links `ra_elc_initialize/enable`); peripheral map wrong | `bsp_elc.h:540-580`, `ek_ra8p1/elc` |
| DTC | `A/ra_dtc.c`, `E/scripts/evk-ra8p1.ld:261-265` | E1 only | `ek_ra8p1/spi`, `sci_spi` r_dtc |
| DMAC | `A/ra_dmac.c`, `hardware/ra8p1/ra_dma{,c}.h` | E1 only; fake unit 1 | `ek_ra8p1/dmac` r_dmac |
| Board ELC | `E/src/ra8p1_elc.c`, `ra8p1_bringup.c:301-307` | E2 (hwtrigger) | n/a |

## 3. Findings

### EVT-01 High (confidence high): ELC peripheral (ELSR) index map compacted, wrong for every slot >= 8

- Core: CM85 (and CM33 if it uses the API).
- Failure: `ra_adc_b.c:737/752` calls `ra_elc_link_set(RA_ELC_PERIPHERAL_ADC0, evt)`. `RA_ELC_PERIPHERAL_ADC0 = 14` writes ELSR14, which is IOPORT1 per FSP. The ADC0 trigger is never routed, and IOPORT1 event input gets an unrelated event. The same applies to DAC0/1 (8/9 vs 12/13), IOPORT1-4 (10-13 vs 14-17), ADC0..ADC2_C (14-22 vs 19-27), I3C/GPTP0/GPTP1 (23-25 vs 30-32).
- Impl: `A/ra_elc.h:50-81`, `A/hardware/ra8p1/ra_elc.h:384,397-415` (`ELC_MAX_PERIPHERALS 27`).
- Ref: `refs/ra8p1/ek_ra8p1/adc/adc_ek_ra8p1_ep/e2studio/ra/fsp/src/bsp/mcu/ra8p1/bsp_elc.h:540-580` (`ELC_PERIPHERAL_NUM 33`, ADC0 = 19, mask `0x1CFFBF0FF`); device header `R7KA8P1KF_core0.h:6809` (`ELSR[53]` at 0x20, index = peripheral number).
- Also: `ra_elc_initialize`/`uninitialize` clear only ELSR0..26, so ELSR27..32 (ADC2_C, I3C, GPTP) are never cleared, and the validator rejects valid slots 27..32.
- Affected configs: adc-b-hwtrigger (linked code path), poeg, PX4 `evk-ra8p1` nsh and `evk-ra8p1-io-cm33` nsh (`RA_ELC=y`). RA8E1: `A/ra_elc.h` is shared and un-gated. Its enum also disagrees with the RA8E1 chip header (`A/hardware/ra8e1/ra_elc.h:210-224`, ADC0 = 8). No RA8E1 consumer of `ra_elc_link_set` was found, so the RA8E1 impact is latent. The RA8E1 FSP map is absent from `refs/`, so RA8E1 correctness is unverified.
- Remediation: make `enum ra_elc_peripheral_e` take its values from the per-chip `ELC_PERIPHERAL_*` macros, and fix the RA8P1 macros to the FSP numbers. Set `ELC_MAX_PERIPHERALS` to 33 and validate against the FSP mask.
- Class: pre-existing defect.

### EVT-02 High (confidence high): DMAC "unit 1" does not exist on RA8P1; init writes the DTC registers

- Failure: when any `RA_DMAC=y` image first calls `ra_dmac_initialize` (from sci_spi, spi, i2c, sdhi or sdram), it does two writes to the DTC:
  - `R_DMA_DMAST_UNIT(1)` lands at 0x4000AC00 (DTCCR), with value 1.
  - `R_DMA_DMCTL_UNIT(1)` lands at 0x4000AC10 (DTCCR_SEC), with value 0.
- Both writes go to the DTC, which also clears the secure RRS. The validators also accept channels 10-17, which map to 0x4000A200.. (no DMAC there). `ra_dmac_set_priority_mode(1)` writes DTCCR_SEC too.
- Impl: `A/ra_dmac.c:368-380,424-444`; `A/hardware/ra8p1/ra_dma.h:33-51` (`R_DMA1_BASE 0x4000ac00`); `A/hardware/ra8p1/ra_dmac.h:34-51,268-272` (`R_DMAC1_BASE 0x4000a200`, `DMAC_IS_VALID_CHANNEL` 10-17); `A/ra_icu.c:594-604,626` (the "shared between units" comment); `A/Kconfig:5129-5133` help text.
- Ref: `R7KA8P1KF_core0.h:64713-64724` (single R_DMA at 0x4000A800, DMAC0..7 at 0x4000A000-0x4000A1C0, R_DTC at 0x4000AC00); `bsp_feature.h:235` `BSP_FEATURE_DMAC_NUM_CHANNELS 8`.
- Affected configs: gps, nsh, sci-spi, spi-loopback, sci-i2c, ospi-b, usb-pcdc, mipi-csi, pwm, poeg (any with `RA_DMAC=y`), and PX4 evk-ra8p1 images that enable DMAC. All of these are "not built". RA8E1: the unit-1 writes are under `CONFIG_RA8P1_GROUP`. However, `A/hardware/ra8e1/ra_dma.h:38` has the same `R_DMA1_BASE`, and `DMAC_IS_VALID_CHANNEL` should be checked there. RA8E1 is not affected unless `set_priority_mode(1)` or channels 10-17 are used.
- Remediation: model one unit with 8 channels for RA8P1. Delete the unit-1 base, writes and validator range. The DELSR use of R_ICU DELSR[0..7] is then correct as-is.
- Class: pre-existing defect.

### EVT-03 Medium (confidence medium): DTC descriptor rewrite and DMAC buffers have no D-cache maintenance on CM85

- Failure: CM85 images run with `ARMV8M_DCACHE=y`.
  - `ra_dtc_reset` rewrites `ctrl->info.sar/dar/cra` in cacheable SRAM without `up_clean_dcache`, so the DTC fetches a stale descriptor.
  - No path invalidates the descriptor before `ra_dtc_get_remaining_count`.
  - `ra_dmac.c` has no cache maintenance, and `ra_sci_spi.c` has none for its DMAC/DTC buffers.
  - The result is stale TX data or stale RX data seen by the CPU.
  - Only `ra_dtc_set_vector` cleans.
- Impl: `A/ra_dtc.c:749-800` (no clean), `A/ra_dtc.c:878-881` (only clean site), `A/ra_dtc.c:818`. `A/ra_dmac.c` has no `up_*_dcache` anywhere. `A/ra_sci_spi.c` has none either. ra_spi/ra_i2c/ra_serial/ra_sdram do contain cache calls; per-path coverage was not traced.
- Ref: absent in FSP (FSP leaves cache policy to the application); CMSIS/NuttX D-cache rule.
- Affected: DTC/DMAC consumers above. RA8E1 is CM85 with D-cache too, so the same shared code applies.
- Remediation: clean the descriptor after every rewrite. Clean TX buffers and invalidate RX buffers (cache-line aligned) in the DMAC/DTC consumers, or place the buffers in non-cacheable RAM.
- Class: pre-existing / validation gap.

### EVT-04 Medium (confidence medium): Board ELC glue: duplicate strong `board_elc_initialize` and Make/CMake drift

- `E/src/ra8p1_elc.c` and `E/src/ra8p1_adc_b_hwtrigger.c:89-119` both define a strong `board_elc_initialize` when `RA_ELC` and `RA8P1_ADC_HW_TRIGGER_EXAMPLE` are set. The Make build avoids the multiple definition only because the hwtrigger object is never pulled; see ADC-01.
- CMake (`E/src/CMakeLists.txt:69-75`) adds the hwtrigger file on `RA_ELC` and never adds `ra8p1_elc.c`. A CMake poeg build would therefore have an undefined `board_elc_initialize`, which `ra8p1_bringup.c:301-307` calls.
- Make: `E/src/Makefile:105-107,164-166`.
- Affected: adc-b-hwtrigger, poeg (CMake only). RA8E1: not affected (board-local).
- Remediation: one owner for `board_elc_initialize` (`ra8p1_elc.c`), with CMake mirroring Make.
- Class: drift.

### EVT-05 Medium (confidence low): ELC is a SoC-shared block, but both cores fully reset it

- `ra_elc_initialize` clears every ELSR and sets ELCON=0. PX4 `boards/renesas/evk-ra8p1-io-cm33` nsh defconfig:143 and PX4 `evk-ra8p1` nsh defconfig:111 both set `RA_ELC=y`. When both cores run, the second core to boot wipes the first core's links.
- Impl: `A/ra_elc.c:228-262`.
- Ref: absent (no FSP dual-core ELC ownership sample).
- Affected: PX4 dual-core images. RA8E1: n/a (single core).
- Remediation: assign ELC ownership to one core, or clear only the owned slots.
- Class: validation gap.

### EVT-06 Low: ICU slot allocator

- `ra_icu_attach` has no lock and does no event or duplicate validation (`A/ra_icu.c:167-200`).
- Detach only compacts the tail, so a freed middle slot is never reused (`:211-268`). Repeated attach/detach cycles run out of the 96 slots.
- `icu_irq >= 112` (:217) equals `RA_IRQ_FIRST + RA_IRQ_IELSR_SIZE` on both chips (96 IELSR, `ra8e1_irq.h:136`, `ra8p1_irq.h:136`, device header `IELSR[96]` :9474). It is correct but should use the macro.
- RA8E1: same shared file, same impact.
- Remediation: free-slot bitmap under a spinlock/critical section, and use `RA_IRQ_FIRST + RA_IRQ_IELSR_SIZE`.

### EVT-07 Low: CEU_CEUI event 0x397 missing

- `RA_ELC_EVENT_MAX` is 0x396, so `ra_icu_enable_dmac`/attach reject CEU (`bsp_elc.h` has `ELC_EVENT_CEU_CEUI`). Only `hardware/ra8p1/ra_ceu.h` exists (no driver).
- RA8E1: n/a.

### EVT-08 validation gap: `RA_HAVE_ICU` never selected on RA8P1

- Both artifacts have `# CONFIG_RA_HAVE_ICU is not set`, so `CONFIG_RA_ICU` (`A/Kconfig:3685-3692`) cannot be enabled. PX4 `boards/renesas/evk-ra8p1/nuttx-config/nsh/defconfig:110` `CONFIG_RA_ICU=y` is therefore dead. No C code gates on it (`ra_icu.c` is always built), so there is no functional effect.
- RA8E1: check the same select.
- Remediation: select it in the RA8P1 chip entries, or drop the option and the defconfig line.

## 4. Items checked correct

- 498/500 `ra8p1_irq.h` event values equal FSP `bsp_elc.h` (scripted compare); all 97 sample `vector_data.c` event names exist.
- ICU ISR clears IR before calling the handler (`A/ra_icu.c:113-126`), same as FSP.
- DELSR via `R_ICU` +0x6280 (`hardware/ra8p1/ra_icu.h:58`) matches FSP `r_dmac.c:518-530` with `BSP_FEATURE_DMAC_HAS_DELSR 0` (`bsp_feature.h:232`) and the device header `R7KA8P1KF_core0.h:9460`.
- Base addresses: `R_ELC_BASE 0x40201000` (`hardware/ra8p1/ra_elc.h:35`) matches device header :64725; R_DMA0 0x4000A800 matches :64713; R_ICU 0x40006000 matches :64749. ELCR/ELSEGR/ELSR/ELCSARA/B offsets (`hardware/ra8p1/ra_elc.h:43-49`) match device header :6807-6876.
- DTC vector table: 1 KiB aligned, NOLOAD section `E/scripts/evk-ra8p1.ld:261-265`; RRS is disabled around vector and descriptor updates (`A/ra_dtc.c:774,799,869`).
- `ra_elc.c` mutations run inside `enter_critical_section`; `ra_dmac.c` uses `g_dmac_lock`.
- RA8E1 C3 is closed: `A/ra_adc.c:226` uses `R_ADC12_CH_BASE(1)`, and `F/Kconfig:239` has `select RA_ADC1` (under `RA8E1_ADC_BMS_EXAMPLE`).

## 5. Rejected / unsupported paths, dead code

- The suspected DELSR collision between unit 0 ch n and unit 1 ch 10+n is rejected as a separate finding: there is no unit 1, so it is folded into EVT-02.
- SCI10/SCI11 ELC events: out of scope.
- `CONFIG_RA_ICU=y` in the PX4 nsh defconfig is dead (EVT-08).
- `ra_elc_link_set` is never linked in the E2 images (hwtrigger example not pulled; see ADC-01).
- Priority-0 vs BASEPRI: `ra_icu_set_priority` (`A/ra_icu.c:323-351`) writes `prio<<4`. Callers passing 0 create an IRQ above BASEPRI masking, which `enter_critical_section` cannot block. No caller doing this was found, so it is not raised as a finding.

## 6. Evidence tier and verdict

| Driver | Tier | Verdict |
|---|---|---|
| ra_icu | E2 (linked in adc-b images, compile+link only) | PASS_WITH_LIMITATIONS |
| ra_elc | E2 (init/enable linked in hwtrigger) | FAIL (EVT-01) |
| ra_dmac | E1 | FAIL (EVT-02) |
| ra_dtc | E1 | DONE_WITH_CONCERNS (EVT-03) |
| board ELC glue | E2 | DONE_WITH_CONCERNS (EVT-04) |
| E3 on target | none | validation gap for all |

Phase verdict: DONE_WITH_CONCERNS.

## 7. Unresolved questions

- Does RA8P1 have a per-core ICU (separate IELSR banks for CM85 and CM33)? This decides whether the CM33 can collide on ICU slots. The device header shows a single R_ICU, but this was not proven.
- RA8E1 ELC peripheral numbers: there is no RA8E1 FSP `bsp_elc.h` in `refs/`. Do the RA8E1 chip-header values (ADC0 = 8) match the RA8E1 HWM?
- Does `ra8e1/ra_dmac.h` also accept channels 10-17?
- Is a DMAC/DTC channel/slot ownership split between CM85 and CM33 intended?
- The skill references (`hardware-fact-parity.md`, `repository-map.md`) say `bsp_elc.h`/`bsp_feature.h` are empty, but they are populated. This is skill drift, noted and not edited.
