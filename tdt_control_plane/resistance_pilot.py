"""Bounded real Resistance preparation. No API for activating candidates or audits."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .contracts import digest
from .ledger import Ledger
from .resistance_candidate import materialize_candidate, specification
from .resistance_sources import read_sources, sha
from .roles import make_context, strict_json, validate_result
from .runtime import CodexRoleExecutor, atomic_json
from .telemetry import observe

PROTECTED = ['Trader AI', 'TEF', 'Governance', 'Sprint 2', 'Support', 'D6',
             'Resistance production and lifecycle', 'historical A4 requests/outputs',
             'evaluated baseline 46828c1658b5328f65fd23ad2e350a19e54039ae']
TASK = str(uuid5(NAMESPACE_URL, 'tdt:resistance:slice002:two-stage-v1'))


def applicable(state):
    """Validate proposals against concrete state; never prescribe a role sequence."""
    if state.get('blocker'):
        return {'ADVISOR', 'PO_REQUIRED'}
    routes = {'ADVISOR'}
    if state.get('specification_gap'):
        routes.add('DEVELOPMENT')
    else:
        if not state.get('candidate') or not state.get('verification'):
            routes.add('CODE_EXECUTOR')
        elif state['verification']['local_validation'] == 'PASS' and state['verification']['preflight'] == 'PASS':
            routes.add('COMPLETE')
    return routes


def route(result, state):
    destination = result['next_destination']
    if result['role'] != 'ADVISOR' or destination not in applicable(state):
        raise ValueError('DESTINATION_NOT_APPLICABLE_OR_AUTHORIZED')
    if destination == 'COMPLETE' and result['outcome'] != 'SUCCEEDED':
        raise ValueError('REFUTATION_CANNOT_COMPLETE')
    return destination


class LocalValidationExecutor:
    """CODE_EXECUTOR backend restricted to the published local validator entrypoint."""
    def __init__(self, root, ledger, spool):
        self.root, self.ledger, self.spool = root, ledger, spool

    def submit(self, context):
        if context['role'] != 'CODE_EXECUTOR' or context['inputs']['operation'] != 'LOCAL_VALIDATION_PREFLIGHT':
            raise ValueError('LOCAL_EXECUTOR_SCOPE')
        self.ledger.register(context)
        path = self.spool / (context['execution_id'] + '.json')
        if path.exists():
            record = strict_json(path.read_text())
            validate_result(record['result'], context)
            if record['context_digest'] != digest(context) or record['result_digest'] != digest(record['result']):
                raise ValueError('RECOVERY_HASH_MISMATCH')
            return record
        self.ledger.claim(context['execution_id'])
        output = self.root/'evidence/slice002/local-verification.json'
        run = subprocess.run([sys.executable, '-m', 'tdt_control_plane.resistance_validate',
                              '--root', str(self.root), '--output', str(output), '--candidate',
                              str(self.root/'evidence/slice002/candidate.json')],
                             cwd=self.root, capture_output=True, text=True, timeout=120)
        if run.returncode or not output.is_file():
            self.ledger.fail(context['execution_id'], 'DEPENDENCY_FAILURE')
            atomic_json(self.root/'evidence/slice002/local-executor-failure.json',
                        {'exit_code':run.returncode, 'output':run.stdout, 'error':run.stderr})
            raise ValueError('LOCAL_VALIDATOR_FAILURE')
        artifact = strict_json(output.read_text())
        result = {k:context[k] for k in ['execution_id','task_id','context_id','input_revision','role']}
        result.update(context_digest=digest(context), outcome='SUCCEEDED', next_destination='NONE',
                      rationale='Native published local validation and full evidence preflight; no audit invocation.',
                      artifact=json.dumps(artifact,sort_keys=True), findings=['Preflight '+artifact['preflight']],
                      evidence_refs=list(context['source_digests']), proposals=[], effects=[], protected_scope_touched=[])
        validate_result(result,context)
        record = {'context':context,'context_digest':digest(context),'result':result,'result_digest':digest(result),
                  'backend':'PublishedLocalValidationExecutor','tool_calls':0,'authoritative':False}
        atomic_json(path,record)
        try:
            self.ledger.observe(observe(context,result,backend='PublishedLocalValidationExecutor',events=[],
                                        attempt=self.ledger.recover(context['execution_id'])['attempts']))
        except Exception as error:
            self.ledger._event(context['execution_id'],'TELEMETRY_FAILED',type(error).__name__)
        return record


def run(root, executable, cost, replay_only=False):
    root = Path(root).resolve()
    sources = read_sources(root)
    publication = strict_json((root/'evidence/slice002/publication-verification.json').read_text())
    if not publication['publication_verified'] or publication['source_revision'] != sources['revision']:
        raise ValueError('PUBLICATION_NOT_VERIFIED')
    evidence = root/'evidence/slice002'
    spool = evidence/'executions'; spool.mkdir(exist_ok=True)
    ledger = Ledger(root/'.runtime/slice002/ledger.sqlite')
    codex = CodexRoleExecutor(executable,ledger,spool,cost)
    local = LocalValidationExecutor(root,ledger,spool)
    publication_summary = {k:publication[k] for k in ['status','source_revision','publication_verified','tooling_passed','resolver_passed','checks']}
    base = {**sources['hashes'], 'publication':digest(publication_summary), 'specification':digest(specification(sources))}
    revision = digest({'source_revision':sources['revision'],'sources':base})
    state = {'source_revision':sources['revision'],'formal_lifecycle':sources['lifecycle'],
             'operational_point':sources['operational_point'],'specification_gap':None,
             'candidate':None,'verification':None,'blocker':None}
    steps = []
    role = 'ADVISOR'
    previous = {'publication':publication_summary,'recovered_operational_point':sources['operational_point']}
    decisions = []
    def save(status):
        report = {'task_id':TASK,'status':status,'source_revision':sources['revision'],
                  'current_operational_resolution':state,'executions':steps,'routing':decisions,
                  'candidate_artifact_identity':state.get('candidate'), 'verification_state':state.get('verification'),
                  'po_manual_transport':False,'authoritative':False}
        atomic_json(evidence/('recovery-run.json' if replay_only else 'pilot-run.json'),report)
        return report
    try:
        for index in range(10):
            read_sources(root)  # reject changed protected bytes before any dispatch
            inputs = {'state':state.copy(),'previous_material_result':previous,
                      'publication':publication_summary,'specification':specification(sources),
                      'po_authority':'Authorized preparation/local validation/preflight in Control Plane ONLY. No Groq, A4, A5, source writes, historical reprocessing, spend or evidence compaction. On unresolved/preflight failure preserve, review and STOP. Final COMPLETE means candidate ready for PO gate, never activated.',
                      'source_contract':sources['texts']['published_contract']}
            if role == 'ADVISOR':
                inputs['applicable_destinations'] = sorted(applicable(state))
                inputs['requested_artifact'] = {'review':'evidenced review/refutation','specification_gap':'null or material missing requirement','authority_gap':'null or genuine missing authority'}
                objective = 'Review the real Resistance state and previous material result. Inspect correctness and scope. Propose the warranted dynamic destination; no self-approval, no fabricated blocker, no forcing Development. Existing exact transformation is sufficient unless you identify a concrete missing requirement. COMPLETE only after native validation AND preflight PASS. Return PO_REQUIRED on the preserved terminal preflight/unresolved blocker; do not suggest compaction or audit execution.'
                # First review sees the actual preexisting inputs; later ones see the full produced artifact.
                inputs['historical_request'] = json.loads(sources['texts']['historical_request'])
                inputs['historical_input'] = sources['texts']['historical_input']
            elif role == 'DEVELOPMENT':
                objective = 'Resolve only the evidenced specification gap using the published contract and supplied sources; no redesign or new authority. Return specification and remaining_gap in artifact, next_destination NONE.'
                inputs['requested_artifact'] = {'specification':'bounded clarification','remaining_gap':'null or unresolved gap'}
            elif not state['candidate']:
                inputs['operation'] = 'PREPARE_CANDIDATE'
                inputs['historical_request'] = json.loads(sources['texts']['historical_request'])
                inputs['historical_input'] = sources['texts']['historical_input']
                objective = 'Compute the complete new request JSON and input_text using the exact supplied literal transformations. Return ONLY those two fields in artifact. Preserve trailing newline and all other input characters. No tools/writes; Control Plane independently verifies and materializes your output in its own candidate directory.'
            else:
                inputs['operation'] = 'LOCAL_VALIDATION_PREFLIGHT'
                objective = 'Run the allowlisted published local validator and full native evidence preflight for the verified candidate. No network, no auditor, no compaction.'
            source_digests = {**base,'state':digest(state),'previous_material_result':digest(previous)}
            eid = str(uuid5(NAMESPACE_URL, TASK+':'+str(index)+':'+role))
            context = make_context(eid,TASK,revision,role,'Slice002: Resistance A4 preparation only',objective,inputs,source_digests,PROTECTED)
            atomic_json(evidence/('replay-next-context.json' if replay_only else 'next-context.json'),context)
            backend = local if inputs.get('operation') == 'LOCAL_VALIDATION_PREFLIGHT' else codex
            if replay_only:
                record = codex.recover(context)
                if record is None:
                    raise ValueError('REPLAY_CANNOT_DISPATCH')
            else:
                print('DISPATCH',index,role,inputs.get('operation','REVIEW'),flush=True)
                # Never auto-regenerate a failed execution inside this pilot.
                row = ledger.db.execute('SELECT status FROM executions WHERE id=?',(eid,)).fetchone()
                if row and row[0] == 'ISOLATED':
                    raise ValueError('ISOLATED_EXECUTION_REQUIRES_REVIEW')
                record = backend.submit(context)
            refreshed = read_sources(root)
            current_sources = {**source_digests,**refreshed['hashes']}
            verdict = ledger.ingest(eid,json.dumps(record['result']),revision,current_sources)
            if verdict not in {'ACCEPTED','DUPLICATE_NOOP'}:
                raise ValueError(verdict)
            result = record['result']
            steps.append({'execution_id':eid,'role':role,'context_digest':record['context_digest'],
                          'result_digest':record['result_digest'],'ingest':verdict,
                          'backend':record.get('backend','CodexRoleExecutor'),
                          'runtime_thread_id':record.get('runtime_thread_id'),
                          'advisor_finding':result['findings'] if role=='ADVISOR' else None,
                          'next_destination':result['next_destination']})
            artifact = strict_json(result['artifact'])
            previous = {'result':result,'artifact':artifact,'result_digest':record['result_digest']}
            if role == 'ADVISOR':
                if artifact.get('specification_gap'):
                    state['specification_gap'] = artifact['specification_gap']
                if artifact.get('authority_gap'):
                    state['blocker'] = {'code':'AUTHORITY_GAP','finding':artifact['authority_gap']}
                destination = route(result,state)
                decisions.append({'execution_id':eid,'proposed':destination,'validated':True,'state_digest':digest(state),'rationale':result['rationale']})
                save('RUNNING')
                if destination in {'COMPLETE','PO_REQUIRED'}:
                    return save('COMPLETE' if destination=='COMPLETE' else 'STOP')
                role = destination
            elif role == 'DEVELOPMENT':
                state['specification_gap'] = artifact.get('remaining_gap')
                state['development_proposal'] = artifact
                role = 'ADVISOR'
            elif inputs['operation'] == 'PREPARE_CANDIDATE':
                try:
                    state['candidate'] = materialize_candidate(root,artifact,sources)
                    atomic_json(evidence/'candidate.json',state['candidate'])
                except ValueError as error:
                    state['blocker'] = {'code':str(error),'finding':'Candidate rejected; no activation or silent correction.'}
                role = 'ADVISOR'
            else:
                state['verification'] = artifact
                if artifact['local_validation'] != 'PASS' or artifact['preflight'] != 'PASS':
                    state['blocker'] = {'code':'LOCAL_VALIDATION_OR_PREFLIGHT_FAILED','finding':artifact}
                role = 'ADVISOR'
            save('RUNNING')
        state['blocker'] = {'code':'BOUNDED_DISPATCH_LIMIT'}
        return save('STOP')
    except (ValueError,OSError,subprocess.TimeoutExpired) as error:
        state['blocker'] = {'code':str(error),'requires_reconciliation':True}
        save('STOP')
        raise
    finally:
        ledger.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--codex',required=True)
    p.add_argument('--cost',required=True);p.add_argument('--replay-only',action='store_true')
    args=p.parse_args()
    report=run(args.root,args.codex,json.loads(Path(args.cost).read_text()),args.replay_only)
    print(report['status'],flush=True)


if __name__=='__main__':main()
