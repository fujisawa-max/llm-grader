import fitz
import pytest

from scoring.source_math_ocr import SourceMathOCR, source_regions


def segments():
    texts = ['Precision=', 'TP', 'TP+FP=', '24', '24+6 =', '30 = 0.800']
    return [{'id': str(i), 'original_text': text, 'page_index': 0,
             'bbox': [50, 50+i*15, 160, 62+i*15], 'reading_order': i}
            for i, text in enumerate(texts)]


def pdf(path):
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 55), 'Precision')
        page.insert_text((110, 48), 'TP')
        page.draw_line((105, 53), (160, 53))
        page.insert_text((105, 68), 'TP+FP')
        document.save(path)


def test_source_alignment_preserves_prose():
    text = '\n'.join(s['original_text'] for s in segments()) + '\nAnswer: 0.800 (80%)'
    regions = source_regions(segments(), text)
    assert len(regions) == 1
    assert text[regions[0]['end']:] == '\nAnswer: 0.800 (80%)'
    assert len(regions[0]['segment_ids']) == 6


def test_no_math_does_not_start_runtime(tmp_path):
    assert SourceMathOCR(None).propose(tmp_path/'missing.pdf', [], 'Prose.')['status'] == 'no_change'
    assert not source_regions(segments(), 'Teacher replaced all source text.')


@pytest.mark.parametrize('box', [[0, 0, 5000, 5000], [2, 2, 2, 2], [0, 0, float('nan'), 50]])
def test_invalid_geometry_before_runtime(tmp_path, box):
    path = tmp_path/'source.pdf'
    pdf(path)
    source = [{'id': '1', 'page_index': 0, 'bbox': box, 'original_text': 'x=1'}]
    with pytest.raises(ValueError):
        SourceMathOCR(None).propose(path, source, 'x=1')


def test_real_managed_math_runtime_cold_warm(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_GRADER_TRUSTED_RUNTIME_HOSTS", "127.0.0.2")
    from tests.runtime_fixture import runtime_service
    path = tmp_path/'source.pdf'
    pdf(path)
    text = '\n'.join(s['original_text'] for s in segments())+'\nAnswer: 0.800 (80%)'
    with runtime_service(tmp_path) as (manager, _, _):
        assert manager.status('math_ocr')['state'] == 'stopped'
        service = SourceMathOCR(manager)
        result = service.propose(path, segments(), text)
        assert result['status'] == 'ambiguous'
        assert r'\frac{TP}{TP+FP}' in result['normalized_text']
        assert r'\frac{24}{24+6}' in result['normalized_text']
        assert r'\frac{24}{30}' in result['normalized_text']
        assert result['normalized_text'].endswith('\nAnswer: 0.800 (80%)')
        assert result['math_regions'][0]['crop_image'].startswith('data:image/png;')
        running = manager.status('math_ocr')
        service.propose(path, segments(), text)
        warm = manager.status('math_ocr')
        assert warm['pid'] == running['pid']
        assert warm['started_at'] == running['started_at']


def test_multiple_regions_keep_source_order():
    source = [
        {'id': 'b', 'original_text': 'y=2', 'bbox': [30, 200, 90, 215], 'page_index': 0, 'reading_order': 2},
        {'id': 'a', 'original_text': 'x=1', 'bbox': [30, 50, 90, 65], 'page_index': 0, 'reading_order': 1},
    ]
    regions = source_regions(source, 'x=1\nProse remains.\ny=2')
    assert [r['segment_ids'] for r in regions] == [['a'], ['b']]


def test_duplicate_source_text_is_not_replaced():
    source = [{'id': 'a', 'original_text': 'x=1', 'bbox': [30, 50, 90, 65], 'page_index': 0}]
    assert source_regions(source, 'x=1\nx=1') == []


def test_ocr_failure_keeps_input(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scoring import source_math_ocr
    path = tmp_path/'source.pdf'
    pdf(path)
    text = 'x=1\nProse'
    source = [{'id': 'a', 'original_text': 'x=1', 'bbox': [30, 50, 90, 65], 'page_index': 0}]
    manager = SimpleNamespace(ensure_running=lambda _: {'state': 'ready', 'profile': {
        'model_id': 'synthetic', 'endpoint': 'http://127.0.0.1:8080/v1', 'runtime_type': 'managed'}})
    def fail(*args):
        raise TimeoutError('synthetic')
    monkeypatch.setattr(source_math_ocr.LocalClient, 'request', fail)
    result = SourceMathOCR(manager).propose(path, source, text)
    assert result["reason_code"] == "math_inference_timeout"
    assert result["status"] == "rejected"
    assert result["math_regions"][0]["crop_image"]
    assert result["normalized_text"] == text
    assert text == 'x=1\nProse'
    assert source[0]['bbox'] == [30, 50, 90, 65]


@pytest.mark.parametrize('latex', ['x=2', 'x=1+invented', 'x='])
def test_unsafe_recognition_rejected(tmp_path, monkeypatch, latex):
    from types import SimpleNamespace
    from scoring import source_math_ocr
    path = tmp_path/'source.pdf'
    pdf(path)
    source = [{'id': 'a', 'original_text': 'x=1', 'bbox': [30, 50, 90, 65], 'page_index': 0}]
    manager = SimpleNamespace(ensure_running=lambda _: {'state': 'ready', 'profile': {
        'model_id': 'synthetic', 'endpoint': 'http://127.0.0.1:8080/v1', 'runtime_type': 'managed'}})
    monkeypatch.setattr(source_math_ocr.LocalClient, 'request', lambda *_: {'choices': [{'message': {'content': latex}}]})
    result = SourceMathOCR(manager).propose(path, source, 'x=1')
    assert result["status"] == "rejected"
    assert result["math_regions"][0]["raw_latex"] == latex
    assert result["math_regions"][0]["crop_image"]
