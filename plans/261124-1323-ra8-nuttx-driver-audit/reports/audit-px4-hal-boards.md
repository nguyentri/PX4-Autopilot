# Audit: PX4 HAL and boards (phase 11, tag PX4)

Static audit only. No PX4 target was built: "not built (user declined builds)". The NuttX ELF layer is not applicable.

## 1. Scope, cores and baseline

- **Baseline:** PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- **Path aliases:**
  - H = `platforms/nuttx/src/px4/renesas/ra8`
  - B85 = `boards/renesas/evk-ra8p1` (CM85)
  - B33 = `boards/renesas/evk-ra8p1-io-cm33` (CM33)
  - A = NuttX `arch/arm/src/ra8`
- **Scope:**
  - H: hrt, io_pins, dshot, spi, board_*, adc, version
  - B85 and B33: src, init, px4board, nuttx-config, script.ld
  - HRT and PWM/DShot timer ownership
  - SPI/I2C tables, serial map, px4io_ipc, init order
- **RA8E1 relevance:** `fpb-ra8e1` maps `CONFIG_ARCH_CHIP_R7FA8E1AFDCFB` to `PX4_CHIP=ra8` (`platforms/nuttx/cmake/px4_impl_os.cmake:154-156`). So every H finding hits RA8E1.
- **Build mechanics confirmed:**
  - The board `src/` is added via `cmake/kconfig.cmake:411-412`.
  - The linker script is `nuttx-config/scripts/script.ld` (`platforms/nuttx/CMakeLists.txt:105-106`).
  - NuttX `E/src` (libboard) is not linked into PX4 images. NuttX builds `arch` only, and libboard belongs to the `nuttx` executable target. The PX4 `drivers_board` supplies `board_app_initialize` and `ra_board_initialize`.

## 2. Per-core trace matrix

### CM85, `evk-ra8p1_default`

| Layer | Anchor | Status | Reference |
|---|---|---|---|
| HAL list | `H/CMakeLists.txt` (hrt, io_pins, dshot, spi, adc, led_pwm, tone_alarm, board_*, version) | OK; `cpuload/` dead | n/a |
| HRT source | `H/hrt/CMakeLists.txt` builds only `hrt.c` | `hrt_gpt_v2.c` and `hrt_systick.c` dead | n/a |
| HRT timer | `B85/src/board_config.h:348` `HRT_TIMER 0` (GPT0) | Matches the hard-coded GPT0 MSTP/ELC | FSP `r_gpt.c` |
| HRT clock | PCLKD 250 MHz / 64 = 3.90625 MHz (`E/include/board.h:90`, `H/hrt/hrt.c:87-112`) | OK, wrap about 1100 s | n/a |
| HRT init | `px4_init.cpp:159` plus `B85/src/timer_config.cpp:157-161` | **Double init** (PX4-01) | n/a |
| GTWP key | `H/hrt/hrt.c:150`, `A/ra_gpt.h:143` | Wrong key (PX4-06) | `r_gpt.c:44-45` |
| PWM timers | `B85/src/timer_config.cpp`: GPT3/5/11/13 A on P912/P915/P903/P515 | OK; disjoint from HRT GPT0 | FSP RDK n/a |
| NuttX PWM | defconfig `CONFIG_PWM`, `RA_GPT0/3/5/11/13`; `E/src/ra8p1_pwm.c` not linked | No runtime conflict | n/a |
| Serial | `B85/src/board_config.h:140-180` vs `A/ra_serial.c:368-406` | **TEL3/RC swap** (PX4-03) | n/a |
| SPI | `B85/src/spi.cpp` bus 1 CS P110, DRDY P011/IRQ16 | Table CS PB00 cosmetic (PX4-08) | n/a |
| I2C | `B85/src/board_config.h:271-282` vs defconfig 112-114 (I2C off) | Drift (PX4-09) | n/a |
| Init order | `B85/src/init.c:209-248`: platform init, LEDs, GPIO, timers, SPI | OK apart from PX4-01 | n/a |
| Early reset | `ra8p1_boardinitialize` (`init.c:260-268`) | Never called (PX4-07) | n/a |
| IPC | no `RA_IPC` in defconfig; `px4io_cm85/` unbuilt; `init/rc.board_sensors:10-20` starts it | Missing (PX4-04) | n/a |

