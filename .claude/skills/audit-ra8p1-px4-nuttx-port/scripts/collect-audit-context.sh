#!/usr/bin/env bash
# Read-only context collector for an RA8P1 PX4/NuttX port audit.
# Prints mandatory anchors, the CM85/CM33 core-selection chain, defconfig
# core-selection candidates, header/HAL routing, the FSP samples that carry
# modules matching the topic, register-macro candidates and topic hits per layer.
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "usage: $0 <topic> [repository-root]" >&2
  exit 2
fi

topic=$1
repo_root=${2:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}
reference_root="refs/ra8p1"
device_header="$reference_root/R7KA8P1KF_core0.h"
cm33_header="$reference_root/R7KA8P1KF_core1.h"
nuttx_root="platforms/nuttx/NuttX/nuttx"
nuttx_arch_root="$nuttx_root/arch/arm/src/ra8"
nuttx_irq_root="$nuttx_root/arch/arm/include/ra8"
nuttx_board_root="$nuttx_root/boards/arm/ra8/evk-ra8p1"
nuttx_driver_root="$nuttx_root/drivers"
nuttx_include_root="$nuttx_root/include/nuttx"
nuttx_apps_root="platforms/nuttx/NuttX/apps"
px4_hal_root="platforms/nuttx/src/px4/renesas/ra8"
px4_cm85_board="boards/renesas/evk-ra8p1"
px4_cm33_board="boards/renesas/evk-ra8p1-io-cm33"


if [ ! -d "$repo_root/$reference_root" ]; then
  echo "error: RA8P1 reference tree $reference_root not found under $repo_root" >&2
  exit 1
fi

mandatory_anchors=(
  "$device_header"
  "$cm33_header"
  "$reference_root/ek_ra8p1"
  "$reference_root/evk_ra8p1_dual_core"
  "$nuttx_root/arch/arm/Kconfig"
  "$nuttx_arch_root/Kconfig"
  "$nuttx_arch_root/Make.defs"
  "$nuttx_arch_root/CMakeLists.txt"
  "$nuttx_arch_root/hardware/ra_memorymap.h"
  "$nuttx_arch_root/hardware/ra8p1"
  "$nuttx_irq_root/ra8p1_irq.h"
  "$nuttx_board_root/Kconfig"
  "$nuttx_board_root/configs/nsh/defconfig"
  "$nuttx_board_root/configs/ipc-cm85/defconfig"
  "$nuttx_board_root/configs/ipc-cm33/defconfig"
  "$nuttx_board_root/include/board.h"
  "$nuttx_driver_root/Kconfig"
  "$nuttx_apps_root/Kconfig"
  "$px4_hal_root/CMakeLists.txt"
  "platforms/nuttx/cmake/px4_impl_os.cmake"
  "$px4_cm85_board/default.px4board"
  "$px4_cm85_board/nuttx-config/nsh/defconfig"
  "$px4_cm85_board/nuttx-config/scripts/script.ld"
  "$px4_cm33_board/default.px4board"
  "$px4_cm33_board/nuttx-config/nsh/defconfig"
  "$px4_cm33_board/nuttx-config/scripts/script.ld"
  "docs/renesas"
  "plans"
)

cd "$repo_root"

missing_anchor=0
for anchor in "${mandatory_anchors[@]}"; do
  if [ ! -e "$anchor" ]; then
    echo "finding: mandatory audit anchor missing: $anchor" >&2
    missing_anchor=1
  fi
done

if [ "$missing_anchor" -ne 0 ]; then
  exit 1
fi

# Recursive grep with capped output; fails the script only on grep errors
# (status > 1). GNU grep is used because ripgrep is not guaranteed on PATH.
# Generated build outputs and duplicate IDE project trees are skipped.
grep_capped()
{
  local limit=$1
  local grep_status
  shift

  set +e
  grep -r -I -H --exclude-dir=Debug --exclude-dir=iar --exclude-dir=keil "$@" |
    sed -n "1,${limit}p"
  grep_status=${PIPESTATUS[0]}
  set -e

  if [ "$grep_status" -gt 1 ]; then
    exit "$grep_status"
  fi
  return "$grep_status"
}

list_topic_files()
{
  local limit=$1
  shift
  grep_capped "$limit" -l -i -F -- "$topic" "$@" || true
}

