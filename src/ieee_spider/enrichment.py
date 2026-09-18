from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ieee_spider.auth import LoginConfig
from ieee_spider.manifest import read_search_manifest
from ieee_spider.xplore import XploreBrowserSearch


class AuthRequiredError(RuntimeError):
    pass


@dataclass(slots=True)
class EnrichmentReport:
    records: int
    cached: int
    pending: int
    attempted: int
    ok: int
    failed: int
    unresolved_failed: int
    output_path: Path


def enrich_manifest(
    input_path: Path,
    output_path: Path,
    *,
    config: LoginConfig | None = None,
    record_ids: set[str] | None = None,
    delay_seconds: float = 4.0,
    cooldown_every: int = 5,
    cooldown_seconds: float = 20.0,
    throttle_cooldown_seconds: float = 60.0,
    page_wait_seconds: float = 1.8,
    max_attempts: int = 4,
    retry_failed: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
) -> EnrichmentReport:
    records = read_search_manifest(input_path)
    if not records:
        raise ValueError(f"No search records found in {input_path}")

    selected_ids = record_ids or set()
    if selected_ids:
        records = [
            record
            for record in records
            if record["record_id"] in selected_ids
        ]
        missing_ids = selected_ids - {
            record["record_id"] for record in records
        }
        if missing_ids:
            raise ValueError(
                "Unknown record IDs: " + ", ".join(sorted(missing_ids))
            )

    cached = read_enrichment_output(output_path)
    pending = [
        record
        for record in records
        if needs_enrichment(
            cached.get(record["record_id"]),
            retry_failed=retry_failed,
        )
    ]
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        pending = pending[:limit]

    unresolved = [
        record["record_id"]
        for record in records
        if cached.get(record["record_id"], {}).get("status") == "failed"
        and not retry_failed
    ]
    if dry_run or not pending:
        return _build_report(
            records,
            cached,
            pending=pending,
            attempted=0,
            unresolved_failed=unresolved,
            output_path=output_path,
        )

    attempted = 0
    with XploreBrowserSearch(config=config) as browser:
        page = browser._page
        for index, record in enumerate(pending, 1):
            item = enrich_one(
                page,
                record,
                page_wait_seconds=page_wait_seconds,
                max_attempts=max_attempts,
                throttle_cooldown_seconds=throttle_cooldown_seconds,
            )
            cached[record["record_id"]] = item
            write_enrichment_output(output_path, records, cached)
            attempted += 1
            print(
                f"[{index}/{len(pending)}] {item['status']} "
                f"{record['record_id']} chars={len(item['abstract'] or '')}",
                flush=True,
            )
            if index < len(pending):
                time.sleep(delay_seconds)
                if index % cooldown_every == 0:
                    print(
                        f"COOLDOWN {cooldown_seconds:g}s",
                        flush=True,
                    )
                    time.sleep(cooldown_seconds)

    return _build_report(
        records,
        cached,
        pending=pending,
        attempted=attempted,
        unresolved_failed=unresolved,
        output_path=output_path,
    )


def enrich_one(
    page: Any,
    record: dict[str, Any],
    *,
    page_wait_seconds: float,
    max_attempts: int,
    throttle_cooldown_seconds: float,
) -> dict[str, Any]:
    url = record.get("landing_page_url") or ""
    if not url:
        return _result(record, status="failed", error="missing landing_page_url")

    abstract = None
    metrics = None
    error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            if response and response.status in {401, 403}:
                raise AuthRequiredError(f"HTTP {response.status} for {url}")
            if response and response.status == 418:
                raise RuntimeError("HTTP 418: IEEE throttled the request")
            page.wait_for_timeout(int(page_wait_seconds * 1000))
            ensure_detail_page(page, url)
            abstract = extract_abstract(page)
            metrics = extract_document_metrics(page)
            if not abstract:
                raise RuntimeError("abstract not found in IEEE detail page")
            error = None
            break
        except AuthRequiredError:
            raise
        except Exception as exc:
            error = str(exc)
            if attempt < max_attempts:
                delay = (
                    throttle_cooldown_seconds
                    if is_throttling_error(error)
                    else min(10.0, 2.0 * attempt)
                )
                print(
                    f"RETRY {record['record_id']} attempt={attempt + 1} "
                    f"sleep={delay:g}s error={error}",
                    flush=True,
                )
                time.sleep(delay)

    return _result(
        record,
        status="ok" if abstract else "failed",
        abstract=abstract,
        metrics=metrics,
        error=error,
    )


def extract_abstract(page: Any) -> str | None:
    expand_abstract(page)
    try:
        page.wait_for_selector(
            "div.abstract-text",
            state="attached",
            timeout=10_000,
        )
    except Exception:
        pass
    locator = page.locator("div.abstract-text").first
    text = None
    if locator.count() > 0:
        locator.wait_for(state="visible", timeout=10_000)
        text = locator.inner_text().strip()
    if not text:
        meta = page.locator('meta[property="og:description"]')
        if meta.count() > 0:
            text = (meta.first.get_attribute("content") or "").strip()
    return clean_abstract_text(text)


