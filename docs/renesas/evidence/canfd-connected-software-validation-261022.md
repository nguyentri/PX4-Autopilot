# Connected CAN-FD software validation — 2026-10-22

The RDK CAN1/HW0 and CAN2/HW3 connected-test implementation passes host,
review and clean-build gates. **No board connection, load, reset, target
write or physical test was performed.** The CAN-FD evidence tier remains
bounded on-target for the historical 2026-08-09 HW0 internal loopback only.
Use the [CAN-FD procedure](../peripherals/canfd.md) for the separate physical gate.

## Implemented contract

- `/dev/can0`: HW0 P80/P81, FIFO0, PA2 standby. `/dev/can1`: HW3 P86/P87,
  FIFO1, PA3 standby. Optional HW1/P82/P83 remains exclusive with HW3 and SCI9.
- Mailbox stride 64, HW3 mailbox 192, sparse AFL counts, indexed TX enables
  and original IRQSEL aliases are checked against local CMSIS/FSP sources.
- Public 32-byte status / 16-byte cancel ABI has target/host size assertions.
  One usable software TX entry, owned standby isolation, bounded abort/reset
  and exactly-once upper-half retirement prevent close from waiting on a
  stranded entry. Failed reset remains an isolated failure. Reopen clears
  stale TX/GIC state and drains the owned RX FIFO within its eight-entry bound.
- `rzv_canfd -n 32 -t 1000` tests 2624 frames by default. Each frame requires
  both TX IRQ status and peer RX. The matrix covers both directions,
  Classic lengths 0..8 and all 16 FD lengths with BRS off/on. Repeated
  one-at-a-time traffic is aggregate coverage, not FIFO saturation.
- Generic CAN upper half/example and the `canfd`/`canfd-rtt` defconfigs are
  unchanged. `canfd-dual` uses HW0+HW3 internal loopback; only `canfd-ext`
  enables the dedicated connected command and normal bus mode.

## Executed host and review checks

| Command from repo root | Result |
|------------------------|--------|
| `python3 test/rzv2h-canfd-tx-lifecycle-runtime-test.py` | 11 passed |
| `python3 test/rzv2h-canfd-sample-contract-test.py` | 8 passed; each scenario with CAN_ERRORS off/on |
| `python3 test/rzv2h-register-base-contract-test.py` | 2 passed |
| `python3 test/rzv2h-driver-unwind-runtime-test.py` | 4 passed |
| `python3 test/rzv2h_board_gpio_contract_test.py` | 7 passed |
| `python3 test/rzv2h-optional-config-contract-test.py` | 3 passed |

Total: 35 test groups/cases across six suites. The lifecycle harness compiles
production lower-half/board code and actual generic `can_write`, `can_txdone`
and `can_close` functions. The app harness executes production C using real
CAN/vendor header declarations, deterministic I/O and monotonic time.
Coverage includes failed/duplicate TX abort IRQ, missing ACK/IRQ, peer RX without TX IRQ, reset timeout
with the request still active, quarantine before retirement, post-fault
writes, stale/duplicate IRQ, stale/stuck RX FIFO, sibling isolation,
registration rollback, sequence exhaustion, short/corrupt I/O, interrupted
waits, close, rerun and bounded isolated reopen failure. Literal 0/1/2-byte
payload vectors call the production frame builder.

Independent code review found no remaining findings after target ABI size
assertions were added. The cook simplification pass preserved behavior.
NuttX `nxstyle` passes for the driver, board glue, public/private API headers,
board header and sample; the scoped repository driver checker reports zero
findings. The full pre-existing register macro header retains 40 native
style diagnostics versus 42 at HEAD, with no new diagnostic categories.
Diff whitespace checks pass. No unrelated style cleanup was added.

## Four sequential clean builds

Each command used `platforms/nuttx/NuttX/build.sh <config>`; the script
performed distclean and fresh configuration. Each resolved config and ELF
were archived before the next build. All four final builds exited zero.

| Config | ELF bytes | ELF SHA-256 | Connected command |
|--------|-----------|-------------|-------------------|
| `canfd` | 1743932 | `214a08c132e76ea5f8f45afe939dca6051c8f72b0cefd52e6ed49e743cbb8aee` | absent |
| `canfd-rtt` | 1773220 | `d331e7c63193aafea2412d4a7a9c03361f48bd528218acdb7abbb72a34be585a` | absent |
| `canfd-dual` | 1771144 | `1a5b18708b765237f14c2d7556ca1e0754e88ac326289f2158bece09f0192df9` | absent |
| `canfd-ext` | 1786456 | `e8e437eda1985c3839950bb8d493e437f659ec861660f6e9ad555b6071d1f7e8` | present |

The ext image has `CONFIG_RZV_CANFD0=y`, `CONFIG_RZV_CANFD3=y`, HW1 and boot
loopback disabled, `CONFIG_CAN_FIFOSIZE=2`, extended IDs, dedicated app,
`CONSOLE_SYSLOG` and RTT console input. `SERIAL_CONSOLE` and SCI console
drivers are disabled. Kconfig drops the hidden `NO_SERIAL_CONSOLE` choice
when its console prerequisites are unavailable; the receipt checks actual
RTT routing and absence of an enabled serial console.

Toolchain: arm-none-eabi-gcc (Arm GNU Toolchain 13.2.rel1 (Build arm-13.7)) 13.2.1 20231009; GNU ld (Arm GNU Toolchain 13.2.rel1 (Build arm-13.7)) 2.41.0.20231009.

Dirty source baseline at build time:

| Tree | HEAD |
|------|------|
| parent | `b2383bb2f42e28589a7766095de95c5b28218eaa` |
| nuttx | `cc10d09f984d993e39b7ba04cfba9b15425cf75c` |
| apps | `8b191ab6887ce0f2ce093055b5c1342438428e42` |

These are local dirty-worktree builds, not builds of committed feature
revisions. Local plan archive:
`plans/261021-2323-rzv2h-canfd-connected-test/artifacts/<config>/` contains
`receipt.json`, complete build log, exact `nuttx.elf`, binary/hex/map and
resolved config, tracked binary patches for all three trees, and an
allowlist with hashes and actual bytes of the untracked public header and
four app build inputs. The common archive also retains the pinned RTT ZIP,
host logs and style reports. Its source hashes agree across the four final
builds. `plans/` is gitignored; retain or transfer this local archive with
any later hardware handoff.

An initial clean attempt failed because sandbox DNS blocked the pinned RTT
download. A permitted network download matched the Make.defs archive hash
`7b18aae08c05a271c994333b14a65f388fe94fd0585a51d5b88ce642f99a1d4c`.
The next attempt caught a missing GIC register-header include at link time;
it was fixed and the lifecycle checks rerun. Both failed logs and the
intermediate baseline are retained separately from the four final receipts.
Final builds have no compiler/linker warnings; the existing recursive-make
jobserver warning remains in each complete log.

## Remaining physical evidence

The fitted board revision, onboard termination and PA2/PA3 electrical levels
must be recorded. An approved run must use the retained ext ELF/hash above
and prove healthy traffic in both directions, bounded missing-ACK failure,
cancel/close, successful reopen and full rerun without reboot. A controller
pair sharing one clock does not independently prove the absolute nominal
or FD data bitrate. No production-readiness claim is made.
