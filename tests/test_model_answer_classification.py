import json
import unittest
from unittest.mock import patch

from scoring.model_answer_classification import (
    ClassificationOutputError,
    CLASSIFICATION_SCHEMA,
    ModelAnswerSemanticClassifier,
    build_classification,
    split_source_segments,
)


class ModelAnswerClassificationTests(unittest.TestCase):
    def test_segments_cover_japanese_source_text_without_rewriting(self):
        source = "問題文。\n標準解答です。\n別解です。"
        segments = split_source_segments(source)
        self.assertEqual("".join(item["text"] for item in segments), source)
        self.assertEqual([source[item["start"]:item["end"]] for item in segments],
                         [item["text"] for item in segments])

    def test_only_source_ids_are_accepted_and_categories_are_grouped(self):
        source = "問題文です。\n正答は $x=1$ です。\n正則化の記載に5点。\n別解: $x=-1$"
        segments = split_source_segments(source)
        categories = ["question", "model_answer", "rubric", "alternative_answer"]
        result = build_classification(source, {
            "overall_confidence": 0.99,
            "segments": [{"id": segment["id"], "category": category, "confidence": 0.96}
                         for segment, category in zip(segments, categories)],
        })
        self.assertEqual(result["status"], "classified")
        self.assertEqual(result["primary_answer_text"], "正答は $x=1$ です。\n")
        self.assertEqual(result["rubric_candidates"][0]["text"], "正則化の記載に5点。\n")
        self.assertEqual(result["alternative_answers"][0]["text"], "別解: $x=-1$")
        self.assertEqual(result["question_segments"][0]["text"], "問題文です。\n")
        self.assertTrue(all(item["source_text"] in source for item in result["segments"]))

    def test_unknown_duplicate_missing_and_generated_text_are_rejected(self):
        source = "正答です。"
        segment = split_source_segments(source)[0]
        assignment = {"id": segment["id"], "category": "model_answer", "confidence": 0.99}
        invalid_results = [
            {"overall_confidence": 0.99, "segments": [{**assignment, "id": "invented"}]},
            {"overall_confidence": 0.99, "segments": [assignment, assignment]},
            {"overall_confidence": 0.99, "segments": [{**assignment, "text": "創作された解答"}]},
            {"overall_confidence": 0.99, "segments": []},
        ]
        for result in invalid_results:
            with self.subTest(result=result), self.assertRaises(ClassificationOutputError):
                build_classification(source, result)

    def test_low_confidence_is_review_required_and_keeps_uncertain_segment(self):
        source = "回答文。\n説明か補足か判断できません。"
        segments = split_source_segments(source)
        result = build_classification(source, {
            "overall_confidence": 0.97,
            "segments": [
                {"id": segments[0]["id"], "category": "model_answer", "confidence": 0.95},
                {"id": segments[1]["id"], "category": "uncertain", "confidence": 0.41},
            ],
        })
        self.assertEqual(result["status"], "needs_teacher_review")
        self.assertEqual(result["uncertain_segments"][0]["text"], segments[1]["text"])

    def test_runtime_adapter_uses_configured_model_and_sends_ids_not_output_text(self):
        source = "再掲された設問です。\n答えは $x=1$ です。"
        segments = split_source_segments(source)
        output = {
            "overall_confidence": 0.99,
            "segments": [
                {"id": segments[0]["id"], "category": "question", "confidence": 0.98},
                {"id": segments[1]["id"], "category": "model_answer", "confidence": 0.97},
            ],
        }

        class Manager:
            def status(self, profile_id):
                self.profile_id = profile_id
                return {"profile": {"runtime_type": "external"}, "pid": None}

            def ensure_running(self, profile_id):
                self.profile_id = profile_id
                return {"endpoint": "http://127.0.0.1:18081/v1", "profile": {
                    "model_id": "runtime-selected-model",
                    "generation": {"temperature": 0, "seed": 3, "top_k": 20, "top_p": 0.9,
                                    "min_p": 0.1, "repeat_penalty": 1.0, "max_output_tokens": 2048},
                }}

        class Client:
            generation = {"temperature": 0, "seed": 3, "top_k": 20, "top_p": 0.9,
                          "min_p": 0.1, "repeat_penalty": 1.0, "max_output_tokens": 2048}
            last_payload = None
            last_url = None

            def __init__(self, config, role):
                self.config = config
                self.role = role

            def request(self, url, payload):
                self.url = url
                self.payload = payload
                Client.last_url = url
                Client.last_payload = payload
                return {"choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps(output, ensure_ascii=False),
                }}]}

        manager = Manager()
        with patch("scoring.model_answer_classification.LocalClient", Client):
            result = ModelAnswerSemanticClassifier(manager, "configured-classifier").classify(
                question_context={"label": "問題2 > (1)", "body": "再掲された設問です。"},
                candidate_text=source,
            )
        self.assertEqual(manager.profile_id, "configured-classifier")
        self.assertEqual(result["primary_answer_text"], "答えは $x=1$ です。")
        self.assertEqual(CLASSIFICATION_SCHEMA["additionalProperties"], False)
        self.assertEqual(Client.last_url, "http://127.0.0.1:18081/v1/chat/completions")
        self.assertEqual(Client.last_payload["model"], "runtime-selected-model")
        user_payload = json.loads(Client.last_payload["messages"][1]["content"])
        self.assertEqual(user_payload["question"]["label"], "問題2 > (1)")
        self.assertEqual([item["id"] for item in user_payload["source_segments"]],
                         [item["id"] for item in segments])
        self.assertNotIn("text", CLASSIFICATION_SCHEMA["properties"]["segments"]["items"]["properties"])