echo "topic: $topic"
echo "repository: $repo_root"
echo
echo "mandatory RA8P1 audit anchors"
printf '%s\n' "${mandatory_anchors[@]}"
echo
echo "RA8P1 core profiles"
echo "CM85 (CPU0): Cortex-M85 / Armv8.1-M, RA_CPU_CORE_CM85, RA8_CM85_FAMILY"
echo "CM33 (CPU1): Cortex-M33 / Armv8-M, RA_CPU_CORE_CM33, RA8_CM33_FAMILY"
echo "device headers: $device_header (CM85) and $cm33_header (CM33); take each core's facts from its own header"
for core_header in "$device_header" "$cm33_header"; do
  echo "core config in $core_header:"
  grep_capped 16 -n -E -e '^[[:space:]]*#define[[:space:]]+__(CM85_REV|CM33_REV|FPU_DP|DSP_PRESENT|ICACHE_PRESENT|DCACHE_PRESENT|PMU_PRESENT|SAUREGION_PRESENT|NVIC_PRIO_BITS)\b' "$core_header" || true
done
echo "peripheral bases present in only one header:"
# diff exits 1 when the sets differ; capture its output instead of failing the pipeline.
base_diff=$(diff <(grep -E '#define[[:space:]]+R_[A-Z0-9_]+_BASE[[:space:]]' "$device_header" | sort) \
  <(grep -E '#define[[:space:]]+R_[A-Z0-9_]+_BASE[[:space:]]' "$cm33_header" | sort) | grep -E '^[<>]' || true)
printf '%s\n' "${base_diff:-none}"
echo
echo "core-selection chain in NuttX Kconfig"
grep_capped 80 -n -E \
  -e '^[[:space:]]*(menu)?config (ARCH_CHIP_RA8|ARCH_CHIP_R7KA8P1KFLCAC|ARCH_CHIP_R7JA8P1JRLSAJ|RA8P1_GROUP|RA8E1_GROUP|RA_CPU_CORE|RA_CPU_CORE_CM85|RA_CPU_CORE_CM33|RA8_CM85_FAMILY|RA8_CM33_FAMILY)$' \
  -e '^[[:space:]]*select (ARCH_CORTEXM85|ARCH_CORTEXM33|RA8_CM85_FAMILY|RA8_CM33_FAMILY|RA8P1_GROUP)' \
  -e '^[[:space:]]*default [01] if RA_CPU_CORE_CM(85|33)' \
  "$nuttx_root/arch/arm/Kconfig" "$nuttx_arch_root/Kconfig" || true
echo
echo "core selection in defconfigs (text only; confirm in the generated .config)"
defconfigs=()
while IFS= read -r config_file; do
  defconfigs+=("$config_file")
done < <(ls "$nuttx_board_root"/configs/*/defconfig \
  "$px4_cm85_board"/nuttx-config/*/defconfig \
  "$px4_cm33_board"/nuttx-config/*/defconfig 2>/dev/null)

for config_file in "${defconfigs[@]}"; do
  core="CM85 (choice default)"
  if grep -q '^CONFIG_RA_CPU_CORE_CM33=y' "$config_file"; then
    core="CM33 (RA_CPU_CORE_CM33=y)"
  elif grep -q '^CONFIG_RA_CPU_CORE_CM85=y' "$config_file"; then
    core="CM85 (RA_CPU_CORE_CM85=y)"
  fi
  echo "$config_file: $core"

  if grep -Eq '^CONFIG_(ARCH_CORTEXM33=y|RA_CPU_CORE=1)$' "$config_file" &&
     ! grep -q '^CONFIG_RA_CPU_CORE_CM33=y' "$config_file"; then
    echo "candidate: $config_file sets CM33 indicators (ARCH_CORTEXM33/RA_CPU_CORE=1) without CONFIG_RA_CPU_CORE_CM33=y"
  fi
  if grep -Eq '^CONFIG_RA_CPU_CORE_CM(85|33)=n$' "$config_file"; then
    echo "candidate: $config_file uses non-standard '=n' for a core choice member"
  fi
done
echo
echo "hardware-header and source routing"
grep_capped 60 -n -E -e 'hardware(/|\$\(DELIM\))ra8(e1|p1)' -e 'CONFIG_RA8(E1|P1)_GROUP' \
  "$nuttx_arch_root/Make.defs" "$nuttx_arch_root/CMakeLists.txt" \
  "$nuttx_arch_root/hardware/ra_memorymap.h" "$nuttx_arch_root/hardware/ra_hardware.h" \
  "$nuttx_arch_root/chip.h" || true
echo
echo "PX4 HAL selection (chip -> platforms/nuttx/src/px4/renesas/<chip>)"
grep_capped 12 -n -E -A2 -e 'R7KA8P1KFLCAC|R7FA8E1AFDCFB' platforms/nuttx/cmake/px4_impl_os.cmake || true
grep_capped 20 -n -e 'add_subdirectory' "$px4_hal_root/CMakeLists.txt" || true
echo
echo "FSP module carriers for topic"
topic_key=$(printf '%s' "$topic" | tr '[:upper:]-' '[:lower:]_' | sed -E 's/^(ra_|r_)//; s/_b(_|$)/\1/g; s/_//g')
module_found=0
while IFS= read -r module_dir; do
  module_name=${module_dir##*/}
  module_key=$(printf '%s' "$module_name" | sed -E 's/^r_//; s/_b(_|$)/\1/g; s/_//g')
  if [ -n "$topic_key" ] && [[ "$module_key" == *"$topic_key"* ]]; then
    echo "$module_name: $module_dir"
    module_found=1
  fi
