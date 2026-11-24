# Audit: dual-core IPC (phase 10, tag IPC)

Static audit only. No build, configure, flash or hardware access. Every config in this phase is "not built (user declined builds)". The only built images are `adc-b` and `adc-b-hwtrigger` (CM85), and neither has `RA_IPC`.

## 1. Scope, cores, baseline

- **Baseline:** PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- **Path aliases:**
  - A = `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8`
  - E = `.../boards/arm/ra8/evk-ra8p1`
  - F = `.../boards/arm/ra8/fpb-ra8e1`
- **Cores:**
  - CM85 = CPU0: D-cache, DPFPU.
  - CM33 = CPU1: no L1 D-cache, SP FPU. Its CTCM/STCM sit at 0x0 and 0x20000000 locally, which the CM85 sees at 0x20100000 and 0x20110000.
- **Scope:**
  - `A/ra_ipc.c`, `A/ra_ipc.h`, `A/hardware/ra8p1/ra_ipc.h`, `A/ra_ipc_ipcc.c`
  - Kconfig IPC menu
  - CPU1 release
  - `E/src/ra8p1_ipc*.c`
  - `E/scripts/{evk-ra8p1.ld, evk-ra8p1_non_ospi.ld, cm33, cm85, common}`
  - the PX4 `script.ld` for both boards
  - the configs `ipc-cm85`, `ipc-cm33`, `wdt-cm33`
- **References:**
  - R0 = `refs/ra8p1/evk_ra8p1_dual_core/RA8P1_DSP_example_cpu0`
  - R1 = `..._cpu1`
- **RA8E1 blast radius:** `RA_HAVE_IPC` is selected only inside the RA8P1 chip entries (`A/Kconfig:275` in `ARCH_CHIP_R7KA8P1KFLCAC` and `A/Kconfig:395` in `ARCH_CHIP_R7JA8P1JRLSAJ`). So no IPC finding reaches `fpb-ra8e1` unless stated otherwise.

## 2. Per-core trace matrix

### CM85 (CPU0), config `ipc-cm85`

| Layer | Anchor | Status | FSP sample |
|---|---|---|---|
| Kconfig | `A/Kconfig:4948-5056` (`RA_IPC` depends on `RA_HAVE_IPC && RA8P1_GROUP`; CH0/CH1 default y) | OK, plus a duplicate definition (IPC-11) | n/a |
| Core id | `ipc-cm85` sets `RA_CPU_CORE=0` directly | Works; sets a derived symbol (IPC-12) | R0 `BSP_CFG_CPU_CORE 0` |
| Units | `A/ra_ipc.c:56-70`: TX = IPC0, RX = IPC1 | **Inverted** (IPC-03) | R0 `ra/fsp/src/r_ipc/r_ipc.c:20-27`: send IPC1, receive IPC0 |
| Channel base | `A/ra_ipc.c:149` (`channel % 2`) | Channels 2-3 alias 0-1 (IPC-04) | R0 `r_ipc.c:112,129-130`: 2 channels per unit |
| IRQ link | `A/ra_ipc.c:557-571`: ch0-1 use `IPC_IRQ0`, ch2-3 use `IPC_IRQ1`; one ICU slot per channel | Mismatch (IPC-03/04) | R0 `ra_gen/ipc_thread.c:17-55`, `vector_data.c:12`: CPU0 receives on `IPC_IRQ0` |
| Send | `A/ra_ipc.c:455-487`: TXD plus SET0 | Extra event (IPC-09) | R0 `r_ipc.c:171` (TXD only), `:198` (SET only in EventGenerate) |
| RX ISR | `A/ra_ipc.c:192-259`: one word, `CLR_CLR` | OK for single-word traffic | R0 `r_ipc.c:353,408-424` |
| NMI | `A/ra_ipc.c:162-182`: clears IPCnNMI, never ICU `NMICLR` | Latent storm (IPC-06) | R0 `ra/fsp/src/bsp/mcu/all/bsp_group_irq.c:96-117` |
| Cache | `ipc-cm85` has `ARMV8M_DCACHE=y`; `ra_ipc.c` uses mailbox registers only | OK for registers; shmem not covered (IPC-08) | R0 non-cacheable sections |
| CPU1 release | none (grep for `CPU1INITVTOR`/`CPU1WAITCR`/`CPU1ACTCSR` is empty in NuttX and PX4) | **Missing** (IPC-01) | R0 `ra/fsp/src/bsp/mcu/all/bsp_common.h:723-736`, `src/ipc_squeue.c:393` |
| Linker | `E/scripts/evk-ra8p1_non_ospi.ld` (Make default) vs `evk-ra8p1.ld` (CMake, `E/src/CMakeLists.txt:111-112`) | Drift (IPC-10) | R0 `Debug/memory_regions.lld` |
| Board init | `E/src/ra8p1_bringup.c:123-134` calls `E/src/ra8p1_ipc.c:60-78` | OK; log claims `/dev/ipcc0-3` (IPC-13) | n/a |
| IPCC | `A/ra_ipc_ipcc.c` | Unbuilt: `IPCC` depends on `EXPERIMENTAL`, which no config sets (IPC-07) | none |
| Test | `E/src/ra8p1_ipc_test.c:40-120`: polled ch0 request/reply/ack | Well designed; self-consistent | none |

