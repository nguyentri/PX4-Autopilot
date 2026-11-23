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
    contracts = INVENTORY.archived_contracts(source_state_path, receipt)
    if contracts:
        legacy = [x for x in contracts['legacy_contract']['profiles']
                  if x['profile'] == profile['profile']]
        if legacy != [profile]:
            raise ValueError('archived legacy profile contract mismatch')
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
        # rzv_serial.c is the single arm_serialinit()/up_putc() provider for
        # SCI-B and SCIF; it forwards SCIF registration and output to the
        # rzv_scif.c entry points, which must be unique and in rzv_scif.o.
        owners_by_name = {'arm_serialinit': 'rzv_serial.o', 'up_putc': 'rzv_serial.o',
                          'rzv_scif_serialinit': 'rzv_scif.o', 'rzv_scif_putc': 'rzv_scif.o'}
        for name, owner in owners_by_name.items():
            owners = re.findall(r'(?m)^(.+):\w+\s+[Tt]\s+' + name + '$', providers)
            if len(owners) != 1 or not owners[0].endswith(':' + owner):
                raise ValueError('multiple/wrong serial providers: ' + name)
            if owner == 'rzv_scif.o' and len(re.findall(r'(?m)^\w+\s+T\s+' + name + '$', definitions)) != 1:
                raise ValueError('SCIF provider missing/ambiguous: ' + name)
        dispatcher = subprocess.check_output(['arm-none-eabi-nm', '--undefined-only', str(directory/'libarch.a')],
                                             text=True).split('rzv_serial.o:', 1)[-1].split('\n\n', 1)[0]
        # up_putc() may route to RTT instead, so only registration must forward.
        if not re.search(r'(?m)^\s+U rzv_scif_serialinit$', dispatcher):
            raise ValueError('serial dispatcher does not forward to SCIF: rzv_scif_serialinit')
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
            'contract_inputs': source_state.get('contract_inputs', []),
            'target_prerequisites_verified': False, 'artifact_authorized': False,
            'on_target': 'NOT-RUN'}


def elf32_symbols(data):
    """Keep symbol types, sizes and duplicate definitions for compiled checks."""
    if len(data) < 52:
        raise ValueError('truncated instance ELF')
    offset = struct.unpack_from('<I', data, 32)[0]
    stride, count = struct.unpack_from('<HH', data, 46)
    if stride < 40 or not count or offset + stride * count > len(data):
        raise ValueError('invalid instance ELF section table')
    sections = [struct.unpack_from('<10I', data, offset + stride * i)
                for i in range(count)]
    result = {}
    for section in sections:
        if section[1] != 2:  # SHT_SYMTAB
            continue
        start, size, link, entry_size = section[4], section[5], section[6], section[9]
        if entry_size != 16 or size % entry_size or start + size > len(data) or link >= count:
            raise ValueError('invalid instance ELF symbol table')
        strings = sections[link]
        if strings[1] != 3 or strings[4] + strings[5] > len(data):
            raise ValueError('invalid instance ELF symbol names')
        names = data[strings[4]:strings[4] + strings[5]]
        for position in range(start, start + size, entry_size):
            name, value, length, info, _, index = struct.unpack_from('<IIIBBH', data, position)
            if name >= len(names):
                raise ValueError('invalid instance ELF symbol name')
            end = names.find(b'\0', name)
            if end < 0:
                raise ValueError('unterminated instance ELF symbol name')
            text = names[name:end].decode('ascii')
            if text:
                result.setdefault(text, []).append((value, length, info & 15, index, info >> 4))
    return result


