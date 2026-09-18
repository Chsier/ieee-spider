# Batch Operations and Concurrency Limits

## Browser Ownership

The maintained persistent profile is designed for one browser process at a
time. Treat authenticated search, detail-page enrichment, authorized
downloads, and `session` as mutually exclusive unless a replacement has been
tested to provide equivalent isolation.

If a command reports:

```text
The background Edge profile is already in use.
```

do not retry it in a loop and do not start another browser mode. First identify
the owner:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'browser-profile|ieee-spider' } |
  Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine
```

- A transient `uv run python ...` or Playwright command is Agent-owned work.
  Wait for it to exit before starting the next job.
- A long-running `ieee-spider session` belongs to the human-controlled
  terminal. Ask the human to stop it, then retry `auth-check`.
- Do not kill an unknown process and do not delete browser profile files.

## Concurrency Defaults

- Search pages are navigated serially by the CLI.
- Detail pages use one persistent browser context and one page.
- Authorized PDF downloads are serial.
- Authorized PDF downloads wait 4 seconds between records by default.
- Only open-access PDF HTTP downloads support `--workers`; valid range is
  `1-5`, with `3` as the default.
- Avoid running separate `search`, detail enrichment, or `download` commands
  concurrently.

The validated authenticated-browser concurrency is therefore `1`. Multiple
processes or context workers can cause profile-lock failures, HTTP 418,
`ERR_HTTP_RESPONSE_CODE_FAILURE`, or incomplete manifests. A different flow is
allowed only after it has been tested for the same failure modes.

## Authorized PDF Downloads

Use one authenticated context and one page. The maintained flow:

1. Open the IEEE document landing page.
2. Resolve the exposed `stamp.jsp` or PDF link.
3. Fetch the link and any nested PDF iframe through the authenticated request
   context instead of navigating the off-screen page into the PDF viewer.
4. Save only a response that starts with `%PDF-`, while respecting the
   configured account's entitlements.
5. Merge the result into `downloads\download_manifest.jsonl` by `record_id`
   after every record, so an interrupted or resumed batch does not erase
   earlier successes.

The CLI defaults are:

- 4 seconds between authorized records
- 60-second cooldown after throttling
- 5-second cooldown after a connection timeout or reset
- at most 2 attempts per record

Observed behavior: after roughly 12-15 rapid detail-page requests, IEEE may
return `ERR_HTTP_RESPONSE_CODE_FAILURE` even while `auth-check` remains true.
After a cooldown, the same record may return HTTP 200 and an ordinary account
permission result. Do not classify this transient failure as a permanent lack
of access.

IEEE may expose the nested iframe as `stampPDF/getPDF.jsp?...` rather than a
URL ending in `.pdf`. Parse any PDF-identifying iframe source and validate the
final response by its `%PDF-` header; do not require a `.pdf` suffix.

## Serial Abstract Enrichment

Run from the project root and provide the authoritative search manifest:

```powershell
& $ieeeSpider enrich `
  --input data\jobs\<job-name>\manifest.jsonl `
  --output data\jobs\<job-name>\abstracts.jsonl
```

The helper defaults are intentionally conservative:

- one browser context and one page
- 4 seconds between detail pages
- 20 seconds of cooldown after every 5 processed records
- 60 seconds of cooldown after suspected throttling
- at most 4 attempts per record
- append-safe resume through the existing output JSONL

An existing successful abstract is not considered complete when its record
lacks `citation_count`, `patent_citation_count`, `full_text_views`, or
`citation_status`. This intentionally refreshes older abstract-only caches
with the citation metrics required by the statistics workflow.

Practical options:

```powershell
# Inspect pending work without opening a browser.
& $ieeeSpider enrich `
  --input data\jobs\<job-name>\manifest.jsonl `
  --output data\jobs\<job-name>\abstracts.jsonl `
  --dry-run

# Retry records already marked failed.
& $ieeeSpider enrich `
  --input data\jobs\<job-name>\manifest.jsonl `
  --output data\jobs\<job-name>\abstracts.jsonl `
  --retry-failed
