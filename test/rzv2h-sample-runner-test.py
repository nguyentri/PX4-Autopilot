#!/usr/bin/env python3
"""Exercise evidence failures independently of any board connection."""

import hashlib
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sample_checker", ROOT / "platforms/nuttx/Debug/rzv2h-sample-runner.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def profile():
    return {
        "profile": "scif-internal-loopback-rtt", "mode": "scif-internal-loopback",
        "invocation": {"command": "hwtest"}, "evidence_class": "function",
        "required_case_ids": ["scif.function_internal_loopback", "scif.function_close_reopen"],
        "expected_summary": {"passed": 2, "failed": 0, "skipped": 0},
        "target_state_types": {"loop": "integer", "case_fds": "integer",
                               "case_irqs": "integer",
                               "rxi_delta": "integer", "txi_delta": "integer"},
        "target_state_required": {"loop": 0, "case_fds": 0, "case_irqs": 0,
                                  "rxi_delta": {"op": "gt", "value": 0},
                                  "txi_delta": {"op": "gt", "value": 0}},
    }


def transcript():
    return """RUN_BEGIN: example
TEST_ENV: mode=scif-internal-loopback expects=controller-internal
TEST: scif.function_internal_loopback START
TEST: scif.function_internal_loopback PASS
TEST: scif.function_close_reopen START
TEST_STATE: loop=0 case_fds=0 case_irqs=0 rxi_delta=7 txi_delta=8
TEST: scif.function_close_reopen PASS
TEST_SUMMARY: passed=2 failed=0 skipped=0
TEST_DONE: exit=0
RUN_END: example
nsh>\x20
"""


HEALTH = "nsh> ps\n PID GRP PRI POLICY TYPE STATE COMMAND\n 1 1 100 RR task Waiting nsh_main\nnsh> free\nnsh> "


def receipt(text, health=HEALTH):
    return {"profile": "scif-internal-loopback-rtt", "run_id": "example",
            "health_run_id": "example", "command": "hwtest", "foreground": True,
            "timed_out": False, "elf_sha256": "a" * 64,
            "transcript_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "health_sha256": hashlib.sha256(health.encode()).hexdigest(),
            "target_prerequisites_verified": True, "resolved_config_verified": True,
            "artifact_authorized": True,
            "cleanup": {"bridge_stopped": True, "owned_pid_dead": True, "port_free": True}}