### CM33 (CPU1), configs `ipc-cm33` and `wdt-cm33`

| Layer | Anchor | Status | FSP sample |
|---|---|---|---|
| Core choice | `RA_CPU_CORE_CM33=y`, `ARCH_CORTEXM33=y`, `RA_CPU_CORE=1` | OK | R1 `BSP_CFG_CPU_CORE 1` |
| FPU | `ipc-cm33` sets `ARCH_DPFPU=y` under the comment "Cortex-M85 has FPU" | Wrong for CM33; Kconfig likely drops it (IPC-12) | R1 SP FPU |
| Cache | no cache options; `RA8_CM33_FAMILY` does not select `ARMV8M_HAVE_DCACHE` (`A/Kconfig:683-693`) | OK | n/a |
| Units | `A/ra_ipc.c:66-69`: TX = IPC1, RX = IPC0 | **Inverted** (IPC-03) | R1 `r_ipc.c:24-26`: send IPC0, receive IPC1 |
| IRQ | ch0-1 on `IPC_IRQ0` | Mismatch: CPU1 receives on `IPC_IRQ1` (IPC-03) | R1 `ra_gen/vector_data.c:17`, `ipc_thread.c` channel 1 / `IPC_IRQ1` |
| Image placement | links `evk-ra8p1(_non_ospi).ld`: MRAM 0x02000000, SRAM 0x22000000 | Collides with CM85 (see ARCH-03 in `audit-arch-foundation.md`; IPC-02 adds the copy/boot side) | R1 `Debug/memory_regions.lld:2-5`: RAM 0x220EA000, FLASH 0x02080000 |
| Start-up copy | `A/ra_start.c:610-641` under `CONFIG_RA_CM33_SUPPORT` | Dead: no such Kconfig symbol (IPC-02) | n/a |
| Console | SCI0, the same as `ipc-cm85` | Conflict when both run (IPC-13) | R1 uses SCI8 |
| Entry | nothing sets `CPU1INITVTOR` or clears `CPU1WAITCR` | CM33 runs only under a debugger (IPC-01) | R0 `bsp_common.h:723-736` |

## 3. Findings by severity

### IPC-01: nothing releases CPU1

- **Severity:** High
- **Confidence:** high
- **Core:** CM85 to CM33
- **Failure sequence:**
  1. CM85 boots.
  2. No code writes `R_CPU_CTRL->CPU1INITVTOR`, `CPU1WAITCR=0` or `CPU1ACTCSR=KEY|ACTREQ`.
  3. The CM33 stays in wait.
  4. Every CM33 image (`ipc-cm33`, `wdt-cm33`, PX4 `evk-ra8p1-io-cm33`) runs only if a debugger starts it.
  5. `ra8p1_ipc_test` on CM85 times out with `-ETIMEDOUT`.
