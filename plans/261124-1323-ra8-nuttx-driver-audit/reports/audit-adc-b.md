# Audit ADC: RA8P1 ADC-B (CM85)

## 1. Scope, core, baseline

- Phase 6 (`phase-06-analog-adc.md`). Static audit only, plus the existing E2 artifacts.
- Core: CM85 (EVK-RA8P1).
- Baseline: PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- Path prefixes: A = `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8`, E = `.../boards/arm/ra8/evk-ra8p1`, F = `.../boards/arm/ra8/fpb-ra8e1`.
- Files read:
  - Driver: `A/ra_adc_b.c` (1754 lines), `A/hardware/ra8p1/ra_adc_b.h`.
  - Board: `E/src/ra8p1_adc_b.c`, `E/src/ra8p1_adc_b_hwtrigger.c`, `E/src/{Makefile,CMakeLists.txt}`, `E/include/board.h`.
  - Configs: `E/configs/adc-b{,-hwtrigger}`.
  - PX4 HAL: `platforms/nuttx/src/px4/renesas/ra8/adc/adc.cpp`.
  - RA8E1 blast radius: `A/ra_adc.c`.
- References:
  - Device header `refs/ra8p1/R7KA8P1KF_core0.h`.
  - FSP `refs/ra8p1/ek_ra8p1/adc/adc_ek_ra8p1_ep/e2studio/ra/fsp/src/r_adc_b/r_adc_b.c`.
  - FSP sample `.../e2studio/ra_gen/{hal_data.c,pin_data.c}`.
- E2 evidence: `adc-b` and `adc-b-hwtrigger` built clean as CM85 on 2026-11-24.
  - Artifacts: `reports/artifacts/nuttx/adc-b{,-hwtrigger}.{config,nm}`.
  - Logs: `artifacts/logs/nuttx-adc-b*.log`.
  - Every other config: "not built (user declined builds)".

## 2. Per-core trace matrix (CM85)

| Layer | Anchor | Status | FSP sample |
|---|---|---|---|
| Register map | `hardware/ra8p1/ra_adc_b.h` | E1 parity: 103 offsets and 317 bit fields match the device header (scripted); base 0x40338000 matches `R_ADC_B0_BASE` (:64802) | n/a |
| Clock / MSTP | `A/ra_adc_b.c:291-330`, `:1152-1180` | E1, order differs from FSP (ADC-05) | `r_adc_b.c:185-192` |
| Calibration | `A/ra_adc_b.c:348-398` | E1, diverges (ADC-03) | `r_adc_b.c:990-1150` |
| Channel/group | `A/ra_adc_b.c:409-417`, `:1240-1260` | E1, diverges (ADC-04) | `hal_data.c:39-45`, `r_adc_b.c:478-481` |
| ISR / FIFO | `A/ra_adc_b.c:584-650`, `:1009-1090` | E1 | `r_adc_b.c` |
| ELC/GPT trigger | `A/ra_adc_b.c:725-777,761` | E1, wrong ELSR (EVT-01) | `r_adc_b.c:410` |
| Board glue | `E/src/ra8p1_adc_b.c`, `ra8p1_adc_b_hwtrigger.c` | E2 compiled, **not linked** | n/a |
| Link | `adc-b.nm`, `adc-b-hwtrigger.nm` | no `ra8_adc_*` / `adc_b_*` / `adc_register` symbol | n/a |
| PX4 HAL | `platforms/nuttx/src/px4/renesas/ra8/adc/adc.cpp` | E1 (separate bare-metal ADC-B path) | n/a |

## 3. Findings

### ADC-01 High (confidence high): neither E2 image contains the ADC-B driver, and `/dev/adc0` is never registered

- **adc-b image.**
  - `ra8_adc_setup` adds channels only under `#ifdef CONFIG_EXAMPLES_ADC`, which is unset in this config. See `E/src/ra8p1_adc_b.c:101-180`.
  - With nchannels==0, the setup logs "No ADC channels configured" and returns OK.
  - `board_adc_initialize` is a `weak_function` (:190). nm shows it as `W board_adc_initialize`, size 4, which is a bare `return OK`.
  - Bringup (`E/src/ra8p1_bringup.c:262-272`) still logs "ADC-B initialized successfully".
- **adc-b-hwtrigger image.**
  - `libboard.a` holds a weak `board_adc_initialize` (from `ra8p1_adc_b.o`) and a strong `board_elc_initialize` (from `ra8p1_elc.o`).
  - The strong `board_adc_initialize` in `ra8p1_adc_b_hwtrigger.o` is never pulled, because no undefined symbol references it after the weak member resolves. nm shows the same 4-byte `W` symbol.
  - The image therefore has no ADC, no GPT trigger and no `ra_elc_link_set`.
  - If that object were ever pulled, `board_elc_initialize` would be multiply defined (EVT-04).
