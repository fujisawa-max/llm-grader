"""Visual expression bands independent of native text segmentation."""
from collections import Counter
import math
import re

from .math_source_tokens import canonical_math_letters


def math_like(text):
    text = canonical_math_letters(text)
    return bool(re.search(r'[=+^_−×÷∑∫√²³]|\\(?:frac|sqrt)|\b(?:TP|FP|TN|FN)\b', text)) or bool(re.fullmatch(r'\s*(?:[\d.]+|[A-Za-zα-ω])\s*', text))


def union_box(items):
    boxes = [item['bbox'] for item in items]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def aligned_atoms(segments, text, *, alignment_mode='line'):
    if alignment_mode not in {'line', 'source_fragment'}:
        raise ValueError('math_source_invalid')
    ordered = sorted(segments, key=lambda s: s.get('reading_order', 0))
    counts = Counter(s.get('original_text', s.get('text', '')) for s in ordered)
    def pattern(value):
        if alignment_mode == 'line':
            return r'(?m)^'+re.escape(value)+r'$'
        # A Question's native spans can occur inside an editable prose line.
        # Exact source characters only, with lexical boundaries: never match
        # a numeral inside another number or identifier.
        # Japanese prose may adjoin a separately anchored mathematical span
        # without a space. Still forbid substrings inside Latin/Greek math
        # identifiers, styled Latin identifiers, decimals and larger numbers.
        token_chars = r'A-Za-z0-9_.\u0370-\u03ff\U0001d400-\U0001d6a5'
        left = r'(?<!['+token_chars+r'])' if re.match(r'[\w.]', value[0]) else ''
        right = r'(?!['+token_chars+r'])' if re.match(r'[\w.]', value[-1]) else ''
        return left+re.escape(value)+right
    matches_by_text = {value: list(re.finditer(pattern(value), text))
                       for value in counts if value.strip()}
    anchors = {i: matches_by_text.get(s.get('original_text', s.get('text', '')), [])[0]
               for i, s in enumerate(ordered)
               if len(matches_by_text.get(s.get('original_text', s.get('text', '')), [])) == 1
               and counts[s.get('original_text', s.get('text', ''))] == 1}
    atoms = []
    for order, segment in enumerate(ordered):
        original = segment.get('original_text', segment.get('text', ''))
        box = segment.get('bbox')
        if not original.strip() or not math_like(original) or not box:
            continue
        if len(box) != 4 or not all(type(v) in (int, float) and math.isfinite(v) for v in box) or box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError('math_source_invalid')
        matches = matches_by_text.get(original, [])
        # Scope by immutable neighboring anchors even when the global count
        # happens to match. Otherwise a deleted numeral can borrow an identical
        # token from another expression. Rank repeated tokens in source order
        # only inside this verified interval; never invent an editing span.
        previous = max((i for i in anchors if i < order), default=-1)
        following = min((i for i in anchors if i > order), default=len(ordered))
        lower = anchors[previous].end() if previous >= 0 else 0
        upper = anchors[following].start() if following < len(ordered) else len(text)
        scoped = [m for m in matches if lower <= m.start() and m.end() <= upper]
        source_occurrences = [i for i in range(previous+1, following)
            if ordered[i].get('original_text', ordered[i].get('text', '')) == original]
        if len(scoped) != len(source_occurrences):
            continue
        match = scoped[source_occurrences.index(order)]
        atoms.append({'id': segment['id'], 'page_index': segment['page_index'], 'bbox': list(box),
                      'start': match.start(), 'end': match.end(), 'original_text': original,
                      'reading_order': segment.get('reading_order', order)})
    return atoms


def connected(a, b, *, loose=False):
    if a['page_index'] != b['page_index']:
        return False
    x, y = a['bbox'], b['bbox']
    h = min(x[3]-x[1], y[3]-y[1])
    vertical_overlap = min(x[3], y[3])-max(x[1], y[1])
    horizontal_gap = max(0, max(x[0], y[0])-min(x[2], y[2]))
    vertical_gap = max(0, max(x[1], y[1])-min(x[3], y[3]))
    centers = abs((x[1]+x[3]-y[1]-y[3])/2)
    def complete(value):
        return bool(re.match(r"^\s*[A-Za-z]+\s*=", canonical_math_letters(value)))
    if complete(a["original_text"]) and complete(b["original_text"]):
        return False
    if vertical_overlap >= .35*h or centers <= h:
        return horizontal_gap <= (60 if loose else 32)
    # A fraction/subscript has overlapping x-ranges but distinct vertical layers.
    overlap_x = min(x[2], y[2])-max(x[0], y[0])
    return overlap_x > 0 and vertical_gap <= (18 if loose else 10) and centers <= (2.6 if loose else 1.8)*h


