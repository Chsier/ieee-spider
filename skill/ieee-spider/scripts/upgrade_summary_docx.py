from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


WORD_NAMESPACE = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
)
WORD_TAG = f"{{{WORD_NAMESPACE}}}"
METADATA_PATTERN = re.compile(
    r"^(?P<year>\d{4})\s+\|\s+(?P<venue>.+?)\s+\|\s+"
    r"(?P<record_id>(?:ieee|doi):[^\s|]+)$"
)
NUMBERED_TITLE_PATTERN = re.compile(r"^\d+\.\s+")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Upgrade an existing IEEE paper-summary DOCX into a Markdown "
            "working file with citation, venue, and Top Cited statistics."
        )
    )
    parser.add_argument("--input-docx", type=Path, required=True)
    parser.add_argument("--statistics", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    input_docx = args.input_docx.expanduser().resolve()
    statistics_path = args.statistics.expanduser().resolve()
    output_path = args.output_markdown.expanduser().resolve()

    paragraphs = read_docx_paragraphs(input_docx)
    statistics = json.loads(statistics_path.read_text(encoding="utf-8"))
    markdown = build_markdown(paragraphs, statistics)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    summary_count = markdown.count("摘要总结：")
    print(
        f"summaries={summary_count} papers={statistics.get('paper_count')} "
        f"output={output_path}"
    )


def read_docx_paragraphs(path: Path) -> list[str]:
    if not path.exists():
        raise ValueError(f"DOCX file does not exist: {path}")
    with zipfile.ZipFile(path) as archive:
        document = archive.read("word/document.xml")
    root = ElementTree.fromstring(document)
    paragraphs = []
    for paragraph in root.iter(f"{WORD_TAG}p"):
        text = "".join(
            node.text or ""
            for node in paragraph.iter(f"{WORD_TAG}t")
        )
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def build_markdown(
    paragraphs: list[str],
    statistics: dict[str, Any],
) -> str:
    first_paper = next(
        (
            index
            for index, text in enumerate(paragraphs)
            if NUMBERED_TITLE_PATTERN.match(text)
        ),
        None,
    )
    if first_paper is None:
        raise ValueError("No numbered paper entries found in DOCX")

    stats_heading = next(
        (
            index
            for index, text in enumerate(paragraphs[:first_paper])
            if text == "统计"
        ),
        None,
    )
    preface_end = stats_heading if stats_heading is not None else first_paper
    preface = paragraphs[:preface_end]
    if not preface:
        raise ValueError("DOCX does not contain a document title")

    paper_by_id = {
        str(paper["record_id"]): paper
        for paper in statistics.get("papers") or []
    }
    lines = [f"# {preface[0]}", ""]
    lines.extend(preface[1:])
    lines.extend(["", *_statistics_markdown(statistics), ""])

    for text in paragraphs[first_paper:]:
        metadata = METADATA_PATTERN.match(text)
        if metadata:
            record_id = metadata.group("record_id")
            paper = paper_by_id.get(record_id)
            if paper is None:
                raise ValueError(f"Missing statistics for {record_id}")
            lines.extend(
                [
                    "",
                    (
                        f"{metadata.group('year')} | "
                        f"{metadata.group('venue')} | {record_id} | "
                        f"Cites in Papers: {_display(paper.get('citation_count'))} | "
                        f"Full Text Views: {_display(paper.get('full_text_views'))}"
                    ),
                    "",
                ]
            )
        elif NUMBERED_TITLE_PATTERN.match(text):
            lines.extend(["", f"### {text}", ""])
        elif text.startswith("摘要总结："):
            lines.append(f"- {text}")
        elif len(text) <= 80 and not text.startswith(("检索", "摘要来源", "文件范围", "总结口径")):
            lines.extend(["", f"## {text}", ""])
        else:
            lines.extend([text, ""])

    return "\n".join(_collapse_blank_lines(lines)).strip() + "\n"


def _statistics_markdown(statistics: dict[str, Any]) -> list[str]:
    citation = statistics["citation_summary"]
    views = statistics["full_text_views_summary"]
    patent = statistics["patent_citation_summary"]
    year_range = statistics.get("year_range") or [None, None]
    lines = [
        "## 统计总览",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 论文数 | {statistics['paper_count']} |",
        f"| 年份范围 | {year_range[0]}-{year_range[1]} |",
        f"| 刊物数 | {len(statistics.get('venue_metrics') or [])} |",
        f"| IEEE 报告引用数 | {_display(citation.get('total'))} |",
        (
            "| 有引用指标的论文 | "
            f"{citation.get('reported_count')} / {statistics['paper_count']} |"
        ),
        f"| 已知引用论文平均引用 | {_display(citation.get('mean'))} |",
        f"| 已知引用论文中位引用 | {_display(citation.get('median'))} |",
        f"| 单篇最高引用 | {_display(citation.get('maximum'))} |",
        f"| 全文浏览量合计 | {_display(views.get('total'))} |",
        (
            "| 有浏览量指标的论文 | "
            f"{views.get('reported_count')} / {statistics['paper_count']} |"
        ),
        f"| IEEE 报告的专利引用 | {_display(patent.get('total'))} |",
        "",
        "### 年份分布",
        "",
        "| 年份 | 论文数 |",
        "|---:|---:|",
    ]
    for year, count in (statistics.get("years") or {}).items():
        lines.append(f"| {year} | {count} |")

    lines.extend(
        [
            "",
            "### 刊物与引用",
            "",
            "| 刊物 | 论文数 | 引用合计 | 平均引用 | 最高引用 | 全文浏览合计 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for venue in statistics.get("venue_metrics") or []:
        lines.append(
            f"| {venue['venue']} | {venue['paper_count']} | "
            f"{_display(venue.get('citation_total'))} | "
            f"{_display(venue.get('citation_mean'))} | "
            f"{_display(venue.get('citation_max'))} | "
            f"{_display(venue.get('full_text_views_total'))} |"
        )

    lines.extend(
        [
            "",
            "### 引用最高论文",
            "",
            "| 排名 | 论文 | 年份 | 刊物 | 引用 | 全文浏览 |",
            "|---:|---|---:|---|---:|---:|",
        ]
    )
    for paper in (statistics.get("top_cited_papers") or [])[:10]:
        lines.append(
            f"| {paper['rank']} | {paper['title']} | {paper['year']} | "
            f"{paper['venue']} | {_display(paper.get('citation_count'))} | "
            f"{_display(paper.get('full_text_views'))} |"
        )
    return lines


def _display(value: Any) -> str:
    return "未报告" if value is None else str(value)


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        if not line and result and not result[-1]:
            continue
        result.append(line)
    return result


if __name__ == "__main__":
    main()
