"""Minimal deterministic binding from a role context to one exact Git checkout."""
import re
import subprocess
from pathlib import Path

from .contracts import digest

POLICY={'require_clean':True,'require_repository_root':True}


def _repository_identity(value):
    value=value.strip().replace('\\','/')
    if value.endswith('.git'):value=value[:-4]
    if value.startswith('git@') and ':' in value:value=value.split(':',1)[1]
    elif '://' in value:
        value=value.split('://',1)[1]
        value=value.split('/',1)[1] if '/' in value else ''
    return value.strip('/')


def validate_binding(binding):
    if type(binding) is not dict or set(binding)!={'repository_identity','required_commit','branch_hint','workspace_policy'}:
        raise ValueError('EXECUTION_ENVIRONMENT_SCHEMA')
    if any(type(binding[k]) is not str or not binding[k] for k in ('repository_identity','branch_hint')):
        raise ValueError('EXECUTION_ENVIRONMENT_IDENTITY')
    if not re.fullmatch(r'[0-9a-f]{40}',binding['required_commit']):raise ValueError('EXECUTION_ENVIRONMENT_COMMIT')
    if binding['workspace_policy']!=POLICY:raise ValueError('EXECUTION_ENVIRONMENT_POLICY')
    if not _repository_identity(binding['repository_identity']):raise ValueError('EXECUTION_ENVIRONMENT_IDENTITY')
    return binding


def verify_workspace(binding,workspace):
    """Fail closed unless workspace is the bound clean repository at the exact commit."""
    validate_binding(binding);workspace=Path(workspace).resolve()
    def git(*args):
        try:
            result=subprocess.run(['git','-C',str(workspace),*args],capture_output=True,text=True,timeout=20)
        except (OSError,subprocess.TimeoutExpired):
            raise ValueError('EXECUTION_ENVIRONMENT_MISMATCH') from None
        if result.returncode:raise ValueError('EXECUTION_ENVIRONMENT_MISMATCH')
        return result.stdout.strip()
    root=Path(git('rev-parse','--show-toplevel')).resolve()
    origin=git('config','--get','remote.origin.url')
    head=git('rev-parse','HEAD')
    status=git('status','--porcelain')
    if (root!=workspace or _repository_identity(origin)!=_repository_identity(binding['repository_identity'])
            or head!=binding['required_commit'] or status):
        raise ValueError('EXECUTION_ENVIRONMENT_MISMATCH')
    return {'status':'VERIFIED','workspace':str(workspace),'repository_identity':_repository_identity(origin),
            'required_commit':head,'branch_hint':binding['branch_hint'],'workspace_policy':POLICY,
            'binding_digest':digest(binding)}
