#!/usr/bin/env python3
"""Admit sealed RZ/V2H PX4 build archives using installation-local policy."""

import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zlib

ROOT = Path(__file__).resolve().parents[1]
POLICY = Path(__file__).with_name('rzv2h-px4-profiles.json')
MAX_FILE = 128 * 1024 * 1024
MAX_ARCHIVE = 2 * 1024 * 1024 * 1024
MAX_FILES = 10000
SPLIT_SECTIONS = {
    'header': ['.header', '.header_reserved'],
    'itcm': ['.itcm_load_section0', '.itcm_load_section1'],
    'sram': ['.sram_load_section0', '.sram_load_section1'],
    'sdram': ['.sdram_text_section', '.sdram_data_section'],
}
RTT_DEPENDENCIES = (
    ('RTT.zip', 'RTT_ARCHIVE_SHA256'),
    ('RTT/RTT/SEGGER_RTT.c', 'RTT_SOURCE_SHA256'),
    ('RTT/RTT/SEGGER_RTT.h', 'RTT_HEADER_SHA256'),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def identity(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def reject_json_constant(value):
    raise ValueError('non-finite JSON constant: '+value)


def load_json(path):
    require(path.stat().st_size <= MAX_FILE, 'oversized input: ' + str(path))
    return json.loads(path.read_text(), object_pairs_hook=no_duplicates,parse_constant=reject_json_constant)


def safe_relative(name):
    require(isinstance(name, str) and name and '\\' not in name,
            'invalid archive path')
    path = Path(name)
    require(not path.is_absolute() and all(p not in ('', '.', '..') for p in name.split('/')),
            'unsafe archive path: ' + name)
    return path


def inventory(directory, exclude=()):
    """Archive inventories are exhaustive; symlinks and special files are refused."""
    records = {}
    total = 0
    for count,path in enumerate(directory.rglob('*'),1):
        name = path.relative_to(directory).as_posix()
        require(count <= MAX_FILES*5 and len(Path(name).parts) <= 32, 'archive traversal limit')
        require(not path.is_symlink(), 'archive symlink: ' + name)
        if path.is_dir():
            continue
        require(path.is_file(), 'nonregular archive input: ' + name)
        size = path.stat().st_size
        total += size
        require(size <= MAX_FILE, 'oversized archive input: ' + name)
        require(total <= MAX_ARCHIVE and len(records) < MAX_FILES, 'aggregate archive limit')
        if name not in exclude:
            records[name] = {'size': size, 'sha256': digest(path)}
    return dict(sorted(records.items()))


def check_inventory(directory, expected, exclude=()):
    require(isinstance(expected, dict), 'missing file inventory')
    for name in expected:
        safe_relative(name)
    actual = inventory(directory, exclude)
    require(actual == expected, 'file inventory mismatch: ' + ', '.join(
        name for name in sorted(set(actual) | set(expected))
        if actual.get(name) != expected.get(name))[:1000])


def policy(source=None):
    result = load_json(POLICY)
    profiles = result['profiles']
    names = [p['target'] for p in profiles]
    require(result['schema_version'] == 1 and result['policy_version'] == 3,
            'unsupported policy version')
    require(len(names) == 11 and len(set(names)) == 11, 'policy must classify eleven unique targets')
    if source:
        available = sorted('renesas_' + p.parent.name + '_' + p.stem
                           for p in (source/'boards/renesas').glob('rdk-rzv2h*/*.px4board')
                           if not p.stem.endswith('_bk'))
        require(sorted(names) == available, 'root target matrix drift')
        for name, expected in result['contract_owners'].items():
            require(digest(source/safe_relative(name)) == expected, 'contract owner drift: ' + name)
    return result


def select_profiles(contract, targets):
    names = [p['target'] for p in contract['profiles']]
    require(len(targets) == len(set(targets)), 'duplicate explicit target')
    require(not set(targets) - set(names), 'unknown target')
    selected = set(targets or names)
    for p in contract['profiles']:
        if p['target'] in selected and p['peer']:
            selected.add(p['peer'])
    return [p for p in contract['profiles'] if p['target'] in selected]


def config_values(text):
    return dict(re.findall(r'^(CONFIG_[A-Z0-9_]+)=(.+)$', text, re.M))


def size_allowed(size, maximum):
    return type(size) is int and 0 <= size <= maximum


def cr81_capacity(linker, cmake):
    """Only known literal constants and the reviewed section mapping are accepted."""
    values = []
    for key, expected in [('HEADER_LENGTH', 0x80), ('ITCM_PRV_LENGTH', 0x1fe00),
                          ('SRAM_CACHE_PRV_LENGTH', 0x20000), ('DDR_CACHE_LENGTH', 0x800000)]:
        match = re.search(r'^' + key + r'\s*=\s*(0x[0-9a-fA-F]+)\s*;', linker, re.M)
        if not match and key == 'SRAM_CACHE_PRV_LENGTH':
            match = re.search(r'^' + key + r'\s*=\s*DEFINED\(CR8_0\)\s*\?\s*'
                              r'(0x[0-9a-fA-F]+)\s*:\s*0x00020000\s*;', linker, re.M)
        require(match and int(match[1], 16) == expected, 'CR8-1 capacity source drift: ' + key)
        values.append(int(match[1], 16))
    for sections in SPLIT_SECTIONS.values():
        require(' '.join('-j ' + s for s in sections) in cmake, 'split section mapping drift')
    require('cat ${rzv_header_binary} ${rzv_itcm_binary} ${rzv_sram_binary} ${rzv_sdram_binary}'
            in cmake, 'split concatenation drift')
    require('_sdram_load_size = _sdram_data_end - _sdram_text_start;' in linker,
            'SDRAM padding contract drift')
    return sum(values)


def bounded(start, size):
    require(type(start) is int and type(size) is int and
            0 <= start < 2**32 and 0 <= size <= 2**32 - start, 'ARM32 range overflow')


def in_regions(start, size, regions):
    bounded(start, size)
    return any(base <= start and start + size <= base + length for base, length in regions)


def elf_view(data):
    require(52 <= len(data) <= MAX_FILE and data[:7] == b'\x7fELF\x01\x01\x01',
            'expected little-endian ELF32')
    header = struct.unpack_from('<HHIIIIIHHHHHH', data, 16)
    kind, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstr = header
    require((kind, machine, version, ehsize, phsize, shsize) == (2, 40, 1, 52, 32, 40),
            'expected executable ARM ELF32')
    require(0 < phnum <= 128 and 0 < shnum <= 32768 and shstr < shnum and
            phoff >= 52 and phoff + phnum * phsize <= len(data) and
            shoff >= 52 and shoff + shnum * shsize <= len(data), 'invalid ELF headers')
    loads = []
    for i in range(phnum):
        kind, offset, va, pa, fs, ms, perm, align = struct.unpack_from('<8I', data, phoff+i*32)
        if kind != 1 or not ms:
            continue
        bounded(va, ms)
        bounded(pa, ms)
        require(fs <= ms and offset + fs <= len(data), 'invalid ELF load size')
        require(not align or not (align & (align-1)) and va % align == offset % align,
                'invalid ELF load alignment')
        loads.append({'address': va, 'physical': pa, 'size': fs, 'memory': ms,
                      'flags': perm, 'data': data[offset:offset+fs]})
    headers = [struct.unpack_from('<10I', data, shoff+i*40) for i in range(shnum)]
    strings = headers[shstr]
    require(strings[4] + strings[5] <= len(data), 'invalid ELF section strings')
    names = data[strings[4]:strings[4]+strings[5]]
    sections = {}
    for row in headers[1:]:
        name, kind, attrs, address, offset, size = row[:6]
        require(name < len(names) and b'\0' in names[name:], 'invalid ELF section name')
        name = names[name:].split(b'\0', 1)[0].decode('ascii')
        require(name not in sections, 'duplicate ELF section')
        bounded(address, size)
        require(kind == 8 or offset + size <= len(data), 'truncated ELF section')
        sections[name] = {'kind': kind, 'flags': attrs, 'address': address, 'size': size,
                          'data': b'' if kind == 8 else data[offset:offset+size]}
    require(loads, 'ELF has no load segments')
    ordered = sorted(loads,key=lambda row:row['address'])
    require(all(left['address']+left['memory'] <= right['address']
                for left,right in zip(ordered,ordered[1:])), 'overlapping ELF load segments')
    require(all(load['address']==load['physical'] for load in loads), 'unsupported relocated ELF load')
    return {'entry': entry, 'flags': flags, 'loads': loads, 'sections': sections}


def virtual_bytes(view, address, size):
    for load in view['loads']:
        offset = address - load['address']
        if 0 <= offset and offset + size <= load['size']:
            return load['data'][offset:offset+size]
    raise ValueError('address has no file-backed ELF load')


def tool(argv):
    return subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT, timeout=60)


def decompress(encoded, maximum):
    require(isinstance(encoded, str) and len(encoded) <= MAX_FILE, 'oversized package encoding')
    data = base64.b64decode(encoded, validate=True)
    parser = zlib.decompressobj()
    result = parser.decompress(data, maximum+1)
    require(len(result) <= maximum and parser.eof and not parser.unused_data and
            not parser.unconsumed_tail, 'invalid or excessive package decompression')
    return result


def check_output(archive, output):
    if output:
        resolved = output.resolve()
        require(not resolved.is_relative_to(archive.resolve()), 'checker output is inside archive')
        # Existing hardlinks can alias an archived file despite a different pathname.
        if resolved.exists():
            require(all(not resolved.samefile(p) for p in archive.rglob('*') if p.is_file()),
                    'checker output aliases archive')


def check_execution(row, name, path, command, log):
    require(row.get('id')==name and row.get('path')==path and row.get('command')==command,
            'execution identity mismatch: '+name)
    require(row.get('status')=='PASS' and type(row.get('exit')) is int and row['exit']==0 and
            all(row.get(k) is False for k in
                ('timed_out','cancelled','skipped','zero_tests','missing_summary')),
            'execution failed or incomplete: '+name)
    require(Path(row.get('log','')).name==log.name and isinstance(row.get('seconds'),(int,float)) and
            math.isfinite(row['seconds']) and row['seconds'] >= 0, 'execution log/time identity: '+name)
    text = log.read_text()
    require(not re.search(r'\.\.\. skipped\b|^SKIP\b|^FAILED\b|\bskipped=[1-9]',text,re.M),
            'execution log failed/skipped: '+name)
    counts = re.findall(r'Ran (\d+) tests?',text)
    if path.endswith('.py'):
        require(type(row.get('tests')) is int and row['tests']>0 and counts and
                sum(map(int,counts))==row['tests'], 'execution test count mismatch: '+name)


def check_host(archive):
    results = load_json(archive/'host/results.json')
    require([r['id'] for r in results] == policy()['host_tests'], 'host test selection mismatch')
    entries = {e['id']:e for e in load_json(ROOT/'Tools/rzv2h-regression-catalog.json')['scripts']}
    python = load_json(archive/'source-state.json')['python']['path']
    tree = ET.parse(archive/'host/junit.xml').getroot()
    require(len(tree.findall('testcase')) == len(results) and not tree.findall('.//failure') and
            not tree.findall('.//skipped'), 'host XML disagrees with results')
    for row in results:
        entry = entries[row['id']]
        argv = [part.format_map({'python':python}) for part in entry['command']]
        check_execution(row,entry['id'],entry['path'],argv,archive/'host'/(row['id']+'.log'))


def required_files(profile, core):
    name = profile['target']
    files = [name+s for s in ('.elf', '.map', '.bin')] + [
        'CMakeCache.txt', 'px4_boardconfig.h', 'boardconfig', 'build.ninja',
        'NuttX/nuttx/.config', 'NuttX/px4.bdat', 'ROMFS/romfs.img', 'ROMFS/romfs.txt',
        'etc/init.d/rcS', 'build.log', 'focused-results.json', 'dependency-inputs.json',
    ]
    if core['binary'] == 'split':
        files += [name+'_'+part+'.bin' for part in SPLIT_SECTIONS]
    if profile['hex']:
        files += [name+'.hex']
    if profile['package']:
        files += [name+'.px4', 'parameters.xml', 'airframes.xml']
    return files


def check_dependencies(directory, contract, config):
    dependencies = load_json(directory/'dependency-inputs.json')
    expected = {filename: contract['rtt_pins'][key] for filename, key in RTT_DEPENDENCIES}
    require(dependencies == (expected if config.get('CONFIG_SEGGER_RTT') == 'y' else {}),
            'download dependency provenance mismatch')
    for filename, expected_hash in dependencies.items():
        require(digest(directory/'dependencies'/safe_relative(filename)) == expected_hash,
                'download dependency pin mismatch')


def significant_lines(text):
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def check_archived_sources(directory, profile):
    source_state = load_json(directory.parents[1]/'source-state.json')
    for source in (directory/'sources').rglob('*'):
        if source.is_file():
            relative = source.relative_to(directory/'sources').as_posix()
            require(source_state['effective_inputs']['files'].get(relative, {}).get('sha256') == digest(source),
                    'archived source/effective input mismatch: '+relative)
    for relative, destination in profile['startup_sources'].items():
        installed = directory/safe_relative(destination)
        require(installed.is_file(), 'missing required startup: '+destination)
        require(significant_lines(installed.read_text()) ==
                significant_lines((directory/'sources'/relative).read_text()),
                'installed startup/source mismatch: '+relative)


def check_package(directory, profile):
    image = (directory/(profile['target']+'.bin')).read_bytes()
    package = load_json(directory/(profile['target']+'.px4'))
    prototype = load_json(directory/'sources'/profile['prototype'])
    for key in ('board_id', 'magic', 'image_maxsize'):
        require(package[key] == prototype[key] == profile[key], 'package identity/maximum: ' + key)
    require(package['board_revision'] == prototype['board_revision'] == 0, 'package revision')
    require(size_allowed(len(image), profile['image_maxsize']) and package['image_size'] == len(image),
            'package image size exceeds contract')
    require(decompress(package['image'], profile['image_maxsize']) == image, 'package payload mismatch')
    for field, filename in [('parameter_xml', 'parameters.xml'), ('airframe_xml', 'airframes.xml')]:
        data = (directory/filename).read_bytes()
        require(decompress(package[field], 16*1024*1024) == data, 'package metadata mismatch: '+field)
        ET.fromstring(data)


def check_binary(directory, profile, core, view, symbols):
    name = profile['target']
    image = (directory/(name+'.bin')).read_bytes()
    require(size_allowed(len(image), profile['image_maxsize']), 'image maximum exceeded')
    with tempfile.TemporaryDirectory(prefix='rzv2h-px4-check-', dir='/tmp') as temporary:
        output = Path(temporary)/'objcopy.bin'
        selections = SPLIT_SECTIONS if core['binary'] == 'split' else {'plain': []}
        parts = {}
        for part, sections in selections.items():
            tool(['arm-none-eabi-objcopy', '-O', 'binary',
                  *(arg for s in sections for arg in ('-j', s)), str(directory/(name+'.elf')), str(output)])
            data = output.read_bytes()
            parts[part] = data
            if part != 'plain':
                require(data == (directory/(name+'_'+part+'.bin')).read_bytes(), 'ELF/split mismatch: '+part)
        require(b''.join(parts.values()) == image, 'ELF/binary concatenation mismatch')
        if profile['hex']:
            tool(['arm-none-eabi-objcopy', '-O', 'ihex', str(directory/(name+'.elf')), str(output)])
            require(output.read_bytes() == (directory/(name+'.hex')).read_bytes(), 'hex/ELF mismatch')
    if core['binary'] != 'split':
        vectors = virtual_bytes(view, core['vector'], 8)
        stack, reset = struct.unpack('<II', vectors)
        require(reset == view['entry'] and reset & 1 and in_regions(stack-8, 8, core['regions']),
                'CM33 reset vector/stack mismatch')
        return
    require(len(parts['header']) == 128, 'CR8 native header size')
    words = struct.unpack('<32I', parts['header'])
    require(words[19:21] == (0x1234fedc, 0x562f5a52) and not any(words[21:]), 'native header signature/padding')
    destination_regions = [([0x12040000 if profile['core']=='CR8-0' else 0x12080000, 0x1fe00]),
                           ([0x08180000 if profile['core']=='CR8-0' else 0x081c0000, 0x20000]),
                           ([0x40800000 if profile['core']=='CR8-0' else 0x41800000, 0x800000])]
    require(words[0] == (0x20200080 if profile['core']=='CR8-0' else 0x21300080),
            'native flash source base')
    for i, part in enumerate(('itcm', 'sram', 'sdram')):
        source, destination, size, invsource, invdest, invsize = words[i*6:i*6+6]
        require((source ^ invsource, destination ^ invdest, size ^ invsize) == (0xffffffff,)*3,
                'native header complement')
        require(size == len(parts[part]) and in_regions(destination, size, [destination_regions[i]]),
                'split destination/region overflow: '+part)
        for field, value in [('addr', source), ('start', destination), ('size', size)]:
            require(symbols.get('_'+part+'_load_'+field) == value, 'native header/ELF descriptor: '+part)
        if i:
            require(source == words[(i-1)*6] + words[(i-1)*6+2], 'split source ordering')
    expected_wait = 0x081bfffc if profile['core']=='CR8-0' else 0x081ffffc
    require(words[18] == expected_wait, 'native header core wait area')


def check_sensor_descriptors(descriptors, count):
    require(len(descriptors) == 48 and count in (1, 3), 'sensor descriptor table size/count')
    pins = []
    for i in range(count):
        cs,drdy,devid,dtype = struct.unpack_from('<IIIH',descriptors,i*16)
        require(cs and drdy==0 and devid==0x10000034+(i<<8) and dtype==0x34,
                'sensor descriptor mismatch')
        pins.append(cs)
    require(len(set(pins))==count,'sensor chip-select alias')
    require(not any(descriptors[count*16:]), 'unexpected extra sensor descriptor')


def check_profile(directory, profile, contract, state_hash):
    name = profile['target']
    core = contract['cores'][profile['core']]
    receipt = load_json(directory/'build-receipt.json')
    require(receipt.get('schema_version') == 1 and receipt.get('target') == name and
            receipt.get('source_state_sha256') == state_hash and
            receipt.get('policy_sha256') == digest(POLICY) and receipt.get('build_exit') == 0 and
            receipt.get('target_actions') == [], 'target receipt identity')
    check_inventory(directory, receipt['files'], ('build-receipt.json',))
    for filename in required_files(profile, core):
        require(filename in receipt['files'], 'missing required artifact: '+filename)
    for owner, expected in contract['contract_owners'].items():
        require(digest(directory/'sources'/owner) == expected, 'trusted owner mismatch: '+owner)
    if profile['core'] == 'CR8-1':
        derived = cr81_capacity((directory/'sources'/core['linker']).read_text(),
                               (directory/'sources/platforms/nuttx/CMakeLists.txt').read_text())
        require(derived == profile['image_maxsize'], 'CR8-1 source capacity mismatch')
    config = config_values((directory/'NuttX/nuttx/.config').read_text())
    check_dependencies(directory, contract, config)
    for key,value in profile['required_config'].items():
        require(config.get(key)==value, 'required configuration: '+key)
    require(not any(config.get(k) in ('y','m') for k in profile['forbidden_config']), 'forbidden configuration')
    require(config.get(core['core_option']) == 'y', 'wrong core option')
    for other in contract['cores'].values():
        if other != core:
            require(config.get(other['core_option']) != 'y', 'conflicting core option')
    cache = (directory/'CMakeCache.txt').read_text()
    for value in ('PX4_BOARD_LABEL:STRING='+profile['label'], 'NUTTX_CONFIG:INTERNAL='+profile['nuttx_config']):
        require(value+'\n' in cache, 'configuration identity: '+value)
    board_config = (directory/'px4_boardconfig.h').read_text()
    require('CONFIG_BOARD_ARCHITECTURE "'+core['architecture']+'"' in board_config, 'board architecture mismatch')
    check_fault_hooks(board_config)
    original = Path(receipt['original_build_directory'])
    require(original.is_absolute() and original.name==name and original.parent.name=='build',
            'original build path identity')
    source_prefix = original.parent.parent
    require('-Wl,--script='+str(source_prefix/core['linker']) in (directory/'build.ninja').read_text(),
            'link graph owner mismatch')
    require('Memory Configuration' in (directory/(name+'.map')).read_text(), 'invalid link map')
    builtins = set(re.findall(r'^\{ "([^"]+)"', (directory/'NuttX/px4.bdat').read_text(), re.M))
    require(set(profile['required_builtins']) <= builtins, 'required builtin missing')
    require(not set(profile['forbidden_builtins']) & builtins, 'forbidden profile builtin')
    elf = directory/(name+'.elf')
    view = elf_view(elf.read_bytes())
    attrs = tool(['arm-none-eabi-readelf', '-A', str(elf)])
    require(view['flags'] == 0x05000400, 'ELF EABI/hard-float flags')
    require(('Tag_CPU_arch: v8-M.mainline' in attrs and 'Tag_CPU_arch_profile: Microcontroller' in attrs)
            if profile['core']=='CM33' else
            ('Tag_CPU_arch: v7\n' in attrs and 'Tag_CPU_arch_profile: Realtime' in attrs),
            'ELF CPU architecture/profile mismatch')
    graph = (directory/'build.ninja').read_text()
    require(('-march=armv8-m.main+dsp' in graph and '-mtune=cortex-m33' in graph)
            if profile['core']=='CM33' else '-mcpu=cortex-r8' in graph, 'compiler CPU selection')
    symbols = dict((n, int(a,16)) for a,n in re.findall(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$',
                      tool(['arm-none-eabi-nm', str(elf)]), re.M))
    require(not tool(['arm-none-eabi-nm', '-u', str(elf)]).strip(), 'unresolved ELF globals')
    for symbol in profile['required_symbols']:
        require(symbol in symbols, 'required ELF provider: '+symbol)
    for command in profile['required_builtins']:
        require(command+'_main' in symbols, 'builtin provider missing: '+command)
    require(view['entry'] == (symbols.get('__start',0) | (1 if profile['core']=='CM33' else 0)),
            'ELF entry is not __start')
    require(symbols.get('_vectors', symbols.get('_vector_start')) == core['vector'] or
            symbols.get('_VECTOR_START') == core['vector'], 'ELF vector location')
    for section in view['sections'].values():
        if section['flags'] & 2 and section['size']:
            require(in_regions(section['address'], section['size'], core['regions']), 'ELF section outside core memory')
    for load in view['loads']:
        require(in_regions(load['address'], load['memory'], core['regions']), 'ELF load/reservation outside core memory')
        require(in_regions(load['physical'], load['memory'], core['regions']), 'ELF physical load outside core memory')
    require(any(l['flags'] & 1 and l['address'] <= (view['entry'] & ~1) < l['address']+l['size']
                for l in view['loads']), 'entry has no executable load')
    if profile['core'] != 'CM33':
        require(struct.unpack('<I',virtual_bytes(view,32,4))[0] == view['entry'], 'CR8 reset vector/entry')
        for symbol,value in [('IPC_RAW_SHM_START',0x43800000),('IPC_RAW_SHM_LENGTH',0x40000),
                             ('MHU_SHMEM_START',0x42f01000),('OPENAMP_VRING_START',0x43000000)]:
            require(symbols.get(symbol)==value,'compiled shared memory contract: '+symbol)
    if config.get('CONFIG_SEGGER_RTT') == 'y':
        require('_SEGGER_RTT' in symbols,'selected RTT provider absent')
        if config.get('CONFIG_SEGGER_RTT_SECTION') == '".noncache_buffer"':
            base = 0x080f8000 if profile['core']=='CM33' else 0x081a0000 if profile['core']=='CR8-0' else 0x081e0000
            require(in_regions(symbols['_SEGGER_RTT'],1,[[base,0x4000 if profile['core']=='CM33' else 0x1fffc]]),
                    'selected RTT section placement')
    check_binary(directory, profile, core, view, symbols)
    check_package(directory, profile)
    romfs = (directory/'ROMFS/romfs.img').read_bytes()
    require(virtual_bytes(view, symbols['romfs_img'], len(romfs)) == romfs, 'ROMFS/ELF image mismatch')
    check_romfs(directory, romfs)
    check_archived_sources(directory, profile)
    if profile['label'] in ('drone','dualcr8','demo'):
        descriptors = virtual_bytes(view,symbols['px4_spi_buses'],48)
        check_sensor_descriptors(descriptors, 3 if profile['label']=='drone' else 1)
    focused = load_json(directory/'focused-results.json')
    require(len(focused) == len(profile['focused_tests']), 'focused checks incomplete')
    python = load_json(directory.parents[1]/'source-state.json')['python']['path']
    for index,(row,script) in enumerate(zip(focused,profile['focused_tests'])):
        check_execution(row,Path(script).stem,script,[python,script],directory/('focused-'+str(index)+'.log'))
    return {'target':name, 'status':'BUILD-CHECKED', 'elf_sha256':digest(elf),
            'rtt_address': symbols.get('_SEGGER_RTT'), 'on_target':'NOT-RUN', 'target_actions':[]}


def check_fault_hooks(board_config):
    require(not re.search(r'^#define CONFIG_RZV2H_DUALCR8_FAULT_INJECTION\s+1\b', board_config, re.M),
            'bench fault hooks present in normal artifact')


def check_romfs(directory, data):
    """Walk the standard ROMFS linked directory format without mounting it."""
    require(data[:8] == b'-rom1fs-' and len(data) >= 32, 'invalid ROMFS superblock')
    total = struct.unpack_from('>I', data, 8)[0]
    require(32 <= total <= len(data), 'truncated ROMFS image')
    def cstring(offset):
        end = data.find(b'\0', offset, min(total, offset+4096))
        require(end >= offset, 'unterminated ROMFS name')
        return data[offset:end].decode(), (end+16)&~15
    _, root = cstring(16)
    files, seen, listed = {}, set(), {}
    def walk(offset, prefix, depth):
        require(depth <= 32, 'ROMFS depth limit')
        while offset:
            require(offset % 16 == 0 and offset+16 <= total and offset not in seen,
                    'invalid/cyclic ROMFS entry')
            seen.add(offset)
            require(len(seen) <= 10000, 'ROMFS entry limit')
            nxt, spec, size, _ = struct.unpack_from('>4I', data, offset)
            kind = nxt & 7
            name, start = cstring(offset+16)
            require('/' not in name and name not in ('',), 'invalid ROMFS basename')
            listed[offset] = (name,size)
            if name not in ('.','..'):
                path = prefix/name
                safe_relative(path.as_posix())
                if kind == 1:
                    walk(spec, path, depth+1)
                elif kind == 2:
                    require(start+size <= total and path.as_posix() not in files, 'invalid ROMFS file')
                    files[path.as_posix()] = data[start:start+size]
                elif kind == 3:
                    require(start+size <= total, 'truncated ROMFS symlink')
                else:
                    require(kind == 0, 'unsupported ROMFS node')
            offset = nxt & ~15
    # genromfs stores '.' as the root directory header.
    walk(root, Path(), 0)
    installed = {p.relative_to(directory/'etc').as_posix():p.read_bytes()
                 for p in (directory/'etc').rglob('*') if p.is_file()}
    require(files == installed, 'ROMFS image/installed tree disagreement')
    listing = (directory/'ROMFS/romfs.txt').read_text()
    rows = re.findall(r'^\d+\s+(\S+)\s+\[.*?\].*?, sz\s+(\d+), at 0x([0-9a-fA-F]+)',listing,re.M)
    observed = {int(offset,16):(name,int(size)) for name,size,offset in rows if int(offset,16)}
    require(len(rows)==len(observed)+1 and observed==listed,'ROMFS listing disagreement')


def check_pair(archive, contract, state_hash):
    dual = next((p for p in contract['profiles'] if p['peer']), None)
    require(dual is not None, 'no qualified image pair in policy')
    names = [dual['target'], dual['peer']]
    pair = load_json(archive/'pair-receipt.json')
    require(pair.get('schema_version') == 1 and pair.get('source_state_sha256') == state_hash and
            pair.get('policy_sha256') == digest(POLICY) and pair.get('status') == 'BUILD-CHECKED',
            'pair identity/compatibility failed')
    expected = {name: {'receipt_sha256':digest(archive/'builds'/name/'build-receipt.json'),
                       'elf_sha256':digest(archive/'builds'/name/(name+'.elf'))} for name in names}
    require(pair['members'] == expected, 'pair member binding mismatch')
    types = pair.get('type_check',{})
    path = 'test/rzv2h-jlink-debug-tools-test.py'
    python = load_json(archive/'source-state.json')['python']['path']
    check_execution(types,'jlink-elf-snippets',path,
                    [python,path,'OneShotReadOnlyFilter.test_shipped_snippets_resolve_against_their_elfs'],
                    archive/'pair-types.log')
    abi = []
    for name in names:
        directory = archive/'builds'/name
        for path in contract['abi_sources'][:2]:
            text = (directory/'sources'/path).read_text()
            abi.append(re.sub(r'/\*.*?\*/|//[^\n]*|\s+', '', text, flags=re.S))
    require(len(set(abi)) == 1, 'pair source ABI mismatch')
    private = []
    for name in names:
        directory = archive/'builds'/name
        view = elf_view((directory/(name+'.elf')).read_bytes())
        private.append([(s['address'],s['address']+s['size']) for s in view['sections'].values()
                        if s['flags']&2 and s['size'] and 0x08000000 <= s['address'] < 0x42800000])
        raw = (directory/'sources'/contract['abi_sources'][3]).read_text()
        channels = (directory/'sources'/contract['abi_sources'][4]).read_text()
        require(re.search(r'#define RZV_IPC_RING_ABI_VERSION\s+2u\b',raw) and
                re.search(r'#define RZV_IPC_CR8CR8_SHM_BASE\s+0x43800000u\b',channels) and
                re.search(r'#define RZV_IPC_CR8CR8_SHM_SIZE\s+0x00010000u\b',channels),
                'pair raw transport ABI/layout')
    require(not any(a<d and c<b for a,b in private[0] for c,d in private[1]),
            'pair private memory overlap')
    return pair


def verify(archive, targets=()):
    archive = archive.resolve()
    inventory(archive)  # Reject escaped/special inputs before opening any archive document.
    contract = policy()
    require(load_json(archive/'px4-profiles.json') == contract, 'archived policy differs from trusted local policy')
    sealed = load_json(archive/'inventory.json')
    require(sealed.get('schema_version') == 1, 'unsupported archive inventory')
    check_inventory(archive, sealed['files'], ('inventory.json',))
    state = load_json(archive/'source-state.json')
    require(state.get('schema_version') == 1 and state.get('target_actions') == [] and
            state.get('policy_sha256') == digest(POLICY), 'source identity/target boundary')
    require(identity(state['effective_inputs']) == state.get('effective_input_sha256'), 'effective source digest mismatch')
    repos = state['effective_inputs']['git']
    require(set(contract['required_submodules']) <= set(repos) and '.' in repos and
            set(repos) <= set(contract['repositories']) | {'.'}, 'source repository inventory')
    for name,observed in repos.items():
        require(re.fullmatch('[0-9a-f]{40}',observed.get('head','')), 'source commit identity')
        if name != '.':
            expected_repo = contract['repositories'][name]
            require(observed['origin']==expected_repo['origin'] and
                    (not expected_repo['branch'] or observed['branch'] in (expected_repo['branch'],'HEAD')),
                    'source repository origin/branch mismatch')
    if not any(p['peer'] for p in contract['profiles']):
        require(not (archive/'pair-receipt.json').exists(), 'no qualified image pair in policy')
    selected = select_profiles(contract, targets)
    expected = [p['target'] for p in selected]
    require(state['selected_targets'] == expected, 'archive target selection mismatch')
    require(sorted(p.name for p in (archive/'builds').iterdir()) == sorted(expected), 'archive target membership')
    check_host(archive)
    state_hash = digest(archive/'source-state.json')
    results = [check_profile(archive/'builds'/p['target'], p, contract, state_hash) for p in selected]
    if any(p['peer'] for p in selected):
        check_pair(archive, contract, state_hash)
    return {'schema_version':1, 'status':'BUILD-CHECKED', 'full_matrix':len(selected)==len(contract['profiles']),
            'archive_sha256':identity(sealed), 'results':results, 'on_target':'NOT-RUN', 'target_actions':[]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--target', action='append', default=[])
    args = parser.parse_args()
    try:
        check_output(args.archive, args.output)
        result = verify(args.archive, args.target)
        code = 0
    except (OSError, ValueError, KeyError, TypeError, struct.error, UnicodeError,
            subprocess.SubprocessError, ET.ParseError, zlib.error) as error:
        result = {'status':'FAIL', 'reason':str(error), 'on_target':'NOT-RUN', 'target_actions':[]}
        code = 1
    if args.output:
        try:
            check_output(args.archive, args.output)
            args.output.write_text(json.dumps(result, indent=2)+'\n')
        except (OSError, ValueError) as error:
            print(error, file=sys.stderr)
            return 2
    print(json.dumps(result, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