- **Implementation:** `E/src/ra8p1_boot.c` (whole file, 110 lines, has no release). `A/hardware/ra8p1/ra_cpu_ctrl.h` has no `CPU1*` start macros (line 116 has only `SECEXT1`). The linker script header comment `E/scripts/evk-ra8p1_non_ospi.ld:44-49` claims "CM85 releases CM33 reset via SYSC".
- **Reference:** R0 `ra/fsp/src/bsp/mcu/all/bsp_common.h:723-736` (`R_BSP_SecondaryCoreStart`), called at R0 `src/ipc_squeue.c:393` after IPC callbackSet. Register offsets are `CPU1INITVTOR` @0x44, `CPU1WAITCR` @0x54 and `CPU1ACTCSR` @0x64 (`refs/ra8p1/R7KA8P1KF_core0.h:32062-32114`).
- **Affected configs:** `ipc-cm85` + `ipc-cm33`; PX4 pair. **RA8E1:** none.
- **Remediation:**
  1. Add a CM85-only `ra_cpu1_start(vtor)` helper and the `CPU_CTRL` macros.
  2. Call it from board bringup after `ra_ipc_initialize()`, gated by a Kconfig option with the CPU1 vector address.
  3. Correct the linker script comment.
- **Classification:** pre-existing gap.

### IPC-02: CM33 image placement and start-up copy are unreachable

- **Severity:** High
- **Confidence:** high
- **Core:** CM33
- **Failure sequence:**
  1. `ipc-cm33` and `wdt-cm33` link at CM85 addresses: MRAM 0x02000000, SRAM 0x22000000, `RAM_START` 0x22000000.
  2. The per-core `cm33/` scripts are not selected, because the selection in `E/scripts/Make.defs:25-40` is commented out. They are only on the `-L` path (`:46-49`).
  3. The alternative design (CM85 copies `.cm33_text`/`.cm33_data` into CM33 TCM, `E/scripts/evk-ra8p1_non_ospi.ld:213-247`) is dead: `A/ra_start.c:610-641` is under `CONFIG_RA_CM33_SUPPORT`, which no Kconfig defines.
  4. Result: no supported way to place a CM33 NuttX image.
- **Reference:** R1 `Debug/memory_regions.lld:2-5`.
- **Affected configs:** `ipc-cm33`, `wdt-cm33`. **RA8E1:** none (board scripts).
- **Remediation:** pick one model.
  - (a) A CM33 script at the FSP CPU1 window, selected when `RA_CPU_CORE_CM33=y`.
  - (b) Add the `RA_CM33_SUPPORT` Kconfig symbol and wire the copy.

  Then delete the other model.
- **Classification:** pre-existing gap. Overlaps ARCH-03, so cite that ID for the link collision itself.

### IPC-03: IPC unit direction and receive IRQ are inverted vs FSP

- **Severity:** High
- **Confidence:** medium
- **Core:** both
- **Failure sequence:**
  1. NuttX core0 sends on IPC0 and receives on IPC1. Core1 does the reverse (`A/ra_ipc.c:56-70`).
  2. FSP has core0 send on IPC1 and receive on IPC0, with the comment "IPC0 is Core1 -> Core0" (R0 `r_ipc.c:20-27`).
  3. FSP CPU0 takes its receive interrupt on `IPC_IRQ0` and CPU1 on `IPC_IRQ1` (R0 `vector_data.c:12`, R1 `vector_data.c:17`).
  4. NuttX attaches channels 0-1 on both cores to `IPC_IRQ0` (`A/ra_ipc.c:557-571`).
  5. Consequences:
     - A NuttX/NuttX pair agrees on the data path, so the polled `ra8p1_ipc_test` can pass.
     - Interrupt-driven receive on CM33 (PX4 `px4io_ipc` callbacks) waits on the event that goes to the CM85 side.
     - The CM85 takes self-interrupts from its own sends.
     - Interop with any FSP peer is broken.
- **Affected configs:** `ipc-cm85`, `ipc-cm33`, PX4 `evk-ra8p1-io-cm33`. **RA8E1:** none.
- **Remediation:**
  1. Swap the `IPC_TX_BASE`/`IPC_RX_BASE` selection to match FSP.
  2. Bind the receive IRQ per core: core0 → `IPC_IRQ0`, core1 → `IPC_IRQ1`.
  3. Fix the comments at `A/hardware/ra8p1/ra_ipc.h:91,105`.
  4. Confirm against the RM ICU event table, since the event-to-core routing is inferred from the FSP samples.
