#!/usr/bin/env bash
# Source contracts for the RDK-RZ/V2H PWM one-shot and DShot board variants.

set -euo pipefail

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly root_dir
readonly board_kconfig="${root_dir}/platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/Kconfig"
readonly dshot_board="${root_dir}/boards/renesas/rdk-rzv2h/dshot.px4board"

oneshot_block="$(sed -n '/^config RZV2H_PWM_ONESHOT_EXAMPLE$/,/^config /p' "${board_kconfig}")"

if ! grep -Fq 'RZV_GPT_ONESHOT' <<<"${oneshot_block}" ||
	! grep -Fq 'EXAMPLES_PWM' <<<"${oneshot_block}" ||
	! grep -Fq '!PWM_MULTICHAN' <<<"${oneshot_block}" ||
	! grep -Fq 'EXAMPLES_PWM_PULSECOUNT > 0' <<<"${oneshot_block}" ||
	! grep -Fq 'RZV2H_EXAMPLE_SUPPORT' <<<"${oneshot_block}"; then
	echo "RZV2H PWM one-shot example must require the PWM app and GPT pulse-count support" >&2
	exit 1
fi

if ! grep -Fqx '# Same as default.px4board but adds the opt-in DShot driver.' "${dshot_board}" ||
	! grep -Fqx '# PWMOut remains linked to provide shared PWM_MAIN actuator parameters.' "${dshot_board}" ||
	grep -Fq 'replaces PWM_OUT' "${dshot_board}"; then
	echo "DShot board header must describe PWMOut as the linked parameter provider" >&2
	exit 1
fi
