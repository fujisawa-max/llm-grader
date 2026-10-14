"""Safety tests for the real validation Compose, without a Docker dependency."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validation_compose", ROOT / "scripts/validation-compose.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture
def config(tmp_path):
    env = {}
    for target, key in launcher.MOUNTS.items():
        path = tmp_path / key.lower()
        if target in {"/inputs/allowlist.json", "/run/secrets/readonly_database_url"}:
            path.write_text("{}")
            path.chmod(0o600)
        else:
            path.mkdir(mode=0o700)
        env[key] = str(path)
    raw = json.loads((ROOT / "compose.validation.yaml").read_text())
    for service in raw["services"].values():
        service["build"]["context"] = str(ROOT)
        service["user"] = "65534:65534"
        for mount in service["volumes"]:
            mount["source"] = env[launcher.MOUNTS[mount["target"]]]
    return raw, env


def test_actual_compose_isolation(config):
    raw, env = config
    launcher.validate_config(raw, env)
    assert "environment" not in raw["services"]["acceptance"]
    assert set(v["target"] for v in raw["services"]["acceptance"]["volumes"]) == {
        "/work", "/inputs/allowlist.json"}


@pytest.mark.parametrize("key,value", [
    ("ports", ["8000:8000"]), ("privileged", True), ("runtime", "nvidia"),
    ("devices", ["/dev/nvidia0:/dev/nvidia0"]), ("pid", "host"),
    ("networks", ["llm-scoring_default"]), ("env_file", [".env"]),
    ("environment", {"LLM_GRADER_DATABASE_URL": "secret"}),
    ("entrypoint", ["bash"]), ("deploy", {"resources": {}}),
    ("network_mode", "host"), ("read_only", False), ("user", "0:0"),
    ("security_opt", []), ("cap_drop", []),
])
def test_exposed_resources_rejected(config, key, value):
    raw, env = config
    raw["services"]["acceptance"][key] = value
    with pytest.raises(ValueError, match="VALIDATION_"):
        launcher.validate_config(raw, env)


@pytest.mark.parametrize("target", ["/var/run/docker.sock", "/source/postgres", "/source/answer_import"])
def test_extra_mount_rejected(config, target):
    raw, env = config
    raw["services"]["acceptance"]["volumes"].append(
        {"type": "bind", "source": "/var/run/docker.sock", "target": target})
    with pytest.raises(ValueError, match="VALIDATION_MOUNT"):
        launcher.validate_config(raw, env)


def test_writable_export_source_rejected(config):
    raw, env = config
    raw["services"]["export"]["volumes"][2]["read_only"] = False
    with pytest.raises(ValueError, match="VALIDATION_MOUNT"):
        launcher.validate_config(raw, env)


def test_project_and_output_overlap_rejected(config):
    raw, env = config
    changed = deepcopy(raw)
    changed["name"] = "llm-scoring"
    with pytest.raises(ValueError, match="VALIDATION_PROJECT"):
        launcher.validate_config(changed, env)
    env["VALIDATION_WORK_ROOT"] = env["VALIDATION_QUESTION_ROOT"]
    with pytest.raises(ValueError, match="VALIDATION_SOURCE_OUTPUT_OVERLAP"):
        launcher.validate_config(raw, env)


def test_image_context_allowlist_and_one_shot():
    ignores = (ROOT / "Dockerfile.validation.dockerignore").read_text().splitlines()
    assert ignores[0] == "**"
    assert "!config/**" not in ignores and "!.env" not in ignores
    dockerfile = (ROOT / "Dockerfile.validation").read_text()
    assert 'CMD ["help"]' in dockerfile
    assert "COPY . " not in dockerfile
    assert "cuda" not in dockerfile.lower()


def test_entrypoint_no_implicit_execution(monkeypatch, capsys):
    import sys
    entry_spec = importlib.util.spec_from_file_location(
        "validation_container", ROOT / "scripts/validation-container.py")
    entry = importlib.util.module_from_spec(entry_spec)
    entry_spec.loader.exec_module(entry)
    monkeypatch.setattr(sys, "argv", ["entrypoint", "help"])
    monkeypatch.setattr(entry, "export_validation_data", lambda *a, **k: pytest.fail("export"))
    monkeypatch.setattr(entry, "run_acceptance", lambda *a, **k: pytest.fail("acceptance"))
    entry.main()
    assert "--approved-export" in capsys.readouterr().out


def test_launcher_discards_production_environment(config, monkeypatch):
    import sys
    raw, env = config
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("LLM_GRADER_DATABASE_URL", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME",
                "GRADING_VALIDATION_READONLY_DATABASE_URL", "LLM_GRADER_RUNTIME_MANAGER_URL"):
        monkeypatch.setenv(key, "should-not-inherit")
    calls = []

    def invoke(command, **kwargs):
        calls.append((command, kwargs))
        assert not any(value == "should-not-inherit" for value in kwargs["env"].values())
        return type("Result", (), {"stdout": json.dumps(raw)})()

    monkeypatch.setattr(launcher.subprocess, "run", invoke)
    monkeypatch.setattr(sys, "argv", ["launcher", "config"])
    launcher.main()
    command = calls[0][0]
    assert command[command.index("--env-file") + 1] == "/dev/null"
    assert command[command.index("-f") + 1] == str(ROOT / "compose.validation.yaml")
    assert len(calls) == 1


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://readonly@postgres/db", "postgresql+psycopg://readonly@127.0.0.1/db",
    "postgresql+psycopg://readonly@/db?host=/other/socket",
    "postgresql+psycopg://readonly@/db?host=/source/postgres&service=production",
    "sqlite:////production/database.sqlite",
])
def test_export_network_or_foreign_driver_rejected(url):
    entry_spec = importlib.util.spec_from_file_location(
        "validation_container", ROOT / "scripts/validation-container.py")
    entry = importlib.util.module_from_spec(entry_spec)
    entry_spec.loader.exec_module(entry)
    with pytest.raises(ValueError, match="VALIDATION_UNIX_SOCKET_URL_REQUIRED"):
        entry.validate_socket_url(url)
    assert entry.validate_socket_url(
        "postgresql+psycopg://readonly@/db?host=/source/postgres")


def test_image_entrypoint_import_path():
    import os
    import subprocess
    import sys
    dockerfile = (ROOT / "Dockerfile.validation").read_text()
    assert "PYTHONPATH=/app" in dockerfile
    result = subprocess.run([sys.executable, str(ROOT / "scripts/validation-container.py"), "help"],
                            cwd="/tmp", env={**os.environ, "PYTHONPATH": str(ROOT)},
                            capture_output=True, text=True, check=True)
    assert "--approved-export" in result.stdout
