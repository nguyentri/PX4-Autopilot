# Phase 5 audit: timers, watchdog, power (tag TMR)

Date 2026-11-24. Auditor: read-only subagent. Static audit only: nothing was built, flashed or run. No source, config, doc or skill file was edited.

## 1. Scope, cores, baseline

- Baseline: PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- Path prefixes:
  - `A` = `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8`
  - `E` = `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1`
  - `F` = `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/fpb-ra8e1`
- Drivers: `ra_gpt`, `ra_agt`, `ra_ulpt`, `ra_poeg` + `ra_poeg_chardev`, `ra_cac`, `ra_rtc` + `ra_rtc_lowerhalf`, `ra_wdt`, `ra_iwdt`, `ra_lpm` (+ `ra_idle`).
- PX4 HAL also read for GPT ownership: `platforms/nuttx/src/px4/renesas/ra8/{hrt,io_pins,dshot}`.
- Configs:
  - CM85: `pwm`, `agt`, `poeg`, `cac`, `rtc`, `iwdt`, `wdt-cm85`, `lpm`.
  - CM33: `wdt-cm33`.
- References (FSP samples): `refs/ra8p1/ek_ra8p1/<s>/<s>_ek_ra8p1_ep/e2studio/`, for `gpt`, `poeg`, `wdt`, `iwdt`, `rtc`, `lpm`. RA8P1 is `BSP_MCU_GROUP_RA8_GEN2`.
- No RA8E1 FSP reference exists in `refs/`. RA8E1 claims are therefore source-only.
- Build layer: no config here was built (the user declined builds). The only build evidence in the brief is `adc-b` and `adc-b-hwtrigger`, which are out of this phase.

## 2. Trace matrix

### CM85

The FSP sample path for each row is `refs/ra8p1/ek_ra8p1/<s>/<s>_ek_ra8p1_ep/e2studio/`. Every row's ELF symbol layer is "not built".

| Driver / config | Kconfig → Make.defs | CMake | Board init anchor | Register layer | FSP sample `<s>` |
|---|---|---|---|---|---|
| ra_gpt / pwm, poeg | `A/Make.defs:120` | `A/CMakeLists.txt:99` | `E/src` PWM nodes (GPT3/5/11/13) | Defects: TMR-01/02/03 | `gpt` |
| ra_poeg / poeg | `A/Make.defs:130` | `A/CMakeLists.txt:104` | `E/src/ra8p1_opeg.c` `board_poeg_initialize` | Bits OK; ISR gap TMR-11 | `poeg` |
| ra_agt / agt | Make.defs (RA8_AGT) | **missing** (TMR-13) | `E/src/ra8p1_bringup.c:290`, `E/src/ra8p1_agt.c:50-60` | Fault at init: TMR-05/06/07 | none (AGT not sampled) |
| ra_ulpt / lpm | `A/Make.defs:219` | `A/CMakeLists.txt:164` | `E/src/ra8p1_lpm.c:138, 258` | MSTP OK; subclock gap TMR-08 | `lpm` (ULPT wake) |
| ra_cac / cac | Make.defs (RA_CAC) | **missing** | `E/src/ra8p1_cac.c:64` | MSTP wrong module: TMR-04 | none |
| ra_rtc(+lh) / rtc | Make.defs (RA_RTC) | **missing** | `up_rtc_initialize` | Subclock never started, no carry: TMR-08/12 | `rtc` |
| ra_wdt / wdt-cm85 | `A/Make.defs:194` | `A/CMakeLists.txt:139` | `E/src/ra8p1_wdt.c:66` (ch0) | WDTRCR never set: TMR-10 | `wdt` |
| ra_iwdt / iwdt | `A/Make.defs:199` | `A/CMakeLists.txt:144` | `E/src/ra8p1_iwdt.c:64` | Register-start OK | `iwdt` |
| ra_lpm + ra_idle / lpm | `A/Make.defs:214`, ra_idle (ARCH_IDLE_CUSTOM) | ra_lpm `:159`; **ra_idle missing** | `E/src/ra8p1_lpm.c` | MOCO / DTC / dual-core gaps: TMR-09 | `lpm` |

### CM33 (`wdt-cm33`)

