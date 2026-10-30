"""Step 7: consistency checks on the published tables (no network). Prints problems; exit code 1 if any.

  * every carrying release has an identification method and a detection route;
  * upstream versions are real pdfjs-dist versions; base versions never exceed the carried version;
  * lag is not below -7 days for upstream copies (a copy cannot predate its release by much; a day or so happens
    when a package is built from PDF.js source just before pdfjs-dist is published);
  * package rows agree with their release rows;
  * the CSV and JSON Lines copies hold the same rows.
"""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATASET, read_jsonl, reference, vkey  # noqa: E402


def main():
    ref = reference()
    problems = []
    rel = read_jsonl(os.path.join(DATASET, "releases.jsonl"))
    pk = read_jsonl(os.path.join(DATASET, "packages.jsonl"))
    for base, rows in (("releases", rel), ("packages", pk)):
        with open(os.path.join(DATASET, base + ".csv"), encoding="utf-8") as f:
            n = sum(1 for _ in csv.DictReader(f))
        if n != len(rows):
            problems.append(f"{base}: csv {n} rows vs jsonl {len(rows)}")
    neg = 0
    for r in rel:
        if not r.get("carries"):
            continue
        if not r.get("id_method") or not r.get("detected_via"):
            problems.append(f"no method: {r['package']}@{r['version']}")
        if r.get("pdfjs_upstream") and r["pdfjs_version"] not in ref["known"]:
            problems.append(f"upstream flag wrong: {r['package']}@{r['version']}")
        if r.get("pdfjs_base_version") and r.get("pdfjs_version") and vkey(r["pdfjs_base_version"]) > vkey(r["pdfjs_version"]):
            problems.append(f"base above version: {r['package']}@{r['version']}")
        if r.get("pdfjs_upstream") and r.get("lag_days") is not None and r["lag_days"] < -7:
            neg += 1
    if neg:
        problems.append(f"{neg} upstream-identified releases published before their PDF.js release (lag < -7 days; copies built from PDF.js source a day before the npm publish are expected)")
    by = {}
    for r in rel:
        by.setdefault(r["package"], []).append(r)
    for p in pk:
        rows = by.get(p["package"], [])
        if sum(1 for r in rows if r.get("carries")) != p["n_carrying_releases"]:
            problems.append(f"carrying count mismatch: {p['package']}")
    for x in problems[:50]:
        print("PROBLEM", x)
    print(f"checked {len(rel)} releases, {len(pk)} packages: {len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
