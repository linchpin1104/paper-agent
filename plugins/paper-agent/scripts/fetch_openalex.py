"""OpenAlex 수집. 키 불필요.
  python scripts/fetch_openalex.py search  --project SLUG [--pages 2]
  python scripts/fetch_openalex.py related --project SLUG      # favorite 논문의 참고문헌·피인용·유사 1홉
  python scripts/fetch_openalex.py add --project SLUG --query "제목 또는 DOI"   # 아는 논문을 찾아 ★ 로 등록
"""
import argparse, json, re, sys, time, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from db import connect, read_brief, upsert_paper, add_edge, log_search, log_hits, load_env

API = "https://api.openalex.org"
SRC = "openalex"


class BudgetError(RuntimeError):
    pass


def get(path, **params):
    """OpenAlex 요청. .env 의 OPENALEX_API_KEY 가 있으면 내 키의 사용량을 쓴다.
    키가 없으면 같은 인터넷 주소의 사용자들이 하루 무료 사용량을 나눠 쓴다 (검색 요청이 조회보다 10배 비쌈)."""
    env = load_env()
    if env.get("CONTACT_EMAIL"):
        params["mailto"] = env["CONTACT_EMAIL"]
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": "paper-agent/0.1"}
    if env.get("OPENALEX_API_KEY"):
        headers["Authorization"] = "Bearer " + env["OPENALEX_API_KEY"]
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                body = e.read().decode("utf-8", "replace")
                if "budget" in body.lower():
                    raise BudgetError("OpenAlex 하루 사용량을 다 썼습니다 (매일 오전 9시(한국) 초기화). "
                                      ".env 에 OPENALEX_API_KEY 를 넣으면 내 몫의 사용량을 씁니다. "
                                      "무료 발급: https://help.openalex.org/api/authentication/") from None
                time.sleep(2 ** i)
                continue
            if e.code == 503:
                time.sleep(2 ** i)
                continue
            if e.code == 404:
                return None
            raise
    raise RuntimeError("openalex 실패: " + url)


def abstract(inv):
    if not inv:
        return None
    pos = {}
    for w, ps in inv.items():
        for p in ps:
            pos[p] = w
    return " ".join(pos[i] for i in sorted(pos))


