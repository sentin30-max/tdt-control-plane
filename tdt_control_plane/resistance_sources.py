"""Slice 002 source reader. Only git show/rev-parse; no Trader write methods."""
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath

REVISION = 'af9f8a392f95363e86c5636aefa5c55494715f6c'
BASELINE = '46828c1658b5328f65fd23ad2e350a19e54039ae'
DOSSIER = 'audits/resistance/RESISTANCE-AUDIT-REQUEST-46828C1658B5'
REQUEST_NAME = 'A4_TWO_STAGE_REQUEST_V1.json'
INPUT_NAME = 'A4_TWO_STAGE_INPUT_V1.md'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_read(repo, revision, path):
    relative = PurePosixPath(path)
    if revision not in {REVISION, BASELINE} or relative.is_absolute() or '..' in relative.parts:
        raise ValueError('SOURCE_SCOPE')
    repo = Path(repo).resolve()
    git = ['C:/Program Files/Git/cmd/git.exe', '-c', 'safe.directory='+repo.as_posix(), '-C', str(repo)]
    return subprocess.check_output(git+['show', revision+':'+relative.as_posix()], timeout=30)


def verify_export(snapshot, manifest):
    snapshot = Path(snapshot)
    if manifest['revision'] != REVISION:
        raise ValueError('STALE_SOURCE_REVISION')
    for path, expected in manifest['files'].items():
        target = (snapshot/path).resolve()
        if not target.is_relative_to(snapshot.resolve()) or not target.is_file() or sha(target.read_bytes()) != expected:
            raise ValueError('PROTECTED_SOURCE_CHANGED:'+path)
    return True


def read_sources(root):
    root=Path(root)
    manifest=json.loads((root/'evidence/slice002/source-manifest.json').read_text())
    snapshot=root/'.runtime/slice002/trader-snapshot'
    verify_export(snapshot,manifest)
    files={
        'historical_request':DOSSIER+'/A4_HYBRID_REQUEST_V1.json',
        'historical_input':DOSSIER+'/A4_HYBRID_INPUT_V1.md',
        'evidence_manifest':DOSSIER+'/EVIDENCE_MANIFEST.json',
        'lifecycle':'sprint3/resistance/RESISTANCE_LIFECYCLE_RESULT.json',
        'published_contract':'audits/A4_OUTPUT_CONTRACT_V2_DRAFT.md',
        'runner':'tools/tef_audit_runner.py', 'resolver':'tools/tef_a4_resolution.py',
        'tooling_tests':'tests/tooling/test_a4_hybrid_request.py',
    }
    texts={k:(snapshot/p).read_text(encoding='utf-8') for k,p in files.items()}
    hashes={k:manifest['files'][p] for k,p in files.items()}
    authority=(root/'evidence/slice002/po-authorization.txt').read_bytes()
    hashes['po_authorization']=sha(authority)
    lifecycle=json.loads(texts['lifecycle'])
    if lifecycle['current_state']!='EN_AUDITORIA' or lifecycle['evaluated_code_baseline']!=BASELINE or lifecycle['executed'] is not True:
        raise ValueError('MATERIAL_SOURCE_CONTRADICTION')
    return {'revision':REVISION,'baseline':BASELINE,'lifecycle':'EN_AUDITORIA',
            'operational_point':'A4_TWO_STAGE_PUBLICATION_COMPLETED; prepare new request/input; local validation and preflight only',
            'files':files,'texts':texts,'hashes':hashes,'snapshot':str(snapshot),'authoritative':False}
