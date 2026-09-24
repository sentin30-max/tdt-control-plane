"""TC-04 side-effect-free shadow preparer for versioned literal transformations."""
import copy
import json
import time

from .contracts import digest

RULE_SET_VERSION="tc04-preparation-rules-v1"
CONTRACT_VERSION="slice002-preparation-contract-v1"
NOT_APPLICABLE="DETERMINISTIC_PREPARATION_NOT_APPLICABLE"

REQUEST_FIELDS={
 'schema_version','request_id','unit','evaluated_baseline','result_directory','a3_instance_id','a4_instance_id',
 'a4_independent_instance_id','a1_state','a2_state','audit_intensity','a3_assignee','a4_assignee',
 'a3_independence_required','a4_independence_required','zero_cost_only','provider','model','runner','resolver',
 'resolver_version','evidence_manifest','a1_input','a2_input','a3_input','a4_input','a5_input_schema','claims',
 'limits','max_output_tokens_per_stage','provider_tpm_limit','token_safety_margin','min_seconds_between_stages',
 'negative_findings_preservation','baseline_guards','a4_justification_contract','permitted_stages'}
REQUEST_OUTPUT_ORDER=(
 'schema_version','request_id','unit','evaluated_baseline','result_directory','a3_instance_id','a4_instance_id',
 'a4_independent_instance_id','a1_state','a2_state','audit_intensity','a3_assignee','a4_assignee',
 'a3_independence_required','a4_independence_required','zero_cost_only','provider','model','runner','resolver',
 'resolver_version','evidence_manifest','a1_input','a2_input','a3_input','a4_input','a5_input_schema','claims',
 'limits','max_output_tokens_per_stage','provider_tpm_limit','token_safety_margin','min_seconds_between_stages',
 'negative_findings_preservation','baseline_guards','a4_justification_contract','permitted_stages','refutation_validity_version')

MATERIAL_OUTPUT_FIELDS=(
 'artifact','context_digest','context_id','effects','evidence_refs','execution_id','findings','input_revision',
 'next_destination','outcome','proposals','protected_scope_touched','rationale','role','task_id')

RULES=(
 {'rule_id':'R-01','rule_version':'1','input_selectors':['/inputs/historical_request','/inputs/specification/request_updates'],
  'output_selector':'/artifact/request','rule_type':'FIELD_PROJECTION','authority_source':'/inputs/po_authority',
  'contract_source':'/inputs/specification','preconditions':'schema and exact update set valid','transformation':'copy then update declared fields','failure_mode':NOT_APPLICABLE,'oracle':'unchanged-field and exact-update comparison'},
 {'rule_id':'R-02','rule_version':'1','input_selectors':['/inputs/historical_input','/inputs/specification/input_literal_replacements'],
  'output_selector':'/artifact/input_text','rule_type':'LITERAL_SUBSTITUTION','authority_source':'/inputs/po_authority',
  'contract_source':'/inputs/specification','preconditions':'each old literal occurs exactly once','transformation':'ordered exact replacement','failure_mode':NOT_APPLICABLE,'oracle':'independent split/join replay and preservation checks'},
 {'rule_id':'R-03','rule_version':'1','input_selectors':['/task_id','/execution_id','/context_id','/input_revision'],
  'output_selector':'/identity_fields','rule_type':'EXACT_COPY','authority_source':'ExecutionContext schema',
  'contract_source':'ExecutionResult schema','preconditions':'valid bound context identity','transformation':'copy identity and digest context','failure_mode':NOT_APPLICABLE,'oracle':'strict identity comparison'},
 {'rule_id':'R-04','rule_version':'1','input_selectors':['/role','/inputs/operation','/inputs/specification'],
  'output_selector':'/status_fields','rule_type':'VERSIONED_TEMPLATE','authority_source':'bounded computation authority',
  'contract_source':'ExecutionResult schema','preconditions':'bounded deterministic preparation only','transformation':'emit fixed non-routing result facts','failure_mode':NOT_APPLICABLE,'oracle':'strict allowlist and no effects/destination'},
)

class PreparationError(ValueError): pass

def _fail(code): raise PreparationError(f"{NOT_APPLICABLE}:{code}")

