"""Server-attested, same-tree assignments over existing verified crop artifacts.

Only saved accepted assignments produce references. After explicit reuse, each
assignment is independent: excluding its origin does not exclude the new one.
Native ownership, SHA, bounds and hashes are revalidated without regrouping.
"""
from copy import deepcopy
import json
import re

from .diagram_review import DiagramReview, FIELDS
from .diagram_regions import DiagramRegionExtractor, visual_elements, write_diagram_json
from .diagram_sources import model_answer_diagram_candidates, visual_ir
from .pdf_native import canonical_hash

REUSE_FIELDS = ('reuse_ref', 'reused_from_assignment_id', 'reused_from_entry_id',
    'reused_from_question_id', 'reused_from_question_path', 'reuse_source_scope',
    'source_teacher_confirmed', 'source_trust_state_at_accept', 'source_confirmation_reason_code')


class ConfirmedDiagramReuse:
    def __init__(self, coordinator):
        self.current = coordinator
        self.context = coordinator.reuse_context
        self.store = coordinator.engine.store

    def root(self, qid):
        questions, seen = self.current.questions, set()
        while qid in questions and qid not in seen:
            seen.add(qid)
            parent = questions[qid].parent_id
            if not parent:
                return qid
            qid = parent
        raise ValueError('diagram_source_stale')

    def source_review(self, entry, record):
        from .model_answer_diagram_review import ModelAnswerDiagramReview, ASSIGNMENT_FIELDS
        scope = record.get('scope', 'exact')
        owner = record.get('source_question_id')
        source = ModelAnswerDiagramReview(self.current.source, self.current.ir, self.store,
            entry=entry, question_regions=self.current.regions, questions=list(self.current.questions.values()))
        if scope == 'manual':
            review = source.manual_review()
            validated = review.validate([record], record.get('revision', 1))[0]
            return source, review, validated
        if scope == 'pdf':
            ir = visual_ir(source.source, source.ir)
            engine = DiagramRegionExtractor(source.source, ir, self.store)
            engine.ownership_key = {'scope': 'pdf', 'regions': sorted(source.regions,
                key=lambda r: (r['question_id'], r['page_index'], r['top'], r['left']))}
            engine.discovery_args = dict(domain='model_answer', target_key=f'pdf:{ir["source"]["sha256"]}',
                ownership={p['page_index']: sorted({e['element_id'] for e in
                    p.get('elements', []) + visual_elements(p)}) for p in ir['pages']})
        elif scope in {'exact', 'parent'}:
            if scope == 'parent' and owner not in source.parents:
                raise ValueError('diagram_source_stale')
            source_entry = entry if scope == 'exact' else {
                'id': f'diagram-source-owner:{owner}', 'question_id': owner, 'source': {'segments': []}}
            regions = source.regions if scope == 'exact' else sorted(source.regions,
                key=lambda r: (r['question_id'], r['page_index'], r['top'], r['left'], r['bottom'], r['right']))
            engine, _ = model_answer_diagram_candidates(source.source, source.ir, self.store,
                entry=source_entry, question_regions=regions, allow_missing=True, discover=False)
        else:
            raise ValueError('diagram_source_stale')
        review = DiagramReview.from_cache(engine, record.get('context_sha256'))
        canonical = source.decorate(review.candidate(record['id']), scope, owner)
        if any(k in record and record[k] != canonical[k] for k in ASSIGNMENT_FIELDS):
            raise ValueError('diagram_source_stale')
        if scope == 'pdf':
            source.check_manual_pdf_bounds(review, record['id'], record.get('final_bbox'))
        validated = source.decorate(review.validate([record], record.get('revision', 1))[0], scope, owner)
        return source, review, validated

    def reference(self, entry, record, *, native_entry=None):
        identity = {'draft': self.context['draft_id'], 'entry': entry['id'],
            'question': entry['question_id'], 'candidate': record['id'],
            'context': record['context_sha256'], 'crop': record['crop_sha256']}
        ref = canonical_hash(identity)
        # Keep just the source entry information needed for native ownership.
        native = native_entry or entry
        origin = {'id': native['id'], 'question_id': native['question_id'], 'source': {'segments': [
            {k: s[k] for k in ('page_index', 'element_ids') if k in s}
            for s in native.get('source', {}).get('segments', [])]}}
        write_diagram_json(self.store, f'diagrams/reuse/{ref}.json', {
            'draft_id': self.context['draft_id'],
            'origin': {'id': entry['id'], 'question_id': entry['question_id']},
            'native_origin': origin, 'record': record})
        return ref

    def load(self, ref):
        if not isinstance(ref, str) or not re.fullmatch(r'[0-9a-f]{64}', ref):
            raise ValueError('diagram_reuse_not_found')
        path = self.store.path(f'diagrams/reuse/{ref}.json')
        if not path.is_file():
            raise ValueError('diagram_reuse_not_found')
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise ValueError('diagram_source_stale') from exc
        if not isinstance(value, dict) or value.get('draft_id') != self.context['draft_id']:
            raise ValueError('diagram_reuse_not_found')
        entry, record = value.get('origin'), value.get('record')
        native = value.get('native_origin', entry)
        if (not all(isinstance(v, dict) for v in (entry, record, native))
                or not all(v.get('id') and v.get('question_id') for v in (entry, native))):
            raise ValueError('diagram_source_stale')
        if (record.get('state') != 'accepted' or self.root(entry['question_id']) != self.root(self.current.assigned)
                or self.root(native['question_id']) != self.root(self.current.assigned)):
            raise ValueError('diagram_reuse_not_found')
        try:
            source, review, validated = self.source_review(native, record)
        except (KeyError, OSError, TypeError) as exc:
            raise ValueError('diagram_source_stale') from exc
        if self.reference_identity(entry, validated) != ref:
            raise ValueError('diagram_source_stale')
        return entry, source, review, validated

    def reference_identity(self, entry, record):
        return canonical_hash({'draft': self.context['draft_id'], 'entry': entry['id'],
            'question': entry['question_id'], 'candidate': record['id'],
            'context': record['context_sha256'], 'crop': record['crop_sha256']})

    def decorate(self, value, ref, entry, origin):
        return {**value, 'scope': 'reuse', 'source_question_id': origin.get('source_question_id'),
            'source_question_path': origin.get('source_question_path'), 'assigned_question_id': self.current.assigned,
            'reuse_ref': ref, 'reused_from_assignment_id': self.reference_identity(entry, origin),
            'reused_from_entry_id': entry['id'], 'reused_from_question_id': entry['question_id'],
            'reused_from_question_path': self.current.labels[entry['question_id']],
            'reuse_source_scope': origin.get('scope', 'exact'),
            'source_teacher_confirmed': origin.get('teacher_confirmed', False),
            'source_trust_state_at_accept': origin.get('trust_state_at_accept', 'trusted'),
            'source_confirmation_reason_code': origin.get('confirmation_reason_code'),
            'acceptance_method': 'reused_confirmed_diagram' if value['state'] == 'accepted' else None}

    def available(self, revision, diagnostics=None):
        def trace(entry, record, outcome, reason=None):
            if diagnostics is not None:
                diagnostics.append({'entry_id': entry.get('id'),
                    'question_id': entry.get('question_id'), 'diagram_id': record.get('id') if record else None,
                    'outcome': outcome, 'reason': reason})

        result, seen = [], set()
        for entry in self.context['entries']:
            reason = (
                'same_target' if entry.get('question_id') == self.current.assigned else
                'entry_not_included' if entry.get('disposition', 'include') != 'include' else
                'unknown_question' if entry.get('question_id') not in self.current.questions else
                'different_major' if self.root(entry['question_id']) != self.root(self.current.assigned) else None)
            if reason:
                trace(entry, None, 'excluded', reason)
                continue
            for record in entry.get('diagram_records', []):
                reason = ('not_accepted' if record.get('state') != 'accepted' else
                    'hard_invalid' if record.get('trust_state') == 'hard_invalid' else
                    'diagram_source_stale' if record.get('reason_code') == 'diagram_source_stale' else None)
                if reason:
                    trace(entry, record, 'excluded', reason)
                    continue
                try:
                    if record.get('scope') == 'reuse':
                        # Flatten to the originally confirmed source, retaining a
                        # server attestation; never manufacture native ownership.
                        _, native_source, native_review, origin = self.load(record.get('reuse_ref'))
                        from .model_answer_diagram_review import ModelAnswerDiagramReview
                        other = ModelAnswerDiagramReview(self.current.source, self.current.ir, self.store,
                            entry=entry, question_regions=self.current.regions,
                            questions=list(self.current.questions.values()), reuse_context=self.context)
                        current_assignment = other.reuse().validate(record, revision)
                        value = native_review.record(record['id'], state='accepted',
                            final_bbox=current_assignment['final_bbox'],
                            teacher_confirmed=current_assignment.get('teacher_confirmed', False), revision=revision)
                        origin = native_source.decorate(value, origin.get('scope', 'exact'), origin.get('source_question_id'))
                        ref = self.reference(entry, origin, native_entry=native_source.entry)
                    else:
                        _, _, origin = self.source_review(entry, record)
                        ref = self.reference(entry, origin)
                    key = (origin['id'], origin['crop_sha256'])
                    if key in seen:
                        trace(entry, record, 'excluded', 'duplicate_artifact')
                        continue
                    value = self.record(origin['id'], ref, revision=revision)
                    result.append(value)
                    seen.add(key)
                    trace(entry, record, 'included')
                except (ValueError, KeyError, OSError) as exc:
                    trace(entry, record, 'excluded', str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
                    # Invalid/missing artifacts are not offered as teacher tasks.
                    continue
        return result

    def record(self, identifier, ref, *, final_bbox=None, state='candidate', teacher_confirmed=False, revision=1):
        entry, source, review, origin = self.load(ref)
        if identifier != origin['id']:
            raise ValueError('diagram_reuse_not_found')
        final = final_bbox if final_bbox is not None else origin['final_bbox']
        if origin.get('scope') == 'pdf':
            source.check_manual_pdf_bounds(review, identifier, final)
        value = review.record(identifier, state=state, final_bbox=final,
            teacher_confirmed=teacher_confirmed, revision=revision)
        return self.decorate(value, ref, entry, origin)

    def validate(self, record, revision):
        if set(record)-set(FIELDS):
            raise ValueError('diagram_invalid_decision')
        # A saved independent assignment survives changes to its origin decision.
        # A NEW assignment must still reference a currently accepted source;
        # an old listing/attestation cannot resurrect an excluded source.
        existing = any(r.get('assigned_question_id') == self.current.assigned
            and r.get('id') == record.get('id') and r.get('reuse_ref') == record.get('reuse_ref')
            for r in self.current.entry.get('diagram_records', []))
        if not existing:
            origin_entry, _, _, origin = self.load(record.get('reuse_ref'))
            accepted = any(e.get('id') == origin_entry['id'] and e.get('question_id') == origin_entry['question_id']
                and e.get('disposition', 'include') == 'include'
                and any(r.get('state') == 'accepted' and r.get('id') == origin['id']
                    and r.get('crop_sha256') == origin['crop_sha256'] for r in e.get('diagram_records', []))
                for e in self.context['entries'])
            if not accepted:
                raise ValueError('diagram_source_stale')
        canonical = self.record(record['id'], record.get('reuse_ref'), final_bbox=record.get('final_bbox'),
            state=record.get('state', 'candidate'), teacher_confirmed=record.get('teacher_confirmed', False), revision=revision)
        for k in ('source_sha256', 'material_id', 'domain', 'target_key', 'page_index', 'automatic_bbox',
                  'source_element_ids', 'context_sha256', 'source_question_id', 'assigned_question_id', *REUSE_FIELDS):
            if k in record and record[k] != canonical[k]:
                raise ValueError('diagram_source_stale')
        return canonical

    def records(self, records, revision):
        result = []
        for record in records:
            try:
                result.append(self.validate(record, revision))
            except (ValueError, KeyError, OSError):
                stale = deepcopy(record)
                stale.update(state='candidate', status='unresolved', trust_state='hard_invalid',
                    reason_code='diagram_source_stale', teacher_confirmed=False, crop_sha256=None, artifact_ref=None)
                result.append(stale)
        return result

    def preview(self, record):
        _, _, review, _ = self.load(record.get('reuse_ref'))
        return review.preview(record)

    def preview_path(self, identifier, ref, crop_sha=None):
        if crop_sha is not None and (not isinstance(crop_sha, str) or not re.fullmatch(r'[0-9a-f]{64}', crop_sha)):
            raise ValueError('diagram_reuse_not_found')
        _, source, review, origin = self.load(ref)
        if identifier != origin['id']:
            raise ValueError('diagram_reuse_not_found')
        # The existing preview manifest stores server-validated manual bounds.
        try:
            record = origin if crop_sha is None else json.loads(self.store.path(
                f'diagrams/previews/{review.context}/{identifier}/{crop_sha}.json').read_text())
        except (OSError, ValueError) as exc:
            raise ValueError('diagram_reuse_not_found') from exc
        if origin.get('scope') == 'pdf':
            source.check_manual_pdf_bounds(review, identifier, record.get('final_bbox'))
        return review.preview_path(identifier, crop_sha)
