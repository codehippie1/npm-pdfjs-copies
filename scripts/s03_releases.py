"""Step 3: every release of every package found to carry PDF.js in step 2.

For each hit package: the full packument (publish times), then every published version is
classified with analyse_version() from its jsDelivr file listing (file-name rules, hash or
banner confirmation, bundle scan when no named copy is found).
Output: data/releases_raw.jsonl (one row per package release), resumable.
"""
import os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, Http, JsonlWriter, analyse_version, big_js, listing, log, packument, read_jsonl, reference  # noqa
from s02_screen import summary, ordered_versions  # noqa: E402

MAX_VERSIONS = 1500  # no hit package comes close; guard only
MAX_BUNDLE_SCANNED = 200  # per package: releases beyond this (evenly spaced) skip the bundle scan


def screen_rows():
    seen = {}
    for r in read_jsonl(os.path.join(DATA, "screen.jsonl")):
        seen[r["name"]] = r
    return seen


def hit_packages():
    rows = read_jsonl(os.path.join(DATA, "screen.jsonl"))
    seen = {}
    for r in rows:
        seen[r["name"]] = r  # last row wins on a resumed run
    return sorted(n for n, r in seen.items() if r.get("ever_carrier"))


def main():
    http = Http()
    reference()
    hits = hit_packages()
    out_path = os.path.join(DATA, "releases_raw.jsonl")
    done = {(r["name"], r["version"]) for r in read_jsonl(out_path)}
    log("releases: hit packages", len(hits), "rows already done", len(done))

    scr = screen_rows()
    prefer = {}
    for n in hits:
        r = scr[n]
        paths = set()
        for res in [r.get("latest") or {}] + (r.get("older") or []):
            paths |= {c["path"] for c in res.get("copies") or [] if c.get("method") == "bundle"}
        prefer[n] = paths
    tasks, meta = [], {}
    with ThreadPoolExecutor(8) as ex:
        for name, pk in zip(hits, ex.map(lambda n: packument(http, n), hits)):
            if "__error" in pk:
                meta[name] = {"error": pk["__error"]}
                continue
            t = pk.get("time") or {}
            vs = ordered_versions(pk)
            if len(vs) > MAX_VERSIONS:
                step = len(vs) / MAX_VERSIONS
                vs = [vs[int(i * step)] for i in range(MAX_VERSIONS)] + [vs[-1]]
                log("version cap applied", name, len(vs))
            if len(vs) > MAX_BUNDLE_SCANNED:
                k = MAX_BUNDLE_SCANNED
                scan_set = {vs[round(i * (len(vs) - 1) / (k - 1))] for i in range(k)}
            else:
                scan_set = set(vs)
            for v in vs:
                if (name, v) not in done:
                    tasks.append((name, v, t.get(v), v in scan_set, prefer.get(name, set())))
    log("release tasks", len(tasks))

    w = JsonlWriter(out_path)

    def one(name, v, published, scan, pref):
        files, err = listing(http, name, v)
        row = {"name": name, "version": v, "published": published}
        if files is None:
            row.update({"status": "no_listing", "err": err})
            return row
        res = analyse_version(http, name, v, files, bundle_scan=scan, max_scan_files=25, max_scan_bytes=60_000_000,
                              prefer=pref)
        row.update(summary(res))
        row["status"] = "ok"
        if not scan and not res["carries"] and big_js(files):
            row.update({"status": "not_scanned", "carries": None})  # bundle scan skipped by the per-package cap
        return row

    n = 0
    with ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(one, *t): t for t in tasks}
        for f in as_completed(futs):
            try:
                w.write(f.result())
            except Exception as e:
                log("release error", futs[f][:2], repr(e)[:200])
                continue
            n += 1
            if n % 500 == 0:
                log("releases", n, "/", len(tasks), http.stats)
    log("releases done", n, http.stats)


if __name__ == "__main__":
    main()
