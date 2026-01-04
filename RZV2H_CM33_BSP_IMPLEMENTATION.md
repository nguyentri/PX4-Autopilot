# RZV2H CM33 NuttX BSP Implementation Guide

## Overview

This document describes the NuttX BSP implementation for the Renesas RZV2H MCU CM33 core. The CM33 is a Cortex-M33 processor with TrustZone, FPU, and DSP extensions used for real-time control and security functions in the RZV2H multi-core system.

## Architecture Summary

### RZV2H Multi-Core System
- **CA55 (Cortex-A55)**: Main application processor (Linux)
- **CR8 (Cortex-R8)**: Real-time safety processor
- **CM33 (Cortex-M33)**: Security and real-time control
  - ARMv8-M architecture
  - Optional FPU and DSP
  - TrustZone support
  - 128KB ATCM (Instruction TCM)
  - 128KB BTCM (Data TCM)
  - 512KB System RAM

### Memory Map (CM33)

```
0x00000000 - 0x0001FFFF  ATCM (128KB)     - Vectors, code
0x20000000 - 0x2001FFFF  BTCM (128KB)     - Stack, critical data
0x22000000 - 0x2207FFFF  System RAM (512KB) - .data, .bss, heap
0x10000000 - 0x1FFFFFFF  Peripherals
0x40000000+              External memory (if configured)
```

## Implementation Files

### 1. Core Startup and Interrupt Handling

#### `/arch/arm/src/rzv/rzv_start_cm33.c`
CM33-specific boot sequence:
- **`__start()`**: Reset entry point
  - Disables interrupts
  - Calls `rzv_cm33_lowsetup()`
  - Copies .data from Flash to RAM (if running from Flash)
  - Clears .bss section
  - Calls `rzv_board_initialize()`
  - Starts NuttX with `nx_start()`

- **`rzv_cm33_cpu_init()`**: CPU initialization
  - Sets vector table base (VTOR)
  - Configures SCR, CCR registers
  - Enables instruction/data caches
  - Enables FPU if configured

- **`rzv_cm33_clock_init()`**: Clock initialization
  - Verifies PLL lock status
  - Enables CM33-specific peripheral clocks

#### `/arch/arm/src/rzv/rzv_start_cm33.h`
Header file declaring CM33 startup functions.

#### `/arch/arm/src/rzv/rzv_irq_cm33.c`
CM33 interrupt handling:
- **`up_irqinitialize()`**: Initialize NVIC and ICU
- **`up_enable_irq()` / `up_disable_irq()`**: IRQ control
- **`up_prioritize_irq()`**: Set interrupt priority
- **Exception handlers**: Hard fault, bus fault, usage fault, etc.

#### `/arch/arm/src/rzv/rzv_icu_cm33.c`
CM33 Interrupt Control Unit driver (already exists, reviewed).

### 2. Hardware Register Definitions

#### `/arch/arm/src/rzv/hardware/rzv_intc_gic.h`
GIC-400 register definitions (already exists, verified for CM33 compatibility).

### 3. Board Configuration

#### `/boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cm33_nuttx.ld`
Linker script for CM33:
- ATCM: Vectors and code
- BTCM: Stack (16KB default)
- SRAM: .data, .bss, heap

Memory layout:
```
MEMORY {
    atcm (rx)  : ORIGIN = 0x00000000, LENGTH = 128K
    btcm (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
    sram (rwx) : ORIGIN = 0x22000000, LENGTH = 512K
}
```

#### `/boards/arm/rzv/rdk-rzv2h/configs/nsh-cm33/defconfig`
CM33-specific configuration:
```
CONFIG_RZV2H_BUILD_CM33=y
CONFIG_ARCH_CORTEXM33=y
CONFIG_ARCH_FPU=y
CONFIG_ARMV8M_ICACHE=y
CONFIG_ARMV8M_DCACHE=y
CONFIG_RAM_START=0x22000000
CONFIG_RAM_SIZE=524288
```

### 4. Build System Integration

#### `/arch/arm/src/rzv/Make.defs`
Updated to conditionally include CM33 files:
```makefile
ifeq ($(CONFIG_RZV2H_BUILD_CM33),y)
  # Cortex-M33 (ARMv8-M) files
  include armv8-m/Make.defs
  CHIP_CSRCS += rzv_start_cm33.c
  CHIP_CSRCS += rzv_irq_cm33.c
  CHIP_CSRCS += rzv_icu_cm33.c
else
  # Cortex-R8 (ARMv7-R) files
  include armv7-r/Make.defs
  CHIP_CSRCS += rzv_start.c
  CHIP_CSRCS += rzv_irq.c
  CHIP_CSRCS += rzv_icu.c
endif
```

#### `/arch/arm/src/rzv/Kconfig`
Added CM33 configuration options:
```kconfig
config RZV2H_BUILD_CM33
    bool "Build for CM33 core"
    default n
    depends on !RZV2H_BUILD_CR8_0 && !RZV2H_BUILD_CR8_1
    help
      Build for the CM33 core of the RZV2H.
      Uses Cortex-M33 (ARMv8-M) architecture.

if RZV2H_BUILD_CM33
  # CM33-specific memory configuration
  config RZV2H_CM33_ATCM_SIZE
  config RZV2H_CM33_BTCM_SIZE
  config RZV2H_CM33_SRAM_BASE
  config RZV2H_CM33_SRAM_SIZE
endif
```

