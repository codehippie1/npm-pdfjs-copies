"""Step 1: the sampling frame (candidate packages) from the npm registry search API.

The search API returns at most ~5,250 results per query (paging past from=5000 wraps to the
first page), so large result sets are reached by query expansion:
  S1  PDF.js terms: pdfjs, pdf.js, keywords:pdfjs, keywords:pdf.js, pdf.worker, keywords:pdfjs-dist
      (every query is below the window: a full census of these queries)
  S2  keyword 'pdf': keywords:pdf, keywords:pdf-viewer, plus AND-expansions keywords:pdf,<kw> for
      co-occurring keywords (the API treats a comma list as AND)
  S3  text 'pdf': the plain query plus expansions 'pdf <term>' (OR semantics, but documents
      matching both terms rank first); only results whose name, description or keywords contain
      the token 'pdf' are kept
  S4  dependents of pdfjs-dist (ecosyste.ms list captured 2026-10-29 by the feasibility check;
      frozen copy in data/s4_pdfjsdist_dependents_ecosystems_2026-10-29.json)
A package belongs to the first stratum that reaches it (S1 > S2 > S3 > S4).
Outputs: data/search_raw.jsonl (every query page), data/frame.jsonl, data/frame_meta.json
"""
import collections, json, os, re, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, Http, JsonlWriter, jdump, jload, log, read_jsonl  # noqa: E402

PAGE = 250
MAX_FROM = 5000
S1_Q = ["pdfjs", "pdf.js", "keywords:pdfjs", "keywords:pdf.js", "pdf.worker", "keywords:pdfjs-dist"]
S2_Q = ["keywords:pdf", "keywords:pdf-viewer"]
S3_Q = ["pdf"]
TOKEN = re.compile(r"[a-z0-9]+")
STOP = set("""a an the and or of for to in on with from by is are be as at it its this that your you
use using used can will into via based js javascript node nodejs npm package module library lib simple
easy fast small tiny lightweight api tool tools plugin component components support supports file
files create generate make new more not no all any some other also just one two get set like
""".split())

http = Http()
raw_path = os.path.join(DATA, "search_raw.jsonl")
done_q = {}
for r in read_jsonl(raw_path):
    done_q.setdefault(r["query"], {})[r["from"]] = r
raw = JsonlWriter(raw_path)


def pdf_member(o):
    text = " ".join([o["name"], o.get("description") or "", " ".join(o.get("keywords") or [])]).lower()
    return "pdf" in TOKEN.findall(text)


def search(q, stop_when=None):
    """All reachable pages of one query. Cached per (query, from) in search_raw.jsonl."""
    seen, out, total = set(), [], None
    frm = 0
    while frm <= MAX_FROM:
        page = done_q.get(q, {}).get(frm)
        if page is None:
            u = "https://registry.npmjs.org/-/v1/search?" + urllib.parse.urlencode({"text": q, "size": PAGE, "from": frm})
            for attempt in range(6):
                d = http.json(u, cache=False)
                if "objects" in d:
                    break
                time.sleep(10 * (attempt + 1))
            if "objects" not in d:
                log("search failed", q, frm, d.get("__error"))
                break
            objs = []
            for o in d["objects"]:
                p = o["package"]
                objs.append({"name": p["name"], "version": p.get("version"),
                             "description": (p.get("description") or "")[:300],
                             "keywords": [k for k in (p.get("keywords") or []) if isinstance(k, str)][:30],
                             "date": p.get("date"), "monthly": (o.get("downloads") or {}).get("monthly"),
                             "score": o.get("searchScore")})
            page = {"query": q, "from": frm, "total": d.get("total"), "fetched": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "objects": objs}
            raw.write(page)
            done_q.setdefault(q, {})[frm] = page
        total = page["total"]
        objs = page["objects"]
        new = [o for o in objs if o["name"] not in seen]
        if not new:  # empty or wrapped to page 0
            break
        for i, o in enumerate(objs):
            if o["name"] not in seen:
                seen.add(o["name"])
                out.append(dict(o, rank=frm + i))
        frm += PAGE
        if frm >= (total or 0):
            break
        if stop_when and stop_when(objs):
            break
    return {"query": q, "total": total, "results": out}


