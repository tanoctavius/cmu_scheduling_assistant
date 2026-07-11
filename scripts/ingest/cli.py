"""Command-line entry point for ingestion.

Examples:
    # Parse the committed fixtures (no network) and write normalized JSON:
    uv run --project backend python scripts/ingest/cli.py --dry-run \\
        --out data/samples/courses.generated.json

    # Live ingest from the official CMU sources (FCE still from a manual CSV):
    uv run --project backend python scripts/ingest/cli.py \\
        --fce data/fixtures/fce_sample.csv --out out.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this file directly (python scripts/ingest/cli.py): put the
# `scripts/` dir on the path so `import ingest.*` resolves. `app.*` comes from the
# backend virtualenv.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.ingest import run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest CMU course data into normalized models.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse committed fixtures instead of hitting the network.",
    )
    parser.add_argument("--soc", type=Path, help="SOC HTML fixture (dry-run override).")
    parser.add_argument("--catalog", type=Path, help="Catalog HTML fixture (dry-run override).")
    parser.add_argument("--fce", type=Path, help="Manual FCE CSV export.")
    parser.add_argument("--out", type=Path, help="Write normalized JSON here.")
    args = parser.parse_args(argv)

    courses = run(
        dry_run=args.dry_run,
        soc_path=args.soc,
        catalog_path=args.catalog,
        fce_path=args.fce,
        out_path=args.out,
    )

    source = "fixtures" if args.dry_run else "live CMU sources"
    print(f"Ingested {len(courses)} courses from {source}.")
    if args.out:
        print(f"Wrote normalized JSON to {args.out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
