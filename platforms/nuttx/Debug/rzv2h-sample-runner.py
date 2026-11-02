#!/usr/bin/env python3
"""Check saved RTT sample evidence. This program never connects to a target."""

import argparse
import hashlib
import importlib.util
import json
import re
import shlex
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'runner_inventory', Path(__file__).with_name('rzv2h-sample-inventory.py'))
INVENTORY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(INVENTORY)


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


def check_dmac(profile, body):
    expected = [channel for batch in INVENTORY.dmac_batches(profile) for channel in batch]
    actual = [int(x) for x in re.findall(r'PASS: DMAC memcpy ch=(\d+)\b', body)]
    require(actual == expected, 'DMAC copy comparison/channel coverage mismatch')
    return actual


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


def native_cases(profile, legacy=None, catalog=None):
    """Existing suite IDs, read from the source-backed installed contract."""
    here = Path(__file__).parent
    if profile.get('hwtest_contract') is not None:
        return profile['hwtest_contract']
    if profile.get('legacy_profile'):
        legacy = legacy if legacy is not None else json.loads((here/'rzv2h-sample-profiles.json').read_text())
        matches = [x for x in legacy['profiles'] if x['profile'] == profile['legacy_profile']]
        require(len(matches) == 1, 'unknown or duplicate legacy suite')
        return matches[0]
    catalog = catalog if catalog is not None else json.loads((here/'rzv2h-driver-coverage.json').read_text())
    name = profile['profile']
    require(name in catalog.get('native_hwtest_contracts', {}), 'unknown native hwtest suite: ' + name)
    return catalog['native_hwtest_contracts'][name]


def native_body(text, run_id, shell):
    require(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id or '') is not None, 'invalid run identifier')
    begin = list(re.finditer(r'(?m)^RUN_BEGIN: (\S+)\s*$', text))
    end = list(re.finditer(r'(?m)^RUN_END: (\S+)\s*$', text))
    require(len(begin) == len(end) == 1 and begin[0][1] == end[0][1] == run_id and
            begin[0].end() < end[0].start(), 'stale or incomplete native run boundaries')
    if shell:
        require('nsh>' in text[end[0].end():], 'native returned prompt missing')
    return text[begin[0].end():end[0].start()]


