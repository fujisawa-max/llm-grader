import json
from types import SimpleNamespace

import fitz
import pytest

from scoring.math_region_grouping import source_regions, validate_groups
from scoring.source_math_ocr import SourceMathOCR
from scoring.vision_output import response_text, unwrap_math_output


PRECISION = r'Precision=\frac{TP}{TP+FP}=\frac{24}{24+6}=\frac{24}{30}=0.800'


def precision(gap=0):
    texts = ['Precision=', 'TP', 'TP+FP=', '24', '24+6 =', '24', '30 = 0.800']
    boxes = [[30, 45, 100, 58], [114, 37, 135, 49], [110, 56, 175, 68],
             [191+gap, 37, 205+gap, 49], [180+gap, 56, 230+gap, 68],
             [250+gap, 37, 264+gap, 49], [240+gap, 56, 330+gap, 68]]
    return [{'id': str(i), 'original_text': t, 'page_index': 0, 'bbox': b, 'reading_order': i}
            for i, (t, b) in enumerate(zip(texts, boxes))]


def test_fragmented_precision_one_band_all_ids_and_duplicates():
    segments = precision()
    text = '\n'.join(s['original_text'] for s in segments)
    regions = source_regions(segments, text)
    assert len(regions) == 1
    assert regions[0]['bbox'] == [30, 37, 330, 68]
    assert regions[0]['segment_ids'] == [str(i) for i in range(7)]
    assert not regions[0]['grouping_ambiguous']
    assert len(regions[0]['source_spans']) == 7


@pytest.mark.parametrize('box', [[30, 95, 130, 108], [300, 45, 400, 58], [140, 45, 240, 58]])
def test_independent_formulas_not_merged(box):
    source = [{'id': 'x', 'original_text': 'x=1', 'bbox': [30, 45, 130, 58], 'page_index': 0},
              {'id': 'y', 'original_text': 'y=2', 'bbox': box, 'page_index': 0, 'reading_order': 1}]
    assert len(source_regions(source, 'x=1\ny=2')) == 2


def test_accuracy_clean_wide_bypasses_grouping():
    source = [{'id': 'a', 'original_text': 'Accuracy=(TP+TN)/(TP+FP+FN+TN)', 'bbox': [30, 45, 400, 65], 'page_index': 0}]
    region = source_regions(source, source[0]['original_text'])[0]
    assert not region['grouping_ambiguous']


def test_prose_not_included():
    source = precision()
    source.append({'id': 'p', 'original_text': 'Explain the result.', 'bbox': [35, 85, 220, 100], 'page_index': 0, 'reading_order': 7})
    regions = source_regions(source, '\n'.join(s['original_text'] for s in source))
    assert regions[0]['segment_ids'] == [str(i) for i in range(7)]


@pytest.mark.parametrize('wrapper', ['{}', '${}$', '$${}$$', r'\({}\)', r'\[{}\]', '```latex\n{}\n```', '```tex\n{}\n```'])
def test_legal_wrappers_only(wrapper):
    assert unwrap_math_output(wrapper.format(PRECISION)) == PRECISION


@pytest.mark.parametrize('field', ['content', 'final', 'answer', 'reasoning_content', 'reasoning'])
def test_response_field_variants(field):
    text, source, _ = response_text({'choices': [{'message': {'content': '', field: PRECISION}}]})
    assert text == PRECISION
    assert source.endswith('.'+field)


def test_content_preferred():
    assert response_text({'choices': [{'message': {'content': 'x=1', 'reasoning_content': 'x=2'}}]})[0] == 'x=1'


@pytest.mark.parametrize('value', [
    {'groups': [{'segment_ids': ['unknown'], 'confidence': .99}]},
    {'groups': [{'segment_ids': ['0', '0'], 'confidence': .99}]},
    {'groups': [{'segment_ids': ['0'], 'confidence': .4}]},
    'not-json',
])
def test_ricoh_unknown_duplicate_missing_low_confidence_rejected(value):
    atoms = source_regions(precision(), '\n'.join(s['original_text'] for s in precision()))[0]['source_spans']
    with pytest.raises(ValueError, match='math_ricoh_grouping_rejected'):
        validate_groups(value, atoms)