### CM33, `evk-ra8p1-io-cm33_default`

| Layer | Anchor | Status | Reference |
|---|---|---|---|
| Core | `RA_CPU_CORE_CM33=y`, `# RA_CPU_CORE_CM85 is not set` | OK (choice) | R1 |
| HRT | `B33/src/board_config.h:267` `HRT_TIMER 1` | GPT0 MSTP/ELC hard-coded (PX4-02) | n/a |
| HRT init | `B33/src/timer_config.cpp:166-168` | Never called | n/a |
| Init | `B33/src/init.c:85-120` only logs | No platform/IPC/timer init (PX4-04) | n/a |
| px4io | `B33/px4io_ipc/px4io.cpp:285` `user_start`; defconfig `INIT_ENTRYPOINT="nsh_main"` (77) | Never runs (PX4-04) | n/a |
| IPC HAL | `B33/px4io_ipc/ipc_hardware.cpp:180-218` registers ch0-3 | Aliasing (IPC-04) | R0 `r_ipc.c` |
| Memory | `script.ld`: mram 0x020E6000, itcm 0x20100000, dtcm 0x20110000, sram 0x22198000/32K; `RAM_START` 0x20110000 | Uses CM85 alias addresses (PX4-10, validation gap) | R1 `memory_regions.lld:2-5` |
| Resources | GPT1/3/5/11/13, DMAC ch0-3, SCI5 console | Overlap with CM85 (PX4-05) | n/a |

## 3. Findings by severity

### PX4-01: `hrt_init()` runs twice on every PX4 boot

- **Severity:** High (Critical candidate)
- **Confidence:** high
- **Core:** CM85; RA8E1 also
- **Failure sequence:**
  1. `board_app_initialize()` calls `px4_platform_init()` (`B85/src/init.c:213`), which calls `hrt_init()` (`platforms/nuttx/src/px4/common/px4_init.cpp:159`). The HRT starts and work-queue/uORB callouts may be queued.
  2. `B85/src/init.c:228` calls `evk_ra8p1_timer_initialize()`, which calls `hrt_init()` again (`B85/src/timer_config.cpp:157-161`).
  3. Second `hrt_init` (`H/hrt/hrt.c:456-470`), step (a): it re-inits the callout queue. Queued entries keep `deadline != 0` and are orphaned. A later `hrt_cancel` runs `sq_rem` on a queue that no longer holds them, and those callouts never fire.
  4. Step (b): `ra_icu_attach` takes two new ICU slots for the same GPT0 events, because there is no dedupe (`A/ra_icu.c:167-199`). Each event then runs `hrt_interrupt` twice.
  5. Step (c): it sets `g_last_counter = N` and `accumulated = 0`, then `hrt_gpt_start()` zeroes GTCNT. The next read gives a delta of `2^32 − N`, so `hrt_absolute_time()` jumps forward by about 1100 s.
- **Reference:** none (PX4 convention: HRT is initialized once by `px4_platform_init`).
- **Affected configs:** `evk-ra8p1_{default,dshot,test}`. **RA8E1: yes.** `boards/renesas/fpb-ra8e1/src/timer_config.cpp:157-159` is called from `fpb-ra8e1/src/init.c:202` after `px4_platform_init` at line 187.
- **Remediation:** remove `hrt_init()` from both `*_timer_initialize()` functions. Optionally make `hrt_init` idempotent with a static guard.
- **Classification:** pre-existing defect.

### PX4-02: `hrt.c` ignores `HRT_TIMER` for clock and interrupts

