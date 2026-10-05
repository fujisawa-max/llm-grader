"""Question review source adapter. No OCR, inference or persistence logic."""
from copy import deepcopy

from .review_document import ReviewError, _content_evidence


def item_reference(item):
    return {**_content_evidence(item), 'type': item['type'],
            **{k: deepcopy(item[k]) for k in ('source_slice', 'merged_source_segments') if k in item}}


def item_ids(item):
    result = list(item.get('source_element_ids') or [])
    for segment in item.get('merged_source_segments') or []:
        result.extend(segment.get('source_element_ids') or [])
    return list(dict.fromkeys(result))


def question_math_source(service, review_id, node_key, item_index, revision, expected_source):
    review = service._review(review_id)
    if review.current_revision != revision:
        raise ReviewError('revision_conflict', 409)
    draft, store, automatic, ir = service._draft(review.draft_id)
    current = service._revision(review, store)
    if current.snapshot['source_draft_sha256'] != draft.draft_sha256:
        raise ReviewError('source_draft_mismatch', 409)
    node = next((n for n in current.snapshot['nodes'] if n['stable_key'] == node_key), None)
    if node is None or not node.get('included'):
        raise ReviewError('math_question_target_not_found', 404)
    items = node['ordered_content']
    if item_index is None:
        reference = {'items': [item_reference(it) for it in items]}
    elif 0 <= item_index < len(items) and items[item_index]['type'] in {'text', 'formula_region'}:
        reference = item_reference(items[item_index])
    else:
        raise ReviewError('math_question_source_missing', 422)
    if reference != expected_source:
        raise ReviewError('math_question_source_stale', 409)
    from .question_source_ownership import owned_native_ids
    nodes = current.snapshot['nodes']
    owned, unresolved = owned_native_ids(node, nodes, automatic, ir)
    if item_index is None:
        ids = owned
    else:
        target = {**node, 'ordered_content': [items[item_index]]}
        ids, _ = owned_native_ids(target, nodes, automatic, ir)
    if not ids:
        raise ReviewError('math_question_source_boundary' if unresolved else 'math_question_source_missing', 422)
    for other in nodes:
        if other['stable_key'] == node_key or not other.get('included'):
            continue
        other_ids, shared = owned_native_ids(other, nodes, automatic, ir)
        if set(ids) & set(other_ids + shared):
            raise ReviewError('math_question_source_boundary', 422)
    # Reviewed ownership is derived from immutable anchors and nonoverlapping
    # source slices, not from all evidence of the original automatic ancestor.
    allowed = set(owned)
    by_id = {e['element_id']: (page['page_index'], e) for page in ir['pages'] for e in page['elements']}
    segments = []
    for identifier in ids:
        page_index, element = by_id.get(identifier, (None, None))
        if element is None or element['type'] != 'text' or not element.get('bbox'):
            raise ReviewError('math_question_source_missing', 422)
        segments.append({'id': identifier, 'original_text': element.get('native_text', ''),
            'page_index': page_index, 'bbox': deepcopy(element['bbox']),
            'reading_order': element.get('reading_order', ids.index(identifier))})
    segments.sort(key=lambda value: (value['page_index'], value['reading_order'], value['id']))
    ids = [segment['id'] for segment in segments]
    exclusions = [{'page_index': page_index, 'bbox': deepcopy(element['bbox'])}
        for identifier, (page_index, element) in by_id.items()
        if identifier not in allowed and element['type'] == 'text' and element.get('bbox')]
    return store.path('source.pdf'), segments, {
        'kind': 'question_review', 'review_id': review.id, 'node_key': node_key,
        'review_node_id': node['review_node_id'], 'revision': revision, 'item_index': item_index if item_index is not None else 0,
        'target': 'question_content' if item_index is None else 'item', 'unresolved_source_ids': unresolved,
        'material_id': ir['source']['material_id'], 'source_sha256': ir['source']['sha256'],
        'source_ir_sha256': draft.source_ir_sha256, 'source_segment_ids': ids}, exclusions


