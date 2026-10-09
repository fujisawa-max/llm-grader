from copy import deepcopy
from unittest.mock import patch

import pytest

from tests.test_authoring_diagrams import workspace as source_workspace, begin, save, manual
from tests.test_sample_q5_answer_diagrams import sample_q5 as real_sample_q5
from tests.test_diagram_review_api import clean

workspace = source_workspace
sample_q5 = real_sample_q5


def setup_crop(w):
    path, row = begin(w, w.answer['test_id'])
    key = row['snapshot']['nodes'][0]['stable_key']
    entry = manual(key)
    endpoint = path + f'/entries/{entry["id"]}/manual-crop?question_id={key}'
    return path, row, key, entry, endpoint


def test_manual_crop_provenance_preview_save_resume_without_discovery(workspace):
    w = workspace
    path, row, key, entry, endpoint = setup_crop(w)
    with patch('scoring.diagram_regions.DiagramRegionExtractor.candidates', side_effect=AssertionError('no discovery')):
        source = w.client.get(endpoint)
        assert source.status_code == 200, source.text
        result = w.client.post(endpoint, json={'expected_revision': row['edit_version'], 'page_index': 0, 'bbox': [20, 20, 90, 70]})
        assert result.status_code == 200, result.text
        record = result.json()
        assert record['source_type'] == 'manual_pdf_crop'
        assert record['scope'] == 'manual'
        assert record['material_id'] == source.json()['material_id']
        assert record['assigned_question_id'] == key
        assert record['crop_bbox'] == [20, 20, 90, 70]
        assert w.client.get(record['preview_url']).status_code == 200
        snapshot = deepcopy(row['snapshot'])
        entry['diagram_records'] = [{**clean(record), 'state': 'accepted', 'teacher_confirmed': True}]
        snapshot['domains']['answer']['entries'].append(entry)
        saved = save(w, path, row, snapshot)
        restored = w.client.get(path).json()['revision']
        assert restored == saved
        accepted = saved['snapshot']['domains']['answer']['entries'][-1]['diagram_records'][0]
        assert accepted['teacher_confirmed'] is True
        assert accepted['acceptance_method'] == 'teacher_manual_pdf_crop'
        assert accepted['crop_sha256'] == record['crop_sha256']
        assert saved['snapshot']['rubrics'] == row['snapshot']['rubrics']
        assert saved['snapshot']['nodes'] == row['snapshot']['nodes']


@pytest.mark.parametrize('page,bbox', [(99,[20,20,90,70]),(0,[20,20,20,70]),(0,[-1,20,90,70]),(0,[20,20,10000,70])])
def test_manual_crop_rejects_invalid_page_or_bbox(workspace, page, bbox):
    w = workspace
    _, row, _, _, endpoint = setup_crop(w)
    result = w.client.post(endpoint, json={'expected_revision': row['edit_version'], 'page_index': page, 'bbox': bbox})
    assert result.status_code == 422, result.text


def test_manual_crop_rejects_stale_version_and_forged_source_identity(workspace):
    w = workspace
    path, row, key, entry, endpoint = setup_crop(w)
    result = w.client.post(endpoint, json={'expected_revision': row['edit_version']+1, 'page_index': 0, 'bbox': [20,20,90,70]})
    assert result.status_code == 409
    record = w.client.post(endpoint, json={'expected_revision': row['edit_version'], 'page_index': 0, 'bbox': [20,20,90,70]}).json()
    snapshot = deepcopy(row['snapshot'])
    entry['diagram_records'] = [{**clean(record), 'state': 'accepted', 'teacher_confirmed': True, 'material_id': 'foreign-binding'}]
    snapshot['domains']['answer']['entries'].append(entry)
    rejected = w.client.put(path, json={'expected_edit_version': row['edit_version'], 'snapshot': snapshot})
    assert rejected.status_code == 409
    assert rejected.json()['error']['code'] == 'AUTHORING_ANSWER_SOURCE_INVALID'
    assert w.client.get(path).json()['revision'] == row
    foreign_endpoint = endpoint.replace(w.answer['test_id'], w.data['test_id'])
    foreign = w.client.post(foreign_endpoint, json={'expected_revision': row['edit_version'], 'page_index': 0, 'bbox': [20,20,90,70]})
    assert foreign.status_code in {409, 422}
    source = w.client.get(endpoint).json()
    deleted = w.client.delete(f'/api/v1/tests/{w.answer["test_id"]}/materials/{source["material_id"]}')
    assert deleted.status_code == 200
    unavailable = w.client.post(endpoint, json={'expected_revision': row['edit_version'], 'page_index': 0, 'bbox': [20,20,90,70]})
    assert unavailable.status_code == 422



def test_manual_crop_same_major_reuse_revalidates_saved_artifact(sample_q5):
    from types import SimpleNamespace
    from scoring.model_answer_diagram_review import ModelAnswerDiagramReview
    source, ir, store, regions = sample_q5
    keys = {r['question_id'] for r in regions}
    questions = [SimpleNamespace(id=k, parent_id=k.split('-')[0] if '-' in k else None,
        display_label=k, question_number=k, sort_order=1, is_gradable='-' in k or k == 'q1') for k in keys]
    first = {'id': 'entry-one', 'question_id': 'q3-1', 'source': {'segments': []}, 'diagram_records': []}
    second = {'id': 'entry-two', 'question_id': 'q3-2', 'source': {'segments': []}, 'diagram_records': []}
    context = {'draft_id': 'answer-draft', 'entries': [first, second]}
    a = ModelAnswerDiagramReview(source, ir, store, entry=first, question_regions=regions, questions=questions, reuse_context=context)
    with patch('scoring.diagram_regions.DiagramRegionExtractor.candidates', side_effect=AssertionError('no discovery')):
        candidate = a.manual_review().create(0, [20, 20, 90, 70])
        first['diagram_records'] = [{**candidate, 'state': 'accepted', 'teacher_confirmed': True}]
        first['diagram_records'] = a.validate(first['diagram_records'], 2)
        b = ModelAnswerDiagramReview(source, ir, store, entry=second, question_regions=regions, questions=questions, reuse_context=context)
        available = b.reuse().available(2)
        assert len(available) == 1
        reused = b.reuse().validate({**available[0], 'state': 'accepted'}, 3)
        assert reused['source_type'] == 'manual_pdf_crop'
        assert reused['assigned_question_id'] == 'q3-2'
        assert reused['crop_sha256'] == candidate['crop_sha256']
        assert first['diagram_records'][0]['assigned_question_id'] == 'q3-1'
        b.preview(reused)
        assert b.reuse().preview_path(reused['id'], reused['reuse_ref'], reused['crop_sha256']).is_file()
        other = {**second, 'question_id': 'q2-1'}
        c = ModelAnswerDiagramReview(source, ir, store, entry=other, question_regions=regions, questions=questions, reuse_context=context)
        assert c.reuse().available(3) == []
        with pytest.raises(ValueError):
            c.reuse().record(reused['id'], reused['reuse_ref'])


