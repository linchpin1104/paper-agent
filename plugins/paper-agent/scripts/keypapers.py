"""핵심 논문 찾기. 키워드 검색 결과를 쏟아 붓는 대신, 읽을 논문 후보를 네 묶음으로 추린다.
  python scripts/keypapers.py run      --project SLUG [--classics 25] [--reviews 8]
  python scripts/keypapers.py discover --project SLUG    # 핵심 논문을 모를 때: 키워드로 가볍게(키워드당 50편) 검색 → 고전·리뷰 후보
                                                         # → 사람이 골라 핵심 논문(★)으로 등록 → seeds.py expand

  리뷰   : 주제 키워드의 리뷰 논문 (체계적 문헌고찰·계량서지·메타분석). 연도 제한 없음
  고전   : 후보 논문들이 가장 많이 인용한 논문 (= 이 분야가 기대는 논문). 후보에 없으면 가져온다.
           검색어(흐름)마다 따로도 센다 — 여러 흐름이 만나는 주제에서 큰 흐름이 고전을 독차지하지 않게
  최전선 : 최근 3년 논문 중 고전을 2편 이상 인용(= 주제가 맞음)하고 연간 인용이 빠른 것
  직결   : 앞 3개 주제 씨앗의 단어(따옴표는 구문)가 제목·초록에 모두 들어간 것
결과는 papers.local_cites / core_links / is_review 칸과 화면 출력. 최종 선정(db.py pick)은 에이전트가 초록을 읽고 한다.
"""
import argparse, collections, datetime, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import connect, read_brief
from fetch_openalex import get, upsert_works, batch

YEAR = datetime.date.today().year


def refs_by_paper(con):
    """{paper_id: [OpenAlex id, ...]} — OpenAlex 에서 온 후보의 참고문헌."""
    out = {}
    for r in con.execute("SELECT paper_id, raw FROM sources WHERE source='openalex' AND raw IS NOT NULL"):
        out[r["paper_id"]] = [w.rsplit("/", 1)[-1] for w in json.loads(r["raw"]).get("referenced_works", [])]
    return out


def oa_map(con):
    return {r["source_id"]: r["paper_id"] for r in con.execute("SELECT source_id, paper_id FROM sources WHERE source='openalex'")}


def terms(seed):
    """'"system dynamics" startup' → ['system dynamics', 'startup']"""
    phrases = re.findall(r'"([^"]+)"', seed)
    rest = re.sub(r'"[^"]+"', " ", seed).split()
    return [t.lower() for t in phrases + rest]


def find_reviews(con, brief, n):
    found = set()
    for kw in brief["keywords"]:
        for flt in ("type:review", "title.search:review"):
            d = get("/works", search=kw, filter=flt, per_page=n) or {}
            found |= set(upsert_works(con, d.get("results", []), brief["exclude"]).values())
    for pid in found:
        con.execute("UPDATE papers SET is_review=1 WHERE id=?", (pid,))
    con.commit()
    return found


