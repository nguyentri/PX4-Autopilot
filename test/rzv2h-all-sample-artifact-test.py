#!/usr/bin/env python3
"""Real all-native ELF admission and coherently rehashed negative controls."""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('native_artifacts',ROOT/'platforms/nuttx/Debug/rzv2h-sample-artifact-check.py')
ART = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ART)
BUILDS = SOURCE = POLICY = None


class NativeArchive(unittest.TestCase):
    def copied(self, name='canfd-rtt'):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        shutil.copy2(SOURCE,root/'source-state.json')
        shutil.copy2(SOURCE.parent/'sample-profiles.json',root/'sample-profiles.json')
        for contract_name in ('legacy-sample-profiles.json','driver-coverage.json'):
            if (SOURCE.parent/contract_name).is_file():
                shutil.copy2(SOURCE.parent/contract_name,root/contract_name)
        target = root/name
        shutil.copytree(BUILDS/name,target)
        profile = copy.deepcopy(next(x for x in POLICY['profiles'] if x['profile']==name))
        return profile,target,root/'source-state.json'

    def refresh(self, directory, source, policy=None):
        path = directory/'build-receipt.json'
        receipt = json.loads(path.read_text())
        for name in receipt['file_sha256']:
            receipt['file_sha256'][name]=ART.INVENTORY.digest(directory/name)
        if policy is not None:
            (source.parent/'sample-profiles.json').write_text(json.dumps(policy))
            state=json.loads(source.read_text())
            state['manifest_sha256']=ART.INVENTORY.digest(source.parent/'sample-profiles.json')
            source.write_text(json.dumps(state))
            receipt['manifest_sha256']=state['manifest_sha256']
            if 'contract_inputs' in state:
                for record in state['contract_inputs']:
                    record['sha256']=ART.INVENTORY.digest(source.parent/record['path'])
                receipt['contract_inputs']=state['contract_inputs']
                source.write_text(json.dumps(state))
        receipt['source_state_sha256']=ART.INVENTORY.digest(source)
        path.write_text(json.dumps(receipt))

    def verify(self, inputs, policy=None):
        return ART.verify_native(*inputs,POLICY if policy is None else policy)

    def test_every_native_image_and_legacy_extension_is_admitted(self):
        contracts=ART.INVENTORY.archived_contracts(SOURCE)
        ART.INVENTORY.validate(POLICY,catalog=contracts.get('driver_coverage'),live=False)
        self.assertTrue({x['profile'] for x in POLICY['profiles']})
        for row in POLICY['profiles']:
            with self.subTest(profile=row['profile']):
                result=ART.verify_native(row,BUILDS/row['profile'],SOURCE,POLICY)
                self.assertEqual(result['status'],'BUILD-CHECKED')
                self.assertFalse(result['artifact_authorized'])
                self.assertEqual(result['on_target'],'NOT-RUN')

    def test_declared_core_console_and_entry_must_match_resolved_config(self):
        for key,value in (('core','cr8_1'),('console','sci5'),('entrypoint','hwtest_main')):
            inputs=self.copied()
            config=inputs[1]/'resolved.config'
            if key=='core':
                config.write_text(config.read_text().replace('CONFIG_RZV2H_BUILD_CR8_0=y','CONFIG_RZV2H_BUILD_CR8_1=y'))
            elif key=='console':
                config.write_text(config.read_text().replace('CONFIG_SYSLOG_RTT_CONSOLE_INPUT=y','# CONFIG_SYSLOG_RTT_CONSOLE_INPUT is not set')+'\nCONFIG_SCI5_SERIAL_CONSOLE=y\n')
            else:
                config.write_text(config.read_text().replace('CONFIG_INIT_ENTRYPOINT="nsh_main"','CONFIG_INIT_ENTRYPOINT="hwtest_main"'))
            self.refresh(inputs[1],inputs[2])
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.verify(inputs)

    def test_rehashed_cross_core_elf_cannot_pass(self):
        inputs=self.copied('nsh-cr8_1')
        shutil.copy2(BUILDS/'nsh-cm33/nuttx.elf',inputs[1]/'nuttx.elf')
        self.refresh(inputs[1],inputs[2])
        with self.assertRaises(ValueError):self.verify(inputs)

    def test_rehashed_elf_entry_cannot_point_away_from_startup(self):
        inputs=self.copied()
        path=inputs[1]/'nuttx.elf'
        data=bytearray(path.read_bytes())
        struct.pack_into('<I',data,24,0x40800004)
        path.write_bytes(data)
        self.refresh(inputs[1],inputs[2])
        with self.assertRaisesRegex(ValueError,'entry'):self.verify(inputs)

    def test_linker_and_configuration_require_original_source_provenance(self):
        for name in ('linker-script.ld','resolved.config'):
            inputs=self.copied()
            if name=='linker-script.ld':
                (inputs[1]/name).write_text('unrelated linker input')
                self.refresh(inputs[1],inputs[2])
            else:
                receipt=inputs[1]/'build-receipt.json'
                data=json.loads(receipt.read_text());data['defconfig_sha256']='0'*64
                receipt.write_text(json.dumps(data))
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'provenance|configuration digest'):
                self.verify(inputs)

    def test_manifest_and_source_receipts_are_bound(self):
        inputs=self.copied()
        source=json.loads(inputs[2].read_text());source['manifest_sha256']='0'*64
        inputs[2].write_text(json.dumps(source));self.refresh(inputs[1],inputs[2])
        with self.assertRaisesRegex(ValueError,'manifest provenance'):self.verify(inputs)

    def test_rehashed_builtin_pointer_must_still_call_the_expected_main(self):
        inputs=self.copied()
        elf=inputs[1]/'nuttx.elf'
        symbols=subprocess.check_output(['arm-none-eabi-nm','-S',str(elf)],text=True)
        match=ART.re.search(r'(?m)^(\w+)\s+(\w+)\s+\w\s+g_builtins$',symbols)
        address,size=(int(x,16) for x in match.groups())
        data=bytearray(elf.read_bytes())
        table=ART.elf32_bytes(data,address,size)
        selected=None
        for offset in range(0,size,16):
            name,_,_,entry=struct.unpack_from('<4I',table,offset)
            if name and ART.elf32_bytes(data,name,4)==b'can\0':
                selected=address+offset+12
        self.assertIsNotNone(selected)
        phoff=struct.unpack_from('<I',data,28)[0]
        entsize,count=struct.unpack_from('<HH',data,42)
        for index in range(count):
            kind,start,virtual,_,length,_,_,_=struct.unpack_from('<8I',data,phoff+index*entsize)
            if kind==1 and virtual<=selected<virtual+length:
                struct.pack_into('<I',data,start+selected-virtual,0x40800000)
                break
        else:self.fail('builtin pointer has no segment')
        elf.write_bytes(data);self.refresh(inputs[1],inputs[2])
        with self.assertRaisesRegex(ValueError,'builtin does not point'):self.verify(inputs)

    def test_missing_or_modified_archive_inputs_are_rejected(self):
        for name in ('nuttx.elf','resolved.config','nuttx.map','System.map','linker-script.ld'):
            inputs=self.copied()
            with (inputs[1]/name).open('ab') as stream:stream.write(b'changed')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'digest mismatch'):
                self.verify(inputs)

    def test_instance_selector_mutants_fail_even_with_updated_artifact_hashes(self):
        instances=[x for x in POLICY['profiles'] if 'instance_id' in x]
        for row in instances:
            for suffix,value in (('CHANNEL','99'),('FAMILY','99'),('OUTPUT','2')):
                inputs=self.copied(row['profile'])
                path=inputs[1]/'resolved.config'
                key='CONFIG_TESTING_RZV_HWTEST_INSTANCE_'+suffix
                text=ART.re.sub(r'(?m)^'+key+r'=.*$',key+'='+value,path.read_text())
                path.write_text(text)
                self.refresh(inputs[1],inputs[2])
                with self.subTest(profile=row['profile'],suffix=suffix),self.assertRaisesRegex(ValueError,'selector mismatch'):
                    self.verify(inputs)

    def test_archived_contract_omission_and_rehashed_semantic_mutation_fail(self):
        if not json.loads(SOURCE.read_text()).get('contract_inputs'):
            with self.assertRaisesRegex(ValueError,'inputs required'):
                ART.INVENTORY.archived_contracts(SOURCE,required=True)
            return
        for name in ('legacy-sample-profiles.json','driver-coverage.json'):
            inputs=self.copied()
            source=inputs[2]
            path=source.parent/name
            path.unlink()
            with self.subTest(name=name),self.assertRaises((OSError,ValueError)):
                self.verify(inputs)
        inputs=self.copied()
        source=inputs[2]
        path=source.parent/'driver-coverage.json'
        catalog=json.loads(path.read_text())
        catalog['instances'][0]['required_config']={}
        path.write_text(json.dumps(catalog))
        state=json.loads(source.read_text())
        for record in state['contract_inputs']:
            record['sha256']=ART.INVENTORY.digest(source.parent/record['path'])
        source.write_text(json.dumps(state))
        receipt_path=inputs[1]/'build-receipt.json'
        receipt=json.loads(receipt_path.read_text())
        receipt['contract_inputs']=state['contract_inputs']
        receipt_path.write_text(json.dumps(receipt))
        self.refresh(inputs[1],source)
        with self.assertRaisesRegex(ValueError,'selector/link/source'):
            self.verify(inputs)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--builds',type=Path,required=True)
    parser.add_argument('--source-state',type=Path,required=True)
    args,remaining=parser.parse_known_args()
    BUILDS=args.builds.resolve();SOURCE=args.source_state.resolve()
    POLICY=json.loads((SOURCE.parent/'sample-profiles.json').read_text())
    unittest.main(argv=[__file__,*remaining])
