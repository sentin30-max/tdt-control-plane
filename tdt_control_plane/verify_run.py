"""Offline verification of a real run after restarting the Python process."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

from .continuity import run, EXECUTION_CONTRACT
from .contracts import digest
from .ledger import Ledger
from .recovery import verify_recovery
from .resolution import load_fixture
from .runtime import CodexRoleExecutor, atomic_json


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--proof',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    proof=json.loads(Path(args.proof).read_text())
    if proof['status'] != 'PASS':
        raise ValueError('PROOF_NOT_COMPLETE')
    ledger=Ledger(root/'.runtime/continuity/ledger.db')
    runtime=CodexRoleExecutor('not-used',ledger,root/'.runtime/continuity',{})
    try:
        first=load_fixture(root/'fixtures/trader')
        projection=root/'.runtime/derived-projection.json'
        atomic_json(projection,first)
        projection.unlink()
        rebuilt=load_fixture(root/'fixtures/trader')
        if first != rebuilt:
            raise ValueError('RECONSTRUCTION_MISMATCH')
        with patch('subprocess.run',side_effect=AssertionError('EXTERNAL_EXECUTION_DURING_RECOVERY')):
            report=verify_recovery(runtime,proof,rebuilt)
            replay=run(runtime,rebuilt,json.loads((root/'evidence/role-quality.json').read_text()),
                       root/'.runtime/replayed-proof.json',proof['workflow_id'])
        if digest(proof) != digest(replay):
            raise ValueError('REPLAY_MISMATCH')
        attempts={r['context']['execution_id']:ledger.recover(r['context']['execution_id'])['attempts'] for r in proof['records']}
        report.update(restart_verified=True,deleted_projection_rebuilt=True,workflow_replay_identical=True,
                      workflow_id=proof['workflow_id'],attempts=attempts,
                      no_retries_in_final_proof=all(n==1 for n in attempts.values()),
                      proof_digest=digest(proof),execution_contract_digest=digest(EXECUTION_CONTRACT))
        atomic_json(args.output,report)
        print('RECOVERY PASS; no external execution; projection rebuilt; identical workflow replay')
    finally:
        ledger.close()


if __name__=='__main__':
    main()
