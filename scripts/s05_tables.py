"""Step 5: build the published tables (no network).

  releases.csv / releases.jsonl  one row per release of every hit package
  packages.csv / packages.jsonl  one row per hit package
The pdfjs-dist package itself is kept as a row with is_upstream_pdfjs = true and is left out
of every statistic.
"""
import csv, json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, DATASET, FIX_VERSION, jload, log, read_jsonl, reference, vkey  # noqa: E402

UPSTREAM = {"pdfjs-dist"}


def ts(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


REL_COLS = ["package", "version", "published", "status", "carries", "pdfjs_version", "pdfjs_versions_all",
            "pdfjs_upstream", "pdfjs_base_version", "pdfjs_release_date", "build_type", "worker_present",
            "id_method", "detected_via", "shape", "n_files", "n_other_files", "lag_days",
            "latest_upstream_at_publish", "behind_latest_upstream", "minor_lines_behind", "affected_range",
            "published_after_fix", "days_after_fix", "is_upstream_pdfjs"]
PKG_COLS = ["package", "stratum", "strata_all", "latest_version", "latest_published", "n_versions",
            "n_versions_listed", "n_carrying_releases", "first_carrying_version", "first_carrying_published",
            "last_carrying_version", "last_carrying_published", "latest_carries", "latest_pdfjs_version",
            "latest_pdfjs_upstream", "latest_affected_range", "ever_affected_range",
            "affected_range_release_after_fix", "detected_via", "latest_shape", "pdfjs_versions_carried",
            "downloads_last_month", "downloads_period", "is_upstream_pdfjs"]


def main():
    ref = reference()
    rdate = {v: ts(d) for v, d in ref["release_date"].items()}
    fix_date = ts(ref["fix_release_date"])
    by_date = sorted(((d, v) for v, d in rdate.items() if d), key=lambda x: x[0])

    def upstream_at(t):
        best = None
        for d, v in by_date:
            if d <= t:
                if best is None or vkey(v) > vkey(best):
                    best = v
            else:
                break
        return best

    frame = {r["name"]: r for r in read_jsonl(os.path.join(DATA, "frame.jsonl"))}
    screen = {}
    for r in read_jsonl(os.path.join(DATA, "screen.jsonl")):
        if r["name"] in frame:  # strata come from the final frame
            r["stratum"], r["in"] = frame[r["name"]]["stratum"], frame[r["name"]]["in"]
        screen[r["name"]] = r
    raw = {}
    for r in read_jsonl(os.path.join(DATA, "releases_raw.jsonl")):
        raw[(r["name"], r["version"])] = r
    dl = jload(os.path.join(DATA, "downloads.json"), {}) or {}

    rel_rows = []
    for (name, ver), r in sorted(raw.items(), key=lambda x: (x[0][0], x[1].get("published") or "")):
        pub = ts(r.get("published"))
        row = {"package": name, "version": ver, "published": r.get("published"), "status": r.get("status"),
               "carries": r.get("carries") if r.get("status") == "ok" else None,
               "is_upstream_pdfjs": name in UPSTREAM}
        if r.get("carries"):
            base = r.get("pdfjs_base_version")
            prd = rdate.get(base) if base else None
            lu = upstream_at(pub) if pub else None
            row.update({
                "pdfjs_version": r.get("pdfjs_version"),
                "pdfjs_versions_all": ";".join(r.get("pdfjs_versions_all") or []),
                "pdfjs_upstream": r.get("pdfjs_upstream"),
                "pdfjs_base_version": base,
                "pdfjs_release_date": prd.strftime("%Y-%m-%dT%H:%M:%SZ") if prd else None,
                "build_type": r.get("build_type"), "worker_present": r.get("worker_present"),
                "id_method": r.get("id_method"), "detected_via": r.get("via"),
                # a copy compiled into the package's own bundle is never a republication
                "shape": "embedded" if r.get("via") == "bundle" else r.get("shape"),
                "n_files": r.get("n_files"), "n_other_files": r.get("n_other_files"),
                "lag_days": round((pub - prd).total_seconds() / 86400, 2) if (pub and prd) else None,
                "latest_upstream_at_publish": lu,
                "behind_latest_upstream": (vkey(base) < vkey(lu)) if (base and lu) else None,
                "minor_lines_behind": (len({vkey(v)[:2] for d, v in by_date if pub and d <= pub
                                            and vkey(v)[:2] > vkey(base)[:2]}) if (base and pub) else None),
                "affected_range": (vkey(base) < FIX_VERSION) if base else None,
                "published_after_fix": (pub >= fix_date) if pub else None,
                "days_after_fix": round((pub - fix_date).total_seconds() / 86400, 2) if (pub and pub >= fix_date) else None,
            })
        else:
            row["n_files"] = r.get("n_files")
        rel_rows.append(row)

    by_pkg = {}
    for row in rel_rows:
        by_pkg.setdefault(row["package"], []).append(row)

    pkg_rows = []
    for name in sorted(by_pkg):
        rows = by_pkg[name]
        s = screen.get(name, {})
        latest_v = s.get("latest_version")
        lat = next((x for x in rows if x["version"] == latest_v), None)
        car = [x for x in rows if x.get("carries")]
        via = sorted({x.get("detected_via") for x in car if x.get("detected_via")})
        d = dl.get(name) or {}
        pkg_rows.append({
            "package": name, "stratum": s.get("stratum"), "strata_all": ";".join(s.get("in") or []),
            "latest_version": latest_v, "latest_published": lat.get("published") if lat else None,
            "n_versions": s.get("n_versions") or len(rows), "n_versions_listed": sum(1 for x in rows if x["status"] == "ok"),
            "n_carrying_releases": len(car),
            "first_carrying_version": car[0]["version"] if car else None,
            "first_carrying_published": car[0]["published"] if car else None,
            "last_carrying_version": car[-1]["version"] if car else None,
            "last_carrying_published": car[-1]["published"] if car else None,
            "latest_carries": lat.get("carries") if lat else None,
            "latest_pdfjs_version": lat.get("pdfjs_version") if lat else None,
            "latest_pdfjs_upstream": lat.get("pdfjs_upstream") if lat else None,
            "latest_affected_range": lat.get("affected_range") if lat else None,
            "ever_affected_range": any(x.get("affected_range") for x in car),
            "affected_range_release_after_fix": any(x.get("affected_range") and x.get("published_after_fix") for x in car),
            "detected_via": "+".join(via),
            "latest_shape": lat.get("shape") if lat else None,
            "pdfjs_versions_carried": ";".join(sorted({x["pdfjs_version"] for x in car if x.get("pdfjs_version")},
                                                      key=lambda v: vkey(v) or (0, 0, 0))),
            "downloads_last_month": d.get("downloads"),
            "downloads_period": f"{d.get('start')}..{d.get('end')}" if d.get("start") else None,
            "is_upstream_pdfjs": name in UPSTREAM,
        })

    def write(base, cols, rows):
        with open(os.path.join(DATASET, base + ".csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
        with open(os.path.join(DATASET, base + ".jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({k: r.get(k) for k in cols}, ensure_ascii=False) + "\n")

    write("releases", REL_COLS, rel_rows)
    write("packages", PKG_COLS, pkg_rows)
    log("tables: releases", len(rel_rows), "carrying", sum(1 for r in rel_rows if r.get("carries")),
        "packages", len(pkg_rows))


if __name__ == "__main__":
    main()
