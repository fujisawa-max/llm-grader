import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scoring.runtime import (RuntimeManager, RuntimeManagerClient, RuntimeProfile,
                              profiles_from_runtime_config)


class FakeProcess:
    _next_pid = 4000

    def __init__(self, returncode=None):
        self.pid = FakeProcess._next_pid
        FakeProcess._next_pid += 1
        self.returncode = returncode
        self.killed = False
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FixedPorts:
    def __init__(self, port=19080):
        self.port = port
        self.released = []

    def acquire(self, requested=None, host="127.0.0.1"):
        return requested or self.port

    def release(self, port):
        self.released.append(port)


class RuntimeTests(unittest.TestCase):
    def profile(self, directory, **overrides):
        model = Path(directory) / "model.gguf"
        mmproj = Path(directory) / "mmproj.gguf"
        model.touch()
        mmproj.touch()
        values = dict(runtime_id="r1", model_id="alias", model_path=str(model),
                      mmproj_path=str(mmproj), expected_ftype="Q8_0", port=19080,
                      startup_timeout_seconds=0.15, log_path=str(Path(directory) / "r.log"))
        values.update(overrides)
        return RuntimeProfile(**values)

    @staticmethod
    def healthy_request(url):
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/models"):
            return {"data": [{"id": "alias"}]}
        return {"model_ftype": "Q8_0", "modalities": {"vision": True}}

    def test_managed_start_status_health_stop_and_command(self):
        with tempfile.TemporaryDirectory() as directory:
            processes = []
            manager = RuntimeManager({"r1": self.profile(directory)},
                                     port_allocator=FixedPorts(),
                                     launcher=lambda command, log: processes.append(
                                         (command, log)) or FakeProcess(),
                                     request=self.healthy_request)
            ready = manager.ensure_running("r1")
            self.assertEqual(ready["state"], "ready")
            self.assertEqual(manager.status("r1")["pid"], 4000)
            self.assertTrue(manager.health("r1")["ok"])
            command = processes[0][0]
            self.assertIn("--mmproj", command)
            self.assertIn("--port", command)
            stopped = manager.stop("r1")
            self.assertEqual(stopped["state"], "stopped")
            self.assertTrue(processes[0][1].closed)

    def test_start_timeout_kills_process(self):
        with tempfile.TemporaryDirectory() as directory:
            process = FakeProcess()
            manager = RuntimeManager({"r1": self.profile(directory, startup_timeout_seconds=0.06)},
                                     port_allocator=FixedPorts(), launcher=lambda *_: process,
                                     request=lambda _: (_ for _ in ()).throw(OSError("not ready")))
            with self.assertRaises(TimeoutError):
                manager.start("r1")
            self.assertTrue(process.killed)
            self.assertEqual(manager.status("r1")["state"], "unhealthy")

    def test_port_conflict_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory)
            class ConflictPorts:
                def acquire(self, requested=None, host="127.0.0.1"):
                    raise RuntimeError("port conflict")
                def release(self, port):
                    pass
            manager = RuntimeManager({"r1": profile}, port_allocator=ConflictPorts(),
                                     request=self.healthy_request)
            with self.assertRaisesRegex(RuntimeError, "port conflict"):
                manager.start("r1")

    def test_process_crash_and_health_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            crashed = FakeProcess(returncode=3)
            manager = RuntimeManager({"r1": self.profile(directory)}, launcher=lambda *_: crashed,
                                     port_allocator=FixedPorts(), request=self.healthy_request)
            with self.assertRaises(RuntimeError):
                manager.start("r1")
            self.assertEqual(manager.status("r1")["state"], "error")
            failed = RuntimeManager({"r1": self.profile(directory)}, request=lambda _: {
                "status": "failed"})
            self.assertFalse(failed.health("r1")["ok"])
            self.assertEqual(failed.status("r1")["state"], "stopped")

    def test_model_ftype_and_mmproj_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            mismatch_ftype = RuntimeManager({"r1": self.profile(directory, expected_ftype="Q4_K_M")},
                                            request=self.healthy_request)
            self.assertFalse(mismatch_ftype.health("r1")["ok"])
            missing = self.profile(directory, mmproj_path=None)
            manager = RuntimeManager({"r1": missing}, port_allocator=FixedPorts())
            with self.assertRaisesRegex(ValueError, "mmproj"):
                manager.start("r1")
            mismatch = RuntimeManager({"r1": self.profile(directory, model_id="wrong")},
                                      request=self.healthy_request)
            self.assertFalse(mismatch.health("r1")["ok"])

    def test_external_runtime_is_checked_but_never_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory, runtime_type="external",
                                    endpoint="http://127.0.0.1:19999/v1")
            manager = RuntimeManager({"r1": profile}, request=self.healthy_request)
            self.assertTrue(manager.ensure_running("r1")["ok"])
            result = manager.stop("r1")
            self.assertTrue(result["stop_ignored"])
            self.assertEqual(result["state"], "stopped")

    def test_logs_and_internal_http_client_match_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory, runtime_type="external")
            Path(profile.log_path).write_text("one\ntwo\n", encoding="utf-8")
            class Response:
                def __init__(self, value): self.value = value
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self): return json.dumps(self.value).encode()
                def __iter__(self): return iter(())
            def fake_urlopen(request, timeout=10):
                path = request.full_url.split("/internal", 1)[1].split("?", 1)[0]
                if path.endswith("/status"):
                    return Response({"state": "stopped"})
                if path.endswith("/health"):
                    return Response({"ok": True})
                if path.endswith("/logs"):
                    return Response({"lines": ["two"]})
                return Response({"stop_ignored": True})
            client = RuntimeManagerClient("http://runtime-manager/internal")
            with patch("scoring.runtime.client.urllib.request.urlopen", fake_urlopen):
                self.assertEqual(client.status("r1")["state"], "stopped")
                self.assertTrue(client.health("r1")["ok"])
                self.assertEqual(client.logs("r1", tail=1)["lines"], ["two"])
                self.assertTrue(client.stop("r1")["stop_ignored"])

    def test_hardware_probe_shape(self):
        from scoring.runtime.hardware import probe_hardware
        value = probe_hardware()
        self.assertIn("ram_bytes", value)
        self.assertIn("recommended_backends", value)

    def test_legacy_runtime_config_maps_to_external_profiles(self):
        profiles = profiles_from_runtime_config({"models": {
            "ocr": {"base_url": "http://127.0.0.1:8081/v1", "model_id": "ricoh"}}})
        self.assertEqual(profiles["ocr"].endpoint, "http://127.0.0.1:8081/v1")
        self.assertEqual(profiles["ocr"].runtime_type, "external")

    def test_runtime_snapshot_contains_reproducibility_metadata(self):
        profile = RuntimeProfile("r1", runtime_type="external", model_id="m")
        snapshot = RuntimeManager({"r1": profile}).status("r1")
        value = snapshot["profile"]
        self.assertEqual(value["generation"]["seed"], 42)
        self.assertIsNone(value["model_sha256"])
        self.assertIsNone(value["mmproj_sha256"])
        self.assertIsNone(value["llama_version"])


if __name__ == "__main__":
    unittest.main()
