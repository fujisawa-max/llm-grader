import json
from pathlib import Path

import pytest

from scoring.math_ocr_candidates import detokenize, select_candidate
from scoring.vision_output import response_text

FIXTURE = json.loads((Path(__file__).parent/'fixtures/math_ocr/precision_spaced.json').read_text())
SOURCE, EXPECTED = FIXTURE['source'], FIXTURE['expected']
RAW, FIELD, _ = response_text(FIXTURE['raw_response'])


def test_production_like_precision_candidates_noise_duplicate_and_offsets():
    result = select_candidate(RAW, SOURCE)
    assert FIELD == 'choices[0].message.reasoning_content'
    assert result['validation_accepted']
    assert result['candidate_count'] == 4
    assert result['duplicate_count'] == 2
    assert result['selected_candidate_index'] == 0
    assert result['selected_candidate'] == EXPECTED
    assert result['candidate_scores'][1]['unsupported_identifiers'] == ['效']
    assert not result['candidate_scores'][1]['accepted']
    assert len(result['normalization_steps']) > 1
    for candidate in result['candidate_scores']:
        assert RAW[candidate['start']:candidate['end']] == candidate['raw_candidate']


@pytest.mark.parametrize('raw,expected', [('P r e c i s i o n', 'Precision'), ('T P', 'TP'), ('F P', 'FP'),
    ('2 4', '24'), ('3 0', '30'), ('0 . 8 0 0', '0.800')])
def test_source_guided_detokenization(raw, expected):
    normalized, steps = detokenize(raw, SOURCE)
    assert normalized == expected
    assert steps == [{'type': 'source_token', 'source': raw, 'replacement': expected}]


def test_unknown_spaced_tokens_are_not_merged():
    assert detokenize('U n k n o w n = 9 9', SOURCE)[0] == 'U n k n o w n=9 9'
    result = select_candidate('U n k n o w n = 9 9', SOURCE)
    assert not result['validation_accepted']
    assert result['rejection_reason'] == 'math_identifier_invalid'


def test_no_partial_numeric_merge_or_decimal_truncation():
    for raw in ('2 4 6', '0 . 8 0 0 1', '0.8001', '2 5'):
        assert detokenize(raw, SOURCE)[0] == raw


@pytest.mark.parametrize('raw', ['An unrelated explanation of the solution.', 'Here is the formula: '+EXPECTED,
    r'Precision=\frac{TP}{TP+FP}=\frac{25}{24+6}=\frac{24}{30}=0.800',
    r'Precision=\frac{TP}{TP+FP}=\frac{24}{24+6}=0.800', EXPECTED+'+Injected',
    EXPECTED+'+99', r'Precision=\frac{TP}{TP+FP', r'Precision=\frac{TP}', r'Precision=\frac{}{TP}',
    '$'+EXPECTED])
def test_real_blockers_remain_rejected(raw):
    assert not select_candidate(raw, SOURCE)['validation_accepted']


@pytest.mark.parametrize('wrapper', ['{}', '${}$', '$${}$$', r'\({}\)', r'\[{}\]', '```latex\n{}\n```', '```tex\n{}\n```'])
def test_candidate_wrappers(wrapper):
    result = select_candidate(wrapper.format(EXPECTED), SOURCE)
    assert result['validation_accepted']
    assert result['selected_candidate'] == EXPECTED


def test_duplicate_normalized_and_exact_same_line():
    spaced = RAW.splitlines()[0]
    result = select_candidate(spaced+'\n'+EXPECTED+'\n'+EXPECTED, SOURCE)
    assert result['candidate_count'] == 3
    assert result['duplicate_count'] == 2
    assert result['selected_candidate'] == EXPECTED
    same_line = select_candidate(spaced+' '+spaced, SOURCE)
    assert same_line['candidate_count'] == 2
    assert same_line['duplicate_count'] == 1
    assert same_line['selected_candidate'] == EXPECTED


def test_only_valid_candidate_selected_deterministically():
    result = select_candidate(EXPECTED.replace('0.800', '0.900')+'\n'+EXPECTED, SOURCE)
    assert result['selected_candidate_index'] == 1
    assert result['validation_accepted']
    assert result['candidate_scores'][0]['rejection_reason'] == 'math_ocr_numeric_mismatch'


def test_meaningful_source_supported_text_and_whitespace_preserved():
    raw = r'x = 1 + \text { true positive }'
    result = select_candidate(raw, 'x=1 + true positive')
    assert result['validation_accepted']
    assert result['selected_candidate'] == r'x=1+\text{true positive}'


