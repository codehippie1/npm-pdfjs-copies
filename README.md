# npm packages that ship their own copy of PDF.js

By Aneesh Gopalakrishnan. Data under CC BY 4.0 (`LICENSE-DATA`), scripts under Apache-2.0 (`LICENSE`). How to cite:
`CITATION.cff`. Archived on Zenodo: https://doi.org/10.5281/zenodo.23820302 (version 1.0.0).

A dataset of npm packages that carry a copy of Mozilla PDF.js inside their published files, which PDF.js
release every package release carries, and how far behind upstream those copies were on the day each
release was published.

- **Collected:** 30 October 2026, between 04:14 and 07:10 UTC (`COLLECTION_DATE = 2026-10-30` in
  `scripts/common.py` is the reference date for ages and survival times). Download counts cover the npm window reported in
  `packages.csv` (`downloads_period`).
- **Headline figures:** `numbers.md`, with confidence intervals. `data/numbers.json` holds the unrounded values.
- **Data:** `packages.csv` / `packages.jsonl` (one row per package), `releases.csv` / `releases.jsonl` (one row
  per release of those packages). The CSV and JSON Lines copies hold the same rows.
- **Code:** `scripts/`, Python 3.10+ standard library only. `run.log` is the log of the collection run.

## Why this exists

PDF.js is published to npm as `pdfjs-dist`. Many packages do not depend on it: they copy its built files
(or bundle them into their own JavaScript) and publish that copy. Copies do not move when upstream does, so a
copy keeps whatever PDF.js release it was taken from. CVE-2024-4367 (fixed in PDF.js 4.2.67, published to
npm on 29 April 2024) makes the lag measurable in terms that matter.

## What counts as a copy

A release *carries PDF.js* when at least one of its files is PDF.js code, established by one of three
methods, tried in this order:

1. **hash**: a file with a PDF.js-like name (`pdf.worker*.js`, `pdf.js`, `pdf.min.mjs`, `pdf.combined.js`,
   `web/viewer.js`, ...) is byte-identical (SHA-256) to a file in some pdfjs-dist release;