| Layer | Anchor | Status |
|---|---|---|
| Core selection | `E/configs/wdt-cm33/defconfig`: `CONFIG_RA_CPU_CORE_CM33=y`, `CONFIG_RA_CPU_CORE=1` (`A/Kconfig:418, 428-431`) | OK |
| WDT instance | `E/src/ra8p1_wdt.c:63-64` picks ch1 → `R_WDT_CH_BASE(1)` = 0x40202700 (`A/hardware/ra8p1/ra_wdt.h:35, 42-43`) | Matches FSP `R_WDT1_BASE` 0x40202700 and `r_wdt.c:21-27` (`BSP_CFG_CPU_CORE==1` → `R_WDT1`) |
| IRQ event | `A/ra_wdt.c:635` uses `RA_ELC_WDT1_UNDERFLOW` | Event number matches FSP `bsp_elc.h` (ELC join, §4) |
| Reset/NMI control | WDTRCR never written | TMR-10 (same as CM85) |
| Make/CMake | `A/Make.defs:194`, `A/CMakeLists.txt:139` | OK |
| Defconfig oddity | `CONFIG_ARMV8M_DTCM=y`, `CONFIG_ARMV8M_ITCM=y` on CM33 | Out of phase; see §7 |
| Build / ELF | not built | E1 |

## 3. Findings (ordered by severity)

### TMR-01: PWM duty and period are lost to empty GPT buffer registers

- **Severity:** High. **Confidence:** High. **Core:** CM85 and CM33 NuttX PWM lowerhalf. **Classification:** pre-existing.
- **Failure sequence:**
  1. `gpt_configure` enables the GTCCRA, GTCCRB and GTPR buffers (`A/ra_gpt.c:700`, `GPT_GTBER_PWM_ENABLE` = CCRA|CCRB|PR).
  2. `gpt_start` writes the period and duty straight to the active registers: GTPR (`:954`), GTCCRA (`:957`) and GTCCRB (`:958`).
  3. It then sets `CCRSWT` (`:965-966`). This force-transfers the buffer registers GTCCRC and GTCCRE, which were never written (0 or stale), into GTCCRA and GTCCRB.
  4. At every overflow, GTPBR (never written, so 0 or reset) reloads GTPR.
  5. `grep` finds no write to GTCCRC, GTCCRE or GTPBR anywhere in `ra_gpt.c`.
  6. Result: duty collapses at once, and the period changes after the first cycle.
- **Reference:** FSP `gpt/.../r_gpt/r_gpt.c:1359-1360` (`GTPBR = GTPR = gtpr`), `:1387-1388` (duty goes into GTCCRC/GTCCRE), `:55, 1515` (`GTBER = 0x550000` set after the buffers are loaded).
- **Affected:**
  - EVK configs `pwm` and `poeg`, plus any NuttX `/dev/pwmN` on CM85 or CM33.
  - The PX4 io_timer/dshot use their own register code and were not traced for this.
  - **RA8E1:** shared `ra_gpt.c`, so `F/configs/pwm` and `escs` are affected if they use this lowerhalf.
- **Remediation:** before setting CCRSWT, write GTPBR together with GTPR, and GTCCRC and GTCCRE together with GTCCRA and GTCCRB. Alternatively, drop the buffer bits for the start path and use them only for in-flight updates.
- **Evidence missing:** scope capture.

### TMR-02: PWM output polarity is inverted, and duty is off by one with no 0%/100% handling

- **Severity:** High. **Confidence:** Medium-High. **Core:** CM85 and CM33. **Classification:** pre-existing.
- **Failure sequence:**
  1. `GPT_GTIOR_PWM_HIGH_A/AB` uses GTIOA = 0x06 (`A/ra_gpt.h:187, 245-247`; applied at `A/ra_gpt.c:682, 975`). That setting gives initial low, high at compare match, low at cycle end.
  2. So the high time is period − CCR, which is the complement of the requested duty.
  3. `duty = period*duty>>16` is used with no −1, and 0% and 100% are not routed through OMDTY.
- **Reference:** FSP `r_gpt.c:50-51` and `:1739-1744`. The default is 0x9: high at cycle end, low at compare, so high time = CCR+1. Duty handling is at `:1620-1700`.
- **Affected:** as TMR-01, and RA8E1 as well (shared code).
- **Remediation:** use 0x09 (`LOW_COMPARE_MATCH_HIGH_CYCLE_END`) for A and B, write CCR = duty−1, and force 0%/100% via GTUDDTYC OADTY/OBDTY.
- **Evidence missing:** scope capture.

### TMR-03: GPT4-9 module-stop bits differ from FSP for RA8_GEN2, so GPT5 is likely never clocked

