# Command Reference

The examples assume that commands run from the repository root.

## Human-Only Commands

Do not run these unless the user explicitly says a human is present and ready:

```powershell
uv run ieee-spider login
uv run ieee-spider session
```

`login` is the only command that opens visible Edge. It waits for SSO/MFA.
`session` is a long-running background keepalive controlled by a human because
it owns the single browser profile for its entire lifetime.

After the human presses Enter, `login` rechecks the live IEEE page and reports
the actual authentication result instead of assuming success. A generic
`WLSESSION` cookie does not represent a completed institutional login.
Saved cookies and localStorage are injected into subsequent persistent
browser launches. A failed `auth-check` must not overwrite the saved session
file.

At least one human `login` is required in the current implementation before any
Agent task. Having
`config/login.toml` or credentials configured does not satisfy this gate.

## Agent Session Check

```powershell
uv run ieee-spider auth-check
```

Continue only when `authenticated: true`. The command may use the saved
`xpluserinfo`, `ERIGHTS`, `WLSESSION`, and IdP cookies when IEEE blocks
automation with HTTP 418.

## Generic Search

Generic search prefers the authenticated IEEE Xplore browser path. There is no
metadata-provider fallback in the maintained CLI.

```powershell
uv run ieee-spider search `
  --query "low altitude networks" `
  --from-year 2025 `
  --to-year 2026 `
  --max-results 25 `
  --output-dir data\jobs\low-altitude
```

Supported filters:

- `--query`: free-text IEEE query
- `--title`: document title
- `--author`: author name
- `--doi`: IEEE DOI
- `--venue`: publication title
- `--from-year`, `--to-year`: local year filtering
- `--open-access`: only results labeled open access
- `--max-results`: result count, default `25`

The Agent may combine filters. IEEE Xplore query fields are generated
deterministically by the CLI.

## Optional Author Shortcut

This is only for the five authors preconfigured in `config/authors.toml`.
It also uses authenticated IEEE Xplore and does not fall back.

```powershell
uv run ieee-spider fetch --max-results 200
uv run ieee-spider fetch --author nan-cheng
```

## Download

Download support is intentionally basic. It downloads links exposed by the
current result page or authorized document page. IEEE `stamp.jsp` previews are
resolved to their nested PDF URL using the authenticated browser context.
Dynamic entitlements and page-specific scraping beyond that are Agent-extension
work, not guaranteed CLI behavior.

Public open-access first:

```powershell
uv run ieee-spider download `
  --input data\jobs\low-altitude\manifest.jsonl `
  --mode oa `
  --limit 5 `
  --workers 3
```

Authorized session:

```powershell
uv run ieee-spider download `
  --input data\jobs\low-altitude\manifest.jsonl `
  --mode authorized `
  --limit 5 `
  --delay-seconds 4 `
  --throttle-cooldown-seconds 60 `
  --max-attempts 2
```

Open access plus authorized access:

```powershell
uv run ieee-spider download `
  --input data\jobs\low-altitude\manifest.jsonl `
  --mode both `
  --limit 5 `
  --workers 3
```

`--workers` is limited to `1-5`; default is `3`. Authorized browser downloads
remain serial. Their defaults are a 4-second delay between records, a
60-second cooldown after a throttling failure, and at most 2 attempts per
record. These delays protect the single authenticated browser session and may
be lengthened when IEEE reports throttling.

`--workers` applies only to open-access HTTP PDF downloads. Do not use it for
authenticated search or detail-page enrichment. There is no supported
multi-page or multi-context mode for the IEEE browser profile.

Authorized downloads resolve `stamp.jsp` and the nested PDF URL with the
authenticated request context. They do not navigate the off-screen browser into
the PDF viewer. Download manifests merge by `record_id` across invocations, so
partial or resume batches retain previous records and never require hand
editing.

Select specific records:

```powershell
uv run ieee-spider download `
  --input data\jobs\low-altitude\manifest.jsonl `
  --record-id "ieee:11447568" `
  --mode authorized
```

Preview without downloading:

