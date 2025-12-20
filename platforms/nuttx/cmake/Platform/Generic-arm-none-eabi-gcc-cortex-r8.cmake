
# Cortex-R8 CPU flags matching NuttX armv7-r/Toolchain.defs
# ARMv7-R architecture with VFPv3-D16 FPU, hard float ABI
# Note: Cortex-R runs in ARM mode (not Thumb), so NO -mthumb flag

# CPU: Cortex-R8 (ARMv7-R architecture)
# FPU: VFPv3-D16 (16 double-precision registers)
# ABI: Hard float (hardware FP instructions, FP args in FP registers)
set(cpu_flags "-mcpu=cortex-r8 -mfpu=vfpv3-d16 -mfloat-abi=hard")

set(CMAKE_C_FLAGS "${cpu_flags}" CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS "${cpu_flags}" CACHE STRING "" FORCE)
set(CMAKE_ASM_FLAGS "${cpu_flags} -D__ASSEMBLY__" CACHE STRING "" FORCE)
