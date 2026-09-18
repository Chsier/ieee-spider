"""Build the source-free IEEE Spider Windows runtime with Nuitka."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist" / "nuitka"
SKILL_RUNTIME_DIR = ROOT / "skill" / "ieee-spider" / "bin"
EXECUTABLE_NAME = "ieee-spider.exe"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-copy-to-skill", action="store_true")
    args = parser.parse_args(argv)

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--onefile",
        "--windows-console-mode=force",
        "--include-package=ieee_spider",
        "--include-package=playwright",
        f"--output-dir={DIST_DIR}",
        f"--output-filename={EXECUTABLE_NAME}",
        f"--company-name=IEEE Spider",
        f"--product-name=IEEE Spider",
        f"--file-version={_project_version()}",
        f"--product-version={_project_version()}",
        "--remove-output",
    ]
    if args.yes:
        command.append("--assume-yes-for-downloads")
    command.append(str(ROOT / "start_ieee_spider.py"))

    completed = subprocess.run(command, cwd=ROOT, check=False)
    executable = DIST_DIR / EXECUTABLE_NAME
    if completed.returncode != 0 or not executable.is_file():
        print(
            f"error: Nuitka build failed; expected {executable}",
            file=sys.stderr,
        )
        return completed.returncode or 1

    _verify_runtime(executable)
    digest = _sha256(executable)
    payload = {
        "schema": "ieee-spider/runtime-package/v1",
        "runtime_version": _project_version(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "nuitka_version": importlib.metadata.version("nuitka"),
        "playwright_version": importlib.metadata.version("playwright"),
        "executable": {
            "filename": executable.name,
            "sha256": digest,
            "size_bytes": executable.stat().st_size,
        },
    }

    if not args.no_copy_to_skill:
        SKILL_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        target = SKILL_RUNTIME_DIR / EXECUTABLE_NAME
        shutil.copy2(executable, target)
        (SKILL_RUNTIME_DIR / "runtime-manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        payload["skill_executable"] = str(target)
        payload["skill_sha256"] = _sha256(target)

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _verify_runtime(executable: Path) -> None:
    completed = subprocess.run(
        [str(executable), "--version"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"runtime verification failed: {completed.stderr.strip()}"
        )


def _project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        payload = tomllib.load(stream)
    return str(payload["project"]["version"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
