# RZV2H CM33 BSP - Kconfig and Build System Reference

## Required Kconfig Symbols

### Core CM33 Configuration

Add these to your `arch/arm/src/rzv/Kconfig`:

```kconfig
config RZV2H_BUILD_CM33
    bool "Build for CM33 core"
    default n
    depends on !RZV2H_BUILD_CR8_0 && !RZV2H_BUILD_CR8_1
    help
      Build for the CM33 core of the RZV2H.
      This core is used for TrustZone security features and real-time control.
      Uses Cortex-M33 (ARMv8-M) architecture with optional FPU and DSP.

if RZV2H_BUILD_CM33

config ARCH_CORTEXM33_SELECTED
   bool
   default y
   select ARCH_CORTEXM33
   select ARCH_HAVE_FPU
   select ARCH_HAVE_DPFPU
   select ARMV8M_HAVE_ICACHE
   select ARMV8M_HAVE_DCACHE
   select ARM_HAVE_MPU_UNIFIED

config RZV2H_CM33_ATCM_SIZE
   int "CM33 ATCM size (KB)"
   default 128
   help
     Size of CM33 Tightly-Coupled Memory A (ATCM) in KB.
     RZV2H CM33 has 128KB ATCM at 0x00000000.

config RZV2H_CM33_BTCM_SIZE
   int "CM33 BTCM size (KB)"
   default 128
   help
     Size of CM33 Tightly-Coupled Memory B (BTCM) in KB.
     RZV2H CM33 has 128KB BTCM at 0x20000000.

config RZV2H_CM33_SRAM_BASE
   hex "CM33 System RAM base address"
   default 0x22000000
   help
     Base address of CM33 system RAM.
     RZV2H allocates 512KB RAM for CM33 at 0x22000000.

config RZV2H_CM33_SRAM_SIZE
   int "CM33 System RAM size (KB)"
   default 512
   help
     Size of CM33 system RAM in KB.

endif # RZV2H_BUILD_CM33
```

## Make.defs Changes

Add to `arch/arm/src/rzv/Make.defs`:

```makefile
# Common ARM files - different for CM33 vs CR8
ifeq ($(CONFIG_RZV2H_BUILD_CM33),y)
# Cortex-M33 (ARMv8-M) files
include armv8-m/Make.defs
else
# Cortex-R8 (ARMv7-R) files
include armv7-r/Make.defs
endif

# Required RZV files - core-specific startup and IRQ handling
ifeq ($(CONFIG_RZV2H_BUILD_CM33),y)
# CM33-specific startup and IRQ files
CHIP_CSRCS += rzv_start_cm33.c
CHIP_CSRCS += rzv_irq_cm33.c
CHIP_CSRCS += rzv_icu_cm33.c
else
# CR8-specific startup and IRQ files (default)
CHIP_CSRCS += rzv_start.c
CHIP_CSRCS += rzv_irq.c
CHIP_CSRCS += rzv_icu.c
endif
```

## Board Make.defs

Update `boards/arm/rzv/rdk-rzv2h/scripts/Make.defs`:

```makefile
ifeq ($(CONFIG_RZV2H_BUILD_CM33),y)
  LDSCRIPT = rdk-rzv2h_cm33_nuttx.ld
else ifeq ($(CONFIG_RZV2H_BUILD_CR8_1),y)
  LDSCRIPT = rdk-rzv2h_cr8_1.ld
else
  LDSCRIPT = rdk-rzv2h_cr8_0.ld
endif
```

## CMakeLists.txt (if using CMake)

Add to `arch/arm/src/rzv/CMakeLists.txt`:

```cmake
if(CONFIG_RZV2H_BUILD_CM33)
  # CM33-specific files
  list(APPEND SRCS
    rzv_start_cm33.c
    rzv_irq_cm33.c
    rzv_icu_cm33.c
  )

  # Include ARMv8-M common files
  include(armv8-m/CMakeLists.txt)
else()
  # CR8-specific files
  list(APPEND SRCS
    rzv_start.c
    rzv_irq.c
    rzv_icu.c
  )

  # Include ARMv7-R common files
  include(armv7-r/CMakeLists.txt)
endif()
```

## Defconfig Template

Minimum required configuration for CM33 (`configs/nsh-cm33/defconfig`):

