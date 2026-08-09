# NuttX Driver Porting Playbook

**Date:** 2026-08-09
**Status:** Phase 2 (Workflow Enablement)  
**Audience:** Developers porting FSP drivers to NuttX for RZ/V2H

Step-by-step recipe for adding a new driver. Each step references existing exemplars and design patterns documented elsewhere.

---

## Step 1: Read FSP Source

**Goal:** Understand the hardware interface and functional requirements.

**Location:** Resolve the sample and core through
[reference-source-map.md](./reference-source-map.md). Prefer
`refs/rzv2h_evk/<sample>/<sample>_rzv2h_evk_<core>_ep/e2studio/`; use the
integrated or legacy trees only for the exceptions recorded in that map.

**Read these files:**
- `configuration.xml` — selected core, module, channel, and configurator properties
- `rzv_gen/{hal_data,pin_data,vector_data}.*` — generated integration contract
- `rzv_cfg/fsp_cfg/r_<driver>_cfg.h` — selected driver options
- `r_<driver>.h` — API interface (function signatures, config structs)
- `r_<driver>.c` — Implementation (register access, init sequence, ISR patterns)
- `src/*_ep.c` or `hal_entry.c` — example lifecycle and expected behavior

Not every NuttX driver has a same-IP FSP example. In particular, SCI-B is not
SCIF/SCIFA, SPI-B is not RSPI, and the current Ethernet reference is a legacy
CA55 project. Record such gaps instead of substituting a nearby IP block.

**Extract and document:**
- Module base address
- Clock resource ID and reset resource ID from CPG
- Interrupt numbers (ICU routing slot and physical GIC INTID)
- Register map (offsets, bit definitions)
- DMA channels (if applicable)
- Pin multiplexing requirements from IOPORT/PFC, not ICU

**Example:** For SPI-B driver:
```
Base:       0x1004A000
CPG:        CPG_SPI_B_CLK (ID = 0x2C)
IRQ (ICU):  SPI_B_INT0 = 32, SPI_B_INT1 = 33
GIC:        (map via interrupt.h)
DMAC:       RX uses DMAC channel 4, TX uses channel 5
Pins:       MOSI=P4_2, MISO=P4_3, CLK=P4_4, CS=P4_5
```

---

## Step 2: Create Hardware Header

**File:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_<driver>.h`

**Content:**
- Register base address macro
- Register offset macros
- Bit definitions and masks
- Interrupt IDs

Do not seed a new header with example addresses or IRQ values. Copy the layout
style from the nearest current `hardware/rzv_*.h`, then derive every base,
offset, mask, CPG/reset ID, ELC event, and GIC INTID from applicable
CMSIS/manual/FSP evidence. Use NuttX `getreg*()`/`putreg*()` helpers rather
than inventing raw volatile-access macros.

**Cross-check:** Match the selected silicon/core view. An FSP driver for a
different device or core is supporting evidence, not authority.

---

## Step 3: Skeleton Lower-Half Driver

**File:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_<driver>.c`

Implement against the real NuttX upper-half contract; operation tables and
registration return types differ by subsystem. Preserve this lifecycle:

1. validate instance and configuration;
2. enable the documented CPG clock;
3. assert/deassert module reset through the current RZ/V2H clock/reset helper;
4. apply board IOPORT/PFC configuration;
5. initialize peripheral state while its interrupts are masked;
6. attach the exact ICU/GIC events;
7. enable the peripheral and its IRQs;
8. on any failure, unwind IRQ, peripheral, reset, clock, and allocation in
   reverse order;
9. make explicit uninitialize follow the same shutdown contract.

The ISR clears only the source(s) it owns and defers blocking/heavy work.
Do not add a manual GIC acknowledgement unless the current architecture
contract requires it.

**References:** `rzv_gtm.c` for a timer lower-half lifecycle,
`rzv_spi.c` for a bus lower-half, and `rzv_serial.c` for the UART framework.

---

## Step 4: Board Wiring

**File:** `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_<driver>.c`

**Content:** Initialize the driver instance and register with upper-half.

For a concrete working example, `rzv2h_timer.c` obtains
`struct timer_lowerhalf_s *` from `rzv_gtm_timer_initialize(channel)`, checks
for `NULL`, passes it to `timer_register(devpath, lower)`, and calls
`rzv_gtm_timer_uninitialize(lower)` when registration fails. Do not generalize
that pointer/`NULL` contract to an upper-half whose registration API returns
an integer.

**Call this from the NuttX board bring-up path; keep standalone board glue
under `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/`.
PX4-only adapters remain under `boards/renesas/rdk-rzv2h/src/`.**

---

## Step 5: Build System Updates

### 5.1 Kconfig (Driver Enablement)

**File:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Kconfig`

Add:
```kconfig
menu "<Driver> (RZV2H)"