- **Severity:** High. **Confidence:** Medium-High (FSP source plus its explicit comment; the HW manual table was not read).
- **Core:** CM85 and CM33 (NuttX and PX4). **Classification:** pre-existing.
- **Failure sequence:**
  1. `A/ra_mstp.h:157-162` maps GPT5..GPT9 to MSTPE26..MSTPE22.
  2. FSP RA8_GEN2 maps all of GPT4-9 to a single bit: MSTPE27, `31-((ch>=4&&ch<=9)?4:ch)`, with the comment "GPT Channels 4-9 share stop bits on this MCU" (`gpt/.../bsp/mcu/all/bsp_module_stop.h:134-141`).
  3. Starting GPT5 clears MSTPE26, which is reserved or unrelated, so GPT5 stays gated. Its registers read 0 and ignore writes.
  4. The reverse also holds: `ra_mstp_stop(GPT4)` would gate GPT5-9 too.
- **Users:**
  - NuttX `ra_gpt.c` config table (`.mstp = RA_MSTP_GPTn`).
  - PX4 `io_pins/io_timer_impl.c:167-171`.
  - PX4 `dshot/dshot.c:215-219, 903`.
  - GPT5 is motor 2 (P915) in both CM85 and CM33 `timer_config.cpp`, and in the NuttX `pwm` and `poeg` samples.
- **Affected:** CM85 and CM33 PX4 nsh, EVK `pwm`, `poeg`.
- **RA8E1:** probably not affected. The non-GEN2 FSP branch is `31-ch`, but no RA8E1 reference is available to confirm.
- **Remediation:**
  - Make the GPT4-9 bitmask chip-conditional (MSTPE27 on RA8P1).
  - Reference-count the shared bit so stopping one channel does not gate the rest.
- **Evidence missing:** HW manual MSTPCRE table, plus an on-target read of the GPT5 GTCR after start.

### TMR-04: CAC passes a register bitmask where a module ID is expected, so DMAC is started and stopped instead

- **Severity:** High. **Confidence:** High. **Core:** CM85 (`cac` config); the same code path runs on CM33 if enabled. **Classification:** pre-existing.
- **Failure sequence:**
  1. `ra_cac_open` calls `ra_mstp_start(R_MSTP_MSTPCRC_CAC)` (`A/ra_cac.c:113`), and close calls `ra_mstp_stop(...)` (`:143`).
  2. `R_MSTP_MSTPCRC_CAC` = `R_MSTP_MSTPCRC_MSTPC0` = `(1<<0)` = 1 (`A/ra_mstp.h:116`, `A/hardware/ra8p1/ra_mstp.h:197`).
  3. The function takes `ra_mstp_module_t`, where value 1 is `RA_MSTP_DMAC` (`A/ra_mstp.h:177-178`).
  4. So open ungates the DMAC (MSTPA22, or 23 on CM33) and never ungates the CAC. CAC register writes are then ignored and measurement never completes.
  5. The last close sets MSTPA22, which stops the DMAC. That bit is shared with DTC (`A/ra_mstp.h:42-47`), so every DMA or DTC user dies.
- **Reference:** the correct enum `RA_MSTP_CAC` exists (`A/ra_mstp.h:234`).
- **Affected:** `cac`. RA8E1 has no CAC config but the code is shared, so it would be affected if enabled.
- **Remediation:** use `ra_mstp_start/stop(RA_MSTP_CAC)`. Consider making `ra_mstp_module_t` a distinct type so a stray `int` is caught by a warning.

### TMR-05: AGT faults at boot on a 16-bit write to an odd address

- **Severity:** Critical (for the `agt` config). **Confidence:** High. **Core:** CM85. **Classification:** pre-existing. Confirms and extends the earlier "agt non-functional" claim.
- **Failure sequence:**
  1. `board_bringup` → `ra_agt_board_initialize()` (`E/src/ra8p1_bringup.c:290`) → AGT configure.
  2. That calls `ra_agt_putreg16(priv, RA_AGTMR1_OFFSET, agtmr1)` (`A/ra_agt.c:227`) with `RA_AGTMR1_OFFSET` = 0x09 (`A/ra_agt.h:43`).
  3. A halfword store to an odd Device-memory address is unaligned. On Armv8-M that raises a UsageFault (UNALIGNED) regardless of CCR.UNALIGN_TRP, and NSH never comes up.
  4. If the store did land, CKS at bit 7 would spill bits 8-9 into AGTMR2 (TMR-06).
- **Reference:** `A/hardware/ra8p1/ra_agt.h:51-52`: AGTMR1 is an 8-bit register at 0x09 and AGTMR2 is at 0x0A. No FSP AGT sample exists, so the R7KA8P1 header is the reference.
- **Affected:** EVK `agt`, and any config with `CONFIG_RA8_AGT`. RA8E1 has no AGT config, but the code is shared and would fault the same way.
- **Remediation:** write AGTMR1 with `putreg8`, and write the divider to AGTMR2 with `putreg8`.
- **Evidence missing:** an on-target fault capture (CFSR UNALIGNED). The claim rests on the architecture rule.