class EvidenceTests(unittest.TestCase):
    def check(self, text=None, health=HEALTH, p=None, r=None):
        text = transcript() if text is None else text
        return CHECKER.check_profile(profile() if p is None else p, text, health,
                                     receipt(text, health) if r is None else r)

    def rejected(self, text=None, health=HEALTH, p=None, r=None):
        with self.assertRaises(CHECKER.EvidenceError):
            self.check(text, health, p, r)

    def test_complete_evidence(self):
        self.assertEqual(self.check()["status"], "PASS")

    def test_echoed_boundary_text_is_outside_bare_markers(self):
        text = "nsh> echo RUN_BEGIN: example\nfatal echoed argument\n" + transcript()
        self.assertEqual(self.check(text=text)["status"], "PASS")

    def test_missing_required_case(self):
        self.rejected(transcript().replace("TEST: scif.function_close_reopen PASS\n", ""))

    def test_all_skip_cannot_pass_exit_zero(self):
        self.rejected(transcript().replace(" PASS", " SKIP"))

    def test_required_fail(self):
        self.rejected(transcript().replace("loopback PASS", "loopback FAIL"))

    def test_duplicate_result(self):
        self.rejected(transcript().replace("TEST_SUMMARY:",
                      "TEST: scif.function_close_reopen PASS\nTEST_SUMMARY:"))

    def test_terminal_requires_start(self):
        self.rejected(transcript().replace("TEST: scif.function_close_reopen START\n", ""))

    def test_unknown_case(self):
        self.rejected(transcript().replace("scif.function_close_reopen", "scif.unknown"))

    def test_wrong_counts(self):
        self.rejected(transcript().replace("passed=2", "passed=3"))

    def test_wrong_mode(self):
        self.rejected(transcript().replace("mode=scif-internal-loopback", "mode=uart-loopback"))

    def test_missing_terminal(self):
        self.rejected(transcript().replace("TEST_DONE: exit=0\n", ""))

    def test_duplicate_terminal(self):
        self.rejected(transcript().replace("TEST_DONE: exit=0", "TEST_DONE: exit=0\nTEST_DONE: exit=0"))

    def test_out_of_order_terminal(self):
        self.rejected(transcript().replace("TEST_ENV:", "TEST_DONE: exit=0\nTEST_ENV:")
                      .replace("TEST_DONE: exit=0\nRUN_END:", "RUN_END:"))

    def test_missing_prompt(self):
        self.rejected(transcript().replace("nsh> ", ""))

    def test_stale_boundaries(self):
        self.rejected(transcript().replace("RUN_BEGIN: example", "RUN_BEGIN: previous"))

    def test_duplicate_boundaries(self):
        self.rejected(transcript() + "RUN_END: example\n")

    def test_wrong_saved_log_hash(self):
        r = receipt(transcript()); r["transcript_sha256"] = "0" * 64
        self.rejected(r=r)

    def test_counter_must_be_positive_integer(self):
        for value in ("0", "-1", ">0", "true", "1.0"):
            with self.subTest(value=value):
                self.rejected(transcript().replace("rxi_delta=7", "rxi_delta=" + value))

    def test_missing_target_state(self):
        self.rejected(transcript().replace(" rxi_delta=7", ""))

    def test_duplicate_target_state(self):
        self.rejected(transcript().replace("rxi_delta=7", "rxi_delta=7 rxi_delta=9"))

    def test_live_irq_is_not_cleanup(self):
        self.rejected(transcript().replace("case_irqs=0", "case_irqs=1"))

    def test_host_cleanup_is_distinct(self):
        for field in ("bridge_stopped", "owned_pid_dead", "port_free"):
            r = receipt(transcript()); r["cleanup"][field] = False
            with self.subTest(field=field):
                self.rejected(r=r)

    def test_timeout_is_not_cancellation(self):
        r = receipt(transcript()); r["timed_out"] = True
        self.rejected(r=r)

    def test_foreground_must_be_proven(self):
        r = receipt(transcript()); r["foreground"] = False
        self.rejected(r=r)

    def test_remaining_task(self):
        self.rejected(health=HEALTH.replace("nsh_main", "hwtest"))

    def test_missing_ps(self):
        self.rejected(health="nsh> ")

    def test_unrelated_task_name(self):
        self.assertEqual(self.check(health=HEALTH.replace("nsh_main", "hwtest-helper"))["status"], "PASS")

    def test_stale_health(self):
        r = receipt(transcript()); r["health_run_id"] = "previous"
        self.rejected(r=r)

    def test_unexpected_error(self):
        self.rejected(transcript().replace("TEST_STATE:", "ERROR: IRQ leaked\nTEST_STATE:"))

    def test_expected_guard_error_is_scoped(self):
        p = profile(); p["allowed_diagnostics_by_case"] = {
            "scif.function_close_reopen": [r"ERROR: expected invalid setting"]}
        text = transcript().replace("TEST_STATE:", "ERROR: expected invalid setting\nTEST_STATE:")
        self.assertEqual(self.check(text=text, p=p)["status"], "PASS")
        self.rejected(text=text, p=profile())

    def test_fatal_never_whitelisted(self):
        p = profile(); p["allowed_diagnostics_by_case"] = {
            "scif.function_close_reopen": [".*"]}
        self.rejected(transcript().replace("TEST_STATE:", "fatal data abort\nTEST_STATE:"), p=p)

    def test_unverified_admission_or_authority(self):
        for key in ("target_prerequisites_verified", "resolved_config_verified", "artifact_authorized"):
            r = receipt(transcript()); r[key] = False
            with self.subTest(key=key):
                self.rejected(r=r)

    def test_legacy_grammar(self):
        p = profile(); p["mode"] = "spi-loopback"; p["evidence_class"] = "legacy"
        p["target_state_types"] = {}; p["target_state_required"] = {}
        ids = ["spi.ch0.byte_loop_1mhz", "spi.ch0.byte_loop_4mhz",
               "spi.ch0.burst_64_pattern", "spi.ch0.mode3"]
        p["required_case_ids"] = ids; p["expected_summary"]["passed"] = 4
        text = "RUN_BEGIN: example\nTEST_ENV: mode=spi-loopback expects=controller-internal\n"
        text += "".join("TEST: " + i + " START\nTEST: " + i + " PASS\n" for i in ids)
        text += "TEST_SUMMARY: passed=4 failed=0 skipped=0\nTEST_DONE: exit=0\nRUN_END: example\nnsh> "
        self.assertEqual(self.check(text, p=p)["cases"], ids)


class NativeSuiteContracts(unittest.TestCase):
    def test_unknown_and_prefix_aliases_do_not_select_a_hil_suite(self):
        for name in ('unknown-instance','hil-new','hil-spi-unreviewed'):
            with self.subTest(name=name), self.assertRaisesRegex(CHECKER.EvidenceError, 'unknown native hwtest suite'):
                CHECKER.native_cases({'profile':name})

    def test_known_hil_full_keeps_all_concatenated_sensor_cases(self):
        contract=CHECKER.native_cases({'profile':'hil-full'})
        self.assertEqual(contract['mode'],'hil-full')
        self.assertEqual(contract['expected_summary']['passed'],len(contract['required_case_ids']))
        self.assertEqual(len(contract['required_case_ids']),len(set(contract['required_case_ids'])))
        self.assertGreater(len(contract['required_case_ids']),0)


if __name__ == "__main__":
    unittest.main()
