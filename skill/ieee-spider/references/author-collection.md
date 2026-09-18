# Author Collection Workflow

Prefer this branch when the user asks to find a specified number of
high-quality papers for one or more named authors, for example:

```text
Find the 50 highest-quality papers from the last four years for <author>.
为这四位作者各查 50 篇
```

## Interpretation Rules

- Treat the requested count as per author unless the user explicitly says it is
  a combined total.
- For "近四年", use the current calendar year and the previous three years,
  inclusive.
- Require exact author-name matching. Same-name records must not be assigned to
  the target author.
- Include IEEE journal and early-access papers by default. Exclude conference
  papers, editorials, corrections, errata, retractions, and call-for-papers
  notices unless the user explicitly requests them.
- Rank by IEEE venue tier first and publication year second. Use the default
  tier table in `scripts/select_author_papers.py`.
- If fewer than the requested number remain, move the start year backward one
  year at a time and repeat the selection. Record the actual final year range.
- A paper with multiple target authors may appear in each author's list, but
  its abstract should be fetched only once.

## Recommended Structure

For a collection named `<collection-slug>`:

```text
data/jobs/<collection-slug>/
|-- README.md
|-- <author-slug>/
|   |-- manifest-<N>.jsonl
|   |-- manifest-<N>.csv
|   |-- abstracts-<N>.jsonl
|   |-- summaries-<N>.docx
|   `-- statistics.json
`-- _shared/
    |-- manifest-union.jsonl
    |-- manifest-union.csv
    |-- manifest-union.md
    `-- abstracts-union.jsonl
```

`_shared` exists to avoid fetching the same paper detail page more than once.
After individual abstracts are split and verified, `_shared` may be removed
unless the user wants to retain the deduplicated source set.

Final summary files must be `.docx`. Markdown is an intermediate working
format only.

The scripts and directory layout are defaults for reproducibility. If a valid
author workflow requires a different parser, query construction, or file
split, make the smallest reusable change and keep the manifest, enrichment,
statistics, and DOCX outputs internally consistent.

## Workflow

1. Run `auth-check` and stop for human login when the session is invalid.

2. Prefer searching each target author through the authenticated browser,
   sequentially. Use a sufficiently large result pool, normally
   `max(200, requested_count * 4)` capped at `500`, and write the raw manifest
   under the collection's temporary working directory.

3. Prefer selecting top papers per author with the reusable script:

   ```powershell
   uv run python `
     "skill\ieee-spider\scripts\select_author_papers.py" `
     --input data\jobs\<collection-slug>\_raw\manifest.jsonl `
     --output-dir data\jobs\<collection-slug> `
     --author "Author One" `
     --author "Author Two" `
     --limit 50
   ```

   The script:

   - filters exact author matches and research paper types;
   - ranks by venue tier and year;
   - writes each author's fixed manifest and `statistics.json`;
   - writes a deduplicated `_shared\manifest-union.jsonl`.

4. Enrich the deduplicated union once:

   ```powershell
   & $ieeeSpider enrich `
     --input data\jobs\<collection-slug>\_shared\manifest-union.jsonl `
     --output data\jobs\<collection-slug>\_shared\abstracts-union.jsonl
   ```

5. Split the union abstracts into each author's
   `abstracts-<N>.jsonl`. Verify every author has exactly `N` records, all with
   non-empty abstracts.

6. Build each author's fixed citation-aware statistics report:

   ```powershell
   uv run python `
     "skill\ieee-spider\scripts\build_paper_statistics.py" `
     --manifest data\jobs\<collection-slug>\<author-slug>\manifest-<N>.jsonl `
     --abstracts data\jobs\<collection-slug>\<author-slug>\abstracts-<N>.jsonl `
     --output data\jobs\<collection-slug>\<author-slug>\statistics.json `
     --author "<author>"
   ```

   The report must include `citation_count`, `patent_citation_count`,
   `full_text_views`, venue counts, per-venue citation aggregates, citation
   coverage, and a Top Cited ranking.

7. Draft each author's summaries, render them to
   `summaries-<N>.docx` with `scripts\render_summary_docx.ps1`, validate the
   DOCX, and remove intermediate Markdown files.

   If an older `summaries-<N>.docx` already has the paper summaries but lacks
   the new citation and venue fields, use
   `scripts\upgrade_summary_docx.py` to preserve the existing Chinese
   summaries while adding the new statistics and per-paper metrics.

   Each paper entry must show its year, venue, record ID, citation count, and
   full-text views. The DOCX opening statistics must summarize total citations,
   citation coverage, publication venues, and the most cited papers.

8. Update the collection `README.md` with author, count, year range, and links
   to the manifest, abstract file, statistics, and DOCX summary.

9. Remove `_raw` after success. Remove `_shared` after all per-author abstract
   files are verified unless retention was requested.

## Validation Gate

Do not report completion until all of these checks pass:

- exact target-author match on every selected record;
- no conference or editorial/correction records;
- selected count equals the requested per-author count;
- abstract count and successful abstract count equal the requested count;
- statistics contain one entry per paper with venue and citation fields;
- DOCX contains the requested number of paper sections and summaries;
- no final summary file uses `.md`;
- statistics, README links, and actual files agree.

## User-Facing Capability Summary

When the user asks what the skill can do, mention this branch explicitly:

> `$ieee-spider` supports per-author high-quality paper collection: exact author
> matching, year-window fallback, journal/early-access filtering, fixed
> per-author manifests, serial abstract enrichment, deduplicated fetching, and
> DOCX summary generation.
