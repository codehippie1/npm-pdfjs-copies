# Headline numbers (npm packages that ship their own copy of PDF.js)

Collected 2026-10-30 from public npm registry data (see README.md for method and sources). Every figure below is computed by `scripts/s06_numbers.py` from the files in this folder; `data/numbers.json` holds the same values unrounded.

Wording: a release *carries a PDF.js release in the affected range* when the newest PDF.js copy found in it is older than 4.2.67, the first release with the fix for CVE-2024-4367 (published to npm on 2024-04-29). Whether a carrying package is exploitable depends on how it uses PDF.js (for example, the `isEvalSupported` option and which PDFs it opens); these figures say nothing about that.

## Abstract-ready figures

- **1,510** npm packages in the reached frame carry their own copy of PDF.js in at least one screened release, across **14,678** carrying releases (pdfjs-dist itself excluded).
- **1,439** packages carry a copy in their latest release (census of the reached frame); adding the unreached part of the 'pdf' search space gives an estimated **2,122** (95% interval 1,868 to 2,519).
- **70.6%** of packages whose latest release carries an identified upstream PDF.js copy carry a release in the affected range (904 of 1,280; Wilson 95% [68.1, 73.1]).
- Of **5,487** carrying releases published after the fix (upstream-identified copies), **28.5%** still carry a release in the affected range (cluster-bootstrap 95% [22.2, 35.0]); these come from 216 of the 587 packages that published a carrying release after the fix (36.8%, Wilson [33.0, 40.8]).
- At publish time a carrying release is a median **232 days** behind the PDF.js release it carries (cluster-bootstrap 95% 191 to 265 days; IQR 78 to 608); **81.5%** ship an older PDF.js than the newest one available that day (95% [77.7, 85.1]).
- File names alone find 53.3% of the packages whose latest release carries PDF.js (767 of 1,439; Wilson [50.7, 55.9]); the rest have PDF.js compiled into their own bundles.
- 33.1% of packages that first shipped a copy after the fix started with a PDF.js release in the affected range (173 of 522; Wilson [29.2, 37.3]).
- Of 779 packages carrying an affected-range copy on the fix date, 93.1% have not published since; of the 54 that did, 48.1% still carried an affected-range copy two years later (Kaplan-Meier).

## Coverage per stratum

| Stratum | Frame | Screened OK | No listing | Unpublished | Older releases screened | Latest-release carriers | Ever carriers (screened releases) |
|---|---:|---:|---:|---:|---:|---:|---:|
| S1 PDF.js terms (full census) | 2,338 | 2,330 | 8 | 0 | 2,330 | 862 | 911 |
| S2 keyword 'pdf' (reached part) | 7,621 | 7,600 | 21 | 0 | 670 | 260 | 265 |
| S3 text 'pdf' (reached part) | 3,461 | 3,453 | 8 | 0 | 327 | 138 | 142 |
| S4 pdfjs-dist dependents (full census) | 691 | 544 | 3 | 101 | 544 | 179 | 192 |

- The registry search API stops at about 5,250 results per query. Keyword 'pdf': 9,285 packages with the keyword were reached (the API reports 9,212 matches), so that space is covered in full. Text 'pdf': 13,054 of about 33,145 reached (39.4%).
- The unreached 20,091 text matches are estimated, not counted. They lie beyond rank 5,250 of the plain query and outside the top of every expansion. The S3 hit rate shows no clear trend with plain-query rank: 0-999: 10/310, 1000-1999: 10/339, 2000-2999: 15/363, 3000-3999: 18/363, 4000-5249: 17/500. Using the last band (17/500, Wilson [2.13, 5.38]) gives 683 (95% 429 to 1,080) more latest-release carriers. As an upper sensitivity bound, the rate of S3 packages reached only through topical expansion (68/1578) would give at most 1,090.
- Older releases (up to five per package, evenly spaced) were screened for every S1 and S4 package and for a seeded random subsample of S2+S3. Former carriers (a copy in an older release but not the latest): 62 found in S1+S4; in the S2+S3 subsample 9 of 968 non-carrying packages, which scales to about 99 (95% 52 to 187) across reached S2+S3; only the 9 found are in the release table.

## Detection and recall

