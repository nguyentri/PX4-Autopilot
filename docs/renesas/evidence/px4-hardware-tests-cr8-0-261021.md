# PX4 CR8-0 hardware test evidence

The 2026-10-21 campaign is **incomplete**: 21 of 32 native PX4 test entries
passed and 11 were blocked by architecture or fixture boundaries. The complete
per-test record, image identity, source and capture digests are in the
[portable receipt](px4-hardware-tests-cr8-0-261021.json); the sanitized RTT and
host transcript is [retained here](px4-hardware-tests-cr8-0-261021.txt).

## Image and scope

The run used CR8-0 RTT at `0x081a2400` and the temporary tests-enabled
`renesas_rdk-rzv2h_dshot.elf`:

`128824d6622df542b9085d7b5e53c3484eba85d901653f59a92f6fa7f8f0ad8f`

The PX4 source was `f14154dac18770a06e5c6a5e1f88167621146571` and NuttX was
`5cf2c27ac7ac77cf9df4b7f78f4981e7b4f3c72b`. The tracked configuration was
restored after enabling the existing test suite. One normal RAM load completed;
the run did not reset the board, retry a failed connection, attach CR8-1 or
CM33, arm, or send a nonzero actuator command.

`/fs` was RAM TMPFS throughout. The `file`, `file2`, `dataman`, and parameter
checks therefore establish RAM behavior only; they do not qualify persistent
storage. RTT TRIM dropped some verbose file progress rows, but the source-backed
final directory completion and explicit `file PASSED` terminal were captured.

## Focused observations

| Area | Evidence and boundary |
|---|---|
| DShot600 | Four zero-throttle motor-stop transfers completed on boot and after restart, mask `0xf`, 128 bytes per channel. GDB found HAL disarmed, DMA remaining/status zero, no group errors, and all GPT counters/output gates disabled. No waveform, powered ESC, nonzero throttle, or ESC response was tested. |
| HRT | Detached test image: 11,041 µs sleep and 4 µs callback latency. The RTT-attached comparison failure of 133,603 µs is retained; probe interference remains a limit. |
| SPI / sensors | The `i2c_spi_cli` argument-parser entry passed, but `mpu9250` and `mpu9250_i2c` were not running and accel/gyro topics were never published. No physical sensor identity or data qualification follows. |
| I2C / barometer | `bmp280` was not running and `sensor_baro` was never published. No fitted-device, bus recovery, or physical barometer qualification follows. |
| Serial | Telemetry/GPS TX counters progressed; RX was zero on `/dev/ttyS4`, `/dev/ttyS5`, `/dev/ttyS6`, and `/dev/ttyS9`. No GPS fix, RC frame, or payload response was established. |
| Cleanup | Commander stayed disarmed; output modules were stopped and task-created files were removed. Read-only GDB confirmed inactive DMA/GPT state and host preflight found no probe owners or listeners. |

## Blocked native entries

These are the 11 blocked entries and their concrete reasons; the JSON receipt
contains the same per-test results and all 21 passing IDs.

| Entry | Reason |
|---|---|
| `time` | The test writes Cortex-M DWT/DEMCR addresses `0xe000xxxx`, which are unsuitable for Cortex-R8. `tests all` was not invoked. |
| `mount` | The reboot stress test calls `px4_reboot_request`; reset was outside this bounded run, and RAM TMPFS cannot qualify physical storage. |
| `led` | `/dev/led0` is absent. |
| `uart_baudchange` | The test hard-codes absent `/dev/ttyS2`. |
| `uart_break` | The test hard-codes absent `/dev/ttyS1`. |
| `uart_console` | `/dev/ttyACM0` is absent and the test contains an unbounded reader. |
| `uart_loopback` | `/dev/ttyS1`, `/dev/ttyS2`, and a wired loopback are unavailable. |
| `uart_send` | Default `/dev/ttyS3` is absent and no unowned wired UART fixture was available. |
| `hott_telemetry` | The required receiver/telemetry fixture and `/dev/ttyS1` are unavailable. |
| `ppm` | `HRT_PPM_CHANNEL` is not configured; the stock success return would exercise no PPM input. |
| `rc` | No receiver frames or `input_rc` publication were available. |

No physical sensor, PWM/DShot waveform, persistent storage, cold-cycle, soak,
other-profile, or IO-core qualification was performed. The previous plan for
an eight-profile register observer remains unimplemented.

## Provenance

The source transcript hash is
`708183bacea2d4db83480c682ee056888e5791b0b4c717544d2d05219b9c333a`.
The retained transcript hash is
`037139462b845b0f28565c5db98c50c56dfe4aad4fb0a46228c4948395c92e1d`; it is
the same sanitized transcript after removing trailing spaces/tabs per line and
terminal blank lines, with one final newline retained. ANSI console bytes were
retained. The JSON receipt lists the source,
capture, and transcript digests without requiring ignored build artifacts to
be present in a clone.