def setup_service(tmp_path, monkeypatch, *, gap=0, ricoh='ok', response=None):
    source = precision(gap)
    text = '\n'.join(s['original_text'] for s in source)+'\nAnswer: 0.800 (80%)'
    path = tmp_path/'precision.pdf'
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((30, 53), 'Precision=')
        for x, numerator, denominator in [(114, 'TP', 'TP+FP'), (191+gap, '24', '24+6'), (250+gap, '24', '30')]:
            page.insert_text((x, 45), numerator)
            page.draw_line((x-2, 52), (x+35, 52))
            page.insert_text((x, 65), denominator)
        page.insert_text((165, 53), '=')
        page.insert_text((224+gap, 53), '=')
        page.insert_text((294+gap, 53), '=0.800')
        document.save(path)
    calls = []
    def ensure(role):
        calls.append(role)
        if role == 'ocr' and ricoh == 'unavailable':
            raise RuntimeError('missing fixture')
        return {'state': 'ready', 'profile': {'model_id': role, 'runtime_type': 'managed', 'endpoint': 'http://127.0.0.1:8080/v1'}}
    def request(client, url, payload):
        if client.role == 'ocr':
            supplied = json.loads(payload['messages'][0]['content'][0]['text'].split('\n', 1)[1])['segments']
            result = {'groups': [{'segment_ids': [s['id'] for s in supplied], 'confidence': .96}]}
            raw = 'not-json' if ricoh == 'malformed' else json.dumps(result)
            return {'choices': [{'message': {'content': raw}}]}
        calls.append('inference')
        return response or {'choices': [{'message': {'content': '$$'+PRECISION+'$$'}}]}
    monkeypatch.setattr('scoring.source_math_ocr.LocalClient.request', request)
    return SourceMathOCR(SimpleNamespace(ensure_running=ensure)), path, source, text, calls


def test_one_unimumer_call_no_ricoh_and_prose_preserved(tmp_path, monkeypatch):
    service, path, source, text, calls = setup_service(tmp_path, monkeypatch)
    result = service.propose(path, source, text)
    assert result['status'] == 'ambiguous'
    assert calls == ['math_ocr', 'inference']
    assert result['grouping_summary'] == {'native_segment_count': 7, 'aligned_math_segment_count': 7,
        'geometry_region_count': 1, 'final_region_count': 1, 'ricoh_used': False}
    assert len(result['math_regions']) == 1
    assert result['math_regions'][0]['normalized_candidate'] == PRECISION
    assert result['normalized_text'].endswith('\nAnswer: 0.800 (80%)')
    assert result['math_regions'][0]['crop_width'] == 624
    assert result['math_regions'][0]['crop_height'] == 86


def test_ricoh_repairs_only_ambiguous_band(tmp_path, monkeypatch):
    service, path, source, text, calls = setup_service(tmp_path, monkeypatch, gap=35)
    result = service.propose(path, source, text)
    assert result['status'] == 'ambiguous'
    assert calls == ['ocr', 'math_ocr', 'inference']
    assert len(result['math_regions']) == 1
    assert result['math_regions'][0]['grouping_method'] == 'ricoh_assisted_repair'
    assert result['math_regions'][0]['bbox'] == [30, 37, 365, 68]


@pytest.mark.parametrize('ricoh,reason', [('malformed','math_ricoh_grouping_rejected'), ('unavailable','math_ricoh_unavailable')])
def test_ricoh_failure_no_unimumer_no_unsafe_merge(tmp_path, monkeypatch, ricoh, reason):
    service, path, source, text, calls = setup_service(tmp_path, monkeypatch, gap=35, ricoh=ricoh)
    result = service.propose(path, source, text)
    assert result['status'] == 'rejected'
    assert result['reason_code'] == reason
    assert calls == ['ocr']
    assert result['normalized_text'] == text
    assert result['math_regions'][0]['crop_image']


