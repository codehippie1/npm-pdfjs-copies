"""Step 0: reference data from pdfjs-dist (Mozilla's official npm build of PDF.js).

For every published pdfjs-dist version: its publish time (packument `time`) and the SHA-256 of
every file (jsDelivr flat listing). JS files over 50 kB go into `js_hashes` (hash -> [[version,
path]]), used to identify byte-identical copies; every file hash goes into `all_file_hashes`,
used to tell republications from embeddings.
Output: data/pdfjs_reference.json
"""
import os, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Http, DATA, jdump, listing, log, packument, vkey, JS_EXT, SKIP_EXT  # noqa: E402


def main():
    http = Http()
    p = packument(http, "pdfjs-dist")
    times = p["time"]
    versions = sorted(p["versions"], key=lambda v: (vkey(v) or (0, 0, 0), v))
    log("pdfjs-dist versions:", len(versions))

    def one(v):
        files, err = listing(http, "pdfjs-dist", v)
        return v, files, err

    js_hashes, all_hashes, missing = {}, set(), []
    with ThreadPoolExecutor(8) as ex:
        for i, (v, files, err) in enumerate(ex.map(one, versions)):
            if files is None:
                missing.append([v, err])
                continue
            for f in files:
                all_hashes.add(f["hash"])
                if JS_EXT.search(f["name"]) and not f["name"].endswith(SKIP_EXT) and (f.get("size") or 0) > 50_000:
                    js_hashes.setdefault(f["hash"], []).append([v, f["name"]])
            if i % 200 == 0:
                log("reference", i, "/", len(versions), http.stats)
    stable = [v for v in versions if "-" not in v]
    out = {
        "source": "registry.npmjs.org/pdfjs-dist + data.jsdelivr.com flat listings",
        "versions": versions,
        "stable_versions": stable,
        "release_date": {v: times.get(v) for v in versions},
        "fix_version": "4.2.67",
        "fix_release_date": times.get("4.2.67"),
        "listing_missing": missing,
        "js_hashes": js_hashes,
        "all_file_hashes": sorted(all_hashes),
    }
    jdump(os.path.join(DATA, "pdfjs_reference.json"), out)
    log("reference done: versions", len(versions), "js hashes", len(js_hashes), "all hashes", len(all_hashes),
        "missing", len(missing), "4.2.67 released", times.get("4.2.67"))


if __name__ == "__main__":
    main()
