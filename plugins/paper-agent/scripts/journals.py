"""학회지 구독 — 연구 프로젝트와 별개. 구독한 학회지에 새로 실린 논문을 키워드로 거르지 않고 모두 받는다.
  python scripts/journals.py find    --query "이름 또는 ISSN"          # 후보. 사람이 고른다
  python scripts/journals.py add     --source S123                     # 구독
  python scripts/journals.py remove  --source S123
  python scripts/journals.py profile [--source S123] [--project SLUG] # 최근 3년 분석. --project 를 주면 그 프로젝트와의 맞춤도도
  python scripts/journals.py update  [--days 90]                      # 지난 확인 이후 새 논문 수신 (처음엔 최근 N일)
  python scripts/journals.py new     [--project SLUG]                  # 확인하지 않은 새 논문 (학회지·날짜순, 초록 포함)
  python scripts/journals.py seen                                      # 새 논문을 모두 확인함으로
  python scripts/journals.py send    --project SLUG --ids 12,15        # 고른 논문을 프로젝트 읽을 목록으로 보낸다
저장: 작업 폴더의 journals/ (watch.json · library.db · feeds/요약.md)
"""
import argparse, datetime, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import db
from db import connect, connect_dir, read_brief, log_hits, now
from fetch_openalex import get, upsert_works, batch
from keypapers import terms

TODAY = datetime.date.today()


def jdir():
    return db.HOME / "journals"


def jcon():
    return connect_dir(jdir())


def load():
    p = jdir() / "watch.json"
    return json.loads(p.read_text()) if p.exists() else {"journals": [], "new": []}


