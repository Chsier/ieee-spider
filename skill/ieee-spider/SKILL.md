---
name: ieee-spider
description: Maintain an authenticated IEEE Xplore browser channel and provide basic searches, fixed manifests, serial abstract/citation enrichment, reusable venue statistics, and best-effort authorized or open-access PDF downloads. Use when an Agent needs IEEE access after human login; complex dynamic page scraping remains Agent work. Never use metadata-source fallback or proxies.
---

# IEEE Spider

This skill is self-contained. Use the embedded Windows runtime unless you are
developing the source repository:

```powershell
$skillRoot = '<path containing this SKILL.md>'
$ieeeSpider = Join-Path $skillRoot 'scripts\ieee-spider.ps1'
```

The wrapper locates `bin\ieee-spider.exe`, creates the runtime workspace, and
forwards all CLI arguments. The default workspace is `$HOME\.ieee-spider`.
Set `IEEE_SPIDER_HOME` before invoking the wrapper to use a different
persistent workspace.

If `bin\ieee-spider.exe` is absent in a development checkout, use
`uv run ieee-spider` as the fallback.

The Agent controls search, manifest generation, downloading, retries, and
reporting. A human controls visible login, institutional SSO, MFA, and CAPTCHA.

## Summary Deliverables

When a task asks for paper summaries, the final deliverable must be Microsoft
Word `.docx`. Markdown may be used only as an intermediate working format and
must not be left as the final summary file. Prefer generating DOCX with
`scripts\render_summary_docx.ps1` and validating it with the `docx` skill
validator. An alternative local renderer is acceptable when needed, provided
the generated document is still validated.

Prefer generating statistics with `scripts\build_paper_statistics.py`. If its
inputs or schema do not fit a valid workflow, make a minimal change to that
script or an equivalent reusable generator. Statistics must not be assembled
by hand and must include the IEEE venue, citation count, patent citations,
full-text views, per-venue aggregates, citation coverage, and a Top Cited
ranking.

For an existing DOCX summary that predates citation metrics, prefer preserving
its paper-by-paper Chinese summaries and upgrading it with
`scripts\upgrade_summary_docx.py`. The script adds the new statistics tables
and appends citation/full-text-view fields to each paper metadata line.

## Author Collection Branch

When the user asks for a specified number of high-quality papers for one or
more named authors, prefer the per-author collection workflow over a single
generic query. It supports exact author matching, per-author quotas, year
fallback, journal/early-access filtering, venue-tier ranking, deduplicated
abstract fetching, fixed manifests, citation-aware venue statistics, and DOCX
summaries.

Read [references/author-collection.md](references/author-collection.md) and
prefer `scripts\select_author_papers.py` for this branch.

That reference also records the observed per-author library layout and a soft
method for extracting red-marked papers from `summaries-<N>.docx`.

When asked what the skill supports, explicitly mention the per-author
collection workflow, not only generic search and download.

## Scope

This skill provides a stable authenticated channel and basic commands, not a
complete implementation of every IEEE page workflow. Search-result parsing,
abstract enrichment, and download-link extraction are intentionally limited.
If IEEE changes a dynamic detail page, an Agent may compose additional scraping
logic in the project while preserving the login, single-process, no-proxy,
serial-detail, and fixed-manifest contracts.

The documented commands, selectors, scripts, and browser flow are strong
defaults, not a requirement to keep using a method that no longer works. If a
recommended method fails, inspect the current project and IEEE page, then make
the smallest effective change to the implementation or execution path. Keep
the boundaries below intact.

## First-Use Gate

The browser profile must have been authenticated by a human at least once. If
`data\auth\ieee-storage-state.json` or the persistent browser profile does not
exist, stop and request:

```powershell
& $ieeeSpider login
```

The Agent must never create the session, fill credentials, handle MFA, or
infer permission from the presence of account configuration alone.

A generic `WLSESSION` cookie is not sufficient proof of an institutional
login. Continue only when `auth-check` reports `authenticated: true` and the
live IEEE page does not still show `Personal Sign In` or
`Institutional Sign In`.

Saved `xpluserinfo`, `ERIGHTS`, or `SDR1` cookies are also not sufficient by
themselves. They can remain in storage after IEEE invalidates the server-side
session. For a normal HTTP 200 page, require live confirmation such as
`Sign Out` or account settings. If the live page shows a sign-in prompt, treat
the session as expired even when those cookies are present. The saved-cookie
fallback is valid only when IEEE blocks the live check with HTTP 403, 418, or
429.

## Operating Boundaries and Defaults

### Preserve These Boundaries

- A human completes visible login, institutional SSO, MFA, and CAPTCHA. The
  Agent does not create the session, fill credentials, or handle MFA.
- Keep authenticated collection inside IEEE Xplore. Do not substitute
  OpenAlex, Crossref, or another metadata source.
- Never add or enable an HTTP proxy.
- Keep authenticated browser work serial unless a replacement implementation
  has been tested to provide equivalent throttling and profile-lock safety.
- Do not hand-edit generated search manifests or download manifests. Change
  the generating code instead.
- Stop and request a human login when authentication is actually lost.

### Preferred Implementation

These defaults reflect methods that currently work reliably. They may be
replaced by a minimal, tested alternative when IEEE or the local environment
changes.

- Prefer the embedded runtime through `scripts\ieee-spider.ps1`; use
  `uv run ieee-spider` only when developing from source.
- Prefer keeping `login` and the long-running `session` command
  human-controlled.
- Prefer one off-screen background Edge process whose lifetime is tied to its
  terminal command.