- **Gating.** The battery-voltage channel is gated by `EXAMPLES_ADC`, not by `RA_ADC_BATTERY_VOLTAGE`.
- **Impl.** `E/src/ra8p1_adc_b.c:101-190`, `E/src/ra8p1_adc_b_hwtrigger.c:89-119,190-213`.
- **Evidence.** nm artifacts above; the build logs show the objects compiled and archived.
- **Affected configs.** adc-b, adc-b-hwtrigger. RA8E1: none (board-local).
- **Remediation.**
  - Build the channel list from the board/ADC-B Kconfig, not from `EXAMPLES_ADC`.
  - Make the hwtrigger example the only strong definer, and remove the weak/strong archive race (for example, compile exactly one of the two glue files).
  - Return an error when no channel is configured.
- **Class.** Pre-existing defect. The E2 "built clean" result proves compilation only.

### ADC-02 High (confidence high): the hardware trigger path cannot work even when linked

- **GPT0 is never armed.** Nothing starts GPT0 or sets `GTINTAD.ADTRAUEN`/`GTADTRA`. The ADTRAUEN code at `A/ra_gpt.c:2290-2305` is not called, and no GPT symbol is linked.
- **The ELC route writes the wrong ELSR slot.** It writes ELSR14 (IOPORT1) instead of ELSR19 (EVT-01).
- **`ADTRGELC` is set to `0x3f`.** `A/ra_adc_b.c:761` enables all six ELC triggers. FSP writes the configured `elc_trigger_enable_mask` (`r_adc_b.c:410`).
- **README drift.** `E/configs/adc-b-hwtrigger/README.md` says "GPT0-triggered single scans at 1 kHz", but the code selects `RA_ADC_MODE_CONTINUOUS_SCAN` (`ra8p1_adc_b_hwtrigger.c:213`).
- **Affected configs.** adc-b-hwtrigger. RA8E1: the shared `ra_elc.h` enum, per EVT-01.
- **Remediation.**
  - Arm GPT0's ADC trigger: set the compare value, ADTRAUEN and start.
  - Fix the ELSR map.
  - Write a single-bit ADTRGELC mask.
  - Use single-scan mode, or correct the README.
- **Class.** Pre-existing / drift.

### ADC-03 Medium (confidence high): calibration diverges from the FSP sequence

- **What NuttX does.**
  - Writes `ADCALSTR = ADCALST0_1 | ADCALST1_1` (0x101) once.
  - Calibrates both converters in parallel.
  - Skips gain/offset calibration (FSP uses ADCALST0 = 0x3, a 3-bit field).
  - Skips S/H calibration.
  - Does not force-stop the ADC or clear the error flags first.
- **What FSP does.** It runs unit 0 (0x3), then S/H, then unit 1 (0x300), and notes: "Converters must be calibrated sequentially".
- **The PX4 HAL copies the same pattern.** `platforms/nuttx/src/px4/renesas/ra8/adc/adc.cpp:163` writes `ADCALST0 | ADCALST1`.
- **Impl.** `A/ra_adc_b.c:348-398`.
- **Ref.** `r_adc_b.c:990-1150`.
- **Affected configs.** adc-b, adc-b-hwtrigger, and PX4 evk-ra8p1 when `CONFIG_ADC` is set. RA8E1: none; ADC12 uses `ra_adc.c`, and the PX4 HAL is empty there because the fpb-ra8e1 PX4 defconfigs leave `CONFIG_ADC` unset.
- **Remediation.** Follow the FSP order: stop and clear errors, then unit 0 at 0x3 and wait for CALEND0, then S/H if used, then unit 1 at 0x300 and wait for CALEND1.
- **Class.** Pre-existing.

### ADC-04 Medium (confidence medium): scan-group field written as an index, not a mask; setup incomplete

- **SGSEL encoding.** `ADCHCR.SGSEL` gets `scan_group << SGSEL_SHIFT` (`A/ra_adc_b.c:409-417`). FSP documents the 5-bit field as a "Scan group mask selection" (`r_adc_b.h:321`), and its sample puts virtual channel 0 in group 0 with `.group = (1)` (`hal_data.c:39-45`). So NuttX group 0 writes SGSEL=0, which means no group, and the channel is never scanned.
- **Missing setup steps compared with FSP.** ADGSPCR, ADSYCR, clearing ADCHCR, ADTRGEXT, ADSGDCR and ADFIFOCR.
- **Error paths leak.** They leave MSTP and the clock enabled (`:1152-1280`).
- **Inconsistent channel IDs to `au_receive`.** The ISR reports the pchannel (`:1009-1090`), but the FIFO path reports the FIFO CH field, which is the vchannel (`:584-650`).
- **Partial group coverage.** FIFO count and level are handled for groups 0-3 only.
- **Affected configs.** adc-b, adc-b-hwtrigger. RA8E1: none.
- **Remediation.** Write `1 << group` into SGSEL after confirming against the HWM, add the missing FSP init steps, unwind on error, and report one consistent channel ID.
- **Class.** Pre-existing. Confidence is medium because HWM wording was not re-read; the FSP field comment and sample are the evidence.

### ADC-05 Low (confidence medium): clock enable/disable order differs from FSP