done < <(find "$reference_root" -type d -path '*/ra/fsp/src/r_*' -prune \
  -not -path '*/Debug/*' -not -path '*/iar/*' -not -path '*/keil/*' | sort)
if [ "$module_found" -eq 0 ]; then
  echo "note: no FSP r_<module> directory matches '$topic'; record the FSP driver layer as unavailable or search by module name"
fi
echo
echo "device header matches (first lines)"
grep_capped 40 -n -i -F -- "$topic" "$device_header" || echo "note: '$topic' not found in $device_header"
echo
echo "hardware-fact parity: device-header instances (count, base, struct type)"
# Match both the literal IP name (ADC_B -> R_ADC_B0_BASE) and the reduced key (SCI_B -> R_SCI0_BASE).
ip_raw=$(printf '%s' "$topic" | tr '[:lower:]-' '[:upper:]_' | sed -E 's/^(RA_|R_)//')
ip_short=$(printf '%s' "$topic_key" | tr '[:lower:]' '[:upper:]')
ip_key="(${ip_raw}|${ip_short})"
[ "$ip_raw" = "$ip_short" ] && ip_key=$ip_short
instance_count=$(grep -c -E "#define[[:space:]]+R_${ip_key}[0-9]*_BASE\\b" "$device_header" || true)
echo "instances of R_${ip_key}<n>_BASE in $device_header: ${instance_count:-0}"
cm33_instance_count=$(grep -c -E "#define[[:space:]]+R_${ip_key}[0-9]*_BASE\\b" "$cm33_header" || true)
echo "instances of R_${ip_key}<n>_BASE in $cm33_header: ${cm33_instance_count:-0}"
if [ "${instance_count:-0}" != "${cm33_instance_count:-0}" ]; then
  echo "candidate: CM85 and CM33 headers disagree on R_${ip_key}<n> instance count"
fi
grep_capped 32 -n -E -e "#define[[:space:]]+R_${ip_key}[0-9]*(_BASE\\b|[[:space:]]+\\(\\(R_)" "$device_header" || true
echo
echo "hardware-fact parity: per-sample vector (IELSR slot) assignments from ra_gen/vector_data.c"
vector_files=()
while IFS= read -r vector_file; do
  vector_files+=("$vector_file")
done < <(find "$reference_root" -path '*/ra_gen/vector_data.c' -not -path '*/Debug/*' | sort)
if [ "${#vector_files[@]}" -gt 0 ]; then
  grep_capped 40 -n -E -e "EVENT_${ip_key}[0-9]*_" "${vector_files[@]}" || \
    echo "note: no sample assigns an EVENT_${ip_key}<n>_* vector; slot assignment is NuttX-only"
fi
echo
echo "hardware-fact parity: NuttX ICU event numbers (RA8P1 vs RA8E1 group)"
for irq_header in "$nuttx_irq_root/ra8p1_irq.h" "$nuttx_irq_root/ra8e1_irq.h"; do
  event_instances=$(grep -o -E "RA_ELC_${ip_key}[0-9]+_" "$irq_header" | sort -u | wc -l || true)
  echo "distinct RA_ELC_${ip_key}<n> instances in $irq_header: $event_instances"
done
grep_capped 16 -n -E -e "#define[[:space:]]+RA_ELC_${ip_key}0?_" "$nuttx_irq_root/ra8p1_irq.h" "$nuttx_irq_root/ra8e1_irq.h" || \
  echo "note: no RA_ELC_${ip_key}* event in the RA8 IRQ headers"
