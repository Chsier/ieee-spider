import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ieee_spider.auth import LoginConfig, _evaluate_auth, launch_persistent_context


def test_auth_check_trusts_saved_session_when_page_is_blocked() -> None:
    state = {
        "cookies": [
            {"name": "xpluserinfo", "value": "saved-user"},
            {"name": "ERIGHTS", "value": "saved-entitlement"},
        ]
    }

    authenticated, message = _evaluate_auth(
        state,
        http_status=418,
        title="IEEE Xplore - Unable to Load Page",
        text="",
    )

    assert authenticated is True
    assert "HTTP 418" in message


def test_auth_check_rejects_sign_in_page_without_session_cookies() -> None:
    authenticated, message = _evaluate_auth(
        {"cookies": []},
        http_status=200,
        title="IEEE Xplore",
        text="personal sign in institutional sign in",
    )

    assert authenticated is False
    assert "sign-in" in message


def test_auth_check_does_not_treat_my_settings_as_sign_in() -> None:
    state = {"cookies": [{"name": "WLSESSION", "value": "generic"}]}

    authenticated, message = _evaluate_auth(
        state,
        http_status=200,
        title="IEEE Xplore",
        text="my settings personal sign in institutional sign in",
    )

    assert authenticated is False
    assert "sign-in" in message


def test_auth_check_trusts_user_cookie_when_hidden_sign_in_markup_exists() -> None:
    state = {
        "cookies": [
            {"name": "xpluserinfo", "value": "saved-user"},
            {"name": "ERIGHTS", "value": "saved-entitlement"},
        ]
    }

    authenticated, message = _evaluate_auth(
        state,
        http_status=200,
        title="IEEE Xplore",
        text="personal sign in sign out",
    )

    assert authenticated is True
    assert "live IEEE page" in message


def test_auth_check_requires_live_confirmation_for_unblocked_cookie_only_session() -> None:
    state = {
        "cookies": [
            {"name": "xpluserinfo", "value": "saved-user"},
            {"name": "ERIGHTS", "value": "saved-entitlement"},
        ]
    }

    authenticated, message = _evaluate_auth(
        state,
        http_status=200,
        title="IEEE Xplore",
        text="",
    )

    assert authenticated is False
    assert "did not confirm" in message


def test_auth_check_rejects_stale_cookies_when_live_page_requires_sign_in() -> None:
    state = {
        "cookies": [
            {"name": "xpluserinfo", "value": "saved-user"},
            {"name": "ERIGHTS", "value": "saved-entitlement"},
            {"name": "SDR1", "value": "saved-institution"},
        ]
    }

    authenticated, message = _evaluate_auth(
        state,
        http_status=200,
        title="IEEE Xplore",
        text="personal sign in institutional sign in",
    )

    assert authenticated is False
    assert "stale" in message


def test_auth_check_rejects_generic_session_without_user_cookie() -> None:
    state = {"cookies": [{"name": "WLSESSION", "value": "generic"}]}

    authenticated, message = _evaluate_auth(
        state,
        http_status=200,
        title="IEEE Xplore",
        text="",
    )

    assert authenticated is False
    assert "institutional sign-in" in message


def test_profile_lock_error_is_actionable() -> None:
    class Chromium:
        @staticmethod
        def launch_persistent_context(**_: object) -> object:
            raise RuntimeError(
                "Target page, context or browser has been closed"
            )

    playwright = SimpleNamespace(chromium=Chromium())

    with pytest.raises(RuntimeError, match="already in use"):
        launch_persistent_context(playwright, LoginConfig())


def test_persistent_context_loads_saved_storage_state(tmp_path: Path) -> None:
    auth_file = tmp_path / "state.json"
    auth_file.write_text(
        json.dumps(
            {
                "cookies": [{"name": "session", "value": "saved"}],
                "origins": [
                    {
                        "origin": "https://example.org",
                        "localStorage": [
                            {"name": "key", "value": "value"}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class Context:
        @staticmethod
        def add_cookies(cookies: object) -> None:
            captured["cookies"] = cookies

        @staticmethod
        def add_init_script(*, script: str) -> None:
            captured["script"] = script

    class Chromium:
        @staticmethod
        def launch_persistent_context(**kwargs: object) -> object:
            captured.update(kwargs)
            return Context()

    playwright = SimpleNamespace(chromium=Chromium())

    launch_persistent_context(
        playwright,
        LoginConfig(auth_file=auth_file),
    )

    assert captured["cookies"] == [{"name": "session", "value": "saved"}]
    assert "https://example.org" in str(captured["script"])


def test_persistent_context_uses_explicit_proxy_without_direct_flag(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class Context:
        @staticmethod
        def add_cookies(cookies: object) -> None:
            return None

    class Chromium:
        @staticmethod
        def launch_persistent_context(**kwargs: object) -> object:
            captured.update(kwargs)
            return Context()

    playwright = SimpleNamespace(chromium=Chromium())

    launch_persistent_context(
        playwright,
        LoginConfig(
            auth_file=tmp_path / "state.json",
            proxy_url="http://127.0.0.1:7897",
        ),
    )

    assert captured["proxy"] == {"server": "http://127.0.0.1:7897"}
    assert "--no-proxy-server" not in captured["args"]
