import argparse
import json
from pathlib import Path
from uuid import uuid4

from .contracts import ExecutionContext, digest
from .executor import CodeExecutorAdapter, CodexCodeExecutor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", required=True)
    parser.add_argument("--cost-attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite execution evidence")
    cost = json.loads(args.cost_attestation.read_text(encoding="utf-8-sig"))
    context = ExecutionContext(str(uuid4()), str(uuid4()), str(uuid4()), (19, 23))
    adapter: CodeExecutorAdapter = CodexCodeExecutor(args.codex, Path.cwd(), cost)
    handle = adapter.submit(context)
    result = adapter.result(handle)
    verified = (adapter.status(handle) == "SUCCEEDED" and result.execution_id == context.execution_id
                and result.context_id == context.context_id and result.context_digest == digest(context.document())
                and result.payload == {"sum": 42})
    report = {"hito_a": "PASS" if verified else "NOT_PASS", "authoritative": False,
              "context": context.document(), "result": result.document(), "result_digest": digest(result.document()),
              "cost_attestation": cost, "po_manual_transport": "NONE", "correlation_verified": verified}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"hito_a": report["hito_a"], "execution_id": handle, "failure": result.failure}))
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