### TMR-06: AGT clock divider is in the wrong register, and the reported frequency is wrong

- **Severity:** Medium. **Confidence:** High. **Core:** CM85. **Classification:** pre-existing.
- **Failure sequence:**
  1. `AGTMR1_CKS_SHIFT` is 7 (`A/ra_agt.h:76-77`). In hardware, CKS is AGTMR2[2:0] and applies only to the LOCO and subclock sources.
  2. PCLKB division is selected through TCK (/1, /2 or /8) and is never used.
  3. `ra_agt_getfrequency` returns `clock_freq >> divider` for every source (`A/ra_agt.c:480-496`). The board table asks for PCLKB with divider 3 (`E/src/ra8p1_agt.c:51-52`), so it reports PCLKB/8 while the hardware would run at PCLKB/1.
  4. The timer period is therefore 8× too short.
  5. LOCO is hard-coded at 32000 Hz (`:487`). The ULPT driver assumes 32768 Hz (`CONFIG_RA_ULPT_LOCO_FREQ=32768`), and the two are inconsistent.
  6. C2 itself (the PCLKB source) is closed (§4).
- **Remediation:** split the divider into TCK (for PCLKB) and AGTMR2.CKS (for LOCO/SOSC), and derive the reported frequency from the same fields.
- **Affected:** `agt`; RA8E1 shares the code.

### TMR-07: AGT channel range exceeds the hardware (phantom AGT2)

- **Severity:** Low. **Confidence:** High. **Core:** CM85. **Classification:** pre-existing (prior M4 still open).
- **Evidence:**
  - The hardware has 2 AGT channels and is 16-bit only (FSP `bsp_feature.h`).
  - `E/src/ra8p1_agt.c:58-59` defines an AGT2 at a raw `0x40221200` with event 0x08c.
  - Kconfig offers AGT2-6, and `RA_AGT_NCHANNELS` is 7.
- **Failure:** enabling AGT2 writes into an unrelated peripheral window and attaches the wrong event.
- **Private register offsets are also off by one:**
  - `ra_agt.h:45-48` has AGTIOC 0x0B, AGTISR 0x0C, AGTCMSR 0x0D, AGTIOSEL 0x0E.
  - The hardware header (`A/hardware/ra8p1/ra_agt.h:53-56`) has 0x0C, 0x0D, 0x0E and 0x0F.
- **One-shot stop:**
  - `AGTCR_STOP_CMD` is 0xF0 (`ra_agt.h:62`), which clears TSTART only.
  - FSP-style forced stop is TSTOP (0x04) with the flags kept and TUNDF cleared.
- **Remediation:** limit the range to 2 channels, delete the AGT2 board entry, and use the hardware-header offsets.

### TMR-08: Sub-clock oscillator is never started, but RTC (default) and ULPT/AGT sub-clock modes depend on it

- **Severity:** Medium. **Confidence:** Medium-High (no `SOSCCR` write exists in any `A/*.c`; reset-state behaviour not confirmed).
- **Core:** CM85 (`rtc`, `lpm`). **Classification:** pre-existing.
- **Failure sequence:**
  1. `up_rtc_initialize` always writes `RCR4 = RA_RTC_CLOCK_SOURCE_SUBCLK` (`A/ra_rtc.c:351`). It ignores `CONFIG_RA_RTC_CLOCK_SOURCE` (`A/Kconfig:4737-4745`), so choosing LOCO in Kconfig has no effect.
  2. It waits 6 count-source clocks and then runs the RCR2 START/RESET polls (`:71-110`).
  3. If SOSC is stopped, those polls time out: `RA_RTC_REGISTER_WAIT_TIMEOUT` is reached and `up_rtc_initialize` returns an error. The RTC is then disabled.
  4. The FSP sample sets `BSP_CLOCK_CFG_SUBCLOCK_POPULATED 1` with 1000 ms stabilisation (`rtc/.../bsp_cfg.h:53-57`), and its BSP explicitly sequences SOSCCR/SOMCR (`bsp_clocks.c:3192-3214`).
  5. The ULPT sub-clock mode (`A/ra_ulpt.c:234`) and the AGT `RA_AGT_CLOCK_SUBCLOCK` mode have the same dependency.
  6. `ra_ulpt.c:225` also spins on TCSTF with no timeout.
- **Affected:** `rtc`, and `lpm` when ULPT uses the sub-clock. RA8E1 shares `ra_rtc.c` but has no RTC config.
- **Remediation:**
  - Start SOSC in clock init when the sub-clock is populated: SOMCR drive, SOSCCR=0, read back, then wait for stabilisation.
  - Honour the Kconfig RCKSEL choice.
  - Bound the ULPT TCSTF poll.

