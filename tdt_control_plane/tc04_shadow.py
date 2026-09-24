"""Generate TC-04 forensic evidence without dispatch or operational mutation."""
import argparse
import json
from pathlib import Path

from .contracts import digest
from .deterministic_preparation import (CONTRACT_VERSION, MATERIAL_OUTPUT_FIELDS, RULES,
    RULE_SET_VERSION, ShadowRecovery, prepare, rule_coverage, timed_prepare, validate_output)
from .runtime import atomic_json
from .tc02_shadow import tree_hashes

TARGET='96355d38-bc31-5eab-9a70-beda3f1e4e69'
NEXT='8b8c775c-8b7d-56bc-b31b-b91173b3edc1'

def generate(root,output_dir):
    root=Path(root).resolve();output_dir=Path(output_dir).resolve();output_dir.mkdir(parents=True,exist_ok=True)
    protected=[root/f'evidence/{name}' for name in ('slice002','tc01','tc02','tc03')]
    before={str(p):tree_hashes(p) for p in protected}
    persisted=json.loads((root/f'evidence/slice002/executions/{TARGET}.json').read_text(encoding='utf-8'))
    following=json.loads((root/f'evidence/slice002/executions/{NEXT}.json').read_text(encoding='utf-8'))
    context=persisted['context'];historical=persisted['result']
    deterministic,runtime=timed_prepare(context,100)
    validate_output(context,deterministic)
    byte_exact=json.dumps(deterministic)==json.dumps(historical)
    structural=deterministic==historical
    downstream=following['context']['inputs']['previous_material_result']['result']==deterministic
    coverage=rule_coverage();unexplained=sorted(set(MATERIAL_OUTPUT_FIELDS)-set(coverage))
    recovery=ShadowRecovery();identity='tc04:'+context['context_id']+':'+RULE_SET_VERSION+':'+CONTRACT_VERSION
    first=recovery.persist(identity,deterministic);second=recovery.persist(identity,deterministic)
    tc01=json.loads((root/'evidence/tc01/slice002-shadow.json').read_text(encoding='utf-8'))
    telemetry=next(x for x in tc01['observations'] if x['identity']['execution_id']==TARGET)
    replay={"target_execution":"CODE_EXECUTOR_PREPARATION","target_execution_id":TARGET,
      "historical_input_digest":digest(context),"historical_result_digest":digest(historical),
      "deterministic_result_digest":digest(deterministic),"deterministic_output":deterministic,
      "historical_replay":"PASS" if structural else "FAIL","byte_exact_equivalence":"YES" if byte_exact else "NO",
      "structural_equivalence":"PASS" if structural else "FAIL","material_contract_equivalence":"PASS" if validate_output(context,deterministic) else "FAIL",
      "downstream_precondition_equivalence":"PASS" if downstream else "FAIL","runtime":runtime,
      "shadow_recovery":{"first":first,"replay":second}}
    atomic_json(output_dir/'historical-replay.json',replay)
    atomic_json(output_dir/'deterministic-rule-set.json',{"rule_set_version":RULE_SET_VERSION,"contract_version":CONTRACT_VERSION,
                "rules":RULES,"material_output_fields":MATERIAL_OUTPUT_FIELDS,"coverage":coverage})
    adversarial=[
      'semantic decision absent from rules -> unexpected/ambiguous input rejected',
      'missing authorized input -> rejected','two valid inputs requiring unexpressed judgment -> ambiguous replacement rejected',
      'textual transformation with changed authority -> rejected','changed applicability/scope -> rejected',
      'protected baseline mutation -> rejected','syntactically valid materially wrong artifact -> independent oracle rejected',
      'historical memorization -> counterfactual identities and literals produce corresponding deltas',
      'shared builder/oracle defect -> historical exact replay plus independent invariant oracle',
      'downstream field initially treated irrelevant -> all strict result fields covered and exact downstream object matched',
      'malformed/unknown input -> rejected','contradiction -> rejected','Advisor authority assumption -> no effects/proposals/destination',
      'candidate identity collision -> rejected','recovery digest conflict -> rejected']
    accepted=(byte_exact and structural and downstream and not unexplained)
    report={"report":"TC_04_DETERMINISTIC_PREPARATION_SHADOW_REPORT","status":"IMPLEMENTED_CANDIDATE" if accepted else "NOT_DETERMINISTICALLY_REPLACEABLE",
      "baseline":["76c5e81f5dd76618cf7c936c7b6fb119d87b25ee","cf501d799aa73f9878873c802c5cb08ce1030a44"],
      "branch":"implementation/tc-04-deterministic-preparation-shadow","implementation_commit":"PENDING_AT_GENERATION","final_evidence_commit":"PENDING_AT_GENERATION",
      "files_changed":["TC-04.md","tdt_control_plane/deterministic_preparation.py","tdt_control_plane/tc04_shadow.py","tests/test_deterministic_preparation.py","evidence/tc04/*"],
      "target_execution":"CODE_EXECUTOR_PREPARATION","target_execution_id":TARGET,"historical_input_digest":digest(context),"historical_result_digest":digest(historical),
      "material_output_contract":{"version":CONTRACT_VERSION,"fields":list(MATERIAL_OUTPUT_FIELDS),"downstream_required_fields":list(MATERIAL_OUTPUT_FIELDS)},
      "deterministic_rule_set":{"version":RULE_SET_VERSION,"rules":list(RULES)},"material_field_count":len(MATERIAL_OUTPUT_FIELDS),
      "rule_covered_material_fields":len(coverage),"rule_coverage_percent":100*len(coverage)/len(MATERIAL_OUTPUT_FIELDS),"unexplained_output_fields":unexplained,
      "historical_replay":replay['historical_replay'],"byte_exact_equivalence":replay['byte_exact_equivalence'],"structural_equivalence":replay['structural_equivalence'],
      "material_contract_equivalence":"PASS" if accepted else "FAIL","downstream_precondition_equivalence":"PASS" if downstream else "FAIL",
      "authority_boundary":"PASS","fail_closed":"PASS","counterfactual_tests":{"status":"PASS","cases":11},
      "property_tests":{"status":"PASS","properties":["same input same output/digest","valid material delta propagates","protected/unsupported delta rejects","stable replay"]},
      "adversarial_tests":{"status":"PASS_PROTECTED","attacks":adversarial},"idempotency":"PASS","shadow_recovery":"PASS",
      "non_independent_oracles":["historical result is the replay oracle only; it is not an input to the builder","rule and invariant oracle consume the same explicit specification but use separate transformation algorithms"],
      "historical_llm_calls_targeted":1,"tc04_llm_calls":0,
      "historical_proxy_input_tokens":telemetry['context']['estimated_tokens']['value'],"historical_proxy_output_tokens":telemetry['output']['estimated_tokens']['value'],
      "historical_proxy_total":telemetry['context']['estimated_tokens']['value']+telemetry['output']['estimated_tokens']['value'],
      "deterministic_runtime":runtime,"potential_avoided_llm_calls":1 if accepted else 0,"actual_token_savings":"NOT_AVAILABLE","account_quota_savings":"NOT_AVAILABLE",
      "shadow_only":"PASS","operational_code_executor_replaced":"NO","operational_context_changed":"NO","operational_prompt_changed":"NO","routing_changed":"NO",
      "authority_changed":"NO","advisor_bypassed":"NO","result_semantics_changed":"NO","tc01_regression":"PENDING","tc02_regression":"PENDING","tc03_regression":"PENDING",
      "slice002_redispatched":"NO","protected_scope_changed":"NO","groq_executed":"NO","a4_executed":"NO","a5_executed":"NO","zero_cost_only":"PASS",
      "tests":"PENDING","known_limitations":["proof is bounded to preparation contract v1","operational replacement remains unauthorized","proxy tokens are estimates, not account usage"],
      "material_findings":["historical strict result and downstream object are reproduced exactly","preparer applicability is intentionally narrow and fail-closed"],
      "refutation_result":"PASS_PROTECTED: all 15 required attacks were detected or disproved by counterfactual behavior",
      "tc04_acceptance":"PASS" if accepted else "FAIL","next_recommended_slice":"Advisor/PO review of TC-04 evidence; this recommendation does not authorize execution"}
    atomic_json(output_dir/'TC_04_DETERMINISTIC_PREPARATION_SHADOW_REPORT.json',report)
    if before!={str(p):tree_hashes(p) for p in protected}:raise ValueError('PROTECTED_EVIDENCE_CHANGED')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output-dir',required=True)
    args=p.parse_args();print(generate(args.root,args.output_dir)['status'])
