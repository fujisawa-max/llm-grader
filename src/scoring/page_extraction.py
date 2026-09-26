"""Immutable page-level Ricoh extraction artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


EXTRACTION_VERSION = "ricoh-compact-v2"


def _sha(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


class PageExtractionArtifactStore:
    """Content-addressed, append-only store for one Ricoh result per page."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, submission_id: str, source_sha: str, version: str) -> Path:
        return self.root / "page-extraction" / submission_id / f"{source_sha}-{version}.json"

    def load(self, submission_id: str, source_sha: str, version: str = EXTRACTION_VERSION):
        path = self._path(submission_id, source_sha, version)
        if not path.is_file():
            return None
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if artifact.get("source_sha256") != source_sha or artifact.get("extraction_version") != version:
            raise ValueError("PAGE_EXTRACTION_ARTIFACT_IDENTITY_MISMATCH")
        return artifact

    def ownership_path(self, submission_id: str, source_sha: str, version: str = EXTRACTION_VERSION):
        return self._path(submission_id, source_sha, version).with_suffix(".ownership.json")

    def save_ownership(self, submission_id: str, source_sha: str, regions: list[dict],
                       *, version: str = EXTRACTION_VERSION):
        path = self.ownership_path(submission_id, source_sha, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        value = {"submission_id": submission_id, "source_sha256": source_sha,
                 "extraction_version": version, "regions": regions}
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return value

    def save(
        self,
        submission_id: str,
        source_sha: str,
        regions: list[dict],
        *,
        response_sha: str,
        model_version: str,
        prompt_version: str,
        version: str = EXTRACTION_VERSION,
        warnings: list[str] | None = None,
        review_required: bool = False,
    ) -> dict:
        path = self._path(submission_id, source_sha, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "artifact_id": _sha({"submission_id": submission_id, "source_sha256": source_sha,
                                  "extraction_version": version})[:32],
            "submission_id": submission_id,
            "source_sha256": source_sha,
            "extraction_version": version,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "regions": regions,
            "warnings": warnings or [],
            "review_required": review_required,
            "response_sha256": response_sha,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            if (current.get("submission_id"), current.get("source_sha256"),
                    current.get("extraction_version")) != (submission_id, source_sha, version):
                raise ValueError("PAGE_EXTRACTION_ARTIFACT_IMMUTABLE_CONFLICT")
            return current
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        tmp.replace(path)
        return artifact