### TMR-09: LPM standby entry misses FSP preconditions, and PM idle enters standby automatically

- **Severity:** Medium (validation gap). **Confidence:** Medium. **Core:** CM85 (`lpm`). **Classification:** pre-existing / validation gap.
- **Failure sequence:**
  1. `ra_lpm_enter_sw_standby` writes LPSCR=0x05 (`A/ra_lpm.c:321-323`), which matches FSP RA8_GEN2 (`lpm/.../r_lpm.c:18-22`).
  2. It does not do the FSP checks:
     - The MOCO-running check that FSP makes before standby (`r_lpm.c:240-246`).
     - Saving and clearing DTCST when MSTPA22 is active (`r_lpm.c:268-279`).
  3. It does not coordinate with the other core. Software standby on RA8P1 is a system state, so CM33 activity is not considered (manual not read).
  4. With `CONFIG_PM=y`, `PM_DEFAULT_STANDBY_DELAY=5000` and `ARCH_IDLE_CUSTOM=y` (`E/configs/lpm/defconfig:104-123`), `up_idlepm` calls `ra_pmstop(true)` inside a critical section (`A/ra_idle.c:80-145`). The system may then enter software standby on its own after about 5 s idle.
  5. In standby, SysTick and the J-Link/RTT console stop. Wake depends on whatever WUPEN currently holds.
- **Also:** `A/CMakeLists.txt` lacks `ra_idle.c`, so a CMake build of `lpm` drops the custom idle and fails to link `up_idle` (TMR-13).
- **Remediation:**
  - Add the MOCO check and DTCST handling.
  - Make PM-driven standby opt-in, or require configured wake sources.
  - Document the other-core precondition.
- **Evidence missing:** on-target current and wake transcript.
- **RA8E1:** shared `ra_lpm.c` branches; no RA8E1 lpm config.

### TMR-10: WDT/IWDT reset-or-NMI control and flag clearing don't match the documented intent

- **Severity:** Medium. **Confidence:** High for the code facts. **Core:** CM85 (`wdt-cm85`) and CM33 (`wdt-cm33`). **Classification:** pre-existing.
- **Failure sequence:**
  1. `ra_wdt_start` writes only WDTCR and then refreshes (`A/ra_wdt.c:219-229`). WDTRCR and WDTCSTPR are never written (the only WDTRCR uses in the file are reads/defines).
  2. FSP register-start mode writes WDTRCR (reset vs interrupt) and WDTCSTPR before the first refresh (`wdt/.../r_wdt.c:238, 246`), and enables NMI through `R_ICU->NMIER.WDTEN` (`:633-635`).
  3. As a result, `CONFIG_RA_WDT_NMI_MODE` (`ra_wdt.c:519-545`) can never produce an interrupt: the WDTRCR reset value selects reset.
  4. The NMI path in FSP goes through NMIER, while NuttX routes an IELSR event instead. That routing needs manual confirmation.
  5. `ra_wdt_interrupt` comments "Read and clear status flags" but only reads WDTSR (`:141-149`). FSP clears by writing (`r_wdt.c:429`), so the flag stays latched.
  6. `ra_wdt_stop` returns OK without stopping (`:240-250`). That is a hardware limit, but the upper half is told the stop succeeded.
  7. Bringup ignores the initialisation return codes (`E/src/ra8p1_bringup.c:116, 120`).
- **IWDT is better:**
  - It writes IWDTRCR and IWDTCSTPR in register-start mode (`A/ra_iwdt.c:236-266`).
  - OFS0 defaults to 0xFFFFFFFF (`A/Kconfig:6610-6613`), so IWDTSTRT=1 and register-start mode applies. FSP allows this on RA8P1 (`BSP_FEATURE_IWDT_SUPPORTS_REGISTER_START_MODE 1`).
- **Remediation:**
  - Write WDTRCR (RSTIRQS) and WDTCSTPR before the first refresh.
  - Use NMIER.WDTEN for NMI mode.
  - Clear UNDFF/REFEF in the ISR.
  - Return `-ENOTSUP` from stop.
  - Propagate the bringup return codes.
- **RA8E1:** shared `ra_wdt.c`; no RA8E1 WDT config.

### TMR-11: PX4 HRT hard-codes GPT0 clock and IRQs while using `HRT_TIMER` for registers

