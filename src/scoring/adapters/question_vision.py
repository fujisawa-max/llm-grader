"""Question-region inference using the existing local multimodal HTTP client."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import time

from ..core import LocalClient, generation_payload, image_content
from ..pdf_native import canonical_hash, sha256_file
from ..vision_output import parse_output

PROMPTS = {
    "math_ocr": {"version": "formula-vision-prompt-v1", "text":
        "切り出された画像内の数式をLaTeXに転写してください。説明、Markdown、$区切りを付けず、"
        "LaTeX本体だけを出力してください。複数の式がある場合は画像上の順序で改行して列挙してください。"
        "式を解いたり、誤りを修正したり、見えない式を補ったりしないでください。"},
    "ocr": {"version": "figure-vision-prompt-v1", "text":
        "画像に印刷された情報だけを観察してください。問題を解かないでください。関数式や正解を推測しないでください。"
        "軸ラベル、数値、記号、曲線や図形、明らかな位置関係を記録してください。"
        "JSONだけを返してください。各値は文字列の配列です: "
        '{"visible_text":[],"labels":[],"visual_elements":[],"spatial_relations":[]}。'
        "読めないものは推測せず不明と記述してください。"},
}


def prompt_metadata():
    return {role: {**value, "sha256": hashlib.sha256(value["text"].encode()).hexdigest()}
            for role, value in PROMPTS.items()}


def normalize_output(raw, role, native):
    """Compatibility entrypoint; role-specific parsing lives outside runtime code."""
    return parse_output(raw, role, native)


class RuntimeVisionAdapter:
    """Sequential borrowed/owned lifecycle; never stops borrowed runtimes."""
    def __init__(self, manager, config):
        self.manager, self.config = manager, config

    def metadata(self, roles):
        result = {}
        for role in sorted(roles):
            settings = self.config.get("models", {}).get(role)
            if not settings:
                raise ValueError("missing_model_asset")
            status = self.manager.status(settings.get("runtime_id", role))
            profile = status["profile"]
            hashes = {}
            for name in ("model", "mmproj"):
                path = profile.get(f"{name}_path")
                if path:
                    if not Path(path).is_file():
                        raise ValueError("missing_model_asset")
                    hashes[f"{name}_sha256"] = sha256_file(Path(path))
                    hashes[f"{name}_identifier"] = Path(path).name
                elif profile.get(f"{name}_sha256"):
                    hashes[f"{name}_sha256"] = profile[f"{name}_sha256"]
                    hashes[f"{name}_identifier"] = "external-declared"
                else:
                    raise ValueError("missing_model_asset_identity")
            generation = {**profile.get("generation", {}), **self.config.get("generation", {}),
                          **settings.get("generation", {})}
            # RuntimeProfile generation supplies existing supported llama parameters.
            payload = generation_payload(generation)
            binary = profile.get("server_binary")
            binary_hash = sha256_file(Path(binary)) if binary and Path(binary).is_file() else None
            if not binary_hash and not profile.get("llama_version"):
                raise ValueError("missing_runtime_identity")
            result[role] = {**hashes, "alias": profile["model_id"], "quantization": profile.get("expected_ftype"),
                            "runtime_backend": "llama.cpp", "runtime_binary_sha256": binary_hash,
                            "declared_runtime_version": None if binary_hash else profile.get("llama_version"),
                            "runtime_id": settings.get("runtime_id", role), "generation": generation,
                            "generation_payload": payload, "request_timeout_seconds": settings.get("request_timeout_seconds", 180),
                            "runtime_parameters": {k: profile.get(k) for k in
                                ("context_size", "batch_size", "ubatch_size", "gpu_layers", "flash_attention")},
                            "additional_args_sha256": canonical_hash(profile.get("additional_args", []))}
        return result

    @contextmanager
    def acquire(self, role, metadata):
        runtime_id = metadata["runtime_id"]
        before = self.manager.status(runtime_id)
        owned = (before["profile"]["runtime_type"] == "managed" and
                 before["state"] not in {"ready", "starting"} and before.get("pid") is None)
        started = time.monotonic()
        try:
            ready = self.manager.ensure_running(runtime_id)
            if ready.get("ok") is False or (ready["profile"]["runtime_type"] == "managed" and ready["state"] != "ready"):
                raise RuntimeError("model_runtime_failed")
            self.endpoint = ready["profile"]["endpoint"]
            self.active_metadata = metadata
            self.runtime_observation = {"startup_seconds": time.monotonic()-started,
                                        "owned": owned, "llama_version": ready["profile"].get("llama_version")}
            yield self
        finally:
            if owned:
                self.manager.stop(runtime_id)

    def infer(self, role, crop):
        metadata = self.active_metadata
        settings = {"models": {role: {"base_url": self.endpoint, "model_id": metadata["alias"],
                    "generation": metadata["generation"], "request_timeout_seconds": metadata["request_timeout_seconds"]}}}
        client = LocalClient(settings, role)
        content = [{"type": "text", "text": PROMPTS[role]["text"]}, image_content(crop)]
        payload = {"model": metadata["alias"], "messages": [{"role": "user", "content": content}],
                   **metadata["generation_payload"], "stream": False}
        if role == "ocr":
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return client.request(client.base + "/chat/completions", payload)