# Compact teacher-applied metadata only; no images or raw model response.
def compact_provenance(result):
    from hashlib import sha256
    source = result['source']
    return {'review_id': source['review_id'], 'node_key': source['node_key'],
        'revision': source['revision'], 'item_index': source['item_index'],
        'material_id': source['material_id'], 'source_sha256': source['source_sha256'],
        'source_ir_sha256': source['source_ir_sha256'], 'profile': result['profile'], 'model': result['model'],
        'original_text_sha256': sha256(result['original_text'].encode()).hexdigest(),
        'normalized_text_sha256': sha256(result['normalized_text'].encode()).hexdigest(),
        'regions': [{k: r.get(k) for k in ('page_index', 'bbox', 'crop_bbox', 'segment_ids',
            'original_text', 'grouping_method', 'normalization_method', 'ornith_used', 'validation')}
            for r in result.get('math_regions', [])]}


def validate_math_edits(edits, node, draft, nodes):
    """Bound provenance to this node's immutable source; reject debug payloads."""
    import json
    from pydantic import BaseModel, ConfigDict, Field, ValidationError
    class Region(BaseModel):
        model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
        page_index: int = Field(ge=0, strict=True)
        bbox: list[float] = Field(min_length=4, max_length=4)
        crop_bbox: list[float] = Field(min_length=4, max_length=4)
        segment_ids: list[str] = Field(min_length=1, max_length=128)
        original_text: str = Field(max_length=12000)
        grouping_method: str = Field(max_length=128)
        normalization_method: str = Field(max_length=128)
        ornith_used: bool
        validation: str = Field(pattern='^accepted$')
    class Edit(BaseModel):
        model_config = ConfigDict(extra='forbid')
        review_id: str = Field(max_length=128)
        node_key: str = Field(max_length=128)
        revision: int = Field(ge=1, strict=True)
        item_index: int = Field(ge=0, strict=True)
        material_id: str = Field(max_length=128)
        source_sha256: str = Field(pattern='^[0-9a-f]{64}$')
        source_ir_sha256: str = Field(pattern='^[0-9a-f]{64}$')
        original_text_sha256: str = Field(pattern='^[0-9a-f]{64}$')
        normalized_text_sha256: str = Field(pattern='^[0-9a-f]{64}$')
        profile: str = Field(max_length=128)
        model: str = Field(max_length=512)
        regions: list[Region] = Field(min_length=1, max_length=8)
    if not isinstance(edits, list) or len(edits) > 16 or len(json.dumps(edits)) > 100000:
        raise ReviewError('math_question_provenance_invalid', 422)
    from .review_document import _source_owner
    owner = _source_owner(node, {n['stable_key']: n for n in nodes})
    original = next((n for n in draft['nodes'] if n['stable_key'] == owner), {})
    allowed = {i for item in original.get('ordered_content', []) for i in item_ids(item)}
    region_ids = {item.get('region_id') for item in original.get('ordered_content', [])}
    allowed.update(i for r in draft.get('formula_regions', []) if r['region_id'] in region_ids for i in r.get('source_element_ids', []))
    try:
        for record in edits:
            value = Edit.model_validate(record)
            if value.node_key != node['stable_key'] or value.source_ir_sha256 != draft['source_ir_sha256']:
                raise ValueError()
            if any(not set(region.segment_ids) <= allowed for region in value.regions):
                raise ValueError()
    except (ValidationError, ValueError, TypeError):
        raise ReviewError('math_question_provenance_invalid', 422) from None


def validate_math_edit_source(edit, ir):
    """Applied metadata cannot claim coordinates/text absent from native IR."""
    from .math_region_grouping import union_box
    by_id = {e['element_id']: (page, e) for page in ir['pages'] for e in page['elements']}
    seen = set()
    for region in edit['regions']:
        ids = region['segment_ids']
        if len(set(ids)) != len(ids) or set(ids) & seen or any(i not in by_id for i in ids):
            raise ReviewError('math_question_provenance_invalid', 422)
        seen.update(ids)
        evidence = [by_id[i] for i in ids]
        if any(page['page_index'] != region['page_index'] or e['type'] != 'text' for page, e in evidence):
            raise ReviewError('math_question_provenance_invalid', 422)
        box = union_box([e for _, e in evidence])
        page = evidence[0][0]
        crop = [max(0, box[0]-6), max(0, box[1]-6),
                min(page['width'], box[2]+6), min(page['height'], box[3]+6)]
        if (any(abs(a-b) > 1e-4 for a, b in zip(box, region['bbox'])) or
                any(abs(a-b) > 1e-4 for a, b in zip(crop, region['crop_bbox'])) or
                region['original_text'] != '\n'.join(e.get('native_text', '') for _, e in evidence)):
            raise ReviewError('math_question_provenance_invalid', 422)
