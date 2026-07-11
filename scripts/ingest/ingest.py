"""Assemble the parsed sources into normalized Course models and write JSON.

Runs **off the request path** — this is scheduled batch work (project context §4),
not something the API calls per request. The output conforms to the Stage 1
models and serializes to the same JSON shape as ``data/samples/courses.json``, so
nothing downstream can tell whether a course came from a sample or a live scrape.

``--dry-run`` sources the SOC and Catalog from committed fixtures instead of the
network, so tests and CI never depend on CMU's site being up. FCE is *always* a
local manual CSV export (the FCE portal is auth-gated), dry-run or not.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.models import Course, Section

from ingest.parsers import (
    parse_course_catalog,
    parse_fce_csv,
    parse_schedule_of_classes,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]  # scripts/ingest/ingest.py -> repo
_FIXTURES = _REPO_ROOT / "data" / "fixtures"

DEFAULT_SOC_FIXTURE = _FIXTURES / "soc_sample.html"
DEFAULT_CATALOG_FIXTURE = _FIXTURES / "catalog_sample.html"
DEFAULT_FCE_CSV = _FIXTURES / "fce_sample.csv"

# Official CMU sources (used only when NOT in dry-run). Selectors are ours; these
# are where the data lives, not a hosted API we depend on.
SOC_URL = "https://enr-apps.as.cmu.edu/open/SOC/SOCServlet"
CATALOG_URL = "https://coursecatalog.web.cmu.edu/"


def _fetch(url: str) -> str:
    """Fetch a page for live ingestion. Imported lazily so dry-run needs no network stack."""
    import httpx

    response = httpx.get(url, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    return response.text


def build_courses(
    soc_html: str,
    catalog_html: str,
    fce_csv: str,
) -> list[Course]:
    """Merge parsed SOC + Catalog + FCE into validated Course models."""
    soc = parse_schedule_of_classes(soc_html)
    catalog = parse_course_catalog(catalog_html)
    fce = parse_fce_csv(fce_csv)

    courses: list[Course] = []
    for course_num, info in soc.items():
        meta = catalog.get(course_num, {})
        stats = fce.get(course_num, {})
        sections = [
            Section(
                course_num=course_num,
                title=info["title"],
                units=info["units"],
                section_id=s["section_id"],
                days=s["days"],
                begin=s["begin"],
                end=s["end"],
                location=s["location"],
            )
            for s in info["sections"]
        ]
        courses.append(
            Course(
                course_num=course_num,
                title=info["title"],
                units=info["units"],
                prereqs=meta.get("prereqs"),
                description=meta.get("description", ""),
                # FCE may be absent (e.g. not in the manual export): default to 0.0.
                fce_workload_hours=stats.get("workload", 0.0),
                fce_rating=stats.get("rating", 0.0),
                sections=sections,
            )
        )
    return courses


def write_courses(courses: list[Course], out_path: Path) -> None:
    """Serialize courses to JSON matching the ``data/samples/courses.json`` shape."""
    data = [c.model_dump(mode="json") for c in courses]
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run(
    *,
    dry_run: bool,
    soc_path: Optional[Path] = None,
    catalog_path: Optional[Path] = None,
    fce_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
) -> list[Course]:
    """Ingest from fixtures (dry-run) or the live sources, return Course models.

    Args:
        dry_run: If True, read the SOC and Catalog from local fixtures instead of
            the network. FCE is always read from a local CSV either way.
        soc_path, catalog_path: Fixture overrides (dry-run only).
        fce_path: Manual FCE CSV export. Defaults to the committed sample.
        out_path: If given, also write the normalized JSON there.

    Returns:
        The validated list of Course models.
    """
    fce_csv = (fce_path or DEFAULT_FCE_CSV).read_text(encoding="utf-8")

    if dry_run:
        soc_html = (soc_path or DEFAULT_SOC_FIXTURE).read_text(encoding="utf-8")
        catalog_html = (catalog_path or DEFAULT_CATALOG_FIXTURE).read_text(encoding="utf-8")
    else:
        soc_html = _fetch(SOC_URL)
        catalog_html = _fetch(CATALOG_URL)

    courses = build_courses(soc_html, catalog_html, fce_csv)
    if out_path is not None:
        write_courses(courses, Path(out_path))
    return courses
