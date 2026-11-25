# Cortex-R52 CPU flags matching NuttX armv8-r/Toolchain.defs
# ARMv8-R AArch32 with the double-precision FPU, 32 D registers and Advanced
# SIMD (CONFIG_ARCH_FPU, CONFIG_ARCH_DPFPU, CONFIG_ARM_DPFPU32 default y),
# hard float ABI.  The PX4 defconfig must keep those options so that PX4 and
# the NuttX libraries share one ABI and the context switch saves d0-d31.
# Cortex-R runs in ARM mode here, as NuttX builds it: no -mthumb.

set(cpu_flags "-mcpu=cortex-r52 -mfpu=neon-fp-armv8 -mfloat-abi=hard")

# GCC 13.2 (Arm GNU 13.2.Rel1) stops with "unrecognizable insn" when it
# auto-vectorizes some EKF2 code for NEON.  The ABI flags above stay identical
# to the NuttX build; only the auto-vectorizer is turned off for PX4 code.
set(cpu_flags "${cpu_flags} -fno-tree-vectorize")

set(CMAKE_C_FLAGS "${cpu_flags}" CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS "${cpu_flags}" CACHE STRING "" FORCE)
set(CMAKE_ASM_FLAGS "${cpu_flags} -D__ASSEMBLY__" CACHE STRING "" FORCE)
