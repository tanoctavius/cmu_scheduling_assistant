"""Load and validate sample/fixture course data into the core models.

Kept deliberately network-free: this reads a committed JSON file from disk and
validates it against :mod:`app.models`. Downstream code and tests use this so
they never depend on a live scrape.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from app.models import Course

# Repo root is three levels up from this file: app/ -> backend/ -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COURSES_PATH = _REPO_ROOT / "data" / "samples" / "courses.json"

_COURSE_LIST = TypeAdapter(list[Course])


def load_courses(path: Path | str | None = None) -> list[Course]:
    """Load courses from a JSON file and validate them against the models.

    Args:
        path: JSON file to load. Defaults to the committed sample fixture at
            ``data/samples/courses.json``.

    Returns:
        The validated list of :class:`~app.models.Course`.

    Raises:
        FileNotFoundError: if the file does not exist.
        pydantic.ValidationError: if the data does not conform to the models.
    """
    resolved = Path(path) if path is not None else DEFAULT_COURSES_PATH
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    return _COURSE_LIST.validate_python(raw)
