"""TC-06 deterministic pre-LLM admission and reservation governance."""
import json
from dataclasses import dataclass
from uuid import uuid5, NAMESPACE_URL

from .contracts import digest
from .deterministic_dispatch import (ELIGIBLE, MATERIAL_BLOCKER, DeterministicDispatcher,
    eligibility as deterministic_eligibility)
from .roles import validate_context
from .telemetry import serialized_json_bytes

POLICY_VERSION='tc06-budget-admission-v1'
FINGERPRINT_VERSION='material-reasoning-fingerprint-v1'
DECISIONS={'ADMIT','DEFER','BLOCK','REVIEW_REQUIRED'}
NECESSITIES={'SEMANTIC_REVIEW_REQUIRED','OPEN_ENDED_ANALYSIS','INDEPENDENT_REVIEW_REQUIRED',
             'UNRESOLVED_INTERPRETATION_WITHIN_AUTHORITY','GENERATIVE_SYNTHESIS_REQUIRED'}
RESERVATION_STATES={'RESERVED','DISPATCHING','CONSUMED','RELEASED','UNCERTAIN'}

@dataclass(frozen=True)
class BudgetPolicy:
    task_id:str
    max_model_calls:int
    estimated_token_ceiling:int
    review_reserve_calls:int
    review_reserve_tokens:int
    role_allocations:dict
    version:str=POLICY_VERSION
    zero_cost_only:bool=True

    def validate(self):
        values=(self.max_model_calls,self.estimated_token_ceiling,self.review_reserve_calls,self.review_reserve_tokens)
        if any(type(v) is not int or v<0 for v in values) or self.review_reserve_calls>self.max_model_calls or self.review_reserve_tokens>self.estimated_token_ceiling:
            raise ValueError('BUDGET_POLICY_VALUES')
        if self.version!=POLICY_VERSION or self.zero_cost_only is not True:raise ValueError('BUDGET_POLICY_VERSION_OR_COST')
        if not isinstance(self.role_allocations,dict) or not self.role_allocations:raise ValueError('ROLE_ALLOCATIONS')
        calls=tokens=0
        for role,allocation in self.role_allocations.items():
            if set(allocation)!={'max_model_calls','estimated_token_ceiling'} or any(type(v) is not int or v<0 for v in allocation.values()):
                raise ValueError('ROLE_ALLOCATION_VALUES')
            calls+=allocation['max_model_calls'];tokens+=allocation['estimated_token_ceiling']
        if calls>self.max_model_calls or tokens>self.estimated_token_ceiling:raise ValueError('BUDGET_DOUBLE_COUNT_OR_OVERALLOCATION')
        return self

def material_fingerprint(context):
    """Execution identity is excluded; authority, blockers and all evidence remain included."""
    validate_context(context)
    material={k:context[k] for k in ('task_id','input_revision','role','scope','authority','protected','objective','inputs','source_digests','done_when','after_completion')}
    return digest({'version':FINGERPRINT_VERSION,'material':material})

