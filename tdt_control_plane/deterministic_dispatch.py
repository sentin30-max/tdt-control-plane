"""TC-05 operational dispatch for one proven deterministic capability."""
import json
import time
from dataclasses import dataclass

from .contracts import digest
from .deterministic_preparation import (CONTRACT_VERSION, RULE_SET_VERSION,
    NOT_APPLICABLE, PreparationError, prepare, validate_output)
from .roles import validate_context, validate_result
from .telemetry import observe

EXECUTOR_ID='deterministic-preparation-v1'
ELIGIBLE='ELIGIBLE';NOT_APPLICABLE_CLASS='NOT_APPLICABLE';MATERIAL_BLOCKER='MATERIAL_BLOCKER'

@dataclass(frozen=True)
class Capability:
    executor_id:str=EXECUTOR_ID
    executor_type:str='DETERMINISTIC'
    supported_role:str='CODE_EXECUTOR'
    supported_operation:str='PREPARE_CANDIDATE'
    contract_version:str=CONTRACT_VERSION
    rule_set_version:str=RULE_SET_VERSION
    scope:str='Slice002: Resistance A4 preparation only'
    authority_profile:str='BOUNDED_COMPUTATION'

CAPABILITY=Capability()
REGISTRY={(CAPABILITY.supported_role,CAPABILITY.supported_operation,CAPABILITY.contract_version,CAPABILITY.rule_set_version):CAPABILITY}

def _operation(context):
    return context.get('inputs',{}).get('operation') if isinstance(context,dict) else None

def eligibility(context,contract_version=None,rule_set_version=None):
    """Control Plane classification. Executor metadata cannot add a capability."""
    if not isinstance(context,dict):
        return {'classification':NOT_APPLICABLE_CLASS,'reason':'UNSUPPORTED_CONTEXT_TYPE','capability':None}
    role=context.get('role');operation=_operation(context)
    if role!='CODE_EXECUTOR' or operation!='PREPARE_CANDIDATE':
        return {'classification':NOT_APPLICABLE_CLASS,'reason':'UNSUPPORTED_ROLE_OR_OPERATION','capability':None}
    if context.get('scope')!=CAPABILITY.scope:
        return {'classification':NOT_APPLICABLE_CLASS,'reason':'UNSUPPORTED_SCOPE','capability':None}
    if contract_version!=CONTRACT_VERSION:
        return {'classification':MATERIAL_BLOCKER if contract_version is not None else NOT_APPLICABLE_CLASS,
                'reason':'INCOMPATIBLE_CONTRACT_VERSION' if contract_version is not None else 'NO_SUPPORTED_CONTRACT_CLAIM','capability':None}
    if rule_set_version!=RULE_SET_VERSION:
        return {'classification':MATERIAL_BLOCKER if rule_set_version is not None else NOT_APPLICABLE_CLASS,
                'reason':'UNKNOWN_RULE_VERSION' if rule_set_version is not None else 'NO_SUPPORTED_RULE_SET_CLAIM','capability':None}
    if (role,operation,contract_version,rule_set_version) not in REGISTRY:
        return {'classification':NOT_APPLICABLE_CLASS,'reason':'CAPABILITY_NOT_REGISTERED','capability':None}
    try:
        validate_context(context)
        # prepare is the definitive applicability oracle and validates sources/authority/protection.
        candidate=prepare(context,rule_set_version,contract_version)
        validate_result(candidate,context);validate_output(context,candidate)
    except (PreparationError,ValueError,KeyError,TypeError) as error:
        reason=str(error).split(':')[-1]
        return {'classification':MATERIAL_BLOCKER,'reason':reason,'capability':EXECUTOR_ID}
    return {'classification':ELIGIBLE,'reason':'ALL_APPLICABILITY_GUARDS_PASS','capability':EXECUTOR_ID}

def _blocked(context,reason):
    return {'execution_classification':MATERIAL_BLOCKER,'reason':reason,'selected_executor':None,
            'result':None,'llm_dispatched':False,'model_call_count':0,'automatic_llm_fallback':False,
            'advisor_handoff':'READY','advisor_review_completed':False,'operational_continuation':'STOPPED_FOR_SCOPE',
            'scope':context.get('scope') if isinstance(context,dict) else None,'authoritative':False}

