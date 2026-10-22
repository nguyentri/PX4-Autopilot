# CAN-FD audit repair software validation — 2026-10-22

The three pre-existing defects identified by the
[CR8-0 re-audit](../../../plans/reports/audit-261022-0637-rzv2h-canfd.md)
are repaired in source. Hardware channels 0..5 and the RDK HW0/HW3 mapping
are preserved. This checkpoint supersedes the earlier
[six-channel source/build checkpoint](canfd-six-channel-software-validation-261022.md)
for the repaired source. No hardware operation was performed.

## Repairs and discriminating evidence

- Accept-all rules leave DLC checking/replacement disabled, matching the
  supplied FSP configuration. Enabling replacement with GAFLDLC zero had
  truncated nonempty RX frames. The host fixture now applies AFL DLC
  checking/replacement before FIFO publication. Each of six channels passes
  Classic lengths 0..8 and all sixteen FD DLCs with BRS off/on, in external
  RX and internal-loopback paths: 492 frame cases across two tests.
- Failed internal-loopback recovery masks owned TX/error/FIFO delivery,
  retains standby and terminal fault/isolation state, and retires subsequent
  queued entries as failed without hardware submission. Production generic
  upper-half close completes with stuck TX/reset, including a depth-eight
  queue and unmanaged expansion channels. Late completion cannot report
  success; mode changes are rejected, and reopening requires reset recovery.
- CAN IRQs attach disabled, receive `CONFIG_RZV_CANFD_IRQ_PRIORITY`, then
  enable after state publication. CR8 advertises priority support and CAN-FD
  selects its architecture facility. A nondefault value of 5 is checked
  before enable for all six channels plus shared IRQs. Priority failures
  release their routes and preserve siblings; optional global-error failure
  retains the existing nonfatal behavior.

Before production edits, all nine initial lifecycle regressions and the
priority Kconfig regression failed. Exact output is retained under
`plans/261022-0710-canfd-audit-fixes/artifacts/before-*.log`.
The extra optional-global-error regression also passes after repair.

## Host and source checks

| Command under `test/`, run with `python3` | Passing cases |
|---|---:|
| `rzv2h-canfd-tx-lifecycle-runtime-test.py` | 26 |
| `rzv2h-canfd-sample-contract-test.py` | 8 |
| `rzv2h-register-base-contract-test.py` | 2 |
| `rzv2h-driver-unwind-runtime-test.py` | 4 |
| `rzv2h_board_gpio_contract_test.py` | 7 |
| `rzv2h-optional-config-contract-test.py` | 4 |
| `rzv2h-irq-routing-runtime-test.py` | 6 |

Total: **57 cases across seven suites**, including the shared IRQ-routing
checks. The production driver passes native
NuttX style checking, and parent/NuttX/apps diff whitespace checks pass.
Host fixture, test sources and hashes are retained in `artifacts/host-inputs/`
and `artifacts/host-input-hashes.json` under the repair plan.

## Build receipts

All five clean builds through the repository build script passed. Every
resolved config enables architecture IRQ priorities; shipping profiles use
priority 12, and the temporary all-six profile uses 5. The linked ELFs
contain `up_prioritize_irq`, `rzv_icu_set_priority` and the CAN setup path.
There are no compiler/linker warnings; only the existing recursive-make
jobserver warning appears.

| Archive | Hardware channels | ELF bytes | ELF SHA-256 |
|---|---|---:|---|
| canfd | 0 | 1745484 | `63980a95fe246ec08e3b3149686eacfd60fc5fbb7fa7dd6b9b1e8ac6482f9fcb` |
| canfd-rtt | 0 | 1774796 | `15697eb83ac4b158315915f5427a66a291f45efa624847720b0fb8775854a849` |
| canfd-dual | 0, 3 | 1772728 | `187ecd5c8a7596b27bb03f2ca6529ca22ae92b73817a14e7615cb110dba9ff5b` |
| canfd-ext | 0, 3 | 1788020 | `7e63ec37423788187860a2dfc0e9104f3a77c004166487971e6be68a7e8799ac` |
| all-six | 0, 1, 2, 3, 4, 5 | 1777036 | `9c81117489ac48f6405d308b5c4165e46beb42455b8db3ebee3816c90871abf4` |

Each archive retains its exact ELF/config, full log, toolchain, revisions,
tracked binary patches and common untracked build inputs. All five share
identical production patches and common input hashes; 76 retained artifact
hashes were rechecked without mismatches. Location:
`plans/261022-0710-canfd-audit-fixes/artifacts/<profile>/`. The connected
`rzv_canfd_main` symbol appears only in `canfd-ext`; the all-six ELF contains
all six channel instances. The temporary all-six profile and its build
stamp were removed after archiving. The mutable build tree contains that
validation image; use a clean shipping-profile build before an incremental
rebuild. For an approved connected test, use the retained `canfd-ext/nuttx.elf`
and its hash above.

The first clean build attempt stopped when DNS could not resolve GitHub
for SEGGER RTT. The repeated builds use a cached archive with the exact
Make.defs SHA-256 `7b18aae08c05a271c994333b14a65f388fe94fd0585a51d5b88ce642f99a1d4c`.
The retained `offline-tools/curl` supplies only that exact pinned URL from
the verified cache; the ordinary NuttX archive/source/header checks still
run. No build rule, RTT source or checksum was changed. The cache and
resolver hashes are recorded in every receipt.

Source baselines, plus retained dirty patches:

| Tree | HEAD |
|---|---|
| Parent | `b2383bb2f42e28589a7766095de95c5b28218eaa` |
| NuttX | `cc10d09f984d993e39b7ba04cfba9b15425cf75c` |
| Apps | `8b191ab6887ce0f2ce093055b5c1342438428e42` |

Current NuttX tracked binary patch SHA-256:
`23c9e1455ac61be35b40c5485ac2b75ba4e94aaca2504ff3727eba2bba93e1bc`.

`plans/` is gitignored; preserve the archive explicitly when handing off
testing. No commit, push, flash or target memory operation occurred.

## Qualification limits

The host tests execute production code with modeled MMIO/interrupts; they
do not prove electrical behavior. The historical bounded-on-target tier
still applies only to the 2026-08-09 four-frame HW0 internal loopback.
Connected HW0/HW3 normal-mode IRQ delivery, payload traffic, absolute
bitrate, transceiver isolation/termination and expansion routing remain
target gates. PX4 CAN integration and FSP TDC/timing-parity work remain
outside this repair. Follow the current
[CAN-FD procedure](../peripherals/canfd.md) for separately authorized testing.
