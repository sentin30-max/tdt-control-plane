import threading
import tempfile
import unittest
from pathlib import Path

from tdt_control_plane.budget_admission import AdmissionGate,BudgetPolicy,GovernedLLMExecutor
from tdt_control_plane.ledger import Ledger
from tdt_control_plane.roles import make_context


class PermitReplayCorrectiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'ledger.db';self.ledger=Ledger(self.path);self.gate=AdmissionGate(self.ledger)
        self.context=make_context('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','a'*64,
            'DEVELOPMENT','corrective-fixture','bounded output',{'state':{'blocker':None}},{'fixture':'b'*64},['protected'])
        self.gate.configure(BudgetPolicy(self.context['task_id'],2,10000,1,1000,
            {'DEVELOPMENT':{'max_model_calls':1,'estimated_token_ceiling':7000},'ADVISOR':{'max_model_calls':1,'estimated_token_ceiling':3000}}))

    def tearDown(self):self.ledger.close();self.tmp.cleanup()

    def reserve(self):
        out=self.gate.evaluate(self.context,why_llm_required='GENERATIVE_SYNTHESIS_REQUIRED',execution_purpose='bounded synthesis',
            expected_material_output='strict result',output_token_budget=1000)
        self.assertEqual(out['decision'],'ADMIT');return out,self.gate.permit(out['reservation_id'],self.context['execution_id'])

    def status(self,reservation_id,ledger=None):
        return (ledger or self.ledger).db.execute('SELECT status FROM reservations WHERE reservation_id=?',(reservation_id,)).fetchone()[0]

    def test_sequential_permit_replay_calls_delegate_once(self):
        out,permit=self.reserve()
        class Delegate:
            calls=0
            def submit(inner,context):inner.calls+=1;return {'ok':True}
        delegate=Delegate();executor=GovernedLLMExecutor(self.gate,delegate)
        self.assertEqual(executor.submit(self.context,permit),{'ok':True})
        with self.assertRaisesRegex(ValueError,'DISPATCH_RIGHT_NOT_AVAILABLE'):executor.submit(self.context,permit)
        self.assertEqual(delegate.calls,1);self.assertEqual(self.status(out['reservation_id']),'CONSUMED')

    def test_concurrent_permit_replay_has_one_claim_and_one_delegate_call(self):
        out,permit=self.reserve();entered=threading.Event();release=threading.Event();calls=[];results=[]
        class Delegate:
            def submit(inner,context):calls.append(1);entered.set();release.wait(5);return 'ok'
        delegate=Delegate()
        def worker():
            ledger=Ledger(self.path);gate=AdmissionGate(ledger);executor=GovernedLLMExecutor(gate,delegate)
            try:results.append(('ok',executor.submit(self.context,permit)))
            except Exception as error:results.append(('error',str(error)))
            finally:ledger.close()
        first=threading.Thread(target=worker);first.start();self.assertTrue(entered.wait(5))
        second=threading.Thread(target=worker);second.start();second.join(5);release.set();first.join(5)
        self.assertEqual(len(calls),1);self.assertEqual(sum(x[0]=='ok' for x in results),1);self.assertEqual(sum('DISPATCH_RIGHT_NOT_AVAILABLE' in x[1] for x in results),1)
        self.assertEqual(self.status(out['reservation_id']),'CONSUMED')

    def test_exception_after_claim_becomes_uncertain_and_cannot_retry(self):
        out,permit=self.reserve()
        class Delegate:
            calls=0
            def submit(inner,context):inner.calls+=1;raise TimeoutError('simulated')
        delegate=Delegate();executor=GovernedLLMExecutor(self.gate,delegate)
        with self.assertRaises(TimeoutError):executor.submit(self.context,permit)
        self.assertEqual(self.status(out['reservation_id']),'UNCERTAIN')
        with self.assertRaisesRegex(ValueError,'DISPATCH_RIGHT_NOT_AVAILABLE'):executor.submit(self.context,permit)
        self.assertEqual(delegate.calls,1)

    def test_crash_window_recovers_dispatching_as_uncertain_never_reserved(self):
        out,permit=self.reserve();self.gate.claim_dispatch(permit,self.context['execution_id'])
        self.assertEqual(self.status(out['reservation_id']),'DISPATCHING')
        self.ledger.close();recovered_ledger=Ledger(self.path);recovered=AdmissionGate(recovered_ledger)
        self.assertEqual(recovered.recover_in_flight(),1);self.assertEqual(self.status(out['reservation_id'],recovered_ledger),'UNCERTAIN')
        with self.assertRaisesRegex(ValueError,'DISPATCH_RIGHT_NOT_AVAILABLE'):recovered.claim_dispatch(permit,self.context['execution_id'])
        recovered_ledger.close();self.ledger=Ledger(self.path)

    def test_claim_event_precedes_success_consumption_event(self):
        out,permit=self.reserve()
        class Delegate:
            def submit(inner,context):return 'ok'
        GovernedLLMExecutor(self.gate,Delegate()).submit(self.context,permit)
        kinds=[x[0] for x in self.ledger.db.execute('SELECT kind FROM events WHERE execution_id=? ORDER BY seq',(self.context['execution_id'],)).fetchall()]
        self.assertLess(kinds.index('DISPATCH_ATTEMPT_CLAIMED'),kinds.index('RESERVATION_CONSUMED'))
        self.assertEqual(self.status(out['reservation_id']),'CONSUMED')


if __name__=='__main__':unittest.main()
