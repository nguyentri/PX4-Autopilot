#!/usr/bin/env python3
"""Verify an archived RTT sample build; this does not authorize target use."""
import argparse
import hashlib
import json
import re
import subprocess
import struct
from pathlib import Path
import importlib.util

_SPEC = importlib.util.spec_from_file_location(
    'sample_inventory', Path(__file__).with_name('rzv2h-sample-inventory.py'))
INVENTORY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(INVENTORY)


def elf32_bytes(data, address, count, executable=False):
    """Read file-backed virtual bytes from the compiled ARM ELF32 artifact."""
    if data[:7] != b'\x7fELF\x01\x01\x01' or len(data) < 52:
        raise ValueError('expected little-endian ELF32')
    if struct.unpack_from('<H', data, 18)[0] != 40:
        raise ValueError('expected ARM machine')
    offset = struct.unpack_from('<I', data, 28)[0]
    entry_size, entries = struct.unpack_from('<HH', data, 42)
    if entry_size < 32 or offset + entry_size * entries > len(data):
        raise ValueError('invalid ELF program headers')
    for index in range(entries):
        kind, file_offset, virtual, _, file_size, memory_size, flags, _ = struct.unpack_from(
            '<8I', data, offset + index * entry_size)
        if kind == 1 and (file_size > memory_size or
                          file_offset + file_size > len(data)):
            raise ValueError('invalid load segment')
        if kind == 1 and (not executable or flags & 1) and \
                virtual <= address and address + count <= virtual + file_size:
            first = file_offset + address - virtual
            if first + count <= len(data):
                return data[first:first+count]
    raise ValueError('builtin address has no file-backed segment')


def builtin_entry(elf, expected_main, program='hwtest'):
    """Verify the actual builtin_s table (four 32-bit fields in this port)."""
    sizes = subprocess.check_output(['arm-none-eabi-nm', '-S', str(elf)], text=True)
    match = re.search(r'(?m)^(\w+)\s+(\w+)\s+\w\s+g_builtins$', sizes)
    if not match:
        raise ValueError('builtin table missing')
    address, size = (int(item, 16) for item in match.groups())
    if size == 0 or size % 16:
        raise ValueError('unsupported builtin table layout')
    data = elf.read_bytes()
    table = elf32_bytes(data, address, size)
    matches = []
    for offset in range(0, size, 16):
        name, priority, stack, entry = struct.unpack_from('<4I', table, offset)
        if name:
            text = bytearray()
            for index in range(64):
                byte = elf32_bytes(data, name+index, 1)[0]
                if byte == 0:
                    break
                text.append(byte)
            if text == program.encode():
                matches.append((priority, stack, entry))
    if len(matches) != 1 or (matches[0][2] & ~1) != (expected_main & ~1):
        raise ValueError(program + ' builtin does not point to its compiled entry')
    elf32_bytes(data, matches[0][2] & ~1, 1, executable=True)
    return {'priority': matches[0][0], 'stack_size': matches[0][1],
            'entry': hex(matches[0][2])}


