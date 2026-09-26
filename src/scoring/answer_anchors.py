"""Question-native page anchors resolved through confirmed review provenance."""
import json
import re
from pathlib import Path

from sqlalchemy import select

from .db.models import TestQuestion, TestQuestionAsset
from .coordinate import validate_bbox
from .pdf_native import canonical_hash


def _figure_canvas_bbox(asset_path, page_bbox):
    """Find the dominant lower-page figure component in a question asset.

    The figure asset is question-side evidence.  Its pixel connected
    component is used only to tighten the printed canvas bbox; no student
    pixels, answer text, or model answer are consulted.
    """
    try:
        import pymupdf
        pix = pymupdf.Pixmap(str(asset_path))
        if pix.width < 8 or pix.height < 8:
            return list(page_bbox)
        step = max(1, min(pix.width, pix.height) // 300)
        grid = set()
        for gy in range(pix.height // step):
            if gy * step < pix.height * 0.42:
                continue
            for gx in range(pix.width // step):
                off = ((gy * step) * pix.width + gx * step) * pix.n
                if sum(pix.samples[off:off + 3]) / 3 < 200:
                    grid.add((gx, gy))
        seen, components = set(), []
        for origin in grid:
            if origin in seen:
                continue
            stack, seen_local = [origin], {origin}
            while stack:
                x, y = stack.pop()
                for nx in range(x - 1, x + 2):
                    for ny in range(y - 1, y + 2):
                        p = (nx, ny)
                        if p in grid and p not in seen_local:
                            seen_local.add(p)
                            stack.append(p)
            seen.update(seen_local)
            components.append(seen_local)
        if not components:
            return list(page_bbox)
        comp = max(components, key=len)
        xs, ys = zip(*comp)
        local = [min(xs) * step, min(ys) * step,
                 min(pix.width, (max(xs) + 1) * step),
                 min(pix.height, (max(ys) + 1) * step)]
        return validate_bbox([
            page_bbox[0] + (local[0] / pix.width) * (page_bbox[2] - page_bbox[0]),
            page_bbox[1] + (local[1] / pix.height) * (page_bbox[3] - page_bbox[1]),
            page_bbox[0] + (local[2] / pix.width) * (page_bbox[2] - page_bbox[0]),
            page_bbox[1] + (local[3] / pix.height) * (page_bbox[3] - page_bbox[1]),
        ], 'normalized')
    except Exception:
        return list(page_bbox)


def question_anchors(session, test_id, root):
    questions = list(session.scalars(select(TestQuestion).where(TestQuestion.test_id == test_id)))
    anchors = []
    anchors_by_question_id = {}
    boundaries = []
    child_layout = []
    for q in questions:
        provenance = q.provenance or {}
        paths = list(Path(root).glob(
            f"*/review/{provenance.get('review_id')}/revisions/{provenance.get('revision', 0):06d}.json"))
        if len(paths) != 1:
            raise ValueError('QUESTION_NATIVE_ANCHOR_PROVENANCE_MISSING')
        document = json.loads(paths[0].read_text())
        nodes = [n for n in document['nodes'] if n['review_node_id'] == provenance['review_node_id']]
        if len(nodes) != 1:
            raise ValueError('QUESTION_NATIVE_ANCHOR_AMBIGUOUS')
        content = nodes[0]['ordered_content']
        pages = {x.get('page_index', 0) for x in content if x.get('bbox')}
        # Teacher-confirmed child nodes may intentionally contain only a
        # semantic label (their native geometry belongs to the structural
        # parent).  An empty set therefore means "inherit parent geometry",
        # not a multipage anchor.  A non-empty set with another page remains
        # an explicit multipage mapping error.
        if pages and pages != {0}:
            raise ValueError('MULTIPAGE_ANCHOR_REQUIRES_PAGE_SELECTION')
        native_path = paths[0].parents[3] / 'native/pages/page-0001.json'
        native = json.loads(native_path.read_text())
        elements = {e['element_id']: e for e in native['elements']}
        boxes = []
        canvases = []
        for item in content:
            if item['type'] == 'figure_region':
                box = item['bbox']
                if item.get('coordinate_space') != 'normalized':
                    box = [box[0]/native['width'], box[1]/native['height'],
                           box[2]/native['width'], box[3]/native['height']]
                canvases.append(validate_bbox(box, 'normalized'))
                continue
            for eid in item.get('source_element_ids', []):
                e = elements.get(eid)
                if e and e.get('bbox') and (e.get('native_text') or '').strip():
                    b = e['bbox']
                    boxes.append([b[0]/native['width'], b[1]/native['height'],
                                  b[2]/native['width'], b[3]/native['height']])
        if not boxes:
            parent_anchor = anchors_by_question_id.get(q.parent_id)
            if parent_anchor is None:
                raise ValueError(f'QUESTION_NATIVE_ANCHOR_MISSING:{q.id}')
            # Semantic child nodes often have no native source element of
            # their own.  Never copy the parent's answer/search rectangle:
            # resolve the printed child label in the native page and defer a
            # distinct answer band to the layout pass below.
            terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}",
                               getattr(q, 'question_text', '') or '')
            label = None
            for element in native['elements']:
                text = (element.get('native_text') or '').strip()
                if not text or not element.get('bbox'):
                    continue
                if terms and any(term.lower() in text.lower() for term in terms):
                    label = element
                    break
            if label is None:
                # Japanese-only labels still have stable printed substrings;
                # use the longest non-punctuation run as a layout hint.
                text = getattr(q, 'question_text', '') or ''
                jp = [x for x in re.findall(r"[\u3040-\u30ff\u3400-\u9fff]{3,}", text)]
                for element in native['elements']:
                    native_text = (element.get('native_text') or '').strip()
                    if native_text and any(x in native_text for x in jp):
                        label = element
                        break
            if label is None:
                raise ValueError(f'QUESTION_NATIVE_CHILD_LABEL_MISSING:{q.id}')
            lb = label['bbox']
            label_box = [lb[0]/native['width'], lb[1]/native['height'],
                         lb[2]/native['width'], lb[3]/native['height']]
            geometry = {'question_ref': q.id, 'question_id': q.id,
                        'question_number': q.question_number, 'bbox': label_box,
                        'printed_bboxes': [label_box], 'canvas_bboxes': [],
                        'native_page_sha256': canonical_hash(native),
                        'review_revision_sha256': provenance['revision_sha256'],
                        'geometry_source': 'question_layout_child_label',
                        'parent_question_id': q.parent_id,
                        'child_label_bbox': label_box}
            anchors.append(geometry)
            anchors_by_question_id[q.id] = geometry
            child_layout.append((q, geometry, parent_anchor))
            continue
        box = [min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes)]
        boundaries.append(box)
        geometry = {'question_ref': q.id, 'question_id': q.id,
                    'question_number': q.question_number, 'bbox': box,
                    'printed_bboxes': boxes, 'canvas_bboxes': canvases,
                    'native_page_sha256': canonical_hash(native),
                    'review_revision_sha256': provenance['revision_sha256']}
        figure = session.scalar(select(TestQuestionAsset).where(
            TestQuestionAsset.question_id == q.id,
            TestQuestionAsset.asset_type == 'figure'))
        if figure:
            extraction_root = paths[0].parents[3]
            figure_path = extraction_root / figure.artifact_ref
            page_bbox = (figure.provenance or {}).get('bbox')
            if figure_path.is_file() and page_bbox:
                geometry['canvas_bboxes'] = [_figure_canvas_bbox(figure_path, page_bbox)]
                geometry['geometry_source'] = 'question_visual_asset_layout'
        # Keep structural parents available as geometry sources for semantic
        # child nodes whose teacher-confirmed content has no native bbox.
        anchors_by_question_id[q.id] = geometry
        if q.is_gradable:
            anchor = geometry
            anchors.append(anchor)
            anchors_by_question_id[q.id] = anchor
    # Derive independent child answer bands from the ordered printed labels.
    # The band is bounded by the previous/next label (or the parent/next
    # question), never by student ink or model-answer content.
    groups = {}
    for q, geometry, parent in child_layout:
        groups.setdefault(parent['question_id'], []).append((q, geometry, parent))
    for members in groups.values():
        members.sort(key=lambda x: float(x[0].sort_order or 0))
        parent = members[0][2]
        label_floor = max(item[1]['child_label_bbox'][3] for item in members)
        # Other gradable children (for example Q2.1) also appear in
        # ``boundaries``.  They are inside this parent's layout and must not
        # become the end of the final child band; choose the next external
        # question boundary after all printed child labels.
        next_questions = [v[1] for v in boundaries if v[1] > label_floor]
        group_bottom = min(next_questions, default=1.0)
        for index, (q, geometry, _) in enumerate(members):
            label = geometry['child_label_bbox']
            if index == 0:
                # Include the printed label's baseline-to-following answer
                # slot.  A model bbox may touch the label edge; ownership
                # validation below distinguishes that small boundary contact
                # from a mixed printed/handwritten region.
                top = max(parent['bbox'][3], label[1])
            else:
                previous = members[index - 1][1]['child_label_bbox']
                top = max(label[1], previous[3])
            bottom = (members[index + 1][1]['child_label_bbox'][1]
                      if index + 1 < len(members) else group_bottom)
            # Keep a meaningful positive band even when adjacent printed
            # labels touch; never emit the former one-pixel inherited box.
            if bottom - top < 0.012:
                bottom = min(group_bottom, top + 0.04)
            x0, x1 = parent['bbox'][0], parent['bbox'][2]
            geometry['layout_search_bbox'] = validate_bbox([x0, top, x1, bottom], 'normalized')
        # A sibling with a native prompt (usually the first child) must end
        # where the first semantic child label begins, rather than inheriting
        # the whole parent-to-next-question span.
        parent_id = members[0][2]['question_id']
        first_label_top = members[0][1]['child_label_bbox'][1]
        # The current anchor list has no ORM parent field.  The first native
        # child boundary is the only boundary between Q2.1 and label Q2.2;
        # narrow the immediately preceding child by its sort position.
        for q in questions:
            if q.parent_id == parent_id and str(q.question_number).endswith('.1'):
                for sibling in anchors:
                    if sibling.get('question_id') == q.id:
                        sb = sibling['search_bbox'] if 'search_bbox' in sibling else [0, sibling['bbox'][3], 1, first_label_top]
                        sibling['layout_search_bbox'] = validate_bbox([sb[0], sb[1], sb[2], first_label_top], 'normalized')
                        sibling['search_bbox'] = sibling['layout_search_bbox']

    for a in anchors:
        b = a['bbox']
        below = [v[1] for v in boundaries if v[1] > b[3]]
        bottom = min(below, default=1.0)
        # A drawing beside a calculation shares its vertical band. Include
        # the registered canvas, and constrain horizontal search at that canvas.
        right = 1.0
        for other in anchors:
            if other is a:
                continue
            for canvas in other['canvas_bboxes']:
                if canvas[1] <= b[3] < canvas[3] and canvas[0] > b[2]:
                    right = min(right, canvas[0])
        a['search_bbox'] = validate_bbox(a.get('layout_search_bbox', [0.0, b[3], right, bottom]), 'normalized')
        if a['canvas_bboxes']:
            # Visual-primary questions search the resolved graph canvas itself;
            # the text below the printed prompt is not an answer substitute.
            a['search_bbox'] = validate_bbox(a['canvas_bboxes'][0], 'normalized')
        a['all_printed_bboxes'] = boundaries
    return anchors
