import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scoring.core import DEFAULT_GENERATION
from scoring.math_ocr_candidates import select_candidate
from scoring.math_ocr_formatting import compare_structure, normalize_with_fallback, structural_fingerprint

FIXTURE = json.loads((Path(__file__).parent/'fixtures/math_ocr/precision_spaced.json').read_text())
SOURCE, EXPECTED = FIXTURE['source'], FIXTURE['expected']
HARD = EXPECTED.replace(r'\frac', '\\f r\n a c', 1)


def factory(calls, *, output=None, ensure_error=None, request_error=None):
    def ensure(profile_id):
        calls.append(('ensure', profile_id))
        if ensure_error:
            raise ensure_error
        def request(url, payload):
            calls.append(('inference', payload))
            if request_error:
                raise request_error
            return {'choices': [{'message': {'content': output if output is not None else json.dumps({'status': 'formatted', 'latex': EXPECTED})}}]}
        client = SimpleNamespace(base='http://fixture/v1', generation=DEFAULT_GENERATION, request=request)
        return client, {'profile': {'model_id': 'ornith-fixture'}}
    return ensure


def test_deterministic_success_never_ensures_ornith():
    calls = []
    result = normalize_with_fallback(select_candidate(FIXTURE['raw_response']['choices'][0]['message']['reasoning_content'], SOURCE), SOURCE, factory(calls))
    assert result['validation_accepted']
    assert not result['ornith_used']
    assert calls == []
    assert result['final_candidate'] == EXPECTED
    assert result['normalization_method'] == 'deterministic'


def test_control_word_spacing_recovers_deterministically():
    raw = EXPECTED.replace(r'\frac', r'\ f r a c')
    result = select_candidate(raw, SOURCE)
    assert result['validation_accepted']
    assert result['selected_candidate'] == EXPECTED


def test_unicode_token_whitespace_is_source_guided():
    raw = FIXTURE['raw_response']['choices'][0]['message']['reasoning_content'].splitlines()[0].replace(' ', '\u00a0')
    assert select_candidate(raw, SOURCE)['selected_candidate'] == EXPECTED


def test_harder_formatting_only_fallback_success_and_candidate_first():
    raw = HARD+'\n'+r'\text { 效 } \dot { 2 } : 0 . 9 0 0'+'\n'+HARD
    selection = select_candidate(raw, SOURCE)
    assert not selection['validation_accepted']
    calls = []
    result = normalize_with_fallback(selection, SOURCE, factory(calls))
    assert result['validation_accepted']
    assert result['ornith_used']
    assert result['ornith_profile'] == 'ornith_rubric_draft'
    assert result['deterministic_candidate'] == HARD
    assert result['final_candidate'] == EXPECTED
    assert result['formatting_validation']['accepted']
    assert result['formatting_validation']['before']['tokens'] == result['formatting_validation']['after']['tokens']
    assert len(calls) == 2
    request = calls[1][1]
    assert json.loads(request['messages'][-1]['content']) == {'candidate': HARD}
    assert '效' not in request['messages'][-1]['content']
    assert request['chat_template_kwargs']['enable_thinking'] is False


@pytest.mark.parametrize('raw', [EXPECTED.replace('FP', 'FN'), EXPECTED.replace('0.800', '0.900'),
    r'Precision=\frac{TP}', r'An explanation of mathematics.', r'Precision=\frac{TP}{TP+FP}=24'])
def test_semantic_failure_never_ensures_ornith(raw):
    calls = []
    result = normalize_with_fallback(select_candidate(raw, SOURCE), SOURCE, factory(calls))
    assert not result['validation_accepted']
    assert not result['ornith_used']
    assert calls == []
    assert result['formatting_validation']['status'] == 'ineligible'


@pytest.mark.parametrize('after', [EXPECTED.replace('FP', 'FN'), EXPECTED.replace('24+6', '30'),
    EXPECTED.replace('24+6', '6+24'), EXPECTED.replace('+', '-', 1), EXPECTED.replace('0.800', '0.8'),
    EXPECTED+' Explanation.', EXPECTED.replace(r'\frac{24}{30}', r'\frac{30}{24}'),
    EXPECTED+'=0.800', EXPECTED.replace(r'\frac{TP}{TP+FP}', r'\frac{TP+FP}{TP}')])
