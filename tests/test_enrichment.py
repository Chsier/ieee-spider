import json
from pathlib import Path

from ieee_spider.cli import build_parser
from ieee_spider.enrichment import (
    clean_abstract_text,
    enrich_one,
    is_throttling_error,
    needs_enrichment,
    parse_document_metrics,
    read_enrichment_output,
    write_enrichment_output,
)


def test_clean_abstract_removes_ieee_label() -> None:
    assert clean_abstract_text("Abstract:\nUseful text.") == "Useful text."
    assert (
        clean_abstract_text("Useful text.\nShow More")
        == "Useful text."
    )
    assert (
        clean_abstract_text("Useful text.\nShow Less")
        == "Useful text."
    )
    assert clean_abstract_text("") is None


def test_needs_enrichment_respects_successful_cache() -> None:
    successful = {"status": "ok", "abstract": "text"}
    failed = {"status": "failed", "abstract": None}
    enriched = {
        "status": "ok",
        "abstract": "text",
        "citation_count": None,
        "patent_citation_count": None,
        "full_text_views": 10,
        "citation_status": "not_reported",
    }

    assert needs_enrichment(successful, retry_failed=False)
    assert not needs_enrichment(enriched, retry_failed=False)
    assert needs_enrichment(
        {"status": "ok", "abstract": "Text truncated...\nShow More"},
        retry_failed=False,
    )
    assert needs_enrichment(
        {"status": "ok", "abstract": "Full text.\nShow Less"},
        retry_failed=False,
    )
    assert not needs_enrichment(failed, retry_failed=False)
    assert needs_enrichment(failed, retry_failed=True)
    assert needs_enrichment(None, retry_failed=False)


def test_throttling_error_detection() -> None:
    assert is_throttling_error("HTTP 418")
    assert is_throttling_error("net::ERR_HTTP_RESPONSE_CODE_FAILURE")
    assert not is_throttling_error("HTTP 403")


def test_parse_document_metrics_extracts_citations_and_views() -> None:
    assert parse_document_metrics(
        [
            "39\nCites in\nPapers\n1417\nFull\nText Views",
            "8\nPatent Cites",
        ]
    ) == {
        "citation_count": 39,
        "patent_citation_count": 8,
        "full_text_views": 1417,
        "citation_status": "available",
    }


def test_parse_document_metrics_supports_views_without_citations() -> None:
    assert parse_document_metrics(
        ["189\nFull\nText Views"]
    ) == {
        "citation_count": None,
        "patent_citation_count": None,
        "full_text_views": 189,
        "citation_status": "not_reported",
    }


def test_parse_document_metrics_reports_unavailable_metrics() -> None:
    assert parse_document_metrics(
        ["No metrics found for this document."]
    ) == {
        "citation_count": None,
        "patent_citation_count": None,
        "full_text_views": None,
        "citation_status": "unavailable",
    }


def test_enrich_one_returns_failure_without_metrics_page() -> None:
    class FailingPage:
        def goto(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("navigation failed")

    result = enrich_one(
        FailingPage(),
        {
            "record_id": "ieee:1",
            "landing_page_url": "https://ieeexplore.ieee.org/document/1/",
        },
        page_wait_seconds=0,
        max_attempts=1,
        throttle_cooldown_seconds=0,
    )

    assert result["status"] == "failed"
    assert result["citation_count"] is None
    assert result["citation_status"] == "not_reported"
    assert result["error"] == "navigation failed"


def test_enrichment_output_round_trip_and_order(tmp_path: Path) -> None:
    records = [
        {"record_id": "ieee:2"},
        {"record_id": "ieee:1"},
    ]
    cached = {
        "ieee:1": {
            "manifest_version": 1,
            "record_id": "ieee:1",
            "status": "ok",
            "abstract": "one",
        },
        "ieee:2": {
            "manifest_version": 1,
            "record_id": "ieee:2",
            "status": "failed",
            "abstract": None,
        },
    }
    path = tmp_path / "abstracts.jsonl"

    write_enrichment_output(path, records, cached)

    loaded = read_enrichment_output(path)
    lines = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert list(loaded) == ["ieee:2", "ieee:1"]
    assert [line["record_id"] for line in lines] == ["ieee:2", "ieee:1"]


def test_cli_parses_enrich_command() -> None:
    args = build_parser().parse_args(
        [
            "enrich",
            "--input",
            "manifest.jsonl",
            "--output",
            "abstracts.jsonl",
            "--dry-run",
        ]
    )

    assert args.command == "enrich"
    assert args.delay_seconds == 4.0
    assert args.cooldown_every == 5
