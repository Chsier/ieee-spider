from pathlib import Path

from ieee_spider.exporters import export_all, read_jsonl
from ieee_spider.models import Work


def test_export_round_trip(tmp_path: Path) -> None:
    work = Work(
        title="A Test Paper",
        authors=["Example Author", "Second Author"],
        doi="10.1109/test.1",
        year=2025,
        venue="IEEE Transactions on Testing",
        source_providers=["ieee-xplore-browser"],
        matched_authors=["Example Author"],
    )

    paths = export_all([work], tmp_path)
    loaded = read_jsonl(paths["jsonl"])

    assert loaded[0].title == work.title
    assert paths["csv"].read_text(encoding="utf-8-sig").startswith("title,authors")
    assert "@article{" in paths["bib"].read_text(encoding="utf-8")
    assert "Unique records: 1" in paths["report"].read_text(encoding="utf-8")
