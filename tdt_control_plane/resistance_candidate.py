"""Exact authorized candidate transformation, independently checked against executor output."""
import copy
import json
from pathlib import Path

from .contracts import digest
from .resistance_sources import BASELINE, DOSSIER, INPUT_NAME, REQUEST_NAME, sha

OLD_BINDING=BASELINE+'-resistance-a4-hybrid-v1'
NEW_BINDING=BASELINE+'-resistance-a4-two-stage-v1'
REPLACEMENTS = [
    (OLD_BINDING,NEW_BINDING),
    ('refutation_valid boolean or "not_evaluable"; ',''),
    ('Do not emit global_state or any final A4 classification;',
     'Do not emit refutation_valid, refutation_validity, global_state or any final A4 classification;'),
    ('code resolver tef_a4_resolution version 1 has sole authority to derive a state when unambiguous.',
     'Code derives refutation validity (version 1) first, then tef_a4_resolution (version 1) derives A4 state only when unambiguous. UNRESOLVED_CONTRADICTION or UNRESOLVED_NORMATIVE_AMBIGUITY means non-consumable, no published global_state, no automatic retry and no raw rewrite.'),
]
REQUEST_UPDATES = {
    'request_id':'RESISTANCE-AUDIT-REQUEST-46828C1658B5-A4-TWO-STAGE-V1-01',
    'result_directory':'two-stage-v1-01-results',
    'a3_instance_id':'RESISTANCE-A3-NOT-INCLUDED-TWO-STAGE-V1',
    'a4_instance_id':'RESISTANCE-INDEPENDENT-INSTANCE-A4-TWO-STAGE-V1-46828C1658B5',
    'a4_independent_instance_id':'RESISTANCE-INDEPENDENT-INSTANCE-A4-TWO-STAGE-V1-46828C1658B5',
    'a4_assignee':'GROQ_FREE/openai/gpt-oss-120b:A4:RESISTANCE-INDEPENDENT-INSTANCE-A4-TWO-STAGE-V1-46828C1658B5',
    'a4_input':INPUT_NAME, 'refutation_validity_version':'1',
}


def specification(sources):
    return {'action':'Prepare a NEW candidate request and input in Control Plane, not in Trader.',
            'request_updates':REQUEST_UPDATES, 'input_literal_replacements':REPLACEMENTS,
            'preserve':'Every other request field and every other input character. Do not compact or truncate.',
            'requested_artifact':{'request':'complete resulting JSON object','input_text':'complete resulting input string'},
            'versions':{'refutation_validity':'1','a4_resolver':'1'},
            'stage':'A4 only; A3 skipped; A5 not authorized',
            'verification':'Independent exact comparison, published local validators, actual full evidence materialization and native token preflight.',
            'prohibited':['Groq call','A4 execution','A5 execution','historical reprocessing','source modification','silent evidence reduction'],
            'authority':'Explicit PO Slice 002 correction and authorization, recorded by digest; A4 architecture publication already completed.'}


def expected_candidate(sources):
    request=json.loads(sources['texts']['historical_request'])
    request.update(copy.deepcopy(REQUEST_UPDATES))
    text=sources['texts']['historical_input']
    for before,after in REPLACEMENTS:
        if text.count(before)!=1:
            raise ValueError('SOURCE_TRANSFORMATION_NOT_APPLICABLE')
        text=text.replace(before,after)
    return {'request':request,'input_text':text}


def validate_candidate(artifact,sources):
    if type(artifact) is not dict or set(artifact)!={'request','input_text'} or digest(artifact)!=digest(expected_candidate(sources)):
        raise ValueError('CANDIDATE_CONTRACT_MISMATCH')
    return True


def materialize_candidate(root,artifact,sources):
    validate_candidate(artifact,sources)
    folder=Path(root)/'candidates/slice002'/DOSSIER
    folder.mkdir(parents=True,exist_ok=True)
    files={REQUEST_NAME:(json.dumps(artifact['request'],ensure_ascii=False,indent=2)+'\n').encode(),
           INPUT_NAME:artifact['input_text'].encode()}
    snapshot=Path(sources['snapshot'])/DOSSIER
    for field in ['evidence_manifest','a1_input','a2_input','a3_input','a5_input_schema']:
        name=artifact['request'][field]
        if Path(name).name!=name:
            raise ValueError('UNSAFE_SUPPORT_PATH')
        files[name]=(snapshot/name).read_bytes()
    for name,raw in files.items():
        path=folder/name
        if path.exists() and path.read_bytes()!=raw:
            raise ValueError('CANDIDATE_IDENTITY_CONTRADICTION')
        if not path.exists():
            with path.open('xb') as f:f.write(raw)
    return {'request_path':(folder/REQUEST_NAME).relative_to(root).as_posix(),
            'input_path':(folder/INPUT_NAME).relative_to(root).as_posix(),
            'files':{name:sha(raw) for name,raw in files.items()},'candidate_digest':digest(artifact),
            'authoritative':False,'activated':False}
