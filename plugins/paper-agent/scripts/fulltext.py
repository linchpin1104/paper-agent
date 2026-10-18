"""원문 PDF 수집과 쪽 단위 텍스트 추출.
  python scripts/fulltext.py fetch  --project SLUG [--status shortlist] [--paper ID] [--retry]   # OA 자동 다운로드 (읽을 목록 + 핵심 논문). 14일 안에 시도한 논문은 --retry 없으면 건너뜀
  python scripts/fulltext.py attach --project SLUG [--paper ID] --file a.pdf [b.pdf …]  # 도서관에서 받은 PDF 등록. --paper 없으면 DOI·제목으로 자동 짝짓기,
                                   [--add-new]                                          # 목록에 없는 논문이면 PDF 의 DOI·제목으로 찾아 새로 등록하고 읽을 목록에 넣는다
  python scripts/fulltext.py missing --project SLUG                                     # 원문 못 받은 shortlist 와 링크
"""
import argparse, datetime, json, pathlib, re, shutil, sys, time, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import connect, project_dir, load_env, now

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) paper-agent/0.1"
# 자동 접속을 감지하면 인터넷 주소(IP) 전체를 막는 출판사. 막히면 도서관 경유 접속까지 안 되므로 자동으로는 건드리지 않는다
NO_BOT = ("sciencedirect.com", "elsevier.com")
try:  # 맥의 python.org 파이썬은 인증서 묶음이 없어 기관 저장소 등에서 SSL 오류가 난다
    import certifi, ssl
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = None


def extract_pages(pdf):
    """쪽별 텍스트 리스트. PyMuPDF 우선, 없으면 pdftotext."""
    try:
        import fitz
        with fitz.open(pdf) as doc:
            return [pg.get_text() for pg in doc]
    except ImportError:
        import subprocess
        out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
        return out.split("\f")


def store(con, slug, pid, pdf_path):
    pages = extract_pages(pdf_path)
    if sum(len(p.strip()) for p in pages) < 500:
        print(f"  #{pid} 텍스트가 거의 없음 (스캔본일 수 있음). OCR 필요")
    rel = str(pathlib.Path(pdf_path).relative_to(project_dir(slug)))
    con.execute("INSERT OR REPLACE INTO fulltext(paper_id,pages,extracted_at) VALUES(?,?,?)",
                (pid, json.dumps(pages, ensure_ascii=False), now()))
    con.execute("UPDATE papers SET pdf_path=?, status=CASE WHEN status IN ('candidate','shortlist') THEN 'fulltext' ELSE status END"
                " WHERE id=?", (rel, pid))
    con.commit()
    import verify  # 원문이 생기면 바로: 엉뚱한 PDF·원고본 여부, 이 논문의 참고문헌과 인용 기록 대조
    print(f"  #{pid} 제목 대조: {verify.title_check(con, pid)} · 인용 검증: {verify.verify_edges(con, pid)}")
    return len(pages)


def fname(pid, doi):
    return f"{pid:05d}_" + (re.sub(r"[^A-Za-z0-9._-]", "_", doi)[:80] if doi else "nodoi") + ".pdf"


