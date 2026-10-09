"""Actual Sample Q5 geometry, including its boundary-adjacent shared diagram."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from scoring.adapters.artifacts import RunArtifactAdapter
from scoring.diagram_regions import _contains
from scoring.diagram_sources import model_answer_diagram_candidates
from scoring.model_answer_geometry import question_regions
from scoring.pdf_native import PyMuPdfNativeExtractor, sha256_file


@pytest.fixture
def sample_q5(tmp_path):
    root = Path(__file__).resolve().parents[1] / 'testData' / 'SampleQ'
    question, answer = root / 'sampleQ5.pdf', root / 'modelAnswer' / 'sampleQ5_modelAnswer.pdf'
    extractor = PyMuPdfNativeExtractor()
    question_ir = extractor.extract(question, source_sha256=sha256_file(question),
        material_id='question-binding', output_dir=tmp_path / 'question').as_dict()
    answer_ir = extractor.extract(answer, source_sha256=sha256_file(answer),
        material_id='answer-binding', output_dir=tmp_path / 'answer').as_dict()
    questions = [SimpleNamespace(id=f'q{i}', parent_id=None, display_label=f'問題{i}',
        question_number=str(i), sort_order=i) for i in range(1, 4)]
    questions += [SimpleNamespace(id=f'q{major}-{i}', parent_id=f'q{major}', display_label=f'({i})',
        question_number=f'({i})', sort_order=i) for major, count in [(2, 2), (3, 3)] for i in range(1, count+1)]
    regions = question_regions(answer_ir, questions, question_ir=question_ir)
    return answer, answer_ir, RunArtifactAdapter(tmp_path / 'answer'), regions


def candidates(sample, target, segments=()):
    source, ir, store, regions = sample
    return model_answer_diagram_candidates(source, ir, store,
        entry={'id': f'entry-{target}', 'question_id': target, 'source': {'segments': list(segments)}},
        question_regions=regions)


def test_real_q5_parent_frame_near_q2_boundary_is_discoverable_and_crop_stays_in_q3(sample_q5):
    _, exact = candidates(sample_q5, 'q3-1')
    assert exact == []  # The complete diagram spans several split children.
    engine, parent = candidates(sample_q5, 'q3')
    assert len(parent) == 1
    diagram = parent[0]
    assert diagram['automatic_bbox'] == pytest.approx([343.7000, 614.7760, 533.0500, 774.6760], abs=.001)
    assert 'page-0001-drawing-0078' in diagram['source_element_ids']  # Q3 frame
    assert 'page-0001-drawing-0111' not in diagram['source_element_ids']  # crossing Q2 annotation
    assert diagram['material_id'] == 'answer-binding'
    assert diagram['source_sha256'] == sample_q5[1]['source']['sha256']
    crop = engine.crop(diagram)
    region = next(r for r in sample_q5[3] if r['question_id'] == 'q3')
    assert _contains([region['left'], region['top'], region['right'], region['bottom']], crop['crop_bbox'])
    assert crop['crop_bbox'][1] == pytest.approx(region['top'])
    assert engine.store.path(crop['artifact_ref']).is_file()


def test_real_q5_image_source_ids_cannot_bypass_split_child_discovery_scope(sample_q5):
    image_ids = [e['element_id'] for e in sample_q5[1]['pages'][0]['elements'] if e['type'] == 'image']
    _, exact = candidates(sample_q5, 'q3-1', [{'page_index': 0, 'element_ids': image_ids}])
    assert exact == []


def test_real_q5_parent_crop_cannot_expand_into_another_major_question(sample_q5):
    engine, parent = candidates(sample_q5, 'q3')
    with pytest.raises(ValueError, match='diagram_source_boundary'):
        engine.crop(parent[0], final_bbox=[330, 400, 530, 500])
    _, other = candidates(sample_q5, 'q2-1')
    assert not any(c['id'] == parent[0]['id'] or _contains(c['automatic_bbox'], parent[0]['automatic_bbox'])
                   for c in other)
