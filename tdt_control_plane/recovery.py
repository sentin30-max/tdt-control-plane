"""Recovery verification and bounded PO package construction; no external dispatch."""
import json

from .contracts import digest
from .roles import validate_result


def review_package(resolution, decision):
    if decision.get('authority_required') != 'PO' or decision.get('review_trigger_reached') is not True:
        raise ValueError('NO_GENUINE_PO_GATE')
    return {'status':'PO_REQUIRED','authoritative':False,'revision':resolution['revision'],
            'question':decision['subject'],'known_requirement':decision.get('requirement'),
            'unresolved':decision.get('placement'), 'protected':resolution['protected'],
            'source_digests':resolution['source_digests'], 'effects_applied':[],
            'reason':'Material decision trigger reached; no delegated decision authority'}


def verify_recovery(runtime, proof, resolution):
    recovered = []
    for record in proof['records']:
        c=record['context']
        validate_result(record['result'],c)
        stored=runtime.recover(c)
        if stored is None or digest(stored['result']) != record['result_digest']:
            raise ValueError('RESULT_NOT_RECOVERABLE')
        verdict=runtime.ledger.ingest(c['execution_id'],json.dumps(stored['result']),resolution['revision'],resolution['source_digests'])
        if verdict != 'DUPLICATE_NOOP':
            raise ValueError('RECOVERY_NOT_IDEMPOTENT')
        recovered.append({'execution_id':c['execution_id'],'result_digest':record['result_digest'],'verdict':verdict})
    return {'authoritative':False,'new_external_executions':0,'recovered':recovered,
            'resolution_digest':digest(resolution),'status':'PASS'}