def test_multiline_operator_continuations_not_unrelated_lines():
    raw = EXPECTED.replace('=\\frac{24}', '\n=\\frac{24}')
    result = select_candidate(raw, SOURCE)
    assert result['validation_accepted']
    assert result['selected_candidate'].replace('\n', '') == EXPECTED
    result = select_candidate('x=1\ny=2', 'x=1')
    assert result['selected_candidate'] == 'x=1'
    assert result['candidate_count'] == 2


def test_native_omitted_repeated_numerator_warns_without_invention():
    source = SOURCE.replace('24\n30', '30')
    result = select_candidate(EXPECTED, source)
    assert result['validation_accepted']
    assert result['numeric_review_required']


def test_math_error_not_corrected_or_precision_changed():
    assert select_candidate(r'x=\frac{24}{30}=0.7', 'x=24/30=0.7')['selected_candidate'].endswith('=0.7')
    assert not select_candidate(EXPECTED.replace('0.800', '0.8'), SOURCE)['validation_accepted']


def test_production_like_response_integrates_without_mutating_source(tmp_path, monkeypatch):
    from tests.test_math_region_grouping import setup_service
    service, path, segments, text, calls = setup_service(tmp_path, monkeypatch, response=FIXTURE['raw_response'])
    result = service.propose(path, segments, text)
    assert result['status'] == 'ambiguous'
    region = result['math_regions'][0]
    assert region['raw_response'] == FIXTURE['raw_response']
    assert region['raw_ocr_text'] == RAW
    assert region['raw_latex'] == RAW
    assert region['source_field'] == FIELD
    assert region['candidate_count'] == 4
    assert region['duplicate_count'] == 2
    assert region['normalized_candidate'] == EXPECTED
    assert region['validation'] == 'accepted'
    assert result['normalized_text'].endswith('Answer: 0.800 (80%)')
    assert region['crop_image']
    assert calls == ['math_ocr', 'inference']
    assert text == result['original_text']


def test_source_unsupported_text_suffix_excluded_without_prose_peeling():
    result = select_candidate(EXPECTED+' '+r'\text { 效 } \dot { 2 } : 0 . 9 0 0', SOURCE)
    assert result['validation_accepted']
    assert result['selected_candidate'] == EXPECTED
    assert result['candidate_count'] == 2
    assert not result['candidate_scores'][0]['accepted']


@pytest.mark.parametrize('raw', ['```latex\n'+EXPECTED, '$$\n'+EXPECTED+'\n$', r'\['+'\n'+EXPECTED])
def test_unclosed_outer_wrappers_not_discarded(raw):
    result = select_candidate(raw, SOURCE)
    assert not result['validation_accepted']
    assert result['rejection_reason'] == 'math_wrapper_invalid'


def test_multiline_wrapped_repetitions_and_offsets():
    raw = '```latex\n'+RAW+'\n```'
    result = select_candidate(raw, SOURCE)
    assert result['validation_accepted']
    assert result['selected_candidate'] == EXPECTED
    assert result['candidate_count'] == 4
    for candidate in result['candidate_scores']:
        assert raw[candidate['start']:candidate['end']] == candidate['raw_candidate']


def test_extra_supported_numbers_penalized_instead_of_rewarded():
    result = select_candidate(EXPECTED+'=0.800\n'+EXPECTED, SOURCE)
    assert result['selected_candidate_index'] == 1
    assert result['candidate_scores'][0]['score'] < result['candidate_scores'][1]['score']


def test_text_argument_internal_spacing_not_math_whitespace():
    result = select_candidate(r'x = 1 + \text { a + b }', 'x=1 + a + b')
    assert result['validation_accepted']
    assert result['selected_candidate'] == r'x=1+\text{a + b}'


def test_missing_source_identifier_not_a_valid_partial_formula():
    result = select_candidate(EXPECTED.replace('TP+FP', 'TP'), SOURCE)
    assert not result['validation_accepted']
    assert result['rejection_reason'] == 'math_identifier_missing'
    assert result['candidate_scores'][0]['missing_identifiers'] == ['FP']


def test_source_function_can_use_latex_control_sequence():
    assert select_candidate(r'\sin(x)=1', 'sin(x)=1')['validation_accepted']


def test_function_not_in_source_is_not_pure_presentation_syntax():
    result = select_candidate(EXPECTED+r'+\sin(24)', SOURCE)
    assert not result['validation_accepted']
    assert result['rejection_reason'] == 'math_identifier_invalid'
