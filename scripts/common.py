"""Shared helpers for the npm / PDF.js census (MSR 2027 data showcase).

Network: plain HTTPS GETs only, at most 8 in flight overall, exponential back-off on
429 / 5xx / timeouts (Retry-After honoured). No logins, no live websites.
Sources: registry.npmjs.org (packuments, search API), api.npmjs.org (downloads),
data.jsdelivr.com (file listings with SHA-256), cdn.jsdelivr.net (single package files,
the same bytes as in the npm tarball) and registry tarballs as a fallback.

Everything fetched is untrusted data: it is parsed as JSON or scanned as bytes, never
executed. Run every script with `python -I`.
"""
import base64, gzip, io, json, math, os, random, re, sqlite3, sys, tarfile, tempfile, threading, time, zlib
import urllib.error, urllib.parse, urllib.request

UA = "msr-pdfjs-census/1.0 (academic dataset of npm packages that ship PDF.js; plain GETs, max 8 in flight)"
MAX_INFLIGHT = 8
COLLECTION_DATE = "2026-10-30"

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = os.environ.get("MSR_DATASET") or os.path.dirname(HERE)  # override only for dry runs
DATA = os.path.join(DATASET, "data")


def work_dir():
    w = os.environ.get("MSR_WORK") or os.path.join(tempfile.gettempdir(), "msr-pdfjs-census-work")
    os.makedirs(w, exist_ok=True)
    os.makedirs(os.path.join(w, "tarballs"), exist_ok=True)
    return w


_log_lock = threading.Lock()