def test_semantic_mutations_rejected_even_if_final_source_sets_match(after):
    calls = []
    result = normalize_with_fallback(select_candidate(HARD, SOURCE), SOURCE,
        factory(calls, output=json.dumps({'status': 'formatted', 'latex': after})))
    assert result['rejection_reason'] == 'math_formatting_semantic_change'
    assert not result['validation_accepted']
    assert result['final_candidate'] == ''
    assert result['ornith_normalized_output'] == after


@pytest.mark.parametrize('kwargs, reason', [({'ensure_error': RuntimeError('missing')}, 'math_formatting_fallback_unavailable'),
    ({'ensure_error': TimeoutError('slow')}, 'math_formatting_fallback_timeout'),
    ({'request_error': TimeoutError('slow')}, 'math_formatting_fallback_timeout'),
    ({'request_error': OSError('down')}, 'math_formatting_fallback_unavailable'),
    ({'output': 'not JSON'}, 'math_formatting_fallback_invalid_output'),
    ({'output': '{"status":"refused","latex":""}'}, 'math_formatting_fallback_invalid_output'),
    ({'output': '{"status":"formatted","latex":"x=1","extra":true}'}, 'math_formatting_fallback_invalid_output')])
def test_formatting_failures_are_diagnostic(kwargs, reason):
    result = normalize_with_fallback(select_candidate(HARD, SOURCE), SOURCE, factory([], **kwargs))
    assert not result['validation_accepted']
    assert result['rejection_reason'] == reason
    assert result['deterministic_candidate'] == HARD


def test_fingerprint_preserves_order_nesting_and_value_spelling():
    before = structural_fingerprint(HARD, SOURCE)
    after = structural_fingerprint(EXPECTED, SOURCE)
    assert before == after
    assert before['equality_count'] == 4
    assert before['fraction_count'] == 3
    assert before['numeric_sequence'] == ['24', '24', '6', '24', '30', '0.800']
    assert compare_structure(HARD, '$$'+EXPECTED+'$$', SOURCE)['accepted']


def test_actual_output_still_has_to_pass_final_validator():
    # A token-equivalent soft-wrap reference is not itself a valid final
    # response; Ornith must return usable syntax, not the same malformed input.
    result = normalize_with_fallback(select_candidate(HARD, SOURCE), SOURCE,
        factory([], output=json.dumps({'status': 'formatted', 'latex': HARD})))
    assert result['formatting_validation']['accepted']
    assert not result['validation_accepted']
    assert result['rejection_reason'] == 'math_formatting_validation_failed'


def test_managed_ornith_cold_warm_and_no_stop(tmp_path, monkeypatch):
    import fitz
    from scoring.source_math_ocr import SourceMathOCR
    from tests.runtime_fixture import runtime_service
    from tests.test_math_region_grouping import precision
    monkeypatch.setenv('LLM_GRADER_TRUSTED_RUNTIME_HOSTS', '127.0.0.2')
    monkeypatch.setenv('LLM_GRADER_STUB_MATH_RESPONSE_MODE', 'formatting_hard')
    source = precision()
    text = '\n'.join(s['original_text'] for s in source)
    path = tmp_path/'source.pdf'
    with fitz.open() as doc:
        doc.new_page()
        doc.save(path)
    with runtime_service(tmp_path) as (manager, _, _):
        assert manager.status('ornith_rubric_draft')['state'] == 'stopped'
        service = SourceMathOCR(manager)
        result = service.propose(path, source, text)
        assert result['status'] == 'ambiguous'
        region = result['math_regions'][0]
        assert region['ornith_used'] and region['final_candidate'] == EXPECTED
        assert region['crop_image']
        assert region['raw_ocr_text'] == HARD
        before = {role: manager.status(role) for role in ('math_ocr', 'ornith_rubric_draft')}
        result = service.propose(path, source, text)
        assert result['math_regions'][0]['formatting_validation']['accepted']
        for role, state in before.items():
            assert manager.status(role)['pid'] == state['pid']
            assert manager.status(role)['started_at'] == state['started_at']
            assert manager.status(role)['state'] == 'ready'