if __name__ == "__main__":
    unittest.main()


def test_managed_classifier_never_stops_after_success_or_failure():
    from unittest.mock import Mock
    import pytest
    manager = Mock()
    manager.ensure_running.return_value = {"profile": {
        "runtime_type": "managed", "endpoint": "http://127.0.0.1:18081/v1",
        "model_id": "fixture", "request_timeout_seconds": 321,
        "generation": {"max_output_tokens": 512},
    }}
    response = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
        "overall_confidence": 0.99,
        "segments": [{"id": "s0001", "category": "model_answer", "confidence": 0.99}],
    })}}]}
    requests = []
    def answer(client, url, payload):
        assert client.timeout == 321
        requests.append(payload)
        return response
    classifier = ModelAnswerSemanticClassifier(manager)
    with patch("scoring.model_answer_classification.LocalClient.request", answer):
        for _ in range(2):
            assert classifier.classify(question_context={}, candidate_text="Source answer.")["status"] == "classified"
    assert manager.ensure_running.call_count == 2
    assert requests[0]["max_tokens"] == 512
    assert requests[0]["chat_template_kwargs"]["enable_thinking"] is False
    with patch("scoring.model_answer_classification.LocalClient.request", side_effect=TimeoutError):
        with pytest.raises(TimeoutError):
            classifier.classify(question_context={}, candidate_text="Source answer.")
    manager.stop.assert_not_called()


def test_native_geometry_batches_are_grounded_and_reuse_runtime():
    from unittest.mock import Mock
    manager = Mock()
    manager.ensure_running.return_value = {"profile": {
        "runtime_type": "managed", "endpoint": "http://127.0.0.1:18081/v1", "model_id": "fixture",
        "generation": {"max_output_tokens": 512},
    }}
    text, spans = '', []
    for i in range(13):
        value = f'Original line {i}.\n'
        spans.append({'id': f'pdf-{i}', 'text': value, 'start': len(text), 'end': len(text) + len(value),
                      'bbox': [30, i * 20, 150, i * 20 + 12], 'page_index': 0,
                      'geometry': {'question_id': 'q1', 'confidence': .95}})
        text += value
    seen = []
    def answer(client, url, request):
        payload = json.loads(request['messages'][-1]['content'])
        assert len(payload['source_segments']) <= 6
        assert payload['source_segments'][0]['geometry']['question_id'] == 'q1'
        assert request['max_tokens'] == 512
        seen.extend(item['id'] for item in payload['source_segments'])
        assignments = [{'id': item['id'], 'category': 'model_answer', 'confidence': .99}
                       for item in payload['source_segments']]
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
            'overall_confidence': .99, 'segments': assignments,
        })}}]}
    with patch('scoring.model_answer_classification.LocalClient.request', answer):
        result = ModelAnswerSemanticClassifier(manager).classify(
            question_context={'question_id': 'q1'}, candidate_text=text, source_segments=spans)
    assert result['primary_answer_text'] == text
    assert seen == [item['id'] for item in spans]
    manager.ensure_running.assert_called_once()
    manager.stop.assert_not_called()


def test_expired_automatic_budget_falls_back_without_inference_or_runtime_stop():
    from unittest.mock import Mock
    import pytest
    manager = Mock()
    manager.ensure_running.return_value = {'profile': {
        'runtime_type': 'managed', 'endpoint': 'http://127.0.0.1:18081/v1', 'model_id': 'fixture',
        'generation': {'max_output_tokens': 512},
    }}
    with patch('scoring.model_answer_classification.LocalClient.request') as request:
        with pytest.raises(TimeoutError):
            ModelAnswerSemanticClassifier(manager).classify(
                question_context={'deadline_monotonic': 0}, candidate_text='Original source.')
    request.assert_not_called()
    manager.stop.assert_not_called()
