"""Stage-barrier orchestration with RuntimeManagerClient lifecycle control."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..adapters import LegacyCliAdapter, StageRequest
from ..core import load_assignment, read_json


class ItemPhaseError(Exception):
    """An answer/crop failure that may be recorded while other items continue."""


class RuntimePhaseError(Exception):
    """A runtime failure that must stop the current phase."""


@dataclass
class PhaseExecutionResult:
    state: str = "preparing"
    states: list[str] = field(default_factory=lambda: ["preparing"])
    item_errors: list[dict] = field(default_factory=list)
    runtime_error: str | None = None
    stage_results: dict[str, list[dict]] = field(default_factory=dict)

    def transition(self, state):
        self.state = state
        self.states.append(state)

    def as_dict(self):
        return {
            "state": self.state,
            "states": self.states,
            "item_errors": self.item_errors,
            "runtime_error": self.runtime_error,
            "stage_results": self.stage_results,
        }


class PhasedAutoOrchestrator:
    """Run all answers through each model before switching runtimes."""

    def __init__(
        self,
        runtime_client,
        adapter=None,
        *,
        runtime_ids=None,
        keep_final_runtime_running=False,
        pause_check=None,
    ):
        self.runtime_client = runtime_client
        self.adapter = adapter or LegacyCliAdapter()
        self.runtime_ids = {"ricoh": "ocr", "unimumer": "math_ocr", "ornith": "grader"}
        self.runtime_ids.update(runtime_ids or {})
        self.keep_final_runtime_running = keep_final_runtime_running
        self.runtime_snapshots = {}
        self.pause_check = pause_check

    def run(self, request: StageRequest):
        result = PhaseExecutionResult()
        items = self._items(request)
        try:
            if self._phase(
                result,
                "ricoh",
                items,
                request,
                self.adapter.run_ricoh_phase,
                "starting_ricoh",
                "ricoh_running",
                "checkpointing_ricoh",
                "stopping_ricoh",
                stop=True,
            ):
                result.transition("paused")
                return result
            if self._phase(
                result,
                "unimumer",
                items,
                request,
                self.adapter.run_math_ocr_phase,
                "starting_unimumer",
                "unimumer_running",
                "checkpointing_unimumer",
                "stopping_unimumer",
                stop=True,
                skip_if_no_math=True,
            ):
                result.transition("paused")
                return result
            if self._phase(
                result,
                "ornith",
                items,
                request,
                self.adapter.run_ornith_phase,
                "starting_ornith",
                "reconstruction_running",
                "review_classification",
                None,
                stop=not self.keep_final_runtime_running,
            ):
                result.transition("paused")
                return result
        except RuntimePhaseError as exc:
            result.runtime_error = str(exc)
            result.transition("runtime_failed")
            return result
        result.transition("completed" if not result.item_errors else "item_errors")
        return result

    def _phase(
        self,
        result,
        name,
        items,
        request,
        runner,
        starting,
        running,
        checkpointing,
        stopping,
        *,
        stop,
        skip_if_no_math=False,
    ):
        runtime_id = self.runtime_ids[name]
        if self._phase_complete(name, request, items):
            result.stage_results[name] = [
                {"submission": item["id"], "state": "resumed"} for item in items
            ]
            result.transition(checkpointing)
            return bool(self.pause_check and self.pause_check())
        result.transition(starting)
        response = self._runtime_call("ensure_running", runtime_id)
        self.runtime_snapshots[name] = dict(response)
        endpoint = self._endpoint(response)
        result.transition(running)
        if name == "ornith":
            result.transition("grading_running")
        stage = []
        for item in items:
            if skip_if_no_math and item.get("has_math") is False:
                stage.append({"submission": item["id"], "state": "skipped"})
                continue
            item_request = StageRequest(
                request.assignment,
                request.run,
                request.config,
                item["id"],
                {**(request.runtime_endpoints or {}), self._role(name): endpoint},
                request.domain_inputs,
            )
            try:
                value = runner(item_request)
                stage.append({"submission": item["id"], "state": "success", "result": value})
            except Exception as exc:
                if not self._runtime_ok(runtime_id):
                    raise RuntimePhaseError(f"{name} runtime failure: {exc}") from exc
                error = {
                    "stage": name,
                    "submission": item["id"],
                    "classification": "item_error",
                    "error": str(exc),
                }
                result.item_errors.append(error)
                stage.append({**error, "state": "error"})
        result.stage_results[name] = stage
        result.transition(checkpointing)
        self._barrier(result, name, items, stage)
        if stop:
            if stopping:
                result.transition(stopping)
            try:
                stopped = self.runtime_client.stop(runtime_id)
                self.runtime_snapshots[name] = {**self.runtime_snapshots.get(name, {}), **stopped}
            except Exception as exc:
                raise RuntimePhaseError(f"{name} runtime stop failure: {exc}") from exc
        return bool(self.pause_check and self.pause_check())

    def _barrier(self, result, name, items, stage):
        expected = {
            item["id"]
            for item in items
            if not (name == "unimumer" and item.get("has_math") is False)
        }
        completed = {entry["submission"] for entry in stage}
        if expected != completed:
            raise RuntimePhaseError(f"{name} barrier未成立")

    def _runtime_call(self, method, runtime_id):
        try:
            response = getattr(self.runtime_client, method)(runtime_id)
            if hasattr(self.runtime_client, "status"):
                self.runtime_client.status(runtime_id)
            self._runtime_health(runtime_id)
            return response
        except Exception as exc:
            details = ""
            if hasattr(self.runtime_client, "logs"):
                try:
                    details = f" logs={self.runtime_client.logs(runtime_id, tail=20)}"
                except Exception:
                    details = ""
            raise RuntimePhaseError(f"{runtime_id} runtime failure: {exc}{details}") from exc

    def _runtime_health(self, runtime_id):
        value = self.runtime_client.health(runtime_id)
        if isinstance(value, dict) and value.get("ok") is False:
            raise RuntimePhaseError(value.get("error", "health check failed"))
        return value

    def _runtime_ok(self, runtime_id):
        try:
            value = self.runtime_client.health(runtime_id)
            return not (isinstance(value, dict) and value.get("ok") is False)
        except Exception:
            return False

    @staticmethod
    def _endpoint(response):
        endpoint = response.get("endpoint") or response.get("base_url")
        if not endpoint and isinstance(response.get("profile"), dict):
            endpoint = response["profile"].get("endpoint")
        if not endpoint:
            raise RuntimePhaseError("runtime managerがendpointを返しませんでした")
        return endpoint

    @staticmethod
    def _role(name):
        return {"ricoh": "ocr", "unimumer": "math_ocr", "ornith": "grader"}[name]

    @staticmethod
    def _items(request):
        try:
            _, _, submissions = load_assignment(request.assignment)
            if request.submission:
                submissions = [s for s in submissions if s["submission_id"] == request.submission]
            items = []
            for sub in submissions:
                layout_files = list(
                    (Path(request.run) / "submissions" / sub["submission_id"] / "ocr/ricoh").glob(
                        "*.layout.json"
                    )
                )
                has_math = True
                if layout_files:
                    has_math = any(
                        any(r.get("kind") == "math" for r in read_json(path).get("regions", []))
                        for path in layout_files
                    )
                items.append({"id": sub["submission_id"], "has_math": has_math})
            return items
        except (OSError, ValueError, KeyError):
            return [{"id": request.submission or "all", "has_math": True}]

    @staticmethod
    def _phase_complete(name, request, items):
        """Return true only when every required legacy checkpoint is successful."""
        root = Path(request.run) / "submissions"
        for item in items:
            folder = root / item["id"]
            if name == "ricoh":
                statuses = list((folder / "ocr/ricoh").glob("*.status.json"))
                if not statuses or any(read_json(p).get("state") != "success" for p in statuses):
                    return False
            elif name == "unimumer":
                if not item.get("has_math"):
                    continue
                statuses = list(
                    (folder / "ocr/unimumer/regions").glob("**/transcription.status.json")
                )
                if not statuses or any(read_json(p).get("state") != "success" for p in statuses):
                    return False
            else:
                statuses = list((folder / "questions").glob("*/reconstruction.status.json"))
                grades = list((folder / "questions").glob("*/grading.status.json"))
                if not statuses or len(statuses) != len(grades):
                    return False
                if any(read_json(p).get("state") != "success" for p in statuses + grades):
                    return False
        return True
