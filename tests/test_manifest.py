import json
from pathlib import Path

from ieee_spider.manifest import (
    SEARCH_MANIFEST_FIELDS,
    manifest_records_to_works,
    read_search_manifest,
    write_download_manifest,
    write_search_manifest,
)
from ieee_spider.downloads import DownloadResult
from ieee_spider.models import Work


def test_search_manifest_has_fixed_schema(tmp_path: Path) -> None:
    work = Work(
        title="A Test Paper",
        authors=["Example Author"],
        doi="10.1109/test.1",
        year=2025,
        pdf_url="https://example.org/test.pdf",
        source_providers=["ieee-xplore-browser"],
        matched_queries=["query=test"],
    )

    paths = write_search_manifest([work], tmp_path)
    raw_record = json.loads(
        paths["manifest_jsonl"].read_text(encoding="utf-8").strip()
    )
    records = read_search_manifest(paths["manifest_jsonl"])
    loaded = manifest_records_to_works(records)

    assert tuple(raw_record) == SEARCH_MANIFEST_FIELDS
    assert raw_record["record_id"] == "doi:10.1109/test.1"
    assert loaded[0].pdf_url == "https://example.org/test.pdf"


def test_download_manifest_preserves_source_record_id(tmp_path: Path) -> None:
    result = DownloadResult(
        title="IEEE record",
        doi=None,
        record_id="ieee:123",
        mode="authorized",
        status="downloaded",
        path=str(tmp_path / "paper.pdf"),
    )

    path = write_download_manifest([result], tmp_path)
    record = json.loads(path.read_text(encoding="utf-8").strip())

    assert record["record_id"] == "ieee:123"


def test_download_manifest_merges_records_across_batches(tmp_path: Path) -> None:
    first = DownloadResult(
        title="First IEEE record",
        doi=None,
        record_id="ieee:123",
        mode="authorized",
        status="downloaded",
        path=str(tmp_path / "first.pdf"),
    )
    second = DownloadResult(
        title="Second IEEE record",
        doi=None,
        record_id="ieee:456",
        mode="authorized",
        status="failed",
        path=None,
        message="No PDF access for this account",
    )

    write_download_manifest([first], tmp_path)
    path = write_download_manifest([second], tmp_path)
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]

    assert [record["record_id"] for record in records] == [
        "ieee:123",
        "ieee:456",
    ]
    assert records[0]["status"] == "downloaded"
    assert records[1]["status"] == "failed"


def test_download_manifest_preserves_existing_success_on_skip(
    tmp_path: Path,
) -> None:
    first = DownloadResult(
        title="First IEEE record",
        doi=None,
        record_id="ieee:123",
        mode="authorized",
        status="downloaded",
        path=str(tmp_path / "first.pdf"),
    )
    skipped = DownloadResult(
        title="First IEEE record",
        doi=None,
        record_id="ieee:123",
        mode="authorized",
        status="skipped",
        path=str(tmp_path / "first.pdf"),
        message="File exists",
    )

    write_download_manifest([first], tmp_path)
    path = write_download_manifest([skipped], tmp_path)
    record = json.loads(path.read_text(encoding="utf-8").strip())

    assert record["status"] == "downloaded"
    assert record["message"] is None