- **Classification:** pre-existing defect.

### IPC-04: four logical channels over two hardware channels

- **Severity:** High
- **Confidence:** high
- **Core:** both
- **Failure sequence:**
  1. `RA_IPC_NUM_CHANNELS` is 4 (`A/ra_ipc.h:42`), but `ra_ipc_get_channel_base()` uses `channel % 2` (`A/ra_ipc.c:149`).
  2. So logical channel 2 reads and writes the same CH0 registers as channel 0, and channel 3 the same as channel 1.
  3. `ra_ipc_channel_register()` does not check `ra_ipc_channel_is_enabled()` (`A/ra_ipc.c:540-590` vs `:726-749`). Each call takes a new ICU slot linked to the same event.
  4. PX4 CM33 registers all four (`boards/renesas/evk-ra8p1-io-cm33/px4io_ipc/ipc_hardware.cpp:185-218`), with only CH0 and CH1 enabled in its defconfig. Two ISRs then race for one RXD word: ch0 and ch2 both read CH0 RX.
- **Reference:** R0 `r_ipc.c:32,112` (two channels per unit).
- **Affected configs:** PX4 `evk-ra8p1-io-cm33`; any NuttX user of channels 2 and 3. **RA8E1:** none.
- **Remediation:**
  1. Set `RA_IPC_NUM_CHANNELS` to 2.
  2. Reject disabled channels in `register`/`read`/`write`.
  3. Drop or remove the CH2/CH3 Kconfig options.
  4. Multiplex PX4's four message types over one channel with a type tag.
- **Classification:** pre-existing defect.

### IPC-05: the PX4 dual-core path is not wired end to end

- **Severity:** Medium
- **Confidence:** high
- **Core:** both
- **Failure sequence:** see PX4-03 and PX4-04 in `audit-px4-hal-boards.md`.
  1. The CM85 PX4 defconfig has no `CONFIG_RA_IPC`.
  2. `px4io_cm85` is never added to the build.
  3. CM33 `px4io` `user_start` is never invoked, because the entry is `nsh_main` and there is no builtin.
  4. CPU1 is never released (IPC-01).
- **Affected configs:** PX4 pair. **RA8E1:** none.
- **Remediation:** see PX4-03 and PX4-04.
- **Classification:** pre-existing deferral.

### IPC-06: the IPC NMI handler never clears ICU `NMICLR`

- **Severity:** Medium
- **Confidence:** medium
- **Core:** both
- **Failure sequence:**
  1. The peer sets IPCnNMI.
  2. The ICU NMI is pending.
  3. `ra_ipc_nmi_interrupt()` clears only the IPC-side flag (`A/ra_ipc.c:162-182`).
  4. FSP also writes `R_ICU->NMICLR` and waits for `NMISR` to clear (R0 `bsp_group_irq.c:96-117`). Without that, the NMI re-enters until lockup.
  5. It is latent today: `ra_ipc_nmi_enable()` (`A/ra_ipc.c:388-431`) has no caller, its `up_enable_irq(NMI)` is a no-op, and `RA_IPC_USE_NMI` (default y) has no consumer.
- **Affected configs:** none active; `ipc-cm85`, `ipc-cm33` and PX4 CM33 set `USE_NMI=y` with no effect. **RA8E1:** none.
- **Remediation:**
  1. Route through the arch NMI dispatcher and clear `NMICLR`.
  2. Or remove `RA_IPC_USE_NMI` and the NMI API until there is a user.
- **Classification:** pre-existing, dead code.

### IPC-07: the IPCC upper half is unbuilt and lossy

- **Severity:** Low
- **Confidence:** high
- **Core:** both
- **Issues:**
  - `RA_IPC_IPCC` depends on `IPCC`, which depends on `EXPERIMENTAL` (`drivers/ipcc/Kconfig:1-4`). No config sets it.
  - Word-granular copy drops `len % 4` bytes. This violates the `ops.write` partial-count contract in `include/nuttx/ipcc.h:53-96`.
  - The PX4 CM85 `script.ld` lacks `_sipc`/`_eipc`, so an IPCC build there would fail to link. The NuttX `E/scripts/evk-ra8p1.ld:854-860` does define them.
  - `RA_IPC_OPENAMP` has no code.
