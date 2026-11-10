# VS Code RTT Monitor: board checks of the trace backends (2026-11-10)

Scope: the host-side backends that the RTT Monitor drives (single-core JLinkExe
bridge, dual AXI-AP bridge, serial TCP relay), run from the shell on the local
RDK-RZ/V2H. The Extension Development Host UI itself was not driven in this
session; its behaviour is covered by `npm test` against fake ports.

## Setup

- Probe J-Link S/N 52000195, V8.94, VTref 1.79 V (a first attempt read 0.000 V
  until the ribbon cable was reseated).
- Images: `renesas_rdk-rzv2h_demo` (CR8-0, `_SEGGER_RTT=0x081a8404`) and
  `renesas_rdk-rzv2h-io-cr8_1_demo` (CR8-1, `0x081e2400`), RAM-loaded with
  `rzv2h-ipc-demo-load-both-auto.sh`; both VERIFY PASS (CR8-0 PC 0x4090ee8c,
  CR8-1 PC 0x4180b140). Repository at 392c4aed7a3 plus uncommitted work.
- Host UART: `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5XK3RJT-if00-port0`.

## Results

| Check | Result |
|-------|--------|
| Single-core bridge honours `RTT_PORT` | `RTT_PORT=19031 nuttx-rtt-bridge.sh start cr8_1` listened on 19031; `nsh_console_exec.py --rtt 127.0.0.1:19031 --marker 'echo port_ok'` returned `port_ok`; stop released the probe. |
| Dual bridge, first board run | Failed: `[Errno 98] Address already in use` on 19021. `JLINKARM_OpenEx` starts SEGGER's RTT telnet server on 19021 (plus 19030, 19080), and the bridge bound its listeners after opening the DLL. With the ports bound first, the DLL opens and skips them. Fixed in `rzv2h-dual-rtt-serve.py`; regression test `test_ports_bound_before_the_probe_opens`. |
| Dual bridge after the fix | Listeners on 19021 (CR8-0) and 19031 (CR8-1). `echo core0_ok` and `echo core1_ok` sent at the same time each returned only on their own port; no input crossed. |
| Core switch (switch mode) | Stop the CR8-0 bridge and start CR8-1: bridge up after 1.09 s (criterion: under 3 s); first NSH reply at 3.71 s including the helper's prompt wait. |
| Probe hand-off around Load | Dual bridge stopped, both cores reloaded and verified, dual bridge restarted: 26.8 s in total. The boot output since the load was replayed to the first client (CR8-0 3553 B, CR8-1 291 B); no `<<rtt-bridge: ...>>` drop or lost-block markers. |
| Serial relay | `serial_console --tcp 19041` reported `serial relay up: /dev/ttyUSB0 -> 127.0.0.1:19041` and forwarded 21279 B in 5 s; a second client got `<<serial-relay: console already has a client>>`. |
| UART lease | While the relay ran, `--check` and a second relay both exited 4 (`UART_BUSY`); after the relay stopped, `--check` exited 0. |

## Limits

- The demo CR8-0 image runs MAVLink at 57600 baud on this UART, and the relay
  is fixed at 115200, so the relay check proves byte flow and lease handling,
  not a readable NSH console. A UART NSH image is needed for that.
- No J-Link reset or failed connect occurred after the cable was reseated.
- Recover and Debug hand-offs, Save Log and the drop badge were not exercised
  on the board.
