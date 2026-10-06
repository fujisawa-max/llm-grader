"""Server-loaded ownership adapters for the shared diagram extractor."""
from copy import deepcopy

from .diagram_regions import DiagramRegionExtractor, visual_elements, _contains, _near
from .pdf_native import native_vector_elements, sha256_file
from .question_source_ownership import owned_native_ids
from .review_document import _source_owner
from .vision_policy import page_space


def visual_ir(source, ir):
    """Read legacy path geometry without rewriting immutable extraction IR."""
    if sha256_file(source) != ir['source']['sha256']:
        raise ValueError('diagram_source_integrity_error')
    result = deepcopy(ir)
    if any('vector_elements' not in p for p in result['pages']):
        import pymupdf
        with pymupdf.open(source) as doc:
            for p in result['pages']:
                actual = doc[p['page_index']]
                if list(actual.cropbox) != p['cropbox'] or actual.rotation != p['rotation']:
                    raise ValueError('diagram_source_integrity_error')
                if 'vector_elements' not in p:
                    p['vector_elements'] = native_vector_elements(actual.get_drawings(), p['page_index'])
    return result


def question_bounds(nodes, automatic, ir):
    """Exclusive vertical bands from retained native occurrences after split.

    Overlapping owners/atomic slices have no exclusive band. Reparenting does
    not change the native order. Text equality and local edited text are unused.
    """
    by_id = {e['element_id']: (p['page_index'], e) for p in ir['pages'] for e in p['elements']}
    anchors, unresolved = {}, set()
    figures = {r['region_id']: r for r in automatic.get('figure_regions', [])}
    for node in nodes:
        key = node['stable_key']
        if not node.get('included'):
            unresolved.add(key)
        ids, shared = owned_native_ids(node, nodes, automatic, ir)
        if shared:
            unresolved.add(key)
        # Even unresolved/excluded native spans reserve their spatial boundary;
        # otherwise a neighbor could grow into evidence it cannot own.
        for identifier in list(dict.fromkeys(ids + shared)):
            if identifier in by_id and by_id[identifier][1].get('bbox'):
                index, e = by_id[identifier]
                anchors.setdefault(index, []).append((e['bbox'][1], key, e['bbox']))
        for item in node['ordered_content']:
            if item.get('type') == 'figure_region' and item.get('region_id') in figures:
                r = figures[item['region_id']]
                anchors.setdefault(r['page_index'], []).append((r['bbox'][1], key, r['bbox']))
    result = {n['stable_key']: {} for n in nodes}
    for page in ir['pages']:
        index = page['page_index']
        rows = sorted(anchors.get(index, []), key=lambda a: (a[0], a[1]))
        runs = []
        for top, key, box in rows:
            if runs and runs[-1][1] == key:
                runs[-1][2] = max(runs[-1][2], box[3])
            else:
                runs.append([top, key, box[3]])
        for i, (top, key, bottom) in enumerate(runs):
            bound = page_space(page).cropbox
            end = runs[i+1][0] if i+1 < len(runs) else bound[3]
            if key in unresolved or bottom > end or (i and runs[i-1][2] > top):
                continue
            result[key].setdefault(index, []).append([bound[0], top, bound[2], end])
    return result