- **Affected configs:** none built. **RA8E1:** none.
- **Remediation:** handle tail bytes, or round the length and return a partial count. Mark the option experimental or remove it.
- **Classification:** dead code / validation gap.

### IPC-08: no cache policy for IPC shared memory on CM85

- **Severity:** Low (latent)
- **Confidence:** medium
- **Core:** CM85
- **Issues:**
  - `ipc-cm85` and PX4 CM85 enable the D-cache.
  - The MPU nocache list covers only the `__ram_*_nocache` sections and exists only under `RA_FSP_LINKER_STYPE` (`A/ra_start.c:388-403`).
  - The IPC regions (0x220E2000 NuttX, 0x22188000 PX4) are not in it.
  - Only the unbuilt IPCC layer does cache maintenance.
  - Today's register-only mailbox path is unaffected. Any shared-memory transport (PX4 `transport_sharedmem.cpp`) would see stale data.
- **Affected configs:** future shmem users. **RA8E1:** none.
- **Remediation:** add an MPU non-cacheable region for the IPC window on CM85.
- **Classification:** pre-existing gap.

### IPC-09: `write` also pulses `SET` after `TXD`

- **Severity:** Low
- **Confidence:** medium
- **Detail:** `A/ra_ipc.c:480-484` writes `TXD`, then `SET`. FSP writes `TXD` only (R0 `r_ipc.c:171`); `SET` is a separate `EventGenerate` (`:198`). The receiver sees an extra event bit, which the NuttX ISR clears with `CLR_CLR`.
- **Remediation:** drop the `SET` write.
- **Classification:** drift.

### IPC-10: Make and CMake pick different linker scripts

- **Severity:** Low
- **Confidence:** high
- **Detail:**
  - CMake always uses `evk-ra8p1.ld` (`E/src/CMakeLists.txt:111-112`).
  - Make uses `evk-ra8p1_non_ospi.ld` unless `RA_FSP_LINKER_STYPE=y` (`E/scripts/Make.defs:25-40`, default n at `A/Kconfig:6972`).
  - The IPC window base is the same in both (0x220E2000/32K).
  - Also: `OSPI1_CS1_LENGTH` is duplicated at `evk-ra8p1.ld:57`, and in the non-OSPI script `sram` (0x22000000/1664K) overlaps `ipc_shmem` 0x220E2000. The latter is safe only because RAM_SIZE in the defconfigs is 512K.
- **RA8E1:** F has its own scripts; not checked here.
- **Remediation:** mirror the Make selection in CMake, and shrink `sram` or move the IPC region out of it.
- **Classification:** drift.

### IPC-11: duplicate Kconfig definitions

- **Severity:** Low
- **Confidence:** high
- **Detail:** a second `config RA_HAVE_IPC` at `A/Kconfig:5998` and a second `config RA_IPC` at `:6065-6069`, which depends only on `RA_HAVE_IPC`. Kconfig merges them; the second prompt lacks the `RA8P1_GROUP` guard.
- **RA8E1:** none in practice (`RA_HAVE_IPC` is not selected there).
- **Remediation:** delete the second pair.
- **Classification:** drift.

### IPC-12: defconfig hygiene

- **Severity:** Low
- **Confidence:** high
- **Detail:**
  - `ipc-cm33` sets `ARCH_DPFPU=y` with a "Cortex-M85" comment, which is wrong for CM33.
  - All three configs set the derived `RA_CPU_CORE` directly.
  - PX4 CM33 uses `# CONFIG_RA_CPU_CORE_CM85 is not set` with `RA_CPU_CORE_CM33=y`. Harmless inside a choice, but non-standard.
- **Remediation:** run `savedefconfig` and fix the comment.
- **Classification:** drift.

### IPC-13: console and log claims

- **Severity:** Low
- **Confidence:** high
- **Detail:**
  - `ipc-cm33` uses SCI0 as its console, the same as `ipc-cm85`. Both cores drive the same TX pin when paired. FSP CPU1 uses SCI8.
  - `E/src/ra8p1_ipc.c:77` logs `/dev/ipcc0-3`, but only two hardware channels exist.
- **Remediation:** give CM33 its own SCI (or RTT) console, and fix the log.
- **Classification:** drift.