def _validate(context, rule_version, contract_version):
    if rule_version!=RULE_SET_VERSION:_fail('UNKNOWN_RULE_VERSION')
    if contract_version!=CONTRACT_VERSION:_fail('INCOMPATIBLE_CONTRACT_VERSION')
    required={'schema_version','task_id','execution_id','context_id','input_revision','role','scope','authority','protected','inputs'}
    if not required.issubset(context) or context['schema_version']!=1:_fail('UNEXPECTED_SCHEMA')
    if context['role']!='CODE_EXECUTOR' or context['scope']!='Slice002: Resistance A4 preparation only':_fail('UNSUPPORTED_ROLE_OR_SCOPE')
    if not isinstance(context['input_revision'],str) or len(context['input_revision'])!=64:_fail('INCOMPATIBLE_REVISION')
    body={k:v for k,v in context.items() if k not in {'context_id','execution_id'}}
    if digest(body)!=context['context_id']:_fail('CONTEXT_IDENTITY_MISMATCH')
    authority=context['authority']
    if authority.get('can_do')!=['bounded_computation'] or set(authority.get('cannot_do',()))!={'product_decision','self_approval','mutate_authority','modify_protected','spend'} or authority.get('tools')!=[]:
        _fail('AUTHORITY_BOUNDARY_MISMATCH')
    inputs=context['inputs']; needed={'historical_request','historical_input','specification','operation','po_authority'}
    if not needed.issubset(inputs):_fail('MISSING_REQUIRED_INPUT')
    if inputs['operation']!='PREPARE_CANDIDATE':_fail('UNSUPPORTED_OPERATION')
    spec=inputs['specification']; request=inputs['historical_request']; text=inputs['historical_input']
    if not isinstance(spec,dict) or not isinstance(request,dict) or not isinstance(text,str):_fail('MALFORMED_INPUT')
    if spec.get('versions')!={'a4_resolver':'1','refutation_validity':'1'}:_fail('INCOMPATIBLE_CONTRACT_VERSION')
    if set(spec.get('request_updates',{}))!={'a3_instance_id','a4_assignee','a4_independent_instance_id','a4_input','a4_instance_id','refutation_validity_version','request_id','result_directory'}:
        _fail('AMBIGUOUS_UPDATE_SET')
    if set(request)!=REQUEST_FIELDS:_fail('UNEXPECTED_REQUEST_FIELD')
    if request.get('schema_version')!='2' or request.get('permitted_stages')!=['A4']:_fail('UNEXPECTED_REQUEST_SCHEMA')
    for key,value in spec['request_updates'].items():
        if key in request and request[key]==value:_fail('CANDIDATE_IDENTITY_COLLISION')
    baseline=request.get('evaluated_baseline')
    if not baseline or not any(baseline in str(x) for x in context['protected']):_fail('PROTECTED_BASELINE_MISMATCH')
    if context.get('source_digests',{}).get('specification')!=digest(spec):_fail('SPECIFICATION_DIGEST_MISMATCH')
    replacements=spec.get('input_literal_replacements')
    if not isinstance(replacements,list) or len(replacements)!=4:_fail('AMBIGUOUS_REPLACEMENTS')
    olds=[]
    for pair in replacements:
        if not isinstance(pair,list) or len(pair)!=2 or not all(isinstance(x,str) for x in pair):_fail('MALFORMED_REPLACEMENT')
        old,new=pair
        if not old or old in olds or old==new or text.count(old)!=1:_fail('UNRESOLVED_SEMANTIC_CHOICE')
        olds.append(old)
    prohibited=' '.join(spec.get('prohibited',[])).lower()
    if not all(x in prohibited for x in ('groq','a4 execution','a5 execution','source modification')):_fail('PROHIBITIONS_MISSING')
    if inputs.get('state',{}).get('blocker') is not None or inputs.get('specification_gap') not in (None,):_fail('MATERIAL_CONTRADICTION')
    return request,text,spec

