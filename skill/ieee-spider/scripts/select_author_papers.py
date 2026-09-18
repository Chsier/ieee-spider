from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ieee_spider.manifest import (
    read_search_manifest,
    write_manifest_csv,
    write_manifest_jsonl,
    write_manifest_markdown,
)
from ieee_spider.xplore import author_matches


VENUE_TIERS = {
    "IEEE Journal on Selected Areas in Communications": 100,
    "IEEE Communications Surveys & Tutorials": 98,
    "IEEE Transactions on Mobile Computing": 97,
    "IEEE Transactions on Wireless Communications": 96,
    "IEEE Transactions on Information Forensics and Security": 95,
    "IEEE Transactions on Networking": 94,
    "IEEE Transactions on Dependable and Secure Computing": 93,
    "IEEE Transactions on Communications": 92,
    "IEEE Transactions on Intelligent Transportation Systems": 91,
    "IEEE Internet of Things Journal": 90,
    "IEEE Transactions on Vehicular Technology": 89,
    "IEEE Transactions on Cognitive Communications and Networking": 88,
    "IEEE Transactions on Services Computing": 87,
    "IEEE Transactions on Computers": 86,
    "IEEE Transactions on Network and Service Management": 85,
    "IEEE Network": 84,
    "IEEE Wireless Communications": 83,
    "IEEE Wireless Communications Letters": 82,
    "IEEE Communications Letters": 81,
    "IEEE Communications Magazine": 80,
    "IEEE Transactions on Consumer Electronics": 79,
    "IEEE Transactions on Aerospace and Electronic Systems": 78,
}

EXCLUDED_TITLE_MARKERS = (
    "editorial",
    "correction",
    "erratum",
    "retraction",
    "call for papers",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Select top-ranked IEEE papers per exact author from a search "
            "manifest and write fixed per-author outputs."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--author", action="append", required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--collection-name")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")

    input_path = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    records = read_search_manifest(input_path)
    collection_name = args.collection_name or output_dir.name
    authors = _unique(args.author)
    if not authors:
        raise SystemExit("At least one --author is required")

    selected_by_author: dict[str, list[dict[str, Any]]] = {}
    union: dict[str, dict[str, Any]] = {}
    for author in authors:
        candidates = _candidates_for_author(records, author)
        selected = candidates[: args.limit]
        if len(selected) < args.limit:
            raise SystemExit(
                f"{author}: only {len(selected)} eligible records available; "
                "extend the year range and rerun the search"
            )
        selected_by_author[author] = selected
        for record in selected:
            union.setdefault(record["record_id"], record)

    for author in authors:
        selected = selected_by_author[author]
        slug = slugify(author)
        author_dir = output_dir / slug
        _write_selection(author_dir, selected, limit=args.limit)
        (author_dir / "statistics.json").write_text(
            json.dumps(
                _statistics(author, selected, input_path),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    shared_dir = output_dir / "_shared"
    union_records = list(union.values())
    write_manifest_jsonl(union_records, shared_dir / "manifest-union.jsonl")
    write_manifest_csv(union_records, shared_dir / "manifest-union.csv")
    write_manifest_markdown(union_records, shared_dir / "manifest-union.md")

    collection = {
        "collection_name": collection_name,
        "generated_at": datetime.now(UTC).isoformat(),
        "requested_per_author": args.limit,
        "authors": authors,
        "unique_selected_records": len(union_records),
        "abstract_file_pattern": f"abstracts-{args.limit}.jsonl",
        "statistics_file": "statistics.json",
        "summary_file_pattern": f"summaries-{args.limit}.docx",
        "summary_format": "docx",
        "authoritative_manifest_pattern": (
            f"<author-slug>/manifest-{args.limit}.jsonl"
        ),
    }
    (output_dir / "collection.json").write_text(
        json.dumps(collection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_readme(output_dir, authors, selected_by_author, limit=args.limit)

    print(
        f"authors={len(authors)} per_author={args.limit} "
        f"unique_records={len(union_records)} output={output_dir}"
    )
    for author in authors:
        print(f"- {author}: {len(selected_by_author[author])}")


def _candidates_for_author(
    records: list[dict[str, Any]],
    author: str,
) -> list[dict[str, Any]]:
    candidates = []
    for record in records:
        if not author_matches(author, list(record.get("authors") or [])):
            continue
        if record.get("publication_type") == "Conference Paper":
            continue
        title = str(record.get("title") or "")
        if any(marker in title.casefold() for marker in EXCLUDED_TITLE_MARKERS):
            continue
        candidates.append(record)
    candidates.sort(
        key=lambda record: (
            -VENUE_TIERS.get(record.get("venue"), 60),
            -(record.get("year") or 0),
            str(record.get("title") or "").casefold(),
        )
    )
    return candidates


def _write_selection(
    output_dir: Path,
    records: list[dict[str, Any]],
    *,
    limit: int,
) -> None:
    write_manifest_jsonl(records, output_dir / f"manifest-{limit}.jsonl")
    write_manifest_csv(records, output_dir / f"manifest-{limit}.csv")
    write_manifest_markdown(records, output_dir / f"manifest-{limit}.md")


def _statistics(
    author: str,
    records: list[dict[str, Any]],
    source: Path,
) -> dict[str, Any]:
    years = Counter(
        record.get("year")
        for record in records
        if record.get("year") is not None
    )
    venues = Counter(
        record.get("venue")
        for record in records
        if record.get("venue")
    )
    return {
        "statistics_version": 1,
        "author": author,
        "slug": slugify(author),
        "paper_count": len(records),
        "unique_record_ids": len(
            {record["record_id"] for record in records}
        ),
        "year_range": [
            min(years) if years else None,
            max(years) if years else None,
        ],
        "years": {
            str(year): count
            for year, count in sorted(years.items(), reverse=True)
        },
        "venues": dict(venues.most_common()),
        "venue_metrics": [
            {
                "venue": venue,
                "paper_count": count,
                "citation_total": None,
                "citation_mean": None,
                "citation_median": None,
                "citation_max": None,
                "full_text_views_total": None,
            }
            for venue, count in venues.most_common()
        ],
        "citation_summary": {
            "status": "pending_enrichment",
            "available_count": 0,
            "unavailable_count": 0,
            "not_reported_count": len(records),
            "reported_count": 0,
            "coverage_ratio": 0.0,
            "total": None,
            "mean": None,
            "median": None,
            "maximum": None,
        },
        "selection_method": (
            "Exact author match; journal/early-access only; IEEE venue tier "
            "first, publication year second"
        ),
        "source_manifest": str(source),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _write_readme(
    output_dir: Path,
    authors: list[str],
    selected: dict[str, list[dict[str, Any]]],
    *,
    limit: int,
) -> None:
    lines = [
        f"# {output_dir.name}",
        "",
        f"Each author has a fixed top-{limit} paper manifest and statistics.",
        "",
        "| Author | Papers | Manifest | Abstracts | Statistics | DOCX Summary |",
        "|---|---:|---|---|---|---|",
    ]
    for author in authors:
        slug = slugify(author)
        lines.append(
            f"| {author} | {len(selected[author])} | "
            f"[manifest-{limit}.csv]({slug}/manifest-{limit}.csv) | "
            f"[abstracts-{limit}.jsonl]({slug}/abstracts-{limit}.jsonl) | "
            f"[statistics.json]({slug}/statistics.json) | "
            f"[summaries-{limit}.docx]({slug}/summaries-{limit}.docx) |"
        )
    lines.append("")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.decode("ascii").casefold())
    return slug.strip("-") or "author"


def _unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


if __name__ == "__main__":
    main()
