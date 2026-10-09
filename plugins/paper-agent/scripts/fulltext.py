"""원문 PDF 수집과 쪽 단위 텍스트 추출.
  python scripts/fulltext.py fetch  --project SLUG [--status shortlist] [--paper ID]   # OA 자동 다운로드
  python scripts/fulltext.py attach --project SLUG --paper ID --file 받은파일.pdf      # 도서관에서 받은 PDF 등록
  python scripts/fulltext.py missing --project SLUG                                     # 원문 못 받은 shortlist 와 링크
"""
import argparse, json, pathlib, re, shutil, sys, time, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import connect, project_dir, load_env, now

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) paper-agent/0.1"


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
    q = "SELECT id,doi,oa_url FROM papers WHERE pdf_path IS NULL AND "
    rows = con.execute(q + "id=?", (paper,)).fetchall() if paper else con.execute(q + "status=?", (status,)).fetchall()
    ok = 0
    for r in rows:
        urls = ([r["oa_url"]] if r["oa_url"] else []) + openalex_pdfs(con, r["id"]) + unpaywall_urls(r["doi"])
        dest = project_dir(slug) / "pdf" / fname(r["id"], r["doi"])
        for u in dict.fromkeys(urls):
            try:
                if download(u, dest):
                    n = store(con, slug, r["id"], dest)
                    print(f"  #{r['id']} 원문 {n}쪽")
                    ok += 1
                    break
            except Exception as e:  # 개별 링크 실패는 다음 링크로
                print(f"  #{r['id']} 실패 {type(e).__name__}: {u[:80]}")
            time.sleep(0.5)
        else:
            print(f"  #{r['id']} OA 원문 없음 → missing 목록에서 도서관으로")
    print(f"원문 확보 {ok}/{len(rows)}")


def missing(con):
    for r in con.execute("SELECT id,doi,title,url FROM papers WHERE pdf_path IS NULL AND status IN ('shortlist','fulltext')"):
        link = f"https://doi.org/{r['doi']}" if r["doi"] else (r["url"] or "")
        print(f"#{r['id']}  {r['title'][:80]}\n      {link}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "attach", "missing"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--status", default="shortlist")
    ap.add_argument("--paper", type=int)
    ap.add_argument("--file")
    a = ap.parse_args()
    con = connect(a.project)
    if a.cmd == "fetch":
        fetch(con, a.project, a.status, a.paper)
    elif a.cmd == "attach":
        src = pathlib.Path(a.file).expanduser()
        if src.read_bytes()[:4] != b"%PDF":
            sys.exit("PDF 가 아닙니다")
        doi = con.execute("SELECT doi FROM papers WHERE id=?", (a.paper,)).fetchone()["doi"]
        dest = project_dir(a.project) / "pdf" / fname(a.paper, doi)
        shutil.copy(src, dest)
        print(f"#{a.paper} 원문 {store(con, a.project, a.paper, dest)}쪽 등록")
    else:
        missing(con)
