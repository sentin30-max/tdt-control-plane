"""TC-03 offline-only positive-selection projections and equivalence gates."""
import copy
import json

from .contracts import digest
from .context_manifest import applicable, build_manifest
from .telemetry import serialized_json_bytes

POLICY_VERSION = "tc03-offline-projection-v1"
BUILDER_VERSION = "1"
GATE_VERSION = "tc03-equivalence-gates-v1"
GATE_IDS = tuple(f"EG-{n:02d}" for n in range(1, 13))


def _parts(selector):
    return [p.replace("~1", "/").replace("~0", "~") for p in selector.strip("/").split("/") if p]


def _get(document, selector):
    value = document
    for part in _parts(selector):
        value = value[part]
    return value


def _delete(document, selector):
    parts = _parts(selector); parent = document
    for part in parts[:-1]: parent = parent[part]
    del parent[parts[-1]]


def _set(document, selector, value):
    parts = _parts(selector); parent = document
    for part in parts[:-1]: parent = parent[part]
    parent[parts[-1]] = copy.deepcopy(value)


def _survivor_value(context, survivor, original):
    value = _get(context, survivor["selector"])
    if survivor["source_digest"] == digest(original):
        return copy.deepcopy(value), "EXACT_COPY_V1"
    if isinstance(original, str):
        encoded = json.dumps(value)
        if encoded == original:
            return encoded, "JSON_DEFAULT_SERIALIZATION_V1"
    raise ValueError("DUPLICATE_RECONSTRUCTION_ORACLE_FAILED")


def reconstruct(projected_context, ledger, original_units):
    """Apply accepted reversible ledger entries; used only by the offline oracle."""
    recovered = copy.deepcopy(projected_context)
    by_id = {u["unit_id"]: u for u in original_units}
    for entry in ledger:
        if entry["status"] != "ACCEPTED":
            continue
        survivor = by_id[entry["surviving_representation"]["unit_id"]]
        current = _get(recovered, survivor["selector"])
        value = json.dumps(current) if entry["reconstruction_rule"] == "JSON_DEFAULT_SERIALIZATION_V1" else current
        _set(recovered, entry["original_selector"], value)
    return recovered


def _closures(context):
    previous = context.get("inputs", {}).get("previous_material_result", {})
    result = previous.get("result", {}) if isinstance(previous, dict) else {}
    state = context.get("inputs", {}).get("state", {})
    return {
        "identity": {k: context.get(k) for k in ("task_id", "input_revision", "role", "scope")},
        "authority": context.get("authority"),
        "protection": {k: context.get(k) for k in ("protected", "done_when", "after_completion")},
        "adverse_findings": result.get("findings", []),
        "contracts": {"requested_artifact": context.get("inputs", {}).get("requested_artifact"),
                      "source_contract": context.get("inputs", {}).get("source_contract")},
        "state": state,
        "blockers": state.get("blocker"),
        "scope": context.get("scope"),
        "destinations": context.get("inputs", {}).get("applicable_destinations"),
        "contradictions": [x for x in result.get("findings", []) if "contradict" in str(x).lower()],
    }


def evaluate_gates(original, projected, ledger, units):
    recovered = reconstruct(projected, ledger, units)
    left, right = _closures(original), _closures(recovered)
    missing = []
    accepted_selectors = {x["original_selector"] for x in ledger if x["status"] == "ACCEPTED"}
    for unit in units:
        if unit["kind"] == "VALUE":
            try: _get(projected, unit["selector"])
            except (KeyError, TypeError):
                if unit["selector"] not in accepted_selectors: missing.append(unit["selector"])
    checks = {
        "EG-01": left["identity"] == right["identity"],
        "EG-02": left["authority"] == right["authority"],
        "EG-03": left["protection"] == right["protection"],
        "EG-04": left["adverse_findings"] == right["adverse_findings"],
        "EG-05": left["contracts"] == right["contracts"],
        "EG-06": recovered == original,
        "EG-07": left["state"] == right["state"],
        "EG-08": left["blockers"] == right["blockers"],
        "EG-09": left["scope"] == right["scope"] and left["destinations"] == right["destinations"],
        "EG-10": not missing and all(x.get("transformation_id") for x in ledger),
        "EG-11": recovered == original and all(x["reversible"] for x in ledger if x["status"] == "ACCEPTED"),
        "EG-12": recovered == original and left["contradictions"] == right["contradictions"],
    }
    return {gate: {"status": "PASS" if checks[gate] else "FAIL"} for gate in GATE_IDS}