def verify(profile, directory, source_state_path):
    config = {}
    for line in (directory / 'resolved.config').read_text().splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key, value = line.split('=', 1)
            config[key] = value.strip('"')
    needed = {'CONFIG_RZV2H_BUILD_CR8_0': 'y', 'CONFIG_ARCH_ARMV7R': 'y',
              'CONFIG_ARCH_CORTEXR8': 'y', 'CONFIG_TESTING_RZV_HWTEST': 'y', profile['mode_key']: 'y',
              'CONFIG_TESTING_RZV_HWTEST_PROGNAME': 'hwtest',
              'CONFIG_NSH_BUILTIN_APPS': 'y', 'CONFIG_SCHED_WAITPID': 'y',
              'CONFIG_SCHED_HAVE_PARENT': 'y', 'CONFIG_SCHED_CHILD_STATUS': 'y',
              'CONFIG_INIT_ENTRYPOINT': 'nsh_main', 'CONFIG_SEGGER_RTT': 'y',
              'CONFIG_SYSLOG_RTT': 'y', 'CONFIG_CONSOLE_SYSLOG': 'y',
              'CONFIG_SYSLOG_RTT_CONSOLE_INPUT': 'y',
              'CONFIG_SEGGER_RTT_UP_MODE_TRIM': 'y',
              'CONFIG_RZV2H_SAMPLE_TEST_API': 'y',
              'CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT': 'y'}
    for key, value in needed.items():
        if config.get(key) != value:
            raise ValueError('required resolved setting: ' + key)
    denied = ['CONFIG_ARCH_LEDS', 'CONFIG_ARCH_BUTTONS', 'CONFIG_USERLED_LOWER',
              'CONFIG_RZV_OPENAMP', 'CONFIG_RZV_IPC_RAW', 'CONFIG_RZV_IPC_IPCC',
              'CONFIG_RZV2H_WDT_TEST', 'CONFIG_WATCHDOG_AUTOMONITOR',
              'CONFIG_RZV2H_BUILD_CM33', 'CONFIG_RZV2H_BUILD_CR8_1',
              'CONFIG_SEGGER_RTT_UP_MODE_BLOCK', 'CONFIG_SEGGER_RTT_UP_MODE_SKIP']
    if profile['mode'] == 'scif-internal-loopback':
        denied += ['CONFIG_RZV_SCI' + str(i) for i in range(10)]
        denied += ['CONFIG_SCIF0_SERIAL_CONSOLE']
        for key in ('CONFIG_STANDARD_SERIAL', 'CONFIG_SERIAL_TERMIOS', 'CONFIG_RZV_SCIF0'):
            if config.get(key) != 'y':
                raise ValueError('SCIF device dependency missing: ' + key)
    if profile['mode'] == 'sdhi-lower-only':
        denied += ['CONFIG_MMCSD', 'CONFIG_MMCSD_SDIO', 'CONFIG_FS_FAT']
        if config.get('CONFIG_RZV2H_SDHI_LOWER_ONLY') != 'y':
            raise ValueError('SDHI lower-only separation missing')
    if profile['mode'].startswith('ether-'):
        denied += ['CONFIG_RZV_ETHER1', 'CONFIG_NETINIT_THREAD',
                   'CONFIG_NSH_NETINIT', 'CONFIG_NETUTILS_DHCPC']
        if config.get('CONFIG_NETDEV_LATEINIT') != 'y':
            raise ValueError('Ethernet early registration remains enabled')
    if profile['mode'] == 'ipc-local-loopback':
        denied += ['CONFIG_SMP']
        if config.get('CONFIG_RZV_IPC_LOCAL') != 'y':
            raise ValueError('CPU-local backend missing')
    if profile['mode'] == 'wdt-nonstart':
        denied += ['CONFIG_RZV_WDT1', 'CONFIG_RZV_WDT2', 'CONFIG_RZV_WDT3',
                   'CONFIG_RZV_WDT_INTERRUPT_MODE', 'CONFIG_EXAMPLES_WATCHDOG',
                   'CONFIG_MCUBOOT_WATCHDOG']
    denied += [key for key in config if key.endswith('_SERIAL_CONSOLE') and
               key != 'CONFIG_NO_SERIAL_CONSOLE']
    if any(config.get(key) in ('y', 'm') for key in denied):
        raise ValueError('prohibited setting: ' + ','.join(
            key for key in denied if config.get(key) in ('y', 'm')))
    modes = [key for key, value in config.items()
             if key.startswith('CONFIG_TESTING_RZV_HWTEST_MODE_') and value == 'y']
    if modes != [profile['mode_key']]:
        raise ValueError('test mode is ambiguous')
    elf = directory / 'nuttx.elf'
    symbols = subprocess.check_output(['arm-none-eabi-nm', str(elf)], text=True)
    def symbol(name, types='\\w'):
        return re.findall(r'(?m)^([0-9a-fA-F]+)\s+[' + types + r']\s+' +
                          re.escape(name) + '$', symbols)
    if len(symbol('hwtest_main', 'Tt')) != 1 or len(symbol('_SEGGER_RTT')) != 1:
        raise ValueError('callable hwtest or exact RTT symbol missing')
    registered = builtin_entry(elf, int(symbol('hwtest_main', 'Tt')[0], 16))
    strings = subprocess.check_output(['arm-none-eabi-strings', '-n', '1', str(elf)], text=True).splitlines()
    if 'hwtest' not in strings or profile['mode'] not in strings:
        raise ValueError('builtin name/mode absent from artifact')
    for case in profile['required_case_ids']:
        suite, name = case.split('.', 1)
        if suite not in strings or name not in strings:
            raise ValueError('required case absent from artifact: ' + case)
    receipt = json.loads((directory/'build-receipt.json').read_text())
    if not isinstance(receipt, dict) or not isinstance(receipt.get('file_sha256'), dict):
        raise ValueError('build receipt digest object missing')
    if receipt.get('profile') != profile['profile'] or receipt.get('build_exit') != 0:
        raise ValueError('build receipt mismatch')
    source_state_bytes = source_state_path.read_bytes()
    source_state = json.loads(source_state_bytes)
    source_digest = hashlib.sha256(source_state_bytes).hexdigest()
    if receipt.get('source_state_sha256') != source_digest:
        raise ValueError('source-state digest missing or mismatched')
    commits = source_state.get('commits') if isinstance(source_state, dict) else None
    if not isinstance(commits, dict) or set(commits) != {'px4', 'nuttx', 'apps'} or \
            any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value)
                for value in commits.values()) or receipt.get('submodule_commits') != commits:
        raise ValueError('source-state commits missing or mismatched')
    compiler = source_state.get('compiler')
    if not isinstance(compiler, str) or not compiler or receipt.get('compiler') != compiler:
        raise ValueError('source-state compiler missing or mismatched')
    for filename, expected in receipt['file_sha256'].items():
        if Path(filename).name != filename:
            raise ValueError('invalid receipt filename')
        if hashlib.sha256((directory/filename).read_bytes()).hexdigest() != expected:
            raise ValueError('build receipt digest mismatch: ' + filename)
    for filename in ('nuttx.elf', 'resolved.config', 'nuttx.map', 'System.map'):
        if filename not in receipt['file_sha256']:
            raise ValueError('missing build digest: ' + filename)
    if profile['mode'] == 'scif-internal-loopback':
        if len(symbol('arm_serialinit')) != 1:
            raise ValueError('SCIF serial registration missing/ambiguous')
        # The unused up_putc function is garbage-collected with an RTT console.
        # Inspect the actual compiler object for the unique implementation.
        obj = directory / 'rzv_scif.o'
        if any(name not in receipt['file_sha256'] for name in ('rzv_scif.o', 'libarch.a')):
            raise ValueError('SCIF compiler/link-input provenance missing')
        member = subprocess.check_output(['arm-none-eabi-ar', 'p',
                                          str(directory/'libarch.a'), 'rzv_scif.o'])
        if member != obj.read_bytes() or 'libarch.a(rzv_scif.o)' not in (directory/'nuttx.map').read_text():
            raise ValueError('SCIF object is not the recorded linker input')
        definitions = subprocess.check_output(['arm-none-eabi-nm', str(obj)], text=True)
        providers = subprocess.check_output(['arm-none-eabi-nm', '-A', '--defined-only',
                                             str(directory/'libarch.a')], text=True)
        for name in ('arm_serialinit', 'up_putc'):
            owners = re.findall(r'(?m)^(.+):\w+\s+[Tt]\s+' + name + '$', providers)
            if len(owners) != 1 or not owners[0].endswith(':rzv_scif.o'):
                raise ValueError('multiple/wrong serial providers: ' + name)
            if len(re.findall(r'(?m)^\w+\s+T\s+' + name + '$', definitions)) != 1:
                raise ValueError('SCIF provider missing/ambiguous: ' + name)
    if profile['mode'] == 'xspi-authority-guard':
        validator = symbol('board_xspi_paramfs_validate', 'Ww')
        if len(validator) != 1:
            raise ValueError('xSPI validator was overridden or ambiguous')
        # Current ARM32 default body is mvn r0,#133; bx lr: return -ENOTSUP
        # (134 in this NuttX ABI). Verify the compiled denial, not just weak type.
        body = elf32_bytes(elf.read_bytes(), int(validator[0], 16), 8, executable=True)
        if body != bytes.fromhex('8500e0e31eff2fe1'):
            raise ValueError('xSPI weak validator is not the default denial')
    return {'status': 'BUILD-CHECKED', 'profile': profile['profile'],
            'elf': str(elf), 'elf_sha256': hashlib.sha256(elf.read_bytes()).hexdigest(),
            'config_sha256': hashlib.sha256((directory/'resolved.config').read_bytes()).hexdigest(),
            'rtt_address': '0x' + symbol('_SEGGER_RTT')[0],
            'builtin': registered, 'source_state_sha256': source_digest,
            'submodule_commits': commits,
            'required_case_ids': profile['required_case_ids'],
            'target_prerequisites_verified': False, 'artifact_authorized': False,
            'on_target': 'NOT-RUN'}


