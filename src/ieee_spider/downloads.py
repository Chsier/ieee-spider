from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from ieee_spider.auth import (
    LoginConfig,
    launch_persistent_context,
    load_login_config,
    refresh_session,
)
from ieee_spider.manifest import write_download_manifest
from ieee_spider.models import Work


MAX_PDF_BYTES = 100 * 1024 * 1024
PDF_REQUEST_TIMEOUT_SECONDS = 180.0
PDF_REQUEST_TIMEOUT_MS = int(PDF_REQUEST_TIMEOUT_SECONDS * 1_000)
_IFRAME_PDF_RE = re.compile(
    r"""<iframe[^>]+src=["']([^"']*pdf[^"']*)["']""",
    re.IGNORECASE,
)


@dataclass(slots=True)
class DownloadResult:
    title: str
    doi: str | None
    record_id: str | None
    mode: str
    status: str
    path: str | None
    message: str | None = None


def select_download_works(
    works: list[Work], *, mode: str, limit: int | None = None
) -> list[Work]:
    if mode == "oa":
        selected = [work for work in works if work.pdf_url]
    elif mode == "authorized":
        selected = [
            work for work in works if work.landing_page_url or work.doi
        ]
    elif mode == "both":
        selected = [
            work
            for work in works
            if work.pdf_url or work.landing_page_url or work.doi
        ]
    else:
        raise ValueError(f"Unsupported download mode: {mode}")
    if limit is not None:
        return selected[: max(0, limit)]
    return selected


def download_oa(
    work: Work,
    output_dir: Path,
    *,
    overwrite: bool = False,
    proxy_url: str | None = None,
) -> DownloadResult:
    if not work.pdf_url:
        return _result(work, "oa", "skipped", None, "No OA PDF URL")
    destination = pdf_path(output_dir, work)
    if destination.exists() and not overwrite:
        return _result(work, "oa", "skipped", destination, "File exists")

    parsed = urlparse(work.pdf_url)
    if parsed.scheme not in {"http", "https"}:
        return _result(work, "oa", "failed", None, "Unsupported PDF URL scheme")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".pdf.part")
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=PDF_REQUEST_TIMEOUT_SECONDS,
            trust_env=False,
            proxy=proxy_url or None,
            headers={"User-Agent": "ieee-spider/0.1"},
        ) as client:
            prefix, total = _download_http_pdf(
                client,
                work.pdf_url,
                temporary,
            )
        if not prefix.startswith(b"%PDF"):
            temporary.unlink(missing_ok=True)
            return _result(
                work,
                "oa",
                "failed",
                None,
                "Response is not a PDF",
            )
        temporary.replace(destination)
        return _result(work, "oa", "downloaded", destination)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        return _result(work, "oa", "failed", None, str(exc))


