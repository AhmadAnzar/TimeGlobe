# The ingest jobs

Three jobs keep the database current, each recorded as one row in `ingest_runs`. They are run by
hand from a GitHub Actions workflow (`workflow_dispatch`); there is no schedule yet. The static
snapshot the globe reads is built from the database after each run and published to a `data` branch.

| Job | When it does anything | What it writes |
|---|---|---|
| `daily` | when Circular T has a new issue, or a stored issue was revised | the 5-day UTC-UTC(k) series (rebuilt from Circular T where the API series is broken), GNSS offsets, stored issues |
| `weekly` | always | each lab's rapid (UTCr) values after the latest Circular T date, replacing the previous ones; only that date range is requested (`mjd1`), not the whole daily history |
| `monthly` | when the clock list was last fetched 30 or more days ago | the clock list's per-lab counts, and the total computed from the page |

## Daily: index first, then integrity

The newest issue number is read from the `MD5SUMS` index in the published-issues folder. Every
stored issue's md5 is compared with the index; only a disagreement triggers a download, which is
then classified (`issue_integrity.py`):

- **changed**: the downloaded file differs from the stored copy. The values taken from it are
  re-ingested and the diff (changed values, labs added or removed) goes into `ingest_runs.details`.
- **index_mismatch**: the file is byte-identical to the stored copy but the index lists another
  checksum (observed for issue 465). It is flagged and never blocks the run.
- **missing**: the index no longer lists the issue. Flagged.

A series whose dates repeat or run backwards is rebuilt from the published Circular T issues; any
other failing series is excluded. Failures are flagged, never repaired.

## Being a considerate client

- **Rapid values by date range.** The API accepts `mjd1`/`mjd2`, so the weekly job asks for the days
  after the latest Circular T date instead of downloading each lab's whole history (about 150 KB
  each) to keep roughly 35 days. The request uses the cutoff date itself, which is right whether the
  API treats `mjd1` as inclusive or not, and the job still trims the result, so it stays correct even
  if the API ignored the parameter. It records how many points came back against how many were kept
  (`rapid_points`) and flags `mjd1_ignored` if the saving did not happen.
- **Scraped pages at most monthly.** The clock list, the lab table and the NTP Pool zone pages are
  HTML pages, not APIs. The HTTP client serves a saved copy younger than 30 days instead of fetching
  again, and the monthly job records when it last fetched in the database (a CI runner starts with no
  saved copies), skips itself inside the window and carries its totals forward. `--force` overrides
  it for one run.
- **robots.txt.** `ntppool.org` allows the zone pages for generic clients (only `/dns.html` and
  `/monitor/` are disallowed, and there is no crawl delay for us). `webtai.bipm.org` has no
  `robots.txt`; its HTML database pages carry `noindex, nofollow`, which is about search indexing.

## Revisions and retraction

When a revised issue (or a corrected API series) no longer contains a value that was stored, the row
is **retracted, never deleted**: `offsets.retracted_at` is set, every read (snapshots, the API) skips
the row, and the run's `details` list it together with the diff of the issue it came from. If the
value comes back in a later revision the same row is restored in place. A retraction larger than a
small limit per lab and run (10 rows, or 2% of the lab's rows, whichever is larger) is refused and
fails the run: a truncated response looks exactly like a mass deletion. Rapid values are the one thing
that is replaced outright each week, because they are provisional and superseded by the next issue.

## Properties

- **Idempotent.** Rows are keyed by (lab, scale, date), so a re-run overwrites in place and the
  run records how many existing rows changed (`rows_changed`). Lab reference rows are reported
  separately and are not counted as data rows.
- **Failing loudly.** A run that could not fetch a lab's series is marked failed after everything
  else is written, so the next run retries. A lab with no data yet (it joined recently) is recorded,
  not failed.
- **Rapid values are provisional.** Only days after the latest Circular T date are kept; the next
  issue supersedes them.
- **The clock total is computed.** It is read from the clock list on every `monthly` run and defined
  as clocks not marked stopped; clocks filed under a non-lab code count in the total but never in a
  lab's own size.
