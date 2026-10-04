import pytest

from scoring.latex_normalization import validate_proposal


def proposal(text, status="safe"):
    return {"status": status, "normalized_text": text, "confidence": 0.95, "warnings": [], "changes": []}


@pytest.mark.parametrize("source,target", [
    ("TP / (TP + FP)", r"$\frac{TP}{TP+FP}$"),
    ("Precision = TP / (TP + FP)", r"$Precision=\frac{TP}{TP+FP}$"),
    ("Recall = TP / (TP + FN)", r"$Recall=\frac{TP}{TP+FN}$"),
    ("24 / 30 = 0.7", r"$\frac{24}{30}=0.7$"),
    ("24 / 30 = 0.800\n答え：0.800（80%）", "$\\frac{24}{30}=0.800$\n答え：0.800（80%）"),
    ("式 TP / (TP + FP) を使う。", r"式 $\frac{TP}{TP+FP}$ を使う。"),
    ("-24 / 30 = -0.800", r"$\frac{-24}{30}=-0.800$"),
] )
def test_safe(source, target):
    assert validate_proposal(source, proposal(target))["status"] == "safe"


@pytest.mark.parametrize("target", [r"$\frac{24}{30}=0.8$", r"$\frac{24}{30}=0.700$", "24 / 30 = 0.7 答えは正しい。", "24 / 30 = 0.7 + 1", "24 / 30 = 0.7 答え：80%"])
def test_changed_content_rejected(target):
    assert validate_proposal("24 / 30 = 0.7", proposal(target))["status"] == "rejected"


def test_answer_removed_rejected():
    assert validate_proposal("24 / 30 答え：0.800（80%）", proposal(r"$\frac{24}{30}$"))["status"] == "rejected"


def test_ambiguous_precedence():
    assert validate_proposal("Accuracy = TP+TN / TP+FP+FN+TN", proposal(r"$Accuracy=\frac{TP+TN}{TP+FP+FN+TN}$"))["status"] == "ambiguous"


def test_no_change():
    assert validate_proposal("文章のみ。", proposal("文章のみ。"))["status"] == "no_change"


@pytest.mark.parametrize("bad", ["not json", {}, {**proposal("x"), "status": "unknown"}, {**proposal("x"), "confidence": True}, {**proposal("x"), "extra": 1}, {**proposal("x"), "changes": [{"type": "fraction", "source": "invented"}]}])
def test_invalid_output(bad):
    with pytest.raises((ValueError, TypeError)):
        validate_proposal("x", bad)


def test_removed_division_rejected():
    assert validate_proposal("TP / FP", proposal("TP FP"))["status"] == "rejected"


def test_reordered_prose_rejected():
    assert validate_proposal("未知データでは低下。", proposal("低下では未知データ。"))["status"] == "rejected"


def test_runtime_reuse(monkeypatch):
    import scoring.latex_normalization as module

    class Manager:
        calls = 0

        def ensure_running(self, profile):
            self.calls += 1
            assert profile == "ornith_rubric_draft"
            return {"endpoint": "http://127.0.0.1:8000/v1", "profile": {"model_id": "synthetic", "generation": {}}}

        def stop(self, profile):
            pytest.fail("normalization must not stop shared runtime")

    class Client:
        generation = __import__("scoring.core", fromlist=["DEFAULT_GENERATION"]).DEFAULT_GENERATION

        def __init__(self, config, role):
            pass

        def request(self, endpoint, body):
            assert body["response_format"]["json_schema"]["name"] == "latex_normalization"
            assert body["chat_template_kwargs"]["enable_thinking"] is False
            assert body["stream"] is False
            return {"choices": [{"finish_reason": "stop", "message": {"content": __import__("json").dumps(proposal(r"$\frac{TP}{FP}$"))}}]}

    monkeypatch.setattr(module, "LocalClient", Client)
    manager = Manager()
    service = module.LatexNormalizer(manager)
    assert manager.calls == 0
    for _ in range(2):
        assert service.normalize("TP / FP", "question")["status"] == "safe"
    assert manager.calls == 2


@pytest.mark.parametrize("source,target", [
    ("TP / TP+FP", r"$\frac{TP}{TP+FP}$"),
    ("Precision=\nTP /\n(TP+FP)", "$Precision=\\frac{TP}{TP+FP}$"),
])
def test_fraction_ambiguity(source, target):
    assert validate_proposal(source, proposal(target))["status"] == "ambiguous"


def test_parentheses_lost():
    assert validate_proposal("a * (b + c)", proposal("$a*b+c$"))["status"] == "rejected"


def test_chained_calculation():
    assert validate_proposal("24 / 30 = 24 / 30 = 0.800", proposal(r"$\frac{24}{30}=\frac{24}{30}=0.800$"))["status"] == "safe"


@pytest.mark.parametrize("error", [ValueError("bad JSON"), RuntimeError("unavailable"), TimeoutError("timeout")])
def test_api_failure_keeps_no_persistence(monkeypatch, error):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from types import SimpleNamespace
    import scoring.api.text_tools as module

    def unavailable(*args):
        raise error

    monkeypatch.setattr(module.LatexNormalizer, "normalize", unavailable)
    app = FastAPI()
    app.include_router(module.router(SimpleNamespace(manager=object(), profile_id="synthetic")))
    response = TestClient(app).post("/api/v1/text-tools/latex-normalize", json={"text": "TP / FP"})
    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "NORMALIZATION_FAILED"