```

The skill wrapper at `scripts\enrich_abstracts.py` is retained only for
compatibility and delegates to `ieee-spider enrich`.

Keep these delays unless testing supports a safer adjustment. They exist
because IEEE may reject a rapid detail-page sequence even when the saved
session and cookies remain valid; do not reduce them merely for speed.

## Throttling and Authentication Failures

Observed failure mode:

- A rapid batch can succeed for several dozen detail pages, then return
  `ERR_HTTP_RESPONSE_CODE_FAILURE` for many consecutive documents.
- `auth-check` may still report `authenticated: true`.
- After a roughly 45-to-60-second cooldown, the same document can return HTTP
  200 with no login action.

For throttling:

1. Stop the batch immediately instead of retrying every record rapidly.
2. Keep the authenticated browser session and retry the failed records in
   small serial batches after a 45-to-60-second cooldown.
3. Preserve successful enrichment records and resume from the output JSONL.
4. Never use a proxy, alternate metadata source, or automatic login.

For authentication failure:

1. Stop the batch when the page redirects to sign-in, returns 401/403, or
   `auth-check` reports `authenticated: false`.
2. Ask the human to run `& $ieeeSpider login` and complete the
   institutional SSO flow in the popup, not merely reload an existing personal
   or anonymous IEEE page.
3. Resume the same job after login; do not recreate the manifest.

`WLSESSION` can exist for an anonymous IEEE page. It must not be treated as a
completed institutional login without `xpluserinfo`, `ERIGHTS`/`SDR1`, or a
live authenticated page that no longer shows `Personal Sign In` or
`Institutional Sign In`.

Saved storage state is loaded into the persistent browser before navigation.
If a later `auth-check` fails, it must not replace the saved state with the
anonymous current context; otherwise a valid human login would be lost on the
next command.

### Resetting Stale Authentication State

Use this procedure when switching institutions, clearing a stale entitlement
cache, or validating the first-use gate:

1. Stop every `login`, `session`, search, enrichment, and download process.
2. Move `$HOME\.ieee-spider\data\auth` to a timestamped quarantine path such
   as `auth.revoked-YYYYMMDD-HHMMSS`; do not keep the active path.
3. Run `& $ieeeSpider auth-check` before logging in. It must fail with
   `Auth state not found`.
4. Ask the human to run `& $ieeeSpider login` and complete institutional
   SSO in the visible browser.
5. Run `auth-check` in two separate processes. Both must report
   `authenticated: true`.
6. Only then resume search or downloads.

The quarantine directory is ignored by Git. Delete it according to the local
security policy after the new session is confirmed, or retain it temporarily
for rollback.

## Abstract Extraction Defaults and Output Contract

Prefer the authenticated IEEE detail page with these selectors and rules:

- Primary selector: `div.abstract-text`
- Fallback: `meta[property="og:description"]`
- Expand an IEEE `Show More` control before reading long abstracts; never
  cache truncated text as a successful abstract.
- Remove the leading `Abstract:` label.
- Reject an empty or obviously non-abstract result.
- Read `Cites in Papers`, `Patent Cites`, and `Full Text Views` from the same
  authenticated detail page when present.
- Distinguish `available`, `unavailable`, and `not_reported` citation status.
- Store enrichment separately from the fixed search manifest.

If IEEE changes the markup or an alternative authenticated route is more
reliable, inspect the page and make the smallest parser or navigation change
that preserves the output contract. Do not silently substitute another
metadata source.

Verify the final output before summarizing or reporting:

- all manifest `record_id` values are present exactly once
- every successful record has a non-empty abstract
- every record retains the citation and venue fields used by the fixed
  statistics reporter
- failed records retain their error text
- no manifest file has been edited by hand
