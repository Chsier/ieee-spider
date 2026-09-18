from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ieee_spider.models import Work


MANIFEST_VERSION = 1

SEARCH_MANIFEST_FIELDS = (
    "manifest_version",
    "record_id",
    "status",
    "title",
    "authors",
    "year",
    "doi",
    "venue",
    "publisher",
    "publication_type",
    "abstract",
    "landing_page_url",
    "oa_pdf_url",
    "authorized_pdf_url",
    "open_access_status",
    "source_providers",
    "matched_authors",
    "matched_queries",
    "retrieved_at",
    "requires_authentication",
    "download_mode",
    "local_path",
    "error",
)

DOWNLOAD_MANIFEST_FIELDS = (
    "manifest_version",
    "record_id",
    "title",
    "doi",
    "mode",
    "status",
    "local_path",
    "message",
    "attempted_at",
)


def build_manifest_record(
    work: Work,
    *,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    timestamp = retrieved_at or _utc_now()
    return {
        "manifest_version": MANIFEST_VERSION,
        "record_id": _record_id(work),
        "status": "discovered",
        "title": work.title,
        "authors": work.authors,
        "year": work.year,
        "doi": work.doi,
        "venue": work.venue,
        "publisher": work.publisher,
        "publication_type": work.publication_type,
        "abstract": work.abstract,
        "landing_page_url": work.landing_page_url,
        "oa_pdf_url": work.pdf_url,
        "authorized_pdf_url": work.authorized_pdf_url,
        "open_access_status": work.oa_status,
        "source_providers": work.source_providers,
        "matched_authors": work.matched_authors,
        "matched_queries": work.matched_queries,
        "retrieved_at": timestamp,
        "requires_authentication": not bool(work.pdf_url),
        "download_mode": (
            "oa" if work.pdf_url else "authorized" if work.landing_page_url else "metadata"
        ),
        "local_path": None,
        "error": None,
    }


def write_search_manifest(
    works: list[Work],
    output_dir: Path,
    *,
    retrieved_at: str | None = None,
) -> dict[str, Path]:
    timestamp = retrieved_at or _utc_now()
    records = [
        build_manifest_record(work, retrieved_at=timestamp) for work in works
    ]
    paths = {
        "manifest_jsonl": output_dir / "manifest.jsonl",
        "manifest_csv": output_dir / "manifest.csv",
        "manifest_md": output_dir / "manifest.md",
    }
    write_manifest_jsonl(records, paths["manifest_jsonl"])
    write_manifest_csv(records, paths["manifest_csv"])
    write_manifest_markdown(records, paths["manifest_md"])
    return paths


def write_manifest_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            normalized = {
                field: record.get(field) for field in SEARCH_MANIFEST_FIELDS
            }
            handle.write(json.dumps(normalized, ensure_ascii=False))
            handle.write("\n")


def write_manifest_csv(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SEARCH_MANIFEST_FIELDS)
        writer.writeheader()
        for record in records:
            row = {field: record.get(field) for field in SEARCH_MANIFEST_FIELDS}
            for field in (
                "authors",
                "source_providers",
                "matched_authors",
                "matched_queries",
            ):
                row[field] = "; ".join(row[field] or [])
            writer.writerow(row)


def write_manifest_markdown(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# IEEE document manifest",
        "",
        f"- Format version: {MANIFEST_VERSION}",
        f"- Records: {len(records)}",
        "",
        "| Record ID | Year | Title | DOI | Access | Download mode |",
        "|---|---:|---|---|---|---|",
    ]
    for record in records:
        title = str(record.get("title") or "").replace("|", "\\|")
        lines.append(
            "| {record_id} | {year} | {title} | {doi} | {access} | {mode} |".format(
                record_id=record.get("record_id") or "",
                year=record.get("year") or "",
                title=title,
                doi=record.get("doi") or "",
                access=record.get("open_access_status") or "",
                mode=record.get("download_mode") or "",
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_search_manifest(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            missing = [
                field for field in SEARCH_MANIFEST_FIELDS if field not in record
            ]
            if missing:
                raise ValueError(
                    f"Manifest line {line_number} is missing fields: {missing}"
                )
            if record["manifest_version"] != MANIFEST_VERSION:
                raise ValueError(
                    f"Unsupported manifest version: {record['manifest_version']}"
                )
            records.append(record)
    return records


def manifest_records_to_works(records: list[dict[str, Any]]) -> list[Work]:
    return [
        Work(
            title=str(record.get("title") or ""),
            record_id=str(record.get("record_id") or "") or None,
            authors=list(record.get("authors") or []),
            abstract=record.get("abstract"),
            doi=record.get("doi"),
            year=record.get("year"),
            venue=record.get("venue"),
            publisher=record.get("publisher"),
            publication_type=record.get("publication_type"),
            landing_page_url=record.get("landing_page_url"),
            pdf_url=record.get("oa_pdf_url"),
            authorized_pdf_url=record.get("authorized_pdf_url"),
            oa_status=record.get("open_access_status"),
            source_providers=list(record.get("source_providers") or []),
            matched_authors=list(record.get("matched_authors") or []),
            matched_queries=list(record.get("matched_queries") or []),
        )
        for record in records
    ]


def write_download_manifest(results: list[object], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "download_manifest.jsonl"
    records_by_id = {
        str(record["record_id"]): record
        for record in _read_download_manifest(path)
        if record.get("record_id")
    }
    for item in results:
        doi = getattr(item, "doi", None)
        work = Work(
            title=str(getattr(item, "title", "")),
            doi=doi,
            record_id=getattr(item, "record_id", None),
        )
        record_id = _record_id(work)
        existing = records_by_id.get(record_id)
        status = getattr(item, "status", None)
        if (
            existing
            and existing.get("status") == "downloaded"
            and status == "skipped"
        ):
            continue
        records_by_id[record_id] = {
            "manifest_version": MANIFEST_VERSION,
            "record_id": record_id,
            "title": work.title,
            "doi": doi,
            "mode": getattr(item, "mode", None),
            "status": status,
            "local_path": getattr(item, "path", None),
            "message": getattr(item, "message", None),
            "attempted_at": _utc_now(),
        }
    records = list(records_by_id.values())
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
    csv_path = output_dir / "download_manifest.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DOWNLOAD_MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(records)
    return path


def _read_download_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{line_number}: invalid JSON: {exc.msg}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"{path}:{line_number}: manifest record must be an object"
                )
            records.append(record)
    return records


def _record_id(work: Work) -> str:
    if work.record_id:
        return work.record_id
    if work.doi:
        return f"doi:{work.doi.casefold()}"
    if work.ieee_article_number:
        return f"ieee:{work.ieee_article_number}"
    digest = hashlib.sha256(
        f"{work.title}|{work.year or ''}".encode("utf-8")
    ).hexdigest()[:16]
    return f"sha256:{digest}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