def test_supplied_production_observation_clean_candidate_is_promoted():
    observed = json.loads((Path(__file__).parent/'fixtures/math_ocr/precision_production_observation.json').read_text())
    raw = observed['raw_response']['choices'][0]['message']['reasoning_content']
    calls = []
    result = normalize_with_fallback(select_candidate(raw, observed['source_math']), observed['source_math'], factory(calls))
    assert result['validation_accepted']
    assert result['final_validation']['accepted']
    assert result['candidate_count'] == 4
    assert result['duplicate_count'] == 1
    assert result['selected_candidate_index'] == 0
    assert result['final_candidate'] == observed['expected']
    assert not result['ornith_used']
    assert calls == []
    # Rejected noisy candidates are warnings/evidence, never blockers on a
    # different accepted candidate. Native omitted repeated 24 is review-only.
    assert not result['candidate_scores'][1]['accepted']
    assert not result['candidate_scores'][2]['accepted']
    assert result['numeric_review_required']


def test_prose_as_math_evidence_is_not_bypassed_by_ornith():
    observed = json.loads((Path(__file__).parent/'fixtures/math_ocr/precision_production_observation.json').read_text())
    raw = observed['raw_response']['choices'][0]['message']['reasoning_content']
    calls = []
    result = normalize_with_fallback(select_candidate(raw, observed['editing_text']), observed['editing_text'], factory(calls))
    assert not result['validation_accepted']
    assert not result['ornith_used']
    assert calls == []
    assert '答え' in result['validation_source_identifiers']


def test_production_observation_apply_reconstruction_preserves_answer_prose(tmp_path, monkeypatch):
    from tests.test_math_region_grouping import setup_service
    observed = json.loads((Path(__file__).parent/'fixtures/math_ocr/precision_production_observation.json').read_text())
    service, path, segments, _, calls = setup_service(tmp_path, monkeypatch, response=observed['raw_response'])
    # Use native segmentation already exercised by source alignment. The user
    # supplied approximate text, not complete per-ID bbox/source-span records.
    segments = [s for s in segments if s['id'] != '5']
    for segment, original in zip(segments, observed['source_math'].splitlines()):
        segment['original_text'] = original
    text = observed['editing_text']
    result = service.propose(path, segments, text)
    assert result['status'] == 'ambiguous'
    assert result['normalized_text'].endswith('答え：0.800（80%）')
    assert result['math_regions'][0]['final_candidate'] == observed['expected']
    assert not result['math_regions'][0]['ornith_used']
    assert calls == ['math_ocr', 'inference']
    assert result['original_text'] == text


def test_mathematical_latin_aliases_preserve_source_not_numeric_superscripts():
    from scoring.math_source_tokens import canonical_math_letters
    from scoring.math_region_grouping import math_like, source_regions
    from tests.test_math_region_grouping import precision
    assert canonical_math_letters('𝑃𝑟𝑒𝑐𝑖𝑠𝑖𝑜𝑛 𝑇𝑃 𝐹𝑃 ² ½ ①') == 'Precision TP FP ² ½ ①'
    assert math_like('𝑇𝑃')
    source = precision()
    originals = ['𝑃𝑟𝑒𝑐𝑖𝑠𝑖𝑜𝑛=', '𝑇𝑃', '𝑇𝑃+𝐹𝑃=']
    for segment, text in zip(source, originals):
        segment['original_text'] = text
    text = '\n'.join(s['original_text'] for s in source)
    regions = source_regions(source, text)
    assert len(regions) == 1
    assert not regions[0]['grouping_ambiguous']
    assert '1' in regions[0]['segment_ids']
    assert regions[0]['source_spans'][1]['original_text'] == '𝑇𝑃'
    selection = select_candidate(FIXTURE['raw_response']['choices'][0]['message']['reasoning_content'], text)
    assert selection['validation_accepted']
    assert selection['selected_candidate'] == EXPECTED
