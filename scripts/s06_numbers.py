"""Step 6: headline figures with confidence intervals -> numbers.md and data/numbers.json (no network).

Intervals:
  * proportions from a census of the frame: Wilson 95% intervals (they describe sampling
    uncertainty only when the figure is read as an estimate for a wider population);
  * figures over releases: cluster bootstrap over packages (2,000 resamples, seed fixed), because
    releases of one package are not independent;
  * unreached parts of the search space: Wilson interval of the hit rate in the nearest reached
    segment (results reached only through query expansion), times the unreached count.
"""
import collections, json, math, os, random, statistics, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import COLLECTION_DATE, DATA, DATASET, FIX_VERSION, jdump, jload, read_jsonl, reference, vkey, wilson  # noqa

B = 2000
rng = random.Random(4367)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def ci_s(lo, hi, d=1):
    return f"[{100 * lo:.{d}f}, {100 * hi:.{d}f}]"


def quant(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = (len(xs) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def cluster_boot(groups, stat):
    """groups: list of lists (one list of values per package). stat: fn(flat list) -> number."""
    vals = []
    n = len(groups)
    if n == 0:
        return (None, None)
    for _ in range(B):
        flat = []
        for _ in range(n):
            flat.extend(groups[rng.randrange(n)])
        if flat:
            v = stat(flat)
            if v is not None:
                vals.append(v)
    return (quant(vals, 0.025), quant(vals, 0.975))


def km(durations):
    """Kaplan-Meier. durations: list of (days, event_bool). Returns step list [(t, S(t))]."""
    times = sorted({d for d, e in durations if e})
    s, out = 1.0, []
    for t in times:
        at_risk = sum(1 for d, e in durations if d >= t)
        ev = sum(1 for d, e in durations if e and d == t)
        if at_risk:
            s *= 1 - ev / at_risk
        out.append((t, s))
    return out


def km_at(curve, t):
    s = 1.0
    for tt, ss in curve:
        if tt <= t:
            s = ss
        else:
            break
    return s


def km_median(curve):
    for t, s in curve:
        if s <= 0.5:
            return t
    return None


def main():
    ref = reference()
    fix_date = ts(ref["fix_release_date"])
    coll = datetime.fromisoformat(COLLECTION_DATE + "T00:00:00+00:00")
    meta = jload(os.path.join(DATA, "frame_meta.json"))
    frame = {r["name"]: r for r in read_jsonl(os.path.join(DATA, "frame.jsonl"))}
    screen = {}
    for r in read_jsonl(os.path.join(DATA, "screen.jsonl")):
        if r["name"] in frame:  # strata come from the final frame
            r["stratum"], r["in"] = frame[r["name"]]["stratum"], frame[r["name"]]["in"]
            screen[r["name"]] = r
    from s02_screen import OLD_SUBSAMPLE, SEED
    s23 = sorted(n for n, r in frame.items() if r["stratum"] in ("S2", "S3"))
    subsample = set(random.Random(SEED).sample(s23, min(OLD_SUBSAMPLE, len(s23))))
    kw = {}
    for p in read_jsonl(os.path.join(DATA, "search_raw.jsonl")):
        for o in p["objects"]:
            kw.setdefault(o["name"], [k.lower() for k in o.get("keywords") or []])
    rels = read_jsonl(os.path.join(DATASET, "releases.jsonl"))
    pkgs = {r["package"]: r for r in read_jsonl(os.path.join(DATASET, "packages.jsonl"))}
    UP = {"pdfjs-dist"}
    N = {}  # every number that goes into numbers.md
    L = []  # markdown lines

    # ------------------------------------------------------------------ coverage
    strata = ["S1", "S2", "S3", "S4"]
    cov = {}
    for s in strata:
        rows = [screen[n] for n in screen if screen[n]["stratum"] == s]
        ok = [r for r in rows if r.get("status") == "ok"]
        cov[s] = {
            "frame": sum(1 for r in frame.values() if r["stratum"] == s),
            "screened": len(rows), "ok": len(ok),
            "no_listing": sum(1 for r in rows if r.get("status") == "no_listing"),
            "unpublished": sum(1 for r in rows if r.get("status") == "unpublished"),
            "other_fail": sum(1 for r in rows if r.get("status") not in ("ok", "no_listing", "unpublished")),
            "deep": sum(1 for r in ok if r.get("deep")),
            "latest_carriers": sum(1 for r in ok if r.get("latest_carrier") and r["name"] not in UP),
            "latest_via_bundle": sum(1 for r in ok if r.get("latest_carrier") and r["latest"].get("via") == "bundle"
                                     and r["name"] not in UP),
            "ever_carriers": sum(1 for r in ok if r.get("ever_carrier") and r["name"] not in UP),
            "deep_ok": sum(1 for r in ok if r.get("deep")),
            "deep_former": sum(1 for r in ok if r.get("deep") and r.get("ever_carrier") and not r.get("latest_carrier")),
            "deep_not_latest": sum(1 for r in ok if r.get("deep") and not r.get("latest_carrier")),
        }
    kw_members = {n for n in frame if "pdf" in kw.get(n, [])}
    pdf_members = {n for n, r in frame.items() if r.get("pdf_token")}
    tot_kw = meta["S2_total_keywords_pdf"]
    tot_tx = meta["S3_total_text_pdf"]
    tail2 = max(0, tot_kw - len(kw_members))
    tail3 = max(0, tot_tx - len(pdf_members))
    N["coverage"] = cov
    N["kw_pdf_total"], N["kw_pdf_reached"], N["kw_pdf_unreached"] = tot_kw, len(kw_members), tail2
    N["text_pdf_total"], N["text_pdf_reached"], N["text_pdf_unreached"] = tot_tx, len(pdf_members), tail3

    # tail rates. The unreached part lies beyond rank 5,250 of the plain query and outside the top of every
    # expansion query, i.e. the least relevant remainder. Primary proxy: the hit rate among the stratum's
    # packages in the last plain-query band (ranks 4,000-5,249). Sensitivity bound: packages reached only
    # through expansion, which are enriched for viewer-like packages by the topical expansion terms.
    def bands(stratum, rank_key):
        out = collections.defaultdict(lambda: [0, 0])
        for n, r in frame.items():
            if r["stratum"] == stratum and r.get(rank_key) is not None and screen.get(n, {}).get("status") == "ok":
                b = min(r[rank_key] // 1000, 4)
                out[b][1] += 1
                out[b][0] += 1 if screen[n].get("latest_carrier") else 0
        return dict(sorted(out.items()))

    def seg_rate(stratum, rank_key):
        seg = [screen[n] for n, r in frame.items() if r["stratum"] == stratum and r.get(rank_key) is None
               and n in screen and screen[n].get("status") == "ok"]
        return sum(1 for r in seg if r.get("latest_carrier")), len(seg)

    census = sum(cov[s]["latest_carriers"] for s in strata)
    tails = {}
    for s_, rk, tail in (("S2", "rank_kw_pdf", tail2), ("S3", "rank_pdf_text", tail3)):
        bd = bands(s_, rk)
        kb, nb = bd.get(4, [0, 0])
        ke, ne = seg_rate(s_, rk)
        lo_b, hi_b = wilson(kb, nb)
        lo_e, hi_e = wilson(ke, ne)
        tails[s_] = {"unreached": tail, "bands": {f"{b * 1000}-{b * 1000 + 999 if b < 4 else 5249}": v for b, v in bd.items()},
                     "last_band": [kb, nb, lo_b, hi_b], "expansion_only": [ke, ne, lo_e, hi_e],
                     "est": (tail * kb / nb, tail * lo_b, tail * hi_b) if (nb and tail) else (0, 0, 0),
                     "sens_hi": tail * hi_e if (ne and tail) else 0}
    t2, t3 = tails["S2"]["est"], tails["S3"]["est"]
    total_latest = (census + t2[0] + t3[0], census + t2[1] + t3[1], census + t2[2] + t3[2])
    N["latest_carriers_census"] = census
    N["tails"] = tails
    N["latest_carriers_total_est"] = total_latest
    N["latest_carriers_total_sensitivity_hi"] = census + tails["S2"]["sens_hi"] + tails["S3"]["sens_hi"]

    # former carriers (ever but not at latest) from deep screening
    deep_S23 = [screen[n] for n in subsample if n in screen and screen[n].get("deep")
                and screen[n].get("status") == "ok" and not screen[n].get("latest_carrier")]
    kf = sum(1 for r in deep_S23 if r.get("ever_carrier"))
    lof, hif = wilson(kf, len(deep_S23))
    non_lat_S23 = sum(1 for n in screen if screen[n]["stratum"] in ("S2", "S3") and screen[n].get("status") == "ok"
                      and not screen[n].get("latest_carrier"))
    former_S14 = cov["S1"]["deep_former"] + cov["S4"]["deep_former"]
    former_S23_est = (non_lat_S23 * kf / max(1, len(deep_S23)), non_lat_S23 * lof, non_lat_S23 * hif)
    N["former"] = {"S1S4_found": former_S14, "S23_sub_k": kf, "S23_sub_n": len(deep_S23),
                   "S23_est": former_S23_est, "S23_found": cov["S2"]["deep_former"] + cov["S3"]["deep_former"]}

    # ------------------------------------------------------------------ releases
    hits = [p for p in pkgs.values() if not p["is_upstream_pdfjs"] and p["n_carrying_releases"] > 0]
    R = [r for r in rels if not r["is_upstream_pdfjs"] and r["package"] in {p["package"] for p in hits}]
    car = [r for r in R if r.get("carries")]
    listed = [r for r in R if r["status"] == "ok"]
    N["hit_packages"] = len(hits)
    N["releases_listed"] = len(listed)
    N["releases_no_listing"] = sum(1 for r in R if r["status"] == "no_listing")
    N["releases_not_scanned"] = sum(1 for r in R if r["status"] == "not_scanned")
    N["releases_total"] = len(R)
    N["carrying_releases"] = len(car)
    N["id_method"] = collections.Counter(r["id_method"] for r in car)
    N["identified"] = sum(1 for r in car if r.get("pdfjs_version"))
    N["upstream_identified"] = sum(1 for r in car if r.get("pdfjs_upstream"))
    N["build_type"] = collections.Counter(r.get("build_type") for r in car)
    N["worker_present"] = sum(1 for r in car if r.get("worker_present"))
    N["major_releases"] = collections.Counter((r["pdfjs_base_version"] or "?").split(".")[0] for r in car)
    lat_car = [p for p in hits if p.get("latest_carries")]
    N["latest_carrier_pkgs"] = len(lat_car)
    N["shape_latest"] = collections.Counter(p.get("latest_shape") for p in lat_car)
    shape_any = collections.Counter()
    for p in hits:
        last = [r for r in car if r["package"] == p["package"]][-1]
        shape_any[last.get("shape")] += 1
    N["shape_last_carrying"] = shape_any

    # ------------------------------------------------------------------ recall of file-name rules
    rec = {}
    for s in strata + ["all"]:
        rows = [screen[n] for n in screen if (s == "all" or screen[n]["stratum"] == s)
                and screen[n].get("status") == "ok" and screen[n].get("latest_carrier") and n not in UP]
        fn = sum(1 for r in rows if r["latest"].get("via") == "filename")
        lo, hi = wilson(fn, len(rows))
        rec[s] = [fn, len(rows), lo, hi]
    rel_fn = sum(1 for r in car if r.get("detected_via") == "filename")
    groups = collections.defaultdict(list)
    for r in car:
        groups[r["package"]].append(1 if r.get("detected_via") == "filename" else 0)
    rlo, rhi = cluster_boot(list(groups.values()), lambda xs: sum(xs) / len(xs))
    rec["releases"] = [rel_fn, len(car), rlo, rhi]
    # precision of the file-name rules: candidates that content checks rejected
    cand_pk = [r for r in screen.values() if r.get("status") == "ok" and r["latest"].get("n_name_candidates")]
    fp = [r for r in cand_pk if r["latest"].get("via") != "filename"]
    rec["name_candidates_latest"] = len(cand_pk)
    rec["name_candidates_rejected"] = len(fp)
    N["recall"] = rec

    # ------------------------------------------------------------------ lag
    up = [r for r in car if r.get("pdfjs_upstream") and r.get("lag_days") is not None]
    g_lag = collections.defaultdict(list)
    g_beh = collections.defaultdict(list)
    for r in up:
        g_lag[r["package"]].append(r["lag_days"])
        g_beh[r["package"]].append(1 if r["behind_latest_upstream"] else 0)
    lags = [r["lag_days"] for r in up]
    N["lag"] = {
        "n_releases": len(up), "n_packages": len(g_lag),
        "median": statistics.median(lags) if lags else None,
        "median_ci": cluster_boot(list(g_lag.values()), statistics.median),
        "p25": quant(lags, .25), "p75": quant(lags, .75), "p90": quant(lags, .9),
        "share_over_365": sum(1 for x in lags if x > 365) / max(1, len(lags)),
        "share_over_365_ci": cluster_boot(list(g_lag.values()), lambda xs: sum(1 for x in xs if x > 365) / len(xs)),
        "share_behind": sum(1 for r in up if r["behind_latest_upstream"]) / max(1, len(up)),
        "share_behind_ci": cluster_boot(list(g_beh.values()), lambda xs: sum(xs) / len(xs)),
        "median_minor_lines_behind": statistics.median([r["minor_lines_behind"] for r in up]) if up else None,
        "pkg_median_of_medians": statistics.median([statistics.median(v) for v in g_lag.values()]) if g_lag else None,
    }
    by_year = {}
    for y in sorted({r["published"][:4] for r in up}):
        xs = [r for r in up if r["published"][:4] == y]
        by_year[y] = {"n": len(xs), "pkgs": len({r["package"] for r in xs}),
                      "median_lag": statistics.median([r["lag_days"] for r in xs]),
                      "share_behind": sum(1 for r in xs if r["behind_latest_upstream"]) / len(xs),
                      "share_affected": sum(1 for r in xs if r["affected_range"]) / len(xs)}
    N["lag_by_year"] = by_year
    # latest-release view (one row per package): lag at publish, age on the collection date
    lat_rows = []
    for p in lat_car:
        r = next((x for x in car if x["package"] == p["package"] and x["version"] == p["latest_version"]), None)
        if r and r.get("pdfjs_upstream") and r.get("pdfjs_release_date"):
            lat_rows.append(r)
    ages = [(coll - ts(r["pdfjs_release_date"])).days for r in lat_rows]
    N["latest_view"] = {"n": len(lat_rows), "median_lag": statistics.median([r["lag_days"] for r in lat_rows]) if lat_rows else None,
                        "median_age_days_at_collection": statistics.median(ages) if ages else None,
                        "share_behind": sum(1 for r in lat_rows if r["behind_latest_upstream"]) / max(1, len(lat_rows))}

    # ------------------------------------------------------------------ affected range (< 4.2.67)
    post = [r for r in car if r.get("published_after_fix") and r.get("pdfjs_base_version")]
    post_up = [r for r in post if r.get("pdfjs_upstream")]
    g_aff = collections.defaultdict(list)
    for r in post_up:
        g_aff[r["package"]].append(1 if r["affected_range"] else 0)
    aff_up = [r for r in post_up if r["affected_range"]]
    aff_all = [r for r in post if r["affected_range"]]
    days = [r["days_after_fix"] for r in aff_up]
    halfyear = collections.Counter()
    for r in aff_up:
        d = ts(r["published"])
        halfyear[f"{d.year}H{1 if d.month <= 6 else 2}"] += 1
    pk_post = {r["package"] for r in post_up}
    pk_aff = {r["package"] for r in aff_up}
    lo_p, hi_p = wilson(len(pk_aff), len(pk_post))
    N["affected"] = {
        "post_fix_carrying_releases": len(post), "post_fix_upstream": len(post_up),
        "post_fix_affected_upstream": len(aff_up),
        "share": len(aff_up) / max(1, len(post_up)),
        "share_ci": cluster_boot(list(g_aff.values()), lambda xs: sum(xs) / len(xs)),
        "post_fix_affected_incl_forks": len(aff_all), "post_fix_incl_forks": len(post),
        "packages_post_fix": len(pk_post), "packages_post_fix_affected": len(pk_aff),
        "packages_share": len(pk_aff) / max(1, len(pk_post)), "packages_share_ci": (lo_p, hi_p),
        "days_after_fix_median": statistics.median(days) if days else None,
        "days_after_fix_p75": quant(days, .75), "days_after_fix_max": max(days) if days else None,
        "by_half_year": dict(sorted(halfyear.items())),
        "last_affected_publish": max((r["published"] for r in aff_up), default=None),
    }
    # packages whose first carrying release came after the fix: did they start with a pre-fix PDF.js?
    first_after = []
    last_aff_days = []
    for name in pk_post:
        rows = [r for r in car if r["package"] == name and r.get("published")]
        rows.sort(key=lambda r: r["published"])
        if rows and rows[0].get("published_after_fix") and rows[0].get("pdfjs_upstream"):
            first_after.append(rows[0])
        aff = [r for r in rows if r.get("published_after_fix") and r.get("pdfjs_upstream") and r.get("affected_range")]
        if aff:
            last_aff_days.append(aff[-1]["days_after_fix"])
    k_fa = sum(1 for r in first_after if r["affected_range"])
    N["new_after_fix"] = {"n": len(first_after), "k_affected": k_fa, "share": k_fa / max(1, len(first_after)),
                          "ci": wilson(k_fa, len(first_after)),
                          "median_lag_days": statistics.median([r["lag_days"] for r in first_after if r["affected_range"]])
                          if k_fa else None}
    N["affected"]["per_package_last_affected_days_median"] = statistics.median(last_aff_days) if last_aff_days else None
    N["affected"]["per_package_last_affected_over_365"] = sum(1 for d in last_aff_days if d > 365)
    # latest-release state
    lat_up = [r for r in lat_rows]
    k_aff = sum(1 for r in lat_up if r["affected_range"])
    lo_l, hi_l = wilson(k_aff, len(lat_up))
    N["latest_affected"] = {"k": k_aff, "n": len(lat_up), "share": k_aff / max(1, len(lat_up)), "ci": (lo_l, hi_l)}
    # Kaplan-Meier: packages whose last release before the fix carried an affected copy
    surv, cohort = [], collections.Counter()
    by_pkg = collections.defaultdict(list)
    for r in R:
        if r.get("published"):
            by_pkg[r["package"]].append(r)
    for name, rows in by_pkg.items():
        rows.sort(key=lambda r: r["published"])
        pre = [r for r in rows if ts(r["published"]) < fix_date and r["status"] == "ok"]
        if not pre or not pre[-1].get("carries") or not pre[-1].get("affected_range") or not pre[-1].get("pdfjs_upstream"):
            continue
        after = [r for r in rows if ts(r["published"]) >= fix_date and r["status"] == "ok"]
        cohort["at_fix_affected"] += 1
        if not after:
            cohort["no_release_since"] += 1
            surv.append(((coll - fix_date).days, False))
            continue
        exit_r = next((r for r in after if not r.get("carries") or (r.get("pdfjs_base_version") and not r.get("affected_range"))), None)
        if exit_r:
            cohort["exited_upgrade" if exit_r.get("carries") else "exited_dropped_copy"] += 1
            surv.append(((ts(exit_r["published"]) - fix_date).days, True))
        else:
            cohort["active_still_affected"] += 1
            surv.append(((coll - fix_date).days, False))
    curve = km(surv)
    act = [d for d in surv]
    N["km"] = {"cohort": dict(cohort), "S_180": km_at(curve, 180), "S_365": km_at(curve, 365), "S_730": km_at(curve, 730),
               "median_days": km_median(curve)}
    # same, restricted to packages that published at least once after the fix (active maintainers)
    surv_a, first_still = [], 0
    for name, rows in by_pkg.items():
        pre = [r for r in rows if ts(r["published"]) < fix_date and r["status"] == "ok"]
        after = [r for r in rows if ts(r["published"]) >= fix_date and r["status"] == "ok"]
        if not pre or not after or not pre[-1].get("carries") or not pre[-1].get("affected_range") or not pre[-1].get("pdfjs_upstream"):
            continue
        exit_r = next((r for r in after if not r.get("carries") or (r.get("pdfjs_base_version") and not r.get("affected_range"))), None)
        first_still += 1 if after[0].get("carries") and after[0].get("affected_range") else 0
        surv_a.append(((ts(exit_r["published"]) - fix_date).days, True) if exit_r else ((coll - fix_date).days, False))
    curve_a = km(surv_a)
    N["km_active"] = {"n": len(surv_a), "S_90": km_at(curve_a, 90), "S_180": km_at(curve_a, 180), "S_365": km_at(curve_a, 365),
                      "S_730": km_at(curve_a, 730), "median_days": km_median(curve_a),
                      "first_post_fix_release_still_affected": first_still}

    # ------------------------------------------------------------------ weight
    dl_lat = [(p, p.get("downloads_last_month") or 0) for p in lat_car]
    tot_dl = sum(d for _, d in dl_lat)
    aff_names = {r["package"] for r in lat_up if r["affected_range"]}
    up_names = {r["package"] for r in lat_up}
    dl_up = sum(d for p, d in dl_lat if p["package"] in up_names)
    dl_aff = sum(d for p, d in dl_lat if p["package"] in aff_names)
    top10 = sum(sorted((d for _, d in dl_lat), reverse=True)[:10])
    N["weight"] = {"latest_carriers_downloads": tot_dl, "upstream_identified_downloads": dl_up,
                   "affected_downloads": dl_aff, "affected_share_weighted": dl_aff / max(1, dl_up),
                   "top10_share": top10 / max(1, tot_dl),
                   "pdfjs_dist_downloads": (pkgs.get("pdfjs-dist") or {}).get("downloads_last_month"),
                   "n_with_downloads": sum(1 for p, d in dl_lat if d)}
    N["ng2_pdfjs_viewer_is_row"] = "ng2-pdfjs-viewer" in pkgs

    jdump(os.path.join(DATA, "numbers.json"), N)
    write_md(N, ref)


def write_md(N, ref):
    cov, f = N["coverage"], N["former"]
    lo, hi = N["latest_carriers_total_est"][1], N["latest_carriers_total_est"][2]
    L = []
    a = L.append
    a("# Headline numbers (npm packages that ship their own copy of PDF.js)")
    a("")
    a(f"Collected {COLLECTION_DATE} from public npm registry data (see README.md for method and sources). "
      "Every figure below is computed by `scripts/s06_numbers.py` from the files in this folder; "
      "`data/numbers.json` holds the same values unrounded.")
    a("")
    a("Wording: a release *carries a PDF.js release in the affected range* when the newest PDF.js copy found in it is "
      "older than 4.2.67, the first release with the fix for CVE-2024-4367 (published to npm on "
      f"{ref['fix_release_date'][:10]}). Whether a carrying package is exploitable depends on how it uses PDF.js "
      "(for example, the `isEvalSupported` option and which PDFs it opens); these figures say nothing about that.")
    a("")
    a("## Abstract-ready figures")
    a("")
    la = N["latest_affected"]
    af = N["affected"]
    lg = N["lag"]
    a(f"- **{N['hit_packages']:,}** npm packages in the reached frame carry their own copy of PDF.js in at least one screened release, "
      f"across **{N['carrying_releases']:,}** carrying releases (pdfjs-dist itself excluded).")
    a(f"- **{N['latest_carriers_census']:,}** packages carry a copy in their latest release (census of the reached frame); "
      f"adding the unreached part of the 'pdf' search space gives an estimated **{N['latest_carriers_total_est'][0]:,.0f}** "
      f"(95% interval {lo:,.0f} to {hi:,.0f}).")
    a(f"- **{pct(la['share'])}** of packages whose latest release carries an identified upstream PDF.js copy carry a release in the "
      f"affected range ({la['k']:,} of {la['n']:,}; Wilson 95% {ci_s(*la['ci'])}).")
    a(f"- Of **{af['post_fix_upstream']:,}** carrying releases published after the fix (upstream-identified copies), "
      f"**{pct(af['share'])}** still carry a release in the affected range (cluster-bootstrap 95% {ci_s(*af['share_ci'])}); "
      f"these come from {af['packages_post_fix_affected']:,} of the {af['packages_post_fix']:,} packages that published a carrying "
      f"release after the fix ({pct(af['packages_share'])}, Wilson {ci_s(*af['packages_share_ci'])}).")
    a(f"- At publish time a carrying release is a median **{lg['median']:.0f} days** behind the PDF.js release it carries "
      f"(cluster-bootstrap 95% {lg['median_ci'][0]:.0f} to {lg['median_ci'][1]:.0f} days; IQR {lg['p25']:.0f} to {lg['p75']:.0f}); "
      f"**{pct(lg['share_behind'])}** ship an older PDF.js than the newest one available that day "
      f"(95% {ci_s(*lg['share_behind_ci'])}).")
    rc = N["recall"]["all"]
    a(f"- File names alone find {pct(rc[0] / max(1, rc[1]))} of the packages whose latest release carries PDF.js "
      f"({rc[0]:,} of {rc[1]:,}; Wilson {ci_s(rc[2], rc[3])}); the rest have PDF.js compiled into their own bundles.")
    nf = N["new_after_fix"]
    if nf["n"]:
        a(f"- {pct(nf['share'])} of packages that first shipped a copy after the fix started with a PDF.js release in the "
          f"affected range ({nf['k_affected']:,} of {nf['n']:,}; Wilson {ci_s(*nf['ci'])}).")
    kc = N["km"]["cohort"]
    ka = N["km_active"]
    if kc.get("at_fix_affected"):
        a(f"- Of {kc['at_fix_affected']:,} packages carrying an affected-range copy on the fix date, "
          f"{pct(kc.get('no_release_since', 0) / kc['at_fix_affected'])} have not published since; of the {ka['n']:,} that did, "
          f"{pct(ka['S_730'])} still carried an affected-range copy two years later (Kaplan-Meier).")
    a("")
    a("## Coverage per stratum")
    a("")
    a("| Stratum | Frame | Screened OK | No listing | Unpublished | Older releases screened | Latest-release carriers | Ever carriers (screened releases) |")
    a("|---|---:|---:|---:|---:|---:|---:|---:|")
    names = {"S1": "S1 PDF.js terms (full census)", "S2": "S2 keyword 'pdf' (reached part)",
             "S3": "S3 text 'pdf' (reached part)", "S4": "S4 pdfjs-dist dependents (full census)"}
    for s in ["S1", "S2", "S3", "S4"]:
        c = cov[s]
        a(f"| {names[s]} | {c['frame']:,} | {c['ok']:,} | {c['no_listing']:,} | {c['unpublished']:,} | {c['deep']:,} | "
          f"{c['latest_carriers']:,} | {c['ever_carriers']:,} |")
    a("")
    a(f"- The registry search API stops at about 5,250 results per query. Keyword 'pdf': {N['kw_pdf_reached']:,} packages with "
      f"the keyword were reached (the API reports {N['kw_pdf_total']:,} matches), so that space is covered in full. Text 'pdf': "
      f"{N['text_pdf_reached']:,} of about {N['text_pdf_total']:,} reached ({pct(N['text_pdf_reached'] / max(1, N['text_pdf_total']))}).")
    t3 = N["tails"]["S3"]
    a(f"- The unreached {t3['unreached']:,} text matches are estimated, not counted. They lie beyond rank 5,250 of the plain query "
      "and outside the top of every expansion. The S3 hit rate shows no clear trend with plain-query rank: "
      + ", ".join(f"{b}: {v[0]}/{v[1]}" for b, v in t3["bands"].items())
      + f". Using the last band ({t3['last_band'][0]}/{t3['last_band'][1]}, Wilson {ci_s(t3['last_band'][2], t3['last_band'][3], 2)}) gives "
      f"{t3['est'][0]:,.0f} (95% {t3['est'][1]:,.0f} to {t3['est'][2]:,.0f}) more latest-release carriers. As an upper sensitivity bound, the "
      f"rate of S3 packages reached only through topical expansion ({t3['expansion_only'][0]}/{t3['expansion_only'][1]}) would give at most "
      f"{N['latest_carriers_total_sensitivity_hi'] - N['latest_carriers_census']:,.0f}.")
    a(f"- Older releases (up to five per package, evenly spaced) were screened for every S1 and S4 package and for a seeded "
      f"random subsample of S2+S3. Former carriers (a copy in an older release but not the latest): {f['S1S4_found']:,} found in "
      f"S1+S4; in the S2+S3 subsample {f['S23_sub_k']} of {f['S23_sub_n']:,} non-carrying packages, which scales to about "
      f"{f['S23_est'][0]:,.0f} (95% {f['S23_est'][1]:,.0f} to {f['S23_est'][2]:,.0f}) across reached S2+S3; only the "
      f"{f['S23_found']:,} found are in the release table.")
    a("")
    a("## Detection and recall")
    a("")
    rc = N["recall"]
    a(f"- Identification of carrying releases: {dict(N['id_method'])} (hash = byte-identical to a pdfjs-dist file; banner = "
      "version string read from the named file; bundle = PDF.js signatures found inside another JS bundle).")
    a(f"- Releases of hit packages: {N['releases_total']:,}; {N['releases_listed']:,} classified, {N['releases_no_listing']:,} "
      f"without a jsDelivr file list, {N['releases_not_scanned']:,} left unclassified by the per-package cap of 200 "
      "bundle-scanned releases (they hold no named copy, so they could only carry a bundled one).")
    a(f"- PDF.js version identified for {N['identified']:,} of {N['carrying_releases']:,} carrying releases; "
      f"{N['upstream_identified']:,} map to a published pdfjs-dist version, the rest are custom or fork builds.")
    a(f"- Recall of the file-name rules against the full bundle scan, latest releases: "
      + "; ".join(f"{s} {rc[s][0]}/{rc[s][1]} = {pct(rc[s][0] / max(1, rc[s][1]))} (Wilson {ci_s(rc[s][2], rc[s][3])})"
                  for s in ["S1", "S2", "S3", "S4", "all"]) + ".")
    a(f"- Over carrying releases: {rc['releases'][0]:,} of {rc['releases'][1]:,} = {pct(rc['releases'][0] / max(1, rc['releases'][1]))} "
      f"(cluster-bootstrap {ci_s(rc['releases'][2], rc['releases'][3])}).")
    a(f"- Precision of the file-name rules alone: {rc['name_candidates_rejected']:,} of {rc['name_candidates_latest']:,} "
      "latest releases with a PDF.js-like file name had no PDF.js content (other PDF engines' workers, renamed files, "
      "character-map-only packages); content checks remove these.")
    a("")
    a("## What the copies are")
    a("")
    a(f"- PDF.js major version in carrying releases: {dict(sorted(N['major_releases'].items()))}.")
    a(f"- Build type in carrying releases: {dict(N['build_type'])}; worker present in {N['worker_present']:,} "
      f"({pct(N['worker_present'] / max(1, N['carrying_releases']))}).")
    a(f"- Shape of the last carrying release per package: {dict(N['shape_last_carrying'])} "
      "(republication = 3 or fewer files outside the PDF.js layout; embedded = a larger package around the copy).")
    a("")
    a("## Lag behind upstream at publish time")
    a("")
    a(f"- {lg['n_releases']:,} carrying releases from {lg['n_packages']:,} packages with an upstream-identified copy and a publish date.")
    a(f"- Lag (publish date minus the carried PDF.js release date): median {lg['median']:.0f} days "
      f"(95% {lg['median_ci'][0]:.0f} to {lg['median_ci'][1]:.0f}), P25 {lg['p25']:.0f}, P75 {lg['p75']:.0f}, P90 {lg['p90']:.0f}; "
      f"per-package median of medians {lg['pkg_median_of_medians']:.0f} days.")
    a(f"- More than a year behind: {pct(lg['share_over_365'])} (95% {ci_s(*lg['share_over_365_ci'])}). "
      f"Behind the newest upstream release on publish day: {pct(lg['share_behind'])} (95% {ci_s(*lg['share_behind_ci'])}); "
      f"median {lg['median_minor_lines_behind']} minor release lines behind.")
    lv = N["latest_view"]
    a(f"- Latest releases only ({lv['n']:,} packages): median lag at publish {lv['median_lag']:.0f} days; on {COLLECTION_DATE} "
      f"the carried PDF.js release is a median {lv['median_age_days_at_collection']:.0f} days old; {pct(lv['share_behind'])} "
      "were already behind upstream when published.")
    a("")
    a("| Publish year | Carrying releases | Packages | Median lag (days) | Behind newest upstream | In affected range |")
    a("|---|---:|---:|---:|---:|---:|")
    for y, d in N["lag_by_year"].items():
        a(f"| {y} | {d['n']:,} | {d['pkgs']:,} | {d['median_lag']:.0f} | {pct(d['share_behind'])} | {pct(d['share_affected'])} |")
    a("")
    a("## Shipping the affected range after the fix (29 Apr 2024)")
    a("")
    a(f"- Carrying releases published after the fix: {af['post_fix_upstream']:,} with an upstream-identified copy; "
      f"{af['post_fix_affected_upstream']:,} of them ({pct(af['share'])}, 95% {ci_s(*af['share_ci'])}) carry a release in the "
      f"affected range. Counting custom and fork builds by their version number: {af['post_fix_affected_incl_forks']:,} of "
      f"{af['post_fix_incl_forks']:,}.")
    a(f"- These affected-range releases were published a median {af['days_after_fix_median']:.0f} days after the fix "
      f"(P75 {af['days_after_fix_p75']:.0f}, latest {af['days_after_fix_max']:.0f} days; most recent on "
      f"{(af['last_affected_publish'] or '')[:10]}). By half-year: {af['by_half_year']}.")
    nf = N["new_after_fix"]
    if nf["n"]:
        a(f"- Packages whose first carrying release came after the fix: {nf['n']:,}; {nf['k_affected']:,} of them "
          f"({pct(nf['share'])}, Wilson {ci_s(*nf['ci'])}) started with a PDF.js release in the affected range"
          + (f", a median {nf['median_lag_days']:.0f} days behind upstream." if nf['median_lag_days'] is not None else "."))
    a(f"- Per package, the last affected-range release after the fix came a median "
      f"{af['per_package_last_affected_days_median'] or 0:.0f} days after it; {af['per_package_last_affected_over_365']:,} of the "
      f"{af['packages_post_fix_affected']:,} packages published one more than a year after the fix.")
    k = N["km"]
    a(f"- Packages whose last release before the fix carried an affected-range copy: {k['cohort'].get('at_fix_affected', 0):,}. "
      f"Since then {k['cohort'].get('no_release_since', 0):,} published nothing, {k['cohort'].get('exited_upgrade', 0):,} moved "
      f"to 4.2.67 or later, {k['cohort'].get('exited_dropped_copy', 0):,} stopped shipping a copy, and "
      f"{k['cohort'].get('active_still_affected', 0):,} kept publishing with an affected-range copy.")
    a(f"- Kaplan-Meier, share still carrying an affected-range copy (all of that cohort, no-release packages censored): "
      f"{pct(k['S_180'])} at 180 days, {pct(k['S_365'])} at 1 year, {pct(k['S_730'])} at 2 years; median "
      f"{'not reached' if k['median_days'] is None else str(k['median_days']) + ' days'}.")
    ka = N["km_active"]
    a(f"- Restricted to the {ka['n']:,} of them that published again after the fix ({ka['first_post_fix_release_still_affected']:,} "
      f"of whose first post-fix release still carried an affected-range copy): {pct(ka['S_90'])} still affected at 90 days, "
      f"{pct(ka['S_365'])} at 1 year, {pct(ka['S_730'])} at 2 years; median "
      f"{'not reached' if ka['median_days'] is None else str(ka['median_days']) + ' days'}.")
    a(f"- Latest releases: {la['k']:,} of {la['n']:,} packages ({pct(la['share'])}, Wilson {ci_s(*la['ci'])}) carry a release "
      "in the affected range.")
    a("")
    a("## Weighted by use (npm downloads, last month)")
    a("")
    w = N["weight"]
    a(f"- Packages whose latest release carries a copy: {w['latest_carriers_downloads']:,} downloads in the last month "
      f"({w['n_with_downloads']:,} packages with any). The ten largest account for {pct(w['top10_share'])}.")
    a(f"- Weighted by downloads, {pct(w['affected_share_weighted'])} of upstream-identified latest-release carriers' downloads "
      "go to packages carrying a release in the affected range.")
    if w.get("pdfjs_dist_downloads"):
        a(f"- For scale: pdfjs-dist had {w['pdfjs_dist_downloads']:,} downloads in the same window.")
    a("")
    a("## Notes")
    a("")
    a("- `ng2-pdfjs-viewer`, maintained by the owner of this dataset, is one row in the data and is handled exactly like every "
      "other row.")
    a("- No package or maintainer is named in this summary; the data files list packages.")
    a("- Against the one-day feasibility check (about 926 latest-release carriers, 95% range 742 to 1,290): the reached "
      "frame alone now holds more. Three things moved the figure: the bundle scan now runs on every package and also "
      "recognises minified display-layer code (the check's sample scan looked for the worker's version-check message "
      "or the `pdfjsVersion` name, which minified display-layer bundles lack); the frame grew "
      "through query expansion; and file-name hits now count only when their content is PDF.js. The check's search "
      "pools were also smaller than it reported (the search window wraps after about 5,250 results, not 10,000).")
    a("- Counts are lower bounds for the reached frame: the bundle scan skips JS files under 150 kB, caps at 25 files and 60 MB "
      "per release, and cannot see copies that are loaded from a CDN at run time.")
    with open(os.path.join(DATASET, "numbers.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