def download_oa_many(
    works: list[Work],
    output_dir: Path,
    *,
    overwrite: bool = False,
    workers: int = 3,
    proxy_by_record: dict[str, str] | None = None,
) -> list[DownloadResult]:
    if not works:
        return []
    bounded_workers = min(max(1, workers), 5)
    proxies = proxy_by_record or {}
    results: list[DownloadResult | None] = [None] * len(works)
    with ThreadPoolExecutor(max_workers=bounded_workers) as executor:
        futures = {
            executor.submit(
                download_oa,
                work,
                output_dir,
                overwrite=overwrite,
                proxy_url=(
                    proxies.get(work.record_id or "") or None
                ),
            ): index
            for index, work in enumerate(works)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [item for item in results if item is not None]


class AuthorizedPdfDownloader:
    def __init__(
        self,
        *,
        config: LoginConfig | None = None,
    ) -> None:
        self.config = config or load_login_config()
        self._playwright = None
        self._context = None
        self._session_page = None

    def __enter__(self) -> AuthorizedPdfDownloader:
        if not self.config.auth_file.exists():
            raise FileNotFoundError(
                f"Auth state not found: {self.config.auth_file}. "
                "Run the login command first."
            )
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._context = launch_persistent_context(
            self._playwright,
            self.config,
        )
        self._session_page = (
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

    def download(
        self,
        work: Work,
        output_dir: Path,
        *,
        overwrite: bool = False,
    ) -> DownloadResult:
        if not self._context:
            raise RuntimeError("Downloader must be used as a context manager")
        self._ensure_session()
        destination = pdf_path(output_dir, work)
        if destination.exists() and not overwrite:
            return _result(work, "authorized", "skipped", destination, "File exists")

        direct_result = self._try_direct_pdf_url(work, destination)
        if direct_result is not None:
            return direct_result

        landing_url = work.landing_page_url
        if not landing_url and work.doi:
            landing_url = f"https://doi.org/{work.doi}"
        if not landing_url:
            return _result(
                work,
                "authorized",
                "skipped",
                None,
                "No landing-page URL",
            )

        page = self._context.new_page()
        try:
            page.goto(landing_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1_000)
            link = page.locator(
                "a[href*='stamp.jsp'], a[href$='.pdf'], "
                "a[aria-label*='PDF' i], a[title*='PDF' i]"
            ).first
            if link.count() == 0:
                return _result(
                    work,
                    "authorized",
                    "failed",
                    None,
                    "No PDF link was exposed for this account",
                )
            href = link.get_attribute("href")
            link_title = (link.get_attribute("title") or "").casefold()
            if (
                not href
                or href.casefold().startswith("javascript:")
                or "do not have access" in link_title
            ):
                return _result(
                    work,
                    "authorized",
                    "failed",
                    None,
                    "No PDF access for this account",
                )
            absolute_url = urljoin(page.url, href) if href else page.url

            if self._try_request_pdf(absolute_url, destination):
                return _result(
                    work,
                    "authorized",
                    "downloaded",
                    destination,
                )
            return _result(
                work,
                "authorized",
                "failed",
                None,
                "No downloadable PDF was exposed for this account",
            )
        except Exception as exc:
            return _result(work, "authorized", "failed", None, str(exc))
        finally:
            try:
                page.close(run_before_unload=False)
            except Exception:
                pass

    def _try_direct_pdf_url(
        self,
        work: Work,
        destination: Path,
    ) -> DownloadResult | None:
        if not work.authorized_pdf_url or not self._context:
            return None
        try:
            response = self._context.request.get(
                work.authorized_pdf_url,
                headers={
                    "Referer": (
                        "https://ieeexplore.ieee.org/"
                        "search/searchresult.jsp"
                    )
                },
                timeout=PDF_REQUEST_TIMEOUT_MS,
            )
            content = response.body()
            if (
                response.status == 200
                and len(content) <= MAX_PDF_BYTES
                and content.startswith(b"%PDF")
            ):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                return _result(
                    work,
                    "authorized",
                    "downloaded",
                    destination,
                )
            if response.status == 200:
                html_text = content.decode("utf-8", "ignore")
                nested_pdf_url = _extract_pdf_iframe_url(
                    html_text,
                    response.url or work.authorized_pdf_url,
                )
                if nested_pdf_url:
                    nested = self._context.request.get(
                        nested_pdf_url,
                        headers={"Referer": work.authorized_pdf_url},
                        timeout=PDF_REQUEST_TIMEOUT_MS,
                    )
                    nested_content = nested.body()
                    if (
                        nested.status == 200
                        and len(nested_content) <= MAX_PDF_BYTES
                        and nested_content.startswith(b"%PDF")
                    ):
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(nested_content)
                        return _result(
                            work,
                            "authorized",
                            "downloaded",
                            destination,
                        )
        except Exception:
            return None
        return None

    def _try_request_pdf(
        self,
        url: str,
        destination: Path,
    ) -> bool:
        if not self._context:
            return False
        try:
            response = self._context.request.get(
                url,
                timeout=PDF_REQUEST_TIMEOUT_MS,
            )
            content = response.body()
            if (
                response.status == 200
                and len(content) <= MAX_PDF_BYTES
                and content.startswith(b"%PDF")
            ):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                return True
            if response.status == 200:
                html_text = content.decode("utf-8", "ignore")
                nested_pdf_url = _extract_pdf_iframe_url(
                    html_text,
                    response.url or url,
                )
                if nested_pdf_url:
                    nested = self._context.request.get(
                        nested_pdf_url,
                        headers={"Referer": url},
                        timeout=PDF_REQUEST_TIMEOUT_MS,
                    )
                    nested_content = nested.body()
                    if (
                        nested.status == 200
                        and len(nested_content) <= MAX_PDF_BYTES
                        and nested_content.startswith(b"%PDF")
                    ):
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(nested_content)
                        return True
        except Exception:
            return False
        return False

    def _ensure_session(self) -> None:
        if not self._context or not self._session_page:
            raise RuntimeError("Authorized downloader is not initialized")
        status = refresh_session(
            self._session_page,
            self._context,
            self.config,
        )
        if status.authenticated:
            return
        raise RuntimeError(
            "IEEE session is not authenticated. Run 'ieee-spider login' "
            "in a separate terminal."
        )

    @staticmethod
    def _try_browser_download(page: object, link: object) -> object | None:
        try:
            with page.expect_download(timeout=15_000) as download_info:
                link.click()
            return download_info.value
        except Exception:
            return None


def pdf_path(output_dir: Path, work: Work) -> Path:
    identifier = work.doi or work.ieee_article_number or work.title[:80]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", identifier).strip("._")
    return output_dir / f"{safe or 'paper'}.pdf"


def _result(
    work: Work,
    mode: str,
    status: str,
    path: Path | None,
    message: str | None = None,
) -> DownloadResult:
    return DownloadResult(
        title=work.title,
        doi=work.doi,
        record_id=work.record_id,
        mode=mode,
        status=status,
        path=str(path) if path else None,
        message=message,
    )


def _is_pdf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size > MAX_PDF_BYTES:
        return False
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def _download_http_pdf(
    client: httpx.Client,
    url: str,
    destination: Path,
) -> tuple[bytes, int]:
    response = client.get(url, timeout=PDF_REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    content = response.content
    if content.startswith(b"%PDF"):
        if len(content) > MAX_PDF_BYTES:
            raise ValueError("PDF exceeds 100 MiB limit")
        destination.write_bytes(content)
        return content[:8], len(content)

    if "html" not in response.headers.get("content-type", "").casefold():
        return content[:8], len(content)
    nested_pdf_url = _extract_pdf_iframe_url(
        content.decode("utf-8", "ignore"),
        url,
    )
    if not nested_pdf_url:
        return content[:8], len(content)

    prefix = b""
    total = 0
    with client.stream(
        "GET",
        nested_pdf_url,
        headers={"Referer": url},
        timeout=PDF_REQUEST_TIMEOUT_SECONDS,
    ) as nested:
        nested.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in nested.iter_bytes():
                if not prefix:
                    prefix = chunk[:8]
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise ValueError("PDF exceeds 100 MiB limit")
                handle.write(chunk)
    return prefix, total


def _extract_pdf_iframe_url(value: str, base_url: str) -> str | None:
    match = _IFRAME_PDF_RE.search(value)
    if not match:
        return None
    return urljoin(base_url, html.unescape(match.group(1)))
