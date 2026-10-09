"""Adapt authoring identities to existing source-backed answer services."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from .db.models import ModelAnswerImportDraft, TestMaterial
from .authoring_sources import _answer_valid, answer_alternatives, normalize_authoring_snapshot
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
        is_gradable=not any(c['included'] and c['parent_key'] == n['stable_key'] for c in snapshot['nodes']), max_points=n.get('score_points'))
        for n in snapshot['nodes'] if n['stable_key'] in aliases]
    return aliases, questions


class AuthoringAnswers:
    def __init__(self, session, root, row, snapshot=None):
        self.row = row
        source_snapshot = snapshot if snapshot is not None else row.snapshot
        normalized = normalize_authoring_snapshot(source_snapshot)
        if snapshot is not None:
            snapshot.clear()
            snapshot.update(normalized)
            self.snapshot = snapshot
        else:
            self.snapshot = normalized
        root_bound = self.snapshot.get('domains', {}).get('answer')
        if not root_bound:
            raise ValueError('authoring_answer_source_missing')
        self.session, self.root = session, root
        all_sources = {root_bound['draft_id']: root_bound, **root_bound.get('sources', {})}
        from .source_registration import deleted_material_ids
        deleted = deleted_material_ids(session, row.test_id)
        self.sources = {identifier: source for identifier, source in all_sources.items()
                        if source.get('material_id') not in deleted}
        if not self.sources:
            raise ValueError('authoring_answer_source_missing')
        answer_sources = [(identifier, source) for identifier, source in self.sources.items()
                          if source.get('material_role', 'model_answer_source') == 'model_answer_source']
        primary_id, primary_source = answer_sources[0] if answer_sources else next(iter(self.sources.items()))
        self.primary_bound = {**primary_source, 'entries': root_bound.get('entries', [])}
        self.bound = self.primary_bound
        for source in self.sources.values():
            self._select_source(source)
        self._select_source(self.primary_bound)
        self.manual_source_id = next((identifier for identifier, source in self.sources.items()
            if session.get(TestMaterial, source['material_id']).material_type == 'model_answer_source'),
            None)
        self.aliases, self.questions = authoring_questions(self.snapshot)
        role_source_ids = {source.get('material_role'): identifier for identifier, source in self.sources.items()}
        self.role_by_source_id = {identifier: source.get('material_role', 'model_answer_source')
                                  for identifier, source in self.sources.items()}
        self.entries = []
        for original in root_bound.get('entries', []):
            entry = deepcopy(original)
            source_id = entry.get('source_draft_id')
            if not source_id:
                source_id = role_source_ids.get(entry.get('material_role'), self.primary_bound['draft_id'])
            if entry.get('source', {}).get('kind') == 'teacher_manual':
                source_id = self.manual_source_id
            if source_id not in self.sources and entry.get('source', {}).get('kind') != 'teacher_manual':
                continue
            entry['source_draft_id'] = source_id
            entry['question_id'] = self.aliases.get(entry.get('authoring_question_key'))
            self.entries.append(entry)
        for entry in self.entries:
            entry.setdefault('source_draft_id', self.manual_source_id)

    def _select_source(self, source):
        self.bound = source
        session, root = self.session, self.root
        draft = session.get(ModelAnswerImportDraft, self.bound['draft_id'])
        if (not draft or draft.test_id != self.row.test_id or draft.material_id != self.bound['material_id']
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
        source_id = entry.get('source_draft_id', self.manual_source_id)
        entry['source_draft_id'] = source_id
        if source_id not in self.sources:
            raise ValueError('model_answer_source_foreign')
        self._select_source(self.sources[source_id])
        if any(m.get('replaces_material_id') == self.bound['material_id'] for m in self.snapshot.get('materials', [])):
            raise ValueError('authoring_material_replaced')
        if question_key is not None:
            if question_key not in self.aliases:
                raise ValueError('authoring_answer_target_missing')
            entry['question_id'] = self.aliases[question_key]
        return entry

    def diagrams(self, entry):
        self._select_source(self.sources[entry.get('source_draft_id', self.primary_bound['draft_id'])])
        same_source = [e for e in self.entries if e.get('source_draft_id', self.primary_bound['draft_id']) == self.bound['draft_id']]
        return ModelAnswerDiagramReview(self.pdf, self.ir, self.store, entry=entry,
            question_regions=self.bound['question_regions'], questions=self.questions,
            reuse_context={'draft_id': self.bound['draft_id'], 'entries': same_source})

    def validate(self):
        gradable = {q.id for q in self.questions if q.is_gradable}
        saved_snapshot = normalize_authoring_snapshot(self.row.snapshot)
        saved = {e['id']: e for e in saved_snapshot.get('domains', {}).get('answer', {}).get('entries', [])}
        previous_keys = {e.get('authoring_question_key') for e in saved.values()}
        originals = {entry['id']: entry for entry in self.primary_bound['entries']}
        for entry in self.entries:
            original = originals.get(entry['id'])
            if original is None:
                continue
            if (self.snapshot is not self.row.snapshot and entry.get('source', {}).get('kind') == 'teacher_manual'
                    and entry['source_draft_id'] != self.primary_bound['draft_id']):
                original.setdefault('source_draft_id', entry['source_draft_id'])
            for field in ('rubric_edits', 'rubric_merge_history', 'rubric_consolidated_groups'):
                entry.pop(field, None)
            if original.get('authoring_question_key') and entry.get('question_id') not in gradable:
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
                from .authoring_answer_inclusion import accept_answer_diagram
                accept_answer_diagram(original, saved.get(entry['id'], {}).get('diagram_records', []),
                    target_valid=entry.get('question_id') in gradable)
        active_entries = [entry for entry in self.primary_bound['entries']
                          if entry.get('source_draft_id', self.primary_bound['draft_id']) in self.sources
                          and self.role_by_source_id.get(entry.get('source_draft_id', self.primary_bound['draft_id']),
                                                         'model_answer_source') == 'model_answer_source']
        for key in (previous_keys | {e.get('authoring_question_key') for e in active_entries}) - {None}:
            answer_included = [e for e in active_entries if e.get('authoring_question_key') == key
                and e.get('disposition', 'include') == 'include']
            primary_entries = [e for e in answer_included if e.get('answer_kind', 'primary') == 'primary']
            primary = next((e for e in primary_entries if e.get('answer_text', '').strip() or
                           any(r.get('state') == 'accepted' for r in e.get('diagram_records', []))),
                           primary_entries[0] if primary_entries else None)
            if answer_included:
                self.snapshot['answers'][key] = {'primary': primary.get('answer_text', '') if primary else '',
                    'alternatives': answer_alternatives(answer_included),
                    'diagram_records': deepcopy(primary.get('diagram_records', [])) if primary else []}