- **Severity:** High
- **Confidence:** high
- **Core:** RA8E1 (active), CM33 (latent)
- **Failure sequence:**
  1. Counter/compare registers use `R_GPT32_CH_BASE(HRT_TIMER)` (`H/hrt/hrt.c:176-181`).
  2. However, `hrt_enable_clock()` only releases `R_MSTP_MSTPCRE_GPT0` (`:212-216`), and `hrt_init()` attaches only `RA_ELC_GPT0_*` events (`:458-466`).
  3. RA8E1 sets `HRT_TIMER 1` (`boards/renesas/fpb-ra8e1/src/board_config.h:279`). Its defconfig enables `RA_GPT0/2/3/4` but not GPT1, and io_timer uses GPT0/2/3/4 for motors (`fpb-ra8e1/src/timer_config.cpp:71-74`). So nothing clears MSTPE30 (GPT1).
  4. GPT1 stays in module-stop, GTCNT reads constant, and `hrt_absolute_time()` does not advance.
  5. In addition, the HRT ISR is bound to GPT0 events, which are motor-2 PWM. It therefore runs only at PWM rate, and checks GPT1 status.
  6. B33 also sets `HRT_TIMER 1`, but its HRT is never started (latent).
- **Reference:** none (FSP `r_gpt` derives the MSTP bit and events from the channel).
- **Affected configs:** RA8E1 `fpb-ra8e1` PX4 images (not built); B33 latent. B85 (`HRT_TIMER 0`) is unaffected.
- **Remediation:** derive the MSTP bit and ELC events from `HRT_TIMER` (a lookup like `H/io_pins/io_timer_impl.c:160-175`). Add a `static_assert` if only a subset is supported.
- **Classification:** pre-existing defect. An RA8E1 board transcript is needed to confirm.

### PX4-03: TEL3 and RC device nodes swapped

- **Severity:** Medium
- **Confidence:** high
- **Core:** CM85
- **Failure sequence:**
  1. NuttX assigns ttyS numbers in ascending SCI order after the console (`A/ra_serial.c:368-372` SCI7 before `:405-406` SCI8). That gives SCI0 = console, SCI4 = ttyS1, SCI5 = ttyS2, SCI7 = ttyS3, SCI8 = ttyS4.
  2. `B85/src/board_config.h:140-180` declares SCI8 = ttyS3 (`RC_SERIAL_PORT "/dev/ttyS3"`) and SCI7 = ttyS4 (TEL3).
  3. Result: MAVLink TEL3 opens SCI8 (RC input pin P806) and the RC parser reads SCI7. RC and TEL3 both fail.
- **Affected configs:** `evk-ra8p1_default`, `_dshot`. **RA8E1:** none (board file).
- **Remediation:** swap the ttyS strings in `board_config.h` and the px4board `SERIAL_*` entries. Alternatively set `CONFIG_SCI8_SERIAL_CONSOLE`-independent fixed numbering.
- **Classification:** pre-existing defect.

### PX4-04: the dual-core PX4 IO path is not functional

- **Severity:** High
- **Confidence:** high
- **Core:** both
- **Failure sequence:**
  1. CM85: the defconfig lacks `CONFIG_RA_IPC`. `B85/px4io_cm85/` is never added to CMake. `CONFIG_BOARD_PX4IO_CM85` is inert, because the board Kconfig is not sourced (root `Kconfig:245-249` sources only rdk-rzv2h). `init/rc.board_sensors:10-20` runs `px4io_cm85 start`, which errors on every boot. Its include path (`ipc_hardware_cm85.cpp:76`) is wrong.
  2. CM33: `px4io` `user_start` (`B33/px4io_ipc/px4io.cpp:285`) is not wired: `INIT_ENTRYPOINT="nsh_main"` and no builtin. `board_app_initialize` (`B33/src/init.c:111-120`) does nothing. `ipc.cpp` (the only `__ipc_ram_*` user) is excluded from `px4io_ipc/CMakeLists.txt`.
  3. CPU1 is never released (IPC-01).
- **Affected configs:** B85 default, B33 default. **RA8E1:** none.
- **Remediation:** treat this as a deferred feature.
  - Remove the `px4io_cm85 start` line until the module is built.
  - Document B33 as build-only.
  - When enabling: start CPU1, set the entry point, and fix the channel model (IPC-03/04).
- **Classification:** deferral (with a misleading boot script).

