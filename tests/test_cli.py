from ieee_spider.cli import (
    _download_retry_cooldown,
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
