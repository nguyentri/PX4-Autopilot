#!/usr/bin/env python3
"""Check saved RTT sample evidence. This program never connects to a target."""

import argparse
import hashlib
import json
import re
import shlex
from pathlib import Path


class EvidenceError(ValueError):
    """Evidence is incomplete, contradictory or from another invocation."""


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def bounded_run(text, run_id):
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id) is not None,
            "invalid run identifier")
    begin_markers = list(re.finditer(r"(?m)^[ \t]*RUN_BEGIN: (\S+)[ \t]*$", text))
    end_markers = list(re.finditer(r"(?m)^[ \t]*RUN_END: (\S+)[ \t]*$", text))
    require([marker[1] for marker in begin_markers] == [run_id] and
            [marker[1] for marker in end_markers] == [run_id],
            "missing, duplicate or stale invocation boundaries")
    body_start = begin_markers[0].start()
    body_end = end_markers[0].start()
    require(body_start < body_end, "reversed invocation boundaries")
    require("nsh>" in text[body_end:], "no prompt after invocation completion")
    return text[body_start:body_end]


def decode_state(text, profile):
    state = {}
    for payload in re.findall(r"TEST_STATE:\s*([^\r\n]+)", text):
        for token in shlex.split(payload):
            require("=" in token, "malformed state token")
            key, value = token.split("=", 1)
            require(key not in state, "duplicate state field: " + key)
            kind = profile["target_state_types"].get(key)
            require(kind is not None, "unexpected state field: " + key)
            if kind in ("integer", "integer-predicate"):
                require(re.fullmatch(r"-?\d+", value) is not None,
                        "state counter is not an integer: " + key)
                value = int(value)
            elif kind == "boolean":
                require(value in ("true", "false"), "invalid boolean: " + key)
                value = value == "true"
            elif kind == "array":
                value = value.split(",")
            state[key] = value

    require(set(state) == set(profile["target_state_required"]),
            "missing target-state fields")
    for key, expected in profile["target_state_required"].items():
        actual = state[key]
        if isinstance(expected, dict):
            require(expected.get("op") == "gt" and type(actual) is int and
                    actual > expected["value"], "counter predicate failed: " + key)
        else:
            require(type(actual) is type(expected) and actual == expected,
                    "target-state mismatch: " + key)
    return state


def check_diagnostics(text, profile):
    fatal = r"(?i)\b(fatal|panic|data abort|hardfault|assertion failed)\b"
    require(re.search(fatal, text) is None, "fatal diagnostic")
    active = None
    permitted = profile.get("allowed_diagnostics_by_case", {})
    for line in text.splitlines():
        event = re.search(r"TEST:\s+(\S+)\s+(START|PASS|FAIL|SKIP)\b", line)
        if event and event[2] == "START":
            active = event[1]
        if re.search(r"\b(ERROR|FAILURE):", line):
            allowed = any(re.search(pattern, line)
                          for pattern in permitted.get(active, []))
            require(allowed, "unexpected error diagnostic: " + line.strip())
        if event and event[2] != "START":
            active = None
    for pattern in profile.get("forbidden_patterns", []):
        require(re.search(pattern, text) is None, "forbidden diagnostic: " + pattern)


def check_profile(profile, transcript, health, receipt):
    require(receipt.get("profile") == profile["profile"], "wrong receipt profile")
    require(receipt.get("command") == profile["invocation"]["command"],
            "wrong invocation command")
    require(receipt.get("foreground") is True, "foreground execution unproved")
    require(receipt.get("timed_out") is False, "timeout is not task cancellation")
    require(re.fullmatch(r"[0-9a-f]{64}", receipt.get("elf_sha256", "")) is not None,
            "missing exact ELF hash")
    require(receipt.get("transcript_sha256") ==
            hashlib.sha256(transcript.encode()).hexdigest(), "transcript hash mismatch")
    require(receipt.get("health_sha256") == hashlib.sha256(health.encode()).hexdigest(),
            "post-run health hash mismatch")
    require(receipt.get("target_prerequisites_verified") is True,
            "target admission prerequisites unverified")
    require(receipt.get("resolved_config_verified") is True,
            "resolved console/mode/builtin configuration unverified")
    require(receipt.get("artifact_authorized") is True,
            "artifact action authority unrecorded")
    for field in ("bridge_stopped", "owned_pid_dead", "port_free"):
        require(receipt.get("cleanup", {}).get(field) is True,
                "host cleanup incomplete: " + field)

    body = bounded_run(transcript, receipt.get("run_id", ""))
    env = re.findall(r"TEST_ENV:\s+mode=(\S+)\s+expects=([^\r\n]+)", body)
    require(len(env) == 1 and env[0][0] == profile["mode"], "wrong or duplicate mode")
    events = re.findall(r"TEST:\s+(\S+)\s+(START|PASS|FAIL|SKIP)\b", body)
    required = profile["required_case_ids"]
    require(required and len(required) == len(set(required)), "invalid case manifest")
    require(set(case for case, _ in events) == set(required), "case IDs differ from manifest")
    active = None
    completed = []
    for case, event in events:
        if event == "START":
            require(active is None and case not in completed, "duplicate or overlapping case")
            active = case
        else:
            require(active == case, "terminal without matching case start")
            require(event == "PASS", "required case did not pass: " + case)
            completed.append(case)
            active = None
    require(active is None and len(completed) == len(required), "incomplete required cases")
    summaries = re.findall(r"TEST_SUMMARY:\s+passed=(\d+)\s+failed=(\d+)\s+skipped=(\d+)", body)
    expected = profile["expected_summary"]
    require(len(summaries) == 1 and tuple(map(int, summaries[0])) ==
            (expected["passed"], expected["failed"], expected["skipped"]),
            "summary counts differ from manifest")
    require(re.findall(r"TEST_DONE:\s+exit=(-?\d+)", body) == ["0"],
            "missing, duplicate or unsuccessful terminal")
    require(body.rfind("TEST_DONE:") > body.rfind("TEST_SUMMARY:") and
            body.rfind("TEST_SUMMARY:") > body.rfind("TEST: "),
            "terminal sequence is out of order")
    check_diagnostics(body, profile)
    state = decode_state(body, profile)
    require(receipt["run_id"] == receipt.get("health_run_id"), "stale post-run health")
    require(re.search(r"\bPID\b.*\b(COMMAND|NAME)\b", health) is not None,
            "post-run ps table is missing")
    require("nsh>" in health, "post-run health prompt missing")
    for line in health.splitlines():
        if re.match(r"\s*\d+\s", line):
            require(re.search(r"(?:^|\s)(?:\S*/)?hwtest(?:\s|$)", line) is None,
                    "test task remains after foreground completion")
    check_diagnostics(health, profile)
    return {"status": "PASS", "profile": profile["profile"],
            "run_id": receipt["run_id"], "elf_sha256": receipt["elf_sha256"],
            "cases": completed, "state": state,
            "evidence_class": profile["evidence_class"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--health", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        profiles = [p for p in manifest["profiles"] if p["profile"] == args.profile]
        require(manifest.get("schema_version") == 1 and len(profiles) == 1,
                "unknown or duplicate profile")
        result = check_profile(profiles[0], args.transcript.read_text(),
                               args.health.read_text(), json.loads(args.receipt.read_text()))
        code = 0
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as error:
        result = {"status": "NOT-PASS", "profile": args.profile, "reason": str(error)}
        code = 1
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    print(output, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