### PX4-05: CM85/CM33 resource overlap

- **Severity:** Medium (latent until both run)
- **Confidence:** high
- **Core:** both
- **Overlaps:**
  - Both defconfigs enable GPT3/5/11/13 and DMAC channels 0-3.
  - The B33 console is SCI5, which is the B85 TEL2.
  - B33 enables GPT1, which is free on B85; that one is fine.
- **Affected configs:** B85 + B33 pair. **RA8E1:** none.
- **Remediation:** partition the peripherals: CM33 owns PWM/DMA only once the CM85 stops claiming them; give CM33 a non-shared console.
- **Classification:** pre-existing design gap.

### PX4-06: wrong GPT write-protect key

- **Severity:** Low
- **Confidence:** high
- **Core:** both; RA8E1 also
- **Detail:**
  - `HRT_GTWP_PRKEY (0xA500 << 8)` (`H/hrt/hrt.c:150`) and `GPT_GTWP_PRKEY (0xa500 << 8)` (`A/ra_gpt.h:143`) both equal 0xA50000.
  - PRKEY is GTWP[15:8] (`refs/ra8p1/R7KA8P1KF_core0.h:68095-68096`), and FSP writes 0xA500/0xA501 (`r_gpt.c:44-45`).
  - So every GTWP write is ignored and write protection is never set. Functionally benign, because GTWP resets unlocked, but the protect/unprotect pairs in `A/ra_gpt.c`, `H/io_pins/io_timer_impl.c:144-149` and `H/dshot/dshot.c:503-545` are no-ops.
- **Affected configs:** all RA8 GPT users including RA8E1.
- **Remediation:** set the key to `0xA500` (that is, `0xA5 << 8`) in both headers.
- **Classification:** pre-existing defect.

### PX4-07: early safe-output reset never runs

- **Severity:** Low
- **Confidence:** high
- **Core:** CM85
- **Detail:** `ra8p1_boardinitialize()` (`B85/src/init.c:260-268`, which calls `board_on_reset(-1)`) has no caller. NuttX calls `ra_board_initialize()` (`A/ra_start.c:859`), and the B85 version is empty (`B85/src/board_common.c:107-111`). Motor pins stay at reset state until GPIO init, which is acceptable (inputs), but the intent is dead.
- **Remediation:** call `board_on_reset(-1)` from `ra_board_initialize`, or delete the function.
- **Classification:** dead code.

### PX4-08: SPI table CS mismatch

- **Severity:** Low
- **Confidence:** medium
- **Detail:** the `spi.cpp` bus table lists CS PortB/Pin0, but the select toggles `PX4_SPI_IMU_CS1` = P110 (`E/include/board.h:152`, `spi.cpp:116`). Only the device-ID/cosmetic path is affected.
- **Remediation:** align the table to P110.
- **Classification:** drift.

### PX4-09: I2C bus table with I2C disabled

- **Severity:** Low
- **Detail:** `BOARD_NUMBER_I2C_BUSES 1` with I2C0 P400/P401, while defconfig 112-114 comments I2C out. The barometer/magnetometer cannot start.
- **Classification:** drift.

### PX4-10: CM33 image linked at CM85-view TCM aliases

- **Severity:** validation gap
- **Detail:**
  - B33 `RAM_START` 0x20110000 and `script.ld` itcm/dtcm 0x20100000/0x20110000 are the CM85 view of the CM33 TCM (CM33 local: 0x0/0x20000000).
  - The FSP CPU1 uses SRAM 0x220EA000.
  - Whether the CM33 can execute or access its own TCM through the 0x2010xxxx alias is unverified.
- **Remediation:** confirm in the RM. Otherwise relink at the local TCM or the FSP window.
- **Classification:** validation gap.

### PX4-11: duplicate serial assignment in leftover px4boards

- **Severity:** Low
- **Detail:** `B85/test.px4board:9-10` and `default_bk.px4board:7-8` put GPS1 and TEL1 both on ttyS1.
- **Classification:** drift.

## 4. Checked correct

