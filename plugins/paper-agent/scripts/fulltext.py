"""원문 PDF 수집과 쪽 단위 텍스트 추출.
  python scripts/fulltext.py fetch  --project SLUG [--status shortlist] [--paper ID]   # OA 자동 다운로드 (읽을 목록 + 핵심 논문)
  python scripts/fulltext.py attach --project SLUG [--paper ID] --file a.pdf [b.pdf …]  # 도서관에서 받은 PDF 등록. --paper 없으면 DOI·제목으로 자동 짝짓기
  python scripts/fulltext.py missing --project SLUG                                     # 원문 못 받은 shortlist 와 링크
"""
import argparse, json, pathlib, re, shutil, sys, time, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import connect, project_dir, load_env, now

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) paper-agent/0.1"
# 자동 접속을 감지하면 인터넷 주소(IP) 전체를 막는 출판사. 막히면 도서관 경유 접속까지 안 되므로 자동으로는 건드리지 않는다
NO_BOT = ("sciencedirect.com", "elsevier.com")


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


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/pdf,*/*"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(60_000_000)
    if not data.startswith(b"%PDF"):
        return False  # 랜딩 페이지 HTML 등
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
    return [l["pdf_url"] for l in locs if l.get("pdf_url")]


def fetch(con, slug, status, paper):
    q = "SELECT id,doi,oa_url,title FROM papers WHERE pdf_path IS NULL AND "
    rows = con.execute(q + "id=?", (paper,)).fetchall() if paper else con.execute(q + "(status=? OR favorite=1)", (status,)).fetchall()
    ok = 0
    for r in rows:
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
                con.commit()
            print(f"  #{r['id']} " + ("무료 원문이 있으나 자동 다운로드가 막힘 → 브라우저로 직접" if blocked else "OA 원문 없음 → 도서관으로"))
    print(f"원문 확보 {ok}/{len(rows)}")


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


def attach(con, slug, src, paper=None):
    src = pathlib.Path(src).expanduser()
    if src.read_bytes()[:4] != b"%PDF":
        print(f"  {src.name}: PDF 가 아닙니다")
        return
    paper = paper or match(con, extract_pages(src))
    if not paper:
        print(f"  {src.name}: 어느 논문인지 못 찾음 → 읽기 화면에서 그 논문을 골라 올리세요")
        return
    doi = con.execute("SELECT doi FROM papers WHERE id=?", (paper,)).fetchone()["doi"]
    dest = project_dir(slug) / "pdf" / fname(paper, doi)
    shutil.copy(src, dest)
    print(f"  {src.name} → #{paper} 원문 {store(con, slug, paper, dest)}쪽 등록")


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
    a = ap.parse_args()
    con = connect(a.project)
    if a.cmd == "fetch":
        fetch(con, a.project, a.status, a.paper)
    elif a.cmd == "attach":
        for f in a.file:
            attach(con, a.project, f, a.paper)
    else:
        missing(con)
