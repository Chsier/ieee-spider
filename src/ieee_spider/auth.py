from __future__ import annotations

import json
import os
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ieee_spider.config import project_root


DEFAULT_AUTH_FILE = project_root() / "data" / "auth" / "ieee-storage-state.json"
IEEE_HOME = "https://ieeexplore.ieee.org/"
NO_PROXY_ARGS = ["--no-proxy-server"]
BACKGROUND_ARGS = [
    "--window-position=-32000,-32000",
    "--window-size=1280,900",
    "--start-minimized",
]


@dataclass(slots=True)
class LoginConfig:
    url: str = IEEE_HOME
    browser: str = "edge"
    auth_file: Path = DEFAULT_AUTH_FILE
    proxy_url: str = ""
    mode: str = "manual"
    username: str = ""
    username_env: str = "IEEE_USERNAME"
    password_env: str = "IEEE_PASSWORD"
    username_selector: str = ""
    password_selector: str = ""
    remember_me_selector: str = ""
    submit_selector: str = ""
    wait_after_submit_ms: int = 1_500
    keep_open: bool = False
    keepalive_interval_seconds: int = 240


@dataclass(slots=True)
class AuthStatus:
    authenticated: bool
    url: str
    title: str
    cookies: int
    message: str


def default_login_config_path() -> Path:
    return project_root() / "config" / "login.toml"


def load_login_config(
    path: Path | str | None = None,
) -> LoginConfig:
    config_path = (
        Path(path).expanduser().resolve()
        if path
        else default_login_config_path()
    )
    payload: dict[str, object] = {}
    if config_path.exists():
        with config_path.open("rb") as handle:
            payload = tomllib.load(handle).get("login", {})
    auth_file_value = str(payload.get("auth_file", DEFAULT_AUTH_FILE))
    auth_file = Path(auth_file_value).expanduser()
    if not auth_file.is_absolute():
        auth_file = project_root() / auth_file
    mode = str(payload.get("mode", "manual")).casefold()
    if mode not in {"manual", "form"}:
        raise ValueError("login mode must be 'manual' or 'form'")
    return LoginConfig(
        url=str(payload.get("url", IEEE_HOME)),
        browser=str(payload.get("browser", "edge")).casefold(),
        auth_file=auth_file.resolve(),
        proxy_url=str(payload.get("proxy_url", "")).strip(),
        mode=mode,
        username=str(payload.get("username", "")),
        username_env=str(payload.get("username_env", "IEEE_USERNAME")),
        password_env=str(payload.get("password_env", "IEEE_PASSWORD")),
        username_selector=str(payload.get("username_selector", "")),
        password_selector=str(payload.get("password_selector", "")),
        remember_me_selector=str(payload.get("remember_me_selector", "")),
        submit_selector=str(payload.get("submit_selector", "")),
        wait_after_submit_ms=int(payload.get("wait_after_submit_ms", 1_500)),
        keep_open=bool(payload.get("keep_open", False)),
        keepalive_interval_seconds=max(
            30,
            int(payload.get("keepalive_interval_seconds", 240)),
        ),
    )


