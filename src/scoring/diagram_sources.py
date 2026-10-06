"""Small ownership adapters for the shared diagram extractor.

These helpers consume server-loaded, validated review/source state. They are
not APIs: neither filesystem paths nor bounds are accepted from a browser.
"""
from .diagram_regions import DiagramRegionExtractor, visual_elements, _contains, _near
from .question_source_ownership import owned_native_ids
from .review_document import _source_owner


def question_diagram_candidates(service, review_id, node_key, revision):
    review = service._review(review_id)
    if review.current_revision != revision:
        raise ValueError("diagram_revision_conflict")
    _, store, automatic, ir = service._draft(review.draft_id)
    snapshot = service._revision(review, store).snapshot
    nodes = snapshot["nodes"]
    node = next((n for n in nodes if n["stable_key"] == node_key and n.get("included")), None)
    if node is None:
        raise ValueError("diagram_target_not_found")
    by_key = {n["stable_key"]: n for n in nodes}
    owner = _source_owner(node, by_key)
    figures = {r["region_id"]: r for r in automatic.get("figure_regions", [])}
    ids, unresolved = owned_native_ids(node, nodes, automatic, ir)
    if unresolved:
        raise ValueError("diagram_shared_source_unresolved")
    ownership, exclusions = {}, {}
    for item in node["ordered_content"]:
        if item["type"] != "figure_region":
            continue
        rid = item["region_id"]
        region = figures.get(rid)
        if region is None or region.get("assigned_question_key") != owner:
            raise ValueError("diagram_source_boundary")
        other_owners = [n for n in nodes if n["stable_key"] != node_key and n.get("included")
                        and any(i.get("type") == "figure_region" and i.get("region_id") == rid
                                for i in n["ordered_content"])]
        if other_owners:
            # Existing review format has exclusive figure items. Do not invent
            # shared ownership until an explicit shared reference is available.
            raise ValueError("diagram_shared_source_unresolved")
        page = next(p for p in ir["pages"] if p["page_index"] == region["page_index"])
        selected = [e["element_id"] for e in visual_elements(page)
                    if e.get("bbox") and _contains(region["bbox"], e["bbox"])]
        ownership.setdefault(page["page_index"], []).extend(selected)
    for page in ir["pages"]:
        index = page["page_index"]
        ownership.setdefault(index, []).extend(i for i in ids
            if any(e["element_id"] == i for e in page["elements"]))
        exclusions[index] = [e["element_id"] for e in visual_elements(page)
                             if e["element_id"] not in ownership[index]]
    engine = DiagramRegionExtractor(store.path("source.pdf"), ir, store)
    return engine, engine.candidates(domain="question", target_key=node_key,
                                     ownership=ownership, exclusions=exclusions)


def model_answer_diagram_candidates(source, ir, store, *, entry, question_regions):
    """Use persisted spatial assignment, never a nearest-text/sibling guess."""
    qid = entry.get("question_id")
    if not qid or entry.get("source", {}).get("kind") == "teacher_manual":
        raise ValueError("diagram_source_mapping_missing")
    regions = [r for r in question_regions if r.get("question_id") == qid]
    if not regions:
        raise ValueError("diagram_source_mapping_missing")
    ownership, exclusions = {}, {}
    for page in ir["pages"]:
        index = page["page_index"]
        own = [r for r in regions if r["page_index"] == index]
        sibling = [r for r in question_regions if r["page_index"] == index
                   and r.get("question_id") != qid and r.get("depth", 0) >= min(
                       (r.get("depth", 0) for r in own), default=0)]
        ids = []
        for element in visual_elements(page):
            box = element.get("bbox")
            if not box:
                continue
            inside = [r for r in own if _contains([r["left"], r["top"], r["right"], r["bottom"]], box)]
            competing = [r for r in sibling if _near([r["left"], r["top"], r["right"], r["bottom"]], box)]
            if len(inside) == 1 and not competing:
                ids.append(element["element_id"])
        # Existing source segments provide immutable native label references.
        labels = {i for s in entry.get("source", {}).get("segments", [])
                  if s.get("page_index") == index for i in s.get("element_ids", [])}
        ownership[index] = ids + sorted(labels)
        exclusions[index] = [e["element_id"] for e in visual_elements(page) if e["element_id"] not in ids]
    engine = DiagramRegionExtractor(source, ir, store)
    return engine, engine.candidates(domain="model_answer", target_key=qid,
                                     ownership=ownership, exclusions=exclusions)
