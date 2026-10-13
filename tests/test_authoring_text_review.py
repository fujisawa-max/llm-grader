"""Manual prose review is scoped and cannot approve other review obligations."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from scoring.authoring_text_review import confirm_manual_text_edits
from scoring.test_authoring import source_warnings
from tests.test_test_authoring import workspace as authoring_workspace, begin, base

workspace = authoring_workspace


def sample():
    return {'nodes': [{'stable_key': 'q3-child', 'body_text': 'Original question',
        'ordered_content': [{'type': 'text', 'text': 'Original question'}],
        'formula_decisions': {'math': {'confirmation_status': 'unreviewed'}},
        'figure_decisions': {'figure': {'decision': 'unresolved'}}}],
        'source_provenance': {}, 'domains': {
            'answer': {'entries': [{'id': 'a', 'answer_text': 'Original answer',
                'semantic_classification': {'status': 'needs_teacher_review', 'segments': []},
                'diagram_records': [{'state': 'accepted', 'revision': 14}],
                'teacher_correction': {'disposition': 'exclude'}}]},
            'rubric': {'entries': [{'id': 'r', 'authoring_question_key': 'q3-child',
                'criteria': [{'id': 'c', 'description': 'Original criterion', 'points': 10,
                    'grouping_confirmed': False, 'points_confirmed': False,
                    'points_conflict': True, 'levels': [], 'provenance': {'source': 'automatic'}}]}]}}}


def test_manual_text_receipts_are_scoped_and_preserve_automatic_evidence():
    old = sample()
    changed = deepcopy(old)
    changed['nodes'][0]['ordered_content'][0]['text'] = 'Revised question'
    changed['domains']['answer']['entries'][0]['answer_text'] = 'Revised answer'
    criterion = changed['domains']['rubric']['entries'][0]['criteria'][0]
    criterion['description'] = 'Revised criterion'
    confirm_manual_text_edits(changed, old, 14)
    question = changed['nodes'][0]
    answer = changed['domains']['answer']['entries'][0]
    for receipt in (question['teacher_correction']['text_review'], answer['teacher_correction']['text_review'],
                    criterion['provenance']['text_review']):
        assert receipt['teacher_confirmed'] is True
        assert receipt['confirmation_origin'] == 'manual_edit'
        assert receipt['revision'] == 14
    assert question['formula_decisions'] == old['nodes'][0]['formula_decisions']
    assert question['figure_decisions'] == old['nodes'][0]['figure_decisions']
    assert answer['semantic_classification'] == old['domains']['answer']['entries'][0]['semantic_classification']
    assert answer['diagram_records'] == old['domains']['answer']['entries'][0]['diagram_records']
    assert answer['teacher_correction']['disposition'] == 'exclude'
    assert criterion['grouping_confirmed'] is False
    assert criterion['points_confirmed'] is False
    assert criterion['points_conflict'] is True
    assert criterion['levels'] == []
    assert criterion['provenance']['source'] == 'automatic'
    assert old == sample()


@pytest.mark.parametrize('text', ['Original question', ' Original  question\n'])
def test_noop_whitespace_and_reverted_edits_do_not_confirm(text):
    old = sample()
    changed = deepcopy(old)
    changed['nodes'][0]['ordered_content'][0]['text'] = text
    changed['domains']['answer']['entries'][0]['answer_text'] = ' Original  answer\n'
    changed['domains']['rubric']['entries'][0]['criteria'][0]['description'] = ' Original  criterion\n'
    confirm_manual_text_edits(changed, old, 2)
    assert 'teacher_correction' not in changed['nodes'][0]
    assert 'text_review' not in changed['domains']['answer']['entries'][0]['teacher_correction']
    assert 'text_review' not in changed['domains']['rubric']['entries'][0]['criteria'][0]['provenance']


def test_unmapped_raw_edit_is_not_silently_attested():
    old = sample()
    changed = deepcopy(old)
    changed['question_text_buffers'] = {'q3-child': 'Unmapped $$ broken formula'}
    confirm_manual_text_edits(changed, old, 2)
    assert 'teacher_correction' not in changed['nodes'][0]
    assert source_warnings(changed)[0]['code'] == 'authoring_text_source_unresolved'


def test_saved_manual_question_buffer_gets_text_receipt_while_source_warning_remains():
    old = sample()
    changed = deepcopy(old)
    edited = 'Teacher-edited text that cannot be projected onto the old source anchors'
    changed['question_text_buffers'] = {'q3-child': edited}
    changed['nodes'][0]['body_text'] = edited
    # The old source-anchored ordered content intentionally remains unchanged.
    confirm_manual_text_edits(changed, old, 2)
    receipt = changed['nodes'][0]['teacher_correction']['text_review']
    assert receipt['teacher_confirmed'] is True
    assert receipt['confirmation_origin'] == 'manual_edit'
    assert receipt['reviewed_text_sha256']
    # Text review is satisfied, while source mapping is still an independent issue.
    assert source_warnings(changed)[0]['code'] == 'authoring_text_source_unresolved'


def test_receipts_preserve_history_without_forged_client_confirmation():
    old = sample()
    saved = deepcopy(old)
    saved['domains']['answer']['entries'][0]['answer_text'] = 'First correction'
    confirm_manual_text_edits(saved, old, 2)
    previous = deepcopy(saved['domains']['answer']['entries'][0]['teacher_correction']['text_review'])
    changed = deepcopy(saved)
    changed['domains']['answer']['entries'][0]['answer_text'] = 'Second correction'
    changed['domains']['answer']['entries'][0]['teacher_correction']['text_review'] = {'forged': True}
    confirm_manual_text_edits(changed, saved, 3)
    assert changed['domains']['answer']['entries'][0]['teacher_correction']['text_review']['previous_review'] == previous


def test_new_item_cannot_import_another_items_text_receipt():
    old = sample()
    changed = deepcopy(old)
    answer = deepcopy(changed['domains']['answer']['entries'][0])
    answer['id'] = 'new-answer'
    answer['teacher_correction']['text_review'] = {'teacher_confirmed': True}
    changed['domains']['answer']['entries'].append(answer)
    criterion = deepcopy(changed['domains']['rubric']['entries'][0]['criteria'][0])
    criterion['id'] = 'new-criterion'
    criterion['provenance']['text_review'] = {'teacher_confirmed': True}
    changed['domains']['rubric']['entries'][0]['criteria'].append(criterion)
    confirm_manual_text_edits(changed, old, 2)
    assert 'text_review' not in answer['teacher_correction']
    assert 'text_review' not in criterion['provenance']


def test_successful_save_persists_text_review_and_failed_cas_does_not(workspace):
    w = workspace
    row = begin(w)
    value = deepcopy(row['snapshot'])
    node = value['nodes'][0]
    node['body_text'] = node['ordered_content'][0]['text'] = 'Teacher reviewed question'
    saved = w.client.put(base(w) + '/authoring', json={'expected_edit_version': row['edit_version'], 'snapshot': value})
    assert saved.status_code == 200, saved.text
    row = saved.json()
    snapshot = deepcopy(row['snapshot'])
    assert snapshot['nodes'][0]['teacher_correction']['text_review']['confirmation_origin'] == 'manual_edit'
    value = deepcopy(snapshot)
    value['nodes'][0]['body_text'] = value['nodes'][0]['ordered_content'][0]['text'] = 'Rejected later edit'
    failed = w.client.put(base(w) + '/authoring', json={'expected_edit_version': row['edit_version'] - 1, 'snapshot': value})
    assert failed.status_code == 409
    assert w.client.get(base(w) + '/authoring').json()['revision']['snapshot'] == snapshot
    # Normal round-trip of server receipts must remain valid and idempotent.
    again = w.client.put(base(w) + '/authoring', json={'expected_edit_version': row['edit_version'], 'snapshot': snapshot})
    assert again.status_code == 200, again.text
    assert again.json()['snapshot']['nodes'][0]['teacher_correction'] == snapshot['nodes'][0]['teacher_correction']


def test_late_save_failure_rolls_back_manual_review(workspace):
    w = workspace
    row = begin(w)
    value = deepcopy(row['snapshot'])
    value['nodes'][0]['body_text'] = value['nodes'][0]['ordered_content'][0]['text'] = 'Unsaved manual correction'
    with patch('scoring.grading_definition.freeze_definition', side_effect=RuntimeError('injected failure')):
        response = w.client.put(base(w) + '/authoring', json={'expected_edit_version': row['edit_version'], 'snapshot': value})
    assert response.status_code == 500
    assert w.client.get(base(w) + '/authoring').json()['revision'] == row


def test_rubric_text_save_retains_points_and_executable_policy(workspace):
    w = workspace
    row = begin(w)
    value = deepcopy(row['snapshot'])
    original = deepcopy(value['domains']['rubric']['entries'][0]['criteria'][0])
    value['domains']['rubric']['entries'][0]['criteria'][0]['description'] = 'Teacher correction to criterion prose'
    response = w.client.put(base(w) + '/authoring', json={'expected_edit_version': row['edit_version'], 'snapshot': value})
    assert response.status_code == 200, response.text
    criterion = response.json()['snapshot']['domains']['rubric']['entries'][0]['criteria'][0]
    assert criterion['provenance']['text_review']['confirmation_origin'] == 'manual_edit'
    assert criterion['points'] == original['points']
    assert criterion['levels'] == original['levels']
