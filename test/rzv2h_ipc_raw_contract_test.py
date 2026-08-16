#!/usr/bin/env python3
"""Static contracts for the RZ/V2H three-core raw IPC lab profiles."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
APPS = ROOT / "platforms/nuttx/NuttX/apps"
BOARD = NUTTX / "boards/arm/rzv/rdk-rzv2h"
CONFIGS = BOARD / "configs"
APP = APPS / "examples/rzv_ipc_demo"

PROFILES = {
    "ipcc-raw-cr8_0": {
        "core": "CR8-0",
        "device": "/dev/ipcc4",
        "selector": "CONFIG_RZV2H_BUILD_CR8_0=y",
        "section": ".noncache_buffer.cr8_0",
    },
    "ipcc-raw-cr8_1": {
        "core": "CR8-1",
        "device": "/dev/ipcc1",
        "selector": "CONFIG_RZV2H_BUILD_CR8_1=y",
        "section": ".noncache_buffer.cr8_1",
    },
    "ipcc-raw-cm33": {
        "core": "CM33",
        "device": "/dev/ipcc3",
        "selector": "CONFIG_RZV2H_BUILD_CM33=y",
        "section": ".noncache_buffer.cm33",
    },
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def active_symbols(defconfig: str) -> set[str]:
    return {
        line.strip()
        for line in defconfig.splitlines()
        if line.startswith("CONFIG_")
    }


class Rzv2hRawIpcContractTest(unittest.TestCase):
    def test_demo_can_build_for_raw_driver_without_generic_ipcc(self) -> None:
        kconfig = read(APP / "Kconfig")
        stanza = re.search(
            r"config EXAMPLES_RZV_IPC_DEMO\n(?P<body>.*?)(?=\nconfig |\Z)",
            kconfig,
            re.DOTALL,
        )
        self.assertIsNotNone(stanza)
        self.assertIn("depends on IPCC || RZV_IPC_RAW", stanza.group("body"))

    def test_raw_arch_driver_does_not_select_or_register_generic_ipcc(self) -> None:
        kconfig = read(NUTTX / "arch/arm/src/rzv/Kconfig")
        stanza = re.search(
            r"config RZV_IPC_RAW\n(?P<body>.*?)(?=\nconfig |\Z)",
            kconfig,
            re.DOTALL,
        )
        self.assertIsNotNone(stanza)
        self.assertNotIn("select IPCC", stanza.group("body"))

        raw_source = read(NUTTX / "arch/arm/src/rzv/rzv_ipc_raw.c")
        self.assertNotRegex(raw_source, r"\bipcc_register\s*\(")

    def test_profiles_are_raw_only_interactive_rtt_images(self) -> None:
        sections = set()
        for profile, expected in PROFILES.items():
            text = read(CONFIGS / profile / "defconfig")
            symbols = active_symbols(text)

            self.assertIn(expected["selector"], symbols)
            self.assertIn("CONFIG_RZV_IPC_RAW=y", symbols)
            self.assertIn("CONFIG_RZV_IPC_RAW_ENTRY_SIZE=64", symbols)
            self.assertIn("CONFIG_RZV_IPC_TX_TIMEOUT_MS=100", symbols)
            self.assertIn("CONFIG_EXAMPLES_RZV_IPC_DEMO=y", symbols)
            self.assertIn("CONFIG_EXAMPLES_RZV_IPC_DEMO_AUTOECHO=y", symbols)
            self.assertIn("CONFIG_EXAMPLES_RZV_IPC_DEMO_BOOT_PEER=y", symbols)
            self.assertIn('CONFIG_INIT_ENTRYPOINT="rzv_ipc_boot_main"', symbols)
            self.assertIn("CONFIG_EXAMPLES_RZV_IPC_DEMO_DEFAULT_SIZE=64", symbols)
            self.assertIn("CONFIG_CONSOLE_SYSLOG=y", symbols)
            self.assertIn("CONFIG_SYSLOG_RTT_CONSOLE_INPUT=y", symbols)
            self.assertNotIn("CONFIG_IPCC=y", symbols)
            self.assertNotIn("CONFIG_IPCC_BUFFERED=y", symbols)
            self.assertNotIn("CONFIG_OPENAMP=y", symbols)
            self.assertNotIn("CONFIG_RPTUN=y", symbols)
            self.assertNotIn("CONFIG_RZV_OPENAMP=y", symbols)

            self.assertIn(
                f'CONFIG_EXAMPLES_RZV_IPC_DEMO_CORE_NAME="{expected["core"]}"',
                symbols,
            )
            self.assertIn(
                f'CONFIG_EXAMPLES_RZV_IPC_DEMO_DEFAULT_DEVICE="{expected["device"]}"',
                symbols,
            )
            section = f'CONFIG_SEGGER_RTT_SECTION="{expected["section"]}"'
            self.assertIn(section, symbols)
            sections.add(section)

        self.assertEqual(len(sections), len(PROFILES))

    def test_profiles_encode_the_approved_chain_roles(self) -> None:
        cr8_0 = active_symbols(read(CONFIGS / "ipcc-raw-cr8_0/defconfig"))
        cr8_1 = active_symbols(read(CONFIGS / "ipcc-raw-cr8_1/defconfig"))
        cm33 = active_symbols(read(CONFIGS / "ipcc-raw-cm33/defconfig"))

        self.assertIn("CONFIG_RZV_IPC_CR8_CR8=y", cr8_0)
        self.assertIn("CONFIG_RZV_IPC_ROLE_INITIATOR=y", cr8_0)
        self.assertIn("CONFIG_RZV_IPC_CR8_CR8_LOOPBACK=y", cr8_0)
        self.assertNotIn("CONFIG_RZV_IPC_CR8_1_CM33=y", cr8_0)

        self.assertIn("CONFIG_RZV_IPC_CR8_CR8=y", cr8_1)
        self.assertNotIn("CONFIG_RZV_IPC_ROLE_INITIATOR=y", cr8_1)
        self.assertIn("CONFIG_RZV_IPC_CR8_1_CM33=y", cr8_1)

        self.assertIn("CONFIG_RZV_IPC_CR8_1_CM33=y", cm33)
        self.assertNotIn("CONFIG_RZV_IPC_CR8_CR8=y", cm33)
        self.assertNotIn("CONFIG_RZV_IPC_CR8_CM33=y", cm33)

    def test_demo_has_bounded_auto_echo_and_machine_markers(self) -> None:
        source = read(APP / "rzv_ipc_demo_main.c")
        self.assertIn('strcmp(argv[i], "--auto-echo")', source)
        self.assertIn("IPCTEST_READY core=%s", source)
        self.assertIn("IPCTEST_RESULT core=%s", source)
        self.assertIn("if (a->bounded_echo && echoed >= a->count)", source)
        self.assertRegex(source, r"if \(nw != a->msgsize\)")
        self.assertRegex(source, r"if \(nr != a->msgsize\)")

    def test_demo_uses_public_raw_stats_and_recovery_contract(self) -> None:
        source = read(APP / "rzv_ipc_demo_main.c")
        self.assertIn("<nuttx/ipc/rzv_ipc_raw.h>", source)
        self.assertNotIn('"arch/arm/src/rzv/', source)
        self.assertIn('strcmp(argv[i], "--recover")', source)
        self.assertIn("RZV_IPC_RAWIOC_GET_STATS", source)
        self.assertIn("RZV_IPC_RAWIOC_RECOVER", source)
        self.assertIn("IPCTEST_STATS core=%s", source)
        self.assertIn("a->msgsize != RZV_IPC_RAW_PAYLOAD_SIZE", source)

    def test_boot_wrapper_starts_peer_then_preserves_interactive_nsh(self) -> None:
        source = read(APP / "rzv_ipc_demo_main.c")
        kconfig = read(APP / "Kconfig")
        self.assertIn("config EXAMPLES_RZV_IPC_DEMO_BOOT_PEER", kconfig)
        self.assertIn("depends on RZV_IPC_RAW", kconfig)
        self.assertIn("int rzv_ipc_boot_main(int argc", source)
        self.assertIn('task_create("ipc-auto-echo"', source)
        self.assertIn("IPCTEST_BOOT core=%s status=task-created", source)
        self.assertIn("IPCTEST_BOOT core=%s status=task-create-failed", source)
        self.assertIn("return nsh_main(argc, argv);", source)

    def test_ping_stops_on_first_write_or_poll_timeout(self) -> None:
        source = read(APP / "rzv_ipc_demo_main.c")
        timeout_blocks = re.findall(
            r"(?:errno == ETIMEDOUT|ret == 0).*?return 2;",
            source,
            re.DOTALL,
        )
        self.assertGreaterEqual(len(timeout_blocks), 2)
        for block in timeout_blocks[:2]:
            self.assertNotIn("continue;", block)

    def test_each_linker_collects_its_profile_specific_rtt_section(self) -> None:
        scripts = {
            "ipcc-raw-cr8_0": BOARD / "scripts/rdk-rzv2h_cr8_0.ld",
            "ipcc-raw-cr8_1": BOARD / "scripts/rdk-rzv2h_cr8_1.ld",
            "ipcc-raw-cm33": BOARD / "scripts/rdk-rzv2h_cm33.ld",
        }
        for profile, script in scripts.items():
            expected = PROFILES[profile]["section"]
            linker = read(script)
            self.assertTrue(
                expected in linker or "*(.noncache_buffer*)" in linker,
                f"{script} does not collect {expected}",
            )

    def test_cm33_uses_its_core_local_mhu_alias(self) -> None:
        mhu = read(NUTTX / "arch/arm/src/rzv/hardware/rzv_mhu.h")
        channels = read(NUTTX / "arch/arm/src/rzv/rzv_ipc_channels.h")
        startup = read(NUTTX / "arch/arm/src/rzv/rzv_start_cm33.c")

        self.assertIn("RZV_MHU0_NS_CM33_BASE        0x50480000u", mhu)
        self.assertRegex(
            channels,
            r"#ifdef CONFIG_RZV2H_BUILD_CM33\s+"
            r"#\s*define RZV_IPC_CR8_1_CM33_MHU_BASE\s+"
            r"RZV_MHU0_NS_CM33_BASE",
        )
        self.assertIn(
            "RZV_CM33_MHU_NS_BASE   RZV_MHU0_NS_CM33_BASE", startup
        )
        self.assertIn("RZV_CM33_IPC_SHM_BASE  0x83820000ul", startup)
        self.assertRegex(
            channels,
            r"#ifdef CONFIG_RZV2H_BUILD_CM33\s+"
            r"#\s*define RZV_IPC_CR8_1_CM33_SHM_BASE\s+0x83820000u",
        )

    def test_cm33_uses_the_fsp_debugger_sram_view(self) -> None:
        linker = read(BOARD / "scripts/rdk-rzv2h_cm33.ld")
        config = read(CONFIGS / "ipcc-raw-cm33/defconfig")

        self.assertIn("ORIGIN = 0x08002800", linker)
        self.assertIn("ORIGIN = 0x080f8000", linker)
        self.assertNotIn("0x22000000", linker)
        self.assertNotIn("ORIGIN = 0x20000000", linker)
        self.assertIn("CONFIG_RAM_START=0x08002800", config)
        self.assertIn("CONFIG_RAM_SIZE=1005568", config)

    def test_both_cr8_cores_allocate_the_linker_bounded_heap(self) -> None:
        memory = read(NUTTX / "arch/arm/src/rzv/rzv_memmng.c")
        guard = (
            "defined(CONFIG_RZV2H_BUILD_CR8_0) || "
            "defined(CONFIG_RZV2H_BUILD_CR8_1)"
        )

        self.assertGreaterEqual(memory.count(guard), 2)
        self.assertIn("start = (uintptr_t)__heap_start__;", memory)
        self.assertIn("end   = (uintptr_t)__heap_end__;", memory)

    def test_degraded_transition_serializes_with_tx_publication(self) -> None:
        source = read(NUTTX / "arch/arm/src/rzv/rzv_ipc_raw.c")
        private = read(NUTTX / "arch/arm/src/rzv/rzv_ipc_raw.h")

        self.assertIn("mutex_t statelock;", private)
        self.assertIn("rzv_ipc_mark_degraded_locked", source)
        write = source[source.index("ssize_t rzv_ipc_raw_write") :]
        state_lock = write.index("nxmutex_lock(&priv->statelock)")
        final_check = write.index("if (!rzv_ipc_link_ready(priv))", state_lock)
        publish = write.index("hdr->tail =", final_check)
        state_unlock = write.index("nxmutex_unlock(&priv->statelock)", publish)
        self.assertLess(state_lock, final_check)
        self.assertLess(final_check, publish)
        self.assertLess(publish, state_unlock)

    def test_ack_transaction_is_armed_with_the_irq_masked(self) -> None:
        source = read(NUTTX / "arch/arm/src/rzv/rzv_ipc_raw.c")
        start = source.index("static void rzv_ipc_arm_ack")
        end = source.index("static int rzv_ipc_rx_isr", start)
        body = source[start:end]

        disable = body.index("up_disable_irq(priv->tx_attached_irq)")
        clear = body.index("rzv_mhu_rsp_clear", disable)
        reset = body.index("nxsem_reset(&priv->acksem, 0)", clear)
        send = body.index("rzv_mhu_send", reset)
        enable = body.index("up_enable_irq(priv->tx_attached_irq)", send)
        self.assertLess(disable, clear)
        self.assertLess(clear, reset)
        self.assertLess(reset, send)
        self.assertLess(send, enable)

        recover = source[source.index("int rzv_ipc_raw_recover") :]
        write = source[source.index("ssize_t rzv_ipc_raw_write") :]
        self.assertIn("rzv_ipc_arm_ack(priv);", recover)
        self.assertIn("rzv_ipc_arm_ack(priv);", write)

    def test_buffered_rpmsg_admits_only_a_complete_packet(self) -> None:
        source = read(NUTTX / "arch/arm/src/rzv/rzv_ipc_ipcc.c")
        start = source.index("static ssize_t rzv_ipcc_buffer_data")
        end = source.index("static ssize_t rzv_ipcc_write_notify", start)
        body = source[start:end]

        admission = body.index("circbuf_space(rxbuf) < sizeof(tmp)")
        dequeue = body.index("rzv_rpmsg_receive(tmp, sizeof(tmp))")
        self.assertLess(admission, dequeue)

        blocked = body[admission:dequeue]
        self.assertIn("ipcc->overflow = 1", blocked)
        self.assertIn("ret = total", blocked)
        self.assertIn("goto out", blocked)
        self.assertIn("nwritten = circbuf_write(rxbuf, tmp, nread)", body)
        self.assertIn("if (nwritten != nread)", body)

    def test_rpmsg_callback_buffers_before_notifying_reader(self) -> None:
        source = read(NUTTX / "arch/arm/src/rzv/rzv_ipc_ipcc.c")
        helper_start = source.index("static void rzv_ipcc_buffer_notify")
        callback_start = source.index("static void rzv_ipcc_rxnotify")
        helper = source[helper_start:callback_start]
        callback_end = source.index("static ssize_t rzv_ipcc_read",
                                    callback_start)
        callback = source[callback_start:callback_end]

        buffered = helper.index("priv->lower.ops.buffer_data")
        notified = helper.index("ipcc_rxfree_notify", buffered)
        self.assertLess(buffered, notified)
        self.assertIn("buffered != 0 || priv->lower.overflow", helper)
        self.assertIn("priv->registered && upper != NULL", callback)
        self.assertIn("rzv_ipcc_buffer_notify(priv, upper)", callback)

        buffer_start = source.index("static ssize_t rzv_ipcc_buffer_data")
        buffer_end = source.index("static ssize_t rzv_ipcc_write_notify",
                                  buffer_start)
        buffer_body = source[buffer_start:buffer_end]
        self.assertIn("nxmutex_lock(&g_rzv_ipcc_rxlock)", buffer_body)
        self.assertIn("nxmutex_unlock(&g_rzv_ipcc_rxlock)", buffer_body)

        initialize = source[source.index("int rzv_ipcc_initialize") :]
        registered = initialize.index("g_rzv_ipcc.registered = true")
        initial_drain = initialize.index("rzv_ipcc_buffer_notify", registered)
        self.assertLess(registered, initial_drain)

    def test_pre_registration_rpmsg_backlog_is_drained_boundedly(self) -> None:
        source = read(NUTTX / "arch/arm/src/rzv/rzv_ipc_ipcc.c")
        helper_start = source.index("static void rzv_ipcc_buffer_notify")
        callback_start = source.index("static void rzv_ipcc_rxnotify")
        helper = source[helper_start:callback_start]
        buffer_start = source.index("static ssize_t rzv_ipcc_buffer_data")
        buffer_end = source.index("static ssize_t rzv_ipcc_write_notify",
                                  buffer_start)
        buffer_body = source[buffer_start:buffer_end]

        loop = buffer_body.index(
            "attempt < CONFIG_RZV_RPMSG_RX_QUEUE_DEPTH"
        )
        receive = buffer_body.index("rzv_rpmsg_receive", loop)
        stop = buffer_body.index(
            "circbuf_space(rxbuf) < sizeof(tmp)", loop
        )
        exhausted = buffer_body.index(
            "attempt == CONFIG_RZV_RPMSG_RX_QUEUE_DEPTH", stop
        )
        self.assertLess(loop, receive)
        self.assertLess(stop, receive)
        self.assertLess(receive, exhausted)
        self.assertIn("ipcc->overflow = 1", buffer_body[exhausted:])
        self.assertEqual(helper.count("priv->lower.ops.buffer_data"), 1)
        self.assertNotIn("CONFIG_RZV_RPMSG_RX_QUEUE_DEPTH", helper)

    def test_backlog_larger_than_circbuf_drains_across_single_retries(self) -> None:
        capacity = 1024
        packet_size = 512
        queued = 5
        used = 0

        def drain_once(queued: int, used: int) -> tuple[int, int, bool]:
            overflow = False
            for _ in range(8):
                if capacity - used < packet_size:
                    overflow = True
                    break
                if queued == 0:
                    overflow = False
                    break
                queued -= 1
                used += packet_size
            else:
                overflow = True
            return queued, used, overflow

        queued, used, overflow = drain_once(queued, used)
        self.assertEqual((queued, used, overflow), (3, 1024, True))

        expected_queued = [2, 1, 0]
        for expected in expected_queued:
            used -= packet_size
            queued, used, overflow = drain_once(queued, used)
            self.assertEqual(queued, expected)
            self.assertTrue(overflow)

        used -= packet_size
        queued, used, overflow = drain_once(queued, used)
        self.assertEqual(queued, 0)
        self.assertFalse(overflow)


if __name__ == "__main__":
    unittest.main()
