#!/usr/bin/env bash
# Source contracts for the RDK-RZ/V2H PWM one-shot example and the default
# target's boot-time PWM/DShot driver selection.

set -euo pipefail

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly root_dir
readonly board_kconfig="${root_dir}/platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/Kconfig"
readonly arch_kconfig="${root_dir}/platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Kconfig"
readonly default_board="${root_dir}/boards/renesas/rdk-rzv2h/default.px4board"
readonly board_defaults="${root_dir}/boards/renesas/rdk-rzv2h/init/rc.board_defaults.cmds"

oneshot_block="$(sed -n '/^config RZV2H_PWM_ONESHOT_EXAMPLE$/,/^config /p' "${board_kconfig}")"

if ! grep -Fq 'RZV_GPT_ONESHOT' <<<"${oneshot_block}" ||
	! grep -Fq 'EXAMPLES_PWM' <<<"${oneshot_block}" ||
	! grep -Fq '!PWM_MULTICHAN' <<<"${oneshot_block}" ||
	! grep -Fq 'EXAMPLES_PWM_PULSECOUNT > 0' <<<"${oneshot_block}" ||
	! grep -Fq 'RZV2H_EXAMPLE_SUPPORT' <<<"${oneshot_block}"; then
	echo "RZV2H PWM one-shot example must require the PWM app and GPT pulse-count support" >&2
	exit 1
fi

dmac_block="$(sed -n '/^config RZV_DMAC$/,/^if RZV_DMAC$/p' "${arch_kconfig}")"

if ! grep -Fq 'hardware-triggered memory-to-peripheral transfers' <<<"${dmac_block}" ||
	! grep -Fq 'Completion callbacks, link mode, dynamic channel allocation' <<<"${dmac_block}" ||
	grep -Fq 'Hardware-triggered transfers, callbacks' <<<"${dmac_block}"; then
	echo "RZV2H DMAC Kconfig help must match the supported DShot trigger contract" >&2
	exit 1
fi

# The default target links both output drivers, and the board defaults start
# exactly one: pwm_out unless PWM_MAIN_TIM0 selects a DShot rate (-3/-4/-5).
if ! grep -Fqx 'CONFIG_DRIVERS_DSHOT=y' "${default_board}" ||
	! grep -Fqx 'CONFIG_DRIVERS_PWM_OUT=y' "${default_board}"; then
	echo "default.px4board must link both pwm_out and dshot" >&2
	exit 1
fi

selection="$(sed -n '/^if param greater PWM_MAIN_TIM0 -2$/,/^fi$/p' "${board_defaults}")"

if ! grep -Fqx 'param set-default PWM_MAIN_TIM0 400' "${board_defaults}" ||
	[[ "$(grep -c 'set DSHOT_START yes' <<<"${selection}")" != 1 ]] ||
	[[ "$(grep -c 'set PWM_OUT_START yes' <<<"${selection}")" != 1 ]] ||
	! grep -Fq 'set PWM_OUT_START no' <<<"${selection}" ||
	[[ "$(sed -n '/^else$/,$p' <<<"${selection}" | grep -c 'set DSHOT_START yes')" != 1 ]]; then
	echo "rc.board_defaults.cmds must start only pwm_out by default and only dshot for DShot rates" >&2
	exit 1
fi