echo
echo "hardware-fact parity: FSP feature/event tables (bsp_feature.h, bsp_elc.h)"
# Every sample carries the same tables; report the first populated copy of each.
for table_name in bsp_feature.h bsp_elc.h; do
  table_file=$(find "$reference_root" -name "$table_name" -path '*/e2studio/*/mcu/ra8p1/*' -size +0 2>/dev/null | sort | head -n 1)
  if [ -z "$table_file" ]; then
    echo "gap: no populated bsp/mcu/ra8p1 $table_name under $reference_root; cite the hardware manual"
    continue
  fi
  echo "present: $table_file ($(wc -l <"$table_file") lines)"
  if [ "$table_name" = bsp_feature.h ]; then
    grep_capped 16 -n -E -e "BSP_FEATURE_${ip_key}_" "$table_file" || \
      echo "note: no BSP_FEATURE_${ip_key}_* entry in $table_name"
  else
    grep_capped 16 -n -E -e "ELC_(EVENT|PERIPHERAL)_${ip_key}" "$table_file" || \
      echo "note: no ELC_EVENT/ELC_PERIPHERAL entry for ${ip_key} in $table_name"
  fi
done
echo
echo "RA8P1 parameterized register-offset and channel-macro candidates"
macro_files=()
while IFS= read -r header_file; do
  macro_files+=("$header_file")
done < <(grep -r -l -i -F -- "$topic" "$nuttx_arch_root/hardware/ra8p1" || true)
if [ "${#macro_files[@]}" -eq 0 ]; then
  macro_files=("$nuttx_arch_root/hardware/ra8p1")
fi
if ! grep_capped 160 -n -E \
  -e '#define[[:space:]]+R_[A-Z0-9_]+_OFFSET\([[:space:]]*[[:alpha:]_][[:alnum:]_]*([[:space:]]*,[[:space:]]*[[:alpha:]_][[:alnum:]_]*)*[[:space:]]*\)' \
  -e '#define[[:space:]]+R_[A-Z0-9_]+_CH_BASE\(' \
  -e 'R_[A-Z0-9_]+##[[:alpha:]_][[:alnum:]_]*##_BASE' \
  "${macro_files[@]}"; then
  echo "finding: no parameterized RA8P1 register/channel macro candidate found" >&2
fi
echo
echo "raw RA8 base-plus-literal candidates outside hardware headers"
grep_capped 120 -n -E --exclude-dir=hardware \
  -e 'R_[A-Z0-9_]+_BASE[[:space:]]*\+[[:space:]]*0[xX][0-9A-Fa-f]+' \
  "$nuttx_arch_root" "$nuttx_board_root" "$px4_hal_root" \
  "$px4_cm85_board" "$px4_cm33_board" || true
echo
echo "FSP references (e2studio and dual-core sources)"
list_topic_files 80 "$reference_root"
echo
echo "NuttX RA8 arch lower-half and headers"
list_topic_files 100 "$nuttx_arch_root" "$nuttx_irq_root"
echo
echo "NuttX evk-ra8p1 board glue and example configs"
list_topic_files 100 "$nuttx_board_root"
echo
echo "NuttX drivers and public contracts"
list_topic_files 100 "$nuttx_driver_root" "$nuttx_include_root"
echo
echo "NuttX applications, examples, and validation"
list_topic_files 100 "$nuttx_apps_root"
echo
echo "PX4 RA8 HAL and RA8P1 boards"
list_topic_files 100 "$px4_hal_root" "platforms/nuttx/src/px4/renesas/ra8p1" \
  "$px4_cm85_board" "$px4_cm33_board"
echo
echo "shared-code blast radius (RA8E1)"
list_topic_files 60 "boards/renesas/fpb-ra8e1" "$nuttx_root/boards/arm/ra8/fpb-ra8e1" \
  "$nuttx_arch_root/hardware/ra8e1"
echo
echo "plans and documentation"
list_topic_files 100 "docs/renesas" "plans"
echo
echo "configuration and build anchors"
grep_capped 120 -n -i -F -- "$topic" \
  "$px4_cm85_board" "$px4_cm33_board" \
  "$nuttx_arch_root/Kconfig" "$nuttx_arch_root/Make.defs" "$nuttx_arch_root/CMakeLists.txt" \
  "$nuttx_board_root/configs" "$nuttx_board_root/Kconfig" \
  "$px4_hal_root" || true
