from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin

from ieee_spider.auth import (
    LoginConfig,
    launch_persistent_context,
    load_login_config,
    refresh_session,
)
from ieee_spider.models import SearchQuery, Work


SEARCH_ENDPOINT = "https://ieeexplore.ieee.org/search/searchresult.jsp"
MAX_PAGES = 20
_YEAR_RE = re.compile(r"\bYear:\s*(\d{4})\b", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"/document/(\d+)")


@dataclass(slots=True)
class XploreSearchReport:
    works: list[Work]
    pages: int
    query_text: str


class XploreBrowserSearch:
    def __init__(
        self,
        *,
        config: LoginConfig | None = None,
    ) -> None:
        self.config = config or load_login_config()
        self._playwright = None
        self._context = None
        self._page = None

    def __enter__(self) -> XploreBrowserSearch:
        if not self.config.auth_file.exists():
            raise FileNotFoundError(
                f"Auth state not found: {self.config.auth_file}. "
                "Run 'ieee-spider login' first."
            )
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._context = launch_persistent_context(
            self._playwright,
            self.config,
        )
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else self._context.new_page()
        )
        self._ensure_session()
        return self

    def __exit__(self, *_: object) -> None:
        if self._context:
            self._context.storage_state(path=str(self.config.auth_file))
            self._context.close()
        if self._playwright:
            self._playwright.stop()

    def search(
        self,
        query: SearchQuery,
        *,
        max_results: int,
    ) -> XploreSearchReport:
        if not self._page:
            raise RuntimeError("Xplore search session is not initialized")
        query_text = build_query_text(query)
        if not query_text:
            raise ValueError("IEEE Xplore search requires at least one field")

        works: list[Work] = []
        seen: set[str] = set()
        pages = 0
        for page_number in range(1, MAX_PAGES + 1):
            if len(works) >= max_results:
                break
            params = {
                "newsearch": "true" if page_number == 1 else "false",
                "queryText": query_text,
                "pageNumber": page_number,
            }
            url = f"{SEARCH_ENDPOINT}?{urlencode(params)}"
            response = self._goto_results(url)
            if response and response.status in {401, 403}:
                self._raise_auth_required()
            self._wait_for_results()
            self._ensure_search_page()
            self._wait_for_pdf_links()
            items = self._page.locator("xpl-results-item")
            count = items.count()
            if count == 0:
                break
            pages += 1
            for index in range(count):
                work = self._parse_item(items.nth(index), query_text)
                if not work:
                    continue
                if query.author and not author_matches(
                    query.author,
                    work.authors,
                ):
                    continue
                if query.from_year and (work.year or 0) < query.from_year:
                    continue
                if query.to_year and (work.year or 9999) > query.to_year:
                    continue
                if query.open_access and work.oa_status != "open":
                    continue
                key = work.ieee_article_number or work.title.casefold()
                if key in seen:
                    continue
                seen.add(key)
                if query.author:
                    work.matched_authors = _unique(
                        work.matched_authors + [query.author]
                    )
                works.append(work)
                if len(works) >= max_results:
                    break
        return XploreSearchReport(
            works=works,
            pages=pages,
            query_text=query_text,
        )

    def _parse_item(self, item: object, query_text: str) -> Work | None:
        title_link = item.locator("h3 a.fw-bold").first
        if title_link.count() == 0:
            return None
        title = title_link.inner_text().strip()
        href = title_link.get_attribute("href") or ""
        article_match = _ARTICLE_RE.search(href)
        article_number = article_match.group(1) if article_match else None
        if not title:
            return None

        authors = _unique(
            value.strip()
            for value in item.locator("xpl-authors-name-list a").all_inner_texts()
            if value.strip()
        )
        description = item.locator(".description").first.inner_text().strip()
        description_lines = [
            line.strip() for line in description.splitlines() if line.strip()
        ]
        metadata_line = next(
            (line for line in reversed(description_lines) if "Year:" in line),
            "",
        )
        year_match = _YEAR_RE.search(metadata_line)
        year = int(year_match.group(1)) if year_match else None
        publication_type = _metadata_value(metadata_line, "|", 1, "|")
        publisher = _metadata_value(metadata_line, "Publisher:", 1, None)
        venue = description_lines[0] if description_lines else None
        oa_marker = item.locator(
            "[aria-label='open access'], .icon-access-open-access"
        )
        pdf_link = item.locator(
            "a[href*='stamp.jsp'], a[aria-label='PDF' i], "
            "a[aria-label='pdf' i]"
        ).first
        authorized_pdf_url = None
        if pdf_link.count() > 0:
            pdf_href = pdf_link.get_attribute("href")
            if pdf_href:
                authorized_pdf_url = urljoin(
                    "https://ieeexplore.ieee.org",
                    pdf_href,
                )
        oa_status = "open" if oa_marker.count() > 0 else "unknown"
        oa_pdf_url = (
            authorized_pdf_url if oa_status == "open" else None
        )
        landing_page_url = urljoin(
            "https://ieeexplore.ieee.org",
            href,
        )
        return Work(
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            publisher=publisher or "IEEE",
            publication_type=publication_type,
            landing_page_url=landing_page_url,
            pdf_url=oa_pdf_url,
            authorized_pdf_url=authorized_pdf_url,
            oa_status=oa_status,
            ieee_article_number=article_number,
            source_providers=["ieee-xplore-browser"],
            matched_queries=[query_text],
        )

    def _ensure_search_page(self) -> None:
        title = self._page.title().casefold()
        if "search results" in title:
            return
        self._raise_auth_required()

    def _wait_for_results(self) -> None:
        try:
            self._page.wait_for_function(
                """
                () => {
                  if (document.querySelectorAll('xpl-results-item').length > 0) {
                    return true;
                  }
                  const text = (document.body?.innerText || '').toLowerCase();
                  return text.includes('no results') ||
                         text.includes('did not match any documents');
                }
                """,
                timeout=30_000,
            )
        except Exception:
            # Let the normal parsing path decide whether the page contains
            # results or a login/error page.
            pass

    def _goto_results(self, url: str) -> object | None:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return self._page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if attempt == 2 or not any(
                    marker in message
                    for marker in (
                        "ERR_NETWORK_CHANGED",
                        "ERR_CONNECTION_RESET",
                        "ERR_TIMED_OUT",
                    )
                ):
                    raise
                time.sleep(2.0 * (attempt + 1))
        raise last_error or RuntimeError("Xplore navigation failed")

    def _wait_for_pdf_links(self) -> None:
        try:
            self._page.wait_for_function(
                """
                () => document.querySelector(
                  "xpl-results-item a[href*='stamp.jsp']"
                ) !== null
                """,
                timeout=3_000,
            )
        except Exception:
            # Some records legitimately expose no direct PDF link.
            pass

    def _ensure_session(self) -> None:
        status = refresh_session(self._page, self._context, self.config)
        if status.authenticated:
            return
        self._raise_auth_required()

    @staticmethod
    def _raise_auth_required() -> None:
        raise RuntimeError(
            "IEEE Xplore session is not authenticated. "
            "Run 'ieee-spider login' in a separate terminal."
        )