@pytest.mark.parametrize('response,reason', [
    ({'choices': [{'message': {'content': ''}}]}, 'math_ocr_empty_response'),
    ({'unexpected': 'shape'}, 'math_response_unsupported'),
    ({'choices': [{'message': {'content': 'Here is the formula: '+PRECISION}}]}, 'math_identifier_invalid'),
    ({'choices': [{'message': {'content': '$'+PRECISION}}]}, 'math_wrapper_invalid'),
])
def test_failed_ocr_keeps_crop_raw_and_field(tmp_path, monkeypatch, response, reason):
    service, path, source, text, calls = setup_service(tmp_path, monkeypatch, response=response)
    result = service.propose(path, source, text)
    assert result['status'] == 'rejected'
    assert result['reason_code'] == reason
    region = result['math_regions'][0]
    assert region['raw_response'] == response
    assert region['inference_completed']
    assert region['crop_image']
    assert result['normalized_text'] == text


def test_managed_ricoh_and_unimumer_reuse(tmp_path, monkeypatch):
    from tests.runtime_fixture import runtime_service
    monkeypatch.setenv('LLM_GRADER_TRUSTED_RUNTIME_HOSTS', '127.0.0.2')
    source = precision(35)
    path = tmp_path/'group.pdf'
    with fitz.open() as doc:
        doc.new_page()
        doc.save(path)
    text = '\n'.join(s['original_text'] for s in source)
    with runtime_service(tmp_path) as (manager, _, _):
        service = SourceMathOCR(manager)
        result = service.propose(path, source, text)
        assert result['status'] == 'ambiguous'
        assert result['math_regions'][0]['grouping_method'] == 'ricoh_assisted_repair'
        before = {role: manager.status(role) for role in ('ocr', 'math_ocr')}
        result = service.propose(path, source, text)
        assert len(result['math_regions']) == 1
        for role, state in before.items():
            assert manager.status(role)['pid'] == state['pid']
            assert manager.status(role)['started_at'] == state['started_at']
            assert manager.status(role)['state'] == 'ready'


def test_managed_empty_response_retains_crop_and_running_runtime(tmp_path, monkeypatch):
    from tests.runtime_fixture import runtime_service
    monkeypatch.setenv('LLM_GRADER_TRUSTED_RUNTIME_HOSTS', '127.0.0.2')
    monkeypatch.setenv('LLM_GRADER_STUB_MATH_RESPONSE_MODE', 'empty')
    source = precision()
    path = tmp_path/'empty.pdf'
    with fitz.open() as doc:
        doc.new_page()
        doc.save(path)
    text = '\n'.join(s['original_text'] for s in source)
    with runtime_service(tmp_path) as (manager, _, _):
        result = SourceMathOCR(manager).propose(path, source, text)
        assert result['status'] == 'rejected'
        assert result['reason_code'] == 'math_ocr_empty_response'
        region = result['math_regions'][0]
        assert region['raw_response']['choices'][0]['message']['content'] == ''
        assert region['crop_image'] and region['crop_sha256']
        assert region['inference_completed']
        assert manager.status('math_ocr')['state'] == 'ready'


def test_repeated_numeral_in_excluded_question_does_not_steal_answer_span():
    source = [{'id': 'question-24', 'original_text': '24', 'bbox': [30, 10, 45, 23],
               'page_index': 0, 'reading_order': -1}] + precision()
    text = '\n'.join(s['original_text'] for s in precision())
    regions = source_regions(source, text)
    assert len(regions) == 1
    assert regions[0]['segment_ids'] == [str(i) for i in range(7)]


