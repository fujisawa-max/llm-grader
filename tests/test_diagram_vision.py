import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scoring.diagram_review import DiagramReview
from scoring.diagram_vision import RicohDiagramGrouping
from scoring.diagram_regions import DiagramRegionExtractor
from tests.test_diagram_regions import ownership, source as source_fixture
from tests.runtime_fixture import runtime_service


@pytest.fixture
def source():
    yield from source_fixture.__wrapped__()


def setup_review(source, ambiguous=True):
    pdf, ir, store = source
    if ambiguous:
        for e in ir['pages'][0]['vector_elements'][:2]:
            e['native'].update(horizontal_lines=3, vertical_lines=3)
    engine = DiagramRegionExtractor(pdf, ir, store)
    candidates = engine.candidates(domain='question', target_key='q3', ownership=ownership(ir))
    return DiagramReview(engine, candidates)


def test_clean_geometry_never_ensures_runtime(source):
    review = setup_review(source, False)
    manager = SimpleNamespace(ensure_running=lambda _: pytest.fail('unexpected Ricoh'))
    review.discover(manager)
    assert all(not r['ricoh_used'] for r in review.records())


def test_managed_ricoh_cold_and_warm_and_resume_zero_calls(source, tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_GRADER_TRUSTED_RUNTIME_HOSTS", "127.0.0.2")
    review = setup_review(source)
    with runtime_service(tmp_path) as (manager, *_):
        assert manager.status('ocr')['pid'] is None
        review.discover(manager)
        assert review.candidates[0]['grouping_method'] == 'geometry_assisted', review.candidates[0]
        assert review.candidates[0]['ricoh_finish_reason'] == 'stop'
        assert review.candidates[0]['ricoh_response_field'] == 'choices[0].message.content'
        first = manager.status('ocr')
        assert first['pid']
        engine = review.engine
        # Explicit independent discovery uses the same managed runtime, without stopping it.
        group = RicohDiagramGrouping(engine, manager)
        elements = engine.ir['pages'][0]['vector_elements'][:6]
        group(elements)
        second = manager.status('ocr')
        assert (first['pid'], first['started_at']) == (second['pid'], second['started_at'])
        assert group.observations[0]['ricoh_finish_reason'] == 'stop'
        resumed = DiagramReview(engine, engine.candidates(**engine.discovery_args))
        calls = manager.logs('ocr')['lines']
        resumed.records()
        resumed.record(resumed.candidates[0]['id'], final_bbox=[68,78,232,242])
        assert manager.logs('ocr')['lines'] == calls


@pytest.mark.parametrize('mode,code', [('truncated', 'diagram_ricoh_output_truncated'),
    ('unknown', 'diagram_grouping_invalid'), ('invalid', 'diagram_grouping_invalid'),
    ('unavailable', 'diagram_ricoh_unavailable'), ('timeout', 'diagram_ricoh_timeout')])
def test_bad_ricoh_is_untrusted(source, mode, code):
    review = setup_review(source)
    manager = SimpleNamespace(ensure_running=lambda _: {'state': 'ready', 'profile': {
        'endpoint': 'http://127.0.0.1:9999/v1', 'model_id': 'fixture'}})
    if mode == 'unavailable':
        manager = None
    def request(_self, _url, payload):
        if mode == 'timeout':
            raise TimeoutError('timeout')
        ids = payload['response_format']['json_schema']['schema']['properties']['groups']['items']['properties']['element_ids']['items']['enum']
        text = '{' if mode == 'invalid' else json.dumps({'groups': [{'element_ids': ['unknown'] if mode == 'unknown' else ids, 'confidence': .96}]})
        return {'choices': [{'finish_reason': 'length' if mode == 'truncated' else 'stop', 'message': {'reasoning_content': text}}]}
    with patch('scoring.core.LocalClient.request', request):
        review.discover(manager)
    candidate = review.candidates[0]
    assert candidate['status'] == 'unresolved'
    # malformed JSON is still an explicit rejection, never accepted geometry.
    if mode != 'invalid':
        assert candidate['reason_code'] == code
    with pytest.raises(ValueError):
        review.record(candidate['id'], state='accepted')