def region_from_atoms(atoms, method='geometry', confidence=None):
    ordered = sorted(atoms, key=lambda a: a['start'])
    return {'page_index': atoms[0]['page_index'], 'bbox': union_box(atoms),
            'start': ordered[0]['start'], 'end': ordered[-1]['end'],
            'source_spans': [dict(a) for a in ordered], 'segment_ids': [a['id'] for a in ordered],
            'original_text': '\n'.join(a['original_text'] for a in ordered),
            'grouping_method': method, 'grouping_confidence': confidence, 'ricoh_used': method != 'geometry'}


def source_regions(segments, text, *, alignment_mode='line'):
    atoms = aligned_atoms(segments, text, alignment_mode=alignment_mode)
    if len(atoms) > 128:
        raise ValueError("math_region_limit")
    groups = []
    for atom in atoms:
        hits = []
        for index, group in enumerate(groups):
            for member in group:
                lo, hi = sorted((atom, member), key=lambda a: a['start'])
                gap = text[lo['end']:hi['start']]
                for other in atoms:
                    if lo['end'] <= other['start'] and other['end'] <= hi['start']:
                        gap = gap.replace(other['original_text'], '', 1)
                if not gap.strip() and connected(atom, member):
                    hits.append(index)
                    break
        if not hits:
            groups.append([atom])
        else:
            merged = [atom]
            for index in reversed(hits):
                merged.extend(groups.pop(index))
            groups.append(merged)
    regions = sorted((region_from_atoms(group) for group in groups), key=lambda r: r['start'])
    # Loose neighboring bands are not merged without vision confirmation.
    for region in regions:
        region['grouping_ambiguous'] = sum(bool(re.match(r'^\s*[A-Za-z]+\s*=', canonical_math_letters(a['original_text']))) for a in region['source_spans']) > 1 or any(
            region is not other and any(connected(a, b, loose=True) for a in region['source_spans'] for b in other['source_spans'])
            for other in regions)
    return regions


def validate_groups(value, atoms):
    if not isinstance(value, dict) or set(value) != {'groups'} or not isinstance(value['groups'], list) or not value['groups']:
        raise ValueError('math_ricoh_grouping_rejected')
    by_id = {a['id']: a for a in atoms}
    seen, regions = set(), []
    for group in value['groups']:
        if not isinstance(group, dict) or set(group) != {'segment_ids', 'confidence'}:
            raise ValueError('math_ricoh_grouping_rejected')
        ids, confidence = group['segment_ids'], group['confidence']
        if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in by_id or i in seen for i in ids)
                or len(set(ids)) != len(ids) or type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not .85 <= confidence <= 1):
            raise ValueError('math_ricoh_grouping_rejected')
        members = [by_id[i] for i in ids]
        if len({a['page_index'] for a in members}) != 1:
            raise ValueError('math_ricoh_grouping_rejected')
        # Every member must connect through the bounded geometry neighborhood.
        reached = [members[0]]
        remaining = members[1:]
        while remaining:
            next_atom = next((a for a in remaining if any(connected(a, b, loose=True) for b in reached)), None)
            if next_atom is None:
                raise ValueError('math_ricoh_grouping_rejected')
            reached.append(next_atom)
            remaining.remove(next_atom)
        seen.update(ids)
        regions.append(region_from_atoms(members, 'ricoh_assisted_repair', confidence))
    # Missing IDs cannot silently remove source fragments.
    if seen != set(by_id):
        raise ValueError('math_ricoh_grouping_rejected')
    return sorted(regions, key=lambda r: r['start'])


def grouping_schema(atoms):
    ids = list(dict.fromkeys(a['id'] for a in atoms))
    return {'type': 'object', 'additionalProperties': False, 'required': ['groups'], 'properties': {
        'groups': {'type': 'array', 'minItems': 1, 'maxItems': len(ids), 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['segment_ids', 'confidence'],
            'properties': {'segment_ids': {'type': 'array', 'minItems': 1, 'maxItems': len(ids),
                'items': {'type': 'string', 'enum': ids}},
                'confidence': {'type': 'number', 'minimum': .85, 'maximum': 1}}}}}}


def safe_geometry_cluster(cluster, editing_text, *, alignment_mode='line'):
    """Independent strict-geometry proof; never trust a broken vision JSON."""
    atoms = [a for region in cluster for a in region['source_spans']]
    if editing_text is None:
        return None
    reconstructed = source_regions(atoms, editing_text, alignment_mode=alignment_mode)
    if (len(reconstructed) != 1 or reconstructed[0]['grouping_ambiguous']
            or len(reconstructed[0]['source_spans']) != len(atoms)
            or set(reconstructed[0]['segment_ids']) != {a['id'] for a in atoms}):
        return None
    return reconstructed[0]
