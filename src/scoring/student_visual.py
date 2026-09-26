"""Immutable student drawing crops, indexed by existing materials and events.

No migration: TestMaterial holds bytes and DomainEvent holds exact ownership,
coordinates and provenance, as in student source registration.
"""
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from .coordinate import validate_bbox
from .core import write_json
from .db.models import DomainEvent, StudentSubmission, TestMaterial, TestQuestion
from .pdf_native import canonical_hash, sha256_file
from .regions import crop_image

ROLE = 'student_visual_answer'
EVENT = 'student_visual_answer_registered'


def safe_file(root, relative, sha):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or sha256_file(path) != sha:
        raise ValueError('VISUAL_ASSET_HASH_MISMATCH')
    return path


class StudentVisualAssetService:
    def __init__(self, session, root):
        self.s = session
        self.root = Path(root).resolve()

    def register(self, submission_id, question_id, bbox, *, source_sha, provenance, verified=False):
        box = validate_bbox(bbox, 'normalized')
        if min(box) < 0 or max(box) > 1:
            raise ValueError('INVALID_RICOH_COORDINATES')
        sub = self.s.get(StudentSubmission, submission_id)
        q = self.s.get(TestQuestion, question_id)
        if sub is None or q is None or q.test_id != sub.test_id or not q.is_gradable:
            raise ValueError('VISUAL_ASSET_OWNERSHIP_MISMATCH')
        material = self.s.get(TestMaterial, sub.material_id)
        if material is None or material.test_id != sub.test_id or material.sha256 != source_sha:
            raise ValueError('SOURCE_ANSWER_HASH_MISMATCH')
        source = Path(material.storage_ref).resolve()
        if not source.is_relative_to(self.root) or not source.is_file() or sha256_file(source) != source_sha:
            raise ValueError('SOURCE_ANSWER_HASH_MISMATCH')
        # Registration is idempotent across page-extraction retries.  A new
        # page artifact/provenance must not create a second visual answer for
        # the same immutable source crop.
        for event in self.s.scalars(select(DomainEvent).where(
                DomainEvent.event_type == EVENT,
                DomainEvent.entity_type == ROLE)):
            payload = event.payload or {}
            if (payload.get('submission_id') == submission_id
                    and payload.get('question_id') == question_id
                    and payload.get('source_sha256') == source_sha
                    and payload.get('bbox') == box):
                return self.get(event.entity_id, submission_id, question_id)
        key = canonical_hash({'submission': sub.id, 'question': q.id, 'source': source_sha,
                              'bbox': box, 'provenance': provenance, 'verified': verified})
        asset_id = str(uuid5(NAMESPACE_URL, ROLE + key))
        existing = self.s.get(TestMaterial, asset_id)
        if existing:
            return self.get(asset_id, sub.id, q.id)
        folder = self.root / 'student-visual' / sub.id / asset_id
        crop = crop_image(source, box, folder / 'crop.png', padding=0, coordinate_space='normalized')
        metadata = {'asset_id': asset_id, 'role': ROLE, 'test_id': sub.test_id,
                    'submission_id': sub.id, 'question_id': q.id, 'source_sha256': source_sha,
                    'source_material_id': material.id, 'bbox': box, 'coordinate_space': 'normalized',
                    'pixel_bbox': crop['bbox_pixels'], 'source_dimensions': crop['page_size'],
                    'sha256': crop['image_sha256'], 'mime_type': 'image/png',
                    'artifact_ref': str((folder / 'crop.png').relative_to(self.root)),
                    'review_required': not verified, 'provenance': provenance}
        metadata['metadata_sha256'] = canonical_hash(metadata)
        write_json(folder / 'metadata.json', metadata)
        self.s.add(TestMaterial(id=asset_id, test_id=sub.test_id, material_type=ROLE,
                                storage_ref=metadata['artifact_ref'], mime_type='image/png',
                                sha256=metadata['sha256'], original_filename='student-graph.png'))
        self.s.add(DomainEvent(entity_type=ROLE, entity_id=asset_id, event_type=EVENT, payload=metadata))
        self.s.flush()
        if sha256_file(source) != source_sha:
            raise ValueError('SOURCE_ANSWER_HASH_MISMATCH')
        return metadata

    def get(self, asset_id, submission_id, question_id):
        events = list(self.s.scalars(select(DomainEvent).where(
            DomainEvent.entity_id == asset_id, DomainEvent.event_type == EVENT)))
        mat = self.s.get(TestMaterial, asset_id)
        sub = self.s.get(StudentSubmission, submission_id)
        if len(events) != 1 or mat is None or sub is None:
            raise ValueError('STUDENT_VISUAL_ASSET_MISSING')
        value = events[0].payload
        if (value.get('submission_id') != sub.id or value.get('question_id') != question_id
                or value.get('test_id') != sub.test_id or mat.test_id != sub.test_id
                or mat.material_type != ROLE or value.get('role') != ROLE
                or mat.sha256 != value.get('sha256') or mat.storage_ref != value.get('artifact_ref')
                or value.get('metadata_sha256') != canonical_hash({k: v for k, v in value.items() if k != 'metadata_sha256'})):
            raise ValueError('VISUAL_ASSET_OWNERSHIP_MISMATCH')
        source = self.s.get(TestMaterial, sub.material_id)
        if source.sha256 != value['source_sha256'] or sha256_file(Path(source.storage_ref)) != source.sha256:
            raise ValueError('SOURCE_ANSWER_HASH_MISMATCH')
        safe_file(self.root, value['artifact_ref'], value['sha256'])
        return dict(value)

    def for_question(self, submission_id, question_id):
        # Multiple revisions must be explicitly resolved, never silently picked.
        events = self.s.scalars(select(DomainEvent).where(DomainEvent.event_type == EVENT))
        excluded = {e.entity_id for e in self.s.scalars(select(DomainEvent).where(
            DomainEvent.event_type == 'student_visual_answer_excluded'))
            if e.payload.get('submission_id') == submission_id and e.payload.get('question_id') == question_id}
        accepted = {e.entity_id for e in self.s.scalars(select(DomainEvent).where(
            DomainEvent.event_type == 'student_visual_answer_accepted'))
            if e.payload.get('submission_id') == submission_id and e.payload.get('question_id') == question_id}
        result = []
        seen_crops = set()
        for e in events:
            if e.entity_id in excluded or e.payload.get('submission_id') != submission_id or e.payload.get('question_id') != question_id:
                continue
            value = self.get(e.entity_id, submission_id, question_id)
            crop_key = (value.get('source_sha256'), tuple(value.get('bbox', [])))
            if crop_key in seen_crops:
                # Retry artifacts are immutable history, but identical source
                # crops resolve to one current evidence asset.
                continue
            seen_crops.add(crop_key)
            if e.entity_id in accepted:
                value['review_required'] = False
                value['teacher_accepted'] = True
                value['provenance'] = {**value.get('provenance', {}),
                                       'requires_reconstruction': False}
                # Acceptance is an append-only review decision. Recompute the
                # derived metadata hash on the transient bundle projection;
                # the immutable registration event remains unchanged.
                from .pdf_native import canonical_hash
                value['metadata_sha256'] = canonical_hash({k: v for k, v in value.items()
                                                            if k != 'metadata_sha256'})
            result.append(value)
        return result
