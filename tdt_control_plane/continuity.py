"""Bounded Advisor-first workflow. The router validates, the Advisor proposes."""
import argparse
import json
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL

from .contracts import digest
from .ledger import Ledger
from .projection import project
from .resolution import load_fixture
from .roles import strict_json
from .runtime import CodexRoleExecutor, atomic_json

EXECUTION_CONTRACT = {
    'scope':'control-plane-fixture', 'authority':'PO IMPLEMENTATION-001 bounded read-only E2E authorization',
    'operation_indices':[0,1], 'operation_count':2,
    'instructions': 'Operation 0: produce a sorted lifecycle list of [subject,state] for Resistance and Support, preserve evaluated_baseline, placement and domain_defects. '
                    'Operation 1: count CERRADO and EN_AUDITORIA entries from the verified operation-0 list as closed_units and auditing_units, preserve placement and set trader_modified false.',
    'artifact_keys': {'0':['lifecycle','evaluated_baseline','placement','domain_defects'],
                      '1':['closed_units','auditing_units','placement','trader_modified']},
    'verification_authority':'Control Plane computes reference artifacts independently and compares canonical JSON digests; it records actual CLI thread IDs and checks no tool-call events occurred.',
    'review_policy':'Every material executor result returns to Advisor. COMPLETE means only the two bounded computations and their reviews are complete, never product approval or final Slice acceptance.',
    'protected_effects_allowed':False,
}


def authorize_destination(proposal, *, specification_ready, completed, decision_required=False):
    if proposal == 'PO_REQUIRED':
        if not decision_required:
            raise ValueError('UNJUSTIFIED_PO_ESCALATION')
        return proposal
    if proposal == 'COMPLETE':
        if not completed:
            raise ValueError('PREMATURE_COMPLETION')
    elif proposal == 'CODE_EXECUTOR':
        if not specification_ready or completed:
            raise ValueError('EXECUTION_PRECONDITIONS')
    elif proposal not in {'ADVISOR','DEVELOPMENT'}:
        raise ValueError('UNAUTHORIZED_DESTINATION')
    return proposal


def expected_artifact(resolution, operation):
    r = resolution['resolved']
    if operation == 0:
        return {'lifecycle': [['Resistance',r['resistance_audit']['value']],['Support',r['support_closed']['value']]],
                'evaluated_baseline':r['evaluated']['value'], 'placement':'UNRESOLVED_PLACEMENT',
                'domain_defects':r['domain_not_determined']['value']}
    if operation == 1:
        values = [r['resistance_audit']['value'],r['support_closed']['value']]
        return {'closed_units': values.count('CERRADO'), 'auditing_units':values.count('EN_AUDITORIA'),
                'placement':'UNRESOLVED_PLACEMENT','trader_modified':False}
    raise ValueError('NO_PENDING_OPERATION')


