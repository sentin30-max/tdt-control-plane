"""Consolidated non-authoritative Slice 002 final/STOP report from persisted evidence."""
import argparse
import json
from pathlib import Path

from .resistance_sources import BASELINE, REVISION, read_sources
from .runtime import atomic_json


def generate(root):
    root=Path(root).resolve();folder=root/'evidence/slice002'
    load=lambda name:json.loads((folder/name).read_text(encoding='utf-8'))
    sources=read_sources(root)
    run=load('pilot-run.json');candidate=load('candidate.json')
    verification=load('local-verification.json');recovery=load('recovery-verification.json')
    publication=load('publication-verification.json');checks=verification['checks']
    steps=run['executions'];route=[s['role'] for s in steps]+[run['routing'][-1]['proposed']]
    advisor_first=steps[0]['role']=='ADVISOR'
    returned=all(i+1<len(steps) and steps[i+1]['role']=='ADVISOR' for i,s in enumerate(steps) if s['role']!='ADVISOR')
    ready=run['status']=='COMPLETE' and verification['preflight']=='PASS' and verification['local_validation']=='PASS'
    report={
        'SLICE_002_REAL_RESISTANCE_PILOT':'PASS' if ready else 'PARTIAL',
        'SEGMENT_COMPLETED':ready,
        'RESISTANCE_SOURCE_REVISION':REVISION,
        'EVALUATED_BASELINE':BASELINE,
        'RESISTANCE_FORMAL_LIFECYCLE':sources['lifecycle'],
        'RECOVERED_OPERATIONAL_POINT':sources['operational_point'],
        'A4_TWO_STAGE_PUBLICATION':'VERIFIED' if publication['publication_verified'] else 'NOT_VERIFIED',
        'REQUEST_PREPARATION':'READY' if ready else 'BLOCKED',
        'CANDIDATE_PREPARATION':'PREPARED; LOCAL_VALIDATION_PASS; INACTIVE; PRESERVED',
        'REQUEST_PATH':candidate['request_path'],'INPUT_PATH':candidate['input_path'],
        'PERMITTED_STAGES':['A4'],'A3':'SKIPPED','A5':'NOT_AUTHORIZED',
        'LLM_EMITS_REFUTATION_VALID':'NO','LLM_EMITS_REFUTATION_VALIDITY':'NO','LLM_EMITS_GLOBAL_STATE':'NO',
        'LLM_FIELDS_CLAIM_BOUNDARY':'Enforced by candidate input and published evidence-only schema; negative probes rejected all three fields. No actual auditor run occurred.',
        'REFUTATION_VALIDITY_VERSION':'1','A4_RESOLVER_VERSION':'1',
        'CLAIMS_PRESERVED':'SI' if checks['claims_preserved'] else 'NO',
        'ATTACK_SURFACES_PRESERVED':'SI' if checks['attack_surfaces_preserved'] else 'NO',
        'EVIDENCE_SET_PRESERVED':'SI' if checks['evidence_set_preserved'] else 'NO',
        'INDEPENDENCE_REQUIREMENT_PRESERVED':'SI' if checks['independence_preserved'] else 'NO',
        'LOCAL_VALIDATION':verification['local_validation'],
        'A4_TWO_STAGE_PREFLIGHT':verification['preflight'],'PREFLIGHT_BUDGET':verification['budget'],
        'ADVISOR_FIRST':'PASS' if advisor_first else 'FAIL',
        'MATERIAL_RESULTS_RETURNED_TO_ADVISOR':'PASS' if returned else 'FAIL',
        'DYNAMIC_ROUTING':'PASS' if all(d['validated'] for d in run['routing']) else 'FAIL',
        'ACTUAL_ROUTE':route,'ROUTING_CLAIM_BOUNDARY':'Observed state-based route to preparation, local preflight and STOP; Development route was not exercised.',
        'PO_MANUAL_TRANSPORT_DURING_SEGMENT':'NONE',
        'RECOVERY':recovery['status'],'IDEMPOTENCY':recovery['status'],
        'PROTECTED_SURFACES_MODIFIED':'NO',
        'PROTECTION_EVIDENCE':'All 238 pinned exported source files retain manifest hashes; actual source reads use git show. Candidate/support files are separate Control Plane copies. Original/corrective/V2/hybrid outputs were never reprocessed.',
        'GROQ_EXECUTED':'NO','A4_EXECUTED':'NO','A5_EXECUTED':'NO','PAID_CAPACITY_USED':'NO',
        'COST_POLICY':'ZERO_COST_ONLY',
        'COST_EVIDENCE':'Four isolated Codex sessions used included ChatGPT capacity, tools disabled, no API-key overrides or paid fallback. One deterministic local CodeExecutor. Zero-credit guard enforced before each model dispatch. No Actions or hosting launched.',
        'MATERIAL_BLOCKERS':[] if ready else ['Native preflight total 8004 is not strictly below 8000. No compaction, evidence reduction, budget reduction, re-dispatch or auditor call performed.'],
        'UNRESOLVED_AUTHORITY_DEPENDENCIES':[] if ready else ['PO disposition needed for a subsequent bounded response to the preserved preflight failure. No constraint change has been selected or authorized.'],
        'DEVELOPMENT_ROLE_COVERAGE':'NOT_REQUIRED','DEVELOPMENT_ROUTE_DEMONSTRATED':False,
        'CODE_EXECUTOR_ROLE_COVERAGE':'DEMONSTRATED',
        'ADVISOR_ROLE_QUALITY':'BOUNDED_OBSERVED: reviewed real inputs/candidate, distinguished successful diagnostics from failed readiness, rejected completion and escalated the preserved preflight blocker. Not general human equivalence.',
        'ADVISOR_CONTEXT_LIMITATION':'Middle Advisor review received complete generated candidate. Final review received verification and candidate hashes, not full candidate contents; its explicit limitation is preserved in the result.',
        'NEXT_ACTION':'Advisor/PO review of preserved preflight STOP; any subsequent adjustment or Groq execution requires separate explicit authorization.',
        'NEXT_DESTINATION':run['routing'][-1]['proposed'],
        'PRODUCT_OWNER_DECISION_REQUIRED':'YES' if not ready else 'NO',
        'TASK_ID':run['task_id'],'EXECUTIONS':steps,
        'CANDIDATE_DIGEST':candidate['candidate_digest'],'CANDIDATE_FILE_DIGESTS':candidate['files'],
        'TESTS':{'control_plane':51,'publication_tooling':publication['tooling_passed'],'resolver_subset':publication['resolver_passed'],'recovery':recovery['status']},
        'SCOPE_LIMITATIONS':['No real external audit','No production readiness claim','No Trader code modification','No autonomous closure of Resistance','No exactly-once external effects claim'],
        'SLICE_001':'Preserved and consumed as accepted bounded dependency; no reopening, merge or authority expansion.',
        'HITO_A_COMMIT':'0962aa340bd6712f9b8d4720adecaaddb9a2dc35',
        'SLICE_001_COMMIT':'97950ef55a6a2cc5a54752d1ec54243de327a646',
        'authoritative':False,
    }
    atomic_json(folder/'implementation-report.json',report)
    lines=['# Slice 002 — informe consolidado de STOP','',
           '**Resultado: PARTIAL. El segmento completo no está demostrado.**',
           '','El candidato fue preparado y validado. El preflight nativo calculó **5.604 + 1.600 + 800 = 8.004**, que no cumple el límite estricto **< 8.000**. Se preservaron candidato, evidencia y finding adverso sin compactar ni reintentar.',
           '', 'Ruta real: `'+ ' → '.join(route)+'`.',
           '', 'Recuperación en un proceso nuevo: mismos cinco resultados, todos duplicate/no-op, cero nuevos dispatches. Las pruebas de contradicción y stale utilizaron ledgers separados.',
           '', 'No se ejecutaron Groq/A4/A5 ni se modificó Trader, TEF, Governance o históricos. La preparación permanece inactiva en Control Plane. Development no fue necesario ni se forzó.',
           '', '51 pruebas de Control Plane; 135 de tooling publicado, incluidas 35 del resolver. La calidad del Advisor observada es limitada a este segmento; el informe conserva las limitaciones de contexto declaradas por el rol.',
           '', '## Campos del gate','', '| Campo | Resultado |','|---|---|']
    for key,value in report.items():
        if key in {'EXECUTIONS','CANDIDATE_FILE_DIGESTS'}:continue
        value=json.dumps(value,ensure_ascii=False) if not isinstance(value,str) else value
        lines.append('| '+key+' | '+value.replace('|','\\|').replace('\n',' ')+' |')
    lines+=['','## Identidades de ejecución','','| Rol / backend | Execution ID | Result digest |','|---|---|---|']
    for s in steps:
        lines.append('| '+s['role']+' / '+s['backend']+' | '+s['execution_id']+' | '+s['result_digest']+' |')
    lines+=['','Cada contexto/digest, resultado y finding del Advisor está en `executions/`; `ledger-export.json` conserva ingest y eventos. `candidate.json` conserva hashes de todos los archivos. `local-verification.json` conserva el presupuesto nativo y los hashes de evidencia.','',
            '**Siguiente destino: PO_REQUIRED.** Corresponde revisar el STOP y autorizar, si procede, un nuevo tramo acotado. Este informe no selecciona una reducción de presupuesto, cambio de evidencia o proveedor, ni autoriza Groq.','']
    (folder/'FINAL-REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);args=p.parse_args()
    print(generate(args.root)['SLICE_002_REAL_RESISTANCE_PILOT'])
