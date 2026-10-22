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
CORE_KCONFIG = Path('platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Kconfig')
CORES = {'RZV2H_BUILD_CR8_0': 'cr8_0', 'RZV2H_BUILD_CR8_1': 'cr8_1',
         'RZV2H_BUILD_CM33': 'cm33'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def validate(manifest, root=ROOT):
    if manifest.get('schema_version') != 2 or manifest.get('kind') != 'rzv2h-native-samples':
        raise ValueError('unsupported native sample inventory')
    profiles = manifest['profiles']
    names = [x['profile'] for x in profiles]
    current = {p.parent.name for p in (root / BOARD / 'configs').glob('*/defconfig')}
    if len(names) != len(set(names)) or set(names) != current:
        raise ValueError('configuration inventory drift or duplicate profiles')
    default = core_default(root)
    if manifest.get('core_default') != default:
        raise ValueError('Kconfig core default changed; review defaulted profiles')
    for row in profiles:
        actual = inspect_profile(row['profile'], root)
        for key, value in actual.items():
            if row.get(key) != value:
                raise ValueError(row['profile'] + ': declaration changed: ' + key)
        if row.get('mode') not in ('hwtest', 'native', 'boot', 'blocked', 'shell'):
            raise ValueError('unknown execution mode')
        if not isinstance(row.get('requirements'), list) or not isinstance(row.get('hazards'), list):
            raise ValueError('fixture/hazard declaration missing')
        if not isinstance(row.get('commands'), list) or any(
                not isinstance(x, str) or '\n' in x or '\r' in x for x in row['commands']):
            raise ValueError('invalid bounded command list')
        if type(row.get('timeout')) is not int or not 1 <= row['timeout'] <= 120:
            raise ValueError('invalid command deadline')
    sources = subprocess.check_output(['git', '-C', str(root/'platforms/nuttx/NuttX/nuttx'),
                                      'ls-files', 'boards/arm/rzv/rdk-rzv2h/src'], text=True).splitlines()
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
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        manifest = load(args.manifest)
        if args.list:
            print('\n'.join(x['profile'] for x in manifest['profiles']))
        else:
            result = {'status': 'PASS', 'configs': len(manifest['profiles']),
                      'board_sources': len(manifest['board_sources']), 'target_actions': []}
            print(json.dumps(result) if args.json else 'Inventory valid: {configs} configs, {board_sources} board files'.format(**result))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print('Inventory invalid: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
