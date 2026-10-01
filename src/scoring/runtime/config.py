"""Resolve installed model definitions and purpose profiles without a DB catalog."""

import json
import os
import re
from pathlib import Path

from .manager import RuntimeProfile, profiles_from_runtime_config


def _expand(value):
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}",
                      lambda m: os.getenv(m[1], m[2] or ""), value)
    return value


def load_runtime_config(path):
    config = _expand(json.loads(Path(path).read_text(encoding="utf-8")))
    if config.get("schema_version", 1) == 1:
        return profiles_from_runtime_config(config), {}
    if config.get("schema_version") != 2:
        raise ValueError("unsupported runtime config schema_version")
    models = config.get("model_definitions", {})
    profiles = {}
    model_fields = {"model_id", "model_path", "mmproj_path", "vision", "expected_ftype",
                    "model_sha256", "mmproj_sha256"}
    for name, assignment in config.get("profiles", {}).items():
        model_ref = assignment.get("model_ref")
        if model_ref not in models:
            raise ValueError(f"unknown model assignment for profile {name}")
        model = models[model_ref]
        if not model.get("model_id"):
            raise ValueError(f"model_id is required for model {model_ref}")
        resolved = {**config.get("runtime_defaults", {}),
                    **{key: value for key, value in model.items() if key in model_fields},
                    **assignment, "runtime_id": name}
        profiles[name] = RuntimeProfile.from_mapping(name, resolved)
    if not profiles:
        raise ValueError("runtime profiles are empty")
    return profiles, models
