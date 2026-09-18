from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TargetAuthor:
    name: str
    slug: str
    affiliation: str
    openalex_id: str | None = None
    orcid: str | None = None
    research_areas: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SearchQuery:
    query: str | None = None
    title: str | None = None
    author: str | None = None
    doi: str | None = None
    venue: str | None = None
    from_year: int | None = None
    to_year: int | None = None
    open_access: bool = False

    def describe(self) -> str:
        values = [
            f"{name}={value}"
            for name, value in (
                ("query", self.query),
                ("title", self.title),
                ("author", self.author),
                ("doi", self.doi),
                ("venue", self.venue),
                ("from_year", self.from_year),
                ("to_year", self.to_year),
                ("open_access", self.open_access or None),
            )
            if value not in {None, ""}
        ]
        return "; ".join(values)


@dataclass(slots=True)
class Work:
    title: str
    record_id: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    doi: str | None = None
    year: int | None = None
    publication_date: str | None = None
    venue: str | None = None
    publisher: str | None = None
    publication_type: str | None = None
    landing_page_url: str | None = None
    pdf_url: str | None = None
    authorized_pdf_url: str | None = None
    oa_status: str | None = None
    cited_by_count: int | None = None
    openalex_id: str | None = None
    ieee_article_number: str | None = None
    source_providers: list[str] = field(default_factory=list)
    matched_authors: list[str] = field(default_factory=list)
    matched_queries: list[str] = field(default_factory=list)

    def merge(self, other: Work) -> Work:
        if not self.title and other.title:
            self.title = other.title
        if not self.record_id and other.record_id:
            self.record_id = other.record_id
        if not self.abstract and other.abstract:
            self.abstract = other.abstract
        if not self.doi and other.doi:
            self.doi = other.doi
        if self.year is None:
            self.year = other.year
        if not self.publication_date and other.publication_date:
            self.publication_date = other.publication_date
        if not self.venue and other.venue:
            self.venue = other.venue
        if not self.publisher and other.publisher:
            self.publisher = other.publisher
        if not self.publication_type and other.publication_type:
            self.publication_type = other.publication_type
        if not self.landing_page_url and other.landing_page_url:
            self.landing_page_url = other.landing_page_url
        if not self.pdf_url and other.pdf_url:
            self.pdf_url = other.pdf_url
        if not self.authorized_pdf_url and other.authorized_pdf_url:
            self.authorized_pdf_url = other.authorized_pdf_url
        if not self.oa_status and other.oa_status:
            self.oa_status = other.oa_status
        if self.cited_by_count is None:
            self.cited_by_count = other.cited_by_count
        if not self.openalex_id and other.openalex_id:
            self.openalex_id = other.openalex_id
        if not self.ieee_article_number and other.ieee_article_number:
            self.ieee_article_number = other.ieee_article_number
        self.authors = _unique(self.authors + other.authors)
        self.source_providers = _unique(self.source_providers + other.source_providers)
        self.matched_authors = _unique(self.matched_authors + other.matched_authors)
        self.matched_queries = _unique(self.matched_queries + other.matched_queries)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "doi": self.doi,
            "year": self.year,
            "publication_date": self.publication_date,
            "venue": self.venue,
            "publisher": self.publisher,
            "publication_type": self.publication_type,
            "landing_page_url": self.landing_page_url,
            "pdf_url": self.pdf_url,
            "authorized_pdf_url": self.authorized_pdf_url,
            "oa_status": self.oa_status,
            "cited_by_count": self.cited_by_count,
            "openalex_id": self.openalex_id,
            "ieee_article_number": self.ieee_article_number,
            "source_providers": self.source_providers,
            "matched_authors": self.matched_authors,
            "matched_queries": self.matched_queries,
        }


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def merge_works(works: list[Work]) -> list[Work]:
    merged: dict[str, Work] = {}
    fallback: list[Work] = []
    for work in works:
        key = f"doi:{work.doi}" if work.doi else f"title:{work.title.casefold()}"
        if not work.title:
            continue
        if key in merged:
            merged[key].merge(work)
        else:
            merged[key] = work
            fallback.append(work)
    return sorted(
        merged.values(),
        key=lambda item: (item.year or 0, item.title.casefold()),
        reverse=True,
    )
