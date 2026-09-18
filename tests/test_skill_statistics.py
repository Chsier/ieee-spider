from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_statistics_module() -> ModuleType:
    script = (
        Path(__file__).parents[1]
        / "skill"
        / "ieee-spider"
        / "scripts"
        / "build_paper_statistics.py"
    )
    spec = importlib.util.spec_from_file_location("skill_statistics", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_statistics_merges_citations_and_venues(tmp_path: Path) -> None:
    module = _load_statistics_module()
    manifest = [
        {
            "record_id": "ieee:1",
            "title": "Older paper",
            "authors": ["Author"],
            "year": 2024,
            "venue": "Journal A",
        },
        {
            "record_id": "ieee:2",
            "title": "Newer paper",
            "authors": ["Author"],
            "year": 2025,
            "venue": "Journal B",
        },
        {
            "record_id": "ieee:3",
            "title": "New paper",
            "authors": ["Author"],
            "year": 2026,
            "venue": "Journal A",
        },
    ]
    abstracts = [
        {
            "record_id": "ieee:1",
            "status": "ok",
            "abstract": "one",
            "citation_count": 25,
            "patent_citation_count": 2,
            "full_text_views": 500,
            "citation_status": "available",
        },
        {
            "record_id": "ieee:2",
            "status": "ok",
            "abstract": "two",
            "citation_count": None,
            "full_text_views": 100,
            "citation_status": "not_reported",
        },
        {
            "record_id": "ieee:3",
            "status": "ok",
            "abstract": "three",
            "citation_count": None,
            "full_text_views": None,
            "citation_status": "unavailable",
        },
    ]

    result = module.build_statistics(
        author="Author",
        manifest=manifest,
        abstracts=abstracts,
        source_manifest=tmp_path / "manifest.jsonl",
        source_abstracts=tmp_path / "abstracts.jsonl",
        top_n=2,
    )

    assert result["citation_summary"] == {
        "available_count": 1,
        "unavailable_count": 1,
        "not_reported_count": 1,
        "reported_count": 1,
        "coverage_ratio": 0.3333,
        "total": 25,
        "mean": 25,
        "median": 25,
        "maximum": 25,
    }
    assert result["abstract_ok_count"] == 3
    assert result["abstract_failed_count"] == 0
    assert result["patent_citation_summary"] == {
        "reported_count": 1,
        "total": 2,
        "maximum": 2,
    }
    assert result["full_text_views_summary"] == {
        "reported_count": 2,
        "total": 600,
        "mean": 300,
        "median": 300,
        "maximum": 500,
    }
    assert result["venues"] == {"Journal A": 2, "Journal B": 1}
    assert result["venue_metrics"][0] == {
        "venue": "Journal A",
        "paper_count": 2,
        "cited_paper_count": 1,
        "citation_total": 25,
        "citation_mean": 25.0,
        "citation_median": 25.0,
        "citation_max": 25,
        "full_text_views_total": 500,
    }
    assert [paper["record_id"] for paper in result["top_cited_papers"]] == [
        "ieee:1",
        "ieee:2",
    ]