- **Severity:** High (CM33 and RA8E1). **Confidence:** High. **Core:** CM33 PX4, RA8E1 PX4. **Classification:** pre-existing.
- **Failure sequence:**
  1. Register access uses `R_GPT32_CH_BASE(HRT_TIMER)` (`platforms/nuttx/src/px4/renesas/ra8/hrt/hrt.c:176, 181`).
  2. But `hrt_enable_clock` clears only `R_MSTP_MSTPCRE_GPT0` (`:211-216`, called at `:408`).
  3. `hrt_init` attaches `RA_ELC_GPT0_CAPTURE_COMPARE_A` and `RA_ELC_GPT0_COUNTER_OVERFLOW` (`:460, 464`).
  4. `HRT_TIMER` is 1 on `boards/renesas/evk-ra8p1-io-cm33/src/board_config.h:267` and on `boards/renesas/fpb-ra8e1/src/board_config.h:279`.
  5. On those boards GPT1 stays module-stopped, unless something else ungates it (for example the NuttX `CONFIG_RA_GPT1` lowerhalf, which is enabled in the CM33 PX4 defconfig and not in RA8E1's).
  6. So `hrt_absolute_time()` is frozen and HRT callouts never fire. The PX4 scheduler and work queues stall.
  7. On CM33, the GPT0 IRQs belong to CM85's timer, which is a cross-core hazard if GPT0 is ever clocked on CM33.
- **Affected:** PX4 `evk-ra8p1-io-cm33` and PX4 `fpb-ra8e1` (the RA8E1 blast radius is direct). CM85 (`HRT_TIMER=0`) is unaffected.
- **Remediation:** derive the MSTP bit and the ELC events from `HRT_TIMER`, using a table like `io_timer_impl.c:162-176`.
- **Evidence missing:** whether `fpb-ra8e1` PX4 boots and logs advance. Check against existing RA8E1 on-target evidence, if any.

### TMR-12: RTC time read has no carry handling

- **Severity:** Low. **Confidence:** High. **Core:** CM85. **Classification:** pre-existing.
- **Failure sequence:** `up_rtc_getdatetime` reads SEC→YEAR once (`A/ra_rtc.c:429-435`), with no RCR1.CIE carry flag or reread. A read across a second rollover returns a torn time; at 23:59:59 that can be off by up to a day.
- **Reference:** FSP uses a carry ISR and a reread loop (`rtc/.../r_rtc/r_rtc.c:99, 238`).
- **Remediation:** read twice until RSECCNT is stable, or enable CIE and reread on carry.
- **RA8E1:** shared code; no RTC config.

### TMR-13: POEG ISR order, IRQ field and reset bits

- **Severity:** Low / validation gap. **Confidence:** Medium. **Core:** CM85 (`poeg`). **Classification:** pre-existing.
- **Failure sequence:**
  1. `ra_poeg_interrupt` runs the callback without clearing POEGG flags. The common ICU path clears IELSR.IR before the handler.
  2. FSP instead clears IR at the END and calls POEG "a level interrupt, so it must be cleared at the end of the ISR" (`poeg/.../r_poeg.c:307-363`).
  3. While the GTETRG pin stays low, the request may re-pend at once and cause an interrupt storm. The FSP sample avoids this by disabling the NVIC line in the callback (`poeg/.../src/hal_entry.c:448-449`).
  4. The board callback only logs (`E/src/ra8p1_opeg.c` `board_poeg_callback`), so syslog storms are possible.
  5. When there is no callback, `dev->irq` stays 0 rather than −1, and deinit calls `ra_icu_detach(0)`.
  6. `ra_poeg_reset` omits ST, which FSP clears (`r_poeg.c:187, 26-28`).
- **Board glue:** `ra_gpt_set_poeg` (`A/ra_gpt.c:2425-2480`) refuses while a channel is running (`-EBUSY`), and `gpt_putreg` keeps OADF/OBDF and GRP set across reopen. Both are correct (§4).
- **Remediation:**
  - Clear IR after the callback, or disable the line until `board_poeg_reset`.
  - Set `irq = -1` when there is no callback.
  - Include ST in the reset mask.
- **RA8E1:** shared `ra_poeg.c` with a 2-channel branch; no RA8E1 poeg config.

### TMR-14: Build-list drift and dead code

- **Severity:** Low (drift). **Confidence:** High.
- **Findings:**
  - `A/CMakeLists.txt` has no entries for `ra_cac.c`, `ra_agt.c`, `ra_rtc.c`, `ra_rtc_lowerhalf.c` or `ra_idle.c`, all of which `A/Make.defs` has. The CMake build of `cac`, `agt`, `rtc` and `lpm` is therefore incomplete, on top of the board CMake parity gap found earlier.
  - The `agt` defconfig still sets `CONFIG_TIMER=y` (`E/configs/agt/defconfig:56`).
  - `GPT_GTIOR_OADF_HIGHZ (0<<9)` is mislabelled (`A/ra_gpt.h:203`). The value 0 means "prohibited" (FSP `GPT_GTIOC_DISABLE_PROHIBITED`), so a reader would choose the wrong POEG disable level.
  - The GPT DMA map omits GPT6-9 (`A/ra_gpt.c:2144-2237`).
  - Dead code: `E/src/ra8p1_iwdg.c` (not built), and PX4 `hrt/hrt_gpt_v2.c` and `hrt/hrt_systick.c` (only `hrt.c` is in the CMakeLists).
- **Remediation:** sync the CMake lists, fix the label, and delete or wire up the dead files.
- **RA8E1:** the CMake drift is shared.

### TMR-15: CM85 and CM33 both claim GPT3/5/11/13 for motors (cross-reference)

- **Severity:** Medium (validation gap). **Classification:** pre-existing; already recorded in `plans/ra8p1_px4_nuttx_gap_analysis.md:17, 54, 67, 343, 376`.
- **Evidence:**
  - `boards/renesas/evk-ra8p1/src/timer_config.cpp:71-74, 107-113` and `boards/renesas/evk-ra8p1-io-cm33/src/timer_config.cpp:44-121` ("matching CM85") claim the same channels and pins.
  - The CM33 DMA macros are undefined in its defconfig.
- **Failure:** running both PX4 images together means two cores program the same GPT and pins.
- **Remediation:** an ownership split decision (user / product).

## 4. Checked and found correct

- **C1 closed:** `ra_poeg_register(const char *devpath, uint8_t channel)` exists and calls `register_driver`. Verified by `A/ra_poeg_chardev.c:118`.
- **C2 closed:** `ra_agt_getfrequency` uses `RA_PCLKB_FREQUENCY` for the PCLKB source. Verified by `A/ra_agt.c:482-484`. Divider semantics are still wrong (TMR-06).
- **ELC events:** every GPT/AGT/ULPT/WDT/IWDT/RTC/CAC/POEG event in `arch/arm/include/ra8/ra8p1_irq.h` was joined against FSP `wdt/.../bsp_mcu/ra8p1/bsp_elc.h`. All 151 NuttX entries matched. The only FSP-only entries are LVD1 and LVD2, which are out of scope.
- **GPT register map:**
  - GTCCRC 0x54, GTCCRE 0x58, GTCCRD 0x5C, GTCCRF 0x60 and GTPBR 0x68.
  - GTIOR OADF bit 9 and OBE bit 24; GTINTAD GRP bit 24.
  - GTBER CCRA 16, PR 20, CCRSWT 22 (`A/ra_gpt.h:255-259`).
  - TPCS [26:23], mapped `{0,1,2,3,4,5,6,8,10}`, which avoids the invalid 7 and 9 per FSP `CLOCK_DIVIDER_VALUE_7_9_VALID=0`.
- **Prescaler search:** `gpt_calculate_prescaler` picks the smallest valid divider (`A/ra_gpt.c:584`).
- **POEGG bits:** PIDF 0, SSF 3, PIDE 4, ST 16, INV 28, NFEN 29, NFCS 30 in `A/hardware/ra8p1/ra_poeg.h` match the R7KA8P1 header. POEG MSTP uses `RA_MSTP_POEG0-3` (`A/ra_poeg.c:170-185`), matching FSP MSTPCRD(14-ch).
- **POEG/GPT policy:** `ra_gpt_set_poeg` is under a critical section, ungates MSTP, returns `-EBUSY` while running, and the policy survives reopen through `gpt_putreg` (`A/ra_gpt.c:450, 2425-2480`). The board applies it to GPT3 and GPT5 before registering `/dev/poeg1` (`E/src/ra8p1_opeg.c`).
- **Other MSTP bits:** AGT = MSTPD(5-ch) (`A/ra_agt.c:203`), ULPT0/1 = MSTPE9/8 (`A/ra_ulpt.c:141-175`), RTC uses `RA_MSTP_RTC` (`A/ra_rtc.c:345`).
- **Base addresses:** IWDT 0x40202200, WDT 0x40202600 (WDT1 +0x100), RTC 0x40202000, CAC 0x40202400, ULPT 0x40220000, AGT 0x40221000 all match `R7KA8P1KF_core0.h:64706-64855`.
- **IWDT start mode:** the register-start path (IWDTRCR, IWDTCR, IWDTCSTPR, then refresh) is consistent with OFS0=0xFFFFFFFF and FSP `r_iwdt.c:67-81`. Verified by `A/ra_iwdt.c:236-275`.
- **OFS0 placement:** a single `.option_setting_ofs0` object per chip group, CM85 only on RA8P1 (`A/ra_start.c:146-147`); the RA8E1 branch is at `:100-101`.
- **LPSCR value:** software standby = 0x05 and deep standby = 0x08/0x09/0x0A match FSP RA8_GEN2. Verified by `A/ra_lpm.c:58-64` against `r_lpm.c:18-26`.
- **RTC init order:** stop, RCR2=0, RESET, RCR1=0, 24 h mode, start. This mirrors FSP open; note that it wipes the time on every boot, which is also what FSP open does. Verified by `A/ra_rtc.c:235-380`.
- **NuttX tick:** SysTick on `RA_CPUCLK_FREQUENCY`, so the tick owns no GPT. Verified by `A/ra_timerisr.c:48-124`.

### GPT channel ownership

| GPT ch | NuttX tick | PX4 HRT | PX4 PWM/DShot CM85 | PX4 PWM CM33 | NuttX `pwm` sample | NuttX `poeg` sample |
|---|---|---|---|---|---|---|
| 0 | - | CM85 (HRT_TIMER=0) | - | (IRQs wrongly attached, TMR-11) | - | - |
| 1 | - | CM33 and RA8E1 (broken, TMR-11) | - | - | - | - |
| 3 | - | - | motor P912 ch A | motor (conflict, TMR-15) | /dev/pwm (P912) | GPT3 + POEG1 |
| 5 | - | - | motor P915 (gated? TMR-03) | motor (conflict) | /dev/pwm (P915) | GPT5 + POEG1 |
| 11 | - | - | motor P903 | motor (conflict) | /dev/pwm (P903) | - |
| 13 | - | - | motor P515 | motor (conflict) | /dev/pwm (P515) | - |
| 2, 4, 6-10, 12 | - | - | free | free | free | free |

The NuttX tick is SysTick.

## 5. Rejected or unsupported paths, and dead code

- **Rejected:** "IWDT has no register-start mode on RA8P1". FSP `bsp_feature.h:374` sets `IWDT_SUPPORTS_REGISTER_START_MODE 1`.
- **Rejected:** a duplicate OFS0 object. The two definitions sit under mutually exclusive chip-group guards (`A/ra_start.c:97-147`).
- **Unsupported:** AGT2-6, which do not exist in hardware (TMR-07).
- **Dead code:**
  - `E/src/ra8p1_iwdg.c`.
  - PX4 `hrt_gpt_v2.c` and `hrt_systick.c`.
  - The `RA_AGT_CLOCK_AGTIO` value 0x80 falls outside `AGTMR1_TCK_MASK`, so it is silently masked to PCLKB.

## 6. Evidence tier and verdict

| Driver | Tier | Verdict |
|---|---|---|
| ra_gpt (PWM) | E1 | FAIL (TMR-01/02/03) |
| ra_poeg + chardev | E1 | PASS_WITH_LIMITATIONS (TMR-13; inherits GPT faults) |
| ra_agt | E1 | FAIL (TMR-05 boot fault) |
| ra_ulpt | E1 | PASS_WITH_LIMITATIONS (TMR-08 sub-clock, unbounded poll) |
| ra_cac | E1 | FAIL (TMR-04) |
| ra_rtc + lowerhalf | E1 | DONE_WITH_CONCERNS (TMR-08, TMR-12) |
| ra_wdt (CM85 + CM33) | E1 | DONE_WITH_CONCERNS (TMR-10) |
| ra_iwdt | E1 | PASS_WITH_LIMITATIONS (no build or target evidence) |
| ra_lpm + ra_idle | E1 | DONE_WITH_CONCERNS (TMR-09) |
| PX4 HRT (CM33, RA8E1) | E1 | FAIL (TMR-11) |

**Phase verdict: FAIL.** That rests on four Critical/High defects that stop the feature working: AGT boot fault, CAC/DMAC gating, GPT PWM buffers and polarity, and the CM33/RA8E1 HRT.

## 7. Unresolved questions

1. The RA8P1 HW manual MSTPCRE table: are GPT4-9 really on a single MSTPE27 bit (TMR-03)? Is there any on-target GPT5 PWM evidence that contradicts this?
2. The SOSCCR reset value on RA8P1, and whether the boot ROM or debugger starts SOSC (TMR-08).
3. Is IELSR routing of the WDT underflow event a valid interrupt path, or is NMIER the only one (TMR-10)?
4. Does PX4 `fpb-ra8e1` have on-target evidence of a running HRT? If so, what ungates GPT1 (TMR-11)?
5. Does the CM33 defconfig need `ARMV8M_DTCM/ITCM`, given that CM33 on RA8P1 may lack TCM? This is outside this phase.
6. The CM85/CM33 GPT ownership split needs a user decision (TMR-15).