def test_noncontiguous_native_ranges_preserve_inserted_prose(tmp_path, monkeypatch):
    service, path, source, text, calls = setup_service(tmp_path, monkeypatch)
    text = text.replace('TP\n', 'TP\nTeacher note remains.\n', 1)
    result = service.propose(path, source, text)
    assert result['status'] == 'ambiguous'
    assert 'Teacher note remains.' in result['normalized_text']
    assert calls == ['ocr', 'math_ocr', 'inference']
    assert len(result['math_regions'][0]['source_spans']) == 7


def test_legal_aligned_environment(tmp_path, monkeypatch):
    wrapped = r'\begin{aligned}'+PRECISION+r'\end{aligned}'
    service, path, source, text, calls = setup_service(tmp_path, monkeypatch,
        response={'choices': [{'message': {'content': wrapped}}]})
    assert service.propose(path, source, text)['status'] == 'ambiguous'


def test_ricoh_candidate_does_not_include_neighboring_prose(tmp_path, monkeypatch):
    service, path, source, text, calls = setup_service(tmp_path, monkeypatch, gap=35)
    source.append({'id': 'p', 'original_text': 'Explanation remains.', 'bbox': [370, 45, 480, 58],
                   'page_index': 0, 'reading_order': 7})
    result = service.propose(path, source, text+'\nExplanation remains.')
    assert result['status'] == 'ambiguous'
    assert result['math_regions'][0]['segment_ids'] == [str(i) for i in range(7)]
    assert result['normalized_text'].endswith('Explanation remains.')
    assert calls == ['ocr', 'math_ocr', 'inference']


def test_truncated_ricoh_rejected_with_exact_reason_no_unsafe_union(tmp_path, monkeypatch):
    service, path, source, text, calls = setup_service(tmp_path, monkeypatch, gap=35)
    def truncated(client, url, payload):
        assert payload['response_format']['json_schema']['name'] == 'math_region_grouping'
        assert payload['response_format']['json_schema']['schema']['properties']['groups']['items']['properties']['segment_ids']['items']['enum'] == [str(i) for i in range(7)]
        assert payload['chat_template_kwargs']['enable_thinking'] is False
        return {'choices': [{'finish_reason': 'length', 'message': {'content': '', 'reasoning_content': 'Long reasoning... {"groups":['}}], 'usage': {'completion_tokens': 1024}}
    monkeypatch.setattr('scoring.source_math_ocr.LocalClient.request', truncated)
    result = service.propose(path, source, text)
    assert result['status'] == 'rejected'
    assert result['reason_code'] == 'math_ricoh_output_truncated'
    assert calls == ['ocr']
    region = result['math_regions'][0]
    assert region['crop_image']
    assert region['ricoh_finish_reason'] == 'length'
    assert region['ricoh_completion_tokens'] == 1024


def test_safe_geometry_proof_can_survive_ricoh_parse_failure(tmp_path, monkeypatch):
    service, path, source, text, calls = setup_service(tmp_path, monkeypatch, ricoh='malformed')
    regions = source_regions(source, text)
    # Simulate an upstream ambiguity flag on an independently provable band.
    # The loose 35pt gap case above cannot use this fallback.
    regions[0]['grouping_ambiguous'] = True
    with fitz.open(path) as document:
        repaired = service.repair_groups(document, regions, text)
    assert len(repaired) == 1
    assert 'rejection_code' not in repaired[0]
    assert repaired[0]['grouping_method'] == 'geometry_ricoh_failure_fallback'
    assert repaired[0]['ricoh_rejection_code'] == 'math_ricoh_grouping_rejected'
    assert repaired[0]['segment_ids'] == [str(i) for i in range(7)]


def production_precision():
    from pathlib import Path
    return json.loads((Path(__file__).parent/'fixtures/math_ocr/precision_production_observation.json').read_text())


