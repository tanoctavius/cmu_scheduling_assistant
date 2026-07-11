"""Load and validate a curated degree-requirements file into typed models.

Mirrors :mod:`app.data_loader`: reads a committed JSON file from ``data/samples/``
and validates it against :mod:`app.requirements`. Network-free.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.requirements import Requirements

# Repo root is three levels up: app/ -> backend/ -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REQUIREMENTS_PATH = _REPO_ROOT / "data" / "samples" / "computer-science.json"


def load_requirements(path: Path | str | None = None) -> Requirements:
    """Load a requirements JSON file and validate it against the models.

    Args:
        path: JSON file to load. Defaults to the committed CS requirements at
            ``data/samples/computer-science.json``.

    Returns:
        The validated :class:`~app.requirements.Requirements`.

    Raises:
        FileNotFoundError: if the file does not exist.
        pydantic.ValidationError: if the data does not conform to the models
            (e.g. a rule is missing its required field).
    """
    resolved = Path(path) if path is not None else DEFAULT_REQUIREMENTS_PATH
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    return Requirements.model_validate(raw)