```powershell
uv run ieee-spider download `
  --input data\jobs\low-altitude\manifest.jsonl `
  --mode both `
  --limit 5 `
  --dry-run
```

## Exit Behavior

- Exit code `0`: command completed.
- Exit code `2`: validation, authentication, or runtime error.
- Missing or invalid browser session: stop and request human `login`.
- Never retry an authentication failure through OpenAlex, Crossref, a proxy,
  or a headless substitute.

## Rate-Limited Abstract Enrichment

Prefer the serial CLI command over writing a new browser loop for each request:

```powershell
uv run ieee-spider enrich `
  --input data\jobs\low-altitude\manifest.jsonl `
  --output data\jobs\low-altitude\abstracts.jsonl
```

The command is serial, resumes completed records, and writes a separate
fixed-schema JSONL file. It defaults to a 4-second delay between details, a
20-second cooldown after every 5 processed records, and a 60-second cooldown
after throttling errors. Use `--dry-run` to inspect pending records before
starting browser work. See
[batch-operations.md](batch-operations.md) for lock and retry handling.

The compatibility wrapper at
`scripts\enrich_abstracts.py` delegates to the same CLI command. New workflows
should normally call `ieee-spider enrich` directly. If the built-in extraction
no longer matches an IEEE page, a minimal targeted implementation change is
allowed while preserving serial access and the enrichment output contract.

## Paper Summary DOCX

Paper summary deliverables must be `.docx`, even when an intermediate Markdown
file is used during drafting. Convert the intermediate summary with:

```powershell
pwsh "skill\ieee-spider\scripts\render_summary_docx.ps1" `
  -InputMarkdown data\jobs\per-author\<author>\summaries-50.md `
  -OutputDocx data\jobs\per-author\<author>\summaries-50.docx
```

Validate the generated DOCX with the `docx` skill validator, then remove the
intermediate Markdown file when the DOCX is the requested final artifact.

## Citation and Venue Statistics

Build the fixed statistics report after serial enrichment:

```powershell
uv run python `
  "skill\ieee-spider\scripts\build_paper_statistics.py" `
  --manifest data\jobs\<job-name>\manifest.jsonl `
  --abstracts data\jobs\<job-name>\abstracts.jsonl `
  --output data\jobs\<job-name>\statistics.json `
  --author "Author Name"
```

The command validates one-to-one `record_id` coverage and writes citation
coverage, per-venue metrics, and Top Cited paper rankings. Prefer fixing the
generator over hand-editing or manually rebuilding this JSON schema.

## Upgrade an Existing Summary DOCX

When a summary DOCX already exists but lacks citation and venue statistics,
preserve its existing paper summaries and rebuild only the report metadata:

```powershell
uv run python `
  "skill\ieee-spider\scripts\upgrade_summary_docx.py" `
  --input-docx data\jobs\<job-name>\summaries-50.docx `
  --statistics data\jobs\<job-name>\statistics.json `
  --output-markdown data\jobs\<job-name>\summaries-50.md
```

Then render and validate the Markdown as a new DOCX, and remove the
intermediate Markdown.

## Per-Author Collection

Prefer `select_author_papers.py` when the user requests a fixed number of
papers per author:

```powershell
uv run python `
  "skill\ieee-spider\scripts\select_author_papers.py" `
  --input data\jobs\<collection>\_raw\manifest.jsonl `
  --output-dir data\jobs\<collection> `
  --author "Author One" `
  --author "Author Two" `
  --limit 50
```

The script writes exact-author manifests, statistics, and a deduplicated union
manifest. See [author-collection.md](author-collection.md) for the complete
workflow and recommended structure.

## Background Session

All non-login commands use one off-screen Edge process. It is not terminal
input-driven and does not pop a window. The process is tied to its terminal:
closing the terminal stops keepalive.

```powershell
uv run ieee-spider session
uv run ieee-spider session --once
```

Authentication failure exits with an error. It never triggers login.

One persistent Edge profile supports one process only. Do not keep `session`
running while an Agent starts `search` or `download`; stop `session` first and
restart it after the Agent job finishes.

Agents should normally use `auth-check` rather than `session`. `session`
exists only for human-controlled idle keepalive.