config RZV_<DRIVER>
  bool "Enable <Driver> Support"
  default n
  depends on ARCH_CHIP_R9A09G057
  ---help---
    Enable NuttX support for RZ/V2H <Driver> peripheral.
    Document the supported instances, core, pins, and target procedure here.

endmenu
```

### 5.2 Make.defs (Build Rules)

**File:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Make.defs`

Add conditional compilation:
```makefile
ifeq ($(CONFIG_RZV_<DRIVER>),y)
CHIP_CSRCS += rzv_<driver>.c
endif
```

### 5.3 Board-level Makefile

**File:** `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/Makefile`

```makefile
ifeq ($(CONFIG_RZV_<DRIVER>),y)
CSRCS += rzv2h_<driver>.c
endif
```

---

## Step 6: Sample Configuration

**Directory:** `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/configs/<driver>/`

Create a minimal defconfig for testing:

**File:** `defconfig`
```
CONFIG_ARCH_CHIP_R9A09G057=y
CONFIG_RZV_<DRIVER>=y
CONFIG_DEBUG_SYMBOLS=y
CONFIG_SYSLOG_TIMESTAMP=y
```

---

## Step 7: Validation Loop

### 7.1 Configure

```bash
# From the PX4-Autopilot repository root:
cd platforms/nuttx/NuttX/nuttx
./tools/configure.sh rdk-rzv2h:<driver>
```

If the exact config is absent, use the closest board sample in the same NuttX
tree and document the substitution.

### 7.2 Build

```bash
make -j$(nproc) 2>&1 | tee build.log
```

**Fix errors:** undefined references, missing includes, Kconfig syntax.

### 7.3 Link Check

Verify symbols resolved (no undefined references to cpg, dmac, pinmux):

```bash
grep -E "undefined reference|multiple definition" build.log
```

### 7.4 Runtime Test (on RDK-RZ/V2H board)

After the board owner approves an exact-image load procedure, load that image
and record its hash, loader/probe, core, and board revision before verifying:
- Device appears in `/dev/`
- No crash on open/read/write
- Data transfers match expected byte counts
- No stack overflow (check syslog)

**Example (UART):**
```bash
# Select the physical channel owned by the image under test.
CONSOLE_DEV=/dev/ttyS4
test -e "${CONSOLE_DEV}"
echo "test" > "${CONSOLE_DEV}"
cat "${CONSOLE_DEV}"  # or use a serial monitor
```

RDK-RZ/V2H keeps physical SCI numbering in device names; selecting a console
does not rename it to `/dev/ttyS0`. Standalone NSH target ownership is SCI4
(`/dev/ttyS4`) on CR8-0, SCI5 (`/dev/ttyS5`) on CR8-1, and SCI9
(`/dev/ttyS9`) on CM33. CR8-1 and CM33 mappings remain hardware-validation
targets until their sample configurations are aligned and tested.

The integrated PX4 CR8-0 image uses RTT0 for console/debug output instead.
Its UARTs retain payload ownership: SCI4 LiDAR, SCI5 MAVLink/QGroundControl,
SCI6 RC at 100000 8E2 with the inversion path proved, and SCI9 GPS at
115200 8N1. These checks are evidence-tier gates for the first
drone-equivalent run. Never mix text diagnostics and binary MAVLink on RTT0.

---

## Step 8: Code Review Checklist

Before pushing:

- [ ] Hardware header (`rzv_<driver>.h`) matches FSP register offsets
- [ ] ISR clears the source that raised the interrupt and defers heavy work
- [ ] Cache invalidate/clean wraps DMA (RX/TX)
- [ ] Init sequence: clock → module reset/unreset → pins (IOPORT/PFC) → IRQ → config
- [ ] Error codes propagated (not swallowed)
- [ ] `nxmutex` protects shared state; critical sections protect R-M-W
- [ ] No malloc/free in ISR
- [ ] Kconfig help text explains constraints and dependencies
- [ ] Arch `Make.defs` and board `Makefile`/`CMakeLists.txt` source selection
      agree
- [ ] Sample config compiles without errors
- [ ] Evidence tier is recorded explicitly; do not promote a claim past the strongest proof actually observed

**Cross-reference:** [Design Guidelines](../design-guidelines.md), [Code Standards](../code-standards.md)

---

## Related References

- [Design Guidelines](../design-guidelines.md) — ISR, DMAC, init sequence details
- [Code Standards](../code-standards.md) — formatting, naming, commit conventions
- [FreeRTOS-to-NuttX Mapping](./freertos-to-nuttx-mapping.md) — API substitutions
- [Reference Source Map](./reference-source-map.md) — core-specific FSP/EVK paths and exceptions

---

**Maintenance:** Update when NuttX driver interface or build system changes; track in Phase 3+ reviews.
