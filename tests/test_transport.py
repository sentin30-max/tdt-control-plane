import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from tdt_control_plane.contracts import ExecutionContext, digest, parse_wire
from tdt_control_plane.executor import CodexCodeExecutor


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.context = ExecutionContext(str(uuid4()), str(uuid4()), str(uuid4()), (19, 23))
        self.cost = dict(checked_at=time.time(), ordinary_usage_allowed=True, remaining_primary=72,
                         remaining_weekly=2, credit_balance=0, paid_fallback_allowed=False)
        self.adapter = CodexCodeExecutor('codex.exe', '.', self.cost)
        self.wire = dict(context_id=self.context.context_id, execution_id=self.context.execution_id,
                         nonce=self.context.nonce, context_digest=digest(self.context.document()),
                         status='SUCCEEDED', executor='CodexCodeExecutor', payload={'sum': 42}, failure=None)

    def fake_run(self, args, **kwargs):
        if args == ['login', 'status']:
            return subprocess.CompletedProcess(args, 0, '', 'Logged in using ChatGPT')
        self.assertIn(self.context.execution_id, kwargs['input'])
        self.assertIn('--ignore-user-config', args)
        self.assertIn('read-only', args)
        Path(args[args.index('--output-last-message') + 1]).write_text(json.dumps(self.wire), encoding='utf-8')
        events = [{'type': 'thread.started', 'thread_id': str(uuid4())}, {'type': 'turn.completed'}]
        return subprocess.CompletedProcess(args, 0, '\n'.join(map(json.dumps, events)), '')

    @patch.dict('os.environ', {}, clear=True)
    def test_adapter_submission_capture_and_correlation(self):
        with patch.object(self.adapter, '_run', side_effect=self.fake_run):
            handle = self.adapter.submit(self.context)
        self.assertEqual(self.adapter.status(handle), 'SUCCEEDED')
        self.assertEqual(self.adapter.result(handle).payload, {'sum': 42})
        with self.assertRaises(ValueError):
            self.adapter.submit(self.context)

    def test_rejects_each_wrong_identity_extra_field_and_payload(self):
        mutations = [(k, str(uuid4())) for k in ('execution_id', 'context_id', 'nonce', 'context_digest')]
        mutations += [('extra', 'unexpected'), ('payload', {'sum': 41}), ('payload', {'sum': 42.0}), ('executor', 'Other'), ('failure', 'oops')]
        for key, value in mutations:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                parse_wire(json.dumps({**self.wire, key: value}), self.context)

    def test_rejects_duplicate_keys(self):
        with self.assertRaises(ValueError):
            parse_wire(json.dumps(self.wire)[:-1] + ',"status":"SUCCEEDED"}', self.context)

    @patch.dict('os.environ', {}, clear=True)
    def test_cost_guard_blocks_before_execution(self):
        for key, value in [('remaining_weekly', 0), ('credit_balance', 1), ('paid_fallback_allowed', True), ('checked_at', 0), ('ordinary_usage_allowed', False)]:
            with self.subTest(key=key):
                adapter = CodexCodeExecutor('codex', '.', {**self.cost, key: value})
                with patch.object(adapter, '_run') as run:
                    result = adapter.result(adapter.submit(self.context))
                run.assert_not_called()
                self.assertEqual(result.failure, 'COST_GUARD')

    @patch.dict('os.environ', {'CODEX_API_KEY': 'synthetic-test-value'}, clear=True)
    def test_api_key_override_blocked(self):
        with patch.object(self.adapter, '_run') as run:
            self.assertEqual(self.adapter.result(self.adapter.submit(self.context)).failure, 'COST_GUARD')
        run.assert_not_called()

    @patch.dict('os.environ', {}, clear=True)
    def test_auth_failure_sanitized(self):
        with patch.object(self.adapter, '_run', return_value=subprocess.CompletedProcess([], 1, '', 'synthetic sensitive error')):
            result = self.adapter.result(self.adapter.submit(self.context))
        self.assertEqual(result.failure, 'AUTH_UNAVAILABLE')
        self.assertNotIn('sensitive', json.dumps(result.document()))

    @patch.dict('os.environ', {}, clear=True)
    def test_timeout_controlled(self):
        with patch.object(self.adapter, '_run', side_effect=subprocess.TimeoutExpired('codex', 120)):
            self.assertEqual(self.adapter.result(self.adapter.submit(self.context)).failure, 'TIMEOUT')

    @patch.dict('os.environ', {}, clear=True)
    def test_wrong_result_returns_failure(self):
        self.wire['execution_id'] = str(uuid4())
        with patch.object(self.adapter, '_run', side_effect=self.fake_run):
            self.assertEqual(self.adapter.result(self.adapter.submit(self.context)).failure, 'INVALID_RESULT')


if __name__ == '__main__':
    unittest.main()