class AdmissionGate:
    def __init__(self,ledger,deterministic_dispatcher=None):
        self.ledger=ledger;self.deterministic_dispatcher=deterministic_dispatcher
        self.ledger.db.executescript('''
        CREATE TABLE IF NOT EXISTS budget_policies(task_id TEXT PRIMARY KEY, policy TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reservations(
          reservation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, role TEXT NOT NULL, execution_id TEXT UNIQUE NOT NULL,
          policy_version TEXT NOT NULL, model_calls INTEGER NOT NULL, context_tokens INTEGER NOT NULL,
          output_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL, reason TEXT NOT NULL,
          state_digest TEXT NOT NULL, status TEXT NOT NULL, measured_tokens INTEGER);
        CREATE TABLE IF NOT EXISTS reusable_reasoning(
          fingerprint TEXT NOT NULL, result_digest TEXT NOT NULL, applicable INTEGER NOT NULL, independent INTEGER NOT NULL,
          PRIMARY KEY(fingerprint,result_digest));
        CREATE TABLE IF NOT EXISTS admissions(
          seq INTEGER PRIMARY KEY, task_id TEXT, execution_id TEXT, decision TEXT NOT NULL, reason TEXT NOT NULL, record TEXT NOT NULL);
        ''')

    def configure(self,policy):
        policy.validate();raw=json.dumps(policy.__dict__,sort_keys=True)
        with self.ledger.db:self.ledger.db.execute('INSERT OR REPLACE INTO budget_policies VALUES(?,?)',(policy.task_id,raw))

    def remember_reusable(self,context,result_digest,independent=False):
        fp=material_fingerprint(context)
        with self.ledger.db:self.ledger.db.execute('INSERT OR REPLACE INTO reusable_reasoning VALUES(?,?,1,?)',(fp,result_digest,1 if independent else 0))
        return fp

    def _policy(self,task_id):
        row=self.ledger.db.execute('SELECT policy FROM budget_policies WHERE task_id=?',(task_id,)).fetchone()
        return BudgetPolicy(**json.loads(row[0])).validate() if row else None

    def _usage(self,task_id,role=None):
        clause='task_id=?';args=[task_id]
        if role is not None:clause+=' AND role=?';args.append(role)
        rows=self.ledger.db.execute(f'SELECT status,model_calls,total_tokens,measured_tokens FROM reservations WHERE {clause}',args).fetchall()
        active=[r for r in rows if r[0] in {'RESERVED','DISPATCHING','CONSUMED','UNCERTAIN'}]
        return {'model_calls':sum(r[1] for r in active),'estimated_tokens':sum(r[2] for r in active),
                'measured_tokens':sum(r[3] for r in rows if r[0]=='CONSUMED' and r[3] is not None),
                'measured_complete':all(r[3] is not None for r in rows if r[0]=='CONSUMED'),
                'reserved':sum(r[0]=='RESERVED' for r in rows),'consumed':sum(r[0]=='CONSUMED' for r in rows),
                'dispatching':sum(r[0]=='DISPATCHING' for r in rows),'released':sum(r[0]=='RELEASED' for r in rows),'uncertain':sum(r[0]=='UNCERTAIN' for r in rows)}

    def _record(self,context,decision,reason,**extra):
        record={'decision':decision,'reason':reason,'task_id':context.get('task_id'),'execution_id':context.get('execution_id'),
                'llm_dispatch_authorized':decision=='ADMIT','llm_dispatched':False,'account_quota':{'status':'NOT_AVAILABLE','value':None,'source':'NOT_CONNECTED'},
                'paid_fallback':False,'silent_context_degradation':False,'silent_output_degradation':False,**extra}
        with self.ledger.db:
            self.ledger.db.execute('INSERT INTO admissions(task_id,execution_id,decision,reason,record) VALUES(?,?,?,?,?)',
                                   (context.get('task_id'),context.get('execution_id'),decision,reason,json.dumps(record,sort_keys=True)))
            if context.get('execution_id'):self.ledger._event(context['execution_id'],'ADMISSION_'+decision,reason)
        return record

    def evaluate(self,context,*,why_llm_required=None,execution_purpose=None,expected_material_output=None,
                 output_token_budget=None,contract_version=None,rule_set_version=None,independent_review=False):
        try:validate_context(context)
        except (ValueError,TypeError,KeyError) as error:return self._record(context,'BLOCK',str(error))
        # Existing execution result precedes all resource work.
        try:
            existing=self.ledger.recover(context['execution_id'])
            if existing['result_digest']:
                return self._record(context,'BLOCK','REUSE_SELECTED',route='REUSE',result_digest=existing['result_digest'],reservation=None)
        except ValueError:pass
        fp=material_fingerprint(context)
        reusable=self.ledger.db.execute('SELECT result_digest,independent FROM reusable_reasoning WHERE fingerprint=? AND applicable=1',(fp,)).fetchone()
        if reusable and not independent_review:
            return self._record(context,'BLOCK','REUSE_SELECTED',route='REUSE',result_digest=reusable[0],reservation=None,
                                material_reasoning_fingerprint=fp)
        deterministic=deterministic_eligibility(context,contract_version,rule_set_version)
        if deterministic['classification']==ELIGIBLE:
            if self.deterministic_dispatcher is None:return self._record(context,'BLOCK','DETERMINISTIC_EXECUTOR_UNAVAILABLE')
            result=self.deterministic_dispatcher.dispatch(context,contract_version,rule_set_version)
            return self._record(context,'BLOCK','DETERMINISTIC_SELECTED',route='DETERMINISTIC',deterministic_result=result,reservation=None,
                                material_reasoning_fingerprint=fp)
        if deterministic['classification']==MATERIAL_BLOCKER:
            return self._record(context,'BLOCK','DETERMINISTIC_MATERIAL_BLOCKER:'+deterministic['reason'],reservation=None)
        if why_llm_required not in NECESSITIES:
            return self._record(context,'BLOCK','LLM_NECESSITY_NOT_ESTABLISHED',reservation=None)
        if not execution_purpose or not expected_material_output:
            return self._record(context,'REVIEW_REQUIRED','EXECUTION_VALUE_JUSTIFICATION_REQUIRED',reservation=None)
        if type(output_token_budget) is not int or output_token_budget<=0:
            return self._record(context,'BLOCK','OUTPUT_BUDGET_NOT_CONFIGURED',reservation=None)
        policy=self._policy(context['task_id'])
        if policy is None:return self._record(context,'REVIEW_REQUIRED','TASK_BUDGET_NOT_CONFIGURED',reservation=None)
        context_bytes=serialized_json_bytes(context);context_tokens=(context_bytes+3)//4;total=context_tokens+output_token_budget
        estimate={'context_bytes':{'value':context_bytes,'status':'MEASURED','method':'utf8_bytes_json_dumps_default'},
                  'context_tokens':{'value':context_tokens,'status':'ESTIMATED','method':'ceil_utf8_bytes_div_4_proxy','version':'1'},
                  'output_tokens':{'value':output_token_budget,'status':'ESTIMATED','method':'explicit_contract_or_task_policy'},
                  'total_tokens':{'value':total,'status':'ESTIMATED','method':'non_overlapping_context_plus_output'}}
        role=context['role'];allocation=policy.role_allocations.get(role)
        if allocation is None:return self._record(context,'BLOCK','ROLE_ALLOCATION_MISSING',resource_estimate=estimate,reservation=None)
        self.ledger.db.execute('BEGIN IMMEDIATE')
        try:
            duplicate=self.ledger.db.execute("SELECT reservation_id,status FROM reservations WHERE execution_id=?",(context['execution_id'],)).fetchone()
            if duplicate and duplicate[1] in {'RESERVED','DISPATCHING','CONSUMED','UNCERTAIN'}:
                decision='DEFER' if duplicate[1]=='UNCERTAIN' else 'BLOCK';reason='UNCERTAIN_NO_AUTOMATIC_RETRY' if duplicate[1]=='UNCERTAIN' else 'DUPLICATE_RESERVATION'
                self.ledger.db.execute('ROLLBACK');return self._record(context,decision,reason,reservation_id=duplicate[0],reservation=None)
            task=self._usage(context['task_id']);role_use=self._usage(context['task_id'],role)
            if task['model_calls']+1>policy.max_model_calls or task['estimated_tokens']+total>policy.estimated_token_ceiling:
                self.ledger.db.execute('ROLLBACK');return self._record(context,'DEFER','TASK_BUDGET_EXHAUSTED',resource_estimate=estimate,reservation=None)
            if role_use['model_calls']+1>allocation['max_model_calls'] or role_use['estimated_tokens']+total>allocation['estimated_token_ceiling']:
                self.ledger.db.execute('ROLLBACK');return self._record(context,'DEFER','ROLE_ALLOCATION_EXHAUSTED',resource_estimate=estimate,reservation=None)
            remaining_calls=policy.max_model_calls-(task['model_calls']+1);remaining_tokens=policy.estimated_token_ceiling-(task['estimated_tokens']+total)
            if role!='ADVISOR' and (remaining_calls<policy.review_reserve_calls or remaining_tokens<policy.review_reserve_tokens):
                self.ledger.db.execute('ROLLBACK');return self._record(context,'REVIEW_REQUIRED','ADVISOR_REVIEW_RESERVE_PROTECTED',resource_estimate=estimate,reservation=None)
            reservation_id=str(uuid5(NAMESPACE_URL,context['execution_id']+':'+POLICY_VERSION))
            state_digest=digest({'fingerprint':fp,'usage':task,'policy':policy.__dict__})
            values=(context['task_id'],role,context['execution_id'],policy.version,1,context_tokens,output_token_budget,total,
                    why_llm_required,state_digest,'RESERVED',None)
            if duplicate and duplicate[1]=='RELEASED':
                reservation_id=duplicate[0]
                self.ledger.db.execute('UPDATE reservations SET task_id=?,role=?,execution_id=?,policy_version=?,model_calls=?,context_tokens=?,output_tokens=?,total_tokens=?,reason=?,state_digest=?,status=?,measured_tokens=? WHERE reservation_id=?',values+(reservation_id,))
            else:
                self.ledger.db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(reservation_id,)+values)
            self.ledger._event(context['execution_id'],'RESERVATION_CREATED',reservation_id);self.ledger.db.execute('COMMIT')
        except Exception:
            self.ledger.db.execute('ROLLBACK');raise
        return self._record(context,'ADMIT','AUTHORIZED_TO_DISPATCH',reservation_id=reservation_id,reservation_status='RESERVED',
                            resource_estimate=estimate,material_reasoning_fingerprint=fp,execution_purpose=execution_purpose,
                            expected_material_output=expected_material_output,why_llm_required=why_llm_required,
                            independent_review=independent_review,review_reserve={'calls':policy.review_reserve_calls,'tokens':policy.review_reserve_tokens})

    def transition(self,reservation_id,status,measured_tokens=None):
        if status not in {'CONSUMED','RELEASED','UNCERTAIN'}:raise ValueError('RESERVATION_TRANSITION')
        self.ledger.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.ledger.db.execute('SELECT execution_id,status FROM reservations WHERE reservation_id=?',(reservation_id,)).fetchone()
            allowed={'RESERVED':{'CONSUMED','RELEASED','UNCERTAIN'},'DISPATCHING':{'CONSUMED','UNCERTAIN'}}
            if not row or status not in allowed.get(row[1],set()):raise ValueError('RESERVATION_NOT_ACTIVE')
            if status!='CONSUMED' and measured_tokens is not None:raise ValueError('MEASURED_USAGE_STATE')
            if measured_tokens is not None and (type(measured_tokens) is not int or measured_tokens<0):raise ValueError('MEASURED_USAGE')
            self.ledger.db.execute('UPDATE reservations SET status=?,measured_tokens=? WHERE reservation_id=?',(status,measured_tokens,reservation_id))
            self.ledger._event(row[0],'RESERVATION_'+status,reservation_id);self.ledger.db.execute('COMMIT')
        except Exception:self.ledger.db.execute('ROLLBACK');raise

    def permit(self,reservation_id,execution_id):
        row=self.ledger.db.execute('SELECT execution_id,status FROM reservations WHERE reservation_id=?',(reservation_id,)).fetchone()
        if not row or row!=(execution_id,'RESERVED'):raise ValueError('PRE_LLM_ADMISSION_REQUIRED')
        return {'reservation_id':reservation_id,'execution_id':execution_id,'policy_version':POLICY_VERSION,'permit_digest':digest(row)}

    def claim_dispatch(self,permit,execution_id):
        """Atomically consumes the local dispatch right before external control transfer."""
        if not isinstance(permit,dict):raise ValueError('PRE_LLM_ADMISSION_REQUIRED')
        reservation_id=permit.get('reservation_id')
        self.ledger.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.ledger.db.execute('SELECT execution_id,status FROM reservations WHERE reservation_id=?',(reservation_id,)).fetchone()
            expected={'reservation_id':reservation_id,'execution_id':execution_id,'policy_version':POLICY_VERSION,
                      'permit_digest':digest((execution_id,'RESERVED'))}
            if row!=(execution_id,'RESERVED') or permit!=expected:raise ValueError('DISPATCH_RIGHT_NOT_AVAILABLE')
            changed=self.ledger.db.execute("UPDATE reservations SET status='DISPATCHING' WHERE reservation_id=? AND execution_id=? AND status='RESERVED'",
                                           (reservation_id,execution_id)).rowcount
            if changed!=1:raise ValueError('DISPATCH_RIGHT_NOT_AVAILABLE')
            self.ledger._event(execution_id,'DISPATCH_ATTEMPT_CLAIMED',reservation_id)
            self.ledger.db.execute('COMMIT')
            return {'reservation_id':reservation_id,'execution_id':execution_id,'status':'DISPATCHING'}
        except Exception:
            self.ledger.db.execute('ROLLBACK');raise

    def recover_in_flight(self):
        """Crash recovery is fail-closed: in-flight work becomes uncertain, never reserved."""
        self.ledger.db.execute('BEGIN IMMEDIATE')
        try:
            rows=self.ledger.db.execute("SELECT reservation_id,execution_id FROM reservations WHERE status='DISPATCHING'").fetchall()
            for reservation_id,execution_id in rows:
                self.ledger.db.execute("UPDATE reservations SET status='UNCERTAIN' WHERE reservation_id=? AND status='DISPATCHING'",(reservation_id,))
                self.ledger._event(execution_id,'RESERVATION_UNCERTAIN','CRASH_RECOVERY:'+reservation_id)
            self.ledger.db.execute('COMMIT');return len(rows)
        except Exception:self.ledger.db.execute('ROLLBACK');raise

    def telemetry(self,task_id):
        usage=self._usage(task_id);rows=self.ledger.db.execute('SELECT decision,count(*) FROM admissions WHERE task_id=? GROUP BY decision',(task_id,)).fetchall()
        return {'task_id':task_id,'decisions':dict(rows),'usage':usage,'account_quota':{'status':'NOT_AVAILABLE','value':None,'source':'NOT_CONNECTED'},
                'authority':False}

class GovernedLLMExecutor:
    def __init__(self,gate,delegate):self.gate=gate;self.delegate=delegate
    def submit(self,context,permit=None):
        claim=self.gate.claim_dispatch(permit,context['execution_id'])
        try:
            result=self.delegate.submit(context)
        except BaseException:
            self.gate.transition(claim['reservation_id'],'UNCERTAIN')
            raise
        self.gate.transition(claim['reservation_id'],'CONSUMED')
        return result