- Identification of carrying releases: {'banner': 3454, 'bundle': 7676, 'hash': 3548} (hash = byte-identical to a pdfjs-dist file; banner = version string read from the named file; bundle = PDF.js signatures found inside another JS bundle).
- Releases of hit packages: 22,235; 19,788 classified, 20 without a jsDelivr file list, 2,427 left unclassified by the per-package cap of 200 bundle-scanned releases (they hold no named copy, so they could only carry a bundled one).
- PDF.js version identified for 14,218 of 14,678 carrying releases; 12,461 map to a published pdfjs-dist version, the rest are custom or fork builds.
- Recall of the file-name rules against the full bundle scan, latest releases: S1 585/862 = 67.9% (Wilson [64.7, 70.9]); S2 94/260 = 36.2% (Wilson [30.6, 42.2]); S3 51/138 = 37.0% (Wilson [29.4, 45.3]); S4 37/179 = 20.7% (Wilson [15.4, 27.2]); all 767/1439 = 53.3% (Wilson [50.7, 55.9]).
- Over carrying releases: 7,002 of 14,678 = 47.7% (cluster-bootstrap [39.8, 55.6]).
- Precision of the file-name rules alone: 50 of 818 latest releases with a PDF.js-like file name had no PDF.js content (other PDF engines' workers, renamed files, character-map-only packages); content checks remove these.

## What the copies are

- PDF.js major version in carrying releases: {'1': 531, '2': 7101, '3': 1929, '4': 2489, '5': 1399, '6': 767, '?': 462}.
- Build type in carrying releases: {'generic': 4256, 'unknown': 7474, 'generic+legacy': 1469, 'legacy': 1479}; worker present in 11,224 (76.5%).
- Shape of the last carrying release per package: {'embedded': 1194, 'republication': 316} (republication = 3 or fewer files outside the PDF.js layout; embedded = a larger package around the copy).

## Lag behind upstream at publish time

- 12,461 carrying releases from 1,364 packages with an upstream-identified copy and a publish date.
- Lag (publish date minus the carried PDF.js release date): median 232 days (95% 191 to 265), P25 78, P75 608, P90 1074; per-package median of medians 261 days.
- More than a year behind: 36.8% (95% [32.0, 42.1]). Behind the newest upstream release on publish day: 81.5% (95% [77.7, 85.1]); median 3 minor release lines behind.
- Latest releases only (1,280 packages): median lag at publish 310 days; on 2026-10-30 the carried PDF.js release is a median 1775 days old; 81.8% were already behind upstream when published.

| Publish year | Carrying releases | Packages | Median lag (days) | Behind newest upstream | In affected range |
|---|---:|---:|---:|---:|---:|
| 2014 | 3 | 1 | 0 | 33.3% | 100.0% |
| 2015 | 6 | 4 | 3 | 66.7% | 100.0% |
| 2016 | 64 | 19 | 30 | 76.6% | 100.0% |
| 2017 | 164 | 37 | 13 | 82.9% | 100.0% |
| 2018 | 416 | 80 | 142 | 73.3% | 100.0% |
| 2019 | 818 | 115 | 204 | 79.1% | 100.0% |
| 2020 | 781 | 133 | 221 | 86.3% | 100.0% |
| 2021 | 1,556 | 169 | 328 | 96.5% | 100.0% |
| 2022 | 1,314 | 185 | 231 | 74.8% | 100.0% |
| 2023 | 1,412 | 219 | 261 | 86.4% | 100.0% |
| 2024 | 1,342 | 190 | 194 | 74.5% | 64.7% |
| 2025 | 1,892 | 213 | 309 | 78.5% | 40.4% |
| 2026 | 2,693 | 348 | 198 | 79.9% | 13.8% |

## Shipping the affected range after the fix (29 Apr 2024)

- Carrying releases published after the fix: 5,487 with an upstream-identified copy; 1,563 of them (28.5%, 95% [22.2, 35.0]) carry a release in the affected range. Counting custom and fork builds by their version number: 1,835 of 6,210.
- These affected-range releases were published a median 438 days after the fix (P75 602, latest 913 days; most recent on 2026-10-30). By half-year: {'2024H1': 193, '2024H2': 235, '2025H1': 329, '2025H2': 435, '2026H1': 201, '2026H2': 170}.
- Packages whose first carrying release came after the fix: 522; 173 of them (33.1%, Wilson [29.2, 37.3]) started with a PDF.js release in the affected range, a median 1128 days behind upstream.
- Per package, the last affected-range release after the fix came a median 448 days after it; 124 of the 216 packages published one more than a year after the fix.
- Packages whose last release before the fix carried an affected-range copy: 779. Since then 725 published nothing, 26 moved to 4.2.67 or later, 4 stopped shipping a copy, and 24 kept publishing with an affected-range copy.
- Kaplan-Meier, share still carrying an affected-range copy (all of that cohort, no-release packages censored): 98.1% at 180 days, 97.4% at 1 year, 96.4% at 2 years; median not reached.
- Restricted to the 54 of them that published again after the fix (34 of whose first post-fix release still carried an affected-range copy): 81.5% still affected at 90 days, 63.0% at 1 year, 48.1% at 2 years; median 691 days.
- Latest releases: 904 of 1,280 packages (70.6%, Wilson [68.1, 73.1]) carry a release in the affected range.

## Weighted by use (npm downloads, last month)

- Packages whose latest release carries a copy: 72,058,931 downloads in the last month (1,433 packages with any). The ten largest account for 97.5%.
- Weighted by downloads, 0.7% of upstream-identified latest-release carriers' downloads go to packages carrying a release in the affected range.
- For scale: pdfjs-dist had 134,953,946 downloads in the same window.

## Notes

- `ng2-pdfjs-viewer`, maintained by the owner of this dataset, is one row in the data and is handled exactly like every other row.
- No package or maintainer is named in this summary; the data files list packages.
- Against the one-day feasibility check (about 926 latest-release carriers, 95% range 742 to 1,290): the reached frame alone now holds more. Three things moved the figure: the bundle scan now runs on every package and also recognises minified display-layer code (the check's sample scan looked for the worker's version-check message or the `pdfjsVersion` name, which minified display-layer bundles lack); the frame grew through query expansion; and file-name hits now count only when their content is PDF.js. The check's search pools were also smaller than it reported (the search window wraps after about 5,250 results, not 10,000).
- Counts are lower bounds for the reached frame: the bundle scan skips JS files under 150 kB, caps at 25 files and 60 MB per release, and cannot see copies that are loaded from a CDN at run time.