def expand_abstract(page: Any) -> None:
    show_more = page.locator("button, a").filter(
        has_text=re.compile(r"^\s*Show More\s*$", re.IGNORECASE)
    )
    for index in range(min(show_more.count(), 3)):
        candidate = show_more.nth(index)
        try:
            if candidate.is_visible():
                candidate.click(timeout=5_000)
                page.wait_for_timeout(300)
                return
        except Exception:
            continue


def clean_abstract_text(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(
        r"^Abstract:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s*(?:Show More|Show Less)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip() or None


def extract_document_metrics(page: Any) -> dict[str, Any]:
    locator = page.locator('[class*="metric" i]')
    texts = [
        locator.nth(index).inner_text()
        for index in range(locator.count())
    ]
    return parse_document_metrics(texts)


def parse_document_metrics(texts: list[str]) -> dict[str, Any]:
    normalized = "\n".join(texts)
    citation_count = _first_metric_count(
        normalized,
        r"(\d[\d,]*)\s+Cites?\s+in\s+Papers",
    )
    patent_citation_count = _first_metric_count(
        normalized,
        r"(\d[\d,]*)\s+Patent\s+Cites?",
    )
    full_text_views = _first_metric_count(
        normalized,
        r"(\d[\d,]*)\s+Full\s+Text\s+Views",
    )
    if citation_count is None:
        status = (
            "unavailable"
            if "no metrics found" in normalized.casefold()
            else "not_reported"
        )
    else:
        status = "available"
    return {
        "citation_count": citation_count,
        "patent_citation_count": patent_citation_count,
        "full_text_views": full_text_views,
        "citation_status": status,
    }


def _first_metric_count(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def ensure_detail_page(page: Any, url: str) -> None:
    title = page.title()
    current_url = page.url.casefold()
    if any(marker in current_url for marker in ("signin", "login", "sign-in")):
        raise AuthRequiredError(f"IEEE redirected to sign-in while opening {url}")
    if "unable to load page" in title.casefold() or "access denied" in title.casefold():
        raise RuntimeError(f"IEEE detail page failed: {title}")


def needs_enrichment(
    cached: dict[str, Any] | None,
    *,
    retry_failed: bool,
) -> bool:
    if cached is None:
        return True
    if cached.get("status") == "ok" and cached.get("abstract"):
        abstract = cached["abstract"].casefold()
        if "show more" in abstract or "show less" in abstract:
            return True
        return any(
            field not in cached
            for field in (
                "citation_count",
                "patent_citation_count",
                "full_text_views",
                "citation_status",
            )
        )
    return retry_failed


def is_throttling_error(error: str) -> bool:
    return (
        "HTTP 418" in error
        or "ERR_HTTP_RESPONSE_CODE_FAILURE" in error
    )


def read_enrichment_output(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            item = json.loads(line)
            record_id = item.get("record_id")
            if not record_id:
                raise ValueError(f"{path}:{line_number}: missing record_id")
            if record_id in result:
                raise ValueError(f"{path}:{line_number}: duplicate {record_id}")
            result[record_id] = item
    return result


def write_enrichment_output(
    path: Path,
    records: list[dict[str, Any]],
    cached: dict[str, dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [
        cached[record["record_id"]]
        for record in records
        if record["record_id"] in cached
    ]
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False) + "\n"
            for item in ordered
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _result(
    record: dict[str, Any],
    *,
    status: str,
    abstract: str | None = None,
    metrics: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    metrics = metrics or {}
    return {
        "manifest_version": 1,
        "record_id": record["record_id"],
        "title": record.get("title"),
        "year": record.get("year"),
        "venue": record.get("venue"),
        "status": status,
        "abstract": abstract,
        "citation_count": metrics.get("citation_count"),
        "patent_citation_count": metrics.get("patent_citation_count"),
        "full_text_views": metrics.get("full_text_views"),
        "citation_status": metrics.get("citation_status", "not_reported"),
        "landing_page_url": record.get("landing_page_url"),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "error": error,
    }


def _build_report(
    records: list[dict[str, Any]],
    cached: dict[str, dict[str, Any]],
    *,
    pending: list[dict[str, Any]],
    attempted: int,
    unresolved_failed: list[str],
    output_path: Path,
) -> EnrichmentReport:
    ordered = [
        cached[record["record_id"]]
        for record in records
        if record["record_id"] in cached
    ]
    ok = sum(
        item.get("status") == "ok" and bool(item.get("abstract"))
        for item in ordered
    )
    failed = sum(
        not (item.get("status") == "ok" and item.get("abstract"))
        for item in ordered
    )
    return EnrichmentReport(
        records=len(records),
        cached=len(ordered),
        pending=len(pending),
        attempted=attempted,
        ok=ok,
        failed=failed,
        unresolved_failed=len(unresolved_failed),
        output_path=output_path,
    )