def main():
    meta = {"queries": {}}
    res = {}
    for q in S1_Q + S2_Q + S3_Q:
        res[q] = search(q)
        log("search", q, "total", res[q]["total"], "reached", len(res[q]["results"]))

    # ---- S2 expansions: keywords:pdf,<kw> (AND)
    reached_kw = {o["name"]: o for q in S2_Q for o in res[q]["results"]}
    tried = set()
    for rnd in range(4):
        co = collections.Counter(k.lower().strip() for o in reached_kw.values() for k in o["keywords"])
        terms = [k for k, c in co.most_common() if c >= 2 and k not in ("pdf",) and re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,40}", k)
                 and k not in tried][:150]
        if not terms:
            break
        before = len(reached_kw)
        for k in terms:
            tried.add(k)
            q = f"keywords:pdf,{k}"
            r = search(q)
            res[q] = r
            for o in r["results"]:
                if "pdf" in [x.lower() for x in o["keywords"]]:
                    reached_kw.setdefault(o["name"], o)
        log(f"S2 round {rnd}: {len(terms)} AND-queries, reached {before} -> {len(reached_kw)} of {res['keywords:pdf']['total']}")
        if len(reached_kw) - before < 50:
            break

    # ---- S3 expansions: 'pdf <term>' (OR, both-term matches rank first)
    reached_tx = {o["name"]: o for o in res["pdf"]["results"]}
    for o in list(reached_kw.values()):
        if pdf_member(o):
            reached_tx.setdefault(o["name"], o)
    tried_t = set()
    low_yield = 0
    for rnd in range(3):
        co = collections.Counter()
        for o in reached_tx.values():
            toks = set(TOKEN.findall((o.get("description") or "").lower())) | {
                t for k in o["keywords"] for t in TOKEN.findall(k.lower())}
            co.update(t for t in toks if t not in STOP and t != "pdf" and len(t) > 2 and not t.isdigit())
        terms = [t for t, c in co.most_common(400) if t not in tried_t][:120]
        before_round = len(reached_tx)
        for t in terms:
            tried_t.add(t)
            q = f"pdf {t}"
            r = search(q, stop_when=lambda objs: sum(pdf_member(o) for o in objs) < 0.1 * max(1, len(objs)))
            res[q] = r
            before = len(reached_tx)
            for o in r["results"]:
                if pdf_member(o):
                    reached_tx.setdefault(o["name"], o)
            gain = len(reached_tx) - before
            low_yield = low_yield + 1 if gain < 15 else 0
            if low_yield >= 25:
                break
        log(f"S3 round {rnd}: reached {before_round} -> {len(reached_tx)} of ~{res['pdf']['total']}")
        if low_yield >= 25 or len(reached_tx) - before_round < 100:
            break

    # ---- S4 frozen list
    s4 = jload(os.path.join(DATA, "s4_pdfjsdist_dependents_ecosystems_2026-10-29.json"))
    s4_names = {d["name"]: d.get("version") for d in s4 if d.get("name")}

    # ---- assemble
    s1 = {}
    for q in S1_Q:
        for o in res[q]["results"]:
            s1.setdefault(o["name"], o)
    frame = {}
    for name, o in s1.items():
        frame[name] = {"name": name, "stratum": "S1", "latest": o["version"], "in": ["S1"]}
    for name, o in reached_kw.items():
        f = frame.setdefault(name, {"name": name, "stratum": "S2", "latest": o["version"], "in": []})
        f["in"].append("S2")
    for name, o in reached_tx.items():
        f = frame.setdefault(name, {"name": name, "stratum": "S3", "latest": o["version"], "in": []})
        f["in"].append("S3")
    for name, v in s4_names.items():
        f = frame.setdefault(name, {"name": name, "stratum": "S4", "latest": None, "in": []})
        f["in"].append("S4")
    plain_rank = {o["name"]: o["rank"] for o in res["pdf"]["results"]}
    kw_rank = {o["name"]: o["rank"] for o in res["keywords:pdf"]["results"]}
    info = {}
    for q, r in res.items():
        for o in r["results"]:
            info.setdefault(o["name"], o)
    with open(os.path.join(DATA, "frame.jsonl"), "w", encoding="utf-8") as f:
        for name in sorted(frame):
            row = frame[name]
            o = info.get(name, {})
            row.update({"rank_pdf_text": plain_rank.get(name), "rank_kw_pdf": kw_rank.get(name),
                        "search_monthly": o.get("monthly"), "description": o.get("description"),
                        "pdf_token": pdf_member(o) if o else None})
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta = {
        "queries": {q: {"total": r["total"], "reached": len(r["results"])} for q, r in res.items()},
        "S1_n": len(s1),
        "S2_total_keywords_pdf": res["keywords:pdf"]["total"], "S2_reached": len(reached_kw),
        "S3_total_text_pdf": res["pdf"]["total"], "S3_reached_pdf_token": len(reached_tx),
        "S4_n": len(s4_names),
        "frame_by_stratum": collections.Counter(r["stratum"] for r in frame.values()),
        "n_queries": len(res),
    }
    jdump(os.path.join(DATA, "frame_meta.json"), meta)
    log("frame:", len(frame), dict(meta["frame_by_stratum"]), "S2 reached", len(reached_kw), "S3 reached", len(reached_tx))


if __name__ == "__main__":
    main()