def question_diagram_candidates(service, review_id, node_key, revision, *, snapshot_override=None, grouping=None):
    review = service._review(review_id)
    if review.current_revision != revision:
        raise ValueError('diagram_revision_conflict')
    _, store, automatic, ir = service._draft(review.draft_id)
    snapshot = snapshot_override or service._revision(review, store).snapshot
    ir = visual_ir(store.path('source.pdf'), ir)
    nodes = snapshot['nodes']
    node = next((n for n in nodes if n['stable_key'] == node_key and n.get('included')), None)
    if node is None:
        raise ValueError('diagram_target_not_found')
    owner = _source_owner(node, {n['stable_key']: n for n in nodes})
    figures = {r['region_id']: r for r in automatic.get('figure_regions', [])}
    ids, unresolved = owned_native_ids(node, nodes, automatic, ir)
    if unresolved:
        raise ValueError('diagram_shared_source_unresolved')
    all_bounds = question_bounds(nodes, automatic, ir)
    bounds = deepcopy(all_bounds.get(node_key, {}))
    ownership, exclusions = {}, {}
    legacy = []
    for item in node['ordered_content']:
        if item['type'] != 'figure_region':
            continue
        rid = item['region_id']
        region = figures.get(rid)
        if region is None or region.get('assigned_question_key') != owner:
            raise ValueError('diagram_source_boundary')
        if any(n['stable_key'] != node_key and n.get('included') and any(
                i.get('type') == 'figure_region' and i.get('region_id') == rid for i in n['ordered_content'])
                for n in nodes):
            raise ValueError('diagram_shared_source_unresolved')
        legacy.append(region)
        # Figure-only historical nodes still have a bounded source anchor.
        if not bounds.get(region['page_index']):
            bounds.setdefault(region['page_index'], []).append(region['bbox'])
    if not ids and legacy:
        bounds = {}
        for r in legacy:
            p = next(p for p in ir['pages'] if p['page_index'] == r['page_index'])
            limit = page_space(p).cropbox
            b = r['bbox']
            bounds.setdefault(r['page_index'], []).append([max(0, b[0]-6), max(0, b[1]-6),
                min(limit[2], b[2]+6), min(limit[3], b[3]+6)])
    for page in ir['pages']:
        index = page['page_index']
        ownership[index] = [e['element_id'] for e in visual_elements(page) if e.get('bbox')
            and any(_contains(b, e['bbox']) for b in bounds.get(index, []))
            and not any(_contains(b, e['bbox']) for key, mapping in all_bounds.items()
                        if key != node_key for b in mapping.get(index, []))]
        ownership[index].extend(i for i in ids if any(e['element_id'] == i for e in page['elements']))
        exclusions[index] = [e['element_id'] for e in visual_elements(page) if e['element_id'] not in ownership[index]]
    engine = DiagramRegionExtractor(store.path('source.pdf'), ir, store)
    engine.allowed_bounds = bounds
    engine.ownership_key = {'bounds': bounds, 'ids': {i: sorted(set(v)) for i, v in ownership.items()}, 'review_id': review_id}
    engine.legacy_figures = legacy
    engine.blocked_bounds = {p['page_index']: [e['bbox'] for e in p['elements'] if e.get('bbox')
        and e.get('type') == 'text' and e['element_id'] not in ids
        and len((e.get('native_text') or '').strip()) > 12] for p in ir['pages']}
    return engine, engine.candidates(domain='question', target_key=node_key,
                                     ownership=ownership, exclusions=exclusions, grouping=grouping)


def model_answer_diagram_candidates(source, ir, store, *, entry, question_regions, grouping=None):
    """Only persisted spatial assignment, never a nearest-text/sibling guess."""
    qid = entry.get('question_id')
    if not qid:
        raise ValueError('diagram_source_mapping_missing')
    regions = [r for r in question_regions if r.get('question_id') == qid]
    if not regions:
        raise ValueError('diagram_source_mapping_missing')
    ir = visual_ir(source, ir)
    ownership, exclusions, bounds, blocked = {}, {}, {}, {}
    for page in ir['pages']:
        index = page['page_index']
        own = [r for r in regions if r['page_index'] == index]
        sibling = [r for r in question_regions if r['page_index'] == index
                   and r.get('question_id') != qid and r.get('depth', 0) >= min(
                       (r.get('depth', 0) for r in own), default=0)]
        bounds[index] = [[r['left'], r['top'], r['right'], r['bottom']] for r in own]
        blocked[index] = [[r['left'], r['top'], r['right'], r['bottom']] for r in sibling]
        ids = [e['element_id'] for e in visual_elements(page) if e.get('bbox')
            and sum(_contains(b, e['bbox']) for b in bounds[index]) == 1
            and not any(_near(b, e['bbox']) for b in blocked[index])]
        labels = {i for s in entry.get('source', {}).get('segments', [])
                  if s.get('page_index') == index for i in s.get('element_ids', [])}
        if not entry.get('source', {}).get('segments'):
            labels = {e['element_id'] for e in page['elements'] if e.get('bbox')
                      and sum(_contains(b, e['bbox']) for b in bounds[index]) == 1
                      and not any(_near(b, e['bbox']) for b in blocked[index])}
        ownership[index] = ids + sorted(labels)
        exclusions[index] = [e['element_id'] for e in visual_elements(page) if e['element_id'] not in ids]
    engine = DiagramRegionExtractor(source, ir, store)
    engine.allowed_bounds, engine.blocked_bounds = bounds, blocked
    engine.ownership_key = {'bounds': bounds, 'blocked': blocked, 'entry_id': entry.get('id', qid)}
    engine.legacy_figures = []
    return engine, engine.candidates(domain='model_answer', target_key=qid,
                                     ownership=ownership, exclusions=exclusions, grouping=grouping)