def build_projection(context, manifest):
    """Build P1 by inclusion-by-default; exclusions require a deterministic duplicate proof."""
    if not applicable(manifest, context): raise ValueError("MANIFEST_NOT_APPLICABLE")
    units = manifest["context_units"]; by_id = {u["unit_id"]: u for u in units}
    projected = copy.deepcopy(context); ledger = []
    for unit in units:
        if unit["kind"] != "VALUE": continue
        candidate = unit["transport_form"] in {"DUPLICATED", "DERIVABLE", "REFERENCE_CANDIDATE"}
        if not candidate: continue
        status="REJECTED"; reason="default_keep_inline"; rule=None; survivor_record=None; oracle="NOT_RUN"; reversible=False
        transformation = ({"EXACT_DUPLICATE":"EXACT_DUPLICATE_ELISION", "STRUCTURAL_DUPLICATE":"STRUCTURAL_DUPLICATE_ELISION"}
                          .get(unit["confidence_basis"], "DERIVABLE_ELISION" if unit["transport_form"]=="DERIVABLE" else "REFERENCE_PROJECTION"))
        protected = unit["adverse_or_protective"] or unit["selector"].endswith("/findings") or "/blocker/" in unit["selector"]
        if unit["transport_form"] == "DUPLICATED" and unit["duplicates"] and not protected:
            survivor = by_id[unit["duplicates"][0]]
            try:
                original = _get(context, unit["selector"])
                rebuilt, rule = _survivor_value(context, survivor, original)
                if rebuilt == original and survivor["authority_class"] == unit["authority_class"]:
                    status="ACCEPTED"; reason="deterministic_same_authority_duplicate"; oracle="PASS"; reversible=True
                    survivor_record={"unit_id":survivor["unit_id"],"selector":survivor["selector"],"source_digest":survivor["source_digest"]}
                    _delete(projected, unit["selector"])
            except (KeyError, ValueError):
                reason="duplicate_reconstruction_oracle_failed"; oracle="FAIL"
        elif protected:
            reason="protective_or_adverse_material_kept_inline"
        elif unit["transport_form"] == "DERIVABLE":
            reason="identity_contract_requires_inline_materialization"
        elif unit["transport_form"] == "REFERENCE_CANDIDATE":
            reason="no_authorized_runtime_reference_resolver"
        ledger.append({
            "transformation_id":digest({"execution_id":context["execution_id"],"selector":unit["selector"],"policy":POLICY_VERSION}),
            "projection_id":None,"unit_id":unit["unit_id"],"source_ref":unit["source_ref"],"source_digest":unit["source_digest"],
            "original_selector":unit["selector"],"original_bytes":unit["byte_size"],"transformation_type":transformation,
            "reason":reason,"contract_or_equivalence_rule":rule,"surviving_representation":survivor_record,
            "reconstruction_rule":rule,"authority_check":"PASS" if status=="ACCEPTED" else "NOT_PROVEN",
            "protective_check":"PASS" if not protected or status!="ACCEPTED" else "FAIL",
            "evidence_check":"PASS" if status=="ACCEPTED" and reversible else "KEPT_INLINE",
            "oracle_result":oracle,"reversible":reversible,"status":status})
    projection_id=digest({"source":manifest["context_digest"],"projected":digest(projected),"policy":POLICY_VERSION})
    for entry in ledger: entry["projection_id"]=projection_id
    gates=evaluate_gates(context,projected,ledger,units)
    accepted=all(g["status"]=="PASS" for g in gates.values())
    original_bytes=serialized_json_bytes(context); projected_bytes=serialized_json_bytes(projected)
    needs=[]
    for u in units:
        if u["semantic_necessity"]=="NEEDS_CONTRACT_EVIDENCE":
            needs.append({"unit_id":u["unit_id"],"selector":u["selector"],"bytes":u["byte_size"],
                          "resolution":"UNRESOLVED_KEEP_INLINE","basis":"no existing contract permits non-materialization"})
    body={"schema_version":1,"policy_version":POLICY_VERSION,"builder_version":BUILDER_VERSION,
          "gate_version":GATE_VERSION,"projection_id":projection_id,"source_context_digest":manifest["context_digest"],
          "manifest_digest":manifest["manifest_digest"],"projection_digest":digest(projected),
          "authoritative":False,"operational":False,"dispatchable":False,"level":"P1_PROVEN_SAFE_REPRESENTATION",
          "projected_context":projected,"transformation_ledger":ledger,"equivalence_gates":gates,
          "needs_contract_evidence_resolution":needs,
          "byte_accounting":{"original_bytes":original_bytes,"projected_bytes":projected_bytes,
                             "removed_bytes":original_bytes-projected_bytes,"future_executor_context_bytes":projected_bytes},
          "projection_acceptance":"ACCEPTED" if accepted else "REJECTED"}
    body["shadow_metadata_bytes"]=0
    body["byte_accounting"]["added_metadata_bytes"]=0
    body["byte_accounting"]["net_bytes_including_shadow_metadata"]=0
    # Account for the complete wrapper, including these accounting fields.
    for _ in range(8):
        artifact_bytes=serialized_json_bytes(body)
        metadata_bytes=artifact_bytes-projected_bytes
        values=(metadata_bytes,metadata_bytes,original_bytes-artifact_bytes)
        current=(body["shadow_metadata_bytes"],body["byte_accounting"]["added_metadata_bytes"],
                 body["byte_accounting"]["net_bytes_including_shadow_metadata"])
        body["shadow_metadata_bytes"],body["byte_accounting"]["added_metadata_bytes"],body["byte_accounting"]["net_bytes_including_shadow_metadata"]=values
        if values==current: break
    return body