def verify_native(profile, directory, source_state_path, manifest):
    """Admit a native image, preserving the stricter existing 14-profile gate."""
    receipt = json.loads((directory/'build-receipt.json').read_text())
    source_bytes = source_state_path.read_bytes()
    source = json.loads(source_bytes)
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if receipt.get('profile') != profile['profile'] or receipt.get('build_exit') != 0:
        raise ValueError('native build receipt mismatch')
    if receipt.get('source_state_sha256') != source_hash:
        raise ValueError('source-state digest mismatch')
    archived_policy = source_state_path.parent/'sample-profiles.json'
    if not archived_policy.is_file() or json.loads(archived_policy.read_text()) != manifest or \
            receipt.get('manifest_sha256') != INVENTORY.digest(archived_policy) or \
            source.get('manifest_sha256') != INVENTORY.digest(archived_policy):
        raise ValueError('native manifest provenance mismatch')
    commits = source.get('commits', {})
    if set(commits) != {'px4', 'nuttx', 'apps'} or any(
            not re.fullmatch(r'[0-9a-f]{40}', str(v)) for v in commits.values()):
        raise ValueError('invalid source revisions')
    if receipt.get('submodule_commits') != commits or not source.get('compiler') or \
            receipt.get('compiler') != source['compiler']:
        raise ValueError('build provenance mismatch')
    required = {'nuttx.elf', 'resolved.config', 'nuttx.map', 'System.map', 'linker-script.ld'}
    hashes = receipt.get('file_sha256', {})
    if not required <= hashes.keys():
        raise ValueError('missing native archive digest')
    for name, expected in hashes.items():
        if Path(name).name != name or INVENTORY.digest(directory/name) != expected:
            raise ValueError('native archive digest mismatch: ' + name)
    if receipt.get('defconfig_sha256') != profile['defconfig_sha256']:
        raise ValueError('requested configuration digest mismatch')
    defconfig = str(INVENTORY.BOARD/'configs'/profile['profile']/'defconfig')
    inputs = {x['path']: x.get('sha256') for x in source.get('source_files', [])}
    if inputs.get(defconfig) != profile['defconfig_sha256']:
        raise ValueError('configuration absent from source snapshot')
    linker_path = str(INVENTORY.BOARD/'scripts'/('rdk-rzv2h_' + profile['core'] + '.ld'))
    if inputs.get(linker_path) != hashes['linker-script.ld']:
        raise ValueError('wrong linker input provenance')
    config = INVENTORY.read_config(directory/'resolved.config')
    actual = INVENTORY.identity(config, manifest['core_default'])
    for key in ('core', 'console', 'entrypoint'):
        if actual[key] != profile[key]:
            raise ValueError('resolved native identity mismatch: ' + key)
    elf = directory/'nuttx.elf'
    data = elf.read_bytes()
    if len(data) < 52:
        raise ValueError('truncated ELF')
    entry = struct.unpack_from('<I', data, 24)[0]
    elf32_bytes(data, entry & ~1, 1, executable=True)
    symbols_text = subprocess.check_output(['arm-none-eabi-nm', str(elf)], text=True)
    symbols = {name: int(address, 16) for address, _, name in
               re.findall(r'(?m)^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$', symbols_text)}
    if symbols.get('__start', -1) & ~1 != entry & ~1:
        raise ValueError('ELF entry does not match startup')
    core = profile['core']
    if core == 'cm33':
        if config.get('CONFIG_ARCH_CORTEXM33') != 'y' or not entry & 1 or not 0x08002800 <= (entry & ~1) < 0x080f8000:
            raise ValueError('CM33 architecture/Thumb/entry range mismatch')
    else:
        expected_start = 0x40800000 if core == 'cr8_0' else 0x41800000
        if config.get('CONFIG_ARCH_CORTEXR8') != 'y' or entry != expected_start or symbols.get(core.upper()) != 1:
            raise ValueError('CR8 architecture/private linker identity mismatch')
    if profile['entrypoint'] not in symbols:
        raise ValueError('configured entrypoint is not linked')
    registered = None
    if profile.get('builtin'):
        builtin = profile['builtin']
        if builtin['symbol'] not in symbols:
            raise ValueError('native builtin entry not linked: ' + builtin['symbol'])
        registered = builtin_entry(elf, symbols[builtin['symbol']], builtin['name'])
    rtt = symbols.get('_SEGGER_RTT')
    if profile['console'].startswith('rtt') and rtt is None:
        raise ValueError('RTT console without compiled control block')
    if rtt is not None and core.startswith('cr8'):
        low = 0x081a0000 if core == 'cr8_0' else 0x081e0000
        uncached = low <= rtt < low + 0x20000
        private_cached = low - 0x20000 <= rtt < low or \
            ((0x40800000 if core == 'cr8_0' else 0x41800000) <= rtt <
             (0x41800000 if core == 'cr8_0' else 0x42800000))
        if not uncached and (profile['console'].startswith('rtt') or not private_cached):
            raise ValueError('primary RTT console outside core-private noncache SRAM')
    if profile.get('legacy_profile'):
        legacy = json.loads(Path(__file__).with_name('rzv2h-sample-profiles.json').read_text())
        matches = [x for x in legacy['profiles'] if x['profile'] == profile['legacy_profile']]
        if len(matches) != 1:
            raise ValueError('legacy profile missing')
        verify(matches[0], directory, source_state_path)
    return {'status': 'BUILD-CHECKED', 'profile': profile['profile'],
            'core': core, 'console': actual['console'], 'entrypoint': actual['entrypoint'],
            'elf': str(elf), 'elf_sha256': hashes['nuttx.elf'],
            'config_sha256': hashes['resolved.config'], 'source_state_sha256': source_hash,
            'submodule_commits': commits, 'rtt_address': hex(rtt) if rtt is not None else None,
            'builtin': registered, 'waitpid': all(config.get(x) == 'y' for x in
                ('CONFIG_SCHED_WAITPID','CONFIG_SCHED_HAVE_PARENT','CONFIG_SCHED_CHILD_STATUS')),
            'application_entry': hex(symbols[profile['builtin']['symbol']
                                           if profile.get('builtin') else profile['entrypoint']]),
            'requirements': profile['requirements'], 'hazards': profile['hazards'],
            'runtime_blocker': profile.get('reason'), 'on_target': 'NOT-RUN',
            'artifact_authorized': False, 'target_prerequisites_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--builds', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-state', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    native = manifest.get('schema_version') == 2 and manifest.get('kind') == 'rzv2h-native-samples'
    if native:
        INVENTORY.validate(manifest)
    profiles = manifest['profiles']
    results = []
    for profile in profiles:
        try:
            results.append(verify_native(profile, args.builds/profile['profile'], args.source_state, manifest)
                           if native else verify(profile, args.builds/profile['profile'], args.source_state))
        except (OSError, ValueError, KeyError, TypeError, struct.error, subprocess.CalledProcessError) as error:
            results.append({'status': 'NOT-READY', 'profile': profile['profile'],
                            'reason': str(error), 'on_target': 'NOT-RUN',
                            'target_prerequisites_verified': False,
                            'artifact_authorized': False})
    args.output.write_text(json.dumps(results, indent=2)+'\n')
    for item in results:
        print(item['profile'], item['status'], item.get('reason', ''))
    print('Target use is unauthorized; runtime prerequisites are unverified.')
    return 0 if all(item['status'] == 'BUILD-CHECKED' for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
