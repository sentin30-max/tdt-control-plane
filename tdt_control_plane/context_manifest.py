"""TC-02 deterministic shadow manifests. Never used to build executor input."""
import json

from .contracts import digest
from .telemetry import serialized_json_bytes

SCHEMA_VERSION=1
POLICY_REF='tc02-context-justification-shadow-v1'
BUILDER_VERSION='1'
NECESSITY={'REQUIRED','CONDITIONAL','UNKNOWN','UNJUSTIFIED','NEEDS_CONTRACT_EVIDENCE'}
TRANSPORT={'INLINE_REQUIRED','REFERENCE_CANDIDATE','DUPLICATED','DERIVABLE','UNKNOWN'}
DEPENDENCIES={'REQUIRES','CONSTRAINS','EVIDENCE_FOR','DERIVED_FROM','SUPERSEDES','INFORMS','PROTECTS','INVALIDATES','AUTHORIZES'}
EXPAND={'/inputs','/inputs/state','/inputs/state/blocker','/inputs/previous_material_result','/inputs/previous_material_result/result'}

BASE_PROTECTIVE={
    'authority':'/authority', 'prohibitions':'/authority/cannot_do',
    'protected_baselines':'/protected', 'acceptance_criteria':'/done_when',
    'advisor_first':'/after_completion', 'scope_limit':'/scope',
}


def _encoded(value):return json.dumps(value).encode('utf-8')


def _unit(path,value,size,kind='VALUE'):
    return {'unit_id':digest({'selector':path,'value':value}), 'source_ref':'execution_context',
            'source_digest':digest(value),'selector':path,'materialization_mode':'INLINE',
            'byte_size':size,'estimated_tokens':(size+3)//4,'authority_class':'CONTEXT',
            'dependency_type':'INFORMS','justification':None,'semantic_necessity':'UNKNOWN',
            'transport_form':'UNKNOWN','confidence_basis':'NO_RULE', 'required_by':[],
            'derived_from':[],'duplicates':[],'resolvable_ref':None,
            'adverse_or_protective':False,'reason_code':'NO_JUSTIFICATION_RULE','kind':kind,
            '_value':value}


def partition_context(context):
    """Partition default JSON serialization exactly, without semantic parsing."""
    units=[]
    def walk(mapping,path,root=False):
        overhead=2
        for index,(key,value) in enumerate(mapping.items()):
            selector=path+'/'+key.replace('~','~0').replace('/','~1')
            prefix=(0 if index==0 else 2)+len(_encoded(key))+2
            if type(value) is dict and selector in EXPAND:
                units.append(_unit(selector+'/@structure',None,prefix+2,'STRUCTURE'))
                walk(value,selector)
            else:
                units.append(_unit(selector,value,prefix+len(_encoded(value))))
        if root:
            units.append(_unit('/@document_structure',None,overhead,'STRUCTURE'))
    walk(context,'',True)
    if sum(u['byte_size'] for u in units)!=serialized_json_bytes(context):
        raise ValueError('CONTEXT_PARTITION_MISMATCH')
    return units


def _set(unit, necessity, transport, dependency, justification, basis, required_by,
         authority_class='CONTEXT', protective=False, reason='JUSTIFIED'):
    unit.update(semantic_necessity=necessity,transport_form=transport,
                dependency_type=dependency,justification=justification,
                confidence_basis=basis,required_by=required_by,
                authority_class=authority_class,adverse_or_protective=protective,
                reason_code=reason)