- Prefer one browser process using the persistent profile at a time. Avoid
  running `session` and `search`/`download` concurrently.
- Prefer serial authenticated search, detail-page enrichment, and authorized
  downloads. Multi-worker execution defaults to open-access PDF downloads and
  is capped at `--workers 5`.
- Authorized downloads default to a 4-second delay between records, a
  60-second cooldown after throttling, and at most 2 attempts per record.
  Preserve these defaults unless testing demonstrates a safer rate.
- If the profile is reported in use, diagnose the owner before changing
  strategy. Wait for a transient Agent command to exit. If a human-controlled
  `session` owns the profile, ask the human to stop it.
- A rapid detail-page batch may trigger `ERR_HTTP_RESPONSE_CODE_FAILURE` or
  HTTP 418 while `auth-check` still reports an authenticated session. Treat
  this as site throttling and preserve the established cooldown/resume
  behavior unless testing supports a safer adaptation.
- Prefer bounded downloads. Start with `--limit 5` unless the user specifies a
  different amount.

If the CLI, selector, script, or page flow in this skill stops matching IEEE's
current behavior, do not treat that mismatch as a hard stop. Inspect the page
or code, make the smallest local change, test it, and document the change in
the task output. The JSONL/manifest/statistics contracts may evolve, but they
must remain script-generated and internally consistent.

## Preferred Workflow

1. Check the human-managed session:

   ```powershell
   & $ieeeSpider auth-check
   ```

2. Continue only when the output contains `authenticated: true`.

   After a new human login, run `auth-check` again in a separate process
   before starting collection. Both checks must report `authenticated: true`.

3. Run a generic authenticated Xplore search:

   ```powershell
   & $ieeeSpider search `
     --query "<query>" `
     --from-year <year> `
     --to-year <year> `
     --max-results 25 `
     --output-dir data\jobs\<job-name>
   ```

4. Prefer `data\jobs\<job-name>\manifest.jsonl` as the authoritative result
   list. If the built-in parser cannot represent a needed IEEE result, add the
   smallest targeted extraction and fold it back into the fixed script output
   contract instead of maintaining ad-hoc notes.

5. For abstract or detail-page enrichment, prefer the serial rate-limited
   helper described in [references/batch-operations.md](references/batch-operations.md):

   ```powershell
   & $ieeeSpider enrich `
     --input data\jobs\<job-name>\manifest.jsonl `
     --output data\jobs\<job-name>\abstracts.jsonl
   ```

   Keep the fixed manifest unchanged and write enrichment to a separate
   script-generated JSONL file. Detail enrichment records must include
   `citation_count`, `patent_citation_count`, `full_text_views`, and
   `citation_status`.

6. Build the fixed statistics report from the manifest and enrichment output:

   ```powershell
   uv run python `
     "skill\ieee-spider\scripts\build_paper_statistics.py" `
     --manifest data\jobs\<job-name>\manifest.jsonl `
     --abstracts data\jobs\<job-name>\abstracts.jsonl `
     --output data\jobs\<job-name>\statistics.json `
     --author "<author>"
   ```

7. Download selected records:

   ```powershell
  & $ieeeSpider download `
    --input data\jobs\<job-name>\manifest.jsonl `
    --mode both `
    --limit 5 `
    --workers 3 `
    --delay-seconds 4 `
    --throttle-cooldown-seconds 60 `
    --max-attempts 2
  ```

8. Report the counts and failed records from
   `downloads\download_manifest.jsonl`.

If an authorized download unexpectedly reports `No PDF access for this
account` after a successful session check, stop the batch. Re-run
`auth-check`; if it is false or the live page shows a sign-in prompt, request
another human login. Do not classify stale-session failures as a permanent
entitlement result and do not retry the full batch.

`download` is best-effort for links exposed by the basic page parser. For IEEE
records it follows the standard search-result `stamp.jsp` link, resolves the
nested PDF `iframe`, and reuses the authenticated browser context without
navigating to the browser's PDF viewer. A record with an unavailable or
structurally changed PDF path is reported as failed; do not fabricate a URL or
bypass access controls. Download manifests merge by `record_id` across runs, so
smaller resume batches do not erase earlier successful records.

The basic Agent workflow is:

```text
auth-check -> search -> inspect fixed manifest
           -> optional serial detail enrichment
           -> fixed citation/venue statistics
           -> download -> report
```

Do not add `session` to this workflow. A human may run `session` only while no
Agent search or download is running.

## Human Handoff

If `auth-check` is false, or a command exits with an authentication error,
stop immediately and ask the human to run:

```powershell
& $ieeeSpider login
```

If a durable background session is needed, the human may leave this running in
its own terminal. This is not an Agent command:

```powershell
& $ieeeSpider session
```

The background Edge exits with that terminal. When authentication expires,
the command exits instead of opening a visible page.

Stop the `session` command before starting an Agent search or download job.
If another process already owns the profile, the CLI reports that the profile
is in use instead of opening a second browser.

When authentication is actually lost, stop the authenticated collection and
request another human login. Do not retry through another metadata source or a
proxy.

## Hidden Dependencies

Read these references only when their details are needed:

- [references/commands.md](references/commands.md) for complete command
  options, mode selection, and exit behavior.
- [references/manifest.md](references/manifest.md) for the fixed manifest
  schema and record selection rules.
- [references/batch-operations.md](references/batch-operations.md) for profile
  lock diagnosis, serial detail-page enrichment, cooldowns, and resume
  behavior.
- [references/author-collection.md](references/author-collection.md) for
  per-author quotas, recommended file structure, ranking, validation, and
  reusable selection and DOCX scripts.
