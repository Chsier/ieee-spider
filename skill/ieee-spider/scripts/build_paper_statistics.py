from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STATISTICS_VERSION = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Merge a fixed IEEE search manifest with serial enrichment output "
            "and write a reusable citation and venue statistics report."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--abstracts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--top", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.top < 1:
        raise SystemExit("--top must be at least 1")

    manifest_path = args.manifest.expanduser().resolve()
    abstracts_path = args.abstracts.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    manifest = _load_jsonl(manifest_path)
    abstracts = _load_jsonl(abstracts_path)
    statistics = build_statistics(
        author=args.author,
        manifest=manifest,
        abstracts=abstracts,
        source_manifest=manifest_path,
        source_abstracts=abstracts_path,
        top_n=args.top,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(statistics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    citation_total = statistics["citation_summary"]["total"]
    venue_count = len(statistics["venue_metrics"])
    print(
        f"author={args.author} papers={statistics['paper_count']} "
        f"venues={venue_count} citations={citation_total} output={output_path}"
    )


def build_statistics(
    *,
    author: str,
    manifest: list[dict[str, Any]],
    abstracts: list[dict[str, Any]],
    source_manifest: Path,
    source_abstracts: Path,
    top_n: int = 20,
) -> dict[str, Any]:
    manifest_by_id = _index_unique(manifest, "manifest")
    abstract_by_id = _index_unique(abstracts, "abstracts")
    missing = sorted(set(manifest_by_id) - set(abstract_by_id))
    unexpected = sorted(set(abstract_by_id) - set(manifest_by_id))
    if missing:
        raise ValueError(
            "Enrichment output is missing manifest records: "
            + ", ".join(missing)
        )
    if unexpected:
        raise ValueError(
            "Enrichment output contains records not in the manifest: "
            + ", ".join(unexpected)
        )

    papers = [
        _merge_paper(manifest_by_id[record_id], abstract_by_id[record_id])
        for record_id in manifest_by_id
    ]
    papers.sort(
        key=lambda item: (
            -(item["citation_count"] if item["citation_count"] is not None else -1),
            -(item["full_text_views"] if item["full_text_views"] is not None else -1),
            -(item["year"] or 0),
            str(item["title"] or "").casefold(),
        )
    )

    years = Counter(
        paper["year"] for paper in papers if paper["year"] is not None
    )
    venues = Counter(
        str(paper["venue"]) for paper in papers if paper["venue"]
    )
    known_citations = [
        paper["citation_count"]
        for paper in papers
        if paper["citation_count"] is not None
    ]
    known_patent_citations = [
        paper["patent_citation_count"]
        for paper in papers
        if paper["patent_citation_count"] is not None
    ]
    known_views = [
        paper["full_text_views"]
        for paper in papers
        if paper["full_text_views"] is not None
    ]
    available = len(known_citations)
    unavailable = sum(
        paper["citation_status"] == "unavailable" for paper in papers
    )
    not_reported = len(papers) - available - unavailable
    abstract_ok = sum(paper["abstract_status"] == "ok" for paper in papers)

    return {
        "statistics_version": STATISTICS_VERSION,
        "author": author,
        "paper_count": len(papers),
        "unique_record_ids": len(manifest_by_id),
        "abstract_ok_count": abstract_ok,
        "abstract_failed_count": len(papers) - abstract_ok,
        "year_range": [
            min(years) if years else None,
            max(years) if years else None,
        ],
        "years": {
            str(year): count
            for year, count in sorted(years.items(), reverse=True)
        },
        "venues": dict(venues.most_common()),
        "citation_summary": {
            "available_count": available,
            "unavailable_count": unavailable,
            "not_reported_count": not_reported,
            "reported_count": len(known_citations),
            "coverage_ratio": (
                round(len(known_citations) / len(papers), 4)
                if papers
                else 0.0
            ),
            "total": sum(known_citations),
            "mean": _mean(known_citations),
            "median": _median(known_citations),
            "maximum": max(known_citations, default=0),
        },
        "patent_citation_summary": {
            "reported_count": len(known_patent_citations),
            "total": sum(known_patent_citations),
            "maximum": max(known_patent_citations, default=0),
        },
        "full_text_views_summary": {
            "reported_count": len(known_views),
            "total": sum(known_views),
            "mean": _mean(known_views),
            "median": _median(known_views),
            "maximum": max(known_views, default=0),
        },
        "venue_metrics": _venue_metrics(papers),
        "top_cited_papers": _top_cited_papers(papers, top_n),
        "papers": papers,
        "selection_method": (
            "Exact author match; journal/early-access only; IEEE venue tier "
            "first, publication year second; citation metrics read from IEEE "
            "document detail pages"
        ),
        "source_manifest": str(source_manifest),
        "source_abstracts": str(source_abstracts),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"JSONL file does not exist: {path}")
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            records.append(value)
    return records


def _index_unique(
    records: list[dict[str, Any]],
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = str(record.get("record_id") or "")
        if not record_id:
            raise ValueError(f"{label} record is missing record_id")
        if record_id in result:
            raise ValueError(f"Duplicate {label} record_id: {record_id}")
        result[record_id] = record
    return result


def _merge_paper(
    manifest: dict[str, Any],
    enriched: dict[str, Any],
) -> dict[str, Any]:
    citation_count = _as_int(enriched.get("citation_count"))
    full_text_views = _as_int(enriched.get("full_text_views"))
    patent_citation_count = _as_int(enriched.get("patent_citation_count"))
    citation_status = str(
        enriched.get("citation_status")
        or ("available" if citation_count is not None else "not_reported")
    )
    return {
        "record_id": manifest["record_id"],
        "title": manifest.get("title") or enriched.get("title"),
        "authors": list(manifest.get("authors") or []),
        "year": manifest.get("year") or enriched.get("year"),
        "venue": manifest.get("venue") or enriched.get("venue"),
        "doi": manifest.get("doi"),
        "publication_type": manifest.get("publication_type"),
        "citation_count": citation_count,
        "patent_citation_count": patent_citation_count,
        "full_text_views": full_text_views,
        "citation_status": citation_status,
        "abstract_status": enriched.get("status"),
        "landing_page_url": manifest.get("landing_page_url"),
    }


def _venue_metrics(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for paper in papers:
        venue = str(paper.get("venue") or "Unknown venue")
        grouped.setdefault(venue, []).append(paper)

    metrics = []
    for venue, items in grouped.items():
        citations = [
            item["citation_count"]
            for item in items
            if item["citation_count"] is not None
        ]
        views = [
            item["full_text_views"]
            for item in items
            if item["full_text_views"] is not None
        ]
        metrics.append(
            {
                "venue": venue,
                "paper_count": len(items),
                "cited_paper_count": sum(
                    value > 0 for value in citations
                ),
                "citation_total": sum(citations),
                "citation_mean": _mean(citations),
                "citation_median": _median(citations),
                "citation_max": max(citations, default=0),
                "full_text_views_total": sum(views),
            }
        )
    return sorted(
        metrics,
        key=lambda item: (
            -item["paper_count"],
            -item["citation_total"],
            item["venue"].casefold(),
        ),
    )


def _top_cited_papers(
    papers: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    result = []
    for rank, paper in enumerate(papers[:limit], 1):
        result.append(
            {
                "rank": rank,
                "record_id": paper["record_id"],
                "title": paper["title"],
                "year": paper["year"],
                "venue": paper["venue"],
                "citation_count": paper["citation_count"],
                "patent_citation_count": paper["patent_citation_count"],
                "full_text_views": paper["full_text_views"],
                "landing_page_url": paper["landing_page_url"],
            }
        )
    return result


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _mean(values: list[int]) -> float | None:
    if not values:
        return None
    return round(statistics.mean(values), 2)


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    return round(float(statistics.median(values)), 2)


if __name__ == "__main__":
    main()
