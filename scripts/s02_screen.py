"""Step 2: screen every package in the frame.

For every package: the latest release is classified with analyse_version() (file-name rules,
content confirmation by hash or banner, and the bundle scan when no named copy is found).
For S1, S4 and a seeded random 1,000-package subsample of S2+S3, up to 5 older releases
(evenly spaced in publish order) are screened as well, to find packages that carried PDF.js in
the past but not in their latest release.
Output: data/screen.jsonl (one row per package), resumable.
"""
import json, os, random, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, Http, JsonlWriter, analyse_version, listing, log, packument, read_jsonl, reference  # noqa

OLDER_K = 5
OLD_SUBSAMPLE = 1000
SEED = 20261030
SUMMARY_KEYS = ("carries", "via", "pdfjs_version", "pdfjs_upstream", "pdfjs_base_version", "pdfjs_versions_all",
                "id_method", "build_type", "worker_present", "n_files", "n_other_files", "shape", "n_name_candidates",
                "bundle_files_scanned", "bundle_scan_capped", "bcmap")


def summary(r):
    d = {k: r[k] for k in SUMMARY_KEYS}
    d["copies"] = [{k: c.get(k) for k in ("path", "kind", "method", "version", "how")} for c in r["copies"]][:12]
    d["rejected"] = r["rejected_candidates"][:12]
    return d


def even_older(versions, latest, k):
    vs = [v for v in versions if v != latest]
    if len(vs) <= k:
        return vs
    idx = sorted({round(i * (len(vs) - 1) / (k - 1)) for i in range(k)})
    return [vs[i] for i in idx]


def ordered_versions(p):
    t = p.get("time") or {}
    vs = list((p.get("versions") or {}).keys())
    return sorted(vs, key=lambda v: t.get(v) or "")


def screen_one(http, row, deep):
    name = row["name"]
    out = {"name": name, "stratum": row["stratum"], "in": row["in"], "deep": deep}
    pk = None
    latest = row.get("latest")
    if deep or not latest:
        pk = packument(http, name)
        if "__error" in pk:
            out["status"] = f"no_packument_{pk['__error']}"
            return out
        if (pk.get("time") or {}).get("unpublished") or not pk.get("versions"):
            out["status"] = "unpublished"
            return out
        latest = (pk.get("dist-tags") or {}).get("latest") or ordered_versions(pk)[-1]
    files, err = listing(http, name, latest)
    if files is None and pk is None:
        pk = packument(http, name)
        if "__error" not in pk and pk.get("versions") and not (pk.get("time") or {}).get("unpublished"):
            l2 = (pk.get("dist-tags") or {}).get("latest")
            if l2 and l2 != latest:
                latest = l2
                files, err = listing(http, name, latest)
        elif "__error" not in pk:
            out["status"] = "unpublished"
            return out
    out["latest_version"] = latest
    if files is None:
        out["status"] = "no_listing"
        out["err"] = err
        return out
    out["status"] = "ok"
    out["latest"] = summary(analyse_version(http, name, latest, files, max_scan_files=25, max_scan_bytes=60_000_000))
    out["older"] = []
    if deep and pk is not None:
        vs = ordered_versions(pk)
        out["n_versions"] = len(vs)
        for v in even_older(vs, latest, OLDER_K):
            f2, e2 = listing(http, name, v)
            if f2 is None:
                out["older"].append({"version": v, "status": "no_listing", "err": e2})
                continue
            res = summary(analyse_version(http, name, v, f2, max_scan_files=25, max_scan_bytes=60_000_000))
            res["version"] = v
            res["status"] = "ok"
            out["older"].append(res)
    out["latest_carrier"] = out["latest"]["carries"]
    out["ever_carrier"] = out["latest_carrier"] or any(o.get("carries") for o in out["older"])
    return out


def main():
    http = Http()
    reference()
    # optional argument: a provisional frame (used to start S1/S4 before the search expansion finished;
    # strata are always re-read from data/frame.jsonl by the later steps)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    frame = read_jsonl(args[0] if args else os.path.join(DATA, "frame.jsonl"))
    rnd = random.Random(SEED)
    s23 = sorted(r["name"] for r in frame if r["stratum"] in ("S2", "S3"))
    sub = set(rnd.sample(s23, min(OLD_SUBSAMPLE, len(s23))))
    if "--no-subsample" in sys.argv:  # provisional frames: the subsample is drawn from the final frame only
        sub = set()
    out_path = os.path.join(DATA, "screen.jsonl")
    done = {}
    for r in read_jsonl(out_path):
        done[r["name"]] = r
    # a package screened earlier without its older releases is screened again if it is now in the
    # subsample (readers keep the last row per package)
    todo = [r for r in frame if r["name"] not in done
            or (r["name"] in sub and not done[r["name"]].get("deep") and done[r["name"]].get("status") == "ok")]
    # high-yield strata first so partial runs are still useful
    order = {"S1": 0, "S4": 1, "S2": 2, "S3": 3}
    todo.sort(key=lambda r: (order[r["stratum"]], r["name"]))
    log("screen: frame", len(frame), "done", len(done), "todo", len(todo), "older-version subsample", len(sub))
    w = JsonlWriter(out_path)
    n = 0
    with ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(screen_one, http, r, r["stratum"] in ("S1", "S4") or r["name"] in sub): r for r in todo}
        for f in as_completed(futs):
            r = futs[f]
            try:
                res = f.result()
            except Exception as e:  # keep going; the row is retried on the next run
                log("screen error", r["name"], repr(e)[:200])
                continue
            w.write(res)
            n += 1
            if n % 250 == 0:
                log("screen", n, "/", len(todo), http.stats)
    log("screen done", n, http.stats)


if __name__ == "__main__":
    main()