```
# Architecture
CONFIG_ARCH="arm"
CONFIG_ARCH_CHIP="rzv"
CONFIG_ARCH_CHIP_RZV=y
CONFIG_ARCH_CHIP_R9A09G057=y

# Core Selection
CONFIG_RZV2H_BUILD_CM33=y

# Cortex-M33
CONFIG_ARCH_CORTEXM33=y
CONFIG_ARCH_FPU=y
CONFIG_ARCH_HAVE_FPU=y
CONFIG_ARCH_HAVE_DPFPU=y

# ARMv8-M
CONFIG_ARMV8M_ICACHE=y
CONFIG_ARMV8M_DCACHE=y
CONFIG_ARM_HAVE_MPU_UNIFIED=y

# Memory
CONFIG_RAM_START=0x22000000
CONFIG_RAM_SIZE=524288

# CM33-specific memory
CONFIG_RZV2H_CM33_ATCM_SIZE=128
CONFIG_RZV2H_CM33_BTCM_SIZE=128
CONFIG_RZV2H_CM33_SRAM_BASE=0x22000000
CONFIG_RZV2H_CM33_SRAM_SIZE=512

# Board
CONFIG_ARCH_BOARD="rdk-rzv2h"
CONFIG_ARCH_BOARD_RDK_RZV2H=y
```

## Conditional Compilation Macros

Use these in source code for CM33-specific logic:

```c
#ifdef CONFIG_RZV2H_BUILD_CM33
  /* CM33-specific code */
  #include "arm_internal.h"  /* ARMv8-M */
  #include "nvic.h"          /* NVIC instead of GIC */
#else
  /* CR8-specific code */
  #include "arm_internal.h"  /* ARMv7-R */
  #include "gic.h"           /* GICv2 */
#endif
```

## File Structure Summary

```
arch/arm/src/rzv/
├── rzv_start.c              # CR8 startup
├── rzv_start_cm33.c         # CM33 startup (NEW)
├── rzv_start_cm33.h         # CM33 startup header (NEW)
├── rzv_irq.c                # CR8 IRQ handling
├── rzv_irq_cm33.c           # CM33 IRQ handling (NEW)
├── rzv_icu.c                # CR8 ICU driver
├── rzv_icu_cm33.c           # CM33 ICU driver (already exists)
├── rzv_icu_cm33.h           # CM33 ICU header (already exists)
├── Make.defs                # Modified for CM33
├── Kconfig                  # Modified for CM33
└── hardware/
    └── rzv_intc_gic.h       # Verified for CM33

boards/arm/rzv/rdk-rzv2h/
├── scripts/
│   ├── rdk-rzv2h_cm33_nuttx.ld  # CM33 linker script (NEW)
│   └── Make.defs                # Modified for CM33
└── configs/
    └── nsh-cm33/
        └── defconfig            # Modified for CM33
```

## Build Commands

### Configure for CM33
```bash
cd nuttx
./tools/configure.sh rdk-rzv2h:nsh-cm33
```

### Configure for CR8_0 (default)
```bash
cd nuttx
./tools/configure.sh rdk-rzv2h:nsh
```

### Build
```bash
make
```

### Clean
```bash
make distclean
```

### Menuconfig (to modify configuration)
```bash
make menuconfig
```

## Configuration Verification

After configuration, verify these settings in `.config`:

```bash
grep -E "CONFIG_RZV2H_BUILD_CM33|CONFIG_ARCH_CORTEXM33|CONFIG_RAM_START" .config
```

Expected output:
```
CONFIG_RZV2H_BUILD_CM33=y
CONFIG_ARCH_CORTEXM33=y
CONFIG_RAM_START=0x22000000
```

## Mutual Exclusion

The build system ensures only one core target is selected:

```kconfig
config RZV2H_BUILD_CR8_0
    depends on !RZV2H_BUILD_CM33 && !RZV2H_BUILD_CR8_1

config RZV2H_BUILD_CR8_1
    depends on !RZV2H_BUILD_CM33 && !RZV2H_BUILD_CR8_0

config RZV2H_BUILD_CM33
    depends on !RZV2H_BUILD_CR8_0 && !RZV2H_BUILD_CR8_1
```

## Troubleshooting

### Error: "Multiple core configurations selected"
**Cause**: Conflicting CONFIG_RZV2H_BUILD_* symbols
**Solution**:
```bash
make distclean
./tools/configure.sh rdk-rzv2h:nsh-cm33
```

### Error: "armv8-m/Make.defs not found"
**Cause**: Missing ARMv8-M support in NuttX
**Solution**: Ensure NuttX version includes ARMv8-M support (NuttX 10.0+)

### Error: "Undefined reference to `up_*` functions"
**Cause**: Incorrect architecture selection
**Solution**: Verify `.config` has `CONFIG_ARCH_CORTEXM33=y`

---
**Note**: All Kconfig symbols with `RZV2H_BUILD_*` are mutually exclusive. Only one can be enabled at a time.