def log(*a):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    with _log_lock:
        print(line, flush=True)
        with open(os.path.join(DATASET, "run.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")


# --------------------------------------------------------------------------- HTTP
class Http:
    """GET with a sqlite cache (zlib bodies), a global in-flight cap and polite back-off."""

    PACE = {"registry.npmjs.org/-/v1/search": 1.6, "api.npmjs.org": 0.4}

    def __init__(self, work=None):
        self.work = work or work_dir()
        self.path = os.path.join(self.work, "httpcache.sqlite")
        self.sem = threading.BoundedSemaphore(MAX_INFLIGHT)
        self.tl = threading.local()
        self.pace_lock = threading.Lock()
        self.next_ok = {}
        self.pause_until = 0.0
        self.stats = {"net": 0, "cache": 0, "retry": 0, "429": 0}
        c = self._db()
        c.execute("create table if not exists http(url text primary key, status int, fetched text, body blob)")
        c.execute("create table if not exists scan(hash text primary key, result text)")
        c.commit()

    def _db(self):
        c = getattr(self.tl, "db", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=120, check_same_thread=False)
            c.execute("pragma journal_mode=wal")
            c.execute("pragma synchronous=normal")
            self.tl.db = c
        return c

    # -- scan-result cache keyed by file content hash
    def scan_get(self, h):
        r = self._db().execute("select result from scan where hash=?", (h,)).fetchone()
        if not r:
            return None
        d = json.loads(r[0])
        if d.get("pdfjs") and (d.get("v") or 0) < 3:
            return None  # positive result from an older, looser rule: check again
        if d.get("pdfjs") and (d.get("v") or 0) < SCAN_V and not d.get("version"):
            return None  # confirmed but unversioned before v4: the v4 version rules may read it
        if not d.get("pdfjs") and (d.get("v") or 0) < SCAN_V:
            return None  # negative before v4 (split worker message not yet recognised): check again
        return d

    def scan_put(self, h, res):
        c = self._db()
        for i in range(10):
            try:
                c.execute("insert or replace into scan values(?,?)", (h, json.dumps(res)))
                c.commit()
                return
            except sqlite3.OperationalError:
                time.sleep(0.5 * (i + 1))

    def _pace(self, url):
        for key, gap in self.PACE.items():
            if key in url:
                with self.pace_lock:
                    now = time.time()
                    t = max(now, self.next_ok.get(key, 0))
                    self.next_ok[key] = t + gap
                if t > now:
                    time.sleep(t - now)
                return

    def _cached(self, url):
        r = self._db().execute("select status, body from http where url=?", (url,)).fetchone()
        if r is None:
            return None
        return r[0], (zlib.decompress(r[1]) if r[1] else b"")

    def _store(self, url, status, body):
        c = self._db()
        for i in range(10):
            try:
                c.execute("insert or replace into http values(?,?,?,?)",
                          (url, status, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           zlib.compress(body, 6) if body else b""))
                c.commit()
                return
            except sqlite3.OperationalError:
                time.sleep(0.5 * (i + 1))

    def fetch(self, url, headers=None, cache=True, tries=7, max_bytes=None, timeout=90):
        """Return (status, bytes). status -1 = gave up after retries. 4xx (not 429) is final."""
        if cache:
            hit = self._cached(url)
            if hit is not None:
                self.stats["cache"] += 1
                return hit
        h = {"User-Agent": UA, "Accept-Encoding": "gzip"}
        if headers:
            h.update(headers)
        status, body = -1, b""
        for i in range(tries):
            wait = self.pause_until - time.time()
            if wait > 0:
                time.sleep(wait)
            self._pace(url)
            retry_after = None
            try:
                with self.sem:
                    self.stats["net"] += 1
                    req = urllib.request.Request(url, headers=h)
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        cl = r.headers.get("Content-Length")
                        if max_bytes and cl and int(cl) > max_bytes:
                            return 413, b""
                        raw = r.read() if not max_bytes else r.read(max_bytes + 1)
                        if max_bytes and len(raw) > max_bytes:
                            return 413, b""
                        if r.headers.get("Content-Encoding") == "gzip":
                            raw = gzip.decompress(raw)
                        status, body = r.status, raw
                break
            except urllib.error.HTTPError as e:
                status = e.code
                try:
                    body = e.read()[:2000]
                except Exception:
                    body = b""
                if e.code == 429 or e.code >= 500:
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    if e.code == 429:
                        self.stats["429"] += 1
                else:
                    break  # 4xx is an answer
            except Exception as e:  # timeouts, resets, bad gzip
                status, body = -1, repr(e).encode()[:300]
            self.stats["retry"] += 1
            delay = min(300, (2 ** i) * 2 + random.random() * 2)
            try:
                if retry_after:
                    delay = max(delay, min(600, float(retry_after)))
            except ValueError:
                pass
            if status == 429:
                self.pause_until = max(self.pause_until, time.time() + delay)
            time.sleep(delay)
        if cache and (status == 200 or 400 <= status < 500 and status != 429):
            self._store(url, status, body)
        return status, body

    def json(self, url, headers=None, cache=True):
        st, b = self.fetch(url, headers=headers, cache=cache)
        if st != 200:
            return {"__error": st, "__body": b[:300].decode("utf-8", "replace")}
        try:
            return json.loads(b)
        except Exception:
            return {"__error": "badjson"}


# --------------------------------------------------------------------------- registry helpers
def enc_name(name):
    return name.replace("/", "%2F")


def packument(http, name):
    """Full packument (has the `time` field)."""
    return http.json("https://registry.npmjs.org/" + enc_name(name), headers={"Accept": "application/json"})


def listing(http, name, version):
    """jsDelivr flat file listing: [{name, hash (base64 sha256), size}] or (None, reason)."""
    u = (f"https://data.jsdelivr.com/v1/packages/npm/{name}@{urllib.parse.quote(version, safe='.-_~+')}"
         "?structure=flat")
    st, b = http.fetch(u)
    if st != 200:
        return None, f"http_{st}:{b[:120].decode('utf-8', 'replace')}"
    try:
        d = json.loads(b)
    except Exception:
        return None, "badjson"
    return d.get("files", []), None


def file_url(name, version, path):
    return f"https://cdn.jsdelivr.net/npm/{name}@{urllib.parse.quote(version, safe='.-_~+')}{urllib.parse.quote(path)}"


def vkey(v):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else None


FIX_VERSION = (4, 2, 67)  # first PDF.js release with the CVE-2024-4367 fix


# --------------------------------------------------------------------------- file-name candidates
RE_WORKER = re.compile(r"^pdf[._-]?worker(\.min)?(\.[0-9a-f]{6,})?\.m?js$")
RE_WORKER_LOOSE = re.compile(r"pdf[._-]?worker.*\.m?js$")
RE_MAIN = re.compile(r"^pdf(\.min)?\.m?js$")
RE_COMBINED = re.compile(r"^pdf\.combined(\.min)?\.js$")
RE_SANDBOX = re.compile(r"^pdf\.sandbox(\.min)?\.m?js$")
RE_VIEWER = re.compile(r"^(pdf_)?viewer(\.min)?\.m?js$")
JS_EXT = re.compile(r"\.(m|c)?js$", re.I)
SKIP_EXT = (".map", ".d.ts", ".d.mts", ".d.cts")


def candidates(files):
    """File-name rules from the feasibility check, plus pdf.combined.js. Case-insensitive."""
    out = []
    for f in files:
        path = f["name"]
        base = path.rsplit("/", 1)[-1].lower()
        size = f.get("size") or 0
        if base.endswith(SKIP_EXT) or "entry" in base:
            continue
        kind = None
        if RE_WORKER.match(base) and size > 100_000:
            kind = "worker"
        elif RE_COMBINED.match(base) and size > 300_000:
            kind = "combined"
        elif RE_SANDBOX.match(base):
            kind = "sandbox"
        elif RE_MAIN.match(base) and size > 150_000:
            kind = "main"
        elif RE_WORKER_LOOSE.search(base) and size > 100_000:
            kind = "worker_loose"
        elif RE_VIEWER.match(base) and "/web/" in path.lower() and size > 100_000:
            kind = "viewer"
        if kind:
            out.append({"path": path, "kind": kind, "size": size, "hash": f.get("hash")})
    return out


BIG_JS = 150_000


def big_js(files, exclude_paths=()):
    """JS files large enough to hold a bundled PDF.js (smallest copy seen in the recall check: 0.72 MB)."""
    ex = set(exclude_paths)
    out = [f for f in files if JS_EXT.search(f["name"]) and not f["name"].lower().endswith(SKIP_EXT)
           and (f.get("size") or 0) >= BIG_JS and f["name"] not in ex]
    # files whose path mentions pdf/worker first, then by size
    out.sort(key=lambda f: (0 if re.search(r"pdf|worker", f["name"], re.I) else 1, -(f.get("size") or 0)))
    return out


# --------------------------------------------------------------------------- republication vs embedding
LAYOUT_DIR = re.compile(r"(^|/)(build|legacy|web|cmaps|bcmaps|standard_fonts|image_decoders|types|wasm|iccs|es5|lib|"
                        r"locale|images|pdfjs|pdf\.js|pdfjs-dist)/", re.I)
META_FILE = re.compile(r"^/(package\.json|readme(\.[a-z]+)?|license(\.[a-z]+)?|licence(\.[a-z]+)?|changelog(\.[a-z]+)?|"
                       r"\.npmignore|bower\.json|webpack\.js|copying|notice)$", re.I)


def count_other(files, pdfjs_hashes, copy_paths):
    """Files that are not PDF.js: not in a PDF.js layout directory, not byte-identical to any
    pdfjs-dist file, not package metadata, not one of the identified copies."""
    n = 0
    cp = set(copy_paths)
    for f in files:
        p = f["name"]
        if p in cp or META_FILE.match(p) or LAYOUT_DIR.search(p) or f.get("hash") in pdfjs_hashes:
            continue
        if p.lower().endswith((".bcmap", ".pfb", ".ftl", ".properties")):
            continue
        n += 1
    return n


# --------------------------------------------------------------------------- content scan
SIG_WORKER = b"does not match the Worker version"
# unminified 4.x+ builds split the message across two literals: "... does not match " + "the Worker version ..."
RX_WORKER_SPLIT = re.compile(rb"does not match \\*['\"`]\s*\+\s*\\*['\"`]the Worker version")
RX_MAIN2 = re.compile(rb"No \\*[\"']?GlobalWorkerOptions\.workerSrc\\*[\"']? specified")
SIG_MAIN1 = b"No PDFJS.workerSrc specified"
# strings from PDF.js's own api.js / worker code, present in every pdfjs-dist build checked (1.0 to 6.4)
INTERNAL = [b"Setting up fake worker failed", b"Worker was destroyed", b"Worker was terminated", b"Transport destroyed",
            b"Invalid PDF structure", b"Invalid page request", b"Loading aborted", b"getOperatorList",
            b"Unknown action from worker"]
SCAN_V = 4
RX_V = [
    # quote optional: the build header comment reads "pdfjsVersion = 5.5.207"
    ("pdfjsVersion", re.compile(rb"pdfjsVersion\s*[=:]\s*\\*['\"`]?(\d+\.\d+\.\d+)")),
    ("workerVersionConst", re.compile(rb"workerVersion\s*=\s*\\*['\"`](\d+\.\d+\.\d+)")),
    ("apiVersion", re.compile(rb"apiVersion\s*:\s*\\*['\"`](\d+\.\d+\.\d+)")),
    ("workerVersion", re.compile(rb"Worker version \\*\"(\d+\.\d+\.\d+)")),
    ("PDFJS.version", re.compile(rb"PDFJS\.version\s*=\s*\\*['\"](\d+\.\d+\.\d+)")),
]
RX_VERBUILD = re.compile(rb"\\*['\"`](\d+\.\d+\.\d+)\\*['\"`]\s*[,;]\s*(?:(?:const|let|var)\s+)?[\w$.]+\s*=\s*\\*['\"`]"
                         rb"([0-9a-f]{7,10})\\*['\"`]")
RX_LIT = re.compile(rb"['\"`](\d+\.\d+\.\d+)['\"`]")


def plausible(v):
    k = vkey(v)
    return bool(k) and 1 <= k[0] <= 9 and k[1] <= 30


def scan_bytes(b, known_versions, path=""):
    """Is this PDF.js code, and which release? Pure byte matching."""
    sig = []
    split = RX_WORKER_SPLIT.search(b)
    if SIG_WORKER in b or split:
        sig.append("worker_msg")
    if RX_MAIN2.search(b):
        sig.append("main_workerSrc")
    if SIG_MAIN1 in b:
        sig.append("main_PDFJS.workerSrc")
    has_vb = b"pdfjsVersion" in b and b"pdfjsBuild" in b
    if has_vb and (b"WorkerMessageHandler" in b or b"PDFWorker" in b):
        sig.append("pdfjsVersion+Build")
    found = []
    for tag, rx in RX_V:
        for m in rx.finditer(b):
            found.append((tag, m.group(1).decode()))
            if len(found) > 50:
                break
    for m in RX_VERBUILD.finditer(b):
        v = m.group(1).decode()
        if v in known_versions or (sig and plausible(v)):
            found.append(("version+build", v))
    if "worker_msg" in sig and not found:
        i = b.find(SIG_WORKER) if SIG_WORKER in b else split.start()
        lits = [m.group(1).decode() for m in RX_LIT.finditer(b[max(0, i - 6000):i + 200])]
        k = [v for v in lits if v in known_versions] or [v for v in lits if plausible(v)]
        if k:
            found.append(("near_worker_msg", k[-1]))
    m = re.search(r"(?:pdf|worker)[^/]*?[-_.@](\d+\.\d+\.\d+)[-_.]", path.rsplit("/", 1)[-1], re.I) if path else None
    if m and plausible(m.group(1)) and not found:
        found.append(("file_name", m.group(1)))
    # every signature needs PDF.js internals next to it, so wrapper code that merely quotes a PDF.js
    # message in a comment does not count (seen in two Angular wrappers during the run)
    n_internal = sum(1 for x in INTERNAL if x in b)
    confirmed = (bool(sig) or any(t in ("pdfjsVersion", "apiVersion", "workerVersion", "workerVersionConst") for t, _ in found))         and n_internal >= 2
    versions = {}
    for t, v in found:
        if plausible(v):
            versions[v] = versions.get(v, 0) + 1
    best = None
    if versions:
        # prefer upstream releases, then the most frequent literal
        best = sorted(versions, key=lambda v: (v not in known_versions, -versions[v], vkey(v) or (0, 0, 0)))[0]
    how = None
    if best:
        how = [t for t, v in found if v == best][0]
    legacy = b"__core-js_shared__" in b or b"core-js/modules" in b
    return {"pdfjs": confirmed, "sig": sig, "version": best, "how": how,
            "all_versions": sorted(versions, key=lambda v: vkey(v) or (0, 0, 0)), "core_js": legacy,
            # worker/core code: the parser's InvalidPDFException message is in every worker and combined
            # build checked (1.0 to 6.4) and in no display-layer build; the version-check message is worker-only
            "has_worker": confirmed and ("worker_msg" in sig or b"Invalid PDF structure" in b),
            "viewer_app": b"PDFViewerApplication" in b and n_internal >= 1, "n_internal": n_internal, "v": SCAN_V}


MAX_FILE = 40 * 1024 * 1024


def scan_file(http, name, version, path, h, known_versions):
    """Content scan of one package file, cached by its SHA-256 (from the listing)."""
    if h:
        r = http.scan_get(h)
        if r is not None:
            return r
    st, b = http.fetch(file_url(name, version, path), cache=False, max_bytes=MAX_FILE, tries=5)
    if st == 200:
        r = scan_bytes(b, known_versions, path)
        r["fetched_from"] = "cdn.jsdelivr.net"
    else:
        r = scan_from_tarball(http, name, version, path, known_versions, why=f"cdn_{st}")
    if h and r.get("status") != "fetch_failed":
        http.scan_put(h, r)
    return r


MAX_TGZ = 120 * 1024 * 1024


def scan_from_tarball(http, name, version, path, known_versions, why=""):
    """Fallback for files jsDelivr will not serve (e.g. > 20 MB): the registry tarball, kept in
    <work>/tarballs/, read with tarfile in memory. Nothing in it is extracted or executed."""
    tdir = os.path.join(http.work, "tarballs")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", f"{name}@{version}") + ".tgz"
    tp = os.path.join(tdir, safe)
    if not os.path.exists(tp):
        meta = http.json(f"https://registry.npmjs.org/{enc_name(name)}/{urllib.parse.quote(version, safe='.-_~+')}")
        url = (meta.get("dist") or {}).get("tarball") if isinstance(meta, dict) else None
        if not url:
            return {"pdfjs": False, "status": "fetch_failed", "why": why + ";no_tarball_url"}
        st, b = http.fetch(url, cache=False, max_bytes=MAX_TGZ, tries=4, timeout=300)
        if st != 200:
            return {"pdfjs": False, "status": "fetch_failed", "why": why + f";tgz_{st}"}
        with open(tp, "wb") as f:
            f.write(b)
    try:
        with tarfile.open(tp, mode="r:gz") as tf:
            for m in tf.getmembers():
                if m.isfile() and m.name.split("/", 1)[-1] == path.lstrip("/"):
                    r = scan_bytes(tf.extractfile(m).read(), known_versions, path)
                    r["fetched_from"] = "tarball"
                    return r
    except Exception as e:
        return {"pdfjs": False, "status": "fetch_failed", "why": why + f";tar_{type(e).__name__}"}
    return {"pdfjs": False, "status": "fetch_failed", "why": why + ";not_in_tarball"}


# --------------------------------------------------------------------------- reference
_REF = None


def reference():
    global _REF
    if _REF is None:
        with open(os.path.join(DATA, "pdfjs_reference.json"), encoding="utf-8") as f:
            _REF = json.load(f)
        _REF["known"] = set(_REF["versions"])
        _REF["all_hashes"] = set(_REF["all_file_hashes"])
    return _REF


ROLE_ORDER = {"worker": 0, "worker_loose": 1, "combined": 2, "main": 3, "viewer": 4, "sandbox": 5}


def analyse_version(http, name, version, files, bundle_scan=True, max_scan_files=40, max_scan_bytes=120_000_000,
                    prefer=()):
    """Classify one package release from its file listing. Returns a dict (see README schema)."""
    ref = reference()
    known = ref["known"]
    hashes = ref["js_hashes"]
    cands = candidates(files)
    copies = []  # confirmed PDF.js files
    rejected = []
    dir_done = {}  # directory -> a content-confirmed copy in it
    for c in sorted(cands, key=lambda c: ROLE_ORDER[c["kind"]]):
        d = c["path"].rsplit("/", 1)[0]
        m = hashes.get(c["hash"])
        if m:
            versions = sorted({x[0] for x in m}, key=vkey)
            refpath = [x[1] for x in m if x[0] == versions[0]][0]
            copies.append({"path": c["path"], "kind": c["kind"], "method": "hash", "version": versions[0],
                           "ambiguous": len(versions) > 1, "legacy": bool(re.search(r"/(legacy|es5)/", refpath)),
                           "worker": "worker" in refpath or "combined" in refpath, "ref_path": refpath})
            dir_done.setdefault(d, copies[-1])
            continue
        if d in dir_done:
            # a sibling of a confirmed copy: attributed by name, not fetched again
            hint = re.search(r"[-_.@](\d+\.\d+\.\d+)[-_.]", c["path"].rsplit("/", 1)[-1])
            copies.append({"path": c["path"], "kind": c["kind"], "method": "same_dir",
                           "version": hint.group(1) if hint and plausible(hint.group(1)) else dir_done[d]["version"],
                           "legacy": True if re.search(r"legacy|es5", c["path"], re.I) else None,
                           "worker": c["kind"] in ("worker", "worker_loose", "combined")})
            continue
        r = scan_file(http, name, version, c["path"], c["hash"], known)
        if r.get("status") == "fetch_failed":
            rejected.append({"path": c["path"], "kind": c["kind"], "why": "fetch_failed"})
            continue
        if r["pdfjs"] or (c["kind"] == "viewer" and r.get("viewer_app")):
            copies.append({"path": c["path"], "kind": c["kind"], "method": "banner", "version": r["version"],
                           "how": r["how"], "legacy": r["core_js"] or bool(re.search(r"legacy|es5", c["path"], re.I)),
                           "worker": c["kind"] in ("worker", "worker_loose", "combined") or r["has_worker"],
                           "all_versions": r["all_versions"]})
            dir_done.setdefault(d, copies[-1])
        else:
            rejected.append({"path": c["path"], "kind": c["kind"],
                             "why": "no_pdfjs_signature" if c["kind"] not in ("viewer", "sandbox") else "unverified_" + c["kind"]})
    via = "filename" if copies else None
    scanned = 0
    capped = False
    if not copies and bundle_scan:
        nbytes = 0
        pref = set(prefer)
        bj = big_js(files, exclude_paths=[c["path"] for c in cands])
        bj.sort(key=lambda f: 0 if f["name"] in pref else 1)  # stable: keeps the pdf/worker-first order
        n_pref = sum(1 for f in bj if f["name"] in pref)
        for i, f in enumerate(bj):
            if i == n_pref and n_pref and copies:
                break  # paths that held PDF.js in other releases of this package confirmed it again
            if scanned >= max_scan_files or nbytes > max_scan_bytes:
                capped = True
                break
            if f.get("hash") in hashes:
                continue  # byte-identical pdfjs-dist file would have been a name hit; skip
            r = scan_file(http, name, version, f["name"], f.get("hash"), known)
            scanned += 1
            nbytes += f.get("size") or 0
            if r.get("pdfjs"):
                copies.append({"path": f["name"], "kind": "bundle", "method": "bundle", "version": r["version"],
                               "how": r["how"], "legacy": None, "worker": r["has_worker"],
                               "all_versions": r["all_versions"]})
        if copies:
            via = "bundle"
    bcmap = sum(1 for f in files if f["name"].endswith(".bcmap"))
    allv = sorted({v for c in copies for v in ([c.get("version")] + (c.get("all_versions") or [])) if v},
                  key=lambda v: vkey(v) or (0, 0, 0))
    # primary = newest copy in the release (conservative for lag and affected-range figures);
    # upstream pdfjs-dist versions win over fork / custom-build numbers
    # library files decide; sandbox and viewer files change rarely, so their hashes can match a later
    # release than the one actually shipped and only count when nothing else has a version
    lib = [c["version"] for c in copies if c.get("version") and c["kind"] not in ("sandbox", "viewer")]
    vers = lib or [c["version"] for c in copies if c.get("version")]
    up = [v for v in vers if v in ref["known"]]
    primary = max(up or vers, key=lambda v: vkey(v) or (0, 0, 0)) if vers else None
    methods = sorted({c["method"] for c in copies if c["method"] != "same_dir"})
    legacy_flags = [c["legacy"] for c in copies if c.get("legacy") is not None
                    and c["kind"] in ("worker", "worker_loose", "combined", "main")]
    build = None
    if copies and primary and (vkey(primary) or (9,))[0] < 2:
        build = "generic"  # PDF.js 1.x had no separate legacy build
    elif copies:
        if legacy_flags:
            build = "legacy" if all(legacy_flags) else ("generic" if not any(legacy_flags) else "generic+legacy")
        else:
            build = "unknown"
    n_other = count_other(files, ref["all_hashes"], [c["path"] for c in copies]) if copies else None
    base = base_version(primary)
    return {
        "carries": bool(copies),
        "pdfjs_upstream": (primary in ref["known"]) if primary else None,
        "pdfjs_base_version": base,
        "via": via,
        "pdfjs_version": primary,
        "pdfjs_versions_all": allv,
        "id_method": ("hash" if "hash" in methods else ("banner" if "banner" in methods else
                                                        ("bundle" if methods else None))),
        "build_type": build,
        "worker_present": any(c.get("worker") for c in copies) if copies else None,
        "n_files": len(files),
        "n_other_files": n_other,
        "shape": (None if not copies else ("republication" if (n_other <= 3 and via == "filename") else "embedded")),
        "copies": copies,
        "rejected_candidates": rejected,
        "n_name_candidates": len(cands),
        "bundle_files_scanned": scanned,
        "bundle_scan_capped": capped,
        "bcmap": bcmap,
    }


def base_version(v):
    """Greatest upstream pdfjs-dist release <= v (maps fork / custom-build numbers onto upstream)."""
    if not v:
        return None
    ref = reference()
    if v in ref["known"]:
        return v
    k = vkey(v)
    if not k:
        return None
    if "_sorted" not in ref:
        ref["_sorted"] = sorted(ref["versions"], key=vkey)
    best = None
    for u in ref["_sorted"]:
        if vkey(u) <= k:
            best = u
        else:
            break
    return best


# --------------------------------------------------------------------------- misc
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


def jdump(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def jload(path, default=None):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def read_jsonl(path):
    """Rows of path.gz (if present, e.g. the compressed copy in the published dataset) then of path."""
    out = []
    for p, opener in ((path + ".gz", lambda p: gzip.open(p, "rt", encoding="utf-8")),
                      (path, lambda p: open(p, encoding="utf-8"))):
        if os.path.exists(p):
            with opener(p) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        out.append(json.loads(line))
    return out


class JsonlWriter:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.f = open(path, "a", encoding="utf-8")

    def write(self, obj):
        with self.lock:
            self.f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.f.flush()
