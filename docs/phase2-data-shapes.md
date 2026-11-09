# Phase 2: more data shapes, and the snapshot format

Observed on 9 November 2026 (Circular T 465 is the latest issue by the index below). Real responses
are saved in `tests/fixtures/`; the code that reads them is in `pipeline/`.

## The Circular T index

The published-issues folder has a file `MD5SUMS` with one line per issue, `<md5>  cirt.<number>`.
It lists 366 issues, 100 to 465, without gaps. Reading it gives the newest issue number without
scraping a web page or probing for the next file, and gives a checksum to verify each download
(`circular_t_index.py`). The twelve issues 453-464 saved as fixtures all match their listed checksums.

**Issue 465 does not.** Downloaded twice, hours apart and bypassing any cache, the served file is
byte-identical both times, and its md5 differs from the one listed; no whitespace or line-ending
variant of the file produces the listed checksum. The content itself is consistent: all 579 values in
its Section 1 (86 labs) equal the API's values. The index entry looks stale or wrong, not the file.

Because a checksum can disagree with a file that never changed, the daily check compares every
stored issue's md5 with the index and, only on a disagreement, downloads the issue again and
classifies it (`issue_integrity.py`): `index_mismatch` (the file is unchanged, the index
disagrees: flagged, not re-ingested), `changed` (the file differs: re-ingested and the diff
recorded), or `missing` (no longer listed: flagged).

## GNSS offsets

`scale=gnss` returns all four systems in one response, **daily** values with uncertainties:

| System | First date (MJD) | Values |
|---|---|---|
| GPS | 55559 | 5,751 (no missing day) |
| GLONASS | 55559 | 5,746 |
| Galileo | 60430 | 880 |
| BeiDou | 60430 | 880 |

Uncertainties are numbers for some systems and strings for others. The metadata fields of this
response (`xmin`, `xmax`, `ymin`, `ymax`) are scrambled for GLONASS and Galileo (for example GLONASS
reports `xmax: 5` and `ymax: 61309`), so ranges are always computed from the arrays.

## Rapid UTC (UTCr)

`scale=utcr` is **daily**, starts at MJD 56467 (2013) for long-running labs and at the lab's own start
for newer ones (UZ: MJD 60289), runs to MJD 61345 (2026-11-01), and carries **no uncertainties**. A
missing day stays missing (NIST and UZ each have one). At roughly 4,900 values per long-running lab,
the full rapid history is about 36 times denser than the 5-day series.

Rapid values are superseded by the published 5-day values once the next Circular T appears, so only
the days **after the latest Circular T date** are kept, they are replaced weekly, and they are marked
provisional (`rapid.provisional: true` in a lab's snapshot file, and a `rapid` block in `meta.json`)
so the UI can draw them differently (`rapid.py`). With the latest Circular T date at MJD 61309 and
rapid data to MJD 61345, that is 36 days per lab.

## Clocks

The Time Database clock list has one row per clock. The clock total is **computed on every run from the
page** and defined as "clocks not marked stopped on the Time Database clock list"; it is never stored
or hardcoded. Rows filed under a code that is not a laboratory (here `F`: French clocks at other sites,
named in the comment) count in the total but never in a laboratory's own size. On 9 November 2026 the
page had 973 rows, 290 of them marked "(stopped)", leaving 683: 657 in 90 of the 98 laboratories
(USNO 63, NICT 52, NTSC 43, NIM 23) and 26 under `F` (all 26 not marked stopped; `F` has 16 stopped
rows besides). Eight labs have no clock that is not marked stopped: AOS, CNES, EE, INCP, KEBS, LDS, LV
and TUG. "Not marked stopped" is what the page shows; it does not say that every such clock took part
in the latest computation.

## Snapshot format

The globe reads static JSON built by the pipeline (`python -m timeglobe_pipeline.build`), never the API:

| File | Content |
|---|---|
| `meta.json` | newest Circular T number, `generated_at` (the date of the last run that changed data, not the build date), counts, computed clock totals, rapid-data cutoff, attribution, data flags |
| `labs.json` | every lab (BIPM text verbatim, ISO code, coordinates, clock count) and the map sites |
| `frames/<year>.json` | one row per date, one column per lab, `null` where a lab has no value |
| `labs/<code>.json` | one lab's whole series with uncertainties, loaded when the lab is picked; plus its provisional rapid values after the latest Circular T date, if any |
| `rapid.json` | every lab's provisional rapid days after the latest Circular T date, as a frame with the same columns as `frames/`, so one request colours all labs for those days |
| `clusters.json` | the multi-site clusters for 8 camera-altitude buckets, precomputed (greedy by lab count, radius about 300 km x altitude, capped at 500 km); a site in no cluster is drawn on its own, and a shared-city site is always one point |
| `gnss.json` | the four GNSS offsets |

Values are integers in tenths of a nanosecond (all 236,288 values and uncertainties of the 5-day series
are exact multiples of 0.1 ns, and the build refuses a value that is not), so no floating-point noise
reaches the browser. `null` means "no data" and is
never written as 0. The output is deterministic.

Measured on the full build (97 labs, 133,809 values, AZ rebuilt from Circular T):

| Part | Size (gzip) |
|---|---|
| First frame: `meta` + `labs` + the latest year of frames | 17 KB |
| All 29 yearly frame files | 327 KB (8-13 KB each) |
| All 97 lab detail files | 554 KB (about 6 KB each) |
| `rapid.json` | 5.2 KB |
| `clusters.json` | 1.3 KB |
| `gnss.json` | 45 KB |
| First load: `meta` + `labs` + latest year of frames + `rapid` + `clusters` | 23.2 KB |

Series are validated before they are published: duplicate or backward dates, zeros on such dates,
dates off the expected grid, absurd values and unknown lab codes are blocking problems; a junk
uncertainty label is flagged and only loses that uncertainty. A blocking series is excluded and
flagged, or rebuilt from the published Circular T issues when its dates repeat or run backwards.

---

Time data: © BIPM Time Department (Circular T, API, Time Database), licensed under CC BY 4.0.
Processed by the Time Globe project; not affiliated with or endorsed by BIPM.
