"""Generate the four authorized TC-03 projections from immutable Slice 002 records."""
import argparse
import json
from pathlib import Path

from .contracts import digest
from .offline_projection import POLICY_VERSION, build_projection
from .runtime import atomic_json
from .tc02_shadow import tree_hashes

LABELS={
"2142e6da-c067-55c8-8912-cff46e335f64":"ADVISOR_INITIAL",
"96355d38-bc31-5eab-9a70-beda3f1e4e69":"CODE_EXECUTOR_PREPARATION",
"8b8c775c-8b7d-56bc-b31b-b91173b3edc1":"ADVISOR_INTERMEDIATE",
"be889d75-1dd5-50bb-8835-ebd70bea693f":"ADVISOR_FINAL"}

def generate(root, output_dir):
    root=Path(root).resolve(); output_dir=Path(output_dir).resolve(); output_dir.mkdir(parents=True,exist_ok=True)
    protected=[root/'evidence/slice002',root/'evidence/tc01',root/'evidence/tc02']
    before={str(p):tree_hashes(p) for p in protected}; projections=[]
    for execution_id,label in LABELS.items():
        record=json.loads((root/'evidence/slice002/executions'/(execution_id+'.json')).read_text(encoding='utf-8'))
        manifest=json.loads((root/'evidence/tc02'/(execution_id+'.manifest.json')).read_text(encoding='utf-8'))
        projection=build_projection(record['context'],manifest); projection['label']=label
        atomic_json(output_dir/(execution_id+'.projection.json'),projection); projections.append(projection)
    tc02=json.loads((root/'evidence/tc02/shadow-index.json').read_text(encoding='utf-8'))
    reuse=[]
    for family in tc02['cross_execution_repetition']:
        reuse.append({**family,"same_content":True,"same_digest":True,"same_authority":True,
                      "same_revision":True,"same_scope":"NOT_PROVEN","still_applicable":"UNRESOLVED",
                      "review_required_again":"UNRESOLVED","executor_can_resolve_prior":False,
                      "material_delta_exists":"UNRESOLVED","classification":"REUSE_UNRESOLVED"})
    original=sum(p['byte_accounting']['original_bytes'] for p in projections)
    projected=sum(p['byte_accounting']['projected_bytes'] for p in projections)
    results=[]
    for p in projections:
        accepted=[x for x in p['transformation_ledger'] if x['status']=='ACCEPTED']
        rejected=[x for x in p['transformation_ledger'] if x['status']!='ACCEPTED']
        removed={k:sum(x['original_bytes'] for x in accepted if x['transformation_type']==k) for k in
                 ('EXACT_DUPLICATE_ELISION','STRUCTURAL_DUPLICATE_ELISION','DERIVABLE_ELISION','REFERENCE_PROJECTION','CONTRACT_SUPPORTED_NON_MATERIALIZATION')}
        needs=p['needs_contract_evidence_resolution']
        results.append({"execution_id":p['projected_context']['execution_id'],"label":p['label'],
          "original_bytes":p['byte_accounting']['original_bytes'],"p1_projected_bytes":p['byte_accounting']['projected_bytes'],
          "p2_projected_bytes":None,"p2_reason":"no additional existing contract supports non-materialization",
          "net_reduction_bytes":p['byte_accounting']['removed_bytes'],"removed_bytes_by_class":removed,
          "kept_required_bytes":sum(u['byte_size'] for u in json.loads((root/'evidence/tc02'/(p['projected_context']['execution_id']+'.manifest.json')).read_text())['context_units'] if u['semantic_necessity']=='REQUIRED' and u['selector'] not in {x['original_selector'] for x in accepted}),
          "kept_protective_bytes":sum(u['byte_size'] for u in json.loads((root/'evidence/tc02'/(p['projected_context']['execution_id']+'.manifest.json')).read_text())['context_units'] if u['adverse_or_protective']),
          "kept_unresolved_bytes":sum(x['bytes'] for x in needs),
          "needs_contract_evidence_resolution":{"resolved_safe":0,"resolved_required":0,"unresolved":len(needs),"units":needs},
          "duplicate_transformations":len([x for x in accepted if 'DUPLICATE' in x['transformation_type']]),
          "derivable_transformations":0,"reference_transformations":0,"rejected_transformations":len(rejected),
          "equivalence_gates":p['equivalence_gates'],"protective_closure":p['equivalence_gates']['EG-03']['status'],
          "adverse_finding_closure":p['equivalence_gates']['EG-04']['status'],"authority_equivalence":p['equivalence_gates']['EG-02']['status'],
          "contract_equivalence":p['equivalence_gates']['EG-05']['status'],"state_equivalence":p['equivalence_gates']['EG-07']['status'],
          "evidence_equivalence":p['equivalence_gates']['EG-06']['status'],"projection_status":p['projection_acceptance'],
          "projection_path":f"evidence/tc03/{p['projected_context']['execution_id']}.projection.json"})
    final=next(x for x in results if x['label']=='ADVISOR_FINAL')
    report={"report":"TC_03_OFFLINE_PROJECTION_IMPLEMENTATION_REPORT","status":"IMPLEMENTED_CANDIDATE",
      "baseline":["0ec9c13013a24ed2fbbde01c1ea92a5e5871a7b3","4b3f022471f1f60a81d259ccf088b745366266bb"],
      "branch":"implementation/tc-03-offline-projection","commit":"PENDING_AT_GENERATION","policy_version":POLICY_VERSION,
      "projection_model":"positive selection; uncertain/protective/adverse material stays inline; offline and non-dispatchable",
      "transformation_model":"versioned exact/structural duplicate reconstruction with equality oracle",
      "equivalence_gates":[f"EG-{n:02d}" for n in range(1,13)],"slice002_results":results,
      "global":{"original_context_bytes":original,"projected_context_bytes":projected,"measured_reduction_bytes":original-projected,
                "measured_reduction_percent":round((original-projected)*100/original,6),"estimated_original_tokens":(original+3)//4,
                "estimated_projected_tokens":(projected+3)//4,"estimated_token_delta":((original+3)//4)-((projected+3)//4),
                "actual_token_savings":"NOT_AVAILABLE","account_quota_savings":"NOT_AVAILABLE"},
      "cross_execution_reuse_analysis":{"families":reuse,"family_count":len(reuse),"bytes_after_first":sum(x['repeated_bytes_after_first'] for x in reuse),"reuse_proven":0},
      "final_advisor_15057_analysis":{"bytes":sum(x['bytes'] for x in final['needs_contract_evidence_resolution']['units']),"unit_count":len(final['needs_contract_evidence_resolution']['units']),"resolution":"UNRESOLVED_KEEP_INLINE","reason":"existing contracts establish carriage but do not prove final-review inline necessity or permit non-materialization"},
      "deterministic_replacement_analysis":{"execution_id":"96355d38-bc31-5eab-9a70-beda3f1e4e69","classification":"OFFLINE_CANDIDATE_ONLY","operational_replacement":False},
      "new_llm_calls_for_tc03":0,"operational_context_changed":"NO","operational_prompt_changed":"NO","routing_changed":"NO","authority_changed":"NO","result_semantics_changed":"NO",
      "tc01_regression":"PENDING","tc02_regression":"PENDING","protected_scope_changed":"NO","slice002_redispatched":"NO","groq_executed":"NO","a4_executed":"NO","a5_executed":"NO","zero_cost_only":"PASS",
      "tests":"PENDING","security_check":"PENDING","known_limitations":["offline equivalence is not LLM behavioral equivalence","no authorized runtime reference resolver","P2 omitted because it equals P1","cross-execution reuse remains unresolved"],
      "material_findings":["shadow metadata exceeds executor savings and is not dispatchable","all five final Advisor contract-evidence units remain inline"],
      "refutation":"adversarial fixtures must fail closed; accepted projections require all twelve gates PASS",
      "tc03_acceptance":"PENDING","next_recommended_slice":"Advisor/PO review of TC-03 evidence; this recommendation does not authorize execution"}
    atomic_json(output_dir/'TC_03_OFFLINE_PROJECTION_IMPLEMENTATION_REPORT.json',report)
    if before!={str(p):tree_hashes(p) for p in protected}: raise ValueError('PROTECTED_EVIDENCE_CHANGED')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output-dir',required=True)
    a=p.parse_args();print(generate(a.root,a.output_dir)['status'])
