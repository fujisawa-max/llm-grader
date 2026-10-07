"""Adapt authoring identities to existing source-backed answer services."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from .db.models import ModelAnswerImportDraft, TestMaterial
from .authoring_sources import _answer_valid, answer_alternatives, rubric_projection, has_rubric_state
from .model_answer_diagram_review import ModelAnswerDiagramReview
from .adapters.artifacts import RunArtifactAdapter


def authoring_questions(snapshot):
    origins = (snapshot['source_provenance'].get('authoring_origins') or {}).get('identities', {})
    aliases = {n['stable_key']: (origins.get(n['stable_key'], {}).get('formal_question_id') or n['stable_key'])
        for n in snapshot['nodes'] if n['included']}
    questions = [SimpleNamespace(id=aliases[n['stable_key']],
        parent_id=aliases.get(n['parent_key']), display_label=n['label']['raw'],
        question_text=n['body_text'], title=n['label']['raw'], node_type=n['node_type'], content={'items': n['ordered_content']},
        question_number=n['label']['raw'], sort_order=n['sort_order'],
        is_gradable=n['score_semantics'] == 'direct', max_points=n.get('score_points'))
        for n in snapshot['nodes'] if n['stable_key'] in aliases]
    return aliases, questions


class AuthoringAnswers:
    def __init__(self, session, root, row, snapshot=None):
        self.row = row
        self.snapshot = snapshot if snapshot is not None else row.snapshot
        self.bound = self.snapshot.get('domains', {}).get('answer')
        if not self.bound:
            raise ValueError('authoring_answer_source_missing')
        draft = session.get(ModelAnswerImportDraft, self.bound['draft_id'])
        if (not draft or draft.test_id != row.test_id or draft.material_id != self.bound['material_id']
                or draft.source_sha256 != self.bound['source_sha256'] or draft.artifact_ref != self.bound['artifact_ref']):
            raise ValueError('model_answer_source_stale')
        _answer_valid(session, draft, root)
        root = Path(root).resolve()
        material = session.get(TestMaterial, draft.material_id)
        pdf = Path(material.storage_ref)
        self.pdf = (pdf if pdf.is_absolute() else root / pdf).resolve()
        path = (root / draft.artifact_ref).resolve()
        self.ir = json.loads(path.read_text())
        self.store = RunArtifactAdapter(path.parent)
        self.aliases, self.questions = authoring_questions(self.snapshot)
        self.entries = [{**deepcopy(e), 'question_id': self.aliases.get(e.get('authoring_question_key'))}
            for e in self.bound['entries']]

    def entry(self, identifier, question_key=None):
        entry = next((e for e in self.entries if e['id'] == identifier), None)
        if entry is None:
            try:
                if not identifier.startswith('teacher-entry-'):
                    raise ValueError()
                UUID(identifier.removeprefix('teacher-entry-'))
            except ValueError:
                raise ValueError('authoring_answer_candidate_missing') from None
            entry = {'id': identifier, 'source': {'kind': 'teacher_manual', 'segments': []}, 'diagram_records': []}
        else:
            entry = deepcopy(entry)
        if question_key is not None:
            if question_key not in self.aliases:
                raise ValueError('authoring_answer_target_missing')
            entry['question_id'] = self.aliases[question_key]
        return entry

    def diagrams(self, entry):
        return ModelAnswerDiagramReview(self.pdf, self.ir, self.store, entry=entry,
            question_regions=self.bound['question_regions'], questions=self.questions,
            reuse_context={'draft_id': self.bound['draft_id'], 'entries': self.entries})

    def validate(self):
        from .api.model_answer_imports import validate_rubric_edits
        gradable = {q.id for q in self.questions if q.is_gradable}
        saved = {e['id']: e for e in self.row.snapshot.get('domains', {}).get('answer', {}).get('entries', [])}
        previous_keys = {e.get('authoring_question_key') for e in saved.values()}
        for entry, original in zip(self.entries, self.bound['entries'], strict=True):
            if entry.get('rubric_edits'):
                validate_rubric_edits(entry['rubric_edits'], entry.get('semantic_classification') or {})
            if entry.get('question_id') and entry['question_id'] not in gradable:
                # Structural edits may turn a leaf into a parent. Preserve its
                # previously verified source artifact as unresolved; never
                # invent a child assignment or accept arbitrary new evidence.
                preserved = []
                for record in entry.get('diagram_records', []):
                    prior = next((r for r in saved.get(entry['id'], {}).get('diagram_records', [])
                        if r['id'] == record.get('id')), None)
                    if not prior or any(record.get(k) != prior.get(k) for k in
                            ('source_sha256', 'material_id', 'context_sha256', 'crop_sha256', 'final_bbox')):
                        raise ValueError('diagram_source_stale')
                    preserved.append({**deepcopy(prior), 'state': 'candidate', 'trust_state': 'hard_invalid',
                        'reason_code': 'diagram_assignment_target_not_gradable'})
                original.update(diagram_records=preserved, authoring_question_key=None,
                    disposition='unassigned', mapping_state='needs_review')
                continue
            if entry.get('diagram_records'):
                original['diagram_records'] = self.diagrams(entry).validate(entry['diagram_records'], self.row.edit_version+1)
        for key in (previous_keys | {e.get('authoring_question_key') for e in self.bound['entries']}) - {None}:
            included = [e for e in self.bound['entries'] if e.get('authoring_question_key') == key
                and e.get('disposition', 'include') == 'include']
            primary = next((e for e in included if e.get('answer_kind', 'primary') == 'primary'), None)
            self.snapshot['answers'][key] = {'primary': primary.get('answer_text', '') if primary else '',
                'alternatives': answer_alternatives(included),
                'diagram_records': deepcopy(primary.get('diagram_records', [])) if primary else []}
            prior_rubric = any(e.get('authoring_question_key') == key and has_rubric_state(e) for e in saved.values())
            if any(has_rubric_state(e) for e in included) or (not included and prior_rubric):
                self.snapshot['rubrics'][key] = [c for e in included for c in rubric_projection(e)]
