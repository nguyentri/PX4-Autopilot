#!/usr/bin/env python3
"""List RZ/V2H tooling or run declared host tests with CI reports."""

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(__file__).with_name('rzv2h-regression-catalog.json')


def read_catalog(path):
    catalog = json.loads(path.read_text())
    entries = catalog['scripts']
    ids = [entry['id'] for entry in entries]
    if catalog.get('schema_version') != 1 or len(ids) != len(set(ids)):
        raise ValueError('unsupported catalog or duplicate script IDs')
    for entry in entries:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts or not (ROOT/relative).is_file():
            raise ValueError('missing or invalid catalog path: ' + str(relative))
    return catalog


def select(catalog, groups, ids):
    scripts = catalog['scripts']
    known_groups = {group for entry in scripts for group in entry['groups']}
    if set(groups) - known_groups or set(ids) - {entry['id'] for entry in scripts}:
        raise ValueError('unknown group or script ID')
    selected = [entry for entry in scripts if
                (not groups and not ids) or entry['id'] in ids or
                set(entry['groups']).intersection(groups)]
    if not selected:
        raise ValueError('empty test selection')
    return selected


def invocation(entry, variables):
    if entry['kind'] != 'test' or entry['target_access'] != 'none':
        raise ValueError('host runner refuses non-test or board operations: ' + entry['id'])
    values = dict(variables, python=sys.executable)
    try:
        argv = [part.format_map(values) for part in entry['command']]
    except KeyError as error:
        raise ValueError('missing artifact option: ' + str(error)) from error
    for name in entry.get('requires', {}).get('tools', []):
        if not shutil.which(name):
            raise ValueError('required host tool missing: ' + name)
    for name in entry.get('requires', {}).get('modules', []):
        if importlib.util.find_spec(name) is None:
            raise ValueError('required Python module missing: ' + name)
    for name in entry.get('requires', {}).get('paths', []):
        if not (ROOT/name).exists():
            raise ValueError('required input missing: ' + name)
    return argv


def process_group_running(group):
    """Observe live Linux group members without waiting on orphan zombies."""
    for directory in Path('/proc').iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            fields = (directory/'stat').read_text().rsplit(')', 1)[1].split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        if int(fields[2]) == group and fields[0] != 'Z':
            return True
    return False


