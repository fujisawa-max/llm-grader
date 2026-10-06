"""Human confirmation overrides only verified detection uncertainty."""
from copy import deepcopy

import pytest

from scoring.diagram_review import DiagramReview
from tests.test_diagram_vision import source as _source_fixture, setup_review


@pytest.fixture
def source():
    yield from _source_fixture.__wrapped__()


@pytest.mark.parametrize('reason', ['diagram_ricoh_output_truncated', 'diagram_ricoh_unavailable',
    'diagram_ricoh_timeout', 'diagram_ricoh_invalid_json', 'diagram_ricoh_low_confidence',
    'diagram_geometry_ambiguous', 'diagram_grouping_ambiguous'])
def test_confirmation_required_and_canonical_provenance_survives_resume(source, reason):
    review = setup_review(source)
    c = review.candidates[0]
    c.update(reason_code=reason, ricoh_used=True, ricoh_finish_reason='length')
    review._cache()
    candidate = review.record(c['id'])
    assert candidate['trust_state'] == 'teacher_confirmable'
    assert not candidate['teacher_confirmed']
    with pytest.raises(ValueError, match='diagram_teacher_confirmation_required'):
        review.validate([{**candidate, 'state': 'accepted'}], 2)
    corrected = review.record(c['id'], final_bbox=[68, 78, 232, 242])
    assert corrected['state'] == 'candidate' and corrected['teacher_adjusted']
    record = review.validate([{**corrected, 'state': 'accepted', 'teacher_confirmed': True,
        'confirmation_reason_code': 'client-forged-reason', 'trust_state': 'trusted'}], 2)[0]
    assert record['trust_state'] == record['trust_state_at_accept'] == 'teacher_confirmable'
    assert record['teacher_confirmed'] and record['confirmation_reason_code'] == reason
    assert record['acceptance_method'] == 'accepted_by_teacher_after_unresolved_detection'
    # Loading cache and saved decisions requires neither a model nor rediscovery.
    resumed = DiagramReview(review.engine, review.engine.candidates(**review.engine.discovery_args))
    restored = resumed.records([record], revision=2)[0]
    assert restored == record


@pytest.mark.parametrize('reason', ['diagram_source_stale', 'diagram_source_integrity_error',
    'diagram_grouping_invalid', 'diagram_source_boundary', 'unknown_failure'])
def test_unrecognized_or_integrity_failures_cannot_be_overridden(source, reason):
    review = setup_review(source)
    review.candidates[0]['reason_code'] = reason
    candidate = review.record(review.candidates[0]['id'])
    assert candidate['trust_state'] == 'hard_invalid'
    with pytest.raises(ValueError, match=reason):
        review.validate([{**candidate, 'state': 'accepted', 'teacher_confirmed': True,
            'trust_state': 'teacher_confirmable'}], 2)


@pytest.mark.parametrize('field,value', [('source_sha256', '0'*64), ('id', 'diagram-'+'0'*24),
    ('final_bbox', [-1, 0, 230, 240]), ('final_bbox', [0, 0, float('nan'), 240])])
def test_forged_override_cannot_bypass_source_id_or_bounds(source, field, value):
    review = setup_review(source)
    record = review.record(review.candidates[0]['id'])
    record.update(state='accepted', teacher_confirmed=True, trust_state='trusted')
    record[field] = value
    with pytest.raises(ValueError):
        review.validate([record], 2)


def test_source_changes_clear_saved_confirmation(source):
    review = setup_review(source)
    record = review.record(review.candidates[0]['id'], state='accepted', teacher_confirmed=True)
    stale = deepcopy(record)
    stale['source_sha256'] = '0'*64
    restored = review.records([stale])[0]
    assert restored['state'] == 'candidate' and restored['trust_state'] == 'hard_invalid'
    assert not restored['teacher_confirmed'] and restored['trust_state_at_accept'] is None
    with pytest.raises(ValueError):
        review.validate([{**stale, 'teacher_confirmed': True}], 2)


def test_historical_trusted_acceptance_defaults_to_no_override(source):
    review = setup_review(source, False)
    record = review.record(review.candidates[0]['id'], state='accepted')
    for k in ('trust_state', 'teacher_confirmed', 'trust_state_at_accept', 'confirmation_reason_code', 'acceptance_method'):
        record.pop(k)
    restored = review.validate([record], 2)[0]
    assert restored['trust_state'] == 'trusted' and not restored['teacher_confirmed']


def test_corrupted_crop_cannot_be_teacher_overridden(source):
    review = setup_review(source)
    record = review.record(review.candidates[0]['id'])
    review.engine.store.path(record['artifact_ref']).write_bytes(b'corrupt image')
    with pytest.raises(ValueError, match='diagram_artifact_integrity_error'):
        review.validate([{**record, 'state': 'accepted', 'teacher_confirmed': True}], 2)


@pytest.mark.parametrize('confirmation', ['true', 1, None, {'confirmed': True}])
def test_confirmation_must_be_an_explicit_boolean(source, confirmation):
    review = setup_review(source)
    record = review.record(review.candidates[0]['id'])
    with pytest.raises(ValueError, match='diagram_invalid_decision'):
        review.validate([{**record, 'state': 'accepted', 'teacher_confirmed': confirmation}], 2)
