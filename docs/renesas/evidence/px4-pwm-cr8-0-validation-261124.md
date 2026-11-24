# PX4 GPT PWM on CR8-0: board run with a logic analyzer (2026-11-24)

Scope: the four analog PWM outputs of `renesas_rdk-rzv2h_default` on CR8-0
(`pwm_out`, 400 Hz), measured on the header pins with a logic analyzer by the
user. Register reads were not available in this session: every GDB one-shot
attach failed with `QStartNoAckMode (noack) conflicting enabled responses`
(no reset or DBGEN marker), so PX4 state was read over RTT instead.

## Setup

- Probe `<probe-sn>`. Images RAM-loaded with `rzv2h-load-one-core.sh cr8_0`;
  each load reported VERIFY PASS. NSH over the JLinkExe RTT bridge
  (`nuttx-rtt-bridge.sh`, `nsh_console_exec.py --marker`).
- Outputs: PWM0 GPT6A/PA4 (pin 32), PWM1 GPT7B/PA7 (pin 33), PWM2 logical
  GPT9A = physical R_GPT11 on P96 (pin 35), PWM3 logical GPT10B = physical
  R_GPT12 on P53 (pin 31).
- Parameters (airframe 4210): `PWM_MAIN_MIN` 1150, `PWM_MAIN_MAX` 1940,
  `PWM_MAIN_DIS`/`FAIL` 800 µs, `THR_MDL_FAC` 0.3.

## Defects found and fixed

| Symptom | Cause | Fix |
|---------|-------|-----|
| No pulses on any channel (the standalone NuttX PWM sample worked) | Channel init never enabled the GTSSR/GTPSR/GTCSR software start/stop/clear sources, so GTSTR was ignored and the counter never ran. | Init writes GTPSR.CSTOP, GTCSR.CCLR and GTSSR.CSTRT before using GTSTP/GTCLR/GTSTR. |
| Disarmed output was not 800 µs | `up_pwm_servo_set()` clamped values below 1000 µs. | Clamp removed; the mixer already bounds values by `PWM_MAIN_*`. |
| Glitch when an output stops (end of `actuator_test`) | Disable stopped and cleared the counter mid-cycle (truncated pulse) and released GTIOR OAE, so the pad floated (reads high); re-enable restarted the counter from that state. | Output driven low from init (OAE=1, OADFLT/OAHLD=0) with the counter running at 0 % duty. Enable/disable only switch the duty, applied at cycle end. Compare/rate writes keep 0 % while disabled. |
| Pads float between boot/reset and timer init | `board_on_reset()` unconfigured the pads (Hi-Z), and the pads were muxed to the GPT before it drove them. | `board_on_reset()` (also run at early boot) drives the pads low as GPIO outputs; `rdk_rzv2h_timer_initialize()` starts the GPTs before muxing the pads; failure unwind restores driven-low GPIOs. |

The first three are in commit `33603a2d847`.

## Results

| Check | Image (sha256 prefix) | Result |
|-------|-----------------------|--------|
| `actuator_test set -m 1 -v 0.15 -t 20` on ESC1 | `8b3bd796` (counter + clamp fix) | Analyzer: period 2.5 ms, duty 52.25 % = 1306 µs, matching 1150 + 0.197·790, where 0.197 solves 0.3u² + 0.7u = 0.15 (`THR_MDL_FAC`). |
| `actuator_test iterate-motors` | `8b3bd796` | 800 µs (32 %) on each slot is expected: each slot lasts 400 ms, shorter than the 500 ms output ramp. |
| All four channels | `778ab9f4` (stop-path fix) | User reported all four outputs working on the analyzer after the stop-path fix. |
| RTT `pwm_out status` before / during / after `-v 0.15 -t 3` | `778ab9f4` | Channel 0 value 800 → 1306 → 800. |
| Live switch `pwm_out stop`, `PWM_MAIN_TIM0..3=-5`, `dshot start` (DShot150, disarmed) | `99b9a8d5` (DShot pad fix) | RTT: `DShot TX initialized: 150000 Hz, channels 0xf`, frames complete (128 bytes each), about 19 frames/s, no errors. Analyzer (user): 2.5 µs high pulses with a ~7 µs period, i.e. DShot150 zero bits (3/8 of 6.67 µs). Idle level between frames, stop level and non-zero throttle not yet reported. |
| Boot with pads driven low from early init | `ed0cc0b7` | No timer initialization error in the boot log; channels 0–3 report 800 µs disarmed and channel 0 reaches 1306 during `-v 0.15`. |

## Limits

- The stop edge and the idle level of the `ed0cc0b7` image were not captured
  as named analyzer traces in this run; the four-channel result is the user's
  report, not a stored capture.
- From SoC reset until early board init the pads are in their hardware reset
  state; only an external pull-down holds an ESC input low in that window.
- Only analog PWM was run. The DShot driver released OAE after every frame,
  while disarmed and after stop, so its pads floated between frames; it now
  keeps the output enabled and driven low (host model regression), with no
  DShot waveform captured on target yet.
- ESC response, failsafe timing and reset behavior under load were not tested.
