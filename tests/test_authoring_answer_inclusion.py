"""Exact production auto-excluded diagram-only entry, without inference."""
from copy import deepcopy

import pytest

from scoring.authoring_answer_inclusion import accept_answer_diagram


def automatic():
    return {'id': 'answer', 'question_id': 'child', 'disposition': 'excluded',
        'mapping_state': 'automatic', 'ignore_reason': 'classified_as_non_answer',
        'semantic_classification': {'status': 'classified', 'segments': [{'category': 'note'}]},
        'diagram_records': []}


@pytest.mark.parametrize('source_type', [None, 'manual_pdf_crop'])
def test_teacher_acceptance_promotes_automatic_non_answer_without_losing_evidence(source_type):
    entry = automatic()
    classification = deepcopy(entry['semantic_classification'])
    record = {'id': 'crop', 'state': 'accepted', 'trust_state': 'trusted',
        'material_id': 'material', 'source_sha256': 'source', 'crop_sha256': 'crop',
        **({'source_type': source_type, 'teacher_confirmed': True} if source_type else {})}
    entry['diagram_records'] = [deepcopy(record)]
    assert accept_answer_diagram(entry, [], target_valid=True)
    assert entry['disposition'] == 'include'
    assert entry['teacher_correction'] == {'disposition': 'include', 'teacher_confirmed': True}
    assert entry['semantic_classification'] == classification
    assert entry['ignore_reason'] == 'classified_as_non_answer'
    assert entry['diagram_records'] == [record]


@pytest.mark.parametrize('patch', [
    {'teacher_correction': {'disposition': 'excluded', 'teacher_confirmed': True}},
    {'teacher_correction': {'disposition': 'ignored', 'teacher_confirmed': True}},
    {'disposition': 'ignored'}, {'disposition': 'unassigned'}, {'disposition': None},
    {'mapping_state': 'needs_review'}, {'mapping_state': 'manual_mapped'},
    {'ignore_reason': 'blank_or_whitespace'}, {'ignore_reason': None},
    {'semantic_classification': {'status': 'teacher_reviewed'}},
])
def test_teacher_exclusion_and_unresolved_state_remain_authoritative(patch):
    entry = {**automatic(), **patch, 'diagram_records': [{'id': 'crop', 'state': 'accepted'}]}
    before = deepcopy(entry)
    assert not accept_answer_diagram(entry, [], target_valid=True)
    assert entry == before


@pytest.mark.parametrize('state,target_valid,previous', [
    ('candidate', True, []), ('excluded', True, []), ('accepted', False, []),
    ('accepted', True, [{'id': 'crop', 'state': 'accepted'}]),
])
def test_only_a_new_valid_teacher_acceptance_changes_disposition(state, target_valid, previous):
    entry = {**automatic(), 'diagram_records': [{'id': 'crop', 'state': state}]}
    before = deepcopy(entry)
    assert not accept_answer_diagram(entry, previous, target_valid=target_valid)
    assert entry == before
