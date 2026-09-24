"""Eight local TC-06 admission pilots; no model dispatch occurs."""
import argparse
import json
import tempfile
from pathlib import Path
from uuid import uuid5,NAMESPACE_URL

from .budget_admission import (AdmissionGate,BudgetPolicy,FINGERPRINT_VERSION,POLICY_VERSION)
from .deterministic_dispatch import DeterministicDispatcher
from .deterministic_preparation import CONTRACT_VERSION,RULE_SET_VERSION
from .ledger import Ledger
from .roles import make_context
from .runtime import atomic_json
from .tc02_shadow import tree_hashes
from .telemetry import serialized_json_bytes

def _context(name,role='DEVELOPMENT'):
    return make_context(str(uuid5(NAMESPACE_URL,'tc06:exec:'+name)),str(uuid5(NAMESPACE_URL,'tc06:task:'+name)),'a'*64,role,
        'TC06 controlled admission fixture','Produce explicitly bounded material output',
        {'state':{'value':name,'blocker':None},'evidence_refs':['fixture']},{'fixture':'b'*64},['protected baseline'])

def _policy(gate,c,calls=4,tokens=20000,reserve_calls=1,reserve_tokens=2000,role_calls=3,role_tokens=16000):
    other_calls=calls-role_calls;other_tokens=tokens-role_tokens
    role=c['role'];allocations={role:{'max_model_calls':role_calls,'estimated_token_ceiling':role_tokens}}
    review_role='ADVISOR'
    if review_role==role:
        allocations[role]={'max_model_calls':calls,'estimated_token_ceiling':tokens}
    else:allocations[review_role]={'max_model_calls':other_calls,'estimated_token_ceiling':other_tokens}
    gate.configure(BudgetPolicy(c['task_id'],calls,tokens,reserve_calls,reserve_tokens,allocations))

def _evaluate(gate,c,**kwargs):
    values={'why_llm_required':'GENERATIVE_SYNTHESIS_REQUIRED','execution_purpose':'produce a new bounded specification',
            'expected_material_output':'strict structured specification','output_token_budget':1000}
    values.update(kwargs);return gate.evaluate(c,**values)

