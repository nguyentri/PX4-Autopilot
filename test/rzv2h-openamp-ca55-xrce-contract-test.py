#!/usr/bin/env python3
"""Static contracts for the CR8-0 OpenAMP link to the CA55 CustomXRCEAgent.

The CA55 runs the shipped, unmodified agent from
refs/rzv2h_drone_px4-dev/ca55_stack.  It is the VIRTIO master: it maps the
two resource tables at 0x42F00000, binds rpmsg-service-1 on the name-service
announcement and then sends a NUL-terminated handshake string.  These tests
pin the CR8-0 side (NuttX rzv_openamp/rzv_rpmsg, PX4 uxrce_dds_client RPMsg
transport, board profiles) to that contract.

Reference comparisons run only when the local, gitignored refs/ tree exists;
the in-tree checks always run.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
RZV = NUTTX / "arch/arm/src/rzv"
NUTTX_SCRIPTS = NUTTX / "boards/arm/rzv/rdk-rzv2h/scripts"
PX4_BOARD = ROOT / "boards/renesas/rdk-rzv2h"
CLIENT = ROOT / "src/modules/uxrce_dds_client"

REF = ROOT / "refs/rzv2h_drone_px4-dev"
REF_FW_CFG = REF / "src/platform/OpenAMP_RPMsg_cfg.h"
REF_FW_RSC = REF / "src/platform/rsc_table.h"
REF_FW_RSC_C = REF / "src/platform/rsc_table.c"
AGENT = REF / "ca55_stack/xrce_dds_agent"
AGENT_CFG = AGENT / "OpenAMP_RPMsg_cfg.h"
AGENT_RSC = AGENT / "rsc_table.h"
AGENT_MAIN = AGENT / "custom_agent.cpp"

HAVE_REFS = all(p.is_file() for p in (
    REF_FW_CFG, REF_FW_RSC, REF_FW_RSC_C, AGENT_CFG, AGENT_RSC, AGENT_MAIN))

# OpenAMP's struct rpmsg_hdr is 16 bytes; the RPMsg buffer is 512 bytes.
RPMSG_HDR_SIZE = 16


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def defines(text: str) -> dict[str, str]:
    """Map every '#define NAME value' to its value, comments stripped."""
    out = {}
    for match in re.finditer(r"^\s*#\s*define\s+(\w+)[ \t]+(.+?)\s*$",
                             text, re.MULTILINE):
        value = re.sub(r"/\*.*?\*/|//.*$", "", match.group(2)).strip()
        out[match.group(1)] = value
    return out


def number(value: str) -> int:
    """Evaluate a C integer literal such as '(0x43000000U)', '1u' or
    '(1U << 0)'."""
    value = value.strip().strip("()").strip()
    if "<<" in value:
        left, right = value.split("<<", 1)
        return number(left) << number(right)
    value = re.sub(r"(?i)(?<=[0-9a-f])u?l*$", "", value)
    return int(value, 0)


def string(value: str) -> str:
    match = re.fullmatch(r'"([^"]*)"', value.strip())
    if match is None:
        raise ValueError(f"not a string literal: {value!r}")
    return match.group(1)


def active_symbols(defconfig: str) -> set[str]:
    return {line.strip() for line in defconfig.splitlines()
            if line.startswith("CONFIG_")}


class _OpenampHeader(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hdr = defines(read(RZV / "rzv_openamp.h"))

    def nuttx(self, name: str) -> int:
        self.assertIn(name, self.hdr)
        return number(self.hdr[name])


class SourceContract(_OpenampHeader):
    """Checks that need only this repository."""

    def test_resource_type_ids_are_the_remoteproc_values(self) -> None:
        # include/openamp/remoteproc.h: RSC_VDEV = 3, RSC_RPROC_MEM = 4.
        remoteproc = NUTTX / "../openamp/open-amp/lib/include/openamp/remoteproc.h"
        self.assertEqual(self.nuttx("RZV_OPENAMP_RSC_VDEV"), 3)
        self.assertEqual(self.nuttx("RZV_OPENAMP_RSC_RPROC_MEM"), 4)
        if remoteproc.is_file():
            text = read(remoteproc)
            self.assertRegex(text, r"RSC_VDEV\s*=\s*3")
            self.assertRegex(text, r"RSC_RPROC_MEM\s*=\s*4")

    def test_table_initializers_pair_notify_id_with_its_rings(self) -> None:
        source = read(RZV / "rzv_openamp.c")
        self.assertRegex(
            source,
            r"RZV_OPENAMP_TABLE_INIT\(0,\s*RZV_OPENAMP_VRING0_BASE,\s*"
            r"RZV_OPENAMP_VRING1_BASE\)")
        self.assertRegex(
            source,
            r"RZV_OPENAMP_TABLE_INIT\(1,\s*RZV_OPENAMP_T1_VRING0_BASE,\s*"
            r"RZV_OPENAMP_T1_VRING1_BASE\)")
        # The struct layout the agent parses: 112 bytes per table.
        self.assertRegex(read(RZV / "rzv_openamp.h"),
                         r"sizeof\(struct rzv_openamp_rsc_table_s\)\s*==\s*112")
        # Boot bytes stay identical to the agent's table: gfeatures is only
        # written after the master reports DRIVER_OK.
        self.assertIn("rzv_openamp_master_ready", source)
        self.assertIn("rzv_openamp_accept_features", source)

    def test_resource_table_section_is_noload_at_0x42f00000(self) -> None:
        scripts = [p for p in NUTTX_SCRIPTS.glob("*.ld")
                   if ".resource_table (NOLOAD)" in read(p)]
        self.assertTrue(scripts, "no NuttX RZ/V script places .resource_table")
        for script in scripts:
            with self.subTest(script=script.name):
                text = read(script)
                self.assertRegex(text, r"OPENAMP_RSCTBL_START\s*==\s*0x42F00000")
                self.assertRegex(text, r"OPENAMP_RSCTBL_LENGTH\s*=\s*0x00001000")

    def test_xrce_mtu_fits_one_rpmsg_payload(self) -> None:
        buffer_size = self.nuttx("RZV_OPENAMP_RPMSG_BUFFER_SIZE")
        payload = self.nuttx("RZV_OPENAMP_RPMSG_PAYLOAD_SIZE")
        self.assertEqual(payload, buffer_size - RPMSG_HDR_SIZE)

        cmake = read(CLIENT / "CMakeLists.txt")
        block = re.search(r"if\(CONFIG_RZV_RPMSG_UXRCE\)(?P<body>.*?)endif\(\)",
                          cmake, re.DOTALL)
        self.assertIsNotNone(block)
        self.assertIn("set(microxrceddsclient_custom_transport ON)",
                      block.group("body"))
        mtu = re.search(r"set\(microxrceddsclient_custom_transport_mtu (\d+)\)",
                        block.group("body"))
        self.assertIsNotNone(mtu)
        self.assertEqual(int(mtu.group(1)), payload)
        self.assertIn("-DUCLIENT_PROFILE_CUSTOM_TRANSPORT:BOOL="
                      "${microxrceddsclient_custom_transport}", cmake)
        self.assertIn("-DUCLIENT_CUSTOM_TRANSPORT_MTU:STRING="
                      "${microxrceddsclient_custom_transport_mtu}", cmake)

        # The agent runs with framing disabled, so the transport is unframed.
        transport = read(CLIENT / "rpmsg_transport.cpp")
        self.assertRegex(transport,
                         r"uxr_set_custom_transport_callbacks\(\s*&_transport,\s*false")

    # --- Board profiles -----------------------------------------------------

    def test_default_and_demo_nuttx_configs_enable_the_link(self) -> None:
        required = {
            "CONFIG_OPENAMP=y",
            "CONFIG_RPTUN=y",
            "CONFIG_RZV_OPENAMP=y",
            "CONFIG_RZV_RPMSG_UXRCE=y",
        }
        for profile in ("nsh", "demo"):
            with self.subTest(profile=profile):
                symbols = active_symbols(
                    read(PX4_BOARD / f"nuttx-config/{profile}/defconfig"))
                self.assertTrue(required <= symbols, required - symbols)
                # Raw IPC and OpenAMP own the same MHU and memory.
                self.assertNotIn("CONFIG_RZV_IPC_RAW=y", symbols)
                self.assertNotIn("CONFIG_IPCC=y", symbols)

    def test_client_is_built_only_where_openamp_exists(self) -> None:
        default = read(PX4_BOARD / "default.px4board")
        self.assertIn("CONFIG_MODULES_UXRCE_DDS_CLIENT=y", default)
        self.assertNotIn("CONFIG_MODULES_UXRCE_DDS_CLIENT=n",
                         read(PX4_BOARD / "demo.px4board"))
        for profile in ("demosih", "dualcr8"):
            with self.subTest(profile=profile):
                self.assertIn("CONFIG_MODULES_UXRCE_DDS_CLIENT=n",
                              read(PX4_BOARD / f"{profile}.px4board"))

    def test_device_is_registered_and_started_on_rpmsg(self) -> None:
        init = read(PX4_BOARD / "src/init.c")
        self.assertIn('rzv_rpmsg_uxrce_register("/dev/uxrce0")', init)
        for extras in ("init/rc.board_extras", "init/demo/rc.board_extras"):
            with self.subTest(extras=extras):
                self.assertRegex(
                    read(PX4_BOARD / extras),
                    r"uxrce_dds_client start -t rpmsg -d /dev/uxrce0")


@unittest.skipUnless(HAVE_REFS, "refs/rzv2h_drone_px4-dev not present")
class AgentReferenceContract(_OpenampHeader):
    """Checks against the reference firmware and the shipped CA55 agent."""

    def test_memory_layout_matches_reference_firmware_and_agent(self) -> None:
        fw = defines(read(REF_FW_CFG))
        fw_rsc = defines(read(REF_FW_RSC))
        agent = defines(read(AGENT_CFG))
        agent_rsc = defines(read(AGENT_RSC))

        pairs = {
            "RZV_OPENAMP_RESOURCE_TABLE_BASE": (
                fw_rsc["CFG_RSCTBL_MEM_PA"], agent_rsc["CFG_RSCTBL_MEM_PA"]),
            "RZV_OPENAMP_RESOURCE_TABLE_SIZE": (
                fw_rsc["CFG_RSCTBL_MAP_SIZE"], agent_rsc["CFG_RSCTBL_MAP_SIZE"]),
            "RZV_OPENAMP_RPMSG_MEM_BASE": (
                fw["RPMSG_MEM_BASE"], agent["UC3_RPMSG_MEM_BASE"]),
            "RZV_OPENAMP_RPMSG_MEM_SIZE": (
                fw["RPMSG_MEM_SIZE"], agent["UC3_RPMSG_MEM_SIZE"]),
            "RZV_OPENAMP_VRING0_BASE": (
                fw["CFG_VRING0_BASE0_PA"], agent["CFG_VRING0_BASE0"]),
            "RZV_OPENAMP_VRING1_BASE": (
                fw["CFG_VRING1_BASE0_PA"], agent["CFG_VRING1_BASE0"]),
            "RZV_OPENAMP_T1_VRING0_BASE": (
                fw["CFG_VRING0_BASE1_PA"], agent["CFG_VRING0_BASE1"]),
            "RZV_OPENAMP_T1_VRING1_BASE": (
                fw["CFG_VRING1_BASE1_PA"], agent["CFG_VRING1_BASE1"]),
            "RZV_OPENAMP_RPMSG_NUM_BUFS": (
                fw["CFG_RPMSG_NUM_BUFS0"], agent["CFG_RPMSG_NUM_BUFS0"]),
            "RZV_OPENAMP_SHM_BASE": (
                fw["CFG_VRING_SHM_BASE0_PA"], fw["CFG_VRING_SHM_BASE0_PA"]),
        }
        for name, (fw_value, agent_value) in pairs.items():
            with self.subTest(name=name):
                self.assertEqual(self.nuttx(name), number(fw_value))
                self.assertEqual(self.nuttx(name), number(agent_value))

        # Both tables use the same buffer count and ring alignment.
        self.assertEqual(number(fw["CFG_RPMSG_NUM_BUFS1"]),
                         self.nuttx("RZV_OPENAMP_RPMSG_NUM_BUFS"))
        self.assertEqual(number(agent["CFG_RPMSG_NUM_BUFS1"]),
                         self.nuttx("RZV_OPENAMP_RPMSG_NUM_BUFS"))
        for align in ("CFG_VRING_ALIGN0", "CFG_VRING_ALIGN1"):
            self.assertEqual(number(fw[align]),
                             self.nuttx("RZV_OPENAMP_VRING_ALIGN"))

        self.assertEqual(number(fw["VRING_NOTIFYID0"]), 0)
        self.assertEqual(number(fw["VRING_NOTIFYID1"]), 1)
        self.assertEqual(number(agent["VRING_NOTIFYID0"]), 0)
        self.assertEqual(number(agent["VRING_NOTIFYID1"]), 1)

    def test_vdev_header_matches_agent_table(self) -> None:
        agent_rsc = defines(read(AGENT_RSC))
        self.assertEqual(self.nuttx("RZV_OPENAMP_RPMSG_FEATURES"),
                         number(agent_rsc["RPMSG_IPU_C0_FEATURES"]))
        self.assertEqual(self.nuttx("RZV_OPENAMP_VIRTIO_ID_RPMSG"),
                         number(agent_rsc["VIRTIO_ID_RPMSG_"]))
        self.assertEqual(self.nuttx("RZV_OPENAMP_NUM_VRINGS"),
                         number(agent_rsc["NUM_VRINGS"]))
        self.assertEqual(self.nuttx("RZV_OPENAMP_NUM_TABLE_ENTRIES"),
                         number(agent_rsc["NUM_TABLE_ENTRIES"]))
        # Two back-to-back tables, as resources_init[2] in rsc_table.c.
        self.assertIn("resources_init[]", read(REF_FW_RSC_C))
        self.assertEqual(self.nuttx("RZV_OPENAMP_NUM_RESOURCE_TABLES"), 2)

    def test_endpoint_names_match_agent(self) -> None:
        agent = defines(read(AGENT_CFG))
        self.assertEqual(string(self.hdr["RZV_OPENAMP_RPC_EPT_NAME"]),
                         string(agent["CFG_RPMSG_SVC_NAME0"]))
        self.assertEqual(string(self.hdr["RZV_OPENAMP_UXRCE_EPT_NAME"]),
                         string(agent["CFG_RPMSG_SVC_NAME1"]))

    def test_transport_drops_exactly_the_agent_handshake(self) -> None:
        # The string the agent sends on the UXRCE endpoint, strlen + 1 bytes
        # (with its NUL); the RPC and MAVLink endpoints send other strings.
        sent = re.search(
            r'handshake_msg\s*=\s*"([^"]+)";\s*'
            r'int\s+send_ret\s*=\s*rpmsg_send_retry\(\s*&rp_ept_uxrce,\s*'
            r'handshake_msg,\s*strlen\(handshake_msg\)\s*\+\s*1',
            read(AGENT_MAIN))
        self.assertIsNotNone(sent)

        transport = read(CLIENT / "rpmsg_transport.cpp")
        expected = re.search(r'kAgentHandshake\[\]\s*=\s*"([^"]+)"', transport)
        self.assertIsNotNone(expected)
        self.assertEqual(expected.group(1), sent.group(1))
        # sizeof() of the array includes the NUL, matching strlen + 1.
        self.assertIn("sizeof(kAgentHandshake)", transport)

    def test_link_follows_agent_departure_and_return(self) -> None:
        # The agent clears DRIVER_OK on exit; CR8-0 must stop notifying the
        # CA55 and restore the tables, then wait for the next agent.
        ipc = read(RZV / "rzv_ipc.c")
        body = re.search(r"static int rzv_rptun_link_thread\(.*?\n}\n",
                         ipc, re.DOTALL)
        self.assertIsNotNone(body)
        text = body.group(0)
        order = [text.index(k) for k in (
            "rzv_openamp_master_ready", "rzv_openamp_link_arm",
            "RPTUNIOC_START", "rzv_openamp_master_replaced",
            "rzv_rptun_stop_and_wait", "rzv_openamp_link_adopt",
            "rzv_openamp_vrings_reset", "rzv_openamp_resource_table_init")]
        self.assertEqual(order, sorted(order))
        self.assertIn("for (; ; )", text)
        self.assertIn("RPTUNIOC_STOP", ipc)
        # The rptun node has no read/write ops: any access flag makes
        # inode_checkflags() fail the open with -EACCES (seen on target).
        self.assertIn("file_open(&filep, RZV_RPTUN_DEV_PATH, 0);", ipc)
        rptun = read(NUTTX / "drivers/rptun/rptun.c")
        ops = re.search(r"g_rptun_devops =\n{(.*?)};", rptun, re.DOTALL)
        self.assertIsNotNone(ops)
        self.assertRegex(ops.group(1), r"NULL,\s*/\* write \*/")
        # Boot clears ring indices left in DDR before publishing the table.
        rproc = read(RZV / "rzv_rproc.c")
        self.assertLess(rproc.index("rzv_openamp_vrings_reset();"),
                        rproc.index("rzv_openamp_resource_table_init();"))

    def test_killed_agent_takeover_needs_no_ca55_change(self) -> None:
        # A successor agent keeps DRIVER_OK set; CR8-0 refuses sends once
        # it sees the takeover, and stopping must not wait on a dead
        # master for a name-service DESTROY buffer.
        rpmsg = read(RZV / "rzv_rpmsg.c")
        send = re.search(r"ssize_t rzv_rpmsg_send\(.*?\n}\n", rpmsg,
                         re.DOTALL).group(0)
        self.assertLess(send.index("rzv_openamp_master_replaced()"),
                        send.index("rpmsg_trysend"))
        destroy = re.search(r"static void rzv_rpmsg_device_destroy\(.*?\n}\n",
                            rpmsg, re.DOTALL).group(0)
        self.assertLess(destroy.index("rdev->support_ns = 0;"),
                        destroy.index("rpmsg_destroy_ept"))

    def test_client_drains_rx_and_never_sleeps_on_tx(self) -> None:
        transport = read(CLIENT / "rpmsg_transport.cpp")
        write_cb = re.search(r"RpmsgTransport::write_cb\(.*?\n}\n",
                             transport, re.DOTALL).group(0)
        self.assertNotIn("usleep", write_cb)
        self.assertIn("rzv_rpmsg_uxrce_rx_dropped()", transport)
        client = read(CLIENT / "uxrce_dds_client.cpp")
        self.assertRegex(client,
                         r"CONFIG_RZV_RPMSG_RX_QUEUE_DEPTH\s*&&\s*"
                         r"_transport_rpmsg->rx_pending\(\)")


if __name__ == "__main__":
    unittest.main()
