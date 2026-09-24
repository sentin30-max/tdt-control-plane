"""TC-01 observational telemetry. It cannot participate in execution decisions."""
import json
from dataclasses import dataclass

from .contracts import digest

MEASURED = 'MEASURED'
ESTIMATED = 'ESTIMATED'
NOT_AVAILABLE = 'NOT_AVAILABLE'
STATUSES = {MEASURED, ESTIMATED, NOT_AVAILABLE}
SCHEMA_VERSION = 1
CONTEXT_POLICY = 'tc01-observe-existing-context-v1'


def canonical_json_bytes(value):
    return len(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8'))


def serialized_json_bytes(value):
    """Match the existing runtime/forensic default JSON representation."""
    return len(json.dumps(value).encode('utf-8'))


def measurement(value, status, method=None, reason=None):
    if status not in STATUSES:
        raise ValueError('USAGE_STATUS')
    if status == NOT_AVAILABLE:
        if value is not None or not reason:
            raise ValueError('NOT_AVAILABLE_SEMANTICS')
    elif type(value) is not int or value < 0 or not method:
        raise ValueError('MEASUREMENT_SEMANTICS')
    return {'value': value, 'status': status, 'method': method, 'reason': reason}


def byte_proxy(value):
    return measurement((value + 3) // 4, ESTIMATED, 'ceil_utf8_bytes_div_4_proxy')


def unavailable(reason):
    return measurement(None, NOT_AVAILABLE, reason=reason)


def _usage_from_events(events):
    """Accept only explicit runtime counters; absence remains NOT_AVAILABLE."""
    found = {}
    aliases = {
        'input_tokens': 'runtime_input_tokens',
        'output_tokens': 'runtime_output_tokens',
        'cached_input_tokens': 'cached_tokens',
        'cached_tokens': 'cached_tokens',
        'reasoning_output_tokens': 'reasoning_tokens',
        'reasoning_tokens': 'reasoning_tokens',
    }
    for event in events or []:
        usage = event.get('usage')
        if type(usage) is not dict:
            continue
        for source, target in aliases.items():
            value = usage.get(source)
            if type(value) is int and value >= 0:
                if target in found and found[target] != value:
                    raise ValueError('CONFLICTING_RUNTIME_USAGE')
                found[target] = value
    return found


def observe(context, result, *, backend, prompt=None, events=None,
            model=None, recovered=False, failed=False, pending_usage=False,
            model_dispatched=True, attempt=0):
    context_bytes = serialized_json_bytes(context)
    output_bytes = serialized_json_bytes(result) if result is not None else None
    explicit = _usage_from_events(events)
    runtime = {}
    for field in ('runtime_input_tokens', 'runtime_output_tokens', 'cached_tokens', 'reasoning_tokens'):
        runtime[field] = (measurement(explicit[field], MEASURED, 'runtime_reported_usage')
                          if field in explicit else unavailable('runtime_did_not_report_field'))
    source_digests = context.get('source_digests', {})
    refs = sorted(source_digests) if type(source_digests) is dict else []
    return {
        'schema_version': SCHEMA_VERSION,
        'context_policy': CONTEXT_POLICY,
        'authoritative': False,
        'identity': {
            'task_id': context.get('task_id'), 'execution_id': context.get('execution_id'),
            'role': context.get('role'), 'scope': context.get('scope'),
            'context_digest': digest(context),
            'result_digest': digest(result) if result is not None else None,
            'input_revision': context.get('input_revision'),
            'attempt': attempt,
        },
        'execution_kind': 'LLM' if backend == 'CodexRoleExecutor' else 'DETERMINISTIC',
        'backend': backend,
        'context': {
            'bytes': measurement(context_bytes, MEASURED, 'utf8_bytes_json_dumps_default'),
            'estimated_tokens': byte_proxy(context_bytes),
            'actual_tokens': unavailable('runtime_did_not_report_context_only_tokens'),
            'source_count': measurement(len(refs), MEASURED, 'source_digest_key_count'),
            'artifact_refs': refs,
            'full_reconstruction': unavailable('existing_context_has_no_full_reconstruction_marker'),
            'full_reconstruction_reason': None,
        },
        'prompt': {
            'bytes': (measurement(len(prompt.encode('utf-8')), MEASURED, 'utf8_bytes_exact_material')
                      if prompt is not None else unavailable('no_prompt_for_deterministic_execution')),
        },
        'output': {
            'bytes': (measurement(output_bytes, MEASURED, 'utf8_bytes_json_dumps_default')
                      if output_bytes is not None else unavailable('no_validated_result')),
            'estimated_tokens': (byte_proxy(output_bytes) if output_bytes is not None
                                 else unavailable('no_validated_result')),
            'actual_tokens': (measurement(explicit['runtime_output_tokens'], MEASURED, 'runtime_reported_usage')
                              if 'runtime_output_tokens' in explicit else unavailable('runtime_did_not_report_field')),
        },
        'runtime': {**runtime, 'model': model, 'model_status': MEASURED if model else NOT_AVAILABLE,
                    'model_reason': None if model else 'runtime_did_not_report_model'},
        'reuse': {
            'previous_state_reused': unavailable('no_existing_deterministic_reuse_marker'),
            'previous_finding_reused': unavailable('no_existing_deterministic_reuse_marker'),
            'derived_state_reused': unavailable('no_existing_deterministic_reuse_marker'),
            'cache_hit': measurement(1 if recovered else 0, MEASURED, 'durable_spool_recovery_flag'),
        },
        'delta': {'new_material_delta_present': unavailable('no_existing_deterministic_delta_marker')},
        'accounting': {
            'model_call_count': measurement(0 if recovered or backend != 'CodexRoleExecutor' or not model_dispatched else 1,
                                            MEASURED, 'dispatch_lifecycle'),
            'failed_call_count': measurement(1 if failed else 0, MEASURED, 'dispatch_lifecycle'),
            'pending_unreconciled_usage': measurement(1 if pending_usage else 0, MEASURED, 'dispatch_lifecycle'),
        },
        'quota': unavailable('token_usage_is_not_account_quota_usage'),
    }


def validate(record):
    if type(record) is not dict or record.get('schema_version') != SCHEMA_VERSION or record.get('authoritative') is not False:
        raise ValueError('TELEMETRY_SCHEMA')
    identity = record.get('identity', {})
    if not identity.get('execution_id') or not identity.get('task_id') or not identity.get('context_digest'):
        raise ValueError('TELEMETRY_IDENTITY')
    for group in ('context', 'output', 'runtime', 'reuse', 'accounting'):
        if type(record.get(group)) is not dict:
            raise ValueError('TELEMETRY_SCHEMA')
    return record


def task_summary(records):
    unique = {}
    for record in records:
        validate(record)
        unique.setdefault((record['identity']['execution_id'],record['identity']['attempt']), record)
    llm_records=[r for r in unique.values() if r['execution_kind']=='LLM' and
                 r['accounting']['model_call_count']['value']==1]
    estimated = [((r['prompt']['bytes']['value'] + 3) // 4) +
                 (r['output']['estimated_tokens']['value'] or 0)
                 for r in llm_records if r['prompt']['bytes']['status']==MEASURED]
    actual_fields = [(r['runtime']['runtime_input_tokens'], r['runtime']['runtime_output_tokens'])
                     for r in unique.values() if r['execution_kind'] == 'LLM']
    actual_available = bool(actual_fields) and all(a['status'] == b['status'] == MEASURED for a, b in actual_fields)
    return {
        'execution_count': len(unique),
        'model_call_count': sum(r['accounting']['model_call_count']['value'] for r in unique.values()),
        'failed_call_count': sum(r['accounting']['failed_call_count']['value'] for r in unique.values()),
        'pending_unreconciled_usage': any(r['accounting']['pending_unreconciled_usage']['value'] for r in unique.values()),
        'cumulative_estimated_llm_prompt_output_tokens': measurement(sum(estimated), ESTIMATED, 'sum_unique_dispatched_llm_byte_proxies'),
        'cumulative_actual_runtime_tokens': (measurement(sum(a['value'] + b['value'] for a, b in actual_fields), MEASURED, 'sum_runtime_reported_usage')
                                              if actual_available else unavailable('one_or_more_llm_executions_lack_runtime_usage')),
    }