def run(con, slug, n_classics, n_reviews):
    brief = read_brief(slug)
    reviews = find_reviews(con, brief, n_reviews)
    # 고전: 후보 전체의 참고문헌을 센다 + 검색어(흐름)별로 따로 센다
    refs = refs_by_paper(con)
    cnt = collections.Counter(w for ws in refs.values() for w in set(ws))
    top = [w for w, _ in cnt.most_common(n_classics)]
    streams = {}
    per = max(4, n_classics // max(1, len(brief["keywords"])))
    for kw in brief["keywords"]:
        ids = [r[0] for r in con.execute("SELECT paper_id FROM hits WHERE query=?", (kw,))]
        c = collections.Counter(w for pid in ids for w in set(refs.get(pid, [])))
        streams[kw] = [(w, n) for w, n in c.most_common(per) if n >= 3]
    stream_top = {w for v in streams.values() for w, _ in v}
    missing = [w for w in dict.fromkeys(top + list(stream_top)) if w not in oa_map(con)]
    if missing:
        batch(con, missing)  # 후보에 없던 고전을 가져온다
    m = oa_map(con)
    con.execute("UPDATE papers SET local_cites=NULL, core_links=NULL")
    for w, c in cnt.items():
        if w in m and c >= 2:
            con.execute("UPDATE papers SET local_cites=? WHERE id=?", (c, m[w]))
    core = set(top) | stream_top
    for pid, ws in refs_by_paper(con).items():
        con.execute("UPDATE papers SET core_links=? WHERE id=?", (len(core & set(ws)), pid))
    con.commit()

    def show(title, rows, fmt):
        print(f"\n[{title}] {len(rows)}편")
        for r in rows:
            print("  " + fmt(r))
    q = "SELECT id, year, title, venue, cited_by, local_cites, core_links, is_review, status FROM papers"
    show("고전 후보 (후보 논문들이 인용한 횟수순)",
         con.execute(q + " WHERE local_cites IS NOT NULL ORDER BY local_cites DESC LIMIT ?", (n_classics,)).fetchall(),
         lambda r: f"#{r['id']} {r['year']} 후보인용 {r['local_cites']} | {r['title'][:80]} — {r['venue'] or ''}")
    show("리뷰 후보 (고전 연결 수 → 인용수 순)",
         con.execute(q + f" WHERE is_review=1 ORDER BY COALESCE(core_links,0) DESC, cited_by DESC LIMIT 20").fetchall(),
         lambda r: f"#{r['id']} {r['year']} 고전연결 {r['core_links'] or 0} 인용 {r['cited_by']} | {r['title'][:80]}")
    show("최전선 후보 (최근 3년 · 고전 2편 이상 인용 · 연간 인용순)",
         con.execute(q + " WHERE year >= ? AND COALESCE(core_links,0) >= 2 AND COALESCE(is_review,0)=0 "
                         "ORDER BY cited_by * 1.0 / (? - year + 1) DESC LIMIT 20", (YEAR - 3, YEAR)).fetchall(),
         lambda r: f"#{r['id']} {r['year']} 고전연결 {r['core_links']} 인용 {r['cited_by']} | {r['title'][:80]}")
    m = oa_map(con)
    title_of = {r["id"]: r for r in con.execute(q).fetchall()}
    for kw, lst in streams.items():
        rows = [title_of[m[w]] for w, _ in lst if w in m and m[w] in title_of]
        show(f"흐름별 고전 · {kw}", rows,
             lambda r: f"#{r['id']} {r['year']} 후보인용 {r['local_cites'] or 0} | {r['title'][:80]} — {r['venue'] or ''}")
    seeds = [terms(k) for k in brief["keywords"][:3]]
    rows = []
    for r in con.execute("SELECT id, year, title, abstract, venue, cited_by, local_cites, core_links, is_review, status FROM papers "
                         "ORDER BY COALESCE(core_links,0) DESC, cited_by DESC"):
        text = (r["title"] + " " + (r["abstract"] or "")).lower()
        if any(all(t in text for t in ts) for ts in seeds):
            rows.append(r)
    show(f"직결 후보 (제목·초록에 {' / '.join(' + '.join(ts) for ts in seeds)})", rows[:25],
         lambda r: f"#{r['id']} {r['year']} 고전연결 {r['core_links'] or 0} 인용 {r['cited_by']} | {r['title'][:80]}")
    print(f"\n리뷰 {len(reviews)}편 확인, 고전 {len(missing)}편 새로 가져옴. 초록은 sqlite3 로 읽고 db.py pick 으로 고른다.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "discover"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--classics", type=int, default=25)
    ap.add_argument("--reviews", type=int, default=8)
    a = ap.parse_args()
    con = connect(a.project)
    if a.cmd == "discover":
        from fetch_openalex import search
        search(con, read_brief(a.project), 1)  # 키워드당 1쪽(50편)만 — 쏟아 붓지 않는다
    run(con, a.project, a.classics, a.reviews)
