"""Teacher-selected, single-page Answer crops with immutable server provenance."""
import json
import re

from .diagram_regions import DiagramRegionExtractor, POLICY, _box, _contains, write_diagram_json
from .pdf_native import canonical_hash
from .vision_policy import page_space


class ManualPdfDiagramReview:
    def __init__(self, source, ir, store, owner):
        self.engine = DiagramRegionExtractor(source, ir, store)
        self.engine.crop_policy = {**POLICY, "figure_margin": 0, "max_figure_page_ratio": 1}
        self.owner = owner
        self.context = canonical_hash({'type': 'manual_pdf_crop', 'source': ir['source'], 'owner': owner})

    def create(self, page_index, bbox):
        page = next((p for p in self.engine.ir['pages'] if p['page_index'] == page_index), None)
        if page is None or type(page_index) is not int:
            raise ValueError('diagram_crop_outside_page')
        bbox = _box(bbox)
        if not _contains(page_space(page).cropbox, bbox):
            raise ValueError('diagram_crop_outside_page')
        identity = {'source': self.engine.ir['source'], 'owner': self.owner, 'page': page_index, 'bbox': bbox}
        identifier = 'diagram-' + canonical_hash(identity)[:24]
        candidate = {'id': identifier, 'domain': 'model_answer', 'target_key': self.owner,
            'page_index': page_index, 'bbox': bbox, 'automatic_bbox': bbox,
            'source_sha256': self.engine.ir['source']['sha256'],
            'material_id': self.engine.ir['source']['material_id'],
            'source_ir_sha256': canonical_hash(self.engine.ir), 'source_element_ids': [],
            'source_type': 'manual_pdf_crop', 'grouping_method': 'teacher_manual_pdf_crop',
            'confidence': 1, 'ricoh_used': False, 'status': 'resolved'}
        # Render/validate before caching. No native grouping or inference is invoked.
        self.engine.crop(candidate)
        write_diagram_json(self.engine.store, f'diagrams/manual/{identifier}.json',
            {'context': self.context, 'identity': identity, 'candidate': candidate})
        return self.record(identifier)

    def candidate(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'diagram-[0-9a-f]{24}', identifier):
            raise ValueError('diagram_candidate_not_found')
        try:
            value = json.loads(self.engine.store.path(f'diagrams/manual/{identifier}.json').read_text())
        except (OSError, ValueError) as exc:
            raise ValueError('diagram_candidate_not_found') from exc
        if (value['context'] != self.context or value['identity']['source'] != self.engine.ir['source']
                or value['identity']['owner'] != self.owner
                or identifier != 'diagram-' + canonical_hash(value['identity'])[:24]):
            raise ValueError('diagram_source_stale')
        candidate = value['candidate']
        if candidate['automatic_bbox'] != value['identity']['bbox'] or candidate['page_index'] != value['identity']['page']:
            raise ValueError('diagram_source_stale')
        return candidate

    def record(self, identifier, *, state='candidate', final_bbox=None, revision=1, teacher_confirmed=False):
        if state not in {'candidate', 'accepted', 'excluded'}:
            raise ValueError('diagram_invalid_decision')
        value = self.engine.crop(self.candidate(identifier), final_bbox=final_bbox)
        page = next(p for p in self.engine.ir['pages'] if p['page_index'] == value['page_index'])
        bounds = page_space(page).cropbox
        result = {**value, 'context_sha256': self.context, 'revision': revision, 'state': state,
            'scope': 'manual', 'source_question_id': self.owner, 'assigned_question_id': self.owner,
            'trust_state': 'trusted', 'teacher_confirmed': state == 'accepted',
            'trust_state_at_accept': 'trusted' if state == 'accepted' else None,
            'acceptance_method': 'teacher_manual_pdf_crop' if state == 'accepted' else None,
            'page_width': bounds[2], 'page_height': bounds[3], 'page_rotation': page['rotation']}
        from .diagram_review import FIELDS
        return {k: v for k, v in result.items() if k in FIELDS}

    def validate(self, records, revision):
        from .diagram_review import FIELDS
        result = []
        for record in records:
            if record.get('state') == 'accepted' and record.get('teacher_confirmed') is not True:
                raise ValueError('diagram_teacher_confirmation_required')
            canonical = self.record(record['id'], state=record.get('state', 'candidate'),
                final_bbox=record.get('final_bbox'), revision=revision)
            if set(record)-set(FIELDS) or any(record.get(k) != canonical.get(k) for k in
                    ('context_sha256', 'source_sha256', 'material_id', 'page_index',
                     'automatic_bbox', 'source_type', 'target_key', 'source_question_id', 'assigned_question_id')):
                raise ValueError('diagram_source_stale')
            result.append(canonical)
        return result

    def preview(self, record):
        write_diagram_json(self.engine.store,
            f'diagrams/previews/{self.context}/{record["id"]}/{record["crop_sha256"]}.json', record)
        return record

    def preview_path(self, identifier, crop_sha=None):
        bbox = None
        if crop_sha is not None:
            if not re.fullmatch(r'[0-9a-f]{64}', crop_sha):
                raise ValueError('diagram_candidate_not_found')
            try:
                record = json.loads(self.engine.store.path(
                    f'diagrams/previews/{self.context}/{identifier}/{crop_sha}.json').read_text())
                bbox = record.get('final_bbox')
            except (OSError, ValueError) as exc:
                raise ValueError('diagram_candidate_not_found') from exc
        canonical = self.record(identifier, final_bbox=bbox)
        if crop_sha is not None and canonical['crop_sha256'] != crop_sha:
            raise ValueError('diagram_source_stale')
        return self.engine.store.path(canonical['artifact_ref'])