def compiled_instance_cases(elf, required_case_ids, required_symbols):
    """Validate the ARM32 getter/table against the archived ordered contract.

    Strings may be suffix-pooled, so only their compiled pointers identify a
    case. The simple count/table getter is decoded conservatively; unsupported
    instruction shapes fail admission instead of falling back to string scans.
    """
    if not isinstance(required_case_ids, list) or not required_case_ids or \
            any(not isinstance(case, str) for case in required_case_ids) or \
            len(set(required_case_ids)) != len(required_case_ids):
        raise ValueError('invalid instance case contract')
    expected_count = len(required_case_ids)
    table_size = expected_count * 12  # ARM32 hwtest_case_s: three pointers
    data = elf.read_bytes()
    definitions = elf32_symbols(data)

    def function(name):
        candidates = [x for x in definitions.get(name, []) if x[3] != 0]
        if len(candidates) != 1 or candidates[0][2] != 2 or \
                candidates[0][4] not in (0, 1) or not candidates[0][1]:
            raise ValueError('instance callable provider missing/ambiguous: ' + name)
        address, size = candidates[0][:2]
        elf32_bytes(data, address & ~1, size, executable=True)
        return address, size

    for name in set(required_symbols) | {'hwtest_main', 'driver_instance_cases'}:
        function(name)
    getter, size = function('driver_instance_cases')
    if getter & 3 or size % 4:
        raise ValueError('unsupported ARM instance case provider')
    code = elf32_bytes(data, getter, size, executable=True)
    # The pointer argument starts in r0. Only the count store, immediate MOV,
    # PC-relative table load and return are admitted for this getter ABI.
    registers = [None] * 16
    registers[0] = 'count-pointer'
    count = table_address = None
    for index in range(min(size // 4, 8)):
        word = struct.unpack_from('<I', code, index * 4)[0]
        if word & 0xffff0000 == 0xe3a00000:  # MOV immediate
            destination = (word >> 12) & 15
            if destination not in (1, 2, 3, 12):
                raise ValueError('unsupported ARM instance case provider register')
            immediate, rotate = word & 255, ((word >> 8) & 15) * 2
            registers[destination] = ((immediate >> rotate) |
                (immediate << ((32 - rotate) % 32))) & 0xffffffff
        elif word & 0xffff0fff == 0xe5800000:  # STR rN,[r0]
            if registers[0] != 'count-pointer' or count is not None:
                raise ValueError('instance case provider count store mismatch')
            count = registers[(word >> 12) & 15]
        elif word & 0xff7ff000 == 0xe51f0000:  # LDR r0,[pc,+/-imm]
            literal = getter + index * 4 + 8
            literal += (word & 4095) * (1 if word & (1 << 23) else -1)
            registers[0] = struct.unpack('<I', elf32_bytes(data, literal, 4))[0]
        elif word == 0xe12fff1e:  # BX lr
            table_address = registers[0]
            break
        else:
            raise ValueError('unsupported ARM instance case provider')
    if count != expected_count or type(table_address) is not int or not table_address:
        raise ValueError('instance case provider count/table mismatch')
    tables = [x for x in definitions.get('g_cases', [])
              if x[0] == table_address and x[3] != 0]
    if len(tables) != 1 or tables[0][1:3] != (table_size, 1):
        raise ValueError('instance compiled case table size/type mismatch')
    table = elf32_bytes(data, table_address, table_size)

    def cstring(address):
        if not address:
            raise ValueError('instance case string pointer is null')
        value = bytearray()
        for index in range(128):
            byte = elf32_bytes(data, address + index, 1)[0]
            if byte == 0:
                return value.decode('ascii')
            value.append(byte)
        raise ValueError('unterminated instance case string')

    actual = []
    pointers = []
    for index in range(expected_count):
        suite, name, pointer = struct.unpack_from('<3I', table, index * 12)
        suite, name = cstring(suite), cstring(name)
        case = suite + '.' + name
        if index >= len(required_case_ids) or case != required_case_ids[index]:
            raise ValueError('instance compiled case identity/order mismatch')
        address, _ = function(name)
        if not pointer or pointer != address or pointer in pointers:
            raise ValueError('instance case function pointer mismatch: ' + case)
        elf32_bytes(data, pointer & ~1, 1, executable=True)
        actual.append(case)
        pointers.append(pointer)
    if actual != required_case_ids:
        raise ValueError('instance compiled case count mismatch')
    main, main_size = function('hwtest_main')
    main_code = elf32_bytes(data, main & ~1, main_size, executable=True)
    calls = 0
    for index in range(0, len(main_code) - 3, 4):
        word = struct.unpack_from('<I', main_code, index)[0]
        if word & 0xff000000 == 0xeb000000:  # ARM BL, unconditional
            displacement = word & 0xffffff
            if displacement & 0x800000:
                displacement -= 0x1000000
            calls += main + index + 8 + displacement * 4 == getter
    if calls != 1:
        raise ValueError('hwtest does not call the instance case provider')
    return actual


def verify_instance(profile, config, symbols, strings, catalog, receipt):
    """Check the selected tuple against resolved selectors and linked drivers."""
    cell = next((x for x in catalog['instances'] if x['instance_id'] == profile['instance_id']), None)
    if cell is None or cell['profile'] != profile['profile'] or \
            INVENTORY.instance_key(cell['core'], cell['instance']) != \
            INVENTORY.instance_key(profile['core'], profile['instance']):
        raise ValueError('instance catalogue/profile mismatch')
    for key in ('instance_id', 'instance'):
        if receipt.get(key) != profile[key]:
            raise ValueError('build receipt instance mismatch: ' + key)
    if receipt.get('core') != profile['core']:
        raise ValueError('build receipt instance core mismatch')
    instance = profile['instance']
    number = {'riic':1, 'spi':2, 'sci-i2c':3, 'sci-spi':4, 'gpt':5,
              'ether':6, 'sdhi':7, 'wdt':8}.get(instance['family'])
    if number is None:
        raise ValueError('unknown compiled instance family')
    # These selectors implement fixed dispatch; their meaning cannot be weakened
    # by coherently editing and rehashing the archived catalogue.
    required = dict(cell['required_config'])
    required.update(CONFIG_TESTING_RZV_HWTEST_MODE_DRIVER_INSTANCE='y',
                    CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY=str(number),
                    CONFIG_TESTING_RZV_HWTEST_INSTANCE_CHANNEL=str(instance['channel']),
                    CONFIG_TESTING_RZV_HWTEST_INSTANCE_OUTPUT=str(int(instance['output'] == 'B')),
                    CONFIG_RZV2H_SAMPLE_TEST_API='y', CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT='y')
    prefix = {'riic':'I2C', 'spi':'SPI', 'sci-i2c':'SCI', 'sci-spi':'SCI',
              'gpt':'GPT', 'ether':'ETHER', 'wdt':'WDT'}.get(instance['family'])
    if prefix:
        required['CONFIG_RZV_'+prefix+str(instance['channel'])] = \
            'n' if instance['family'] in ('sci-i2c', 'sci-spi') else 'y'
    if instance['family'] == 'gpt':
        required['CONFIG_RZV_PWM'] = 'y'
    if instance['family'] == 'ether':
        required.update(CONFIG_RZV_ETHERNET='y', CONFIG_NETDEV_LATEINIT='y',
                        CONFIG_NSH_NETINIT='n', CONFIG_NETINIT_THREAD='n',
                        CONFIG_NETUTILS_DHCPC='n')
        required['CONFIG_RZV_ETHER'+str(1-instance['channel'])] = 'n'
    if instance['family'] == 'sdhi':
        required.update(CONFIG_RZV_SDHI='y', CONFIG_RZV2H_SDHI_LOWER_ONLY='y',
                        CONFIG_RZV2H_BUILD_CM33='n', CONFIG_MMCSD='n',
                        CONFIG_MMCSD_SDIO='n', CONFIG_FS_FAT='n')
    if instance['family'] == 'wdt':
        required.update(CONFIG_RZV_WDT='y', CONFIG_WATCHDOG_AUTOMONITOR='n',
                        CONFIG_RZV2H_WDT_TEST='n', CONFIG_RZV_WDT_INTERRUPT_MODE='n')
        for channel in range(4):
            required['CONFIG_RZV_WDT'+str(channel)] = 'y' if channel == instance['channel'] else 'n'
    if instance['family'] in ('sci-i2c', 'sci-spi'):
        required['CONFIG_RZV_SCI'+str(instance['channel'])+'_'+instance['family'][4:].upper()] = 'y'
        required['CONFIG_RZV_SCI'+str(instance['channel'])+('_SPI' if instance['family'] == 'sci-i2c' else '_I2C')] = 'n'
    for key, value in required.items():
        if config.get(key, 'n') != value:
            raise ValueError('resolved instance selector mismatch: ' + key)
    modes = [key for key, value in config.items()
             if key.startswith('CONFIG_TESTING_RZV_HWTEST_MODE_') and value == 'y']
    if modes != ['CONFIG_TESTING_RZV_HWTEST_MODE_DRIVER_INSTANCE']:
        raise ValueError('conflicting instance test modes')
    for channel in range(10):
        selected = [key for key in ('CONFIG_RZV_SCI'+str(channel)+'_SPI',
                                   'CONFIG_RZV_SCI'+str(channel)+'_I2C',
                                   'CONFIG_RZV_SCI'+str(channel)) if config.get(key) == 'y']
        if len(selected) > 1:
            raise ValueError('conflicting SCI instance modes')
    provider = {1:'rzv_i2c_initialize', 2:'rzv_spibus_initialize',
                3:'rzv_sci_i2c_initialize', 4:'rzv_sci_spi_initialize',
                5:'rzv_gpt_initialize_output', 6:'rzv_ether_initialize',
                7:'rzv_sdhi_initialize', 8:'rzv_wdt_initialize'}[number]
    providers = set(cell['required_symbols']) | {'hwtest_main', provider}
    if number in (7, 8):
        providers.add('rzv2h_' + instance['family'] + '_sample_state_at')
    for name in providers:
        if name not in symbols:
            raise ValueError('instance implementation not linked: ' + name)
    contract = INVENTORY.validate_hwtest(profile['hwtest_contract'])
    if contract['mode'] not in strings:
        raise ValueError('instance mode absent from artifact')
    return providers - {'hwtest_main'}


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
    contracts = INVENTORY.archived_contracts(source_state_path, receipt,
                                            required='instance_id' in profile)
    matches = [x for x in manifest['profiles'] if x['profile'] == profile['profile']]
    if matches != [profile]:
        raise ValueError('native profile differs from archived manifest')
    if contracts:
        INVENTORY.validate(manifest, catalog=contracts['driver_coverage'], live=False)
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
        expected_start = 0x40800000 if core == 'cr8_0' else 0x44000000
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
            ((0x40800000 if core == 'cr8_0' else 0x44000000) <= rtt <
             (0x41800000 if core == 'cr8_0' else 0x45000000))
        if not uncached and (profile['console'].startswith('rtt') or not private_cached):
            raise ValueError('primary RTT console outside core-private noncache SRAM')
    hwtest_contract = profile.get('hwtest_contract')
    if 'instance_id' in profile:
        strings = subprocess.check_output(['arm-none-eabi-strings', '-n', '1', str(elf)], text=True).splitlines()
        providers = verify_instance(profile, config, symbols, strings,
                                    contracts['driver_coverage'], receipt)
        compiled_instance_cases(elf, hwtest_contract['required_case_ids'], providers)
    if profile.get('legacy_profile'):
        # Historical unbound archives retain their old admission path. They
        # cannot acquire instance completeness without the three-input bundle.
        legacy = contracts['legacy_contract'] if contracts else json.loads(INVENTORY.LEGACY.read_text())
        matches = [x for x in legacy['profiles'] if x['profile'] == profile['legacy_profile']]
        if len(matches) != 1:
            raise ValueError('legacy profile missing')
        verify(matches[0], directory, source_state_path)
        hwtest_contract = matches[0]
    if contracts and profile.get('oracle') == 'hwtest' and hwtest_contract is None:
        hwtest_contract = contracts['driver_coverage'].get('native_hwtest_contracts', {}).get(profile['profile'])
        if hwtest_contract is None:
            raise ValueError('unknown native hwtest suite contract')
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
            'contract_inputs': source.get('contract_inputs', []),
            'contract_binding': 'archived' if contracts else 'historical-unbound',
            'hwtest_contract': hwtest_contract,
            **{key:profile[key] for key in ('instance_id', 'instance') if key in profile},
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
        contracts = INVENTORY.archived_contracts(args.source_state)
        INVENTORY.validate(manifest, catalog=contracts.get('driver_coverage'), live=False)
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
