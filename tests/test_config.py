from pathlib import Path

from ieee_spider.auth import load_login_config
from ieee_spider.config import load_config


def test_load_default_config() -> None:
    config = load_config()

    assert config.from_year == 2020
    assert config.to_year == 2026
    assert config.authors == []


def test_author_lookup_accepts_slug(tmp_path: Path) -> None:
    config_path = tmp_path / "authors.toml"
    config_path.write_text(
        """
from_year = 2024
to_year = 2026

[[authors]]
name = "Example Author"
slug = "example-author"
affiliation = "Example University"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)

    assert config.author_for("example-author").name == "Example Author"


def test_login_config_loads_script_friendly_defaults() -> None:
    config = load_login_config()

    assert config.browser == "edge"
    assert config.mode == "manual"
    assert config.auth_file.is_absolute()
    assert config.keepalive_interval_seconds == 240