## 4. Checked correct

- **IPC offsets and bits:** base 0x40020000; units at 0xC0/0x100; channel stride 0x20; STA `RDY` b16, `FULL` b17; IPC0NMI at 0x80, IPC1NMI at 0x90. Verified by `A/hardware/ra8p1/ra_ipc.h` vs `refs/ra8p1/R7KA8P1KF_core0.h` (R_IPC block).
- **ELC events:** `IPC_IRQ0` = 0x05B, `IPC_IRQ1` = 0x05C. Verified by `A/ra_ipc.c:552-564` vs R0 `vector_data.c:12`.
- **NMI register selection:** core0 sets IPC1NMI and clears IPC0NMI. Verified by `A/ra_ipc.c:56-62` vs R0 `r_ipc.c:20-27` comment.
- **Semaphore and lock usage:** non-SMP `spin_lock_irqsave` = `up_irq_save`. Verified by `A/ra_ipc.c:330-378`.
- **Build lists:** both build systems add `ra_ipc.c` and `ra_ipc_ipcc.c`. Verified by `A/Make.defs:202-210` and `A/CMakeLists.txt:147-155`. The same holds for `E/src/Makefile:200` and `E/src/CMakeLists.txt:97-99`.
- **IPC test protocol:** token, request/reply/ack, timeout, mutex. Verified by `E/src/ra8p1_ipc_test.c:40-120`.
- **PX4 IPC window:** the CM85 and CM33 `ipc_ram` regions agree at 0x22188000/64K. The CM85 sram ends at 0x22180000 and the CM33 sram starts at 0x22198000, so they do not overlap. Verified by `boards/renesas/evk-ra8p1/nuttx-config/scripts/script.ld:96` and `boards/renesas/evk-ra8p1-io-cm33/nuttx-config/scripts/script.ld` memory block.
- **CM33 cache:** CM33 configs carry no D-cache option, and none is possible. Verified by `A/Kconfig:683-693`.

## 5. Rejected, unsupported and dead

- **Rejected:** "CMake omits `ra_ipc.c`", a historical theme. Both build lists include it (section 4).
- **Dead:**
  - `RA_CM33_SUPPORT` copy block (`A/ra_start.c:610-641`)
  - `ra_ipc_nmi_enable` and `RA_IPC_USE_NMI`
  - `RA_IPC_OPENAMP`
  - `ra_ipc_ipcc.c` (unbuildable without `EXPERIMENTAL`)
  - `.cm33_*` sections in both NuttX and PX4 CM85 scripts
  - `msgq_send` (`A/ra_ipc.c:1021-1160`): over-reads the caller buffer by up to 3 bytes and returns `nwords*4`. It has no in-tree user (Low if kept).
- **Comment drift:** PX4 CM85 `script.ld:257-271` says "Reserve full 32KB" for a 64K region.

## 6. Evidence tier and verdict

| Driver / item | Tier | Note |
|---|---|---|
| `ra_ipc` (CM85) | E0 | not built |
| `ra_ipc` (CM33) | E0 | not built |
| `ra_ipc_ipcc` | E0 | unbuildable as configured |
| CPU1 release | n/a | absent |
| Linker partition | E0 | static only |

**Verdict:** not dual-core capable. The mailbox register layer is close, but four things block a working pair:
- CPU1 release (IPC-01)
- CM33 placement (IPC-02 / ARCH-03)
- unit/IRQ direction (IPC-03)
- channel model (IPC-04)

No RA8E1 exposure.

## 7. Unresolved questions

1. Is a debugger-started CM33 the intended bring-up model? If so, IPC-01 is a deferral; if not, it is a defect.
2. Which CM33 placement model is intended: FSP CPU1 window, CM33 TCM copy, or PX4 0x020E6000/0x2010xxxx?
3. RM confirmation: is `IPC_IRQ0` delivered only to CPU0's ICU and `IPC_IRQ1` only to CPU1's? This decides the exact IPC-03 fix.

Status: DONE_WITH_CONCERNS
Summary: The IPC register layer matches the hardware map, but nothing releases CPU1, the CM33 images have no valid placement, the unit/IRQ direction is inverted vs FSP, and four logical channels alias two hardware channels.
