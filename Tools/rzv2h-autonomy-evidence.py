#!/usr/bin/env python3
"""Analyze bounded-clock timing and validate honest Autonomy Lab evidence receipts.

This host-only tool neither operates hardware nor promotes software checks into
SW0-SW4 qualification. Its input is recorded observations, not target values.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

CARDS = {
    'T00': 'Reproduce', 'T01': 'Sensors/time', 'T02': 'Battery/store',
    'T03': 'Inactive outputs', 'T04': 'See/model', 'T05': 'A55-CR8 IPC',
    'T06': 'Perception-to-output', 'T07': 'Planner freeze', 'T08': 'CR8 loss/lease',
    'T09': 'Corruption/reconnect', 'T10': 'Isolation/thermal',
    'T11': 'Rig dynamics', 'T12': 'Scenario/landing adapter',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value, label, minimum=None):
    require(type(value) in (int, float) and math.isfinite(value), 'non-finite ' + label)
    require(minimum is None or value >= minimum, 'out-of-range ' + label)
    return value


def unique(pairs):
    output = {}
    for key, value in pairs:
        require(key not in output, 'duplicate key: ' + key)
        output[key] = value
    return output


def load(path):
    require(path.stat().st_size <= 16 * 1024 * 1024, 'oversized JSON')
    return json.loads(path.read_text(), object_pairs_hook=unique,
                      parse_constant=lambda value: require(False, 'non-finite JSON: ' + value))


def sha256(path):
    require(path.is_file() and not path.is_symlink(), 'missing/nonregular raw evidence: ' + str(path))
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def percentile(values, fraction):
    ordered = sorted(values)
    require(bool(ordered), 'empty distribution')
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def analyze(records):
    groups, previous = {}, {}
    require(len(records) <= 1000000, 'too many records')
    for record in records:
        stream, session = record.get('stream'), record.get('session')
        require(isinstance(stream, str) and 0 < len(stream) <= 128, 'missing stream')
        require(isinstance(session, str) and 0 < len(session) <= 128, 'missing session')
        generation = record.get('generation')
        require(type(generation) is int and generation > 0, 'invalid source generation')
        require(record.get('generation_kind') in ('source', 'receiver_callback', 'control_publication'),
                'generation meaning required')
        start = finite(record.get('start_us'), 'start', 0)
        end = finite(record.get('end_us'), 'end', 0)
        source_clock, destination_clock = record.get('start_clock'), record.get('end_clock')
        require(isinstance(source_clock, str) and source_clock and isinstance(destination_clock, str)
                and destination_clock, 'clock identity required')
        require(record.get('endpoint_start') and record.get('endpoint_end'), 'measurement endpoints required')
        key = (stream, session)
        old = previous.get(key)
        require(old is None or generation > old[0], 'duplicate/regressing source generation')
        require(old is None or start >= old[1], 'source clock regression')
        previous[key] = (generation, start)
        uncertainty = 0
        if source_clock == destination_clock:
            require(not record.get('clock_mapping'), 'unnecessary clock mapping')
            duration = end - start
        else:
            mapping = record.get('clock_mapping')
            require(isinstance(mapping, dict) and mapping.get('qualification'), 'unsynchronized clocks')
            require(mapping.get('source_clock') == source_clock and mapping.get('destination_clock') == destination_clock,
                    'wrong clock mapping domains')
            offset = finite(mapping.get('destination_minus_source_us'), 'clock offset')
            uncertainty = finite(mapping.get('uncertainty_us'), 'clock uncertainty', 0)
            valid_from = finite(mapping.get('valid_from_source_us'), 'mapping start', 0)
            valid_until = finite(mapping.get('valid_until_source_us'), 'mapping end', valid_from)
            require(valid_from <= start <= valid_until, 'expired clock mapping')
            duration = end - start - offset
        require(duration >= 0, 'negative mapped duration')
        signature = (record['endpoint_start'], record['endpoint_end'], source_clock, destination_clock,
                     record['generation_kind'])
        group = groups.setdefault(key, {'signature': signature, 'values': [], 'upper': [], 'missing_generations': 0,
                                        'max_uncertainty_us': 0})
        require(group['signature'] == signature, 'mixed endpoint/clock/generation semantics')
        group['values'].append(duration)
        group['upper'].append(duration + uncertainty)
        group['max_uncertainty_us'] = max(group['max_uncertainty_us'], uncertainty)
        if old:
            group['missing_generations'] += generation - old[0] - 1
    output = []
    for (stream, session), group in groups.items():
        values = group['values']
        output.append({'stream': stream, 'session': session, 'endpoints_and_clocks': group['signature'],
                       'samples': len(values), 'missing_generations': group['missing_generations'],
                       'min_us': min(values), 'median_us': statistics.median(values),
                       'p95_us': percentile(values, .95), 'p99_us': percentile(values, .99),
                       'p999_us': percentile(values, .999), 'max_us': max(values),
                       'max_upper_bound_us': max(group['upper']),
                       'max_uncertainty_us': group['max_uncertainty_us'],
                       'qualification': 'analysis-only; workload/duration/card review still required'})
    require(bool(output), 'no observations')
    return output


def raw_files(receipt, root):
    require(isinstance(receipt, list) and receipt, 'raw evidence required')
    names = set()
    for item in receipt:
        name = item.get('path')
        require(isinstance(name, str) and name and '\\' not in name, 'invalid raw path')
        relative = Path(name)
        require(not relative.is_absolute() and all(p not in ('', '.', '..') for p in name.split('/')),
                'raw path traversal')
        require(name not in names, 'duplicate raw path')
        names.add(name)
        path = root / relative
        require(path.resolve().is_relative_to(root.resolve()), 'escaped raw root')
        require(sha256(path) == item.get('sha256'), 'raw hash mismatch: ' + name)


def check_ledger(ledger, root):
    require(ledger.get('schema') == 1, 'unsupported ledger schema')
    rows = ledger.get('cards')
    require(isinstance(rows, list) and len(rows) == len(CARDS), 'all thirteen cards required')
    require({row.get('id') for row in rows} == set(CARDS), 'card identity drift')
    for row in rows:
        require(row.get('meaning') == CARDS[row['id']], 'card meaning drift')
        require(row.get('state') in ('not-run', 'blocked', 'failed', 'passed'), 'invalid card state')
        require(isinstance(row.get('limitations'), list) and row['limitations'], 'limitations required')
        if row['state'] == 'passed':
            require(row.get('stage') == 'gate-passed' and row.get('reviewed_by'), 'pass lacks gate review')
            require(row.get('hardware_identity') and row.get('source_identity') and row.get('run_identity'),
                    'pass lacks immutable identity')
            require(row.get('conditions') and row.get('acceptance_revision'), 'pass lacks accepted conditions')
            require(row.get('on_target') is True, 'software-only evidence cannot pass a complete physical card')
            raw_files(row.get('raw'), root)
        elif row.get('raw'):
            raw_files(row['raw'], root)
    for claim in ledger.get('claims', []):
        require(isinstance(claim.get('text'), str) and claim['text'], 'empty customer claim')
        require(claim.get('cards') and set(claim['cards']) <= set(CARDS), 'claim lacks known card')
        require(all(next(row for row in rows if row['id'] == card)['state'] == 'passed'
                    for card in claim['cards']), 'claim references an unpassed card')
    return {'schema': 1, 'status': 'ledger-consistent', 'passed': [r['id'] for r in rows if r['state'] == 'passed'],
            'limitations': 'Hash/schema checks do not independently verify the truth of a reviewed measurement.'}


def check_calibration(receipt, root, physical_identity, image_sha256):
    require(receipt.get('schema') == 1 and type(receipt.get('generation')) is int
            and receipt['generation'] > 0, 'calibration generation/schema')
    require(receipt.get('physical_identity') == physical_identity and physical_identity,
            'calibration physical identity mismatch')
    require(receipt.get('image_sha256') == image_sha256 and re.fullmatch('[0-9a-f]{64}', image_sha256), 'image mismatch')
    require(receipt.get('parameter_schema') and receipt.get('sensors'), 'incomplete calibration generation')
    for sensor in receipt['sensors']:
        require(sensor.get('device_id') and sensor.get('orientation') is not None
                and sensor.get('serial_or_replacement_epoch'), 'route/type ID alone cannot identify a fitted sensor')
    raw_files(receipt.get('raw'), root)
    paths = {item['path'] for item in receipt['raw']}
    require(receipt.get('parameters_path') in paths and receipt.get('calibration_path') in paths,
            'complete parameter/calibration files required')
    provisional = receipt.get('storage_class') != 'qualified-durable'
    require(receipt.get('provisional') is provisional, 'storage/provisional contradiction')
    if not provisional:
        require(receipt.get('cold_boot_record') in paths and receipt.get('power_cut_record') in paths,
                'durability evidence missing')
    return {'schema': 1, 'compatible': True, 'provisional': provisional, 'output_ready': False,
            'reason': 'Offline compatibility only; qualified cold-boot restore and all safety gates remain required.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('analyze', 'ledger', 'calibration'))
    parser.add_argument('input', type=Path)
    parser.add_argument('--raw-root', type=Path)
    parser.add_argument('--physical-identity')
    parser.add_argument('--image-sha256')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        data = load(args.input)
        if args.operation == 'analyze':
            result = analyze(data)
        else:
            require(args.raw_root is not None, '--raw-root required')
            if args.operation == 'ledger':
                result = check_ledger(data, args.raw_root)
            else:
                require(args.physical_identity and args.image_sha256, 'physical/image identities required')
                result = check_calibration(data, args.raw_root, args.physical_identity, args.image_sha256)
        encoded = json.dumps(result, indent=2, allow_nan=False) + '\n'
        if args.output:
            require(not args.output.exists(), 'output already exists; preserve previous evidence')
            args.output.write_text(encoded)
        else:
            print(encoded, end='')
        return 0
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
