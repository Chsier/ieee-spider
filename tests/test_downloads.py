from pathlib import Path
import threading
import time

import ieee_spider.downloads as downloads
from ieee_spider.downloads import (
    DownloadResult,
    _extract_pdf_iframe_url,
    pdf_path,
    select_download_works,
)
from ieee_spider.models import Work


def test_pdf_path_uses_doi(tmp_path: Path) -> None:
    work = Work(title="A/B", doi="10.1109/TEST.1")

    result = pdf_path(tmp_path, work)

    assert result == tmp_path / "10.1109_TEST.1.pdf"


def test_oa_download_workers_are_bounded(
    tmp_path: Path, monkeypatch: object
) -> None:
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_download(
        work: Work, output_dir: Path, *, overwrite: bool = False
    ) -> DownloadResult:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return DownloadResult(
            title=work.title,
            doi=work.doi,
            record_id=work.record_id,
            mode="oa",
            status="downloaded",
            path=str(output_dir / f"{work.doi}.pdf"),
        )

    monkeypatch.setattr(downloads, "download_oa", fake_download)  # type: ignore[attr-defined]
    works = [Work(title=f"Paper {index}", doi=f"10.1109/{index}") for index in range(9)]

    results = downloads.download_oa_many(works, tmp_path, workers=3)

    assert len(results) == 9
    assert maximum_active <= 3


def test_limit_applies_after_oa_eligibility_filter() -> None:
    works = [
        Work(title="Closed", doi="10.1109/closed"),
        Work(title="OA 1", doi="10.1109/oa1", pdf_url="https://example.org/1.pdf"),
        Work(title="Closed 2", doi="10.1109/closed2"),
        Work(title="OA 2", doi="10.1109/oa2", pdf_url="https://example.org/2.pdf"),
    ]

    selected = select_download_works(works, mode="oa", limit=1)

    assert [work.title for work in selected] == ["OA 1"]


def test_extract_pdf_iframe_url() -> None:
    html = (
        '<iframe src="https://ieeexplore.ieee.org/ielx7/1/2/3.pdf'
        '?tp=&amp;arnumber=3"></iframe>'
    )

    assert _extract_pdf_iframe_url(html, "https://ieeexplore.ieee.org") == (
        "https://ieeexplore.ieee.org/ielx7/1/2/3.pdf?tp=&arnumber=3"
    )


def test_extract_pdf_iframe_url_accepts_get_pdf_endpoint() -> None:
    html = (
        '<iframe src="https://ieeexplore.ieee.org/stampPDF/getPDF.jsp'
        '?tp=&arnumber=11576101&ref=abc"></iframe>'
    )

    assert _extract_pdf_iframe_url(
        html,
        "https://ieeexplore.ieee.org/stamp/stamp.jsp",
    ) == (
        "https://ieeexplore.ieee.org/stampPDF/getPDF.jsp"
        "?tp=&arnumber=11576101&ref=abc"
    )
