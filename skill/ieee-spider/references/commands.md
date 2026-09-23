# Command Reference

The examples assume that commands run from the repository root.

For the self-contained installed skill:

```powershell
$skillRoot = '<path containing SKILL.md>'
$ieeeSpider = Join-Path $skillRoot 'scripts\ieee-spider.ps1'
```

Use `& $ieeeSpider ...` for all CLI examples below. The wrapper locates the
embedded executable and uses `$HOME\.ieee-spider` unless `IEEE_SPIDER_HOME` is
set.

## Human-Only Commands

Do not run these unless the user explicitly says a human is present and ready:

```powershell
& $ieeeSpider login
& $ieeeSpider session
```

`login` is the only command that opens visible Edge. It waits for SSO/MFA.
`session` is a long-running background keepalive controlled by a human because
it owns the single browser profile for its entire lifetime.

After the human presses Enter, `login` rechecks the live IEEE page and reports
the actual authentication result instead of assuming success. It waits for
live confirmation rather than accepting stale saved cookies. A generic
`WLSESSION` cookie does not represent a completed institutional login, and
saved `xpluserinfo`, `ERIGHTS`, or `SDR1` values do not override a live
sign-in page. Saved cookies and localStorage are injected into subsequent
persistent browser launches. A failed `auth-check` must not overwrite the
saved session file.

To reset stale authentication state safely, stop all browser commands and move
`data\auth` to a timestamped quarantine directory. Run `auth-check` before
logging in and require `Auth state not found`; then log in and verify two
separate `auth-check` runs.

At least one human `login` is required in the current implementation before any
Agent task. Having
`config/login.toml` or credentials configured does not satisfy this gate.

## Agent Session Check

```powershell
& $ieeeSpider auth-check
```

Continue only when `authenticated: true`. The command may use the saved
`xpluserinfo`, `ERIGHTS`, `WLSESSION`, and IdP cookies only when IEEE blocks
the live check with HTTP 403, 418, or 429. For HTTP 200, the live page must
confirm the session and must not show `Personal Sign In` or
`Institutional Sign In`.

## Generic Search

Generic search prefers the authenticated IEEE Xplore browser path. There is no
metadata-provider fallback in the maintained CLI.

```powershell
& $ieeeSpider search `
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
& $ieeeSpider fetch --max-results 200
& $ieeeSpider fetch --author example-author
```

## Download

Download support is intentionally basic. It downloads links exposed by the
current result page or authorized document page. IEEE `stamp.jsp` previews are
resolved to their nested PDF URL using the authenticated browser context.
Dynamic entitlements and page-specific scraping beyond that are Agent-extension
work, not guaranteed CLI behavior.

Public open-access first:

```powershell
& $ieeeSpider download `
  --input data\jobs\low-altitude\manifest.jsonl `
  --mode oa `
  --limit 5 `
  --workers 3
```

Authorized session:

```powershell
& $ieeeSpider download `
  --input data\jobs\low-altitude\manifest.jsonl `
  --mode authorized `
  --limit 5 `
  --delay-seconds 4 `
  --throttle-cooldown-seconds 60 `
  --max-attempts 2
```

Open access plus authorized access:

```powershell
& $ieeeSpider download `
  --input data\jobs\low-altitude\manifest.jsonl `
  --mode both `
  --limit 5 `
  --workers 3
```

`--workers` is limited to `1-5`; default is `3`. Authorized browser downloads
remain serial. Their defaults are a 4-second delay between records, a
60-second cooldown after a throttling failure, and at most 2 attempts per
record. PDF transfer timeout is 180 seconds to accommodate large authorized
files. These delays protect the single authenticated browser session and may
be lengthened when IEEE reports throttling.

`--workers` applies only to open-access HTTP PDF downloads. Do not use it for
authenticated search or detail-page enrichment. There is no supported
multi-page or multi-context mode for the IEEE browser profile.

Authorized downloads resolve `stamp.jsp` and the nested PDF URL with the
authenticated request context. They do not navigate the off-screen browser into
the PDF viewer. Download manifests merge by `record_id` across invocations, so
partial or resume batches retain previous records and never require hand
editing.

Proxy routing is explicit per record and direct by default:

```powershell
& $ieeeSpider download `
  --input data\jobs\low-altitude\manifest.jsonl `
  --record-id "ieee:11022699" `
  --mode authorized `
  --proxy-record "ieee:11022699=http://127.0.0.1:7897"
```

`--proxy-record` may be repeated. Records without a rule remain direct.
Login, search, enrichment, auth-check, and session commands do not consume
these rules. If an explicitly proxied request is rejected by IEEE, retry that
record without the rule instead of routing authentication through the proxy.

If a batch starts returning `No PDF access for this account` immediately
across many records, stop instead of continuing. Run `auth-check`; a stale
session can preserve old authentication cookies while IEEE has already
invalidated access. Resume only after a new live-confirmed login check.

Select specific records:

```powershell
& $ieeeSpider download `
  --input data\jobs\low-altitude\manifest.jsonl `
  --record-id "ieee:11447568" `
  --mode authorized
```

Preview without downloading:

```powershell
& $ieeeSpider download `
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
  or a headless substitute. A valid per-record PDF proxy rule is not an
  authentication workaround.

## Rate-Limited Abstract Enrichment

Prefer the serial CLI command over writing a new browser loop for each request:

```powershell
& $ieeeSpider enrich `
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
& $ieeeSpider session
& $ieeeSpider session --once
```

Authentication failure exits with an error. It never triggers login.

One persistent Edge profile supports one process only. Do not keep `session`
running while an Agent starts `search` or `download`; stop `session` first and
restart it after the Agent job finishes.

Agents should normally use `auth-check` rather than `session`. `session`
exists only for human-controlled idle keepalive.
