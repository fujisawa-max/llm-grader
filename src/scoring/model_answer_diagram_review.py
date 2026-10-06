"""Authorized diagram scopes and assignments over the shared review engine.

Source candidate identity belongs to its discovery owner, not to an answer
entry. Broad scopes are exposed only after narrower discovery is empty; no
scope discovery or assignment invokes persistence.
"""
from types import SimpleNamespace
import json

from .diagram_regions import DiagramRegionExtractor, visual_elements, _contains, _box, POLICY
from .vision_policy import crop_geometry
from .diagram_review import DiagramReview
from .diagram_sources import model_answer_diagram_candidates, visual_ir
from .model_answer_drafts import question_choices

ASSIGNMENT_FIELDS = ('scope', 'source_question_id', 'source_question_path', 'assigned_question_id')


class ModelAnswerDiagramReview:
    def __init__(self, source, ir, store, *, entry, question_regions, questions):
        self.source, self.ir, self.store = source, ir, store
        self.entry, self.regions = entry, question_regions
        self.questions = {q.id: q for q in questions}
        self.assigned = entry.get('question_id')
        if self.assigned not in self.questions or not self.questions[self.assigned].is_gradable:
            raise ValueError('diagram_source_mapping_missing')
        self.labels = {q['id']: q['label'] for q in question_choices([
            SimpleNamespace(id=q.id, parent_id=q.parent_id, display_label=q.display_label,
                question_number=q.question_number, sort_order=q.sort_order, is_gradable=True)
            for q in questions])}
        self.parents, seen = [], {self.assigned}
        current = self.questions[self.assigned].parent_id
        while current:
            if current in seen or current not in self.questions:
                raise ValueError('diagram_source_mapping_missing')
            seen.add(current)
            self.parents.append(current)
            current = self.questions[current].parent_id
        self.reviews = {}
        # Registration uses this store only; no page-wide discovery is performed.
        self.engine = SimpleNamespace(store=store)

    def owner_review(self, owner):
        if owner not in self.reviews:
            original = owner == self.assigned
            entry = self.entry if original else {
                'id': f'diagram-source-owner:{owner}', 'question_id': owner, 'source': {'segments': []}}
            engine, candidates = model_answer_diagram_candidates(self.source, self.ir, self.store,
                entry=entry, question_regions=self.regions if original else sorted(
                    self.regions, key=lambda r: (r["question_id"], r["page_index"], r["top"], r["left"], r["bottom"], r["right"])),
                allow_missing=True)
            self.reviews[owner] = DiagramReview(engine, candidates)
        return self.reviews[owner]

    def parent_owner(self):
        if self.owner_review(self.assigned).candidates:
            return None
        return next((owner for owner in self.parents
                     if any(r.get('question_id') == owner for r in self.regions)
                     and self.owner_review(owner).candidates), None)

    def fallback(self):
        if self.owner_review(self.assigned).candidates:
            return None
        owner = self.parent_owner()
        return ({'scope': 'parent', 'source_question_id': owner,
                 'source_question_path': self.labels[owner]} if owner else {'scope': 'pdf'})

    def diagnostics(self):
        exact = self.owner_review(self.assigned)
        mapped = any(r.get('question_id') == self.assigned for r in self.regions)
        fallback = self.fallback()
        return {'source_sha256': self.ir['source']['sha256'],
                'assigned_question_id': self.assigned, 'exact_source_region_present': mapped,
                'exact_candidate_count': len(exact.candidates),
                'exact_source_element_count': sum(len(ids) for ids in exact.engine.discovery_args['ownership'].values()),
                'exact_reason_code': None if exact.candidates else (
                    'diagram_exact_no_candidates' if mapped else 'diagram_exact_source_region_missing'),
                'parent_source_question_id': fallback.get('source_question_id') if fallback else None,
                'fallback_scope': fallback.get('scope') if fallback else None}

    def scoped_review(self, scope):
        if scope == 'exact':
            return self.owner_review(self.assigned), self.assigned
        if scope == 'parent':
            owner = self.parent_owner()
            if owner is None:
                raise ValueError('diagram_scope_unavailable')
            return self.owner_review(owner), owner
        if scope != 'pdf':
            raise ValueError('diagram_invalid_scope')
        if self.owner_review(self.assigned).candidates or self.parent_owner():
            raise ValueError('diagram_scope_unavailable')
        if 'pdf' not in self.reviews:
            ir = visual_ir(self.source, self.ir)
            engine = DiagramRegionExtractor(self.source, ir, self.store)
            engine.ownership_key = {'scope': 'pdf', 'regions': sorted(
                self.regions, key=lambda r: (r['question_id'], r['page_index'], r['top'], r['left']))}
            ownership = {p['page_index']: sorted({e['element_id'] for e in
                p.get('elements', []) + visual_elements(p)}) for p in ir['pages']}
            candidates = engine.candidates(domain='model_answer',
                target_key=f'pdf:{ir["source"]["sha256"]}', ownership=ownership)
            self.reviews['pdf'] = DiagramReview(engine, candidates)
        return self.reviews['pdf'], None

    def decorate(self, record, scope, owner):
        if scope == 'pdf':
            containing = [r for r in self.regions if r['page_index'] == record['page_index']
                          and _contains([r['left'], r['top'], r['right'], r['bottom']], record['automatic_bbox'])]
            depth = max((r.get('depth', 0) for r in containing), default=-1)
            owners = {r['question_id'] for r in containing if r.get('depth', 0) == depth}
            owner = next(iter(owners)) if len(owners) == 1 and next(iter(owners)) in self.questions else None
        return {**record, 'scope': scope, 'source_question_id': owner,
                'source_question_path': self.labels.get(owner), 'assigned_question_id': self.assigned}

    def discover(self, manager, scope='exact'):
        review, _ = self.scoped_review(scope)
        # Reopening already resolved cached groups must never re-run vision.
        if any(c.get('status') == 'unresolved' and not c.get('ricoh_used') for c in review.candidates):
            review.discover(manager)

    def records(self, saved=(), *, revision=1, scope=None):
        scopes = [scope] if scope else list(dict.fromkeys(r.get('scope', 'exact') for r in saved)) or ['exact']
        result = []
        for selected in scopes:
            subset = [r for r in saved if r.get('scope', 'exact') == selected]
            try:
                review, owner = self.scoped_review(selected)
                for r in subset:
                    if selected == 'pdf':
                        self.check_manual_pdf_bounds(review, r['id'], r.get('final_bbox'))
                    canonical = self.decorate(review.candidate(r['id']), selected, owner)
                    if any(key in r and r[key] != canonical[key] for key in ASSIGNMENT_FIELDS):
                        raise ValueError('diagram_source_stale')
                result.extend(self.decorate(r, selected, owner) for r in review.records(subset, revision=revision))
            except ValueError:
                if not subset:
                    raise
                result.extend({**r, 'state': 'candidate', 'status': 'unresolved',
                    'reason_code': 'diagram_source_stale', 'crop_sha256': None,
                    'artifact_ref': None} for r in subset)
        return result

    def check_manual_pdf_bounds(self, review, identifier, final_bbox):
        if final_bbox is None:
            return
        final_bbox = _box(final_bbox)
        candidate = review.candidate(identifier)
        if final_bbox == candidate['automatic_bbox']:
            return
        page = next(p for p in review.engine.ir['pages'] if p['page_index'] == candidate['page_index'])
        expanded = crop_geometry(page, final_bbox, 'figure', POLICY)['expanded_bbox']
        owner = self.decorate(candidate, 'pdf', None)['source_question_id']
        if owner:
            source_engine = self.owner_review(owner).engine
            if (not any(_contains(b, expanded) for b in source_engine.allowed_bounds.get(candidate['page_index'], []))
                    or any(all(min(expanded[k+2], b[k+2]) > max(expanded[k], b[k]) for k in (0, 1))
                           for b in source_engine.blocked_bounds.get(candidate['page_index'], []))):
                raise ValueError('diagram_source_boundary')
        else:
            # Without a proven Question owner, correction stays close to the
            # discovered visual component and cannot swallow another diagram.
            box = candidate['automatic_bbox']
            envelope = [box[0]-24, box[1]-24, box[2]+24, box[3]+24]
            if not _contains(envelope, expanded) or any(
                    other['id'] != identifier and other['page_index'] == candidate['page_index']
                    and all(min(expanded[k+2], other['automatic_bbox'][k+2]) >
                            max(expanded[k], other['automatic_bbox'][k]) for k in (0, 1))
                    for other in review.candidates):
                raise ValueError('diagram_source_boundary')

    def record(self, identifier, *, final_bbox=None, revision=1, scope='exact'):
        review, owner = self.scoped_review(scope)
        if scope == 'pdf':
            self.check_manual_pdf_bounds(review, identifier, final_bbox)
        return self.decorate(review.record(identifier, final_bbox=final_bbox, revision=revision), scope, owner)

    def validate(self, records, revision):
        if not isinstance(records, list) or len(records) > 16 or len(json.dumps(records)) > 100000:
            raise ValueError('diagram_invalid_decision')
        result, seen = [], set()
        for r in records:
            if not isinstance(r, dict) or not isinstance(r.get('id'), str) or r['id'] in seen:
                raise ValueError('diagram_invalid_decision')
            scope = r.get('scope', 'exact')
            review, owner = self.scoped_review(scope)
            canonical = self.record(r['id'], final_bbox=r.get('final_bbox'), revision=revision, scope=scope)
            if any(key in r and r[key] != canonical[key] for key in ASSIGNMENT_FIELDS):
                raise ValueError('diagram_source_stale')
            validated = review.validate([r], revision)[0]
            result.append(self.decorate(validated, scope, owner))
            seen.add(r['id'])
        return result

    def preview(self, record):
        review, _ = self.scoped_review(record.get('scope', 'exact'))
        return review.preview(record)

    def preview_path(self, identifier, crop_sha=None, scope='exact'):
        review, _ = self.scoped_review(scope)
        return review.preview_path(identifier, crop_sha)
