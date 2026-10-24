#!/usr/bin/env python3
"""Inspect the native RDK sample inventory without touching firmware or a probe."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
BOARD = Path('platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h')
POLICY = Path(__file__).with_name('rzv2h-all-sample-configs.json')
LEGACY = Path(__file__).with_name('rzv2h-sample-profiles.json')
COVERAGE = Path(__file__).with_name('rzv2h-driver-coverage.json')
CONTRACT_PATHS = {'selected_manifest': 'sample-profiles.json',
                  'legacy_contract': 'legacy-sample-profiles.json',
                  'driver_coverage': 'driver-coverage.json'}
CORE_KCONFIG = Path('platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Kconfig')
CORES = {'RZV2H_BUILD_CR8_0': 'cr8_0', 'RZV2H_BUILD_CR8_1': 'cr8_1',
         'RZV2H_BUILD_CM33': 'cm33'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract_inputs(manifest, legacy=LEGACY, coverage=COVERAGE):
    paths = dict(selected_manifest=manifest, legacy_contract=legacy,
                 driver_coverage=coverage)
    return [dict(role=role, path=name, sha256=digest(paths[role]))
            for role, name in CONTRACT_PATHS.items()]


def archived_contracts(source_path, receipt=None, required=False):
    """Resolve only fixed archive-relative contract roles, never receipt paths."""
    source = json.loads(source_path.read_text())
    records = source.get('contract_inputs')
    if records is None:
        if required or (receipt is not None and 'contract_inputs' in receipt):
            raise ValueError('archived contract inputs required')
        return {}
    if not isinstance(records, list) or len(records) != len(CONTRACT_PATHS):
        raise ValueError('missing or duplicate archived contract roles')
    result = {}
    for record in records:
        role = record.get('role')
        if role not in CONTRACT_PATHS or role in result or \
                record.get('path') != CONTRACT_PATHS[role] or set(record) != {'role', 'path', 'sha256'}:
            raise ValueError('unknown, duplicate or mismatched archived contract role/path')
        path = source_path.parent/CONTRACT_PATHS[role]
        if path.is_symlink() or digest(path) != record.get('sha256'):
            raise ValueError('archived contract digest mismatch: ' + role)
        result[role] = json.loads(path.read_text())
    if source.get('manifest_sha256') != records[0]['sha256'] or records[0]['role'] != 'selected_manifest':
        raise ValueError('selected manifest provenance mismatch')
    if receipt is not None and receipt.get('contract_inputs') != records:
        raise ValueError('receipt archived contract binding mismatch')
    legacy = result['legacy_contract']
    names = [x['profile'] for x in legacy['profiles']]
    if legacy.get('schema_version') != 1 or len(names) != 14 or len(set(names)) != 14:
        raise ValueError('legacy fourteen-profile contract changed')
    selected = result['selected_manifest']
    validate_coverage(result['driver_coverage'],
                      selected['profiles'] if selected.get('schema_version') == 2 else None)
    return result


def instance_key(core, instance):
    if not isinstance(instance, dict) or set(instance) != {'family', 'unit', 'channel', 'mode', 'output'}:
        raise ValueError('incomplete instance tuple')
    if core not in CORES.values() or any(type(instance[x]) is not int or instance[x] < 0
                                        for x in ('unit', 'channel')) or \
            any(not isinstance(instance[x], str) or not instance[x] for x in ('family', 'mode')) or \
            instance['output'] not in (None, 'A', 'B'):
        raise ValueError('invalid typed instance tuple')
    return (core, instance['family'], instance['unit'], instance['channel'],
            instance['mode'], instance['output'])


def validate_hwtest(contract):
    if not isinstance(contract, dict) or not isinstance(contract.get('mode'), str) or not contract['mode']:
        raise ValueError('unknown hwtest contract')
    cases = contract.get('required_case_ids')
    if not isinstance(cases, list) or not cases or any(not isinstance(x, str) or
            not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+', x) for x in cases) or \
            len(cases) != len(set(cases)):
        raise ValueError('missing, duplicate or malformed hwtest cases')
    if contract.get('expected_summary') != dict(passed=len(cases), failed=0, skipped=0):
        raise ValueError('required hwtest cases must all pass')
    if any(type(x) is not int for x in contract['expected_summary'].values()):
        raise ValueError('hwtest summary counts must be integers')
    required = contract.get('target_state_required')
    types = contract.get('target_state_types')
    if not isinstance(required, dict) or not isinstance(types, dict) or set(required) != set(types):
        raise ValueError('hwtest typed state contract missing')
    for key, kind in types.items():
        value = required[key]
        good = ((kind == 'string' and isinstance(value, str)) or
                (kind == 'integer' and type(value) is int) or
                (kind == 'boolean' and type(value) is bool) or
                (kind == 'array' and isinstance(value, list) and all(isinstance(x, str) for x in value)) or
                (kind in ('integer', 'integer-predicate') and isinstance(value, dict) and
                 set(value) == {'op', 'value'} and value['op'] == 'gt' and type(value['value']) is int))
        if not re.fullmatch(r'[A-Za-z0-9_]+', key) or not good:
            raise ValueError('invalid hwtest state type: ' + key)
    if 'invocation' in contract and contract['invocation'].get('command') != 'hwtest':
        raise ValueError('instance invocation must be fixed hwtest')
    return contract


def domain_keys(catalog):
    keys = {}
    for domain in catalog['domains']:
        for core in catalog['cores']:
            for unit, channels in enumerate(domain['channels_by_unit']):
                for channel in channels:
                    for family, mode in domain['modes'].items():
                        for output in domain['outputs']:
                            key = instance_key(core, dict(family=family, unit=unit,
                                channel=channel, mode=mode, output=output))
                            if key in keys:
                                raise ValueError('duplicate hardware domain tuple')
                            keys[key] = domain
    return keys


def validate_coverage(catalog, profiles=None):
    if catalog.get('schema_version') != 1 or catalog.get('kind') != 'rzv2h-driver-coverage':
        raise ValueError('unknown driver coverage catalogue')
    domains = catalog['domains']
    if len({x['family'] for x in domains}) != len(domains):
        raise ValueError('duplicate hardware domains')
    for domain in domains:
        if not domain.get('source_evidence') or not domain.get('ownership_gate'):
            raise ValueError('hardware source/ownership evidence missing')
        for channels in domain['channels_by_unit']:
            if not channels or len(channels) != len(set(channels)) or \
                    any(type(x) is not int or x < 0 for x in channels):
                raise ValueError('invalid hardware channel domain')
    for category in ('core_private_timers', 'shared_timer_services',
                     'non_channel_services', 'header_only_ip'):
        records = catalog.get(category, [])
        if not isinstance(records, list) or len({x['name'] for x in records}) != len(records):
            raise ValueError('duplicate non-executable metadata records')
        for record in records:
            if record.get('state') not in ('reference-only', 'unimplemented') or \
                    record.get('executable') is not False or not record.get('source_evidence') or \
                    not record.get('blockers') or any(x in record for x in ('profile','commands','instance_id')):
                raise ValueError('invalid non-executable source metadata')
    mapped_profiles = set()
    for record in catalog.get('native_profile_coverage', []):
        if record.get('profile') not in ('dmac-memcpy', 'dmac-memcpy-rtt') or \
                record.get('profile') in mapped_profiles or record.get('family') != 'dmac' or \
                record.get('core') != 'cr8_0' or record.get('mode') != 'memcpy' or \
                record.get('channel_batches') != [list(range(x, x+5)) for x in range(0,80,5)] or \
                not record.get('source_evidence') or not record.get('gates'):
            raise ValueError('invalid native DMAC batch coverage')
        mapped_profiles.add(record['profile'])
    keys = domain_keys(catalog)
    identifiers, tuples, names = set(), set(), set()
    by_id = {}
    for cell in catalog['instances']:
        key = instance_key(cell['core'], cell['instance'])
        identifier, name = cell['instance_id'], cell['profile']
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-z0-9_-]+', identifier) or \
                key not in keys or identifier in identifiers or key in tuples or name in names:
            raise ValueError('unknown or duplicate instance catalogue cell')
        if not cell.get('required_config') or not cell.get('required_symbols') or not cell.get('source_evidence'):
            raise ValueError('instance selector/link/source contract missing')
        identifiers.add(identifier); tuples.add(key); names.add(name)
        by_id[identifier] = cell
    if profiles is not None:
        baseline = catalog['baseline_native_profiles']
        if len(baseline) != catalog.get('baseline_native_count') or len(baseline) != 55 or \
                len({x['profile'] for x in baseline}) != len(baseline):
            raise ValueError('invalid recorded baseline inventory')
        rows = {x['profile']: x for x in profiles}
        if len(rows) != len(profiles) or any(any(rows.get(x['profile'], {}).get(k) != v
                for k, v in x.items()) for x in baseline):
            raise ValueError('baseline native profile omitted or identity changed')
        seen = set()
        for row in profiles:
            fields = {'instance_id', 'instance', 'hwtest_contract'} & row.keys()
            if not fields:
                if row['profile'] in names:
                    raise ValueError('instance profile omitted its instance tuple/contract')
                continue
            if fields != {'instance_id', 'instance', 'hwtest_contract'}:
                raise ValueError('partial instance metadata')
            cell = by_id.get(row['instance_id'])
            if cell is None or row['instance_id'] in seen or cell['profile'] != row['profile'] or \
                    instance_key(row['core'], row['instance']) != instance_key(cell['core'], cell['instance']):
                raise ValueError('unknown, duplicate or mismatched profile/instance tuple')
            if row['mode'] != 'hwtest' or row['oracle'] != 'hwtest' or row['commands'] != ['hwtest']:
                raise ValueError('one instance requires exactly one fixed hwtest invocation')
            contract = validate_hwtest(row['hwtest_contract'])
            cases = instance_contract(row['instance'])['required_case_ids']
            accepted = [cases]
            if row['instance']['family'] == 'spi':
                accepted.append(cases[:-1])  # Archived registration-only contract.
                if contract['required_case_ids'] == cases and \
                        'rzv2h_spi_sample_loopback_at' not in cell['required_symbols']:
                    raise ValueError('SPI loopback implementation contract missing')
            if contract['mode'] != 'driver-instance' or contract['required_case_ids'] not in accepted:
                raise ValueError('unknown fixed-instance suite contract')
            state = contract['target_state_required']
            for key, value in dict(instance_family=row['instance']['family'],
                    instance_unit=row['instance']['unit'], instance_channel=row['instance']['channel'],
                    instance_output=row['instance']['output'] or 'none').items():
                if type(state.get(key)) is not type(value) or state.get(key) != value:
                    raise ValueError('instance telemetry contract mismatch: ' + key)
            if state.get('instance_identity') != {'op': 'gt', 'value': 0}:
                raise ValueError('actual initialized instance identity must be positive')
            expected_types = dict(instance_family='string', instance_unit='integer',
                                  instance_channel='integer', instance_output='string')
            if any(contract['target_state_types'].get(k) != v for k, v in expected_types.items()) or \
                    contract['target_state_types'].get('instance_identity') not in ('integer', 'integer-predicate'):
                raise ValueError('instance telemetry field type mismatch')
            seen.add(row['instance_id'])
    return catalog


def read_config(path):
    result = {}
    for line in path.read_text().splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key, value = line.split('=', 1)
            result[key] = value.strip('"')
    return result


def core_default(root=ROOT):
    text = (root / CORE_KCONFIG).read_text()
    choices = re.findall(r'(?ms)^choice\s*\n(.*?)^endchoice\b', text)
    choices = [x for x in choices if 'config RZV2H_BUILD_CR8_0' in x]
    if len(choices) != 1 or any('config ' + x not in choices[0] for x in CORES):
        raise ValueError('core choice missing or ambiguous')
    defaults = re.findall(r'(?m)^\s*default\s+(\w+)\s*$', choices[0])
    if len(defaults) != 1 or defaults[0] not in CORES:
        raise ValueError('unknown or conditional core default')
    return defaults[0]


def identity(config, default):
    selected = [x for x in CORES if config.get('CONFIG_' + x) == 'y']
    if len(selected) > 1:
        raise ValueError('contradictory core selectors')
    selector = selected[0] if selected else default
    core = CORES[selector]
    number = config.get('CONFIG_RZV_MPU_CR8_CORE_NUM')
    if number is not None and core != 'cm33' and number != core[-1]:
        raise ValueError('core number contradicts core choice')
    if config.get('CONFIG_ARCH_CORTEXM33') == 'y' and core != 'cm33':
        raise ValueError('CM33 architecture contradicts core choice')
    if config.get('CONFIG_SYSLOG_RTT_CONSOLE_INPUT') == 'y':
        console = 'rtt'
    else:
        serial = [key[7:-15].lower() for key, value in config.items()
                  if value == 'y' and re.fullmatch(r'CONFIG_(?:SCI\d|SCIF\d)_SERIAL_CONSOLE', key)]
        if len(serial) > 1:
            raise ValueError('multiple serial consoles')
        console = serial[0] if serial else 'rtt-output' if config.get('CONFIG_SEGGER_RTT') == 'y' else 'unconfigured'
    return {'core': core, 'core_source': 'defconfig-selector' if selected else 'kconfig-default',
            'core_selector': selector, 'console': console,
            'entrypoint': config.get('CONFIG_INIT_ENTRYPOINT', 'nsh_main')}


def inspect_profile(name, root=ROOT):
    if not re.fullmatch(r'[a-z0-9_-]+', name):
        raise ValueError('invalid profile name')
    path = root / BOARD / 'configs' / name / 'defconfig'
    result = identity(read_config(path), core_default(root))
    result.update(profile=name, defconfig_sha256=digest(path))
    return result


def instance_contract(instance):
    cases = ['instance.guard', 'instance.identity', 'instance.stable']
    if instance['family'] == 'spi':
        cases.append('instance.loopback')
    return dict(mode='driver-instance', required_case_ids=cases,
        expected_summary=dict(passed=len(cases), failed=0, skipped=0),
        target_state_required=dict(instance_family=instance['family'], instance_unit=instance['unit'],
            instance_channel=instance['channel'], instance_output=instance['output'] or 'none',
            instance_identity={'op':'gt', 'value':0}),
        target_state_types=dict(instance_family='string', instance_unit='integer',
            instance_channel='integer', instance_output='string', instance_identity='integer-predicate'))


def dmac_batches(profile):
    """Decode fixed native commands, including historical five-position runs."""
    batches = []
    for command in profile.get('commands', []):
        if not isinstance(command, str) or not re.fullmatch(r'rzv_dmac(?: [0-9]+){1,5}', command):
            raise ValueError('invalid bounded DMAC command')
        values = command.split()[1:]
        channels = [int(x) for x in values]
        if any(str(channel) != value or not 0 <= channel < 80
               for channel, value in zip(channels, values)):
            raise ValueError('invalid DMAC channel')
        batches.append(channels)
    channels = [channel for batch in batches for channel in batch]
    if channels not in (list(range(80)), [0,16,32,48,64]):
        raise ValueError('missing, duplicate or unordered DMAC channel coverage')
    return batches


def dmac_commands():
    return ['rzv_dmac ' + ' '.join(str(x) for x in range(first,first+5))
            for first in range(0,80,5)]


def configured_instance(config, name, core, catalog):
    values = []
    for suffix in ('FAMILY', 'CHANNEL', 'OUTPUT'):
        value = config.get('CONFIG_TESTING_RZV_HWTEST_INSTANCE_'+suffix, '')
        if not re.fullmatch(r'\d+', value):
            raise ValueError('invalid configured instance '+suffix)
        values.append(int(value))
    number, channel, output = values
    families = {1:('riic','master'), 2:('spi','spi'), 3:('sci-i2c','master'),
                4:('sci-spi','spi'), 5:('gpt','pwm'), 6:('ether','register'),
                7:('sdhi','lower'), 8:('wdt','nonstart')}
    if number not in families or output not in (0, 1) or (number != 5 and output != 0):
        raise ValueError('unknown configured instance family/output')
    family, mode = families[number]
    instance = dict(family=family, unit=int(channel >= 8) if number == 5 else 0,
                    channel=channel, mode=mode, output=('B' if output else 'A') if number == 5 else None)
    matches = [x for x in catalog['instances'] if x['profile'] == name and
               instance_key(core, instance) == instance_key(x['core'], x['instance'])]
    if len(matches) != 1:
        raise ValueError('configured instance is unknown or mismatches fixed profile: '+name)
    return dict(instance_id=matches[0]['instance_id'], instance=instance,
                hwtest_contract=instance_contract(instance))


def generate(manifest, root=ROOT, catalog=None):
    """Refresh hashes and derive fixed-instance contracts from source selectors."""
    catalog = catalog if catalog is not None else json.loads(COVERAGE.read_text())
    validate_coverage(catalog)
    prior = {x['profile']: x for x in manifest['profiles']}
    if len(prior) != len(manifest['profiles']):
        raise ValueError('duplicate generation policy profiles')
    result = dict(manifest, core_default=core_default(root), profiles=[])
    for path in sorted((root/BOARD/'configs').glob('*/defconfig')):
        name = path.parent.name
        config = read_config(path)
        actual = inspect_profile(name, root)
        row = dict(prior.get(name, {}))
        if config.get('CONFIG_TESTING_RZV_HWTEST_MODE_DRIVER_INSTANCE') == 'y':
            metadata = configured_instance(config, name, actual['core'], catalog)
            sci = metadata['instance']['family'].startswith('sci-')
            spi = metadata['instance']['family'] == 'spi'
            row.update(mode='hwtest', oracle='hwtest', commands=['hwtest'],
                requirements=(['SCI-mode-authority'] if sci else [])+['controller-clock-ownership']+
                             (['pad-ownership'] if spi else []),
                hazards=[], timeout=30, evidence_class='internal-function' if spi else 'diagnostic',
                builtin=dict(name='hwtest', symbol='hwtest_main'),
                reason='SCI behavioral authority and RDK route qualification remain open.' if sci else None,
                completion='waitpid-or-task-resource-oracle', reset_classes=['warm-load'], **metadata)
            if metadata['instance']['family'] == 'ether':
                row['requirements'].append('ether-parent-clock-handoff')
            if metadata['instance']['family'] == 'sdhi':
                row['requirements'].append('sdhi-handoff')
            if metadata['instance']['family'] == 'wdt':
                row['requirements'].append('wdt-stopped')
        elif not row:
            raise ValueError('new native profile requires a reviewed execution policy: '+name)
        elif any(key in row for key in ('instance_id','instance','hwtest_contract')):
            raise ValueError('fixed instance test selector omitted: '+name)
        if name in ('dmac-memcpy', 'dmac-memcpy-rtt'):
            row['commands'] = dmac_commands()
        row.update(actual)
        result['profiles'].append(row)
    result['board_sources'] = subprocess.check_output(['git', '-C', str(root/'platforms/nuttx/NuttX/nuttx'),
        'ls-files', 'boards/arm/rzv/rdk-rzv2h/src'], text=True).splitlines()
    validate(result, root, catalog)
    return result


def validate(manifest, root=ROOT, catalog=None, live=True):
    if manifest.get('schema_version') != 2 or manifest.get('kind') != 'rzv2h-native-samples':
        raise ValueError('unsupported native sample inventory')
    profiles = manifest['profiles']
    catalog = catalog if catalog is not None else json.loads(COVERAGE.read_text())
    names = [x['profile'] for x in profiles]
    current = {p.parent.name for p in (root / BOARD / 'configs').glob('*/defconfig')} if live else set(names)
    if len(names) != len(set(names)) or set(names) != current:
        raise ValueError('configuration inventory drift or duplicate profiles')
    default = core_default(root) if live else manifest.get('core_default')
    if manifest.get('core_default') != default:
        raise ValueError('Kconfig core default changed; review defaulted profiles')
    for row in profiles:
        if not re.fullmatch(r'[a-z0-9_-]+', row['profile']):
            raise ValueError('invalid profile name')
        actual = inspect_profile(row['profile'], root) if live else {}
        for key, value in actual.items():
            if row.get(key) != value:
                raise ValueError(row['profile'] + ': declaration changed: ' + key)
        if live:
            config = read_config(root/BOARD/'configs'/row['profile']/'defconfig')
            if config.get('CONFIG_TESTING_RZV_HWTEST_MODE_DRIVER_INSTANCE') == 'y':
                metadata = configured_instance(config, row['profile'], row['core'], catalog)
                if any(row.get(key) != value for key, value in metadata.items()):
                    raise ValueError('configured instance metadata drift: '+row['profile'])
            elif 'instance_id' in row:
                raise ValueError('fixed instance mode selector missing: '+row['profile'])
        if row.get('mode') not in ('hwtest', 'native', 'boot', 'blocked', 'shell'):
            raise ValueError('unknown execution mode')
        if not isinstance(row.get('requirements'), list) or not isinstance(row.get('hazards'), list):
            raise ValueError('fixture/hazard declaration missing')
        if not isinstance(row.get('commands'), list) or any(
                not isinstance(x, str) or '\n' in x or '\r' in x for x in row['commands']):
            raise ValueError('invalid bounded command list')
        if type(row.get('timeout')) is not int or not 1 <= row['timeout'] <= 120:
            raise ValueError('invalid command deadline')
        if row.get('oracle') == 'dmac':
            dmac_batches(row)
            if live and row['commands'] != dmac_commands():
                raise ValueError('current DMAC profiles must cover all 80 channels')
    validate_coverage(catalog, profiles)
    sources = subprocess.check_output(['git', '-C', str(root/'platforms/nuttx/NuttX/nuttx'),
                                      'ls-files', 'boards/arm/rzv/rdk-rzv2h/src'], text=True).splitlines() if live else manifest['board_sources']
    if set(manifest['board_sources']) != set(sources) or len(sources) != len(manifest['board_sources']):
        raise ValueError('tracked board-source inventory drift')
    return profiles


def load(path=POLICY, root=ROOT):
    manifest = json.loads(path.read_text())
    validate(manifest, root)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=POLICY)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--json', action='store_true', help='emit a regenerated complete inventory; never writes the policy')
    parser.add_argument('--generate', action='store_true', help='refresh source hashes and fixed-instance metadata')
    args = parser.parse_args()
    try:
        manifest = generate(json.loads(args.manifest.read_text())) if args.json or args.generate else load(args.manifest)
        if args.list:
            print('\n'.join(x['profile'] for x in manifest['profiles']))
        else:
            result = {'status': 'PASS', 'configs': len(manifest['profiles']),
                      'board_sources': len(manifest['board_sources']), 'target_actions': []}
            print(json.dumps(manifest, indent=2) if args.json else 'Inventory valid: {configs} configs, {board_sources} board files'.format(**result))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print('Inventory invalid: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
