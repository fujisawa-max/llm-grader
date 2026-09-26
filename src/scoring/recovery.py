"""Read-only artifact backup manifests and integrity verification helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_artifact_manifest(root: str | Path) -> dict:
    """Return a deterministic manifest without modifying the artifact tree."""
    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError("ARTIFACT_ROOT_NOT_FOUND")
    files = []
    for path in sorted((value for value in base.rglob("*") if value.is_file()),
                       key=lambda value: value.relative_to(base).as_posix()):
        relative = path.relative_to(base).as_posix()
        files.append({"path": relative, "size": path.stat().st_size, "sha256": _sha256(path)})
    payload = {"schema_version": "i5-artifact-manifest.v1", "root": str(base), "files": files}
    payload["manifest_sha256"] = hashlib.sha256(
        json.dumps({k: v for k, v in payload.items() if k != "manifest_sha256"},
                   ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def verify_artifact_manifest(root: str | Path, manifest: dict) -> dict:
    """Verify all manifest entries and report extras without changing files."""
    base = Path(root).resolve()
    expected = {entry["path"]: entry for entry in manifest.get("files", [])}
    missing, mismatched = [], []
    for relative, entry in expected.items():
        path = (base / relative).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            missing.append(relative)
            continue
        if path.stat().st_size != entry.get("size") or _sha256(path) != entry.get("sha256"):
            mismatched.append(relative)
    actual = {value.relative_to(base).as_posix() for value in base.rglob("*") if value.is_file()}
    extras = sorted(actual - set(expected))
    unsigned = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    expected_manifest_sha = hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest_hash_valid = manifest.get("manifest_sha256") == expected_manifest_sha
    return {"valid": manifest_hash_valid and not missing and not mismatched,
            "manifest_hash_valid": manifest_hash_valid, "missing": missing,
            "mismatched": mismatched, "extra": extras}


def postgres_logical_backup_command(output: str = "backup.sql") -> list[str]:
    """Document the non-destructive logical backup command with placeholders."""
    return ["pg_dump", "--format=custom", "--file", output,
            "${DATABASE_URL:?set DATABASE_URL for the backup}"]
