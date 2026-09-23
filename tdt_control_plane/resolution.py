"""Bounded fact-class resolver. No entity-specific precedence rules."""
import hashlib
from pathlib import Path

from .contracts import digest
from .roles import strict_json


class TraderSourceAdapter:
    """Reads a pinned export, never opens a writable Trader connection."""
    def __init__(self, root):
        self.root = Path(root)

    def load(self):
        manifest = strict_json((self.root / "sources.json").read_text(encoding="utf-8"))
        documents = {}
        for key, source in manifest["sources"].items():
            path = (self.root / source["file"]).resolve()
            if path.parent != self.root.resolve():
                raise ValueError("SOURCE_PATH")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise ValueError("HASH_MISMATCH")
            documents[key] = strict_json(raw)
        return manifest, documents


def pointer(document, path):
    for part in path.split("/"):
        document = document[part]
    return document


def derive_claims(manifest, documents, mapping):
    claims = []
    for item in mapping:
        source = item["source"]
        doc = documents[source]
        for field, expected in item.get("requires", {}).items():
            if pointer(doc, field) != expected:
                raise ValueError("SOURCE_CONTRACT_INVALID")
        claims.append({"id": item["id"], "subject": item["subject"], "fact_class": item["fact_class"],
                       "scope": item["scope"], "value": pointer(doc, item["pointer"]),
                       "authority": item["authority"], "source": source,
                       "source_revision": manifest["revision"], "source_digest": manifest["sources"][source]["sha256"],
                       "supersedes": item.get("supersedes", []), "authoritative": False})
    return claims


def resolve(claims, catalog, subject, fact_class, scope):
    applicable = []
    for c in claims:
        if (c["subject"], c["fact_class"], c["scope"]) != (subject, fact_class, scope):
            continue
        authority = catalog.get(c["authority"], {})
        if fact_class not in authority.get("fact_classes", []) or scope not in authority.get("scopes", []) or c["source"] not in authority.get("sources", []):
            continue
        applicable.append(c)
    ids = {c["id"] for c in applicable}
    superseded = {i for c in applicable for i in c["supersedes"] if i in ids}
    current = [c for c in applicable if c["id"] not in superseded]
    values = {digest(c["value"]) for c in current}
    status = "RESOLVED" if len(values) == 1 else "UNRESOLVED"
    return {"status": status, "value": current[0]["value"] if status == "RESOLVED" else None,
            "reason": "APPLICABLE_AUTHORITY_AND_SUPERSESSION" if status == "RESOLVED" else "MISSING_OR_CONTRADICTORY_SOURCE",
            "sources": sorted(c["source"] for c in current), "historical": sorted(superseded), "authoritative": False}


def next_action(scope, actions, blockers, decisions):
    relevant = [d for d in decisions if d["scope"] == scope and d["review_trigger_reached"]]
    if relevant:
        return {"status": "PO_DECISION_REQUIRED", "decisions": relevant, "authoritative": False}
    blocked = [b for b in blockers if scope in b["affected_scopes"]]
    if blocked:
        return {"status": "BLOCKED", "blockers": blocked, "authoritative": False}
    permitted = [a for a in actions if a["scope"] == scope and a["authorized"] and a["preconditions_met"]]
    return {"status": "DERIVABLE" if len(permitted) == 1 else "NONE" if not permitted else "UNRESOLVED", "candidates": permitted, "authoritative": False}


def load_fixture(root):
    manifest, docs = TraderSourceAdapter(root).load()
    config = strict_json((Path(root).parent / "mapping.json").read_text(encoding="utf-8"))
    if docs["consumption"]["consumption_basis"]["manifest_sha256"] != manifest["sources"]["manifest"]["sha256"]:
        raise ValueError("CONSUMPTION_HASH_MISMATCH")
    claims = derive_claims(manifest, docs, config["mapping"])
    resolution = {q["name"]: resolve(claims, config["authority_catalog"], q["subject"], q["fact_class"], q["scope"]) for q in config["queries"]}
    return {"authoritative": False, "revision": digest({"manifest": manifest, "config": config}),
            "source_revision": manifest["revision"], "source_digests": {**{k: v["sha256"] for k, v in manifest["sources"].items()}, "mapping_contract": digest(config)},
            "resolved": resolution, "open_decisions": config["open_decisions"],
            "protected": config["protected"], "scope": "control-plane-fixture",
            "limitations": ["Pinned fixture, not a live global Trader resolution", "No authority to execute Trader audits or mutate lifecycle"]}