def stop_process(process):
    """Stop the owned session's group even if its leader already exited."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    else:
        deadline = time.monotonic()+5
        while process_group_running(process.pid):
            if time.monotonic() >= deadline:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            time.sleep(0.05)
    # SIGKILL delivery is asynchronous. Wait for descendants to leave the
    # runnable/sleeping states before callers remove their working files.
    deadline = time.monotonic()+5
    while process_group_running(process.pid):
        if time.monotonic() >= deadline:
            raise TimeoutError('owned process group did not stop: ' + str(process.pid))
        time.sleep(0.01)
    process.wait()


def interrupted(signum, frame):
    raise KeyboardInterrupt


def execute(entry, argv, log, timeout):
    started = time.monotonic()
    timed_out = False
    cancelled = False
    with log.open('w') as stream:
        process = subprocess.Popen(argv, cwd=ROOT, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            stop_process(process)
        except KeyboardInterrupt:
            cancelled = True
            stop_process(process)
        finally:
            stop_process(process)
    output = log.read_text(errors='replace')
    skipped = any(int(count) > 0 for count in re.findall(r'\bskipped=(\d+)', output)) or bool(
        re.search(r'\.\.\. skipped\b|^SKIP\b', output, re.M))
    counts = re.findall(r'Ran (\d+) tests?', output)
    test_count = sum(map(int, counts)) if counts else None
    zero_tests = test_count == 0
    missing_summary = Path(entry['path']).suffix == '.py' and not counts
    passed = process.returncode == 0 and not (cancelled or timed_out or skipped or zero_tests or missing_summary)
    return {'id': entry['id'], 'path': entry['path'], 'status': 'PASS' if passed else 'FAIL',
            'exit': process.returncode, 'timed_out': timed_out, 'skipped': skipped,
            'cancelled': cancelled,
            'zero_tests': zero_tests, 'missing_summary': missing_summary,
            'tests': test_count,
            'seconds': round(time.monotonic()-started, 3), 'command': argv,
            'log': str(log)}


def write_reports(output, results):
    (output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
    suite = ET.Element('testsuite', name='rzv2h-regression', tests=str(len(results)),
                       failures=str(sum(row['status'] == 'FAIL' for row in results)),
                       skipped=str(sum(row['status'] == 'NOT-RUN' for row in results)))
    for row in results:
        case = ET.SubElement(suite, 'testcase', name=row['id'], time=str(row.get('seconds', 0)))
        if row['status'] == 'NOT-RUN':
            ET.SubElement(case, 'skipped', message=row['reason'])
        elif row['status'] == 'FAIL':
            ET.SubElement(case, 'failure', message=row.get('reason', 'host check failed')).text = (
                'exit={exit}, timeout={timed_out}, cancelled={cancelled}, skipped={skipped}; log={log}'.format(**row)
                if 'exit' in row else row['reason'])
        ET.SubElement(case, 'system-out').text = 'Log: ' + row.get('log', '')
    ET.ElementTree(suite).write(output/'junit.xml', encoding='utf-8', xml_declaration=True)


def main():
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('list', 'check', 'run'))
    parser.add_argument('--group', action='append', default=[], help='repeat to select catalog groups')
    parser.add_argument('--test', action='append', default=[], help='repeat to select exact script IDs')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--output', type=Path, help='new or empty directory for run logs/JSON/JUnit')
    parser.add_argument('--timeout', type=float, default=180, help='per-script timeout in seconds')
    parser.add_argument('--sample-builds', type=Path)
    parser.add_argument('--sample-source-state', type=Path)
    parser.add_argument('--px4-archive', type=Path)
    args = parser.parse_args()
    output = None
    results = []
    try:
        catalog = read_catalog(CATALOG)
        groups = args.group or (['sample-host'] if args.operation == 'run' and not args.test else [])
        selected = select(catalog, groups, args.test)
        if args.operation != 'run':
            if args.json:
                print(json.dumps(selected if args.operation == 'list' else
                                 {'status': 'PASS', 'scripts': len(catalog['scripts'])}, indent=2))
            elif args.operation == 'list':
                for entry in selected:
                    print(entry['id'], ','.join(entry['groups']), entry['target_access'], entry['path'])
            else:
                print('Catalog paths/IDs valid:', len(catalog['scripts']))
            return 0
        if not args.output or not math.isfinite(args.timeout) or args.timeout <= 0:
            parser.error('run requires --output and a positive --timeout')
        # Refuse a mixed hardware/host selection before starting any script.
        if any(entry['kind'] != 'test' or entry['target_access'] != 'none' for entry in selected):
            raise ValueError('host runner refuses tools/HIL entries; select a host test group')
        output = args.output.resolve()
        if args.px4_archive and output.is_relative_to(args.px4_archive.resolve()):
            raise ValueError('run output must be outside the PX4 archive')
        output.mkdir(parents=True, exist_ok=True)
        if any(output.iterdir()):
            raise ValueError('output directory must be new or empty')
        variables = {}
        if args.sample_builds:
            variables['sample_builds'] = str(args.sample_builds.resolve())
            variables['sample_source_state'] = str((args.sample_source_state or
                                                    args.sample_builds.resolve().parent/'source-state.json').resolve())
        if args.px4_archive:
            if not args.px4_archive.is_dir():
                raise ValueError('PX4 archive directory missing')
            variables['px4_archive'] = str(args.px4_archive.resolve())
        if any('{px4_archive}' in part for entry in selected for part in entry['command']) and not args.px4_archive:
            raise ValueError('missing artifact option: px4_archive')
        results = [{'id': entry['id'], 'path': entry['path'], 'status': 'NOT-RUN',
                    'reason': 'not executed'} for entry in selected]
        write_reports(output, results)
        for index, entry in enumerate(selected):
            try:
                argv = invocation(entry, variables)
                result = execute(entry, argv, output/(entry['id']+'.log'), args.timeout)
            except (OSError, ValueError) as error:
                result = {'id': entry['id'], 'path': entry['path'], 'status': 'FAIL', 'reason': str(error)}
            results[index] = result
            write_reports(output, results)
            print(entry['id'], result['status'], result.get('reason', ''), flush=True)
            if result.get('cancelled'):
                print('interrupted; owned test process stopped', file=sys.stderr)
                return 130
        return 0 if all(row['status'] == 'PASS' for row in results) else 1
    except (OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        if results:
            write_reports(output, results)
        print('interrupted; owned test process stopped', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