def prepare(context, rule_version=RULE_SET_VERSION, contract_version=CONTRACT_VERSION):
    """Pure transformation. It never dispatches, routes, writes, or calls a provider."""
    request,text,spec=_validate(context,rule_version,contract_version)
    values=copy.deepcopy(request);values.update(copy.deepcopy(spec['request_updates']))
    resulting_request={key:values[key] for key in REQUEST_OUTPUT_ORDER}
    guard_order=('modify_evaluated_code','reopen_support_or_d6','rerun_consumed_tests','redesign_resistance','execute_a5_before_a3_a4')
    resulting_request['baseline_guards']={key:values['baseline_guards'][key] for key in guard_order}
    resulting_text=text
    for old,new in spec['input_literal_replacements']: resulting_text=resulting_text.replace(old,new)
    artifact={'request':resulting_request,'input_text':resulting_text}
    result={
      'artifact':json.dumps(artifact,separators=(',',':')),
      'context_digest':digest(context),'context_id':context['context_id'],'effects':[],
      'evidence_refs':['historical_request','historical_input','specification'],'execution_id':context['execution_id'],
      'findings':['Completed the bounded literal transformation; no runtime validation, materialization or token preflight was performed.'],
      'input_revision':context['input_revision'],'next_destination':'NONE','outcome':'SUCCEEDED','proposals':[],
      'protected_scope_touched':[],
      'rationale':'Applied the eight supplied request updates and four literal input replacements using only supplied data, preserving all other fields and input characters, including the trailing newline.',
      'role':'CODE_EXECUTOR','task_id':context['task_id']}
    validate_output(context,result)
    return result

def validate_output(context,result):
    """Independent invariant oracle; it does not call prepare()."""
    if set(result)!=set(MATERIAL_OUTPUT_FIELDS):_fail('OUTPUT_CONTRACT_VIOLATION')
    if result['effects'] or result['proposals'] or result['protected_scope_touched'] or result['next_destination']!='NONE':_fail('AUTHORITY_ESCALATION')
    for key in ('task_id','execution_id','context_id','input_revision','role'):
        if result[key]!=context[key]:_fail('OUTPUT_IDENTITY_MISMATCH')
    if result['context_digest']!=digest(context):_fail('OUTPUT_CONTEXT_DIGEST_MISMATCH')
    try:artifact=json.loads(result['artifact'])
    except (ValueError,TypeError):_fail('MALFORMED_OUTPUT_ARTIFACT')
    if set(artifact)!={'request','input_text'}:_fail('OUTPUT_ARTIFACT_SCHEMA')
    original=context['inputs']['historical_request']; updates=context['inputs']['specification']['request_updates']
    if set(artifact['request'])!=set(original)|set(updates):_fail('REQUEST_FIELD_LOSS')
    for key,value in original.items():
        expected=updates.get(key,value)
        if artifact['request'].get(key)!=expected:_fail('REQUEST_TRANSFORMATION_ORACLE_FAILED')
    expected=context['inputs']['historical_input']
    for old,new in context['inputs']['specification']['input_literal_replacements']:
        pieces=expected.split(old)
        if len(pieces)!=2:_fail('INPUT_TRANSFORMATION_ORACLE_FAILED')
        expected=new.join(pieces)
    if artifact['input_text']!=expected:_fail('INPUT_TRANSFORMATION_ORACLE_FAILED')
    return True

def rule_coverage():
    mapping={
      'artifact':['R-01','R-02'],'context_digest':['R-03'],'context_id':['R-03'],'execution_id':['R-03'],
      'input_revision':['R-03'],'role':['R-03'],'task_id':['R-03'],
      'effects':['R-04'],'evidence_refs':['R-04'],'findings':['R-04'],'next_destination':['R-04'],
      'outcome':['R-04'],'proposals':['R-04'],'protected_scope_touched':['R-04'],'rationale':['R-04']}
    return mapping

class ShadowRecovery:
    def __init__(self):self._records={}
    def persist(self,identity,result):
        result_digest=digest(result)
        if identity in self._records:
            if self._records[identity]!=result_digest:_fail('RECOVERY_DIGEST_CONTRADICTION')
            return {'status':'NO_NEW_EFFECT','result_digest':result_digest}
        self._records[identity]=result_digest
        return {'status':'PERSISTED_SHADOW','result_digest':result_digest}

def timed_prepare(context,iterations=10):
    start=time.perf_counter_ns();outputs=[prepare(context) for _ in range(iterations)]
    elapsed=time.perf_counter_ns()-start
    if len({digest(x) for x in outputs})!=1:_fail('IDEMPOTENCY_FAILURE')
    return outputs[0],{'iterations':iterations,'elapsed_ns':elapsed,'mean_ns':elapsed//iterations,'classification':'LOCAL_MEASURED'}
