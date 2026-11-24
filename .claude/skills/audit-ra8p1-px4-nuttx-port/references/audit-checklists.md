# Audit checklists

## Common checklist

- Provenance: FSP sample path, FSP version, board (EK vs EVK), core and instance.
- Core identity: explicitly name CM85 or CM33 and its architecture.
- Build: one coherent selector; source compiled once; dependencies/selects valid.
- Configuration: default and test configs match board wiring and intended scope.
- Registers: base, secure/non-secure alias, offset, width, reserved bits,
  write protection (PRCR, PWPR) and ordering.
- Hardware facts: instance count, IRQ/event IDs, vector slots and per-unit
  feature support per [hardware-fact-parity.md](hardware-fact-parity.md).
- Lifecycle: initialize/open/configure/start/stop/close, rollback and reuse.
- Concurrency: atomic publication, task/ISR sharing, locks and bounded waits.
- Errors: status cleared/propagated; timeout and partial-init cleanup deterministic.
- Memory: address view, alignment, cache maintenance, MPU attributes, barriers.
- Ownership: no channel/pin/timer/IRQ/IPC-memory collisions across CM85 and CM33.
- Shared code: RA8E1 (`fpb-ra8e1`) impact stated for arch and HAL changes.
- Consumers: PX4 call semantics, units, polarity, frequency, mode, device paths.
- Evidence: build, symbol, runtime and stress results recorded separately.

## Mandatory core, Kconfig and device-header checks

- Always audit `arch/arm/src/ra8/Kconfig`; do not replace it with a
  driver-local Kconfig or a defconfig-only check.
- Verify the effective `RA_CPU_CORE_CM85` / `RA_CPU_CORE_CM33` choice for the
  selected config. Flag defconfigs that set only `RA_CPU_CORE=<n>`,
  `ARCH_CORTEXM33=y`, or the non-standard `=n` form for a choice member.
- CM85: `RA8_CM85_FAMILY`, `ARCH_CORTEXM85`, Helium/MVE, DPFPU, I/D cache,
  ITCM/DTCM, `armv8-m/Make.defs`, `CONFIG_BOARD_ARCHITECTURE="cortex-m85"`.
- CM33: `RA8_CM33_FAMILY`, `ARCH_CORTEXM33`, CTCM/STCM, `armv8-m/Make.defs`;
  no `ARMV8M_HAVE_ICACHE/DCACHE` and no `ARMV8M_ICACHE/DCACHE`.
- Verify `RA8P1_GROUP` routes `hardware/ra_memorymap.h`, Make.defs and CMake
  to RA8P1 files, and that bare includes do not resolve to `hardware/ra8e1/`.
- Compare register/IRQ facts with the selected core's header:
  `refs/ra8p1/R7KA8P1KF_core0.h` (CM85) or `refs/ra8p1/R7KA8P1KF_core1.h`
  (CM33). The collector prints each header's core config and any base defined
  in only one header.
- CM33 cache: core1 sets `__ICACHE_PRESENT 0` / `__DCACHE_PRESENT 0`; the
  Renesas C-cache/S-cache is the `R_CACHE` peripheral, which NuttX does not
  manage. Any CM33 path to `ARMV8M_HAVE_*CACHE`/`ARMV8M_*CACHE` (a select, a
  redefinition inside `if RA8_CM33_FAMILY`, or a CM33 defconfig line) is a
  finding: it runs SCB L1 maintenance (`ICIALLU`, `DCISW`, `CCR.IC/DC`) on a
  core without L1 cache and makes IPC coherency calls look real. An `R_CACHE`
  driver is a separate feature. `ra_ipc_initialize()` only reports a set
  `SCACTL.ENS` on CM33; that report is not coherency proof.

## NuttX lower-half

- Match the NuttX upper-half contract, return codes and locking rules.
- Verify ops table completeness and instance isolation.
- Keep ISR work bounded; acknowledge the peripheral and the ICU/NVIC.
- Validate MSTP/clock enable order and shutdown symmetry.
- Check no unbounded polling, dynamic allocation in restricted paths, or stale state.

## Register offsets and parameterized macros

- Load [register-offset-audit.md](register-offset-audit.md) for indexed
  register, channel, clock, MSTP or hardware-header audits.
- Report raw base-plus-literal addresses outside `hardware/` as candidates; a
  defect needs a matching named register symbol.
- Parameterize only after the device header/FSP prove first index, last index,
  fixed stride, width and no reserved-hole or special-member exception.
- Check caller bounds separately; a macro cannot make a runtime index safe.

## NuttX drivers, board examples and apps

- Trace the lower-half through the matching `drivers/` upper-half, public
  header, device registration and return/error contract.
- Trace each `evk-ra8p1/configs/<example>/defconfig` to the board glue in
  `src/ra8p1_*.c`, the registered device path, and the NSH/app consumer.
- No RA8P1-specific app exists in `apps/`; mark the app layer `N/A` with that
  reason, or trace the generic example the defconfig enables.
- Treat direct application use of private `arch/arm/src/ra8/` headers or raw
  MMIO as a layering finding unless confined to a named validation config.
