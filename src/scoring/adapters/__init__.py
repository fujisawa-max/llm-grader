"""Adapters that expose the legacy scoring engine to other orchestrators."""

from .scoring_adapter import LegacyCliAdapter, Stage, StageRequest
from .artifacts import RunArtifactAdapter

__all__ = ["LegacyCliAdapter", "RunArtifactAdapter", "Stage", "StageRequest"]
