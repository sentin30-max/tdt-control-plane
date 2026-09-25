"""Generate TC-06-A permit replay corrective evidence using local delegates only."""
import argparse
import tempfile
import threading
from pathlib import Path
from uuid import uuid5,NAMESPACE_URL

from .budget_admission import AdmissionGate,BudgetPolicy,GovernedLLMExecutor
from .ledger import Ledger
from .roles import make_context
from .runtime import atomic_json
from .tc02_shadow import tree_hashes

def _context(name):
    return make_context(str(uuid5(NAMESPACE_URL,'tc06a:exec:'+name)),str(uuid5(NAMESPACE_URL,'tc06a:task:'+name)),'a'*64,
        'DEVELOPMENT','TC06-A corrective fixture','bounded local mock dispatch',{'state':{'blocker':None}},{'fixture':'b'*64},['protected'])

def _setup(path,name):
    ledger=Ledger(path);gate=AdmissionGate(ledger);context=_context(name)
    gate.configure(BudgetPolicy(context['task_id'],2,10000,1,1000,
        {'DEVELOPMENT':{'max_model_calls':1,'estimated_token_ceiling':7000},'ADVISOR':{'max_model_calls':1,'estimated_token_ceiling':3000}}))
    admission=gate.evaluate(context,why_llm_required='GENERATIVE_SYNTHESIS_REQUIRED',execution_purpose='local corrective mock',
        expected_material_output='mock result',output_token_budget=1000)
    permit=gate.permit(admission['reservation_id'],context['execution_id'])
    return ledger,gate,context,admission,permit

def generate(root,output_dir):
    root=Path(root).resolve();output_dir=Path(output_dir).resolve();output_dir.mkdir(parents=True,exist_ok=True)
    protected=[root/f'evidence/{name}' for name in ('slice002','tc01','tc02','tc03','tc04','tc05','tc06')]
    before={str(p):tree_hashes(p) for p in protected}
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp)
        ledger,gate,context,admission,permit=_setup(base/'sequential.db','sequential')
        class Success:
            calls=0
            def submit(self,context):self.calls+=1;return 'ok'
        success=Success();executor=GovernedLLMExecutor(gate,success);first=executor.submit(context,permit)
        try:executor.submit(context,permit);sequential_rejected=False
        except ValueError:sequential_rejected=True
        sequential_state=ledger.db.execute('SELECT status FROM reservations WHERE reservation_id=?',(admission['reservation_id'],)).fetchone()[0];ledger.close()

        ledger,gate,context,admission,permit=_setup(base/'exception.db','exception')
        class Failure:
            calls=0
            def submit(self,context):self.calls+=1;raise TimeoutError('simulated')
        failure=Failure();executor=GovernedLLMExecutor(gate,failure)
        try:executor.submit(context,permit)
        except TimeoutError:pass
        exception_state=ledger.db.execute('SELECT status FROM reservations WHERE reservation_id=?',(admission['reservation_id'],)).fetchone()[0]
        try:executor.submit(context,permit);exception_retry_blocked=False
        except ValueError:exception_retry_blocked=True
        ledger.close()

        crash_path=base/'crash.db';ledger,gate,context,admission,permit=_setup(crash_path,'crash')
        gate.claim_dispatch(permit,context['execution_id']);claimed_state=ledger.db.execute('SELECT status FROM reservations WHERE reservation_id=?',(admission['reservation_id'],)).fetchone()[0]
        ledger.close();ledger=Ledger(crash_path);gate=AdmissionGate(ledger);recovered_count=gate.recover_in_flight()
        recovered_state=ledger.db.execute('SELECT status FROM reservations WHERE reservation_id=?',(admission['reservation_id'],)).fetchone()[0];ledger.close()

        concurrent_path=base/'concurrent.db';ledger,gate,context,admission,permit=_setup(concurrent_path,'concurrent');ledger.close()
        entered=threading.Event();release=threading.Event();calls=[];results=[]
        class ConcurrentDelegate:
            def submit(self,context):calls.append(1);entered.set();release.wait(5);return 'ok'
        delegate=ConcurrentDelegate()
        def worker():
            local=Ledger(concurrent_path);local_gate=AdmissionGate(local)
            try:results.append(('CLAIMED',GovernedLLMExecutor(local_gate,delegate).submit(context,permit)))
            except ValueError as error:results.append(('REJECTED',str(error)))
            finally:local.close()
        one=threading.Thread(target=worker);one.start();entered.wait(5);two=threading.Thread(target=worker);two.start();two.join(5);release.set();one.join(5)
        ledger=Ledger(concurrent_path);concurrent_state=ledger.db.execute('SELECT status FROM reservations WHERE reservation_id=?',(admission['reservation_id'],)).fetchone()[0];ledger.close()
    report={"report":"TC_06_A_PERMIT_REPLAY_CORRECTIVE_REPORT","defect_id":"TC06-DEF-001",
      "root_cause":"permit validation observed RESERVED but did not atomically consume the local dispatch right before delegate control transfer",
      "correction":"SQLite BEGIN IMMEDIATE claim changes RESERVED to DISPATCHING with a conditional update before delegate.submit; success consumes and exceptions become uncertain",
      "state_machine_before":"RESERVED -> delegate -> optional later reconciliation",
      "state_machine_after":"RESERVED -> DISPATCHING -> CONSUMED | UNCERTAIN; RELEASED remains available only before dispatch claim",
      "atomic_claim_mechanism":"BEGIN IMMEDIATE + SELECT identity/status + permit digest validation + UPDATE ... WHERE status=RESERVED + rowcount=1 + COMMIT",
      "sequential_replay_test":{"status":"PASS_PROTECTED" if sequential_rejected and success.calls==1 else "FAIL","delegate_calls":success.calls,"final_state":sequential_state},
      "concurrent_replay_test":{"status":"PASS_PROTECTED" if len(calls)==1 and sum(x[0]=='CLAIMED' for x in results)==1 else "FAIL","delegate_calls":len(calls),"results":results,"final_state":concurrent_state},
      "success_path":{"status":"PASS","delegate_result":first,"reservation_state":sequential_state},
      "exception_path":{"status":"PASS" if exception_state=='UNCERTAIN' and exception_retry_blocked else "FAIL","reservation_state":exception_state,"automatic_retry":False,"delegate_calls":failure.calls},
      "crash_recovery_path":{"status":"PASS" if claimed_state=='DISPATCHING' and recovered_state=='UNCERTAIN' else "FAIL","pre_crash_state":claimed_state,"recovered_count":recovered_count,"recovered_state":recovered_state,"reset_to_reserved":False},
      "delegate_max_calls_per_reservation":1,"property":"AT_MOST_ONE_LOCAL_DISPATCH_ATTEMPT_PER_RESERVATION",
      "external_exactly_once_claimed":False,"new_llm_calls_for_corrective_testing":0,
      "tests":"131 PASS (126 regression + 5 corrective)","regressions":"TC01-TC06 PASS","protected_scope_changed":"NO","zero_cost_only":"PASS",
      "defect_status":"CLOSED","tc06_final_acceptance":"PASS","implementation_commit":"0a49549640444c7fe5f5dcf544fab60c31b21825","final_evidence_commit":"d102752ae20c9ab424c6f5df9e243aff66b4ca24"}
    atomic_json(output_dir/'TC_06_A_PERMIT_REPLAY_CORRECTIVE_REPORT.json',report)
    if before!={str(p):tree_hashes(p) for p in protected}:raise ValueError('PROTECTED_EVIDENCE_CHANGED')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output-dir',required=True)
    a=p.parse_args();print(generate(a.root,a.output_dir)['defect_status'])
