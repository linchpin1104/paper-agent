"""Semantic Scholar 수집. 키 선택(S2_API_KEY).
  python scripts/fetch_s2.py search  --project SLUG
  python scripts/fetch_s2.py related --project SLUG   # favorite 의 참고문헌·피인용·추천 1홉
"""
import argparse, json, sys, time, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from db import connect, read_brief, upsert_paper, add_edge, log_search, log_hits, load_env

API = "https://api.semanticscholar.org"
SRC = "s2"
FIELDS = "paperId,title,authors,year,venue,abstract,citationCount,externalIds,openAccessPdf,url"


def get(path, **params):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": "paper-agent/0.1"}
    key = load_env().get("S2_API_KEY")
    if key:
        headers["x-api-key"] = key
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                time.sleep(1.1)  # 무키 한도 보호
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(5 * (i + 1))
                continue
            if e.code == 404:
                return None
            raise
    print("  [s2] 요청 한도 초과로 건너뜀. .env 에 S2_API_KEY 를 넣으면 풀린다:", path, file=sys.stderr)
    return None


def rec(p):
    ext = p.get("externalIds") or {}
    return dict(doi=ext.get("DOI"), title=p.get("title"),
                authors="; ".join(a.get("name", "") for a in p.get("authors") or []),
                year=p.get("year"), venue=p.get("venue"), abstract=p.get("abstract"),
                cited_by=p.get("citationCount"), oa_url=(p.get("openAccessPdf") or {}).get("url"), url=p.get("url"))


def upsert_many(con, papers, exclude=()):
    out = {}
    for p in papers:
        if not p or not p.get("title"):
            continue
        if any(x.lower() in p["title"].lower() for x in exclude):
            continue
        pid = upsert_paper(con, rec(p), SRC, p["paperId"], raw={"paperId": p["paperId"]})
        if pid:
            out[p["paperId"]] = pid
    return out


def search(con, brief):
    y0, y1 = brief["years"]
    total = 0
    for kw in brief["keywords"]:
        d = get("/graph/v1/paper/search", query=kw, year=f"{y0}-{y1}", fields=FIELDS, limit=100)
        got = upsert_many(con, (d or {}).get("data", []), brief["exclude"])
        log_hits(con, got.values(), kw)
        log_search(con, SRC, kw, len(got))
        con.commit()
        print(f"[s2] {kw!r}: {len(got)}")
        total += len(got)
    return total


def s2_id(con, paper):
    row = con.execute("SELECT source_id FROM sources WHERE paper_id=? AND source=?", (paper["id"], SRC)).fetchone()
    if row:
        return row["source_id"]
    return f"DOI:{paper['doi']}" if paper["doi"] else None


def related(con):
    favs = con.execute("SELECT id, doi FROM papers WHERE favorite=1").fetchall()
    if not favs:
        print("favorite 논문이 없습니다.")
        return
    for f in favs:
        sid = s2_id(con, f)
        if not sid:
            print(f"  #{f['id']} s2 id 없음")
            continue
        refs = get(f"/graph/v1/paper/{sid}/references", fields=FIELDS, limit=100) or {}
        r_ids = upsert_many(con, [x.get("citedPaper") for x in refs.get("data") or []])
        for pid in r_ids.values():
            add_edge(con, f["id"], pid, "cites", SRC)
        cits = get(f"/graph/v1/paper/{sid}/citations", fields=FIELDS, limit=100) or {}
        c_ids = upsert_many(con, [x.get("citingPaper") for x in cits.get("data") or []])
        for pid in c_ids.values():
            add_edge(con, pid, f["id"], "cites", SRC)
        rcm = get(f"/recommendations/v1/papers/forpaper/{sid}", fields=FIELDS, limit=30) or {}
        m_ids = upsert_many(con, rcm.get("recommendedPapers") or [])
        for pid in m_ids.values():
            add_edge(con, f["id"], pid, "recommended", SRC)
        con.commit()
        print(f"  #{f['id']} 참고문헌 {len(r_ids)} / 피인용 {len(c_ids)} / 추천 {len(m_ids)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search", "related"])
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    con = connect(a.project)
    if a.cmd == "search":
        print("합계", search(con, read_brief(a.project)))
    else:
        related(con)