class DeterministicDispatcher:
    def __init__(self,ledger,execute=prepare):
        self.ledger=ledger;self.execute=execute

    def dispatch(self,context,contract_version=None,rule_set_version=None,normal_path_authorized=False):
        decision=eligibility(context,contract_version,rule_set_version)
        if decision['classification']==NOT_APPLICABLE_CLASS:
            return {'execution_classification':NOT_APPLICABLE_CLASS,'reason':decision['reason'],'selected_executor':None,
                    'deterministic_executed':False,'normal_path_selectable':bool(normal_path_authorized),
                    'llm_dispatched':False,'model_call_count':0,'automatic_llm_fallback':False,
                    'advisor_handoff':'READY','advisor_review_completed':False,'authoritative':False}
        if decision['classification']==MATERIAL_BLOCKER:return _blocked(context,decision['reason'])
        try:
            self.ledger.register(context)
            prior=self.ledger.recover(context['execution_id'])
            if prior['result'] is not None:
                validate_result(prior['result'],context);validate_output(context,prior['result'])
                record=self._record(context,prior['result'],'REUSABLE',0,True)
                return record
            self.ledger._event(context['execution_id'],'DETERMINISTIC_EXECUTOR_SELECTED',json.dumps({
                'executor_id':EXECUTOR_ID,'contract_version':CONTRACT_VERSION,'rule_set_version':RULE_SET_VERSION,
                'input_revision':context['input_revision'],'reason':decision['reason']}))
            start=time.perf_counter_ns();result=self.execute(context,RULE_SET_VERSION,CONTRACT_VERSION);elapsed=time.perf_counter_ns()-start
            validate_result(result,context);validate_output(context,result)
            verdict=self.ledger.ingest(context['execution_id'],json.dumps(result),context['input_revision'],context['source_digests'])
            if verdict not in {'ACCEPTED','DUPLICATE_NOOP'}:raise ValueError('VERIFY_INGEST_'+verdict)
            status='ALREADY_COMPLETED' if verdict=='DUPLICATE_NOOP' else 'COMPLETED'
            self.ledger._event(context['execution_id'],'ADVISOR_HANDOFF_READY',digest(result))
            self._observe(context,result,False)
            return self._record(context,result,status,elapsed,False)
        except (PreparationError,ValueError,KeyError,TypeError) as error:
            return _blocked(context,str(error).split(':')[-1])

    def _observe(self,context,result,recovered):
        try:
            attempt=self.ledger.recover(context['execution_id'])['attempts']
            self.ledger.observe(observe(context,result,backend='DeterministicPreparationExecutor',recovered=recovered,
                                        model_dispatched=False,attempt=attempt))
        except Exception as error:
            self.ledger._event(context['execution_id'],'TELEMETRY_FAILED',type(error).__name__)

    def _record(self,context,result,recovery_status,elapsed_ns,recovered):
        return {'execution_classification':ELIGIBLE,'selected_executor':EXECUTOR_ID,'executor_type':'DETERMINISTIC',
          'contract_version':CONTRACT_VERSION,'rule_set_version':RULE_SET_VERSION,'task_id':context['task_id'],
          'context_id':context['context_id'],'execution_id':context['execution_id'],'input_revision':context['input_revision'],
          'result':result,'result_digest':digest(result),'oracles':['validate_result','validate_output'],
          'verify_ingest':'PASS','recovery_status':recovery_status,'recovered':recovered,
          'local_runtime':{'status':'MEASURED','elapsed_ns':elapsed_ns},'llm_dispatched':False,'model_call_count':0,
          'avoided_llm_dispatch':0 if recovered else 1,'historical_proxy_comparator':'8249 estimated tokens',
          'actual_token_savings':'NOT_AVAILABLE','account_quota_savings':'NOT_AVAILABLE',
          'advisor_handoff':'READY','advisor_review_completed':False,'next_operational_dispatch_before_advisor':False,
          'automatic_llm_fallback':False,'authoritative':False}


class ExecutionRouter:
    """Minimal Control Plane router boundary; it never silently invokes normal execution."""
    def __init__(self,deterministic_dispatcher):
        self.deterministic_dispatcher=deterministic_dispatcher

    def route(self,context,contract_version=None,rule_set_version=None,normal_path_authorized=False):
        result=self.deterministic_dispatcher.dispatch(context,contract_version,rule_set_version,normal_path_authorized)
        if result['execution_classification']==NOT_APPLICABLE_CLASS:
            result['router_decision']='NORMAL_PATH_AVAILABLE' if normal_path_authorized else 'NO_AUTHORIZED_PATH'
            result['normal_dispatch_executed']=False
        elif result['execution_classification']==MATERIAL_BLOCKER:
            result['router_decision']='STOP_SCOPE_AND_HANDOFF_ADVISOR'
            result['normal_dispatch_executed']=False
        else:
            result['router_decision']='DETERMINISTIC_EXECUTOR'
            result['normal_dispatch_executed']=False
        return result
