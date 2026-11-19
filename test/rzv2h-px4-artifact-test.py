#!/usr/bin/env python3
"""Parser units or full positive admission and semantic mutants of real PX4 archives."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('px4_check',ROOT/'Tools/rzv2h-px4-artifact-check.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
ARCHIVE = None


class ParserUnits(unittest.TestCase):
    def test_normal_artifacts_reject_bench_fault_hooks(self):
        CHECK.check_fault_hooks('/* #undef CONFIG_RZV2H_DUALCR8_FAULT_INJECTION */\n')
        with self.assertRaisesRegex(ValueError, 'bench fault hooks'):
            CHECK.check_fault_hooks('#define CONFIG_RZV2H_DUALCR8_FAULT_INJECTION 1\n')

    def test_single_sensor_profile_rejects_staging_table(self):
        descriptors = b''.join(struct.pack('<IIIHxx',0x93811000+i,0,
                              0x10000034+(i<<8),0x34) for i in range(3))
        single = descriptors[:16] + bytes(32)
        CHECK.check_sensor_descriptors(single,1)
        CHECK.check_sensor_descriptors(descriptors,3)
        with self.assertRaisesRegex(ValueError,'extra sensor'):
            CHECK.check_sensor_descriptors(descriptors,1)
        with self.assertRaisesRegex(ValueError,'descriptor mismatch'):
            CHECK.check_sensor_descriptors(single,3)
        alias = descriptors[:16] + descriptors[:4] + descriptors[20:]
        with self.assertRaisesRegex(ValueError,'chip-select alias'):
            CHECK.check_sensor_descriptors(alias,3)

    def test_contradictory_execution_receipts_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp)/'test.log';log.write_text('Ran 1 test in 0.1s\n\nOK\n')
            good = {'id':'test','path':'test.py','command':['python','test.py'],'log':str(log),
                    'status':'PASS','exit':0,'seconds':0.1,'tests':1,
                    **{k:False for k in ('timed_out','cancelled','skipped','zero_tests','missing_summary')}}
            CHECK.check_execution(good,'test','test.py',['python','test.py'],log)
            for key,value in [('exit',1),('timed_out',True),('cancelled',True),('skipped',True),
                              ('missing_summary',True),('zero_tests',True),('tests',0),('command',['wrong'])]:
                with self.subTest(key=key),self.assertRaises(ValueError):
                    CHECK.check_execution(dict(good,**{key:value}),'test','test.py',['python','test.py'],log)

    def test_aggregate_archive_limits_are_enforced_before_hashing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);(root/'a').write_text('1234');(root/'b').write_text('5678')
            with patch.object(CHECK,'MAX_ARCHIVE',3),self.assertRaisesRegex(ValueError,'aggregate'):
                CHECK.inventory(root)
            with patch.object(CHECK,'MAX_FILES',1),self.assertRaisesRegex(ValueError,'aggregate'):
                CHECK.inventory(root)
    def test_truncated_and_wrong_elf_rejected(self):
        for data in (b'',b'\x7fELF',b'\x7fELF\x02\x01\x01'+bytes(100)):
            with self.assertRaisesRegex(ValueError,'ELF32'): CHECK.elf_view(data)

    def test_ranges_cannot_wrap_or_cross_region(self):
        self.assertTrue(CHECK.in_regions(0x41800000,0x800000,[[0x41800000,0x800000]]))
        self.assertFalse(CHECK.in_regions(0x41800000,0x800001,[[0x41800000,0x800000]]))
        with self.assertRaisesRegex(ValueError,'overflow'): CHECK.bounded(0xffffffff,2)

    def test_component_overflow_can_fit_aggregate(self):
        size = 0x20001
        self.assertTrue(CHECK.size_allowed(size+128,8650368))
        self.assertFalse(CHECK.in_regions(0x081c0000,size,[[0x081c0000,0x20000]]))

    def test_bounded_decompression_and_trailing_streams(self):
        encoded = lambda b:base64.b64encode(zlib.compress(b)).decode()
        self.assertEqual(CHECK.decompress(encoded(b'valid'),5),b'valid')
        with self.assertRaisesRegex(ValueError,'decompression'): CHECK.decompress(encoded(b'x'*100000),100)
        with self.assertRaises(ValueError): CHECK.decompress(encoded(b'valid')[:-4],100)

    def test_path_traversal_and_duplicate_json_keys(self):
        for path in ('/absolute','../escape','a/../b','a//b','a\\b'):
            with self.assertRaises(ValueError): CHECK.safe_relative(path)
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'input.json'; p.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError,'duplicate'): CHECK.load_json(p)

    def test_archive_inventory_rejects_symlinks_and_unrecorded_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'file').write_text('input')
            expected = CHECK.inventory(root)
            (root/'extra').touch()
            with self.assertRaisesRegex(ValueError,'inventory'): CHECK.check_inventory(root,expected)
            (root/'extra').unlink(); (root/'alias').symlink_to('file')
            with self.assertRaisesRegex(ValueError,'symlink'): CHECK.inventory(root)

    def test_contained_symlink_and_hardlink_outputs_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); archive = root/'archive'; archive.mkdir()
            (archive/'file').write_text('input'); (root/'alias').symlink_to(archive,target_is_directory=True)
            (root/'hardlink').hardlink_to(archive/'file')
            for output in (archive/'new.json',root/'alias/new.json',root/'hardlink'):
                with self.assertRaisesRegex(ValueError,'output'): CHECK.check_output(archive,output)


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')


def reseal(archive):
    """Rehash semantics mutants so a stale hash cannot be their rejection reason."""
    contract = CHECK.policy()
    for directory in (archive/'builds').iterdir():
        receipt = CHECK.load_json(directory/'build-receipt.json')
        receipt['files'] = CHECK.inventory(directory,('build-receipt.json',))
        write_json(directory/'build-receipt.json',receipt)
    pair_path = archive/'pair-receipt.json'
    if pair_path.exists():
        pair = CHECK.load_json(pair_path)
        for name in pair['members']:
            d = archive/'builds'/name
            if d.exists():
                pair['members'][name] = {'receipt_sha256':CHECK.digest(d/'build-receipt.json'),
                                        'elf_sha256':CHECK.digest(d/(name+'.elf'))}
        write_json(pair_path,pair)
    write_json(archive/'inventory.json',{'schema_version':1,'files':CHECK.inventory(archive,('inventory.json',))})


class RealArchives(unittest.TestCase):
    def test_complete_positive_and_relocated_read_only_archive(self):
        before = CHECK.inventory(ARCHIVE)
        result = CHECK.verify(ARCHIVE)
        self.assertTrue(result['full_matrix']); self.assertEqual(len(result['results']),9)
        self.assertEqual(CHECK.inventory(ARCHIVE),before)
        with tempfile.TemporaryDirectory(prefix='rzv2h-px4-relocated-') as temp:
            copy = Path(temp)/'archive'; shutil.copytree(ARCHIVE,copy)
            directories = [copy]+[p for p in copy.rglob('*') if p.is_dir()]
            try:
                for path in copy.rglob('*'):
                    if path.is_file():path.chmod(0o444)
                for path in directories:path.chmod(0o555)
                self.assertEqual(CHECK.verify(copy)['archive_sha256'],result['archive_sha256'])
                self.assertEqual(CHECK.inventory(copy),before)
            finally:
                for path in directories:path.chmod(0o755)

    def mutant(self,change,reason):
        with tempfile.TemporaryDirectory(prefix='rzv2h-px4-mutant-') as temp:
            copy = Path(temp)/'archive'; shutil.copytree(ARCHIVE,copy)
            change(copy); reseal(copy)
            with self.assertRaisesRegex((ValueError,FileNotFoundError),reason): CHECK.verify(copy)

    def test_missing_target_and_peer_fail(self):
        name = 'renesas_rdk-rzv2h-io-cr8_1_default'
        self.mutant(lambda a:shutil.rmtree(a/'builds'/name),'membership')

    def test_rehashed_config_and_package_identity_fail(self):
        name = 'renesas_rdk-rzv2h-io-cr8_1_default'
        def config(a):
            p = a/'builds'/name/'NuttX/nuttx/.config'
            p.write_text(p.read_text().replace('CONFIG_RZV2H_BUILD_CR8_1=y','CONFIG_RZV2H_BUILD_CR8_0=y'))
        self.mutant(config,'core')
        def package(a):
            p = a/'builds'/name/(name+'.px4'); obj = CHECK.load_json(p)
            obj['image_maxsize']=131072; write_json(p,obj)
        self.mutant(package,'identity/maximum')

    def test_rehashed_policy_owner_is_not_authority(self):
        def change(a):
            p = a/'px4-profiles.json'; obj = CHECK.load_json(p)
            obj['profiles'][0]['image_maxsize']*=2; write_json(p,obj)
        self.mutant(change,'trusted local policy')
        def linker(a):
            name = 'renesas_rdk-rzv2h_default'; contract = CHECK.policy()
            p = a/'builds'/name/'sources'/contract['cores']['CR8-0']['linker']
            p.write_text(p.read_text().replace('0x00800000','0x01000000'))
        self.mutant(linker,'trusted owner')

    def test_coherently_rewritten_policy_and_package_cannot_authorize_limit(self):
        def change(a):
            manifest = CHECK.load_json(a/'px4-profiles.json')
            prototype_name = manifest['profiles'][0]['prototype']
            for profile in manifest['profiles']:
                if profile['core']=='CR8-0':profile['image_maxsize']*=2
            for d in (a/'builds').iterdir():
                proto = d/'sources'/prototype_name; obj=CHECK.load_json(proto)
                obj['image_maxsize']*=2;write_json(proto,obj)
                manifest['contract_owners'][prototype_name]=CHECK.digest(proto)
                profile=next(p for p in manifest['profiles'] if p['target']==d.name)
                if profile['core']=='CR8-0':
                    package=d/(d.name+'.px4');obj=CHECK.load_json(package)
                    obj['image_maxsize']=profile['image_maxsize'];write_json(package,obj)
            write_json(a/'px4-profiles.json',manifest);policy_hash=CHECK.digest(a/'px4-profiles.json')
            state=CHECK.load_json(a/'source-state.json');state['policy_sha256']=policy_hash
            for inputs in ('original_inputs','effective_inputs'):
                state[inputs]['files'][prototype_name]['sha256']=manifest['contract_owners'][prototype_name]
                state[inputs]['files']['Tools/rzv2h-px4-profiles.json']['sha256']=policy_hash
            state['effective_input_sha256']=CHECK.identity(state['effective_inputs'])
            write_json(a/'source-state.json',state);state_hash=CHECK.digest(a/'source-state.json')
            for d in (a/'builds').iterdir():
                r=CHECK.load_json(d/'build-receipt.json');r.update(policy_sha256=policy_hash,source_state_sha256=state_hash)
                write_json(d/'build-receipt.json',r)
            if (a/'pair-receipt.json').exists():
                pair=CHECK.load_json(a/'pair-receipt.json');pair.update(policy_sha256=policy_hash,source_state_sha256=state_hash)
                write_json(a/'pair-receipt.json',pair)
        self.mutant(change,'trusted local policy')

    def test_rehashed_elf_entry_and_split_corruption_fail(self):
        name = 'renesas_rdk-rzv2h_default'
        def entry(a):
            p = a/'builds'/name/(name+'.elf'); data = bytearray(p.read_bytes())
            struct.pack_into('<I',data,24,0x41800000); p.write_bytes(data)
        self.mutant(entry,'entry')
        def split(a):
            p = a/'builds'/name/(name+'_sdram.bin'); data = bytearray(p.read_bytes())
            data[0]^=1; p.write_bytes(data)
        self.mutant(split,'ELF/split')

    def test_rehashed_romfs_and_missing_package_fail(self):
        name = 'renesas_rdk-rzv2h_default'
        def romfs(a):
            p = a/'builds'/name/'etc/init.d/rcS'; p.write_text(p.read_text()+'\ncommander start\n')
        self.mutant(romfs,'ROMFS')
        self.mutant(lambda a:(a/'builds'/name/(name+'.px4')).unlink(),'required artifact')

    def test_missing_startup_and_metadata_are_required(self):
        name = 'renesas_rdk-rzv2h_default'
        for filename in ('parameters.xml',name+'.map','etc/init.d/rc.board_sensors'):
            with self.subTest(filename=filename):
                self.mutant(lambda a:(a/'builds'/name/filename).unlink(),
                            'required artifact|ROMFS|startup')

    def test_rehashed_unqualified_pair_receipt_fails(self):
        def change(a):
            write_json(a/'pair-receipt.json', {'members': {}})
        self.mutant(change,'no qualified image pair')

    def test_rehashed_contradictory_focused_evidence_fails(self):
        name = 'renesas_rdk-rzv2h_default'
        for field,value in [('exit',1),('timed_out',True),('cancelled',True),('skipped',True)]:
            def change(a):
                p = a/'builds'/name/'focused-results.json'; rows = CHECK.load_json(p)
                rows[0][field]=value;write_json(p,rows)
            with self.subTest(field=field): self.mutant(change,'execution failed')

    def test_rehashed_profile_and_hard_float_identity_fail(self):
        name = 'renesas_rdk-rzv2h_default'
        def label(a):
            p = a/'builds'/name/'CMakeCache.txt'
            p.write_text(p.read_text().replace('PX4_BOARD_LABEL:STRING=default','PX4_BOARD_LABEL:STRING=simple'))
        self.mutant(label,'configuration identity')
        def flags(a):
            p = a/'builds'/name/(name+'.elf'); data = bytearray(p.read_bytes())
            struct.pack_into('<I',data,36,0x05000200); p.write_bytes(data)
        self.mutant(flags,'hard-float')

    def test_rehashed_reset_vector_and_component_overflow_fail(self):
        name='renesas_rdk-rzv2h_default'
        def vector(a):
            p=a/'builds'/name/(name+'.elf');data=bytearray(p.read_bytes())
            offset=struct.unpack_from('<I',data,28)[0];count=struct.unpack_from('<H',data,44)[0]
            for i in range(count):
                kind,file_offset,va,pa,size=struct.unpack_from('<5I',data,offset+i*32)
                if kind==1 and va==0 and size>=36:
                    struct.pack_into('<I',data,file_offset+32,0x41800000);break
            else:raise AssertionError('real ELF vector load missing')
            p.write_bytes(data)
        self.mutant(vector,'reset vector')
        def overflow(a):
            n='renesas_rdk-rzv2h-io-cr8_1_default';p=a/'builds'/n/(n+'.elf')
            data=bytearray(p.read_bytes());offset=struct.unpack_from('<I',data,32)[0]
            count,strings_index=struct.unpack_from('<HH',data,48)
            start,size=struct.unpack_from('<II',data,offset+strings_index*40+16)
            strings=data[start:start+size]
            for i in range(count):
                header=offset+i*40;key=struct.unpack_from('<I',data,header)[0]
                if strings[key:].split(b'\0',1)[0]==b'.sdram_data_section':
                    payload_size=0x20001
                    self.assertLess(payload_size+128,8650368)
                    struct.pack_into('<III',data,header+12,0x081c0000,len(data),payload_size)
                    data.extend(bytes(payload_size));break
            else:raise AssertionError('real ELF data section missing')
            p.write_bytes(data)
        self.mutant(overflow,'section outside core memory')

    def test_rehashed_source_and_dependency_provenance_fail(self):
        name = 'renesas_rdk-rzv2h_default'
        def dependency(a):
            p = a/'builds'/name/'dependency-inputs.json'; obj = CHECK.load_json(p)
            obj['RTT.zip']='0'*64; write_json(p,obj)
        self.mutant(dependency,'dependency provenance')
        def source(a):
            p = a/'source-state.json'; state = CHECK.load_json(p)
            state['effective_inputs']['git']['platforms/nuttx/NuttX/nuttx']['origin']='https://wrong.invalid/fork.git'
            state['effective_input_sha256']=CHECK.identity(state['effective_inputs']); write_json(p,state)
            for d in (a/'builds').iterdir():
                r = CHECK.load_json(d/'build-receipt.json');r['source_state_sha256']=CHECK.digest(p)
                write_json(d/'build-receipt.json',r)
        self.mutant(source,'origin/branch')


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-only',action='store_true')
    parser.add_argument('--archive',type=Path)
    args,remaining = parser.parse_known_args()
    if not args.unit_only and not args.archive: parser.error('--archive is required, or select --unit-only')
    ARCHIVE = args.archive.resolve() if args.archive else None
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ParserUnits))
    if not args.unit_only: suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(RealArchives))
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
