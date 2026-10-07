"""Question review engine adapter over an authoring working copy."""
from copy import deepcopy
from types import SimpleNamespace

from .question_reviews import QuestionReviewService, ReviewError
from .review_document import validate_snapshot


class AuthoringQuestionReview(QuestionReviewService):
    def __init__(self, session, root, row, snapshot=None):
        super().__init__(session, root)
        self.row = row
        self.working = snapshot if snapshot is not None else row.snapshot
        self.bound = self.working.get('domains', {}).get('question')
        if not self.bound:
            raise ReviewError('authoring_question_source_missing', 422)

    def _review(self, rid, *, lock=False):
        if rid != self.bound['document']['id']:
            raise ReviewError('review_not_found', 404)
        original = super()._review(rid, lock=lock)
        # Never assign to the ORM review: legacy revisions remain untouched.
        return SimpleNamespace(id=original.id, draft_id=original.draft_id,
            source_draft_sha256=original.source_draft_sha256, current_revision=self.row.edit_version,
            current_revision_sha256=self.row.snapshot_sha256, vision_run_id=original.vision_run_id,
            artifact_ref=original.artifact_ref)

    def _revision(self, review, store, number=None):
        if number is not None and number != self.row.edit_version:
            raise ReviewError('revision_conflict', 409)
        return SimpleNamespace(snapshot={**deepcopy(self.bound['snapshot']),
            'nodes': deepcopy(self.working['nodes']), 'state': 'editing', 'reviewed': False},
            revision_number=self.row.edit_version, revision_sha256=self.row.snapshot_sha256)

    def validate_working(self, previous):
        review = self._review(self.bound['document']['id'])
        _, store, automatic, ir = self._draft(review.draft_id)
        current = {**deepcopy(previous['domains']['question']['snapshot']),
            'nodes': deepcopy(previous['nodes']), 'state': 'editing', 'reviewed': False}
        submitted = self._revision(review, store).snapshot
        self._verify_pin(store, current['vision_pin'])
        validated = validate_snapshot(submitted, current, automatic, current['vision_pin'], mark=False)
        for node in validated['nodes']:
            from .question_math_source import validate_math_edit_source
            for edit in node.get('math_ocr_edits', []):
                if (edit['source_sha256'] != ir['source']['sha256'] or
                        edit['material_id'] != ir['source']['material_id'] or
                        edit['review_id'] != review.id or edit['revision'] > self.row.edit_version):
                    raise ReviewError('math_question_provenance_invalid', 422)
                validate_math_edit_source(edit, ir)
            if node.get('diagram_records'):
                from .diagram_review import question_diagram_review
                engine = question_diagram_review(self, review.id, node['stable_key'], self.row.edit_version,
                    snapshot_override=validated)
                node['diagram_records'] = engine.validate(node['diagram_records'], self.row.edit_version+1)
        return validated['nodes']
