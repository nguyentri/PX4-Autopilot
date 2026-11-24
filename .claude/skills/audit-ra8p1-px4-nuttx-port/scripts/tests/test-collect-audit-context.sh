#!/usr/bin/env bash
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
collector="$repo_root/.claude/skills/audit-ra8p1-px4-nuttx-port/scripts/collect-audit-context.sh"
output=$("$collector" gpt "$repo_root")

require_text()
{
  local expected=$1

  if ! grep -Fq -- "$expected" <<<"$output"; then
    echo "FAIL: collector output missing: $expected" >&2
    exit 1
  fi
}

forbid_text()
{
  local unexpected=$1

  if grep -Fq -- "$unexpected" <<<"$output"; then
    echo "FAIL: collector output unexpectedly contains: $unexpected" >&2
    exit 1
  fi
}

require_text "platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/Kconfig"
require_text "refs/ra8p1/R7KA8P1KF_core0.h"
require_text "CM85 (CPU0): Cortex-M85"
require_text "CM33 (CPU1): Cortex-M33"
require_text "refs/ra8p1/R7KA8P1KF_core1.h (CM33)"
require_text "#define __CM33_REV"
require_text "#define R_CACHE_BASE"
require_text "RA_CPU_CORE_CM33"
require_text "RA8_CM85_FAMILY"
require_text "ARCH_CORTEXM85"
require_text "ARCH_CORTEXM33"
require_text "RA8P1_GROUP"
require_text "boards/renesas/evk-ra8p1-io-cm33/nuttx-config/nsh/defconfig: CM33"
forbid_text "configs/ipc-cm33/defconfig sets CM33 indicators"
require_text "hardware-header and source routing"
require_text "PX4 HAL selection"
require_text "set(CHIP \"ra8\")"
require_text "FSP module carriers for topic"
require_text "r_gpt: refs/ra8p1/ek_ra8p1/gpt/gpt_ek_ra8p1_ep/e2studio/ra/fsp/src/r_gpt"
require_text "instances of R_GPT<n>_BASE in refs/ra8p1/R7KA8P1KF_core0.h: 14"
require_text "instances of R_GPT<n>_BASE in refs/ra8p1/R7KA8P1KF_core1.h: 14"
require_text "#define R_GPT13_BASE"
require_text "BSP_PRV_VECT_ENUM(EVENT_GPT6_COUNTER_OVERFLOW,GROUP0)"
require_text "distinct RA_ELC_GPT<n> instances in platforms/nuttx/NuttX/nuttx/arch/arm/include/ra8/ra8p1_irq.h: 14"
require_text "RA_ELC_GPT0_COUNTER_OVERFLOW                 (0x187)"
require_text "mcu/ra8p1/bsp_feature.h ("
require_text "BSP_FEATURE_GPT_32BIT_CHANNEL_MASK"
require_text "ELC_EVENT_GPT0_COUNTER_OVERFLOW         = (0x187)"
forbid_text "bsp_elc.h under refs/ra8p1 is empty"
require_text "RA8P1 parameterized register-offset and channel-macro candidates"
require_text "R_GPT32_CH_BASE(ch)"
require_text "raw RA8 base-plus-literal candidates"
require_text "NuttX drivers and public contracts"
require_text "NuttX applications, examples, and validation"
require_text "shared-code blast radius (RA8E1)"
require_text "boards/renesas/evk-ra8p1/src/timer_config.cpp"

echo "PASS: RA8P1 audit collector mandatory anchors"