def download(url, dest, follow=True):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/pdf,*/*"})
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:  # 응답 없는 사이트에 오래 묶이지 않게
        data, base = r.read(60_000_000), r.url
    if not data.startswith(b"%PDF"):
        # 논문 페이지(HTML)면 학술 메타태그의 PDF 주소를 한 번 더 따라간다 (PeerJ·저장소 등 직링크가 없는 무료본)
        m = re.search(rb'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)', data[:300_000], re.I)
        return follow and bool(m) and download(urllib.parse.urljoin(base, m.group(1).decode()), dest, follow=False)
    dest.write_bytes(data)
    return True


def unpaywall_urls(doi):
    email = load_env().get("CONTACT_EMAIL")
    if not (doi and email):
        return []
    try:
        url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}"
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.load(r)
        return [loc["url_for_pdf"] for loc in d.get("oa_locations", []) if loc.get("url_for_pdf")]
    except (urllib.error.URLError, json.JSONDecodeError):
        return []


def s2_pdfs(doi):
    """Semantic Scholar 가 찾아 둔 무료 PDF (저자 홈페이지·arXiv 등)."""
    from fetch_s2 import get
    try:
        url = ((get(f"/graph/v1/paper/DOI:{doi}", fields="openAccessPdf") or {}).get("openAccessPdf") or {}).get("url") if doi else None
    except urllib.error.URLError:  # S2 가 모르는 DOI 형식이면 400
        return []
    return [url] if url else []


def has_title(pages, title):
    """첫 2쪽에 제목 앞 8단어가 있는가 (띄어쓰기·하이픈 무시). 엉뚱한 PDF 를 붙이지 않으려고."""
    from verify import plain
    squash = lambda t: re.sub(r"[^a-z0-9가-힣]", "", plain(t))
    return squash(" ".join(re.findall(r"[a-z0-9가-힣]+", plain(title))[:8])) in squash(" ".join(pages[:2]))


def openalex_pdfs(con, pid):
    """OpenAlex 에 기록된 모든 무료 위치의 PDF 링크 (기관 저장소·프리프린트 포함)."""
    from fetch_openalex import get
    row = con.execute("SELECT source_id FROM sources WHERE paper_id=? AND source='openalex'", (pid,)).fetchone()
    if not row:
        return []
    locs = (get(f"/works/{row['source_id']}", select="locations") or {}).get("locations", [])
    # 저장소(repository) 위치를 먼저: 출판사 사이트보다 봇 차단이 적다
    locs.sort(key=lambda l: ((l.get("source") or {}).get("type") != "repository"))
    # PDF 직링크 먼저, 없으면 무료(OA) 위치의 논문 페이지 → download() 가 페이지 안의 PDF 주소를 찾는다
    return ([l["pdf_url"] for l in locs if l.get("pdf_url")]
            + [l["landing_page_url"] for l in locs if l.get("is_oa") and l.get("landing_page_url")])


RETRY_DAYS = 14  # 이 기간 안에 시도해 못 받은 논문은 다시 시도하지 않는다 (막힌 사이트는 대개 계속 막힘)


def fetch(con, slug, status, paper, retry=False):
    q = "SELECT id,doi,oa_url,title FROM papers WHERE pdf_path IS NULL AND "
    if paper:
        rows = con.execute(q + "id=?", (paper,)).fetchall()
    else:
        rows = con.execute(q + "(status=? OR favorite=1)", (status,)).fetchall()
        cut = (datetime.datetime.now() - datetime.timedelta(days=RETRY_DAYS)).isoformat(timespec="seconds")
        recent = [] if retry else [r for r in rows if (con.execute("SELECT ft_tried FROM papers WHERE id=?", (r["id"],))
                                                        .fetchone()[0] or "") > cut]
        if recent:
            print(f"최근 {RETRY_DAYS}일 안에 시도한 {len(recent)}편은 건너뜁니다 (다시 하려면 --retry)", flush=True)
            skip = {r["id"] for r in recent}
            rows = [r for r in rows if r["id"] not in skip]
    ok = 0
    for i, r in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] #{r['id']} {(r['title'] or '')[:50]}", flush=True)
        urls = ([r["oa_url"]] if r["oa_url"] else []) + openalex_pdfs(con, r["id"]) + unpaywall_urls(r["doi"]) + s2_pdfs(r["doi"])
        urls = [u for u in urls if not any(d in urllib.parse.urlparse(u).netloc for d in NO_BOT)]
        dest = project_dir(slug) / "pdf" / fname(r["id"], r["doi"])
        blocked = []
        for u in dict.fromkeys(urls):
            try:
                if not download(u, dest):
                    continue
                if not has_title(extract_pages(dest), r["title"]):
                    print(f"  #{r['id']} 제목이 다른 PDF 라 버림: {u[:80]}")
                    dest.unlink()
                else:
                    n = store(con, slug, r["id"], dest)
                    print(f"  #{r['id']} 원문 {n}쪽")
                    ok += 1
                    break
            except Exception as e:  # 개별 링크 실패는 다음 링크로
                print(f"  #{r['id']} 실패 {type(e).__name__}: {u[:80]}")
                if getattr(e, "code", None) == 403:  # 403 = 사이트가 프로그램 접속을 막음. 404 등 죽은 링크는 남기지 않는다
                    blocked.append(u)
            time.sleep(0.5)
        else:
            if blocked and not r["oa_url"]:  # 무료 원문은 있는데 사이트가 프로그램 접속을 막은 경우: 화면에서 직접 열도록 남긴다
                con.execute("UPDATE papers SET oa_url=? WHERE id=?", (blocked[0], r["id"]))
            result = "접속 차단" if blocked else "무료본 없음" if not urls else "받기 실패"
            con.execute("UPDATE papers SET ft_tried=?, ft_result=? WHERE id=?", (now(), result, r["id"]))
            con.commit()
            print(f"  #{r['id']} " + ("무료 원문이 있으나 자동 다운로드가 막힘 → 브라우저로 직접" if blocked else "OA 원문 없음 → 도서관으로"))
    print(f"원문 확보 {ok}/{len(rows)}", flush=True)


def library_link(doi, url=None):
    """DOI 링크. .env 의 LIBRARY_PROXY(학교 도서관 원격접속 주소 앞부분)가 있으면 도서관을 거쳐 연다."""
    link = f"https://doi.org/{doi}" if doi else (url or "")
    return load_env().get("LIBRARY_PROXY", "") + link if link else ""


def match(con, pages):
    """올린 PDF 가 어느 논문인지: 첫 2쪽의 DOI → 없으면 기록된 제목 앞 8단어. 원문 없는 논문 중에서만 찾는다."""
    from verify import plain
    head = plain(" ".join(pages[:2]))
    rows = con.execute("SELECT id, doi, title FROM papers WHERE pdf_path IS NULL").fetchall()
    for r in rows:
        if r["doi"] and r["doi"].lower() in head:
            return r["id"]
    hits = [r["id"] for r in rows if len(re.findall(r"\w+", r["title"] or "")) >= 3 and has_title(pages, r["title"])]
    return hits[0] if len(hits) == 1 else None  # 둘 이상이면 모호하니 사람에게


def pdf_title(pdf):
    """첫 쪽에서 가장 큰 글씨 줄(대개 제목). PDF 정보의 제목이 그럴듯하면 그것."""
    try:
        import fitz
        with fitz.open(pdf) as doc:
            meta = (doc.metadata or {}).get("title") or ""
            spans = [(round(sp["size"], 1), sp["text"].strip()) for b in doc[0].get_text("dict")["blocks"]
                     for ln in b.get("lines", []) for sp in ln["spans"] if sp["text"].strip()]
    except Exception:
        return ""
    if len(re.findall(r"[A-Za-z가-힣]+", meta)) >= 4:
        return meta
    if not spans:
        return ""
    big = max(sz for sz, t in spans if len(t) > 3) if any(len(t) > 3 for _, t in spans) else 0
    return " ".join(t for sz, t in spans if sz == big)[:300]


def identify(con, pdf, pages):
    """목록에 없는 논문의 PDF: 첫 2쪽의 DOI → 없으면 제목으로 OpenAlex 에서 찾는다.
    찾은 논문의 제목이 PDF 첫 2쪽에 실제로 있어야 등록한다(엉뚱한 논문 방지). 등록하면 읽을 목록에 넣고 id 를 돌려준다."""
    import seeds
    import fetch_openalex as oa
    head = " ".join(pages[:2])
    m = re.search(r"10\.\d{4,9}/[^\s\"<>]+", head)
    queries = ([m.group(0).rstrip(".,;)]")] if m else []) + ([t] if (t := pdf_title(pdf)) else [])
    for q in queries:
        for c in seeds.find(q)[:3]:
            if c["title"] and has_title(pages, c["title"]):
                w = oa.get(f"/works/{c['openalex']}")
                pid = w and oa.upsert_works(con, [w]).get(oa.oid(w))
                if pid:
                    con.execute("UPDATE papers SET status='shortlist' WHERE id=? AND status='candidate'", (pid,))
                    con.commit()
                    print(f"  목록에 없던 논문을 찾아 등록: #{pid} {c['year']} {c['title'][:80]} → 읽을 목록")
                    return pid
    return None


def attach(con, slug, src, paper=None, add_new=False):
    """add_new: 목록에 없는 논문이면 PDF 의 DOI·제목으로 찾아 새로 등록한다(사람이 직접 고른 파일에만 쓴다)."""
    src = pathlib.Path(src).expanduser()
    if src.read_bytes()[:4] != b"%PDF":
        print(f"  {src.name}: PDF 가 아닙니다")
        return
    pages = extract_pages(src)
    chosen = paper  # 사람이 논문을 골라 올렸으면 원문을 바꿀 수 있다
    paper = paper or match(con, pages) or (add_new and identify(con, src, pages))
    if not paper:
        print(f"  {src.name}: " + ("어느 논문인지 못 찾음 (PDF 에서 DOI·제목을 읽지 못했거나 OpenAlex 에 없음) → "
                                   "찾기 탭에서 그 논문을 먼저 등록하거나, 읽기 화면에서 그 논문을 골라 올리세요" if add_new
                                   else "이 프로젝트 목록에 없는 논문이라 건너뜀"))
        return
    if not chosen and con.execute("SELECT pdf_path FROM papers WHERE id=?", (paper,)).fetchone()[0]:
        print(f"  {src.name}: #{paper} 는 이미 원문이 있습니다. 바꾸려면 읽기 화면에서 그 논문에 올리세요")
        return
    doi = con.execute("SELECT doi FROM papers WHERE id=?", (paper,)).fetchone()["doi"]
    dest = project_dir(slug) / "pdf" / fname(paper, doi)
    shutil.copy(src, dest)
    print(f"  {src.name} → #{paper} 원문 {store(con, slug, paper, dest)}쪽 등록")
    # 사람이 직접 받아 올린 PDF 가 기록과 제목까지 맞으면 그 자체가 원문 확인이다. 원고본·불일치는 사람이 따로 본다
    if con.execute("UPDATE papers SET review='원문 확인함', review_note='직접 올린 PDF · 제목 일치 (자동 기록)', reviewed_at=? "
                   "WHERE id=? AND review IS NULL AND title_check='일치'", (now(), paper)).rowcount:
        print(f"  #{paper} 검토: 원문 확인함 (직접 올린 PDF, 제목 일치)")
    con.commit()


def missing(con):
    for r in con.execute("SELECT id,doi,title,url FROM papers WHERE pdf_path IS NULL AND (status IN ('shortlist','fulltext') OR favorite=1)"):
        link = library_link(r["doi"], r["url"])
        print(f"#{r['id']}  {r['title'][:80]}\n      {link}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "attach", "missing"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--status", default="shortlist")
    ap.add_argument("--paper", type=int)
    ap.add_argument("--file", nargs="+")
    ap.add_argument("--retry", action="store_true", help="최근에 시도한 논문도 다시")
    ap.add_argument("--add-new", action="store_true", help="attach: 목록에 없는 논문이면 찾아 새로 등록하고 읽을 목록에 넣는다")
    a = ap.parse_args()
    con = connect(a.project)
    if a.cmd == "fetch":
        fetch(con, a.project, a.status, a.paper, a.retry)
    elif a.cmd == "attach":
        for f in a.file:
            attach(con, a.project, f, a.paper, a.add_new)
    else:
        missing(con)
