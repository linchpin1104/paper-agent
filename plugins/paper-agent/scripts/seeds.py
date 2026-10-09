"""핵심 논문(★)에서 출발하는 연관 논문 찾기.
  python scripts/seeds.py find   --project SLUG --query "제목 또는 DOI"   # 후보 3개와 일치도. 사람이 맞는 것을 고른다
  python scripts/seeds.py probe  --project SLUG --query "주제어 조합" [--top 15]   # 주제 검색 결과를 초록과 함께 보기만 (저장 안 함). 가장 가까운 선행연구 찾기용
  python scripts/seeds.py add    --project SLUG --openalex W123456          # 고른 후보를 핵심 논문으로 등록
  python scripts/seeds.py expand --project SLUG                             # 참고문헌·피인용·유사·추천 수집 → 인용 검증 → 순위
  python scripts/seeds.py rank   --project SLUG [--top 40]                  # 연관 논문 순위만 다시 보기
연관도 = 이어진 핵심 논문 수. 관계: 선행(핵심 논문이 인용) · 후속(핵심 논문을 인용) · 유사(OpenAlex 유사·S2 추천)
"""
import argparse, difflib, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import connect, VERIFY
import fetch_openalex as oa
import fetch_s2 as s2
import verify

ORDER = ["human", "text", "db2", "db1", "miss"]  # 보여줄 때 높은 신뢰 순


def norm(t):
    return re.sub(r"[^a-z0-9가-힣 ]", "", verify.plain(t)).strip()


def find(query, year=None):
    """후보 최대 3개: [{openalex, title, authors, year, venue, doi, match}]. year 를 주면 그 해 ±1 로 좁힌다 (재판본 대신 원본)."""
    q = query.strip()
    if re.match(r"^(https?://(dx\.)?doi\.org/|doi:)?10\.", q, re.I):
        w = oa.get("/works/doi:" + re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", q, flags=re.I))
        works = [w] if w else []
    else:
        clean = re.sub(r"[,:;()\[\]\"?!|]", " ", q)  # 쉼표 등은 OpenAlex 검색에서 400 오류
        extra = {"filter": f"publication_year:{year - 1}-{year + 1}"} if year else {}
        works = (oa.get("/works", search=clean, per_page=3, **extra) or {}).get("results", [])
    out = []
    for w in works:
        r = oa.rec(w)
        out.append(dict(openalex=oa.oid(w), title=r["title"], authors=r["authors"], year=r["year"], venue=r["venue"],
                        doi=r["doi"], match=round(difflib.SequenceMatcher(None, norm(q), norm(r["title"] or "")).ratio(), 2)))
    return out


def add(con, openalex_id):
    w = oa.get(f"/works/{openalex_id}")
    if not w:
        return None
    pid = oa.upsert_works(con, [w]).get(oa.oid(w))
    con.execute("UPDATE papers SET favorite=1 WHERE id=?", (pid,))
    con.commit()
    return pid


def rank(con, top=40):
    """핵심 논문이 아닌 논문마다 이어진 핵심 논문과 관계, 가장 강한 인용 검증 단계."""
    seeds = {r[0] for r in con.execute("SELECT id FROM papers WHERE favorite=1")}
    agg = {}
    for e in con.execute("SELECT from_id, to_id, kind, verified FROM edges"):
        a, b = e["from_id"], e["to_id"]
        if a in seeds and b not in seeds:
            other, rel = b, ("선행" if e["kind"] == "cites" else "유사")
            seed = a
        elif b in seeds and a not in seeds:
            other, rel = a, ("후속" if e["kind"] == "cites" else "유사")
            seed = b
        else:
            continue
        d = agg.setdefault(other, {"seeds": set(), "rels": set(), "levels": set()})
        d["seeds"].add(seed)
        d["rels"].add(rel)
        if e["kind"] == "cites":
            d["levels"].add(e["verified"] or "db1")
    rows = []
    for pid, d in agg.items():
        p = con.execute("SELECT id, title, year, venue, cited_by, review, status FROM papers WHERE id=?", (pid,)).fetchone()
        best = next((l for l in ORDER if l in d["levels"]), None)
        rows.append(dict(p, n_seeds=len(d["seeds"]), rels="·".join(sorted(d["rels"])), verified=best))
    rows.sort(key=lambda r: (-r["n_seeds"], ORDER.index(r["verified"]) if r["verified"] else 9, -(r["cited_by"] or 0)))
    return rows[:top] if top else rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["find", "probe", "add", "expand", "rank"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--query")
    ap.add_argument("--openalex")
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args()
    con = connect(a.project)
    if a.cmd == "find":
        for c in find(a.query):
            print(f"{c['openalex']} 일치 {c['match']} | {c['year']} {c['title']} — {c['authors'][:60]} · {c['venue'] or ''} · {c['doi'] or 'DOI 없음'}")
    elif a.cmd == "probe":
        clean = re.sub(r"[,:;()\[\]\"?!|]", " ", a.query or "")
        for w in (oa.get("/works", search=clean, per_page=min(a.top, 50)) or {}).get("results", []):
            r = oa.rec(w)
            print(f"{oa.oid(w)} | {r['year']} {r['title']} — {r['venue'] or ''} · 인용 {r['cited_by']}\n    {(r['abstract'] or '(초록 없음)')[:400]}\n")
    elif a.cmd == "add":
        pid = add(con, a.openalex)
        print(f"★ #{pid}" if pid else "못 찾음")
    else:
        if a.cmd == "expand":
            n_seed = con.execute("SELECT COUNT(*) FROM papers WHERE favorite=1").fetchone()[0]
            if not n_seed:
                sys.exit("핵심 논문(★)이 없습니다. find → add 로 먼저 등록하세요.")
            oa.related(con)
            s2.related(con)
            print("인용 검증:", verify.verify_edges(con))
        for r in rank(con, a.top):
            print(f"#{r['id']:>4} 핵심 {r['n_seeds']} {r['rels']:<8} {VERIFY.get(r['verified'], '-'):<12} {r['year']} "
                  f"{r['title'][:70]} [{r['review'] or '미검토'}]")


if __name__ == "__main__":
    main()