2. **banner**: such a named file is not byte-identical, but its content holds PDF.js signatures (the worker's
   `does not match the Worker version` message, the display layer's `No "GlobalWorkerOptions.workerSrc"
   specified` message, or `pdfjsVersion` with `pdfjsBuild`) and a version string;
3. **bundle**: no named copy exists, but a JavaScript file of 150 kB or more holds the same signatures
   (PDF.js bundled into the package's own build output by webpack, Vite, Rollup and the like).

Methods 2 and 3 also require at least two strings from PDF.js's own API and worker code (`Setting up fake
worker failed`, `Worker was destroyed`, `Worker was terminated`, `Transport destroyed`, `Invalid PDF structure`,
`Invalid page request`, `Loading aborted`, `getOperatorList`, `Unknown action from worker`). Every pdfjs-dist
build checked, 1.0 to 6.4, holds two or more; wrapper code that only quotes a PDF.js error message in a comment
holds none. This rule was added during collection after two Angular wrappers were caught that way, and the
screen was rerun with it.

A file name alone never counts: named candidates without PDF.js content (other engines' workers, renamed
files) are rejected and listed in `data/screen.jsonl` (`rejected`). Character maps without PDF.js code do not
count either. Copies whose version cannot be read (source-built copies where the version is compiled out,
PDF.js-derived forks such as old parser packages) count as carrying, with an empty `pdfjs_version`.

The **PDF.js version** comes from the matching pdfjs-dist file (hash) or from version strings in the file
(`pdfjsVersion = "x.y.z"` or the unquoted build header `pdfjsVersion = x.y.z`, `apiVersion: "x.y.z"`,
`workerVersion = "x.y.z"`, the version literal next to the worker's version check, the version literal followed
by the build hash). When a release carries several copies, `pdfjs_version` is the
**newest** one, which makes lag and affected-range figures conservative; all versions are in
`pdfjs_versions_all`. Versions that are not a published pdfjs-dist release (custom or fork builds, e.g.
`6.4.1351`) keep their own number (`pdfjs_upstream = false`) and are mapped to the greatest pdfjs-dist release
not above them (`pdfjs_base_version`). Headline lag and affected-range figures use upstream-identified copies
only; `numbers.md` gives the count with fork builds included as well.

**Build type** is `legacy` when the library file carries core-js polyfills (PDF.js legacy/es5 builds do,
generic builds do not; checked against pdfjs-dist 2.6 to 6.4) or sits under `legacy/` or `es5/` in pdfjs-dist,
`generic` otherwise, `generic+legacy` when both ship, `unknown` for bundled copies. PDF.js 1.x had no separate
legacy build and is always `generic`. **worker_present** is true when a confirmed copy holds PDF.js's worker
(core parser) code: a pdfjs-dist worker or combined file by hash, or a file holding the worker's version-check
message or the parser's `Invalid PDF structure` message (in every worker and combined build checked, 1.0 to 6.4,
and in no display-layer build). Copies without it are display-layer only; such packages load the worker from
elsewhere at run time.

**Shape**: a carrying release is a `republication` when 3 or fewer of its files are not PDF.js files, and
`embedded` otherwise. PDF.js files are the identified copies, files byte-identical to any pdfjs-dist file, files
inside a PDF.js layout directory (`build/`, `legacy/`, `web/`, `cmaps/`, `standard_fonts/`, `es5/`, `lib/`,
`pdfjs/`, ...), character maps and fonts, and package metadata (`package.json`, README, LICENSE, CHANGELOG).
A copy found only by the bundle scan is compiled into the package's own build output, so it is always
`embedded`.

## Sampling frame

The registry search API returns at most about 5,250 results per query (paging past `from=5000` wraps to the
first page; the feasibility check before this dataset read its 10,000-result pages as 10,000 distinct names,
which overstated the reached frame). Large result sets are therefore reached by query expansion.

| Stratum | Definition | Reach |
|---|---|---|
| S1 | results of `pdfjs`, `pdf.js`, `keywords:pdfjs`, `keywords:pdf.js`, `pdf.worker`, `keywords:pdfjs-dist` | every query is under the window: full census |
| S2 | packages with the keyword `pdf` (`keywords:pdf`, `keywords:pdf-viewer`), reached through the plain query plus AND-queries `keywords:pdf,<co-keyword>` | in full: more packages with the keyword were reached (through all queries) than the API's own total |
| S3 | text search `pdf`, reached through the plain query plus `pdf <term>` expansions; a result is kept only if its name, description or keywords contain the token `pdf` | part of the text space; `numbers.md` gives reached / total |
| S4 | dependents of pdfjs-dist listed by ecosyste.ms on 2026-10-29 (frozen copy in `data/`) | full census |

A package belongs to the first stratum that reaches it (S1, S2, S3, S4). The unreached part of the text
space is estimated, not counted: it lies beyond rank 5,250 of the plain `pdf` query and outside the top of every
expansion, so the estimate uses the S3 hit rate in the last band of the plain query (ranks 4,000 to 5,249) times
the unreached count, with a Wilson 95% interval. Packages reached only through expansion are not used for the
estimate because the topical expansion terms (viewer, preview, vue, react, ...) enrich them for carriers; their
rate gives an upper sensitivity bound, reported next to the estimate.

## Pipeline

| Step | Script | Output |
|---|---|---|
| 0 | `s00_reference.py`: every pdfjs-dist release, its publish time and the SHA-256 of every file | `data/pdfjs_reference.json` |
| 1 | `s01_frame.py`: search queries and expansions; S4 list | `data/search_raw.jsonl(.gz)`, `data/frame.jsonl`, `data/frame_meta.json` |
| 2 | `s02_screen.py`: classify the latest release of every frame package; also up to five older releases (evenly spaced) for S1, S4 and a seeded random 1,000-package subsample of S2+S3 | `data/screen.jsonl` |
| 3 | `s03_releases.py`: every release of every package with a carrying release in step 2. The bundle scan looks first at the paths where step 2 found a bundled copy and stops there if they confirm it; it runs on at most 200 evenly spaced releases per package, and other releases without a named copy are marked `not_scanned` | `data/releases_raw.jsonl` |
| 4 | `s04_downloads.py`: last-month downloads (bulk API for unscoped names, one request per scoped name) | `data/downloads.json` |
| 5 | `s05_tables.py`: the published tables | `packages.*`, `releases.*` |
| 6 | `s06_numbers.py`: headline figures and intervals | `numbers.md`, `data/numbers.json` |
| 7 | `s07_checks.py`: consistency checks on the tables (methods present, versions valid, no release dated well before its PDF.js release, package rows agree with release rows, CSV and JSONL agree) | exit code |

## Sources

All public, unauthenticated, plain HTTPS GETs; at most 8 requests in flight; exponential back-off on 429,
5xx and timeouts, honouring `Retry-After`; the search API paced at one request per 1.6 s.

- `registry.npmjs.org`: packuments (version list, `time` per version, `dist-tags`), the search API
  (`/-/v1/search`), and tarballs as a fallback for files jsDelivr will not serve (needed for 7 files over its
  size limit);
- `api.npmjs.org`: `/downloads/point/last-month/...`;
- `data.jsdelivr.com`: `/v1/packages/npm/<name>@<version>?structure=flat`, the file list of a release with the
  SHA-256 and size of every file, so most questions are answered without downloading the package;
- `cdn.jsdelivr.net/npm/<name>@<version>/<path>`: single files of a release (the same bytes as in the npm
  tarball), fetched only for content checks of files whose hash is not a pdfjs-dist hash;
- `packages.ecosyste.ms`: the pdfjs-dist dependents list, captured once on 2026-10-29 and reused frozen.

Nothing was fetched from live websites or deployed applications, and nothing required a login. Downloaded
content is treated as untrusted data: it is scanned as bytes, never executed; tarballs (fallback only) were
kept in a scratch folder outside this dataset.

## Schema

### `releases.csv`

One row per published version of every package in `packages.csv` (carrying or not).

| Column | Meaning |
|---|---|
| `package`, `version` | npm name and version |
| `published` | publish time from the packument `time` field (UTC) |
| `status` | `ok`; `no_listing` when jsDelivr had no file list for the version; `not_scanned` when the release holds no named copy and fell outside the 200 bundle-scanned releases of its package (`carries` is then empty) |
| `carries` | the release ships PDF.js code (see "What counts as a copy") |
| `pdfjs_version` | newest PDF.js copy in the release |
| `pdfjs_versions_all` | every PDF.js version found, `;`-separated |
| `pdfjs_upstream` | `pdfjs_version` is a published pdfjs-dist version |
| `pdfjs_base_version` | greatest pdfjs-dist version not above `pdfjs_version` (equal when upstream) |
| `pdfjs_release_date` | npm publish time of `pdfjs_base_version` in pdfjs-dist |
| `build_type` | `generic`, `legacy`, `generic+legacy`, `unknown` |
| `worker_present` | a worker copy is among the confirmed files |
| `id_method` | strongest method among the copies: `hash`, `banner`, `bundle` |
| `detected_via` | `filename` (named copy) or `bundle` (bundle scan only) |
| `shape` | `republication` (3 or fewer non-PDF.js files) or `embedded` |
| `n_files`, `n_other_files` | files in the release; files that are not PDF.js files |
| `lag_days` | `published` minus `pdfjs_release_date`, in days |
| `latest_upstream_at_publish` | newest pdfjs-dist version published before this release |
| `behind_latest_upstream` | the carried version is older than that |
| `minor_lines_behind` | newer PDF.js major.minor lines available at publish time |
| `affected_range` | `pdfjs_base_version` is older than 4.2.67 |
| `published_after_fix` | published on or after the 4.2.67 publish time (2024-04-29 17:31 UTC) |
| `days_after_fix` | days between the 4.2.67 publish time and this release |
| `is_upstream_pdfjs` | the row belongs to pdfjs-dist itself (left out of every figure) |

### `packages.csv`

| Column | Meaning |
|---|---|
| `package` | npm name |
| `stratum`, `strata_all` | assigned stratum; every stratum that reached the package |
| `latest_version`, `latest_published` | `dist-tags.latest` at collection time and its publish time |
| `n_versions`, `n_versions_listed` | published versions; versions with a jsDelivr file list |
| `n_carrying_releases` | releases that carry PDF.js |
| `first_carrying_*`, `last_carrying_*` | first and last carrying release (version, publish time) |
| `latest_carries`, `latest_pdfjs_version`, `latest_pdfjs_upstream` | state of the latest release |
| `latest_affected_range` | the latest release carries a PDF.js release older than 4.2.67 |
| `ever_affected_range` | any carrying release does |
| `affected_range_release_after_fix` | a carrying release in the affected range was published after the fix |
| `detected_via` | `filename`, `bundle`, or both across releases |
| `latest_shape` | shape of the latest release, if it carries |
| `pdfjs_versions_carried` | every PDF.js version carried across releases |
| `downloads_last_month`, `downloads_period` | npm downloads and the window they cover |
| `is_upstream_pdfjs` | pdfjs-dist itself |

### `data/`

`frame.jsonl` (every candidate package, stratum, search ranks), `screen.jsonl` (step 2 result per package,
including rejected file-name candidates and older-release checks), `releases_raw.jsonl` (step 3, with the
per-file evidence for each copy), `search_raw.jsonl.gz` (every search page as returned, 3,044 pages; 66 MB
compressed, the largest file; the scripts read the `.gz` copy directly), `pdfjs_reference.json`,
`downloads.json`, `frame_meta.json`, `numbers.json`, and the frozen S4 list.

## Reproduce

```
set MSR_WORK=C:\some\scratch\folder        (Windows; export MSR_WORK=... elsewhere)
python -I scripts/run_all.py               (all steps; resumable)
python -I scripts/run_all.py s05_tables s06_numbers s07_checks   (rebuild tables and figures only, no network)
```

`MSR_WORK` holds the HTTP cache (`httpcache.sqlite`, zlib-compressed bodies, and a per-file-hash cache of content
checks) and the tarball fallback folder; keep it outside this dataset. With a warm cache the whole run replays
without network access. A fresh run will see a registry that has moved on: new releases, unpublished packages,
and search results that change from day to day (the search API's own `total` for `pdf` moved between 31,636 and
33,145 during collection). `data/search_raw.jsonl.gz` and the frozen S4 list pin the frame used here: replaying
`s01_frame.py` from them with an empty cache makes no search request and rebuilds `data/frame.jsonl`
byte for byte (checked on 30 October 2026).

## Run history

The collection ran on 30 October 2026 (local time UTC-4); `run.log` has every step with timestamps.

1. Reference (`s00`), then the frame (`s01`: 577 search queries, about 3,000 result pages).
2. While the search expansion ran, steps 2 and 3 were run on provisional frames to find problems early. Four
   detection rules were tightened as a result:
   (a) PDF.js internals required next to every signature (two Angular wrappers had been counted because a
   comment quoted a PDF.js error message);
   (b) the worker marker (display-layer bundles had been reported as including the worker);
   (c) the version of a release comes from library files, not from rarely changing sandbox or viewer files
   (a pre-release build had been dated by an unchanged sandbox file);
   (d) unminified 4.x+ builds split the worker's version-check message across two string literals and write
   `pdfjsVersion = x.y.z` without quotes; both forms are now read.
3. The provisional outputs were then set aside and steps 2 to 6 were run once more, end to end, on the final
   frame and under the final rules. The HTTP cache made that rerun cheap. The content-check cache is versioned,
   and a check was fetched and scanned again wherever a later rule could change its outcome: every positive made
   before rules (a) and (b), and every negative and every positive without a version made before rule (d).
   Positives with a version made under (a) and (b) were reused; rule (d) only adds version patterns that the
   earlier patterns had already resolved for those files.

## Limitations

- **Frame.** Search reach is bounded by the API window. About 61% of the text-`pdf` space was not reached; its
  carriers are estimated from a reached segment, not sampled at random, and the S3 hit rate shows no clear trend
  with relevance rank (3 to 5% per band), so the unreached part may hold about as many carriers per package as
  the reached part. Packages that ship PDF.js without mentioning PDF.js or "pdf" anywhere in their metadata, and
  that are not listed as pdfjs-dist dependents, are outside the frame. The S4 list is a single ecosyste.ms
  snapshot; 144 of its packages are now unpublished or gone.
- **Detection.** The bundle scan skips JS files under 150 kB, scans at most 25 files and 60 MB per release, and
  cannot see PDF.js loaded from a CDN at run time; heavily minified bundles without any of the signature strings
  are missed. Counts are lower bounds for the reached frame.
- **Former carriers.** Older releases were screened at up to five evenly spaced points per package (all of S1
  and S4, a 1,000-package random subsample of S2+S3); short carrying stretches between those points can be
  missed, and S2+S3 former carriers outside the subsample are estimated, not listed.
- **Versions.** Fork and custom builds carry their own version numbers; they are kept but left out of headline
  lag and affected-range figures. Release dates are npm publish times of pdfjs-dist, which can differ by hours
  from the GitHub release.
- **Weighting.** Release-level figures lean towards packages with many releases; intervals for them use a
  cluster bootstrap over packages, and package-level figures are given next to them. Download counts include CI
  and mirror traffic, and two packages account for most carrier downloads.
- **Survival.** Most packages that carried an affected-range copy on the fix date never published again, so the
  Kaplan-Meier curve over that whole cohort mostly measures abandonment; the curve for packages that did publish
  again rests on a few dozen packages.
- **Exposure.** "Carries a PDF.js release in the affected range" is a statement about files, not about
  exploitability: that depends on how a package uses PDF.js (for example `isEvalSupported`) and what documents it
  opens. Nothing here is a finding about the security of any one package.

## Notes

- `ng2-pdfjs-viewer` is maintained by the author of this dataset. It is one row in the data and was handled exactly
  like every other row.
- The prose in this folder cites aggregate figures only and names no maintainers or people. Package names appear
  in the data files because they are the unit of observation.
- The collection scripts and this README were written with help from Claude (Anthropic); the author reviewed them and
  checked the figures against the data.
