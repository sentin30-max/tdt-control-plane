"""Restart the real persisted pilot without permitting a fresh execution."""
import argparse
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from .ledger import Ledger
from .resistance_pilot import run
from .runtime import atomic_json


def verify(root):
    root=Path(root).resolve();evidence=root/'evidence/slice002'
    original=json.loads((evidence/'pilot-run.json').read_text())
    ledger=Ledger(root/'.runtime/slice002/ledger.sqlite')
    before=ledger.db.execute("SELECT COUNT(*) FROM events WHERE kind='DISPATCHED'").fetchone()[0]
    attempts_before=ledger.db.execute('SELECT SUM(attempts) FROM executions').fetchone()[0]
    ledger.close()
    with (patch('tdt_control_plane.runtime.CodexRoleExecutor.submit',side_effect=AssertionError('NO_REDISPATCH')),
          patch('tdt_control_plane.resistance_pilot.LocalValidationExecutor.submit',side_effect=AssertionError('NO_REVALIDATION')),
          patch('subprocess.run',side_effect=AssertionError('NO_SUBPROCESS'))):
        recovered=run(root,'not-used-on-recovery',{},replay_only=True)
    ledger=Ledger(root/'.runtime/slice002/ledger.sqlite')
    after=ledger.db.execute("SELECT COUNT(*) FROM events WHERE kind='DISPATCHED'").fetchone()[0]
    attempts_after=ledger.db.execute('SELECT SUM(attempts) FROM executions').fetchone()[0]
    snapshots=[ledger.recover(step['execution_id']) for step in original['executions']]
    events=[dict(zip(['sequence','execution_id','kind','detail'],row)) for row in ledger.db.execute('SELECT * FROM events ORDER BY seq')]
    atomic_json(evidence/'ledger-export.json',{'executions':snapshots,'events':events})
    ledger.close()
    sample=json.loads((evidence/'executions'/(original['executions'][1]['execution_id']+'.json')).read_text())
    context=sample['context'];result=sample['result'];eid=context['execution_id']
    with tempfile.TemporaryDirectory(prefix='recovery-',dir=root/'.runtime/slice002') as tmp:
        isolated=Ledger(Path(tmp)/'contradiction.sqlite');isolated.register(context)
        accepted=isolated.ingest(eid,json.dumps(result),context['input_revision'],context['source_digests'])
        duplicate=isolated.ingest(eid,json.dumps(result),context['input_revision'],context['source_digests'])
        changed=copy.deepcopy(result);changed['rationale']+=' changed result'
        contradiction=isolated.ingest(eid,json.dumps(changed),context['input_revision'],context['source_digests'])
        preserved=isolated.recover(eid)['result_digest']==sample['result_digest'];isolated.close()
        stale=Ledger(Path(tmp)/'stale.sqlite');stale.register(context)
        altered={**context['source_digests'],'historical_request':'0'*64}
        stale_verdict=stale.ingest(eid,json.dumps(result),context['input_revision'],altered)
        stale_isolated=stale.recover(eid)['status']=='ISOLATED';stale.close()
    checks={
        'same_terminal_status':original['status']==recovered['status'],
        'same_operational_resolution':original['current_operational_resolution']==recovered['current_operational_resolution'],
        'same_results':[s['result_digest'] for s in original['executions']]==[s['result_digest'] for s in recovered['executions']],
        'all_recovered_ingests_noop':all(s['ingest']=='DUPLICATE_NOOP' for s in recovered['executions']),
        'no_new_dispatch':before==after,'no_new_attempt':attempts_before==attempts_after,
        'duplicate_noop':duplicate=='DUPLICATE_NOOP','different_digest_contradiction':contradiction=='EXECUTION_CONTRADICTION',
        'original_adverse_evidence_preserved':preserved,
        'changed_source_revalidation':stale_verdict=='REQUIRES_REVALIDATION' and stale_isolated,
    }
    report={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,
            'dispatches_before':before,'dispatches_after':after,'accepted':accepted,
            'duplicate':duplicate,'contradiction':contradiction,'changed_source':stale_verdict,
            'scope':'Real persisted results replayed; contradiction/stale probes in separate disposable ledgers; no historical A4 outputs reprocessed.'}
    atomic_json(evidence/'recovery-verification.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True)
    args=parser.parse_args();result=verify(args.root);print(result['status'])
    raise SystemExit(0 if result['status']=='PASS' else 1)
