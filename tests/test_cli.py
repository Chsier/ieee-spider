from ieee_spider.cli import (
    _download_retry_cooldown,
    _proxy_record,
    _retryable_download_failure,
)


def test_retryable_download_failure_classifies_throttling() -> None:
    assert _retryable_download_failure(
        "Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE"
    )
    assert _retryable_download_failure("HTTP 429 Too Many Requests")
    assert not _retryable_download_failure(
        "No PDF access for this account"
    )


def test_download_retry_cooldown_uses_full_cooldown_for_throttling() -> None:
    assert _download_retry_cooldown(
        "Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE",
        60.0,
    ) == 60.0
    assert _download_retry_cooldown(
        "Page.goto: net::ERR_CONNECTION_TIMED_OUT",
        60.0,
    ) == 5.0


def test_proxy_record_parses_record_specific_proxy() -> None:
    assert _proxy_record(
        "ieee:11022699=http://127.0.0.1:7897"
    ) == (
        "ieee:11022699",
        "http://127.0.0.1:7897",
    )
