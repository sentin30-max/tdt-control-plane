from .roles import make_context


def project(resolution, task, role, execution_id):
    """Select declared material inputs; never pass a repository or conversation."""
    names = task["required_claims"]
    selected = {name: resolution["resolved"][name] for name in names}
    if any(c["status"] != "RESOLVED" for c in selected.values()):
        raise ValueError("UNRESOLVED_DEPENDENCY")
    refs = {s for c in selected.values() for s in c["sources"]} | {"mapping_contract"}
    inputs = {"claims": selected, "requirements": task["requirements"], "work": task["work"],
              "source_evidence": {name:resolution['source_excerpts'][name] for name in names},
              "open_decisions": [d for d in resolution["open_decisions"] if d["scope"] in task["relevant_scopes"]]}
    if role == "ADVISOR":
        inputs["review_target"] = task["review_target"]
        inputs["permitted_destinations"] = task["permitted_destinations"]
    elif role == "DEVELOPMENT":
        inputs["specification_contract"] = ["requirements", "steps", "acceptance", "prohibitions", "open_questions"]
    else:
        inputs["implementation_specification"] = task["implementation_specification"]
    return make_context(execution_id, task["task_id"], resolution["revision"], role,
                        resolution["scope"], task["objective"], inputs,
                        {k: resolution["source_digests"][k] for k in sorted(refs)}, resolution["protected"])
