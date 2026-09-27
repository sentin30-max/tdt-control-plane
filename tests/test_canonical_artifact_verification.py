import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from tdt_control_plane.contracts import digest
from tdt_control_plane.execution_environment import POLICY
from tdt_control_plane.execution_environment import verify_workspace as real_verify_workspace
from tdt_control_plane.ledger import Ledger
from tdt_control_plane.resistance_pilot import LocalValidationExecutor
from tdt_control_plane.roles import make_context


class CanonicalArtifactVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.repo, self.runtime = base / 'trader', base / 'runtime'
        self.repo.mkdir(); self.runtime.mkdir(); (self.runtime / 'spool').mkdir()
        self.git('init'); self.git('config', 'user.email', 'tests@example.invalid')
        self.git('config', 'user.name', 'Tests')
        self.git('remote', 'add', 'origin', 'https://github.com/sentin30-max/tdt-TRADER-AI.git')
        self.first, self.second = self.repo / 'audit/request.json', self.repo / 'audit/input.md'
        self.first.parent.mkdir(); self.first.write_bytes(b'{"request":true}\n')
        self.second.write_bytes(b'canonical input\r\n')
        self.git('add', '.'); self.git('commit', '-m', 'fixture')
        self.commit = self.git('rev-parse', 'HEAD').stdout.strip()
        self.ledger = Ledger(self.runtime / 'ledger.sqlite')
        self.executor = LocalValidationExecutor(self.runtime, self.ledger,
                                                self.runtime / 'spool', self.repo)

    def tearDown(self):
        self.ledger.close(); self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True, text=True)

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def context(self, artifacts=None, repository='sentin30-max/tdt-TRADER-AI', commit=None):
        artifacts = artifacts if artifacts is not None else [
            {'relative_path': 'audit/request.json', 'expected_sha256': self.sha(self.first)},
            {'relative_path': 'audit/input.md', 'expected_sha256': self.sha(self.second)},
        ]
        sources = {'fixture': digest('canonical-fixture')}
        return make_context(str(uuid4()), str(uuid4()), digest('revision'), 'CODE_EXECUTOR',
                            'Read-only canonical artifact verification', 'Verify exact bytes',
                            {'operation': 'VERIFY_EXISTING_CANONICAL_ARTIFACTS',
                             'canonical_artifacts': artifacts}, sources, ['Trader AI'],
                            {'repository_identity': repository,
                             'required_commit': commit or self.commit,
                             'branch_hint': self.git('branch', '--show-current').stdout.strip(),
                             'workspace_policy': POLICY})

    def artifact(self, record):
        return json.loads(record['result']['artifact'])

    def test_correct_environment_and_two_hashes_pass(self):
        record = self.executor.submit(self.context())
        artifact = self.artifact(record)
        self.assertEqual((record['result']['outcome'], artifact['verification_status']), ('SUCCEEDED', 'PASS'))
        self.assertEqual([f['status'] for f in artifact['files']], ['PASS', 'PASS'])

    def test_wrong_repository_is_blocked_before_executor(self):
        context = self.context(repository='sentin30-max/not-trader')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('canonical read')), \
             self.assertRaisesRegex(ValueError, 'EXECUTION_ENVIRONMENT_MISMATCH'):
            self.executor.submit(context)
        self.assertEqual(self.ledger.recover(context['execution_id'])['attempts'], 0)

    def test_wrong_commit_is_blocked_before_executor(self):
        context = self.context(commit='0' * 40)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('canonical read')), \
             self.assertRaisesRegex(ValueError, 'EXECUTION_ENVIRONMENT_MISMATCH'):
            self.executor.submit(context)
        self.assertEqual(self.ledger.recover(context['execution_id'])['attempts'], 0)

    def test_dirty_workspace_is_blocked_before_executor(self):
        (self.repo / 'untracked').write_text('dirty')
        context = self.context()
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('canonical read')), \
             self.assertRaisesRegex(ValueError, 'EXECUTION_ENVIRONMENT_MISMATCH'):
            self.executor.submit(context)
        self.assertEqual(self.ledger.recover(context['execution_id'])['attempts'], 0)

    def test_missing_file_returns_blocked(self):
        specs = [{'relative_path': 'audit/missing.json', 'expected_sha256': 'a' * 64}]
        record = self.executor.submit(self.context(specs))
        self.assertEqual(record['result']['outcome'], 'BLOCKED')
        self.assertEqual(self.artifact(record)['files'][0]['status'], 'MISSING')

    def test_wrong_hash_returns_blocked(self):
        specs = [{'relative_path': 'audit/request.json', 'expected_sha256': 'a' * 64}]
        record = self.executor.submit(self.context(specs))
        self.assertEqual(record['result']['outcome'], 'BLOCKED')
        self.assertEqual(self.artifact(record)['files'][0]['status'], 'MISMATCH')

    def test_absolute_path_is_rejected(self):
        specs = [{'relative_path': str(self.first.resolve()), 'expected_sha256': self.sha(self.first)}]
        with self.assertRaisesRegex(ValueError, 'CANONICAL_ARTIFACT_SCOPE'):
            self.executor.submit(self.context(specs))

    def test_path_traversal_is_rejected(self):
        specs = [{'relative_path': '../outside', 'expected_sha256': 'a' * 64}]
        with self.assertRaisesRegex(ValueError, 'CANONICAL_ARTIFACT_SCOPE'):
            self.executor.submit(self.context(specs))

    def test_duplicate_algorithm_and_malformed_digest_are_rejected(self):
        duplicate = [
            {'relative_path': 'audit/request.json', 'expected_sha256': self.sha(self.first)},
            {'relative_path': 'audit/request.json', 'expected_sha256': self.sha(self.first)},
        ]
        wrong_algorithm = [{'relative_path': 'audit/request.json',
                            'expected_sha256': self.sha(self.first), 'algorithm': 'SHA-1'}]
        malformed = [{'relative_path': 'audit/request.json', 'expected_sha256': 'not-a-digest'}]
        for specs, code in ((duplicate, 'CANONICAL_ARTIFACT_DUPLICATE'),
                            (wrong_algorithm, 'CANONICAL_ARTIFACT_SCHEMA'),
                            (malformed, 'CANONICAL_ARTIFACT_DIGEST')):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                self.executor.submit(self.context(specs))

    def test_workspace_change_after_initial_verification_blocks_before_read(self):
        calls = 0
        def verify_then_dirty(binding, workspace):
            nonlocal calls
            result = real_verify_workspace(binding, workspace)
            calls += 1
            if calls == 1:
                (self.repo / 'changed-after-binding').write_text('dirty')
            return result
        context = self.context()
        with patch('tdt_control_plane.resistance_pilot.verify_workspace', side_effect=verify_then_dirty), \
             patch.object(Path, 'read_bytes', side_effect=AssertionError('canonical read')), \
             self.assertRaisesRegex(ValueError, 'EXECUTION_ENVIRONMENT_MISMATCH'):
            self.executor.submit(context)
        self.assertEqual(self.ledger.recover(context['execution_id'])['attempts'], 0)

    def test_symlink_escape_is_rejected_when_supported(self):
        outside = Path(self.temp.name) / 'outside'; outside.write_text('outside')
        link = self.repo / 'audit/link'
        try:
            os.symlink(outside, link)
        except OSError as error:
            self.skipTest('symlinks unavailable: ' + str(error))
        specs = [{'relative_path': 'audit/link', 'expected_sha256': hashlib.sha256(b'outside').hexdigest()}]
        with self.assertRaisesRegex(ValueError, 'CANONICAL_ARTIFACT_SCOPE'):
            self.executor.submit(self.context(specs))

    def test_unlisted_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'CANONICAL_ARTIFACT_NOT_AUTHORIZED'):
            self.executor._authorized_path(self.repo, 'audit/input.md', {'audit/request.json'})

    def test_executor_does_not_modify_files(self):
        before = (self.first.read_bytes(), self.second.read_bytes(), self.git('status', '--porcelain').stdout)
        self.executor.submit(self.context())
        after = (self.first.read_bytes(), self.second.read_bytes(), self.git('status', '--porcelain').stdout)
        self.assertEqual(before, after)

    def test_does_not_execute_preflight(self):
        with patch.object(self.executor, '_submit_preflight', side_effect=AssertionError('preflight')):
            record = self.executor.submit(self.context())
        self.assertFalse(self.artifact(record)['guards']['preflight_executed'])

    def test_does_not_execute_groq_a4_or_a5(self):
        guards = self.artifact(self.executor.submit(self.context()))['guards']
        self.assertEqual(guards, {'preflight_executed': False, 'groq_executed': False,
                                  'a4_executed': False, 'a5_executed': False})

    def test_result_is_structured_correlated_and_ingested(self):
        context = self.context(); record = self.executor.submit(context)
        recovered = self.ledger.recover(context['execution_id'])
        self.assertEqual(record['ingest'], 'ACCEPTED')
        self.assertEqual(recovered['status'], 'INGESTED')
        self.assertEqual(recovered['result_digest'], record['result_digest'])
        self.assertEqual(self.artifact(record)['environment_binding_digest'],
                         record['environment_verification']['binding_digest'])

    def test_telemetry_and_provenance_are_persisted(self):
        context = self.context(); record = self.executor.submit(context)
        telemetry = self.ledger.telemetry(context['execution_id'])[0]['record']
        self.assertEqual(telemetry['identity']['result_digest'], record['result_digest'])
        self.assertEqual(telemetry['provenance']['operation'], 'VERIFY_EXISTING_CANONICAL_ARTIFACTS')
        self.assertEqual(telemetry['accounting']['model_call_count']['value'], 0)
        self.assertFalse(telemetry['provenance']['model_dispatched'])

    def test_recovery_reuses_result_without_read_or_execution(self):
        context = self.context(); first = self.executor.submit(context)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('new read')), \
             patch.object(self.executor, '_verify_environment', side_effect=AssertionError('new execution')):
            second = self.executor.submit(context)
        self.assertEqual(first, second)
        self.assertEqual(self.ledger.recover(context['execution_id'])['attempts'], 1)


if __name__ == '__main__':
    unittest.main()
