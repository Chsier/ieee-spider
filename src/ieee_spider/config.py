from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ieee_spider.models import TargetAuthor


@dataclass(slots=True)
class AppConfig:
    from_year: int
    to_year: int
    authors: list[TargetAuthor]

    def author_for(self, value: str) -> TargetAuthor:
        normalized = value.casefold()
        for author in self.authors:
            if normalized in {author.slug.casefold(), author.name.casefold()}:
                return author
        raise ValueError(f"Unknown author: {value}")


def project_root() -> Path:
    configured = os.getenv("IEEE_SPIDER_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, "frozen", False):
        local_app_data = os.getenv("LOCALAPPDATA")
        base = (
            Path(local_app_data)
            if local_app_data
            else Path.home() / ".local" / "share"
        )
        return (base / "ieee-spider").resolve()
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    configured = os.getenv("IEEE_SPIDER_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / "config" / "authors.toml"


def load_config(path: Path | str | None = None) -> AppConfig:
    config_path = Path(path).expanduser().resolve() if path else default_config_path()
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)

    authors = [
        TargetAuthor(
            name=item["name"],
            slug=item["slug"],
            affiliation=item["affiliation"],
            openalex_id=item.get("openalex_id"),
            orcid=item.get("orcid"),
            research_areas=list(item.get("research_areas", [])),
        )
        for item in payload.get("authors", [])
    ]
    return AppConfig(
        from_year=int(payload.get("from_year", 2020)),
        to_year=int(payload.get("to_year", 2026)),
        authors=authors,
    )