def login(
    *,
    config: LoginConfig | None = None,
) -> AuthStatus:
    from playwright.sync_api import sync_playwright

    login_config = config or load_login_config()
    auth_file = login_config.auth_file.expanduser().resolve()
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = launch_persistent_context(
            playwright,
            login_config,
            background=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(
            login_config.url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        if login_config.mode == "form":
            _fill_login_form(page, login_config)
        else:
            print("Complete the IEEE or institutional SSO sign-in in the browser.")
        print("MFA and CAPTCHA are intentionally left to the user.")
        input("Press Enter here after the authenticated IEEE page is visible... ")
        status = _wait_for_login_confirmation(
            page,
            context,
            login_config,
        )
        if login_config.keep_open:
            print("Browser kept open. Close the browser window to exit login.")
            try:
                page.wait_for_event("close", timeout=0)
            except Exception:
                pass
        context.close()
        return status


def check_auth(
    *,
    config: LoginConfig | None = None,
) -> AuthStatus:
    from playwright.sync_api import sync_playwright

    login_config = config or load_login_config()
    auth_file = login_config.auth_file.expanduser().resolve()
    if not auth_file.exists():
        raise FileNotFoundError(
            f"Auth state not found: {auth_file}. Run the login command first."
        )
    with sync_playwright() as playwright:
        context = launch_persistent_context(
            playwright,
            login_config,
        )
        page = context.pages[0] if context.pages else context.new_page()
        status = refresh_session(page, context, login_config)
        if login_config.keep_open:
            print("Browser kept open. Close the browser window to exit auth-check.")
            try:
                page.wait_for_event("close", timeout=0)
            except Exception:
                pass
        context.close()
        return status


def keepalive(
    *,
    config: LoginConfig | None = None,
    interval_seconds: int | None = None,
    once: bool = False,
) -> AuthStatus:
    from playwright.sync_api import sync_playwright

    login_config = config or load_login_config()
    interval = max(
        30,
        interval_seconds or login_config.keepalive_interval_seconds,
    )
    auth_file = login_config.auth_file.expanduser().resolve()
    if not auth_file.exists():
        raise FileNotFoundError(
            f"Auth state not found: {auth_file}. Run the login command first."
        )

    with sync_playwright() as playwright:
        context = launch_persistent_context(playwright, login_config)
        page = context.pages[0] if context.pages else context.new_page()
        status = refresh_session(page, context, login_config)
        try:
            while True:
                if not status.authenticated:
                    context.close()
                    raise RuntimeError(
                        "IEEE session expired. Run 'ieee-spider login' "
                        "in a separate terminal."
                    )
                now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
                print(
                    f"[{now}] authenticated={str(status.authenticated).lower()} "
                    f"cookies={status.cookies} message={status.message}"
                )
                if once:
                    context.close()
                    return status
                time.sleep(interval)
                status = refresh_session(page, context, login_config)
        except KeyboardInterrupt:
            context.close()
            return status


def refresh_session(
    page: object,
    context: object,
    config: LoginConfig,
    storage_state: dict[str, object] | None = None,
) -> AuthStatus:
    response = None
    title = ""
    text = ""
    try:
        response = page.goto(
            config.url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        title = page.title()
        text = page.locator("body").inner_text(timeout=30_000).casefold()
    except Exception:
        title = page.title() if page else ""
    state = context.storage_state()
    authenticated, message = _evaluate_auth(
        state,
        http_status=response.status if response else None,
        title=title,
        text=text,
    )
    if authenticated:
        context.storage_state(path=str(config.auth_file))
    return AuthStatus(
        authenticated=authenticated,
        url=page.url,
        title=title,
        cookies=len(state.get("cookies", [])),
        message=message,
    )


def launch_persistent_context(
    playwright: object,
    config: LoginConfig,
    *,
    background: bool = True,
) -> object:
    args: list[str] = []
    if not config.proxy_url:
        args.extend(NO_PROXY_ARGS)
    if background:
        args.extend(BACKGROUND_ARGS)
    try:
        options = {
            "user_data_dir": str(browser_profile_dir(config.auth_file)),
            "channel": _browser_channel(config.browser),
            "headless": False,
            "accept_downloads": True,
            "args": args,
        }
        if config.proxy_url:
            options["proxy"] = {"server": config.proxy_url}
        context = playwright.chromium.launch_persistent_context(
            **options,
        )
        _apply_saved_storage_state(context, config.auth_file)
        return context
    except Exception as exc:
        if "Target page, context or browser has been closed" in str(exc):
            raise RuntimeError(
                "The background Edge profile is already in use. "
                "Only one ieee-spider browser process may run at a time; "
                "stop the existing session command first."
            ) from exc
        raise


def browser_profile_dir(auth_file: Path) -> Path:
    return auth_file.expanduser().resolve().parent / "browser-profile"


def _apply_saved_storage_state(context: object, auth_file: Path) -> None:
    if not auth_file.exists():
        return
    state = json.loads(auth_file.read_text(encoding="utf-8"))
    cookies = state.get("cookies")
    if isinstance(cookies, list) and cookies:
        context.add_cookies(cookies)
    origins = state.get("origins")
    if not isinstance(origins, list):
        return
    for origin in origins:
        if not isinstance(origin, dict):
            continue
        origin_url = origin.get("origin")
        entries = origin.get("localStorage")
        if not isinstance(origin_url, str) or not isinstance(entries, list):
            continue
        context.add_init_script(
            script=(
                "(() => {"
                f"if (location.origin !== {json.dumps(origin_url)}) return;"
                f"const entries = {json.dumps(entries)};"
                "for (const entry of entries) {"
                "localStorage.setItem(entry.name, entry.value);"
                "}"
                "})()"
            )
        )


def _browser_channel(browser: str) -> str | None:
    values = {
        "edge": "msedge",
        "chrome": "chrome",
        "chromium": None,
    }
    if browser not in values:
        raise ValueError(f"Unsupported browser: {browser}")
    return values[browser]


def _fill_login_form(page: object, config: LoginConfig) -> None:
    username = config.username or os.getenv(config.username_env, "")
    password = os.getenv(config.password_env, "")
    missing = [
        name
        for name, value in (
            ("username", username),
            ("password", password),
            ("username_selector", config.username_selector),
            ("password_selector", config.password_selector),
            ("submit_selector", config.submit_selector),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Form login is missing configuration: " + ", ".join(missing)
        )
    page.locator(config.username_selector).fill(username)
    page.locator(config.password_selector).fill(password)
    if config.remember_me_selector:
        remember = page.locator(config.remember_me_selector)
        if remember.count() > 0 and not remember.is_checked():
            remember.check()
    page.locator(config.submit_selector).click()
    page.wait_for_timeout(config.wait_after_submit_ms)


def _evaluate_auth(
    storage_state: dict[str, object],
    *,
    http_status: int | None,
    title: str,
    text: str,
) -> tuple[bool, str]:
    cookies = {
        str(cookie.get("name")): str(cookie.get("value") or "")
        for cookie in storage_state.get("cookies", [])
        if isinstance(cookie, dict)
    }
    has_user_cookie = bool(cookies.get("xpluserinfo"))
    has_entitlement_cookie = any(
        bool(cookies.get(name))
        for name in ("ERIGHTS", "SDR1")
    )
    has_generic_session = bool(cookies.get("WLSESSION"))
    positive = any(
        marker in text
        for marker in ("sign out", "account settings")
    )
    negative = "personal sign in" in text or "institutional sign in" in text
    blocked = (
        http_status in {403, 418, 429}
        or "unable to load page" in title.casefold()
    )

    if blocked and (has_user_cookie or has_entitlement_cookie):
        return (
            True,
            "Saved IEEE cookies are present; the live page was blocked by "
            f"anti-automation HTTP {http_status or 'unknown'}.",
        )
    if negative and not positive:
        return (
            False,
            "IEEE live page shows a sign-in prompt; saved session cookies "
            "are stale.",
        )
    if positive:
        return True, "Session is confirmed by the live IEEE page."
    if has_user_cookie:
        return (
            False,
            "Saved IEEE user session cookie is present, but the live page "
            "did not confirm authentication.",
        )
    if has_entitlement_cookie:
        return (
            False,
            "Saved IEEE entitlement cookie is present, but the live page "
            "did not confirm authentication.",
        )
    if has_generic_session:
        return (
            False,
            "Only a generic WLSESSION cookie is present; "
            "institutional sign-in was not completed.",
        )
    return False, "No authenticated IEEE session cookie was found."


def _wait_for_login_confirmation(
    page: object,
    context: object,
    config: LoginConfig,
    *,
    timeout_seconds: int = 45,
) -> AuthStatus:
    deadline = time.monotonic() + timeout_seconds
    status = refresh_session(page, context, config)
    while not status.authenticated and time.monotonic() < deadline:
        time.sleep(2)
        status = refresh_session(page, context, config)
    return status