- **HRT GTST clear** (`status & ~mask`, write-0-to-clear). Verified by `H/hrt/hrt.c:381-389`.
- **64-bit time accumulation** under a critical section. Verified by `H/hrt/hrt.c:218-232`.
- **Compare programming** (count plus ticks, in a critical section) and half-period keepalive. Verified by `H/hrt/hrt.c:265-295` and `hrt_schedule`.
- **Callout invoke**: drops the lock around callbacks and re-inserts periodic calls. Verified by `H/hrt/hrt.c:315-367`.
- **`hrt_cancel`** zeroes deadline/period. Verified by `H/hrt/hrt.c:563-574`.
- **B85 io_timer pins** match `board_config.h` motor pins, and DShot DMA comes from `CONFIG_RA_DMAC_GPT*_CHANNEL`. Verified by `B85/src/timer_config.cpp` vs `B85/src/board_config.h`.
- **HRT GPT0 is disjoint from PWM GPT3/5/11/13 on B85**, and no `ra_gpt_initialize(0)` caller exists. Verified by `B85/src/timer_config.cpp` and the NuttX PWM not being linked.
- **DRDY P011 / IRQ16** is consistent. Verified by `B85/src/board_config.h:238-253`.
- **Init order**: `px4_platform_init` runs before GPIO/SPI. Verified by `B85/src/init.c:209-248`.
- **No duplicate `board_app_initialize`**: NuttX `E/src` is not linked into PX4. Verified by `A/../Makefile:147-159` and `platforms/nuttx/CMakeLists.txt`.
- **PX4 `ipc_ram` agrees between cores** (0x22188000/64K), with no SRAM overlap. Verified by both `script.ld` files.

## 5. Rejected, unsupported and dead

- **Rejected:** "`CONFIG_RA_CPU_CORE_CM85=n` breaks core selection". It is inside a choice with `CM33=y`, so it is harmless (see IPC-12).
- **Dead:**
  - `H/cpuload/` (not in `H/CMakeLists.txt`)
  - `H/hrt/hrt_gpt_v2.c`, `H/hrt/hrt_systick.c`
  - `B85/px4io_cm85/`, the unsourced board Kconfig, `default_bk.px4board`, `init_bk/`
  - `B33/px4io_ipc/ipc.cpp`
  - `B33/nuttx-config/src/` (empty)
  - `B33/src/timer_config.cpp` init function
- **Inconsistency:** `B33/default.px4board` sets `ARCH_BOARD_CUSTOM`, while its NuttX defconfig uses `ARCH_BOARD="evk-ra8p1"`.
- **Cosmetic:** the log at `B85/src/init.c:233` prints a literal `\\n`.

## 6. Evidence tier and verdict

| Item | Tier |
|---|---|
| H hrt | E0 (static), not built |
| H io_pins/dshot | E0 |
| B85 board integration | E0 |
| B33 board integration | E0 |
| RA8E1 HRT path | E0 |

**Verdict:**

- **CM85 single-core:** plausible but not flight-ready until PX4-01 and PX4-03 are fixed.
- **RA8E1:** likely has no advancing HRT (PX4-02) plus the double init. This needs a board transcript.
- **Dual-core PX4:** non-functional (deferral).

## 7. Unresolved questions

1. Is `fpb-ra8e1` PX4 expected to run today? If so, PX4-02 is the top RA8E1 blocker. Confirm that GPT1 is not released elsewhere (no grep hit found).
2. Is the B33/px4io dual-core path a deferral or an active goal? This sets the severity of PX4-04 and PX4-05.
3. Is the intended TEL3/RC wiring SCI7 = TEL3 and SCI8 = RC (the board comments)? If so, only the ttyS strings are wrong.
4. RM: can the CM33 run from the 0x2010xxxx TCM alias (PX4-10)?

Status: DONE_WITH_CONCERNS
Summary: The PX4 HAL is structurally sound, but the HRT is initialized twice on both RA8 boards and hard-codes GPT0 regardless of `HRT_TIMER` (which breaks RA8E1). The evk-ra8p1 TEL3/RC nodes are swapped, and the dual-core IO path is not wired.
