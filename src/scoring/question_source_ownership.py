"""Resolve validated review slices to whole native elements, never guessed bboxes."""
from .review_document import _content_evidence, _source_owner


def owned_native_ids(node, nodes, automatic, ir):
    owner = _source_owner(node, {n['stable_key']: n for n in nodes})
    original = next((n for n in automatic['nodes'] if n['stable_key'] == owner), {})
    canonical = original.get('ordered_content', [])
    regions = {r['region_id']: r for r in automatic.get('formula_regions', [])}
    native = {e['element_id']: e for p in ir['pages'] for e in p['elements']}
    result, unresolved = [], []
    for item in node['ordered_content']:
        if item['type'] not in {'text', 'formula_region'}:
            continue
        for anchor in [item, *(item.get('merged_source_segments') or [])]:
            ids = anchor.get('source_element_ids') or []
            if anchor.get('type') == 'formula_region':
                region = regions.get(anchor.get('region_id'), {})
                if region.get('assigned_question_key') != owner:
                    unresolved.extend(ids)
                    continue
                ids = ids or region.get('source_element_ids', [])
            source_slice = anchor.get('source_slice')
            if source_slice is None:
                result.extend(ids)
                continue
            matches = [i for i in canonical if i.get('type') == 'text'
                       and _content_evidence(i) == _content_evidence(anchor)]
            if len(matches) != 1:
                unresolved.extend(ids)
                continue
            source = matches[0]['text']
            if (len(source_slice) != 3 or source_slice[2] != len(source)
                    or not 0 <= source_slice[0] < source_slice[1] <= len(source)):
                unresolved.extend(ids)
                continue
            # Walk immutable source in native reading order. Repeated short
            # values are occurrences, not globally unique string identities.
            ordered = sorted(ids, key=lambda key: (native.get(key, {}).get('reading_order', 0), ids.index(key)))
            cursor = 0
            for identifier in ordered:
                text = native.get(identifier, {}).get('native_text', '')
                start = source.find(text, cursor) if text else -1
                if start < 0:
                    unresolved.append(identifier)
                    continue
                end = start + len(text)
                cursor = end
                if source_slice[0] <= start and end <= source_slice[1]:
                    result.append(identifier)
                elif max(start, source_slice[0]) < min(end, source_slice[1]):
                    unresolved.append(identifier)
    return list(dict.fromkeys(result)), list(dict.fromkeys(unresolved))


def review_source_regions(nodes, automatic, ir):
    """Current reviewed ownership for PDF highlights, including untouched figures."""
    native = {e['element_id']: (p['page_index'], e) for p in ir['pages'] for e in p['elements']}
    figures = {r['region_id']: r for r in automatic.get('figure_regions', [])}
    result = {}
    for node in nodes:
        ids, _ = owned_native_ids(node, nodes, automatic, ir)
        boxes = [{'page_index': native[i][0], 'bbox': native[i][1]['bbox']}
                 for i in ids if i in native and native[i][1].get('bbox')]
        for item in node['ordered_content']:
            if item['type'] == 'figure_region' and item.get('region_id') in figures:
                r = figures[item['region_id']]
                boxes.append({'page_index': r['page_index'], 'bbox': r['bbox']})
        result[node['stable_key']] = boxes
    return result
