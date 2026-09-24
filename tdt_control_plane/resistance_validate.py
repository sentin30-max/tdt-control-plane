"""Network-denied local validation using byte-identical published Trader tools."""
import argparse
import contextlib
import io
import json
import os
import sys
from uuid import uuid4
from pathlib import Path
from unittest.mock import patch

from .contracts import digest
from .resistance_sources import BASELINE, DOSSIER, REVISION, git_read, read_sources, sha
from .runtime import atomic_json


def deny_network():
    attempts=[]
    def audit(event,args):
        if event in {'socket.connect','socket.getaddrinfo','socket.bind'}:
            attempts.append(event)
            raise RuntimeError('NETWORK_FORBIDDEN_IN_LOCAL_VALIDATION')
    sys.addaudithook(audit)
    return attempts


def setup(root,sources):
    sys.dont_write_bytecode=True
    snapshot=Path(sources['snapshot'])
    sys.path[:0]=[str(snapshot),str(root/'.runtime/slice002/test-deps')]
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    os.environ['GIT_DIR']=str(root.parent/'trader-reference/.git')
    os.environ['GIT_CONFIG_COUNT']='1'
    os.environ['GIT_CONFIG_KEY_0']='safe.directory'
    os.environ['GIT_CONFIG_VALUE_0']=(root.parent/'trader-reference').as_posix()
    os.chdir(snapshot)


def bootstrap(root,sources):
    import pytest
    class Results:
        def __init__(self):self.results=[]
        def pytest_runtest_logreport(self,report):
            if report.when=='call' or report.failed:
                self.results.append({'test':report.nodeid,'outcome':report.outcome})
    plugin=Results();log=io.StringIO()
    temp=root/'.runtime/slice002'/('pytest-'+str(uuid4()))
    if not temp.resolve().is_relative_to((root/'.runtime/slice002').resolve()):
        raise ValueError('TEST_TEMP_SCOPE')
    with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        code=pytest.main(['-q','--tb=short','--basetemp',str(temp),'-p','no:cacheprovider','tests/tooling'],plugins=[plugin])
    from tools import tef_a4_resolution as resolver
    from tools import tef_audit_runner as runner
    checked={
        'refutation_validity_version':resolver.REFUTATION_VALIDITY_VERSION,
        'a4_resolver_version':resolver.A4_RESOLVER_VERSION,
        'llm_forbidden_fields_absent_from_schema':not {'refutation_valid','refutation_validity','global_state'} & set(resolver.A4_AUDITOR_EVIDENCE_FIELDS),
        'a4_only_request_supported':runner.execution_plan(Path(sources['snapshot'])/DOSSIER/'A4_HYBRID_REQUEST_V1.json',json.loads(sources['texts']['historical_request']))['stages']==('A4',),
    }
    passed=code==0 and checked['refutation_validity_version']=='1' and checked['a4_resolver_version']=='1' and checked['llm_forbidden_fields_absent_from_schema'] and checked['a4_only_request_supported']
    return {'status':'PASS' if passed else 'FAIL','source_revision':REVISION,'publication_verified':passed,
            'tooling_passed':sum(r['outcome']=='passed' for r in plugin.results),
            'resolver_passed':sum(r['outcome']=='passed' and 'test_tef_a4_resolution.py' in r['test'] for r in plugin.results),
            'tests':plugin.results,'checks':checked,'output':log.getvalue(),'python':sys.version.split()[0],
            'scope':'Published tooling only; no production-domain test rerun; no historical output reprocessing', 'authoritative':False}