def check_native(profile, transcript, health, receipt, admission):
    require(profile['mode'] != 'blocked', 'profile has an unresolved execution route')
    require(admission['status'] == 'BUILD-CHECKED' and receipt.get('profile') == profile['profile'],
            'native artifact/profile mismatch')
    for key in ('elf_sha256', 'config_sha256', 'source_state_sha256'):
        require(receipt.get(key) == admission[key], 'native artifact hash mismatch: ' + key)
    contracts = admission.get('contract_inputs', [])
    if contracts:
        require(receipt.get('contract_inputs') == contracts, 'run archived contract binding mismatch')
    else:
        require(not receipt.get('contract_inputs'), 'historical evidence cannot acquire contract completeness')
    if 'instance_id' in profile:
        require(bool(contracts), 'instance evidence requires archived contracts')
        for key in ('instance_id', 'instance'):
            require(receipt.get(key) == profile[key] == admission.get(key), 'run instance mismatch: ' + key)
        require(receipt.get('core') == profile['core'] == admission.get('core'), 'run instance core mismatch')
    here = Path(__file__).resolve().parent
    installed = json.loads((here/'rzv2h-all-sample-configs.json').read_text())
    require(profile in installed['profiles'], 'native contract differs from reviewed installed policy')
    if contracts:
        reviewed = [dict(role=role, path=archived,
                         sha256=hashlib.sha256((here/source).read_bytes()).hexdigest())
                    for role, archived, source in (
                        ('selected_manifest','sample-profiles.json','rzv2h-all-sample-configs.json'),
                        ('legacy_contract','legacy-sample-profiles.json','rzv2h-sample-profiles.json'),
                        ('driver_coverage','driver-coverage.json','rzv2h-driver-coverage.json'))]
        require(contracts == reviewed, 'archived contract differs from reviewed installed policy inputs')
    for key, path in (('policy_sha256',here/'rzv2h-all-sample-configs.json'),
                      ('executor_sha256',here/'rzv2h-sample-lab.py')):
        require(receipt.get(key) == hashlib.sha256(path.read_bytes()).hexdigest(),
                'reviewed native tool/policy digest mismatch: ' + key)
    require(receipt.get('commands') == profile['commands'], 'unapproved native command list')
    for name, content in (('transcript', transcript), ('health', health)):
        require(receipt.get(name+'_sha256') == hashlib.sha256(content.encode()).hexdigest(), name+' hash mismatch')
    require(receipt.get('timed_out') is False and receipt.get('approval_reference'), 'timeout or authority missing')
    require(receipt.get('reset_class') == 'warm-load' and receipt.get('initial_state'), 'initial/reset state missing')
    require(all(receipt.get('cleanup', {}).get(x) is True for x in
                ('bridge_stopped','owned_pid_dead','port_free')), 'native host cleanup incomplete')
    body = native_body(transcript, receipt.get('run_id'), profile['console'] != 'rtt-output')
    require(re.search(r'(?i)\b(panic|data abort|hardfault|assertion failed|fatal)\b', transcript+health) is None,
            'fatal native diagnostic')
    expected_negative = profile['oracle'] == 'canfd' and profile['evidence_class'] == 'missing-ack'
    if not expected_negative and profile['oracle'] != 'hwtest':
        require(re.search(r'(?im)\b(?:ERROR|FAILURE):|\bFAIL\b|TEST:\s+\S+\s+SKIP\b', body+health) is None,
                'native error/skip diagnostic')
    shell = profile['entrypoint'] == 'nsh_main'
    if shell:
        require(re.search(r'\bPID\b.*\b(COMMAND|NAME)\b', health) and 'nsh>' in health, 'native post-run ps missing')
        if profile.get('builtin'):
            for line in health.splitlines():
                if re.match(r'\s*\d+\s', line):
                    require(re.search(r'(?:^|\s)'+re.escape(profile['builtin']['name'])+r'(?:\s|$)', line) is None,
                            'native task remains after completion')
    if not shell or (profile['commands'] and not admission['waitpid'] and profile['mode'] != 'shell'):
        count = re.findall(r'TASK_HEALTH_BEGIN count=(\d+)', health)
        require(len(count) == 1 and 0 < int(count[0]) <= 256 and 'TASK_HEALTH_END' in health,
                'boot task census missing or incomplete')
        entries = [int(x,16) & ~1 for x in re.findall(r'TASK_ENTRY: (0x[0-9a-f]+)', health)]
        require(int(admission['application_entry'],16) & ~1 not in entries, 'boot application is still alive')
    exits = [(int(index),int(status)) for index,status in
             re.findall(r'(?m)^APP_EXIT_(\d+)=(-?\d+)\s*$', body)]
    if profile['commands'] and admission['waitpid']:
        require(exits == [(index,1 if expected_negative else 0) for index in range(len(profile['commands']))],
                'real command exit status mismatch')
    elif profile['commands'] and profile['mode'] != 'shell':
        require(receipt.get('completion_source') == 'task-resource-oracle', 'asynchronous completion unproved')
    oracle = profile['oracle']
    state = {}
    if oracle == 'hwtest':
        spec = admission.get('hwtest_contract') or native_cases(profile)
        require(spec == profile.get('hwtest_contract', spec), 'archived hwtest contract mismatch')
        check_diagnostics(body, spec)
        check_diagnostics(health, spec)
        env = re.findall(r'TEST_ENV:\s+mode=(\S+)', body)
        require(env == [spec['mode']], 'native hwtest mode mismatch')
        events = re.findall(r'TEST:\s+(\S+)\s+(START|PASS|FAIL|SKIP)\b', body)
        expected = [(case, event) for case in spec['required_case_ids'] for event in ('START','PASS')]
        require(events == expected, 'native hwtest exact cases/order mismatch')
        require(re.findall(r'TEST_SUMMARY:\s+passed=(\d+)\s+failed=(\d+)\s+skipped=(\d+)', body) ==
                [tuple(str(spec['expected_summary'][k]) for k in ('passed','failed','skipped'))], 'native hwtest counts mismatch')
        require(re.findall(r'TEST_DONE:\s+exit=(-?\d+)', body) == ['0'], 'native hwtest terminal mismatch')
        require(body.rfind('TEST_DONE:') > body.rfind('TEST_SUMMARY:') > body.rfind('TEST: '),
                'native hwtest terminal sequence is out of order')
        if spec['target_state_required']:
            state = decode_state(body, spec)
    elif oracle == 'can':
        ids = [(int(a),int(b)) for a,b in re.findall(r'ID:\s+(\d+)\s+DLC:\s+(\d+)', body)]
        expected = [(i,i) for i in range(1,5)]
        ok = [(int(a),int(b)) for a,b in re.findall(r'ID:\s+(\d+)\s+DLC:\s+(\d+) -- OK', body)]
        require('Terminating!' in body, 'CAN termination missing')
        if ok:
            require(ok == expected and ids == [x for item in expected for x in (item,item,item)], 'CAN loopback IDs/DLC differ')
        else:
            require(ids == [x for item in expected for x in (item,item)], 'CAN transmit/receive IDs differ')
            chunks = re.findall(r'Data received:\s*\n((?:\s*\d+: 0x[0-9a-fA-F]+\s*\n?)+)', body)
            require(len(chunks) == 4, 'CAN payload groups missing')
            first = 0
            for length, chunk in enumerate(chunks, 1):
                values = [int(x,16) for x in re.findall(r'\d+: 0x([0-9a-fA-F]+)',chunk)]
                require(values == list(range(first,first+length)), 'CAN payload mismatch')
                first += length
    elif oracle == 'canfd':
        require(re.findall(r'FAIL frames=(\d+)/(\d+) result=(\d+)',body) == [('0','82','116')],
                'missing-ACK outcome differs')
        require(re.search(r'cleanup seq=\d+ failed=\d+ result=-140 isolated=1',body), 'CAN cancellation/isolation missing')
    elif oracle == 'dmac':
        state['dmac_channels'] = check_dmac(profile, body)
    elif oracle == 'timer':
        require(all(x in body for x in ('Start the timer','Stop the timer','Finished')), 'timer lifecycle incomplete')
        signals = [int(x) for x in re.findall(r'nsignals:\s*(\d+)',body)]
        require(len(signals) == 24 and signals[0] == 0 and max(signals) > 0 and
                signals == sorted(signals), 'timer sample count/notifications did not progress')
    elif oracle == 'adc':
        require(re.findall(r'channel:\s*(\d+) value:\s*-?\d+',body) == ['0','1','2','3'], 'ADC scan records mismatch')
    elif oracle == 'gy912':
        results = re.findall(r'ICM20948 result=(-?\d+) samples=(\d+)/(\d+) IRQ=(\d+)', body)
        require(results and [(int(result), int(samples), int(total))
                             for result, samples, total, _ in results] ==
                [(0,1,1),(0,20,20),(0,20,20)], 'sensor result/count mismatch')
        irqs = re.findall(r'ICM20948 result=.*? IRQ=(\d+)', body)
        require(all(int(irq) > 0 for irq in irqs), 'sensor IRQ did not progress')
        require(len(re.findall(r'ICM20948 sample=',body)) == 41, 'sensor sample records missing')
    elif oracle == 'bmm150':
        require(body.count('bmm150: scan PASS') == body.count('bmm150: PASS') == 1 and
                'bmm150: self-test X:pass Y:pass Z:pass' in body,
                'BMM150 scan/self-test result missing')
        require(re.findall(r'bmm150: \[(\d+)\] uT',body) == [str(x) for x in range(20)] and
                re.search(r'bmm150: 20 valid, \d+ not-ready, \d+ overflow',body),
                'BMM150 sample count mismatch')
        require(len(re.findall(r'rhall=([1-9]\d*)',body)) == 20, 'BMM150 sample data missing')
    elif oracle == 'bmp280':
        # Whole-line grammar: echoed command text cannot satisfy any record.
        lines = [x.strip() for x in body.splitlines()]
        ident = 'bmp280: addr 0x76 chip ID 0x58 (BMP280)'
        require(lines.count(ident) == 1, 'BMP280 address/chip ID missing')
        records = [(n, re.fullmatch(r'bmp280: \[(\d+)\] T=(-?\d{1,3}\.\d{2}) degC P=(\d{5,6}\.\d{2}) Pa', x))
                   for n, x in enumerate(lines) if x.startswith('bmp280: [')]
        require(len(records) == 10 and all(m for _, m in records) and
                [int(m[1]) for _, m in records] == list(range(10)), 'BMP280 sample count/order mismatch')
        require(all(-40 <= float(m[2]) <= 85 and 30000 <= float(m[3]) <= 110000 for _, m in records),
                'BMP280 sample outside the datasheet envelope')
        require(lines.count('bmp280: 10 samples') == 1 and lines.count('bmp280: PASS') == 1,
                'BMP280 sample summary/terminal missing')
        require(lines.index(ident) < records[0][0] and records[-1][0] < lines.index('bmp280: 10 samples') <
                lines.index('bmp280: PASS'), 'BMP280 records out of order')
    elif oracle == 'spi-board':
        require('SPI Loopback example completed successfully' in body, 'board SPI compare incomplete')
    elif oracle == 'shell':
        require(re.search(r'\btotal\b.*\bused\b.*\bfree\b',body,re.I) and re.search(r'\bPID\b',body), 'shell/heap response missing')
    else:
        raise EvidenceError('native oracle not implemented: ' + oracle)
    return {'profile':profile['profile'], 'status':'PASS', 'run_id':receipt['run_id'],
            'elf_sha256':admission['elf_sha256'], 'evidence_class':profile['evidence_class'],
            'reset_class':receipt['reset_class'], 'state':state,
            'contract_inputs': contracts,
            **{key:profile[key] for key in ('instance_id', 'instance') if key in profile}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--health", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive", type=Path, help='native build archive; required for schema 2')
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        profiles = [p for p in manifest["profiles"] if p["profile"] == args.profile]
        require(manifest.get("schema_version") in (1,2) and len(profiles) == 1,
                "unknown or duplicate profile")
        if manifest.get('schema_version') == 2:
            import importlib.util
            spec = importlib.util.spec_from_file_location('artifacts', Path(__file__).with_name('rzv2h-sample-artifact-check.py'))
            artifacts = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(artifacts)
            require(args.archive is not None, 'native archived inputs required')
            contracts = artifacts.INVENTORY.archived_contracts(args.archive/'source-state.json')
            artifacts.INVENTORY.validate(manifest, catalog=contracts.get('driver_coverage'), live=False)
            admission = artifacts.verify_native(profiles[0], args.archive/'builds'/args.profile,
                                                args.archive/'source-state.json', manifest)
            result = check_native(profiles[0],args.transcript.read_text(),args.health.read_text(),
                                  json.loads(args.receipt.read_text()),admission)
        else:
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
