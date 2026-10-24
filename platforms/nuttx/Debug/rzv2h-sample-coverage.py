#!/usr/bin/env python3
"""Re-admit native archives and replay named lab receipts into coverage.

Offline only. A complete partial report is distinct from a passing campaign.
Warm receipts never satisfy the independent cold-state qualification gate.
"""

import argparse
import datetime
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ART=load_module('coverage_artifacts',HERE/'rzv2h-sample-artifact-check.py')
RUNNER=load_module('coverage_evidence',HERE/'rzv2h-sample-runner.py')


def hardware_coverage(catalog, profiles, rows, bound=True):
    """Hardware resources and mode/output cells have independent denominators."""
    ART.INVENTORY.validate_coverage(catalog, profiles)
    mapped = {ART.INVENTORY.instance_key(x['core'], x['instance']): x
              for x in catalog['instances']}
    declared = {x['profile']: x for x in profiles}
    evidence = {x['profile']: x for x in rows}
    batch_mapped = {}
    if bound:
        for record in catalog.get('native_profile_coverage', []):
            profile = declared.get(record['profile'])
            if profile is None:
                continue
            batches = ART.INVENTORY.dmac_batches(profile)
            row = evidence.get(profile['profile'], {})
            if row.get('runtime_state') == 'PASS' and row.get('target_state', {}).get('dmac_channels') != \
                    [channel for batch in batches for channel in batch]:
                raise ValueError('passing DMAC coverage lacks exact checked channel set')
            for batch in batches:
                for global_channel in batch:
                    key = ART.INVENTORY.instance_key(record['core'], dict(family='dmac',
                        unit=global_channel//16, channel=global_channel%16, mode='memcpy', output=None))
                    batch_mapped.setdefault(key, []).append((profile,
                        evidence.get(profile['profile'], {}), record))
    domains = []
    keys = ART.INVENTORY.domain_keys(catalog)
    for domain in catalog['domains']:
        cells = []
        for key, owner in keys.items():
            if owner['family'] != domain['family']:
                continue
            core, family, unit, channel, mode, output = key
            selected = mapped.get(key, {})
            profile = declared.get(selected.get('profile'), {}) if bound else {}
            row = evidence.get(profile.get('profile'), {})
            candidates = batch_mapped.get(key, [])
            if candidates:
                profile, row, selected = max(candidates, key=lambda x: (
                    x[1].get('build_state') == 'BUILD-CHECKED' and x[1].get('runtime_state') == 'PASS',
                    x[1].get('build_state') == 'BUILD-CHECKED'))
            reservations = [x for x in domain.get('reservations', [])
                            if x['unit'] == unit and x['channel'] == channel]
            reserved = any(x.get('kind') != 'conditional' for x in reservations)
            built = row.get('build_state') == 'BUILD-CHECKED'
            passed = built and row.get('runtime_state') == 'PASS'
            gates = [domain['ownership_gate'], *selected.get('gates', [])]
            if family in domain.get('mode_gates', {}):
                gates.append(domain['mode_gates'][family])
            gates.extend(x['reason'] for x in reservations)
            if not profile:
                gates.append('No archived fixed-instance profile/contract is configured for this cell.')
            elif not passed:
                gates.append(row.get('blocker') or 'No admitted target receipt for this instance.')
            records = row.get('evidence', [])
            if candidates:
                records = [dict(item, profile=p['profile']) for p,r,_ in candidates for item in r.get('evidence', [])]
            internal_spi = family == 'spi' and 'instance.loopback' in \
                profile.get('hwtest_contract', {}).get('required_case_ids', [])
            cells.append(dict(core=core, instance=dict(family=family, unit=unit, channel=channel,
                mode=mode, output=output), instance_id=selected.get('instance_id'),
                profile=profile.get('profile'), state='RESERVED' if reserved else 'PASS' if passed else 'BLOCKED',
                implemented=bool(bound and selected.get('source_evidence') and
                                 (selected.get('required_symbols') or candidates)),
                configured=bool(profile), built=built,
                diagnostic=passed and ('diagnostic' in row.get('evidence_class', '') or
                                       'register' in row.get('evidence_class', '')),
                function=passed and (internal_spi or row.get('evidence_class') in
                    ('function', 'internal-function', 'connected-function', 'memory-function')),
                electrical=False, gates=list(dict.fromkeys(gates)), evidence=records))
        domains.append(dict(family=domain['family'],
            total=sum(len(x) for x in domain['channels_by_unit']), instance_cells=len(cells),
            **{name:sum(bool(x[name]) for x in cells) for name in
               ('implemented','configured','built','diagnostic','function','electrical')},
            reserved=sum(x['state'] == 'RESERVED' for x in cells),
            blocked=sum(x['state'] == 'BLOCKED' for x in cells),
            source_evidence=domain['source_evidence'], cells=cells))
    return dict(status='INCOMPLETE', contract_binding='archived' if bound else 'historical-unbound',
                qualification='No electrical, cold-state or all-channel claim follows from profile counts.',
                domains=domains, non_executable_metadata={key:catalog.get(key, []) for key in
                    ('core_private_timers','shared_timer_services','non_channel_services','header_only_ip')})


def validate(report,profiles,catalog=None):
    if report.get('status') not in ('PASS','FAIL','INCOMPLETE'):
        raise ValueError('invalid campaign state')
    rows=report['profiles']
    names=[x['profile'] for x in rows]
    expected={x['profile'] for x in profiles}
    if len(names)!=len(profiles) or len(set(names))!=len(profiles) or set(names)!=expected:
        raise ValueError('coverage must contain exactly the validated inventory profiles')
    contracts=report.get('contract_inputs', [])
    if any('instance_id' in x for x in profiles) and not contracts:
        raise ValueError('instance coverage requires archived contract bindings')
    for row in rows:
        profile=next(x for x in profiles if x['profile']==row['profile'])
        if row.get('core')!=profile['core'] or row.get('evidence_class')!=profile['evidence_class']:
            raise ValueError('coverage core/evidence class differs from reviewed policy')
        for key in ('instance_id', 'instance'):
            if row.get(key) != profile.get(key):
                raise ValueError('coverage instance differs from reviewed policy: ' + key)
        if contracts and row['build_state']=='BUILD-CHECKED' and row.get('contract_inputs')!=contracts:
            raise ValueError('coverage archived contract binding mismatch')
        if row['runtime_state'] not in ('PASS','FAIL','BLOCKED','NOT-RUN'):
            raise ValueError('invalid runtime state')
        if row['runtime_state']=='PASS' and (row['build_state']!='BUILD-CHECKED' or
                not row.get('evidence') or not row.get('elf_sha256') or
                not row.get('warm_qualified') or row.get('reset_class')!='warm-load'):
            raise ValueError('passing row lacks admitted bounded evidence')
        if row['runtime_state'] in ('BLOCKED','NOT-RUN') and not row.get('blocker'):
            raise ValueError('unexecuted row lacks concrete blocker')
        if row.get('cold_qualified'):
            raise ValueError('this executor does not establish cold qualification')
    green=all(x['build_state']=='BUILD-CHECKED' and x['runtime_state']=='PASS' and
              not x['release_blockers'] for x in rows)
    if report.get('status')=='PASS' and not green:
        raise ValueError('global PASS would hide incomplete or blocked qualification')
    if 'hardware_coverage' in report:
        if catalog is None:
            raise ValueError('hardware coverage requires its archived catalogue')
        expected_hardware = hardware_coverage(catalog, profiles, rows,
            bound=report['hardware_coverage'].get('contract_binding') == 'archived')
        if report['hardware_coverage'] != expected_hardware:
            raise ValueError('hardware coverage has missing, duplicate or mismatched cells')
        if report['status'] == 'PASS' and expected_hardware['status'] != 'PASS':
            raise ValueError('global PASS would hide hardware qualification gates')
    elif any('instance_id' in x for x in profiles):
        raise ValueError('instance campaign omitted hardware domain coverage')
    return report


def relative(path):
    try:return str(path.resolve().relative_to(ROOT))
    except ValueError:return str(path.resolve())


def mark_stopped(rows,reason):
    if not reason:
        return
    for row in rows:
        if row['runtime_state'] in ('NOT-RUN','BLOCKED'):
            row['runtime_state']='BLOCKED'
            row['blocker']='Campaign stopped after '+reason+'. '+str(row.get('blocker') or '')
        if row['runtime_state']!='PASS':
            row['release_blockers'].append('Fresh recovery approval/state evidence is required before further probe access.')


def aggregate(archive,runs):
    manifest=json.loads((archive/'sample-profiles.json').read_text())
    contracts=ART.INVENTORY.archived_contracts(archive/'source-state.json')
    catalog=contracts.get('driver_coverage') or json.loads(ART.INVENTORY.COVERAGE.read_text())
    profiles=ART.INVENTORY.validate(manifest,catalog=catalog,live=False)
    receipts={}
    invocation_ids=set()
    stopped=None
    for path in runs:
        receipt=json.loads((path/'run-receipt.json').read_text())
        name=receipt['profile']
        if name not in {x['profile'] for x in profiles}:
            raise ValueError('unknown lab profile: '+name)
        identifier=(name,receipt.get('run_id'))
        if identifier in invocation_ids:
            raise ValueError('duplicate lab invocation receipt')
        invocation_ids.add(identifier)
        receipts.setdefault(name,[]).append((path,receipt))
        result_path=path/'result.json'
        if result_path.is_file():
            result=json.loads(result_path.read_text())
            if result.get('recovery_required'):
                stopped=name+': '+result.get('reason','target recovery required')
            elif result.get('status')=='PASS':
                stopped=None
    rows=[]
    for profile in profiles:
        name=profile['profile']
        row=dict(profile=name,core=profile['core'],evidence_class=profile['evidence_class'],
                 build_state='NOT-RUN',runtime_state='NOT-RUN',reset_class=None,
                 warm_qualified=False,cold_qualified=False,evidence=[],
                 owning_phase=5 if name.startswith('ipcc') or profile['core']!='cr8_0' else 4,
                 blocker=profile.get('reason') or 'No accepted local lab receipt; fixture prerequisites: '+
                    (', '.join(profile['requirements']) or 'bounded local batch pending'),
                 release_blockers=['Independent approved cold-state qualification is missing.'])
        row['last_evidence_date']=None
        row['last_evidence_sha256']=None
        row.update({key:profile[key] for key in ('instance_id', 'instance') if key in profile})
        try:
            admission=ART.verify_native(profile,archive/'builds'/name,archive/'source-state.json',manifest)
            row.update(build_state='BUILD-CHECKED',elf_sha256=admission['elf_sha256'],
                       source_state_sha256=admission['source_state_sha256'],
                       contract_inputs=admission.get('contract_inputs', []))
            row['last_evidence_sha256']=admission['elf_sha256']
            row['last_evidence_date']=json.loads((archive/'source-state.json').read_text())['created']
        except (OSError,ValueError,KeyError,TypeError) as error:
            row.update(build_state='ADMISSION-FAIL',runtime_state='BLOCKED',blocker=str(error))
            rows.append(row);continue
        if profile['mode']=='blocked' or profile['core']=='cm33':
            row['runtime_state']='BLOCKED'
        elif profile['requirements']:
            row['runtime_state']='BLOCKED'
        for path,receipt in receipts.get(name,[]):
            row['last_evidence_sha256']=ART.INVENTORY.digest(path/'run-receipt.json')
            row['last_evidence_date']=datetime.datetime.fromtimestamp(
                (path/'run-receipt.json').stat().st_mtime,datetime.timezone.utc).isoformat()
            result_path=path/'result.json'
            result=json.loads(result_path.read_text()) if result_path.is_file() else {}
            if result.get('recovery_required'):
                row.update(runtime_state='BLOCKED',warm_qualified=False,blocker=result['reason'])
                row['evidence'].append({'path':relative(path),'receipt_sha256':ART.INVENTORY.digest(path/'run-receipt.json'),
                                        'state':'BLOCKED','reason':result['reason']})
                continue
            try:
                accepted=RUNNER.check_native(profile,(path/'transcript.txt').read_text(),
                                            (path/'health.txt').read_text(),receipt,admission)
                row.update(runtime_state='PASS',warm_qualified=True,reset_class=accepted['reset_class'],
                           target_state=accepted.get('state', {}),blocker=None)
                row['evidence'].append({'path':relative(path),'receipt_sha256':ART.INVENTORY.digest(path/'run-receipt.json'),
                                        'run_id':receipt['run_id'],'state':'PASS'})
            except (OSError,ValueError,KeyError,TypeError) as error:
                # A later passing rerun is preserved with the earlier failure visible.
                row.update(runtime_state='FAIL',warm_qualified=False,blocker=str(error))
                row['evidence'].append({'path':relative(path),'receipt_sha256':ART.INVENTORY.digest(path/'run-receipt.json'),
                                        'state':'FAIL','reason':str(error)})
        if row['runtime_state']!='PASS':
            row['release_blockers'].append(row['blocker'])
        if name=='nsh-leds':
            row['release_blockers'].append('Shell observation does not exercise the indefinite LED daemon; bounded LED lifecycle pending.')
        if name=='gy912':
            row['release_blockers'].append('Original verbose fault remains unresolved; native 1/20/repeated-20 reproduction and repair gate is open.')
        if name=='bmm150':
            row['release_blockers'].append('Bounded bad-address and recovery scenario pending separate fixture admission.')
        if name in ('canfd-ext','canfd-dual'):
            row['release_blockers'].append('Connected HW0/HW3 CAN-FD/BRS, completion IRQs and no-reboot recovery pending; FDCFG/TDC parity gap remains open.')
        rows.append(row)
    mark_stopped(rows,stopped)
    status='FAIL' if any(x['build_state']!='BUILD-CHECKED' or x['runtime_state']=='FAIL' for x in rows) else 'INCOMPLETE'
    return validate(dict(schema_version=1,created=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         status=status,target_actions=[],hardware_stop=stopped,
                         archive=relative(archive),profiles=rows,
                         contract_inputs=json.loads((archive/'source-state.json').read_text()).get('contract_inputs', []),
                         hardware_coverage=hardware_coverage(catalog,profiles,rows,bound=bool(contracts))),profiles,catalog)


def markdown(report):
    rows=report['profiles']
    counts={state:sum(x['runtime_state']==state for x in rows) for state in ('PASS','FAIL','BLOCKED','NOT-RUN')}
    lines=['# Native sample campaign results','',f"Campaign: **{report['status']}**. "+
           ', '.join(f'{n} {s}' for s,n in counts.items())+'.',
           '',f"Archive: `{report['archive']}`. Passing rows establish bounded warm-load evidence only.",
           'Cold-state, connected fixture, peer and recovery gates remain separate.',
           '', '| Profile | Core | Build | Runtime | Class | Evidence or blocker |',
           '|---|---|---|---|---|---|']
    for row in rows:
        evidence='; '.join('['+x.get('run_id',x['state'])+']('+str(ROOT/x['path'])+')' for x in row['evidence'])
        note=evidence or row['blocker'] or ''
        lines.append('| '+' | '.join(str(x).replace('|','/').replace('\n',' ') for x in
                     (row['profile'],row['core'],row['build_state'],row['runtime_state'],row['evidence_class'],note))+' |')
    if report.get('hardware_coverage'):
        lines.extend(['', '| Hardware family | Resources | Mode/output cells | Configured | Built | Diagnostic | Function | Electrical | Blocked/reserved |',
                      '|---|---|---|---|---|---|---|---|---|'])
        for domain in report['hardware_coverage']['domains']:
            lines.append('| '+' | '.join(str(domain[x]) for x in ('family','total','instance_cells',
                'configured','built','diagnostic','function','electrical'))+
                ' | '+str(domain['blocked'])+'/'+str(domain['reserved'])+' |')
        metadata=report['hardware_coverage'].get('non_executable_metadata', {})
        if any(metadata.values()):
            lines.extend(['', 'The following source records are not executable profiles and are excluded from channel and implementation totals.',
                          '', '| Reference inventory | State | Remaining contract |', '|---|---|---|'])
            for records in metadata.values():
                for record in records:
                    lines.append('| '+record['name']+' | '+record['state']+' | '+
                                 '; '.join(record['blockers']).replace('|','/')+' |')
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--run',type=Path,action='append',default=[],help='exact lab run directory; repeat chronologically')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--markdown',type=Path)
    args=parser.parse_args()
    report=aggregate(args.archive.resolve(),[x.resolve() for x in args.run])
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    if args.markdown:args.markdown.write_text(markdown(report))
    print(report['status'],len(report['profiles']),'profiles')
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