def _classify(units,context):
    role=context['role'];inputs=context['inputs'];state=inputs.get('state',{})
    final_review=role=='ADVISOR' and type(state.get('verification')) is dict
    required_top={
        '/schema_version':('REQUIRES','context schema'),'/execution_id':('REQUIRES','execution identity'),
        '/task_id':('REQUIRES','task identity'),'/context_id':('DERIVED_FROM','correlation identity'),
        '/input_revision':('REQUIRES','stale-input guard'),'/role':('REQUIRES','role contract'),
        '/scope':('CONSTRAINS','scope boundary'),'/authority':('AUTHORIZES','role authority and prohibitions'),
        '/protected':('PROTECTS','protected baselines'),'/objective':('REQUIRES','task objective'),
        '/source_digests':('EVIDENCE_FOR','source provenance'),'/done_when':('CONSTRAINS','acceptance criteria'),
        '/after_completion':('CONSTRAINS','Advisor-first continuation'),'/authoritative':('CONSTRAINS','non-authority marker')}
    input_rules={
        'state':('REQUIRES','current operational state'),'previous_material_result':('EVIDENCE_FOR','previous material result under review or continuity'),
        'applicable_destinations':('CONSTRAINS','destinations Control Plane may validate'),'requested_artifact':('CONSTRAINS','output contract'),
        'operation':('REQUIRES','bounded operation selector'),'po_authority':('AUTHORIZES','applicable PO authority'),
        'publication':('EVIDENCE_FOR','published-state evidence'),'specification':('REQUIRES','explicit transformation specification'),
        'historical_request':('REQUIRES','explicit transformation/review input'),'historical_input':('REQUIRES','explicit transformation/review input'),
        'source_contract':('CONSTRAINS','active output/authority contract')}
    for unit in units:
        selector=unit['selector']
        if unit['kind']=='STRUCTURE':
            _set(unit,'REQUIRED','INLINE_REQUIRED','REQUIRES','serialization structure required by current schema','SCHEMA_V1',['context_schema'])
            continue
        top='/'+selector.strip('/').split('/')[0]
        if top in required_top:
            dep,why=required_top[top]
            protective=top in {'/authority','/protected','/done_when','/after_completion','/scope'}
            _set(unit,'REQUIRED','INLINE_REQUIRED',dep,why,'ROLE_CONTEXT_SCHEMA_V1',[why],
                 'AUTHORITY' if top=='/authority' else 'PROTECTION' if protective else 'CONTEXT',protective)
        elif selector.startswith('/inputs/'):
            key=selector.split('/')[2]
            if final_review and key in {'historical_request','historical_input','source_contract','specification','publication'}:
                _set(unit,'NEEDS_CONTRACT_EVIDENCE','UNKNOWN','INFORMS',
                     'material was carried forward, but no explicit dependency selector proves inline need for the narrow final review',
                     'PHASE_AND_EXISTING_CONTEXT',['final_review_dependency_contract'],reason='MISSING_DEPENDENCY_EVIDENCE')
            elif key in input_rules:
                dep,why=input_rules[key]
                text=json.dumps(unit['_value']).lower()
                protective=(key in {'po_authority'} or '/blocker' in selector or selector.endswith('/findings')
                            or any(marker in text for marker in ('zero_cost','do not','forbidden','no automatic','unresolved_')))
                _set(unit,'REQUIRED','INLINE_REQUIRED',dep,why,'STRUCTURED_FIELD_RULE_V1',[why],
                     'AUTHORITY' if key=='po_authority' else 'PROTECTION' if protective else 'EVIDENCE',protective)
            else:
                unit['reason_code']='UNKNOWN_INPUT_FIELD'
        if selector=='/context_id':
            body={k:v for k,v in context.items() if k not in {'context_id','execution_id'}}
            if digest(body)==context['context_id']:
                unit.update(transport_form='DERIVABLE',derived_from=['context_without_context_id_and_execution_id'],
                            confidence_basis='roles.make_context digest rule v1',reason_code='DETERMINISTIC_ORACLE_PASS')
    _duplicates(units)
    return units


def _normalized(value):
    if type(value) is str:
        try:return json.loads(value),True
        except (ValueError,TypeError):pass
    return value,False


def _duplicates(units):
    seen=[]
    for unit in units:
        value,parsed=_normalized(unit['_value'])
        for other,other_value,other_parsed in seen:
            composite=(type(value) in {dict,list} and bool(value)) or (type(value) is str and len(value)>64)
            if composite and value==other_value and unit['authority_class']==other['authority_class'] and unit['kind']=='VALUE' and other['kind']=='VALUE':
                kind='STRUCTURAL_DUPLICATE' if parsed!=other_parsed else 'EXACT_DUPLICATE'
                unit.update(transport_form='DUPLICATED',duplicates=[other['unit_id']],
                            confidence_basis=kind,reason_code=kind)
                break
        seen.append((unit,value,parsed))


def _protective(context,units):
    expected=dict(BASE_PROTECTIVE)
    if context['role']=='ADVISOR':expected['permitted_destinations']='/inputs/applicable_destinations'
    raw=json.dumps(context,sort_keys=True)
    if 'zero_cost' in raw.lower():expected['zero_cost_only']='text:zero_cost'
    state=context['inputs'].get('state',{})
    if state.get('blocker'):expected['blocker']='/inputs/state/blocker'
    previous=context['inputs'].get('previous_material_result',{})
    findings=previous.get('result',{}).get('findings') if type(previous) is dict else None
    if findings:expected['adverse_findings']='/inputs/previous_material_result/result/findings'
    represented=[];missing=[]
    def path_exists(selector):
        current=context
        try:
            for part in selector.strip('/').split('/'):
                current=current[part.replace('~1','/').replace('~0','~')]
            return True
        except (KeyError,TypeError):return False
    for name,selector in expected.items():
        present=('text:' in selector and selector.split(':',1)[1].lower() in raw.lower()) or ('text:' not in selector and path_exists(selector))
        (represented if present else missing).append(name)
    return {'expected':sorted(expected),'represented':sorted(represented),'missing':sorted(missing),
            'status':'PASS' if not missing else 'MATERIAL_FINDING'}


