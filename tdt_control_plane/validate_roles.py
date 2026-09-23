import argparse
import json
from pathlib import Path

from .ledger import Ledger
from .quality import evaluate
from .resolution import load_fixture
from .runtime import CodexRoleExecutor, atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--codex', required=True)
    parser.add_argument('--cost-attestation', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    state = root / '.runtime/quality'
    state.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(state / 'ledger.db')
    runtime = CodexRoleExecutor(args.codex, ledger, state, json.loads(Path(args.cost_attestation).read_text()))
    results = []
    try:
        for role in ('ADVISOR','DEVELOPMENT'):
            value = evaluate(runtime, load_fixture(root/'fixtures/trader'), role)
            results.append(value)
            atomic_json(args.output, {'evaluations':results,'authoritative':False})
            print(role, 'PASS' if value['passed'] else 'FAIL', flush=True)
            if not value['passed']:
                return 1
    finally:
        ledger.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