- **Enable.** NuttX writes ADCLKCR, then ADCLKENR=1, then polls ADCLKSR. FSP sets ADSYCR, writes ADCLKENR=0, waits for ADCLKSR==0, then writes ADCLKCR and enables.
- **Disable.** NuttX does not wait for ADCLKSR to clear.
- **Impl.** `A/ra_adc_b.c:291-330`.
- **Ref.** `r_adc_b.c:185-192`.
- **The PX4 HAL partly follows FSP.** `adc.cpp:136-143` writes ADCLKCR=0, then enables and polls.
- **RA8E1.** None.

### ADC-06 Low: board channel/pin comments conflict with `board.h` and the FSP sample

- **Glue comments.** `E/src/ra8p1_adc_b.c:47-63` claims P004=AN000, P000=AN004, P003=AN001 and P002=AN002.
- **board.h.** `E/include/board.h:385-396` gives P001=AN001, P007=AN007, P003=AN003 and P004=AN004.
- **FSP sample.** It uses P001 as analog (`pin_data.c:11`) for `ADC_CHANNEL_1` (`hal_data.c:43`), which is consistent with board.h.
- **Assessment.** The glue mapping is likely wrong. The code is dead today (ADC-01).
- **RA8E1.** None.

### ADC-07 validation gap

- **No E3 evidence.** The E2 images contain no ADC-B code, so even E2 for `ra_adc_b.c` covers compilation only.
- **DTC path not compiled.** `A/ra_adc_b.c:917-1005`, under `CONFIG_RA_DTC`, was not compiled in either image. It uses a `kmm_malloc` buffer with no D-cache maintenance (see EVT-03).
- **RA8E1 PX4 HAL.** If `CONFIG_ADC` were enabled in a PX4 RA8E1 image, the ungated `adc.cpp` would reference `R_ADC_B_*`, which does not exist on RA8E1, and fail to compile.

## 4. Items checked correct

- **Register map.** Base `R_ADC_B_BASE` 0x40338000 (NS 0x50338000) matches device header `R_ADC_B0_BASE` (:64802). All 103 register offsets and 317 bit positions in `hardware/ra8p1/ra_adc_b.h` match the device header (scripts in the session scratchpad: `cmp_adcb.py`, `cmp_adcb_bits.py`).
- **FIFODR and ADTRGGPT fields.** FIFODR has DATA [15:0], CH [30:24] and ERR bit 31. ADTRGGPT uses A bit m and B bit m+16.
- **Driver lifecycle.** `ra8_adc_initialize` validates nchannels, copies the config, and defaults to single scan, software trigger and 12-bit (`A/ra_adc_b.c:1511-1570`). The ioctl handlers (`:1411-1495`) take `sem_excl`. Shutdown detaches the IRQs, gates the clock and MSTP, and destroys the semaphore (`:1287-1360`).
- **RA8E1 C3 is closed.** `A/ra_adc.c:226` uses `R_ADC12_CH_BASE(1)` (`hardware/ra8e1/ra_adc12.h:43`). `F/Kconfig:239` has `select RA_ADC1` under `RA8E1_ADC_BMS_EXAMPLE`.

## 5. Rejected / unsupported paths, dead code

- **No `/dev/adc0`.** `EXAMPLES_ADC` is not set in either config, so no NSH `adc` app exists to exercise `/dev/adc0`, which is not registered anyway.
- **Dead public setters.** `ra8_adc_set_resolution`, `set_scan_mode`, `set_averaging`, `enable_fifo`, `read_sync` and `get_fullcount` are not linked anywhere.
- **Truncating cast.** `ANIOC_SAMPLES_ON_READ` accepts up to 1024 but stores the value in a `uint8_t` `avg_count` (`:1462-1466`). This is minor: values above 255 truncate.
- **Starts ADC1 MSTP without using it.** `adc_b_setup` starts `RA_MSTP_ADC0` and ADC1, while FSP starts only `FSP_IP_ADC,0`. This is harmless but unnecessary.

## 6. Evidence tier and verdict

| Driver | Tier | Verdict |
|---|---|---|
| ra_adc_b (arch) | E2 compile-only (not linked) | DONE_WITH_CONCERNS |
| adc-b board glue | E2 (dead weak stub linked) | FAIL (ADC-01) |
| adc-b-hwtrigger example | E2 compiled, not linked | FAIL (ADC-01, ADC-02) |
| PX4 HAL adc.cpp | E1 | DONE_WITH_CONCERNS (ADC-03) |
| RA8E1 ra_adc.c (C3) | E1 | PASS (closed) |

Phase verdict: DONE_WITH_CONCERNS.

## 7. Unresolved questions

- **SGSEL encoding.** The HWM wording for ADCHCR.SGSEL (mask vs index) needs confirmation; the evidence so far is the FSP struct comment and sample.
- **Analog pin map.** Which analog pins does the RDK/EVK user actually want (battery voltage/current)? The glue and `board.h` disagree.
- **Calibration approach.** Should the PX4 HAL keep its own bare-metal ADC-B path, or use the NuttX `/dev/adc0` driver? The duplication spreads the calibration defect.