def _coverage(units):
    total=sum(u['byte_size'] for u in units)
    justified=[u for u in units if u['semantic_necessity'] in {'REQUIRED','CONDITIONAL'}]
    by_nec={n:sum(u['byte_size'] for u in units if u['semantic_necessity']==n) for n in sorted(NECESSITY)}
    by_transport={n:sum(u['byte_size'] for u in units if u['transport_form']==n) for n in sorted(TRANSPORT)}
    return {'context_bytes':total,'unit_count':len(units),'justified_unit_count':len(justified),
            'unknown_unit_count':sum(u['semantic_necessity']=='UNKNOWN' for u in units),
            'unjustified_unit_count':sum(u['semantic_necessity']=='UNJUSTIFIED' for u in units),
            'needs_contract_evidence_unit_count':sum(u['semantic_necessity']=='NEEDS_CONTRACT_EVIDENCE' for u in units),
            'bytes_by_semantic_necessity':by_nec,'bytes_by_transport_form':by_transport,
            'context_justification_coverage_units':len(justified)/len(units) if units else 1,
            'context_justification_coverage_bytes':sum(u['byte_size'] for u in justified)/total if total else 1,
            'measured_bytes_reduction_potential':sum(u['byte_size'] for u in units if u['transport_form'] in {'DUPLICATED','DERIVABLE','REFERENCE_CANDIDATE'}),
            'estimated_token_reduction_potential':(sum(u['byte_size'] for u in units if u['transport_form'] in {'DUPLICATED','DERIVABLE','REFERENCE_CANDIDATE'})+3)//4,
            'actual_token_savings':None,'account_quota_savings':None}


def validate_dependencies(units):
    ids={u['unit_id'] for u in units};graph={u['unit_id']:[x for x in u['derived_from'] if x in ids] for u in units}
    visiting=set();done=set()
    def visit(node):
        if node in visiting:raise ValueError('CIRCULAR_DEPENDENCY')
        if node in done:return
        visiting.add(node)
        for child in graph[node]:visit(child)
        visiting.remove(node);done.add(node)
    for node in graph:visit(node)


def build_manifest(context, telemetry_ref=None):
    units=_classify(partition_context(context),context);validate_dependencies(units)
    protection=_protective(context,units);coverage=_coverage(units)
    public_units=[]
    for unit in units:
        public_units.append({k:v for k,v in unit.items() if k!='_value'})
    body={'schema_version':SCHEMA_VERSION,'policy_ref':POLICY_REF,'builder_version':BUILDER_VERSION,
          'task_id':context['task_id'],'execution_id':context['execution_id'],'role':context['role'],
          'scope':context['scope'],'context_digest':digest(context),'source_revision':context['input_revision'],
          'telemetry_ref':telemetry_ref,'context_units':public_units,'protective_coverage':protection,
          'coverage':coverage,'shadow':True,'operational':False,'authoritative':False}
    body['manifest_digest']=digest(body)
    return body


def applicable(manifest,context):
    return (manifest.get('context_digest')==digest(context) and
            manifest.get('source_revision')==context.get('input_revision') and
            manifest.get('policy_ref')==POLICY_REF and manifest.get('builder_version')==BUILDER_VERSION)


def derivability_candidate(required_inputs=None, rule_version=None, reconstruct=None, expected=None):
    if not required_inputs or type(rule_version) is not str or not rule_version or not callable(reconstruct):
        return {'eligible':False,'classification':'NEEDS_CONTRACT_EVIDENCE','reason':'deterministic_rule_version_inputs_and_oracle_required'}
    try:actual=reconstruct(required_inputs)
    except Exception:return {'eligible':False,'classification':'NEEDS_CONTRACT_EVIDENCE','reason':'deterministic_reconstruction_failed'}
    passed=actual==expected
    return {'eligible':passed,'classification':'DERIVABLE' if passed else 'NEEDS_CONTRACT_EVIDENCE',
            'reason':'equality_oracle_pass' if passed else 'equality_oracle_failed'}


def reference_candidate(stable_id=None,version=None,digest_value=None,permission=None,fetch_mechanism=None,
                        requested_scope=None,source_scope=None):
    passed=(all(type(v) is str and v for v in (stable_id,version,digest_value,fetch_mechanism,requested_scope,source_scope))
            and len(digest_value)==64 and all(c in '0123456789abcdef' for c in digest_value)
            and permission=='READ_AUTHORIZED' and requested_scope==source_scope)
    return {'eligible':passed,'classification':'REFERENCE_CANDIDATE' if passed else 'NEEDS_CONTRACT_EVIDENCE',
            'reason':'all_resolution_guards_present' if passed else 'stable_identity_version_digest_scope_permission_and_fetch_required'}