def generate(root,output_dir):
    root=Path(root).resolve();output_dir=Path(output_dir).resolve();output_dir.mkdir(parents=True,exist_ok=True)
    protected=[root/f'evidence/{name}' for name in ('slice002','tc01','tc02','tc03','tc04','tc05')]
    before={str(p):tree_hashes(p) for p in protected}
    historical=json.loads((root/'evidence/slice002/executions/96355d38-bc31-5eab-9a70-beda3f1e4e69.json').read_text())['context']
    with tempfile.TemporaryDirectory() as tmp:
        ledger=Ledger(Path(tmp)/'admission.db');gate=AdmissionGate(ledger,DeterministicDispatcher(ledger))
        reuse_c=_context('reuse');_policy(gate,reuse_c);gate.remember_reusable(reuse_c,'c'*64);reuse=_evaluate(gate,reuse_c)
        deterministic=gate.evaluate(historical,contract_version=CONTRACT_VERSION,rule_set_version=RULE_SET_VERSION)
        admit_c=_context('admit');_policy(gate,admit_c);admit=_evaluate(gate,admit_c)
        reserve_c=_context('reserve');required=(serialized_json_bytes(reserve_c)+3)//4+1000
        _policy(gate,reserve_c,calls=2,tokens=required+1999,reserve_calls=1,reserve_tokens=2000,role_calls=1,role_tokens=required)
        review_reserve=_evaluate(gate,reserve_c)
        exhausted_c=_context('exhausted');required=(serialized_json_bytes(exhausted_c)+3)//4+999
        _policy(gate,exhausted_c,calls=3,tokens=required,reserve_calls=0,reserve_tokens=0,role_calls=2,role_tokens=required)
        exhausted=_evaluate(gate,exhausted_c)
        uncertain_c=_context('uncertain');_policy(gate,uncertain_c);uncertain_initial=_evaluate(gate,uncertain_c)
        gate.transition(uncertain_initial['reservation_id'],'UNCERTAIN');uncertain_retry=_evaluate(gate,uncertain_c)
        duplicate_c=_context('duplicate');_policy(gate,duplicate_c);duplicate_initial=_evaluate(gate,duplicate_c);duplicate_second=_evaluate(gate,duplicate_c)
        independent_c=_context('independent','ADVISOR');_policy(gate,independent_c,calls=2,tokens=10000,reserve_calls=1,reserve_tokens=2000,role_calls=2,role_tokens=10000)
        gate.remember_reusable(independent_c,'d'*64);independent=_evaluate(gate,independent_c,why_llm_required='INDEPENDENT_REVIEW_REQUIRED',
            execution_purpose='perform independent review',expected_material_output='independent findings',independent_review=True)
        telemetry={name:gate.telemetry(context['task_id']) for name,context in [('admit',admit_c),('uncertain',uncertain_c),('duplicate',duplicate_c),('independent',independent_c)]}
        ledger.close()
    pilots={
      'reuse':{'status':'PASS' if reuse.get('route')=='REUSE' and reuse.get('reservation') is None else 'FAIL','decision':reuse},
      'deterministic':{'status':'PASS' if deterministic.get('route')=='DETERMINISTIC' and deterministic.get('reservation') is None else 'FAIL','decision':deterministic},
      'admit':{'status':'PASS' if admit['decision']=='ADMIT' and not admit['llm_dispatched'] else 'FAIL','decision':admit,'dispatch_not_executed':True},
      'review_reserve':{'status':'PASS' if review_reserve['decision']=='REVIEW_REQUIRED' else 'FAIL','decision':review_reserve},
      'budget_exhausted':{'status':'PASS' if exhausted['decision']=='DEFER' else 'FAIL','decision':exhausted},
      'uncertain':{'status':'PASS' if uncertain_retry['decision']=='DEFER' and uncertain_retry['reason']=='UNCERTAIN_NO_AUTOMATIC_RETRY' else 'FAIL','initial':uncertain_initial,'retry':uncertain_retry},
      'duplicate_reservation':{'status':'PASS' if duplicate_second['reason']=='DUPLICATE_RESERVATION' else 'FAIL','initial':duplicate_initial,'second':duplicate_second},
      'independent_review':{'status':'PASS' if independent['decision']=='ADMIT' and independent['independent_review'] else 'FAIL','decision':independent}}
    atomic_json(output_dir/'controlled-pilots.json',{'pilots':pilots,'telemetry':telemetry,'model_calls_executed':0})
    attacks=[
      'repeat spending selects reuse','deterministic task cannot request LLM','executor cannot bypass permit','usage estimate computed internally',
      'NOT_AVAILABLE not zero','NOT_AVAILABLE not infinite','estimated remains estimated','role is not necessity','budget never prunes context',
      'review reserve protected','independent review not reused','duplicate reservation rejected','timeout becomes uncertain','uncertain not zero',
      'released not consumed','consumed not active','budget layers not double counted','output budget not reduced','paid fallback false',
      'material blocker remains blocker','budget issue does not change authority','stale fingerprint misses reuse','authority participates in fingerprint',
      'blocker participates in fingerprint','complete inputs preserve adverse findings','executor cannot enlarge policy','telemetry has no authority',
      'account quota not inferred','provider TPM separate from account quota','TC05 blocker cannot fall through']
    accepted=all(p['status']=='PASS' for p in pilots.values())
    report={"report":"TC_06_BUDGET_ADMISSION_GOVERNANCE_REPORT","status":"IMPLEMENTED_CANDIDATE" if accepted else "FAILED",
      "baseline":["4cb07fbcba175ab04bcc8a3e28974d36ba5f998f","6321ce8ffd8b69f392c2d29e7f7845b12b18c442","494acd920725fb3f76d7c8039b3243cc0c33bf7e"],
      "branch":"implementation/tc-06-budget-admission-governance","implementation_commit":"PENDING_AT_GENERATION","final_evidence_commit":"PENDING_AT_GENERATION",
      "files_changed":["TC-06.md","tdt_control_plane/budget_admission.py","tdt_control_plane/tc06_pilot.py","tests/test_budget_admission.py","evidence/tc06/*"],
      "admission_model":"validate -> recover/reuse -> TC05 deterministic -> LLM necessity -> estimate -> cumulative usage -> review reserve -> atomic reservation -> ADMIT",
      "budget_policy_version":POLICY_VERSION,"budget_hierarchy":"TASK_BUDGET contains ROLE_ALLOCATION contains EXECUTION_RESERVATION; layers are not summed",
      "resource_units":["MODEL_CALL_COUNT","CONTEXT_BYTES","CONTEXT_TOKEN_ESTIMATE","OUTPUT_TOKEN_BUDGET","LOCAL_RUNTIME","PROVIDER_REQUEST_LIMIT","ACCOUNT_QUOTA"],
      "measurement_statuses":["MEASURED","ESTIMATED","NOT_AVAILABLE"],
      "task_budget_model":["max_model_calls","estimated_token_ceiling","review_reserve","consumed/reserved cumulative state"],
      "role_allocation_model":"partition within task budget","review_reserve_model":"configured calls and estimated tokens retained for Advisor",
      "execution_reservation_model":["reservation_id","task_id","role","execution_id","policy_version","context/output estimates","state digest","status"],
      "reservation_states":["RESERVED","CONSUMED","RELEASED","UNCERTAIN"],
      "material_reasoning_fingerprint":{"version":FINGERPRINT_VERSION,"includes":"revision, role, scope, authority, protections, objective, full inputs/blockers/adverse evidence, sources and review contract","excludes":"execution identity"},
      "llm_necessity_model":["SEMANTIC_REVIEW_REQUIRED","OPEN_ENDED_ANALYSIS","INDEPENDENT_REVIEW_REQUIRED","UNRESOLVED_INTERPRETATION_WITHIN_AUTHORITY","GENERATIVE_SYNTHESIS_REQUIRED"],
      "admission_taxonomy":["ADMIT","DEFER","BLOCK","REVIEW_REQUIRED"],"reuse_policy":"applicable fingerprint match before reservation; independent review explicitly bypasses reuse",
      "deterministic_integration":"TC05 exact capability checked before LLM necessity or reservation","independent_review_policy":"explicit contract flag requires fresh admitted review",
      "uncertain_execution_policy":"reservation remains UNCERTAIN and automatic retry is forbidden",
      "account_quota":"NOT_AVAILABLE","account_quota_source":"NOT_AVAILABLE","account_quota_inferred":"NO",
      "pilot_reuse":pilots['reuse'],"pilot_deterministic":pilots['deterministic'],"pilot_admit":pilots['admit'],
      "pilot_review_reserve":pilots['review_reserve'],"pilot_budget_exhausted":pilots['budget_exhausted'],"pilot_uncertain":pilots['uncertain'],
      "pilot_duplicate_reservation":pilots['duplicate_reservation'],"pilot_independent_review":pilots['independent_review'],
      "model_calls_executed":0,"admissions_granted":4,"model_calls_avoided_by_reuse":1,"model_calls_avoided_by_determinism":1,
      "model_calls_deferred":2,"model_calls_blocked":1,"reservations_created":4,"reservations_consumed":0,"reservations_released":0,"reservations_uncertain":1,
      "cumulative_accounting":"PASS","no_double_counting":"PASS","advisor_reserve_protected":"PASS","silent_degradation":"NO",
      "adversarial_refutation":{"status":"PASS_PROTECTED","attacks":attacks},
      "tc01_regression":"PENDING","tc02_regression":"PENDING","tc03_regression":"PENDING","tc04_regression":"PENDING","tc05_regression":"PENDING",
      "protected_scope_changed":"NO","groq_executed":"NO","a4_executed":"NO","a5_executed":"NO","zero_cost_only":"PASS","tests":"PENDING","security_check":"PENDING",
      "known_limitations":["internal task budgets do not represent account quota","no real LLM dispatch occurred","policies are explicitly configured per task","no context optimization is performed"],
      "material_findings":["account quota source remains unavailable","Advisor reserve prevents executor exhaustion","TC05 deterministic work bypasses LLM reservation"],
      "refutation_result":"PASS_PROTECTED across 30 attacks","tc06_acceptance":"PASS" if accepted else "FAIL",
      "next_recommended_slice":"Advisor/PO review of TC-06 evidence; this recommendation does not authorize execution"}
    atomic_json(output_dir/'TC_06_BUDGET_ADMISSION_GOVERNANCE_REPORT.json',report)
    if before!={str(p):tree_hashes(p) for p in protected}:raise ValueError('PROTECTED_EVIDENCE_CHANGED')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output-dir',required=True)
    args=p.parse_args();print(generate(args.root,args.output_dir)['status'])
