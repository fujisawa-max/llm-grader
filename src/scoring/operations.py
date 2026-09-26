"""Small, side-effect-free operational configuration helpers.

The application intentionally keeps deployment configuration in environment
variables.  This module centralises boolean parsing so the API, scripts, and
health reporting agree on the same feature-flag semantics.
"""

from __future__ import annotations

import os


def env_bool(name: str, default: bool = False, *, environ: dict[str, str] | None = None) -> bool:
    """Return a predictable boolean for an environment variable.

    Empty and unknown values use ``default`` rather than silently enabling a
    feature.  Accepted true values are ``1``, ``true``, ``yes``, and ``on``;
    accepted false values are ``0``, ``false``, ``no``, and ``off``.
    """

    values = os.environ if environ is None else environ
    raw = values.get(name)
    if raw is None or not str(raw).strip():
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def student_portal_enabled(value: bool | None = None) -> bool:
    """Resolve the student portal flag.

    ``create_app`` keeps the historical in-process test default enabled when
    no deployment environment is supplied.  The production server passes its
    explicit default of ``False`` so student web access is opt-in in deployed
    environments.
    """

    return env_bool("STUDENT_PORTAL_ENABLED", True) if value is None else bool(value)