def build_query_text(query: SearchQuery) -> str:
    terms: list[str] = []
    if query.query:
        terms.append(f"({query.query})")
    if query.title:
        terms.append(f'"Document Title":"{_quote_value(query.title)}"')
    if query.author:
        terms.append(f'"Authors":"{_quote_value(query.author)}"')
    if query.doi:
        terms.append(f'"DOI":"{_quote_value(query.doi)}"')
    if query.venue:
        terms.append(f'"Publication Title":"{_quote_value(query.venue)}"')
    year_clause = _build_year_clause(query.from_year, query.to_year)
    if year_clause:
        terms.append(year_clause)
    return " AND ".join(terms)


def _build_year_clause(
    from_year: int | None, to_year: int | None
) -> str | None:
    if from_year is None and to_year is None:
        return None
    start = from_year or to_year
    end = to_year or from_year
    if start is None or end is None or end < start or end - start > 10:
        return None
    years = [f'"Publication Year":{year}' for year in range(start, end + 1)]
    if len(years) == 1:
        return years[0]
    return f"({' OR '.join(years)})"


def _quote_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def author_matches(target: str, authors: list[str]) -> bool:
    normalized_target = _normalize_author(target)
    return any(
        _normalize_author(author) == normalized_target
        for author in authors
    )


def _normalize_author(value: str) -> str:
    return " ".join(value.split()).casefold()


def _metadata_value(
    value: str,
    marker: str,
    index: int,
    trailing: str | None,
) -> str | None:
    if marker not in value:
        return None
    tail = value.split(marker, 1)[1]
    if trailing:
        tail = tail.split(trailing, 1)[0]
    return tail.strip() or None


def _unique(values: object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = str(value).casefold()
        if key not in seen:
            seen.add(key)
            result.append(str(value))
    return result