def test_real_precision_geometry_retains_unicode_and_both_numerators():
    observed = production_precision()
    # Nine records supplied by the user; do not fabricate the other two of 11.
    source, text = observed['production_segments'], observed['complete_source_text']
    regions = source_regions(list(reversed(source)), text)
    assert len(regions) == 1
    region = regions[0]
    assert region['segment_ids'] == [s['id'] for s in source[1:8]]
    assert region['bbox'] == observed['observed_bbox']
    assert not region['grouping_ambiguous']
    assert not region['ricoh_used']
    assert region['original_text'] == observed['complete_math_text']
    spans = region['source_spans']
    assert spans[1]['original_text'] == '𝑇𝑃'
    numerators = [s for s in spans if s['original_text'] == '24']
    assert [s['reading_order'] for s in numerators] == [37, 39]
    assert numerators[0]['start'] < numerators[1]['start']
    assert all(text[s['start']:s['end']] == s['original_text'] for s in spans)
    assert source[0]['id'] not in region['segment_ids']
    assert source[-1]['id'] not in region['segment_ids']


def test_repeated_numbers_use_local_source_anchors_not_global_count():
    observed = production_precision()
    source = observed['production_segments']
    # Delete the second numerator but add an identical line outside the formula.
    # Global source/editing counts are still two; borrowing that line is unsafe.
    text = observed['editing_text']+'\n24'
    region = source_regions(source, text)[0]
    assert source[4]['id'] in region['segment_ids']
    assert source[6]['id'] not in region['segment_ids']
    assert all(text[s['start']:s['end']] == s['original_text'] for s in region['source_spans'])


def test_repeated_numbers_without_unique_global_matches_align_in_source_order():
    observed = production_precision()
    source = observed['production_segments']
    text = '24\n'+observed['complete_source_text']+'\n24'
    region = source_regions(source, text)[0]
    assert region['segment_ids'] == [s['id'] for s in source[1:8]]
    assert [s['reading_order'] for s in region['source_spans'] if s['original_text'] == '24'] == [37, 39]


def test_real_geometry_crop_and_one_unimumer_request(tmp_path, monkeypatch):
    observed = production_precision()
    service, _, _, _, calls = setup_service(tmp_path, monkeypatch, response=observed['raw_response'])
    # Representative rendered PDF at the supplied coordinates, not the actual
    # production artifact. Do not send an empty crop to the managed response.
    from scoring.math_source_tokens import canonical_math_letters
    path = tmp_path/'production-coordinate-fixture.pdf'
    with fitz.open() as document:
        page = document.new_page()
        for segment in observed['production_segments'][1:8]:
            box = segment['bbox']
            page.insert_text((box[0], box[3]-1), canonical_math_letters(segment['original_text']), fontsize=6)
        for denominator in (3, 5, 7):
            box = observed['production_segments'][denominator]['bbox']
            page.draw_line((box[0], 510.8), (box[2]-4, 510.8), width=.4)
        document.save(path)
    original = observed['complete_source_text']
    result = service.propose(path, observed['production_segments'], original)
    assert result['status'] == 'ambiguous'
    assert calls == ['math_ocr', 'inference']  # No Ricoh or Ornith startup.
    assert result['grouping_summary']['aligned_math_segment_count'] == 7
    assert result['grouping_summary']['geometry_region_count'] == 1
    assert result['grouping_summary']['final_region_count'] == 1
    region = result['math_regions'][0]
    assert region['bbox'] == observed['observed_bbox']
    assert region['crop_bbox'] == observed['observed_crop_bbox']
    assert [region['crop_width'], region['crop_height']] == observed['observed_crop_dimensions']
    assert region['validation'] == 'accepted'
    assert region['final_candidate'] == observed['expected']
    assert not region['ornith_used']
    assert not region['numeric_review_required']
    assert result['normalized_text'].startswith('2. Precision（適合率）\n$$\n')
    assert result['normalized_text'].endswith('答え：0.800（80%）')
    assert result['original_text'] == original
