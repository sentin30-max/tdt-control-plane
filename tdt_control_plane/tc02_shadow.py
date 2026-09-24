"""Generate TC-02 manifests from persisted records without executor dispatch."""
import argparse
import hashlib
import json
from pathlib import Path

from .context_manifest import build_manifest
from .contracts import digest
from .runtime import atomic_json, build_role_prompt


def tree_hashes(folder):
    return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob('*')) if p.is_file()}


def generate(root,output_dir):
    root=Path(root).resolve();output_dir=Path(output_dir).resolve();output_dir.mkdir(parents=True,exist_ok=True)
    protected=[root/'evidence/slice002',root/'evidence/tc01']
    before={str(p):tree_hashes(p) for p in protected}
    pilot=json.loads((root/'evidence/slice002/pilot-run.json').read_text(encoding='utf-8'))
    tc01=json.loads((root/'evidence/tc01/slice002-shadow.json').read_text(encoding='utf-8'))
    telemetry={r['identity']['execution_id']:r for r in tc01['observations']}
    llm_steps=[s for s in pilot['executions'] if s['backend']=='CodexRoleExecutor']
    manifests=[];snapshots=[]
    for step in llm_steps:
        persisted=json.loads((root/'evidence/slice002/executions'/(step['execution_id']+'.json')).read_text(encoding='utf-8'))
        context=persisted['context'];result=persisted['result']
        t=telemetry[step['execution_id']]
        manifest=build_manifest(context,{'schema_version':t['schema_version'],'record_digest':digest(t)})
        if manifest['coverage']['context_bytes']!=t['context']['bytes']['value']:
            raise ValueError('TC01_CONTEXT_BYTE_MISMATCH')
        atomic_json(output_dir/(step['execution_id']+'.manifest.json'),manifest)
        manifests.append(manifest)
        snapshots.append({'execution_id':step['execution_id'],'context_digest':digest(context),
                          'prompt_digest':hashlib.sha256(build_role_prompt(context).encode()).hexdigest(),
                          'result_digest':digest(result),'next_destination':result['next_destination'],
                          'findings_digest':digest(result['findings'])})
    # Cross-execution repetition is evidence, not a removal decision.
    occurrences={}
    for manifest in manifests:
        for unit in manifest['context_units']:
            key=(unit['selector'],unit['source_digest'],unit['authority_class'])
            occurrences.setdefault(key,[]).append({'execution_id':manifest['execution_id'],'bytes':unit['byte_size']})
    repeated=[{'selector':k[0],'source_digest':k[1],'authority_class':k[2],
               'executions':[x['execution_id'] for x in v],
               'repeated_bytes_after_first':sum(x['bytes'] for x in v[1:])}
              for k,v in occurrences.items() if len(v)>1]
    coverage_bytes=sum(m['coverage']['context_bytes'] for m in manifests)
    justified_bytes=sum(m['coverage']['bytes_by_semantic_necessity']['REQUIRED']+
                        m['coverage']['bytes_by_semantic_necessity']['CONDITIONAL'] for m in manifests)
    units=sum(m['coverage']['unit_count'] for m in manifests)
    justified_units=sum(m['coverage']['justified_unit_count'] for m in manifests)
    reduction=sum(m['coverage']['measured_bytes_reduction_potential'] for m in manifests)
    material_findings=[]
    for m in manifests:
        if m['protective_coverage']['missing']:
            material_findings.append({'execution_id':m['execution_id'],'code':'MISSING_PROTECTIVE_ELEMENT',
                                      'missing':m['protective_coverage']['missing']})
    if repeated:material_findings.append({'code':'CROSS_EXECUTION_REPETITION','unit_count':len(repeated),
                                          'bytes_after_first':sum(x['repeated_bytes_after_first'] for x in repeated),
                                          'effect':'shadow finding only; no context removal authorized'})
    preparation=next((m for m in manifests if any(u['selector']=='/inputs/operation' and
                     u['source_digest']==digest('PREPARE_CANDIDATE') for u in m['context_units'])),None)
    if preparation:
        material_findings.append({'code':'DETERMINISTIC_REPLACEMENT_CANDIDATE','execution_id':preparation['execution_id'],
                                  'basis':'operation is a bounded literal transformation with an existing exact deterministic oracle',
                                  'effect':'shadow candidate only; replacement not authorized'})
    def display_path(path):
        try:return path.relative_to(root).as_posix()
        except ValueError:return str(path)
    report={'schema_version':1,'policy_ref':'tc02-context-justification-shadow-v1','builder_version':'1',
            'status':'PASS' if len(manifests)==4 and not any(m['protective_coverage']['missing'] for m in manifests) else 'FAIL',
            'authoritative':False,'shadow':True,'operational':False,
            'source_fixture':'Slice 002 persisted evidence','manifests':[
                {'execution_id':m['execution_id'],'path':display_path(output_dir/(m['execution_id']+'.manifest.json')),
                 'manifest_digest':m['manifest_digest'],'coverage':m['coverage'],'protective_coverage':m['protective_coverage']}
                for m in manifests],
            'global_coverage':{'context_bytes':coverage_bytes,'unit_count':units,'justified_bytes':justified_bytes,
                               'justified_unit_count':justified_units,
                               'context_justification_coverage_bytes':justified_bytes/coverage_bytes,
                               'context_justification_coverage_units':justified_units/units},
            'cross_execution_repetition':repeated,
            'measured_bytes_reduction_potential':reduction,
            'estimated_token_reduction_potential':(reduction+3)//4,
            'actual_token_savings':None,'account_quota_savings':None,
            'material_findings':material_findings,'behavior_snapshot':snapshots,
            'tc01_baseline':tc01['forensic_baseline'],
            'new_llm_calls_for_tc02':0,'slice002_redispatched':False,'groq_executed':False,
            'a4_executed':False,'a5_executed':False,'material_context_change':False,
            'material_prompt_change':False,'routing_change':False,'authority_change':False,
            'result_semantics_change':False,'protected_scope_changed':False}
    atomic_json(output_dir/'shadow-index.json',report)
    after={str(p):tree_hashes(p) for p in protected}
    # output_dir is evidence/tc02 and is deliberately outside both protected trees.
    if before!=after:raise ValueError('PROTECTED_EVIDENCE_CHANGED')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output-dir',required=True)
    args=p.parse_args();report=generate(args.root,args.output_dir);print(report['status'])
    raise SystemExit(0 if report['status']=='PASS' else 1)
