"""Deterministic TC-01 shadow reconstruction from preserved Slice 002 records."""
import argparse
import hashlib
import json
from pathlib import Path

from .ledger import Ledger
from .runtime import atomic_json, build_role_prompt
from .telemetry import observe, task_summary


def tree_hashes(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob('*')) if p.is_file()}


def reconstruct(root, output):
    root=Path(root).resolve();source=root/'evidence/slice002'
    before=tree_hashes(source)
    pilot=json.loads((source/'pilot-run.json').read_text(encoding='utf-8'))
    recovery=json.loads((source/'recovery-run.json').read_text(encoding='utf-8'))
    exported=json.loads((source/'ledger-export.json').read_text(encoding='utf-8'))
    attempts={row['context']['execution_id']:row['attempts'] for row in exported['executions']}
    records=[]
    shadow_db=root/'.runtime/tc01/shadow.sqlite';shadow_db.parent.mkdir(parents=True,exist_ok=True)
    if shadow_db.exists():
        shadow_db.unlink()
    ledger=Ledger(shadow_db)
    try:
        for step in pilot['executions']:
            persisted=json.loads((source/'executions'/(step['execution_id']+'.json')).read_text(encoding='utf-8'))
            context=persisted['context'];result=persisted['result'];backend=step['backend']
            ledger.register(context)
            ledger.ingest(context['execution_id'],json.dumps(result),context['input_revision'],context['source_digests'])
            prompt=build_role_prompt(context) if backend=='CodexRoleExecutor' else None
            record=observe(context,result,backend=backend,prompt=prompt,events=[],attempt=attempts[context['execution_id']])
            ledger.observe(record);records.append(record)
        recovery_ids=[step['execution_id'] for step in recovery['executions']]
        for eid in recovery_ids:
            if not ledger.telemetry(eid):
                raise ValueError('RECOVERY_WITHOUT_PERSISTED_OBSERVATION')
            ledger._event(eid,'TELEMETRY_RECOVERY_REUSED','no_new_dispatch_or_usage')
        ledger_events=[{'seq':r[0],'execution_id':r[1],'kind':r[2],'detail':r[3]}
                       for r in ledger.db.execute('SELECT seq,execution_id,kind,detail FROM events ORDER BY seq')]
    finally:
        ledger.close()
    llm=[r for r in records if r['execution_kind']=='LLM']
    deterministic=[r for r in records if r['execution_kind']=='DETERMINISTIC']
    estimated_input=sum((r['prompt']['bytes']['value']+3)//4 for r in llm)
    estimated_output=sum(r['output']['estimated_tokens']['value'] for r in llm)
    forensic={'llm_sessions':len(llm),'deterministic_executions':len(deterministic),
              'estimated_input_tokens':estimated_input,'estimated_output_tokens':estimated_output,
              'estimated_combined_tokens':estimated_input+estimated_output,
              'classification':'ESTIMATED','method':'ceil_utf8_bytes_div_4_proxy over reconstructed existing prompt; default JSON result serialization',
              'actual_runtime_tokens':None,'actual_runtime_tokens_status':'NOT_AVAILABLE',
              'actual_runtime_tokens_reason':'preserved records contain no runtime usage counters',
              'account_quota_attribution':None,'account_quota_status':'NOT_AVAILABLE',
              'account_quota_reason':'token usage is not account quota usage'}
    expected={'llm_sessions':4,'estimated_input_tokens':28397,'estimated_output_tokens':4928,'estimated_combined_tokens':33325}
    report={'schema_version':1,'status':'PASS' if all(forensic[k]==v for k,v in expected.items()) else 'METHOD_DIFFERENCE',
            'authoritative':False,'source_fixture':'Slice 002 persisted evidence at c9d895cca0aee1f12aa1c85af564047d2a9a4457',
            'observations':records,'task_summary':task_summary(records),'forensic_baseline':forensic,
            'expected_forensic_baseline':expected,'recovery':{'recovered_results':len(recovery_ids),'new_dispatches':0,
            'new_model_calls':0,'usage_double_counted':False},'ledger_events':ledger_events,
            'material_behavior_change':'NONE','historical_evidence_modified':False,
            'new_llm_calls_for_tc01_testing':0,'groq_executed':False,'a4_executed':False,'a5_executed':False}
    after=tree_hashes(source)
    if after != before:
        raise ValueError('PROTECTED_HISTORICAL_EVIDENCE_CHANGED')
    atomic_json(output,report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();report=reconstruct(args.root,args.output);print(report['status'])
    raise SystemExit(0 if report['status']=='PASS' else 1)