def verify_prepared(root,sources,candidate):
    from tools import tef_audit_runner as runner
    from tools import tef_a4_resolution as resolver
    from .resistance_candidate import validate_candidate
    request_path=root/candidate['request_path']
    input_path=root/candidate['input_path']
    validate_candidate({'request':json.loads(request_path.read_text()),'input_text':input_path.read_text(encoding='utf-8')},sources)
    def reader(revision,path):
        return git_read(root.parent/'trader-reference',revision,path)
    # No auditor function can be reached through the allowed validator call graph.
    with (patch.object(runner,'call_groq',side_effect=RuntimeError('GROQ_NOT_AUTHORIZED')) as provider,
          patch.object(runner,'execute_stage',side_effect=RuntimeError('AUDIT_NOT_AUTHORIZED'))):
        request=runner.load_request(request_path)
        evidence=runner.materialize_evidence(request_path,request,baseline_reader=reader)
        package=runner.build_stage_package('A4',request_path,request,evidence)
        budget=runner.stage_request_budget(request,package)
        plan=runner.execution_plan(request_path,request)
        rejection={}
        for field in ['refutation_valid','refutation_validity','global_state']:
            # Synthetic contract probe, never a historical auditor output.
            response=resolver.resolve_a4_evidence({'stage':'A4',field:True})
            resolution=response['deterministic_resolution']
            rejection[field]=(resolution['resolution_status']=='UNRESOLVED_CONTRADICTION' and 'global_state' not in resolution)
        provider.assert_not_called()
    reference=json.loads(sources['texts']['historical_request'])
    old_input=sources['texts']['historical_input']
    new_input=input_path.read_text(encoding='utf-8')
    surfaces=lambda s:s.split('MANDATORY ATTACK SURFACES:',1)[1].split('ORACLES:',1)[0]
    oracles=lambda s:s.split('ORACLES:',1)[1].split('INDEPENDENCE AND PRESERVATION:',1)[0]
    checks={
        'claims_preserved':request['claims']==reference['claims']==['C'+str(i) for i in range(1,15)],
        'attack_surfaces_preserved':surfaces(old_input)==surfaces(new_input),
        'oracles_preserved':oracles(old_input)==oracles(new_input),
        'evidence_set_preserved':(request_path.parent/request['evidence_manifest']).read_bytes()==(Path(sources['snapshot'])/DOSSIER/reference['evidence_manifest']).read_bytes(),
    }
    checks['independence_preserved']=request['a4_independence_required']==reference['a4_independence_required'] is True and package['independence']['required'] is True and request['a4_instance_id']==request['a4_independent_instance_id'] and request['a4_instance_id']!=reference['a4_instance_id']
    checks.update(versions_1_1=request['refutation_validity_version']==package['auditor_output_authority']['refutation_validity_version']=='1' and request['resolver_version']==package['auditor_output_authority']['resolver_version']=='1',
                  a4_only=plan['stages']==('A4',) and not plan['run_a3'],
                  no_llm_derived_fields=not set(rejection)&set(package['auditor_output_authority']['allowed_fields']),
                  forbidden_fields_rejected=all(rejection.values()), baseline_pinned=request['evaluated_baseline']==BASELINE,
                  provider_preserved=request['provider']=='groq' and request['model']=='openai/gpt-oss-120b' and request['zero_cost_only'] is True)
    return {'status':'PASS' if all(checks.values()) else 'FAIL','local_validation':'PASS' if all(checks.values()) else 'FAIL',
            'preflight':'PASS' if budget['fits'] else 'FAIL','budget':budget,'checks':checks,'forbidden_field_rejections':rejection,
            'request_sha256':sha(request_path.read_bytes()),'input_sha256':sha(input_path.read_bytes()),
            'package_digest':digest(package),'native_input_hash':package['input_hash'],'native_evidence_hash':package['evidence_hash'],
            'materialized_evidence':[{'path':e['source_path'],'sha256':e['sha256'],'line_ranges':e['line_ranges'],'stages':e['stages']} for e in evidence],
            'groq_executed':False,'a4_executed':False,'a5_executed':False,'authoritative':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output',required=True);p.add_argument('--candidate')
    args=p.parse_args();root=Path(args.root).resolve();sources=read_sources(root)
    setup(root,sources);network=deny_network()
    report=verify_prepared(root,sources,json.loads(Path(args.candidate).read_text())) if args.candidate else bootstrap(root,sources)
    report['network_attempts']=network
    read_sources(root) # all exported protected bytes must still match
    report['protected_sources_unchanged']=True
    atomic_json(args.output,report)
    print(report['status'],report.get('preflight','PUBLICATION'),flush=True)
    return 0 if report['status']=='PASS' and not network else 1


if __name__=='__main__':raise SystemExit(main())