def rec(w):
    src = ((w.get("primary_location") or {}).get("source") or {})
    oa = w.get("best_oa_location") or {}
    return dict(doi=w.get("doi"), title=w.get("display_name"),
                authors="; ".join(a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author")),
                year=w.get("publication_year"), venue=src.get("display_name"),
                abstract=abstract(w.get("abstract_inverted_index")), cited_by=w.get("cited_by_count"),
                oa_url=oa.get("pdf_url"), url=w.get("doi") or w.get("id"))


def oid(w):
    return w["id"].rsplit("/", 1)[-1]


def upsert_works(con, works, exclude=()):
    ids = {}
    for w in works:
        if not w.get("display_name"):
            continue
        t = w["display_name"].lower()
        if any(x.lower() in t for x in exclude):
            continue
        pid = upsert_paper(con, rec(w), SRC, oid(w), raw={"id": w["id"], "referenced_works": w.get("referenced_works", []),
                                                         "date": w.get("publication_date")})
        if pid:
            ids[oid(w)] = pid
    return ids


def field_filter(brief):
    """연구 주제 설정의 '검색 분야'. 'system dynamics', 'feedback loops' 같은 방법·개념어를 분야 제한 없이
    단독 검색하면 공학·생물학 논문이 대부분을 차지한다. 기본은 사회과학, 필요하면 공학 등을 더하거나 '전체'."""
    return f",primary_topic.field.id:{'|'.join(map(str, brief['fields']))}" if brief.get("fields") else ""


def queries(brief):
    """[(기록 이름, 검색식)]. 키워드마다 하나 + 첫 키워드(중심 개념)와 다음 3개의 교차 검색.
    교차 검색은 두 흐름이 만나는 논문(예: 시스템 다이내믹스 × 벤처캐피탈)을 따로 잡는다.
    교차 검색은 이미 주제가 좁혀져 있어 분야 제한 없이 찾는다 (공학·컴퓨터과학 저널의 관련 논문도 잡히게)."""
    kws = brief["keywords"]
    out = [(k, k) for k in kws]
    if len(kws) >= 2:
        k0 = kws[0].replace('"', "")
        out += [(f"{k0} × {k.replace(chr(34), '')}", f'"{k0}" AND "{k.replace(chr(34), "")}"') for k in kws[1:4]]
    return out


def search(con, brief, pages):
    y0, y1 = brief["years"]
    total = 0
    for label, q in queries(brief):
        n = 0
        for page in range(1, pages + 1):  # 관련도 정렬만. 인용수 정렬은 주제 밖 논문을 끌어온다
            fields = "" if " × " in label else field_filter(brief)
            d = get("/works", search=q, filter=f"publication_year:{y0}-{y1},type:article{fields}", per_page=50, page=page) or {}
            got = upsert_works(con, d.get("results", []), brief["exclude"])
            log_hits(con, got.values(), label)
            n += len(got)
            if len(d.get("results", [])) < 50:
                break
        log_search(con, SRC, label, n)
        con.commit()
        print(f"[openalex] {label!r}: {n}")
        total += n
    return total


def batch(con, ids):
    """OpenAlex id 목록을 50개씩 받아 upsert. {oid: pid}"""
    out = {}
    ids = [i for i in ids if i]
    for i in range(0, len(ids), 50):
        d = get("/works", filter="ids.openalex:" + "|".join(ids[i:i + 50]), per_page=50)
        out.update(upsert_works(con, d.get("results", []) if d else []))
    return out


def add(con, query):
    """제목 또는 DOI 로 한 편을 찾아 ★(favorite) 로 등록. 찾은 논문을 출력해 사람이 맞는지 확인하게 한다."""
    q = query.strip()
    if q.lower().startswith(("10.", "https://doi.org/", "doi:")):
        w = get("/works/doi:" + re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", q, flags=re.I))
        works = [w] if w else []
    else:
        works = (get("/works", search=q, per_page=3) or {}).get("results", [])
    if not works:
        print(f"못 찾음: {q}")
        return None
    w = works[0]
    pid = upsert_works(con, [w]).get(oid(w))
    con.execute("UPDATE papers SET favorite=1 WHERE id=?", (pid,))
    con.commit()
    print(f"★ #{pid} {w.get('publication_year')} {w.get('display_name')} — "
          f"{((w.get('primary_location') or {}).get('source') or {}).get('display_name', '')}")
    for alt in works[1:]:
        print(f"   (다른 후보) {alt.get('publication_year')} {alt.get('display_name')}")
    return pid


def related(con):
    favs = con.execute("SELECT id, doi FROM papers WHERE favorite=1").fetchall()
    if not favs:
        print("favorite 논문이 없습니다. 페이지에서 ★ 표시 후 다시 실행.")
        return
    for f in favs:
        row = con.execute("SELECT source_id FROM sources WHERE paper_id=? AND source=?", (f["id"], SRC)).fetchone()
        w = get(f"/works/{row['source_id']}") if row else (get(f"/works/doi:{f['doi']}") if f["doi"] else None)
        if not w:
            print(f"  #{f['id']} openalex 에 없음")
            continue
        upsert_works(con, [w])
        refs = batch(con, [r.rsplit("/", 1)[-1] for r in w.get("referenced_works", [])])
        for pid in refs.values():
            add_edge(con, f["id"], pid, "cites", SRC)
        sim = batch(con, [r.rsplit("/", 1)[-1] for r in w.get("related_works", [])[:20]])
        for pid in sim.values():
            add_edge(con, f["id"], pid, "similar", SRC)
        d = get("/works", filter=f"cites:{oid(w)}", sort="cited_by_count:desc", per_page=50)
        cit = upsert_works(con, d.get("results", []) if d else [])
        for pid in cit.values():
            add_edge(con, pid, f["id"], "cites", SRC)
        con.commit()
        print(f"  #{f['id']} 참고문헌 {len(refs)} / 유사 {len(sim)} / 피인용 {len(cit)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search", "related", "add"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--query")
    a = ap.parse_args()
    con = connect(a.project)
    if a.cmd == "search":
        print("합계", search(con, read_brief(a.project), a.pages))
    elif a.cmd == "add":
        add(con, a.query)
    else:
        related(con)
