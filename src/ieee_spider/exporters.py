from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

from ieee_spider.manifest import write_search_manifest
from ieee_spider.models import Work


CSV_FIELDS = [
    "title",
    "authors",
    "abstract",
    "doi",
    "year",
    "publication_date",
    "venue",
    "publisher",
    "publication_type",
    "landing_page_url",
    "pdf_url",
    "authorized_pdf_url",
    "oa_status",
    "cited_by_count",
    "openalex_id",
    "ieee_article_number",
    "source_providers",
    "matched_authors",
]


def export_all(works: list[Work], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "jsonl": output_dir / "articles.jsonl",
        "csv": output_dir / "articles.csv",
        "bib": output_dir / "articles.bib",
        "report": output_dir / "report.md",
    }
    write_jsonl(works, paths["jsonl"])
    write_csv(works, paths["csv"])
    write_bibtex(works, paths["bib"])
    write_markdown_report(works, paths["report"])
    paths.update(write_search_manifest(works, output_dir))
    return paths


def write_jsonl(works: list[Work], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for work in works:
            handle.write(
                json.dumps(work.to_dict(), ensure_ascii=False, sort_keys=True)
            )
            handle.write("\n")


def read_jsonl(path: Path) -> list[Work]:
    works: list[Work] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                works.append(Work(**json.loads(line)))
    return works


def write_csv(works: list[Work], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for work in works:
            row = work.to_dict()
            for field in (
                "authors",
                "source_providers",
                "matched_authors",
            ):
                row[field] = "; ".join(row[field])
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})


def write_bibtex(works: list[Work], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    used_keys: Counter[str] = Counter()
    entries: list[str] = []
    for work in works:
        base_key = _bib_key(work)
        used_keys[base_key] += 1
        key = (
            base_key
            if used_keys[base_key] == 1
            else f"{base_key}{used_keys[base_key]}"
        )
        entry_type = (
            "inproceedings"
            if "proceedings" in (work.publication_type or "").casefold()
            else "article"
        )
        fields = {
            "title": work.title,
            "author": " and ".join(work.authors),
            "year": str(work.year) if work.year else None,
            "journal": work.venue if entry_type == "article" else None,
            "booktitle": work.venue if entry_type == "inproceedings" else None,
            "doi": work.doi,
            "url": work.landing_page_url,
        }
        lines = [f"@{entry_type}{{{key},"]
        for name, value in fields.items():
            if value:
                lines.append(f"  {name} = {{{_bib_escape(value)}}},")
        lines.append("}")
        entries.append("\n".join(lines))
    path.write_text("\n\n".join(entries) + "\n", encoding="utf-8")


def write_markdown_report(works: list[Work], path: Path) -> None:
    by_author: Counter[str] = Counter()
    by_year: Counter[int] = Counter()
    venues: Counter[str] = Counter()
    oa_count = 0
    pdf_count = 0
    for work in works:
        by_author.update(work.matched_authors or ["Unassigned"])
        if work.year:
            by_year[work.year] += 1
        if work.venue:
            venues[work.venue] += 1
        if work.oa_status and work.oa_status.casefold() != "closed":
            oa_count += 1
        if work.pdf_url:
            pdf_count += 1

    lines = [
        "# IEEE author publication report",
        "",
        f"- Unique records: {len(works)}",
        f"- Records with an OA PDF link: {pdf_count}",
        f"- Open-access records: {oa_count}",
        "",
        "## Records by target author",
        "",
        "| Author | Count |",
        "|---|---:|",
    ]
    for author, count in by_author.most_common():
        lines.append(f"| {author} | {count} |")

    lines.extend(["", "## Records by year", "", "| Year | Count |", "|---|---:|"])
    for year, count in sorted(by_year.items(), reverse=True):
        lines.append(f"| {year} | {count} |")

    lines.extend(["", "## Top venues", "", "| Venue | Count |", "|---|---:|"])
    for venue, count in venues.most_common(20):
        lines.append(f"| {venue} | {count} |")

    lines.extend(
        [
            "",
            "## Latest records",
            "",
            "| Year | Target author | Title | Venue | DOI |",
            "|---:|---|---|---|---|",
        ]
    )
    for work in works[:50]:
        title = work.title.replace("|", "\\|")
        venue = (work.venue or "").replace("|", "\\|")
        doi = work.doi or ""
        author = ", ".join(work.matched_authors)
        lines.append(
            f"| {work.year or ''} | {author} | {title} | {venue} | {doi} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bib_key(work: Work) -> str:
    first_author = work.authors[0] if work.authors else "unknown"
    surname = first_author.split()[-1]
    title_word = next(
        (word for word in re.findall(r"[A-Za-z0-9]+", work.title) if len(word) > 2),
        "paper",
    )
    clean = re.sub(r"[^A-Za-z0-9]", "", f"{surname}{work.year or ''}{title_word}")
    return clean.casefold() or "ieee-paper"


def _bib_escape(value: str) -> str:
    return (
        value.replace("\\", "\\textbackslash{}")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("&", "\\&")
        .replace("%", "\\%")
    )