- Do not let a loopback example prove PX4 integration or hardware function.

## PX4 HAL and board integration

- Confirm the linked HAL is `platforms/nuttx/src/px4/renesas/ra8/` and that a
  `ra8p1/` file is not assumed to be compiled.
- Check HAL `CMakeLists.txt` subdirectory list against the directories present
  (for example `cpuload/` exists but may not be added).
- Trace PX4 API units and timing semantics into the lower-half.
- Verify bus tables, chip selects, GPIO polarity, timer/channel ownership in
  `board_config.h`, `spi.cpp`, `i2c.cpp`, `timer_config.cpp`, `manifest.xml`.
- Check `*.px4board` module/driver enablement, especially `MODULES_PX4IOFIRMWARE`
  and `px4io_ipc` wiring for the CM33 IO board.
- Trace init order through `init.c`, `board_common.c` and `init/rc.board_*`.

## Kconfig, defconfig and CMake

- Detect duplicate selectors, dead options, `select` cycles and wrong-core gates.
- Compare NuttX symbols with board CMake and PX4 generated config.
- Check `boards/renesas/evk-ra8p1/Kconfig` prompt syntax and whether it is sourced.
- Verify validation-only features stay disabled in default PX4 builds.
- Inspect final archives/ELF symbols; config text alone is insufficient.
- Check that sources listed in `CMakeLists.txt` are also in `Make.defs` (the
  make build uses Make.defs), and that every `depends on` symbol exists.
  Example: `RA_IPC_IPCC` depended on a nonexistent `DRIVERS_IPCC` and its
  source was CMake-only, so it could never be enabled or built.
- Check that `ra_get_peripheral_clock()` IDs used by drivers exist in
  `ra_clock.h` and have a case in the selected chip's getter. Both chip
  getters use the shared `RA_PCLK_*` IDs; an ID with no case falls to the
  getter's default (system clock on RA8E1), which is a silent wrong clock.
- Check that `BOARD_IPC_SHMEM_BASE/SIZE` (`_sipc`/`_eipc`) cover the whole
  IPC_SHMEM region in every linker script both cores can use, and that the
  scripts assert `.ipc_shmem` stays empty.

## Interrupts, ICU, ELC, GPIO and pinmux

- Verify ICU `IELSRn` event-to-IRQ linking against `ra8p1_irq.h`, the FSP
  `vector_data.c` and the event numbers in the device header.
- Verify attach/enable/ack/clear/detach ordering and NVIC priority range.
- Verify ELC links used by GPT, ADC_B, DMAC/DTC triggers; flag commented-out
  `CONFIG_RA_ICU` / `CONFIG_RA_ELC` where a consumer needs them.
- Compare PFS/PWPR writes and pin function/electrical flags with the EK FSP
  `pin_data.c` / `configuration.xml` (the board pin authority) and
  `evk-ra8p1` `board.h` / `board.csv`.
- Check that IRQ/pin ownership does not collide across CM85 and CM33.

## DMA (DMAC/DTC)

- Separate DMAC and DTC; never infer one from the other.
- Verify CM85 D-cache clean/invalidate on CPU addresses and alignment to the
  cache line; verify CM33 S-cache behavior separately.
- Verify activation-source routing, channel allocation, widths, increments, limits.
- Audit completion/error signaling, abort/reset and descriptor lifetime.

## Timers: GPT, AGT, ULPT, HRT, PWM and DShot

- Verify source clock (PCLKD / GTCLK), prescaler math, counter width and wrap.
- Check compare/buffer update semantics and one-shot/periodic behavior.
- Trace HRT (`hrt.c`, `hrt_gpt_v2.c`, `hrt_systick.c`): which one is compiled,
  callback rearm and ISR vs cancel races.
- Detect GPT channel conflicts among system tick, HRT, PWM, DShot and the
  CM33 IO board timer config.
- Require scope/logic-analyzer evidence for waveform and timing claims.

## Serial, SPI and I2C (SCI_B, SPI_B, IIC, I3C)

- Verify baud/frequency divisor bounds and the actual kernel clock.
- Check mode, word width, bit order, FIFO thresholds and status clearing.
- Trace CS ownership across multi-device SPI buses and PX4 board tables.
- For IIC/SCI-I2C, verify repeated START, NOSTART/NOSTOP, ACK/NACK and timeout recovery.
- Map PX4 `ttyS*` names (TEL1/TEL2/TEL3/RC in `*.px4board`) to SCI channels.
- Require real device probes beyond loopback before functional status.

## Startup, linker, memory and dual-core IPC

- Compare reset entry, VTOR, stack, TCM/cache/MPU/FPU ordering with FSP
  `bsp/mcu` startup for the same core.
- Verify option-setting memory (OFS) sections, MRAM/OSPI placement, LMA/VMA.
- Verify CM33 boot release by CM85 and per-core memory windows.
- Check IPC/IPCC base addresses agree across NuttX `ra_ipc*.c`, NuttX board
  scripts, PX4 linker scripts and `px4io_ipc` transport.
- Check mailbox direction, barriers, cache coherency of shared memory and CRC.
- Build every affected core; one core's success does not validate another.
