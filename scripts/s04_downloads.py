"""Step 4: last-month npm downloads for every hit package (api.npmjs.org point API).

Unscoped names go in bulk requests of up to 128 names (the API's limit); scoped names, which
the bulk endpoint does not accept, are fetched one at a time. Paced and backed off by Http.
Output: data/downloads.json {name: {downloads, start, end}}
"""
import os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, Http, jdump, jload, log  # noqa: E402
from s03_releases import hit_packages  # noqa: E402

BULK = 128


def main():
    http = Http()
    names = hit_packages()
    path = os.path.join(DATA, "downloads.json")
    out = jload(path, {}) or {}
    todo = [n for n in names if n not in out]
    unscoped = [n for n in todo if not n.startswith("@")]
    scoped = [n for n in todo if n.startswith("@")]
    log("downloads: todo", len(todo), "unscoped", len(unscoped), "scoped", len(scoped))
    for i in range(0, len(unscoped), BULK):
        chunk = unscoped[i:i + BULK]
        u = "https://api.npmjs.org/downloads/point/last-month/" + ",".join(urllib.parse.quote(n, safe="") for n in chunk)
        d = http.json(u, cache=False)
        if "__error" in d:
            log("bulk failed", d.get("__error"), "falling back to single requests")
            scoped.extend(chunk)
            continue
        if len(chunk) == 1:
            d = {chunk[0]: d}
        for n in chunk:
            x = d.get(n)
            out[n] = {"downloads": x.get("downloads") if x else None,
                      "start": x.get("start") if x else None, "end": x.get("end") if x else None}
        jdump(path, out)
    for j, n in enumerate(scoped):
        d = http.json("https://api.npmjs.org/downloads/point/last-month/" + urllib.parse.quote(n, safe="@/"),
                      cache=False)
        out[n] = {"downloads": d.get("downloads"), "start": d.get("start"), "end": d.get("end"),
                  "error": d.get("__error")}
        if j % 50 == 0:
            jdump(path, out)
    out = {n: out[n] for n in names if n in out}  # only packages that are hits in this run
    jdump(path, out)
    log("downloads done", len(out))


if __name__ == "__main__":
    main()
