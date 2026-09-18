from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from ieee_spider import __version__
from ieee_spider.auth import (
    LoginConfig,
    check_auth,
    default_login_config_path,
    keepalive,
    load_login_config,
    login,
)
from ieee_spider.config import default_config_path, load_config, project_root
from ieee_spider.downloads import (
    AuthorizedPdfDownloader,
    download_oa_many,
    select_download_works,
    write_download_manifest,
)
from ieee_spider.enrichment import AuthRequiredError, enrich_manifest
from ieee_spider.exporters import export_all, read_jsonl
from ieee_spider.manifest import manifest_records_to_works, read_search_manifest
from ieee_spider.models import SearchQuery, merge_works
from ieee_spider.xplore import XploreBrowserSearch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ieee-spider",
        description=(
            "Collect public IEEE metadata and download OA or authorized PDFs."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser(
        "login", help="Open a visible browser and save an IEEE session"
    )
    login_parser.add_argument(
        "--config", type=Path, default=default_login_config_path()
    )
    login_parser.add_argument("--browser", choices=["edge", "chrome", "chromium"])
    login_parser.add_argument("--auth-file", type=Path)
    login_parser.add_argument("--url")
    login_parser.add_argument("--keep-open", action="store_true", default=None)

    check_parser = subparsers.add_parser(
        "auth-check", help="Check the saved IEEE browser session"
    )
    check_parser.add_argument(
        "--config", type=Path, default=default_login_config_path()
    )
    check_parser.add_argument("--browser", choices=["edge", "chrome", "chromium"])
    check_parser.add_argument("--auth-file", type=Path)
    check_parser.add_argument("--url")

    session_parser = subparsers.add_parser(
        "session", help="Keep the IEEE browser session alive"
    )
    session_parser.add_argument(
        "--config", type=Path, default=default_login_config_path()
    )
    session_parser.add_argument("--browser", choices=["edge", "chrome", "chromium"])
    session_parser.add_argument("--auth-file", type=Path)
    session_parser.add_argument("--url")
    session_parser.add_argument("--interval", type=int)
    session_parser.add_argument("--once", action="store_true")

    fetch_parser = subparsers.add_parser(
        "fetch", help="Fetch configured authors through authenticated Xplore"
    )
    fetch_parser.add_argument("--config", type=Path, default=default_config_path())
    fetch_parser.add_argument(
        "--login-config",
        type=Path,
        default=default_login_config_path(),
    )
    fetch_parser.add_argument("--author", action="append", default=[])
    fetch_parser.add_argument("--from-year", type=int)
    fetch_parser.add_argument("--to-year", type=int)
    fetch_parser.add_argument("--max-results", type=int, default=200)
    fetch_parser.add_argument("--output-dir", type=Path)
    fetch_parser.add_argument("--browser", choices=["edge", "chrome", "chromium"])
    fetch_parser.add_argument("--auth-file", type=Path)
    fetch_parser.add_argument("--url")

    search_parser = subparsers.add_parser(
        "search", help="Search IEEE Xplore through the authenticated browser"
    )
    search_parser.add_argument(
        "--login-config",
        type=Path,
        default=default_login_config_path(),
    )
    search_parser.add_argument("--query")
    search_parser.add_argument("--title")
    search_parser.add_argument("--author")
    search_parser.add_argument("--doi")
    search_parser.add_argument("--venue")
    search_parser.add_argument("--from-year", type=int)
    search_parser.add_argument("--to-year", type=int)
    search_parser.add_argument("--open-access", action="store_true")
    search_parser.add_argument("--max-results", type=int, default=25)
    search_parser.add_argument("--browser", choices=["edge", "chrome", "chromium"])
    search_parser.add_argument("--auth-file", type=Path)
    search_parser.add_argument("--url")
    search_parser.add_argument(
        "--output-dir", type=Path, default=project_root() / "data" / "search"
    )

    enrich_parser = subparsers.add_parser(
        "enrich",
        help="Serially retrieve IEEE abstracts for a fixed search manifest",
    )
    enrich_parser.add_argument("--input", type=Path, required=True)
    enrich_parser.add_argument("--output", type=Path, required=True)
    enrich_parser.add_argument(
        "--login-config",
        type=Path,
        default=default_login_config_path(),
    )
    enrich_parser.add_argument("--browser", choices=["edge", "chrome", "chromium"])
    enrich_parser.add_argument("--auth-file", type=Path)
    enrich_parser.add_argument("--url")
    enrich_parser.add_argument("--record-id", action="append", default=[])
    enrich_parser.add_argument(
        "--delay-seconds",
        type=_non_negative_float,
        default=4.0,
    )
    enrich_parser.add_argument(
        "--cooldown-every",
        type=_positive_int,
        default=5,
    )
    enrich_parser.add_argument(
        "--cooldown-seconds",
        type=_non_negative_float,
        default=20.0,
    )
    enrich_parser.add_argument(
        "--throttle-cooldown-seconds",
        type=_non_negative_float,
        default=60.0,
    )
    enrich_parser.add_argument(
        "--page-wait-seconds",
        type=_non_negative_float,
        default=1.8,
    )
    enrich_parser.add_argument(
        "--max-attempts",
        type=_positive_int,
        default=4,
    )
    enrich_parser.add_argument("--retry-failed", action="store_true")
    enrich_parser.add_argument("--limit", type=_positive_int)
    enrich_parser.add_argument("--dry-run", action="store_true")

    download_parser = subparsers.add_parser(
        "download", help="Download OA PDFs or entitled IEEE PDFs"
    )
    download_parser.add_argument(
        "--input", type=Path, default=project_root() / "data" / "manifest.jsonl"
    )
    download_parser.add_argument(
        "--output-dir", type=Path, default=project_root() / "downloads"
    )
    download_parser.add_argument(
        "--mode", choices=["oa", "authorized", "both"], default="oa"
    )
    download_parser.add_argument("--login-config", type=Path, default=default_login_config_path())
    download_parser.add_argument("--browser", choices=["edge", "chrome", "chromium"])
    download_parser.add_argument("--auth-file", type=Path)
    download_parser.add_argument("--record-id", action="append", default=[])
    download_parser.add_argument("--doi", action="append", default=[])
    download_parser.add_argument("--limit", type=int)
    download_parser.add_argument(
        "--workers",
        type=_concurrency,
        default=3,
        help="OA download concurrency, capped at 5 (default: 3)",
    )
    download_parser.add_argument(
        "--delay-seconds",
        type=_non_negative_float,
        default=4.0,
        help="Serial delay between authorized page requests (default: 4)",
    )
    download_parser.add_argument(
        "--throttle-cooldown-seconds",
        type=_non_negative_float,
        default=60.0,
    )
    download_parser.add_argument(
        "--max-attempts",
        type=_positive_int,
        default=2,
    )
    download_parser.add_argument("--overwrite", action="store_true")
    download_parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "login":
            status = login(config=_resolve_login_config(args))
            _print_auth_status(status)
        elif args.command == "auth-check":
            _print_auth_status(
                check_auth(config=_resolve_login_config(args))
            )
        elif args.command == "session":
            _session(args)
        elif args.command == "fetch":
            _fetch(args)
        elif args.command == "search":
            _search(args)
        elif args.command == "enrich":
            _enrich(args)
        elif args.command == "download":
            _download(args)
    except AuthRequiredError as exc:
        print(
            f"authentication required: {exc}. "
            "Run 'ieee-spider login' in a separate terminal.",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _fetch(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    selected_authors = (
        [config.author_for(value) for value in args.author]
        if args.author
        else None
    )
    output_dir = (args.output_dir or project_root() / "data").resolve()
    authors = selected_authors or config.authors
    if not authors:
        raise ValueError(
            f"No authors configured in {args.config}. "
            "Add an [[authors]] entry before using fetch."
        )
    login_config = _resolve_login_config(args, config_attr="login_config")
    all_works = []
    with XploreBrowserSearch(
        config=login_config,
    ) as browser:
        for author in authors:
            query = SearchQuery(
                author=author.name,
                from_year=args.from_year or config.from_year,
                to_year=args.to_year or config.to_year,
            )
            print(f"Searching {author.name}...", flush=True)
            report = browser.search(query, max_results=args.max_results)
            for work in report.works:
                if author.name not in work.matched_authors:
                    work.matched_authors.append(author.name)
            all_works.extend(report.works)
            print(
                f"- {author.name}: {len(report.works)} exact records",
                flush=True,
            )
    works = merge_works(all_works)
    paths = export_all(works, output_dir)
    print(f"Fetched {len(works)} unique records from IEEE Xplore")
    for name, path in paths.items():
        print(f"{name}: {path}")


def _search(args: argparse.Namespace) -> None:
    output_dir = args.output_dir.expanduser().resolve()
    query = SearchQuery(
        query=args.query,
        title=args.title,
        author=args.author,
        doi=args.doi,
        venue=args.venue,
        from_year=args.from_year,
        to_year=args.to_year,
        open_access=args.open_access,
    )
    login_config = _resolve_login_config(args, config_attr="login_config")
    with XploreBrowserSearch(
        config=login_config,
    ) as browser:
        report = browser.search(
            query,
            max_results=args.max_results,
        )
    paths = export_all(report.works, output_dir)
    print(f"Found {len(report.works)} unique records")
    print(f"Source: IEEE Xplore authenticated browser")
    print(f"Query: {report.query_text}")
    print(f"Pages inspected: {report.pages}")
    for name, path in paths.items():
        print(f"{name}: {path}")


def _enrich(args: argparse.Namespace) -> None:
    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    login_config = _resolve_login_config(args, config_attr="login_config")
    report = enrich_manifest(
        input_path,
        output_path,
        config=login_config,
        record_ids=set(args.record_id),
        delay_seconds=args.delay_seconds,
        cooldown_every=args.cooldown_every,
        cooldown_seconds=args.cooldown_seconds,
        throttle_cooldown_seconds=args.throttle_cooldown_seconds,
        page_wait_seconds=args.page_wait_seconds,
        max_attempts=args.max_attempts,
        retry_failed=args.retry_failed,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(
        f"records={report.records}; cached={report.cached}; "
        f"pending={report.pending}; attempted={report.attempted}; "
        f"ok={report.ok}; failed={report.failed}; "
        f"unresolved_failed={report.unresolved_failed}"
    )
    print(f"output: {report.output_path}")


def _download(args: argparse.Namespace) -> None:
    works = _load_works(
        args.input.expanduser().resolve(),
        record_ids=set(args.record_id),
    )
    selected_dois = {value.casefold() for value in args.doi}
    if selected_dois:
        works = [
            work
            for work in works
            if work.doi and work.doi.casefold() in selected_dois
        ]
    works = select_download_works(
        works,
        mode=args.mode,
        limit=args.limit,
    )

    if args.dry_run:
        for work in works:
            targets: list[str] = []
            if args.mode in {"oa", "both"} and work.pdf_url:
                targets.append("oa")
            if args.mode in {"authorized", "both"}:
                targets.append("authorized")
            print(f"{work.doi or '-'}\t{','.join(targets)}\t{work.title}")
        return

    results = []
    if args.mode in {"oa", "both"}:
        results.extend(
            download_oa_many(
                works,
                args.output_dir,
                overwrite=args.overwrite,
                workers=args.workers,
            )
        )
    if args.mode in {"authorized", "both"}:
        login_config = _resolve_login_config(args, config_attr="login_config")
        with AuthorizedPdfDownloader(
            config=login_config,
        ) as downloader:
            for index, work in enumerate(works, 1):
                label = work.record_id or work.doi or work.title
                item = None
                for attempt in range(1, args.max_attempts + 1):
                    print(
                        f"[{index}/{len(works)}] downloading {label} "
                        f"(attempt {attempt}/{args.max_attempts})",
                        flush=True,
                    )
                    item = downloader.download(
                        work,
                        args.output_dir,
                        overwrite=args.overwrite,
                    )
                    if item.status != "failed" or not _retryable_download_failure(
                        item.message
                    ):
                        break
                    if attempt < args.max_attempts:
                        cooldown = _download_retry_cooldown(
                            item.message,
                            args.throttle_cooldown_seconds,
                        )
                        print(
                            f"[{index}/{len(works)}] retryable failure; "
                            f"cooling down {cooldown:.0f}s",
                            flush=True,
                        )
                        time.sleep(cooldown)
                results.append(item)
                write_download_manifest(results, args.output_dir)
                print(f"[{index}/{len(works)}] {item.status}", flush=True)
                if index < len(works):
                    time.sleep(args.delay_seconds)
    manifest = write_download_manifest(results, args.output_dir)
    counts = {
        status: sum(item.status == status for item in results)
        for status in ("downloaded", "skipped", "failed")
    }
    print(
        f"Downloaded: {counts['downloaded']}; skipped: {counts['skipped']}; "
        f"failed: {counts['failed']}; manifest: {manifest}"
    )
    for item in results:
        if item.status == "failed":
            print(f"- {item.doi or item.title}: {item.message}")


def _print_auth_status(status: object) -> None:
    authenticated = getattr(status, "authenticated")
    print(f"authenticated: {str(authenticated).lower()}")
    print(f"url: {getattr(status, 'url')}")
    print(f"title: {getattr(status, 'title')}")
    print(f"cookies: {getattr(status, 'cookies')}")
    print(f"message: {getattr(status, 'message')}")


def _session(args: argparse.Namespace) -> None:
    login_config = _resolve_login_config(args)
    _print_auth_status(
        keepalive(
            config=login_config,
            interval_seconds=args.interval,
            once=args.once,
        )
    )


def _resolve_login_config(
    args: argparse.Namespace,
    *,
    config_attr: str = "config",
) -> LoginConfig:
    login_config = load_login_config(getattr(args, config_attr))
    overrides = {}
    if getattr(args, "browser", None):
        overrides["browser"] = args.browser
    if getattr(args, "auth_file", None):
        overrides["auth_file"] = args.auth_file.expanduser().resolve()
    if getattr(args, "url", None):
        overrides["url"] = args.url
    if getattr(args, "keep_open", None) is not None:
        overrides["keep_open"] = args.keep_open
    return replace(login_config, **overrides)


def _load_works(path: Path, *, record_ids: set[str]) -> list:
    with path.open("r", encoding="utf-8") as handle:
        first_line = next(
            (line for line in handle if line.strip()),
            "",
        )
    if not first_line:
        return []
    first_record = json.loads(first_line)
    if first_record.get("manifest_version"):
        records = read_search_manifest(path)
        if record_ids:
            records = [
                record
                for record in records
                if record["record_id"] in record_ids
            ]
        return manifest_records_to_works(records)
    if record_ids:
        raise ValueError("--record-id requires a script-generated manifest")
    return read_jsonl(path)


def _concurrency(value: str) -> int:
    workers = int(value)
    if not 1 <= workers <= 5:
        raise argparse.ArgumentTypeError("must be between 1 and 5")
    return workers


def _retryable_download_failure(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.casefold()
    return any(
        marker in lowered
        for marker in (
            "err_http_response_code_failure",
            "err_connection_timed_out",
            "err_connection_reset",
            "err_connection_closed",
            "timeout",
            "http 418",
            "status 418",
            "http 429",
            "status 429",
        )
    )


def _download_retry_cooldown(
    message: str | None,
    configured_cooldown: float,
) -> float:
    lowered = (message or "").casefold()
    if any(
        marker in lowered
        for marker in (
            "err_http_response_code_failure",
            "http 418",
            "status 418",
            "http 429",
            "status 429",
        )
    ):
        return configured_cooldown
    return min(configured_cooldown, 5.0)


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed
