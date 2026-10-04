import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from scoring.core import LocalClient
from scoring.model_answer_classification import ModelAnswerSemanticClassifier
from scoring.runtime.client import RuntimeManagerClient
from scoring.runtime.config import load_runtime_config
from scoring.runtime.network import validate_endpoint
from tests.runtime_fixture import runtime_service


def test_real_manager_managed_process_classifier_and_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_GRADER_TRUSTED_RUNTIME_HOSTS", "127.0.0.2")
    with runtime_service(tmp_path) as (client, url, process):
        assert len(client.profiles()) == 3
        assert client.models()["default_text"]["model_id"] == "synthetic-text-model"
        before = client.status("ornith_rubric_draft")
        assert before["pid"] is None and before["state"] == "stopped"
        classifier = ModelAnswerSemanticClassifier(client)
        result = classifier.classify(
            question_context={"label": "問題1", "body": "Explain overfitting."},
            candidate_text="Explain overfitting.\nIt memorizes the training data.\n5 points: explain it.\nAlternative: high variance.")
        assert result["status"] == "classified"
        assert result["primary_answer_text"] == "It memorizes the training data.\n"
        assert result["rubric_candidates"] and result["alternative_answers"]
        classifier_pid = client.status("ornith_rubric_draft")["pid"]
        assert classifier_pid is not None
        repeated = classifier.classify(question_context={"body": "Explain overfitting."},
                                       candidate_text="It memorizes the training data.")
        assert repeated["status"] == "classified"
        assert client.status("ornith_rubric_draft")["pid"] == classifier_pid
        client.stop("ornith_rubric_draft")
        assert client.status("ornith_rubric_draft")["pid"] is None
        assert any("POST /v1/chat/completions" in line for line in client.logs("ornith_rubric_draft")["lines"])
        ready = client.start("grader")
        pid = ready["pid"]
        assert "127.0.0.2" in ready["profile"]["endpoint"]
        assert client.health("grader")["ok"]
        restarted = client.restart("grader")
        assert restarted["pid"] != pid
        client.stop("grader")
        for bad in ["/foo/grader/start", "/internal/runtimes", "/internal/runtimes/grader/start/extra"]:
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(urllib.request.Request(url.removesuffix("/internal") + bad, method="POST"))
            assert caught.value.code == 404
        assert process.poll() is None


def test_model_missing_does_not_fail_manager_health(tmp_path):
    with runtime_service(tmp_path, model_present=False) as (client, url, process):
        with urllib.request.urlopen(url + "/health") as response:
            assert json.load(response)["ok"]
        status = client.status("ornith_rubric_draft")
        assert status["state"] == "unavailable"
        assert status["availability"] == "model_missing"
        with pytest.raises(RuntimeError, match="model path"):
            client.ensure_running("ornith_rubric_draft")
        assert process.poll() is None


def test_config_assignments_and_legacy_compatibility(tmp_path):
    root = Path(__file__).resolve().parents[1]
    profiles, models = load_runtime_config(root / "config/runtime.deployment.json")
    assert set(profiles) == {"grader", "ornith_rubric_draft", "math_ocr"}
    assert all(profiles[name].model_ref == "default_text" for name in ("grader", "ornith_rubric_draft"))
    assert profiles["math_ocr"].model_ref == "unimumer"
    assert profiles["math_ocr"].vision
    assert models["default_text"]["vision"] is False
    legacy, _ = load_runtime_config(root / "config/runtime.example.json")
    assert all(profile.runtime_type == "external" for profile in legacy.values())
    config = tmp_path / "invalid.json"
    config.write_text(json.dumps({"schema_version": 2, "profiles": {"grader": {"model_ref": "fake"}}}))
    with pytest.raises(ValueError, match="unknown model assignment"):
        load_runtime_config(config)


def test_runtime_host_allowlist_and_origin(monkeypatch):
    monkeypatch.delenv("LLM_GRADER_TRUSTED_RUNTIME_HOSTS", raising=False)
    for url in ["http://runtime-manager:18080/v1", "http://169.254.169.254/v1", "http://example.com/v1"]:
        with pytest.raises(ValueError):
            validate_endpoint(url)
    monkeypatch.setenv("LLM_GRADER_TRUSTED_RUNTIME_HOSTS", "runtime-manager")
    validate_endpoint("http://runtime-manager:18080/v1")
    for url in ["http://user@runtime-manager/v1", "http://runtime-manager/v1?url=x",
                "http://runtime-manager.attacker.invalid/v1", "http://runtime-manager:0/v1"]:
        with pytest.raises(ValueError):
            validate_endpoint(url)
    client = LocalClient({"models": {"grader": {"base_url": "http://runtime-manager:18080/v1"}}}, "grader")
    with pytest.raises(ValueError, match="configured endpoint"):
        client.request("http://169.254.169.254/latest/meta-data")


def test_runtime_redirect_is_rejected():
    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data")
            self.end_headers()
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = LocalClient({"models": {"grader": {"base_url": f"http://127.0.0.1:{server.server_port}/v1"}}}, "grader")
        with pytest.raises(ValueError, match="redirects"):
            client.request(client.base + "/chat/completions", {})
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('disconnect', [BrokenPipeError, ConnectionResetError])
def test_disconnected_health_client_does_not_resend_500(disconnect):
    from unittest.mock import Mock
    from scoring.runtime.http_api import RuntimeHTTPHandler
    handler = object.__new__(RuntimeHTTPHandler)
    handler.path = '/internal/health'
    handler.manager = Mock()
    handler.manager.statuses.return_value = []
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = Mock()
    handler.wfile.write.side_effect = disconnect
    handler.do_GET()
    handler.send_response.assert_called_once_with(200)
    handler.wfile.write.assert_called_once()


def test_real_manager_error_still_returns_500():
    from io import BytesIO
    from unittest.mock import Mock
    from scoring.runtime.http_api import RuntimeHTTPHandler
    handler = object.__new__(RuntimeHTTPHandler)
    handler.path = '/internal/health'
    handler.manager = Mock()
    handler.manager.statuses.side_effect = RuntimeError('real runtime error')
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = BytesIO()
    handler.do_GET()
    handler.send_response.assert_called_once_with(500)
    assert json.loads(handler.wfile.getvalue())['error'] == 'real runtime error'


def test_startup_timeout_is_separate_from_status_timeout():
    from unittest.mock import Mock
    client = RuntimeManagerClient(timeout=120, startup_timeout=330)
    client._call = Mock(return_value={})
    client.ensure_running('grader')
    client._call.assert_called_with('POST', '/runtimes/grader/ensure', timeout=330)
    client.status('grader')
    client._call.assert_called_with('GET', '/runtimes/grader/status')


def test_standard_classifier_generation_does_not_change_grader():
    profiles, _ = load_runtime_config(Path(__file__).resolve().parents[1] / 'config/runtime.deployment.json')
    assert profiles['ornith_rubric_draft'].generation['max_output_tokens'] == 512
    assert profiles['ornith_rubric_draft'].chat_template_kwargs == {'enable_thinking': False}
    assert profiles['grader'].generation['max_output_tokens'] == 4096
    assert profiles['grader'].chat_template_kwargs == {}