## Build Instructions

### Configure for CM33

```bash
cd ~/px4_ra8/PX4-Autopilot/platforms/nuttx/NuttX/nuttx
./tools/configure.sh rdk-rzv2h:nsh-cm33
```

### Build

```bash
make
```

### Output Files

- `nuttx` - ELF binary
- `nuttx.bin` - Raw binary for flashing
- `nuttx.hex` - Intel HEX format

## Key Differences from CR8 Implementation

| Feature | CR8 (Cortex-R8) | CM33 (Cortex-M33) |
|---------|-----------------|-------------------|
| Architecture | ARMv7-R | ARMv8-M |
| Interrupt Controller | GICv2 | NVIC |
| Memory | No TCM, uses RAM | ATCM, BTCM, RAM |
| Startup | `rzv_start.c` | `rzv_start_cm33.c` |
| IRQ Handling | `rzv_irq.c` | `rzv_irq_cm33.c` |
| Cache | L1 I/D cache | Optional I/D cache |
| Security | No TrustZone | TrustZone support |

## Peripheral Driver Compatibility

Most peripheral drivers are shared between CM33 and CR8:
- **Serial (SCI/SCIF)**: Compatible
- **I2C (RIIC)**: Compatible
- **SPI**: Compatible
- **GPT (PWM)**: Compatible
- **GTM (Timer)**: Compatible
- **ADC**: Compatible
- **DMA**: May need CM33-specific configuration

## Debug and Development

### RTT (Real-Time Transfer) Support
The CM33 configuration includes Segger RTT for debug output:
```
CONFIG_SEGGER_RTT=y
CONFIG_SYSLOG_RTT=y
```

### Debug Symbols
Full debug symbols are enabled by default:
```
CONFIG_DEBUG_SYMBOLS=y
CONFIG_DEBUG_SYMBOLS_LEVEL="-g3"
CONFIG_DEBUG_OPTLEVEL="-O0"
```

### Console
SCI1 UART is configured as the primary console:
- Baud rate: 115200
- Data bits: 8
- Parity: None
- Stop bits: 1

## Boot Sequence

1. **Hardware Reset**
   - CM33 loads initial SP from vector table[0]
   - CM33 loads Reset_Handler address from vector table[1]
   - Jumps to `__start()`

2. **Early Initialization** (`rzv_cm33_lowsetup()`)
   - Configure CPU (VTOR, CCR, SCR)
   - Enable caches
   - Enable FPU
   - Initialize clocks

3. **Memory Initialization**
   - Copy .data from Flash to RAM (if needed)
   - Clear .bss section

4. **Board Initialization** (`rzv_board_initialize()`)
   - GPIO security setup
   - Serial pin configuration
   - LED initialization

5. **IRQ Initialization** (`up_irqinitialize()`)
   - Initialize NVIC
   - Initialize ICU
   - Enable interrupts

6. **Start NuttX** (`nx_start()`)
   - Create idle task
   - Start scheduler
   - Run user applications

## Troubleshooting

### Build Errors

**Error: "armv8-m/Make.defs not found"**
- Solution: Ensure NuttX ARM architecture files include ARMv8-M support
- Verify `arch/arm/src/armv8-m` directory exists

**Error: "undefined reference to `arm_*` functions"**
- Solution: Verify correct architecture is selected in defconfig
- Check that `CONFIG_ARCH_CORTEXM33=y` is set

### Runtime Issues

**System doesn't boot**
- Check linker script memory regions match hardware
- Verify vector table at 0x00000000 in ATCM
- Ensure stack pointer is valid (in BTCM)

**Hard fault on startup**
- Check VTOR setting
- Verify FPU enable sequence
- Check stack alignment (must be 8-byte aligned)

**Serial output not working**
- Verify SCI1 pin configuration
- Check baud rate settings
- Ensure clock to SCI1 is enabled

## Future Enhancements

1. **TrustZone Support**
   - Secure/Non-secure world configuration
   - SAU (Security Attribution Unit) setup
   - Secure peripherals

2. **Power Management**
   - Low-power modes
   - Clock gating
   - Dynamic voltage scaling

3. **AMP (Asymmetric Multi-Processing)**
   - Inter-core communication with CA55/CR8
   - Shared memory regions
   - Message passing

4. **DMA Optimization**
   - CM33-specific DMA configuration
   - TCM-aware DMA transfers

## References

- **Renesas RZV2H User Manual**: Hardware specifications
- **Renesas FSP**: Example implementations
- **ARM Cortex-M33 TRM**: Processor architecture
- **NuttX Documentation**: RTOS internals

## Contact and Support

For questions or issues:
- NuttX Mailing List: https://nuttx.apache.org/community/
- Renesas Support: https://en-support.renesas.com/

---
**Last Updated**: January 4, 2026
**Author**: NuttX BSP Team
**Version**: 1.0
