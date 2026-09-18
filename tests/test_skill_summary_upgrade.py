from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path
from types import ModuleType


def _load_module() -> ModuleType:
    script = (
        Path(__file__).parents[1]
        / "skill"
        / "ieee-spider"
        / "scripts"
        / "upgrade_summary_docx.py"
    )
    spec = importlib.util.spec_from_file_location("skill_summary_upgrade", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_summary_preserves_body_and_adds_metrics(tmp_path: Path) -> None:
    module = _load_module()
    document_xml = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Author summaries</w:t></w:r></w:p>
    <w:p><w:r><w:t>1. Example paper</w:t></w:r></w:p>
    <w:p><w:r><w:t>2026 | Journal A | ieee:1</w:t></w:r></w:p>
    <w:p><w:r><w:t>摘要总结：Example summary.</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    docx_path = tmp_path / "old.docx"
    with zipfile.ZipFile(docx_path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    statistics = {
        "paper_count": 1,
        "year_range": [2026, 2026],
        "years": {"2026": 1},
        "venue_metrics": [
            {
                "venue": "Journal A",
                "paper_count": 1,
                "citation_total": 7,
                "citation_mean": 7,
                "citation_max": 7,
                "full_text_views_total": 42,
            }
        ],
        "citation_summary": {
            "total": 7,
            "reported_count": 1,
            "mean": 7,
            "median": 7,
            "maximum": 7,
        },
        "patent_citation_summary": {"total": 0},
        "full_text_views_summary": {"total": 42, "reported_count": 1},
        "top_cited_papers": [
            {
                "rank": 1,
                "title": "Example paper",
                "year": 2026,
                "venue": "Journal A",
                "citation_count": 7,
                "full_text_views": 42,
            }
        ],
        "papers": [{"record_id": "ieee:1", "citation_count": 7, "full_text_views": 42}],
    }

    markdown = module.build_markdown(
        module.read_docx_paragraphs(docx_path),
        statistics,
    )

    assert "# Author summaries" in markdown
    assert "### 1. Example paper" in markdown
    assert "Cites in Papers: 7 | Full Text Views: 42" in markdown
    assert "- 摘要总结：Example summary." in markdown
