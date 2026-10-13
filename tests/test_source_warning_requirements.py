"""Coverage is attested source provenance, never code equality or approval."""
from copy import deepcopy

import pytest

from scoring.review_document import warning_catalog
from scoring.source_warning_requirements import COVERAGE_SCHEMA, SPATIAL_LABEL, SPATIAL_EXPLANATION
from scoring.test_authoring import preflight
from tests.test_authoring_question_issues import source_snapshot

CODE = 'ambiguous_geometric_order'
AGGREGATE = f'draft:document:{CODE}'


def source_case(keys=('q2',), independent=(), *, producer=True):
    snap = source_snapshot()
    template = deepcopy(snap['nodes'][0])
    criterion = deepcopy(snap['rubrics']['accuracy'])
    snap['nodes'] = []
    snap['answers'], snap['rubrics'] = {}, {}
    for key in keys:
        node = deepcopy(template)
        node.update(stable_key=key, source_draft_stable_key=key,
                    body_text='|予測|Positive|Negative|\n|Negative|8|42|', review_flags=[CODE])
        snap['nodes'].append(node)
        snap['answers'][key] = {'primary': 'Answer'}
        snap['rubrics'][key] = deepcopy(criterion)
    snap['metadata']['total_points'] = len(keys)*10
    draft = {'review_flags': [CODE], 'nodes': snap['nodes'], 'formula_regions': [], 'figure_regions': []}
    if producer:
        draft['parser'] = {'name': 'native-question-structure', 'version': 'question-structure-v1.2.1'}
    if independent:
        draft['warning_provenance'] = {CODE: {'schema_version': COVERAGE_SCHEMA,
            'covered_warning_ids': [f'node:{k}:{CODE}' for k in keys],
            'independent_evidence_ids': list(independent)}}
    question = snap['domains']['question']
    question['document']['automatic_nodes'] = deepcopy(snap['nodes'])
    question['document']['warnings'] = warning_catalog(draft, {})
    return snap


def source_issues(snap):
    return [i for i in preflight(snap)['issues'] if i.get('code') == 'question_source_warning']


def acknowledge(snap, key):
    snap['domains']['question']['snapshot']['warning_states'][f'node:{key}:{CODE}'] = {'state': 'acknowledged'}


def test_production_shape_one_action_exact_owner_wording_and_no_implicit_approval():
    snap = source_case()
    original = deepcopy(snap)
    issues = source_issues(snap)
    assert len(issues) == 1
    issue = issues[0]
    assert issue['question_key'] == 'q2' and issue['warning_id'] == f'node:q2:{CODE}'
    assert issue['message'] == SPATIAL_LABEL
    assert issue['source_review_explanation'] == SPATIAL_EXPLANATION
    assert SPATIAL_EXPLANATION in issue['expected_state']
    assert issue['action_label'] == '出典確認へ'
    assert snap == original
    catalog = preflight(snap)['question_warning_catalog']
    aggregate = next(w for w in catalog if w['id'] == AGGREGATE)
    assert aggregate['actionable'] is False
    assert aggregate['coverage']['covered_warning_ids'] == [f'node:q2:{CODE}']
    assert snap['domains']['question']['snapshot']['warning_states'] == {}
    acknowledge(snap, 'q2')
    assert source_issues(snap) == []
    assert snap['nodes'] == original['nodes']
    assert AGGREGATE not in snap['domains']['question']['snapshot']['warning_states']


def test_independent_document_only_evidence_stays_blocking_and_actionable():
    snap = source_case(keys=(), independent=('page-1:header',))
    issues = source_issues(snap)
    assert len(issues) == 1 and issues[0]['question_key'] is None
    assert issues[0]['warning_id'] == AGGREGATE
    assert issues[0]['message'] == SPATIAL_LABEL
    assert issues[0]['action_label'] == '出典確認へ'
    assert preflight(snap)['can_confirm'] is False


def test_multiple_nodes_are_two_actions_not_three_and_resolve_independently():
    snap = source_case(keys=('q2', 'q3'))
    assert [i['question_key'] for i in source_issues(snap)] == ['q2', 'q3']
    acknowledge(snap, 'q2')
    assert [i['question_key'] for i in source_issues(snap)] == ['q3']
    acknowledge(snap, 'q3')
    assert not source_issues(snap)
    assert preflight(snap)['can_confirm'] is True


def test_mixed_coverage_keeps_document_evidence_after_node_acknowledgment():
    snap = source_case(independent=('page-1:header',))
    assert {i['question_key'] for i in source_issues(snap)} == {None, 'q2'}
    acknowledge(snap, 'q2')
    assert [i['warning_id'] for i in source_issues(snap)] == [AGGREGATE]


def test_unknown_producer_same_code_is_not_proof_of_coverage():
    snap = source_case(producer=False)
    assert {i['question_key'] for i in source_issues(snap)} == {None, 'q2'}


def test_previous_document_acknowledgment_is_audit_only_not_node_approval():
    snap = source_case()
    states = snap['domains']['question']['snapshot']['warning_states']
    states[AGGREGATE] = {'state': 'acknowledged', 'note': 'previous teacher decision'}
    before = deepcopy(states)
    assert [i['question_key'] for i in source_issues(snap)] == ['q2']
    assert states == before


@pytest.mark.parametrize('bad_ids', [['node:missing:'+CODE], [], [None], [{'id': 'q2'}]])
def test_missing_or_malformed_coverage_fails_closed(bad_ids):
    snap = source_case()
    snap['domains']['question']['document']['warnings'][0]['coverage']['covered_warning_ids'] = bad_ids
    assert {i['question_key'] for i in source_issues(snap)} == {None, 'q2'}


def test_excluded_or_ambiguous_source_owner_does_not_hide_document_finding():
    snap = source_case()
    snap['nodes'][0]['included'] = False
    assert any(i['warning_id'] == AGGREGATE for i in source_issues(snap))
    snap['nodes'][0].update(included=True, stable_key='child-a')
    other = deepcopy(snap['nodes'][0])
    other['stable_key'] = 'child-b'
    snap['nodes'].append(other)
    assert any(i['warning_id'] == AGGREGATE for i in source_issues(snap))