def save(d):
    jdir().mkdir(parents=True, exist_ok=True)
    (jdir() / "watch.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))


def sid(s):
    return s.rsplit("/", 1)[-1]


def find(query):
    q = query.strip()
    flt = {"filter": f"issn:{q}"} if len(q) == 9 and q[4] == "-" else {"search": q}
    res = (get("/sources", per_page=5, **flt) or {}).get("results", [])
    return [dict(source=sid(s["id"]), name=s["display_name"], issn=s.get("issn_l"), publisher=s.get("host_organization_name"),
                 works=s.get("works_count"), h=(s.get("summary_stats") or {}).get("h_index"),
                 if2=(s.get("summary_stats") or {}).get("2yr_mean_citedness"), type=s.get("type"))
            for s in res]


def seed_ids(pcon):
    return {r[0] for r in pcon.execute("SELECT s.source_id FROM sources s JOIN papers p ON p.id=s.paper_id "
                                       "WHERE p.favorite=1 AND s.source='openalex'")}


def profile(j, project=None):
    """최근 3년: 편수·주제·국가·한국 저자·고인용. project 를 주면 그 주제 키워드·핵심 논문과의 맞춤도."""
    y0, y1 = TODAY.year - 3, TODAY.year
    base = f"primary_location.source.id:{j['source']},publication_year:{y0}-{y1},type:article"
    g = lambda key: [(x["key_display_name"], x["count"]) for x in (get("/works", filter=base, group_by=key) or {}).get("group_by", [])]
    all_countries = g("authorships.countries")
    top = (get("/works", filter=base, sort="cited_by_count:desc", per_page=5) or {}).get("results", [])
    pr = dict(at=now(), period=f"{y0}–{y1}", years=sorted(g("publication_year")), topics=g("primary_topic.id")[:8],
              countries=all_countries[:8], korea=next((n for c, n in all_countries if "Korea" in (c or "")), 0),
              top=[(w.get("publication_year"), w.get("display_name"), w.get("cited_by_count")) for w in top])
    if project:
        pcon = connect(project)
        kw = {}
        for k in read_brief(project)["keywords"][:5]:
            d = get("/works", filter=base, search=" AND ".join(f'"{t}"' for t in terms(k)), per_page=1) or {}
            kw[k] = d.get("meta", {}).get("count", 0)
        names = {r["source_id"]: r["title"] for r in pcon.execute(
            "SELECT s.source_id, p.title FROM sources s JOIN papers p ON p.id=s.paper_id WHERE s.source='openalex'")}
        cites = {}
        for w in sorted(seed_ids(pcon))[:10]:
            cites[names.get(w, w)] = (get("/works", filter=base + f",cites:{w}", per_page=1) or {}).get("meta", {}).get("count", 0)
        j.setdefault("fit", {})[project] = dict(at=now(), my_keywords=kw, cites_my_seeds=cites)
    j["profile"] = pr
    return j


def update(days):
    d, con = load(), jcon()
    total = 0
    for j in d["journals"]:
        since = j.get("last_checked") or (TODAY - datetime.timedelta(days=days)).isoformat()
        got = {}
        for page in range(1, 5):
            res = (get("/works", filter=f"primary_location.source.id:{j['source']},from_publication_date:{since}",
                       sort="publication_date:desc", per_page=50, page=page) or {}).get("results", [])
            got.update(upsert_works(con, res))
            if len(res) < 50:
                break
        log_hits(con, got.values(), f"journal:{j['name']}")
        known = set(d["new"]) | set(j.get("seen_ids", []))
        fresh = [p for p in dict.fromkeys(got.values()) if p not in known]  # 같은 논문이 두 기록으로 오면 한 번만
        d["new"] += fresh
        j["last_checked"] = TODAY.isoformat()
        print(f"[{j['name']}] {since} 이후 {len(got)}편, 새로 {len(fresh)}편")
        total += len(fresh)
    con.commit()
    save(d)
    return total


def new_list(project=None):
    """새 논문. project 를 주면 관련도(그 프로젝트 핵심 논문 인용 ×2 + 주제 키워드 일치)를 덧붙인다."""
    d, con = load(), jcon()
    jmap = {r["paper_id"]: r["query"][8:] for r in con.execute("SELECT paper_id, query FROM hits WHERE query LIKE 'journal:%'")}
    seeds, seed_terms = set(), []
    if project:
        seeds = seed_ids(connect(project))
        seed_terms = [terms(k) for k in read_brief(project)["keywords"][:5]]
    out = []
    for pid in dict.fromkeys(d["new"]):
        p = con.execute("SELECT id, title, year, abstract, authors, doi FROM papers WHERE id=?", (pid,)).fetchone()
        if not p:
            continue
        raw = con.execute("SELECT raw FROM sources WHERE paper_id=? AND source='openalex'", (pid,)).fetchone()
        rj = json.loads(raw["raw"]) if raw and raw["raw"] else {}
        r = dict(p, journal=jmap.get(pid, ""), date=rj.get("date") or str(p["year"] or ""))
        if project:
            text = (p["title"] + " " + (p["abstract"] or "")).lower()
            r["kw"] = [" + ".join(ts) for ts in seed_terms if all(t in text for t in ts)]
            r["cites_seeds"] = len({sid(w) for w in rj.get("referenced_works", [])} & seeds)
            r["score"] = r["cites_seeds"] * 2 + len(r["kw"])
        out.append(r)
    out.sort(key=lambda r: (r["journal"], r["date"]), reverse=False)
    out.sort(key=lambda r: r["date"], reverse=True)
    out.sort(key=lambda r: r["journal"])
    return out


def send(project, ids):
    """구독 DB 의 논문을 프로젝트로 복사해 읽을 목록에 넣는다."""
    con, pcon = jcon(), connect(project)
    wids = [r["source_id"] for r in con.execute(
        f"SELECT source_id FROM sources WHERE source='openalex' AND paper_id IN ({','.join('?' * len(ids))})", ids)]
    got = batch(pcon, wids)
    pcon.executemany("UPDATE papers SET status='shortlist' WHERE id=? AND status='candidate'", [(p,) for p in got.values()])
    pcon.commit()
    return len(got)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["find", "add", "remove", "profile", "update", "new", "seen", "send"])
    ap.add_argument("--project")
    ap.add_argument("--query")
    ap.add_argument("--source")
    ap.add_argument("--ids")
    ap.add_argument("--days", type=int, default=90)
    a = ap.parse_args()
    d = load()
    if a.cmd == "find":
        for c in find(a.query):
            print(f"{c['source']} | {c['name']} · ISSN {c['issn']} · {c['publisher']} · 논문 {c['works']} · h {c['h']}")
    elif a.cmd == "add":
        src = get(f"/sources/{a.source}") or {}
        if not any(j["source"] == a.source for j in d["journals"]):
            d["journals"].append({"source": a.source, "name": src.get("display_name", a.source), "issn": src.get("issn_l"),
                                  "publisher": src.get("host_organization_name"), "added": now()})
        save(d)
        print("구독:", src.get("display_name", a.source))
    elif a.cmd == "remove":
        d["journals"] = [j for j in d["journals"] if j["source"] != a.source]
        save(d)
        print("ok")
    elif a.cmd == "profile":
        for j in d["journals"]:
            if a.source and j["source"] != a.source:
                continue
            profile(j, a.project)
            pr = j["profile"]
            print(f"[{j['name']}] {pr['period']} 편수 {pr['years']} · 한국 저자 {pr['korea']} · 주제 {[t for t, _ in pr['topics'][:3]]}")
            if a.project:
                f = j["fit"][a.project]
                print(f"   {a.project} 맞춤도: 키워드 {f['my_keywords']} · 핵심 논문 인용 {f['cites_my_seeds']}")
        save(d)
    elif a.cmd == "update":
        print("새 논문 합계", update(a.days))
    elif a.cmd == "new":
        for r in new_list(a.project):
            extra = f" 관련 {r['score']}" if a.project else ""
            print(f"#{r['id']} [{r['journal'][:30]}] {r['date']}{extra} | {r['title'][:90]}\n    {(r['abstract'] or '(초록 없음)')[:300]}")
    elif a.cmd == "seen":
        for j in d["journals"]:
            j["seen_ids"] = sorted(set(j.get("seen_ids", [])) | set(d["new"]))
        d["new"] = []
        save(d)
        print("ok")
    elif a.cmd == "send":
        print(f"{send(a.project, [int(x) for x in a.ids.split(',')])}편을 {a.project} 읽을 목록으로 보냄")


if __name__ == "__main__":
    main()