def run(runtime, resolution, quality, output, workflow_id, max_dispatches=10, refresh=None):
    if {e['role'] for e in quality['evaluations'] if e['passed']} != {'ADVISOR','DEVELOPMENT'} or quality.get('semantic_review',{}).get('passed') is not True:
        raise ValueError('ROLE_QUALITY_NOT_VALIDATED')
    # This is an authorized fixture contract, not a product-state transition.
    operation = 0
    role = 'ADVISOR'
    target = {'kind':'seed_result', 'artifact':{k:resolution['resolved'][k] for k in ['support_closed','resistance_audit','evaluated','domain_not_determined']}, 'verified':True,
              'verification_basis':'Pinned source byte hashes, explicit applicability predicates and fact-scoped authority mapping checked by the read-only source adapter. Relevant source excerpts are in inputs.source_evidence.',
              'purpose':'Two authorized read-only computations over the fixture; no Trader operation'}
    records = []
    specifications = {}
    sources = dict(resolution['source_digests'])
    sources['execution_contract'] = digest(EXECUTION_CONTRACT)
    for index in range(max_dispatches):
        if refresh is not None and refresh()['revision'] != resolution['revision']:
            raise ValueError('SOURCE_CHANGED_REVALIDATION_REQUIRED')
        eid = str(uuid5(NAMESPACE_URL, workflow_id + ':' + str(index)))
        done = operation >= 2
        work = EXECUTION_CONTRACT
        history = [{'execution_id':r['context']['execution_id'], 'role':r['context']['role'],
                    'result_digest':r['result_digest'], 'destination':r['result']['next_destination'],
                    'outcome':r['result']['outcome'], 'artifact':r['result']['artifact'],
                    'runtime_evidence':{'thread_id':r.get('runtime_thread_id'), 'tool_calls':r.get('tool_calls'), 'sandbox':'read-only'},
                    'independent_verification':r.get('independent_verification')}
                   for r in records if r['context']['role'] in {'CODE_EXECUTOR','ADVISOR'}]
        task = dict(task_id=str(uuid5(NAMESPACE_URL,workflow_id+':operation:'+str(operation))),
                    required_claims=['support_closed','resistance_audit','evaluated','domain_not_determined'],
                    requirements=['No protected writes','Preserve unresolved placement','No audit/domain conflation','Advisor review after every material result'],
                    relevant_scopes=['product-placement'], objective='Complete two authorized fixture computations under Advisor-first routing',
                    work={'contract':work,'current_operation':None if done else operation,'completed_operation_count':operation,
                          'completion_review':done,'previous_result':target,'verification_history':history},
                    review_target=target, permitted_destinations=['ADVISOR','DEVELOPMENT','COMPLETE'] if done else ['ADVISOR','DEVELOPMENT','CODE_EXECUTOR'],
                    implementation_specification=specifications.get(operation, {'contract':work,'authorized':True,'scope':'read-only fixture computation'}))
        context = project(resolution, task, role, eid)
        context['source_digests']['execution_contract'] = digest(EXECUTION_CONTRACT)
        # Include prior result digests as material dependencies, but not source authority.
        if records:
            context['inputs']['prior_result_digest'] = records[-1]['result_digest']
        context['context_id'] = digest({k:v for k,v in context.items() if k not in {'context_id','execution_id'}})
        record = runtime.submit(context)
        verdict = runtime.ledger.ingest(eid,json.dumps(record['result']),resolution['revision'],sources)
        if verdict not in {'ACCEPTED','DUPLICATE_NOOP','STILL_APPLICABLE'} or runtime.ledger.recover(eid)['status'] != 'INGESTED':
            raise ValueError('INGEST_REJECTED')
        records.append(record)
        result = record['result']
        atomic_json(output,{'status':'RESULT_RECEIVED','workflow_id':workflow_id,'records':records,'executions_verified':operation,'authoritative':False})
        if role == 'ADVISOR':
            if result['outcome'] != 'SUCCEEDED' and result['next_destination'] in {'CODE_EXECUTOR','COMPLETE'}:
                raise ValueError('UNRESOLVED_REVIEW_FINDINGS')
            destination = authorize_destination(result['next_destination'],specification_ready=not done,completed=done)
            if destination == 'COMPLETE':
                proof = {'status':'PASS','workflow_id':workflow_id,'records':records,'executions_verified':operation,
                         'authoritative':False,'manual_transport':False,'hardcoded_role_alternation':False,
                         'scope':'Pinned read-only fixture computations only; final Slice acceptance remains with PO'}
                atomic_json(output,proof)
                return proof
            role = destination
            if role == 'ADVISOR':
                target = {'kind':'advisor_result','artifact':result,'verified':True}
        elif role == 'CODE_EXECUTOR':
            if result['outcome'] != 'SUCCEEDED':
                raise ValueError('EXECUTION_NOT_SUCCEEDED')
            artifact = strict_json(result['artifact'])
            # Exact comparison is the independent task oracle, not executor self-approval.
            if type(artifact) is not dict or digest(artifact) != digest(expected_artifact(resolution,operation)):
                raise ValueError('MATERIAL_RESULT_CONTRADICTION')
            record['independent_verification'] = {'verifier':'Control Plane deterministic fixture oracle',
                                                  'operation_index':operation,'expected_artifact':expected_artifact(resolution,operation),
                                                  'actual_artifact_digest':digest(artifact),'matches':True}
            target = {'kind':'code_result','artifact':artifact,'verified':True,'operation':operation}
            operation += 1
            role = 'ADVISOR'
        else:
            artifact = strict_json(result['artifact'])
            if (result['outcome'] != 'SUCCEEDED' or type(artifact) is not dict
                    or any(type(artifact.get(k)) is not list for k in ('requirements','steps','acceptance','prohibitions','open_questions'))
                    or any(not artifact[k] for k in ('requirements','steps','acceptance','prohibitions'))
                    or artifact.get('self_approved',False) is not False):
                raise ValueError('SPECIFICATION_INVALID')
            specifications[operation] = artifact
            target = {'kind':'development_result','artifact':artifact,'verified':False}
            role = 'ADVISOR'
        atomic_json(output,{'status':'IN_PROGRESS','workflow_id':workflow_id,'records':records,'executions_verified':operation,'authoritative':False})
    raise ValueError('DISPATCH_BUDGET_EXHAUSTED')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--codex',required=True)
    p.add_argument('--cost-attestation',required=True)
    p.add_argument('--quality',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--workflow-id',required=True)
    args=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    state=root/'.runtime/continuity'
    state.mkdir(parents=True,exist_ok=True)
    ledger=Ledger(state/'ledger.db')
    runtime=CodexRoleExecutor(args.codex,ledger,state,json.loads(Path(args.cost_attestation).read_text()))
    try:
        proof=run(runtime,load_fixture(root/'fixtures/trader'),strict_json(Path(args.quality).read_text()),args.output,args.workflow_id,
                  refresh=lambda:load_fixture(root/'fixtures/trader'))
        print('CONTINUITY',proof['status'],'EXECUTIONS',proof['executions_verified'],flush=True)
    except ValueError as e:
        path=Path(args.output)
        state=strict_json(path.read_text()) if path.exists() else {'workflow_id':args.workflow_id,'records':[],'authoritative':False}
        state.update(status='STOP',reason=str(e))
        atomic_json(path,state)
        print('STOP',str(e),flush=True)
        return 1
    finally:
        ledger.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
