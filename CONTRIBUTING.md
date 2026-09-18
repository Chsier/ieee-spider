# Contributing

## Development Setup

```powershell
uv sync --python 3.12.12
uv run pytest -q
```

## Change Requirements

- Preserve the fixed search, enrichment, statistics, and download manifest
  schemas unless the change explicitly versions and migrates them.
- Keep authenticated browser operations serial and one process per profile.
- Do not add proxy support for bypassing access controls.
- Do not add metadata-source fallback when IEEE Xplore is unavailable.
- Keep parser failures explicit; do not fabricate PDF URLs or results.
- Add focused tests for authentication, parsing, retry, and schema changes.
- Remove generated `data/`, `downloads/`, browser profiles, and local
  configuration before submitting a pull request.

## Pull Requests

A pull request should include:

1. the behavioral problem being fixed;
2. the smallest implementation change;
3. tests proving the new behavior;
4. any manifest or CLI compatibility impact.

Run `uv run pytest -q` before opening the pull request.
