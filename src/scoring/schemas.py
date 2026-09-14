"""Response schemas for llama.cpp's constrained JSON generation."""


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def array(items, minimum=0, maximum=None):
    value = {"type": "array", "items": items, "minItems": minimum}
    if maximum is not None:
        value["maxItems"] = maximum
    return value


def response_schema(materials):
    string = {"type": "string"}
    nonempty = {"type": "string", "minLength": 1}
    boolean = {"type": "boolean"}
    if materials.get("task") == "locate":
        question = {"enum": [q["question_id"] for q in materials["questions"]]}
        return obj({"page_id": {"const": materials["page_id"]},
                    "questions": array(obj({"question_id": question,
                        "status": {"enum": ["located", "blank", "no_math", "unreadable"]},
                        "reason": nonempty}), 1),
                    "regions": array(obj({"region_id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]+$"},
                        "question_id": question, "kind": {"enum": ["math", "graph", "text"]},
                        "bbox": array({"type": "integer", "minimum": 0, "maximum": 1000}, 4, 4),
                        "description": nonempty}), 0, 32), "needs_review": boolean})
    if "question_id" not in materials:
        return obj({"page_id": {"const": materials["page_id"]}, "student_id": string,
                    "name": string, "text": string,
                    "uncertainties": array(obj({"location": nonempty,
                                                "candidates": array(string), "reason": nonempty}))})
    page_id = {"enum": list(materials["ocr"])}
    evidence = array({"oneOf": [obj({"page_id": page_id, "quote": nonempty}),
                                 obj({"page_id": page_id, "visual_observation": nonempty})]}, 1)
    qid = {"const": materials["question_id"]}
    if "rubric" in materials:
        criteria = materials["rubric"]["criteria"]
        alternatives = [obj({
            "criterion_id": {"const": c["criterion_id"]},
            "score": {"enum": [level["score"] for level in c["levels"]] + [None]},
            "max_score": {"const": c["max_score"]}, "evidence": evidence, "reason": nonempty,
        }) for c in criteria]
        return obj({"question_id": qid,
                    "criteria": array({"oneOf": alternatives}, len(criteria), len(criteria)),
                    "needs_review": boolean, "review_reasons": array(nonempty)})
    return obj({"question_id": qid, "transcript": nonempty, "evidence": evidence,
                "uncertainties": array(obj({"page_id": page_id, "location": nonempty,
                                            "candidates": array(string), "reason": nonempty})),
                "changes": array(obj({"page_id": page_id, "before": string,
                                       "after": string, "reason": nonempty})),
                "needs_review": boolean})
