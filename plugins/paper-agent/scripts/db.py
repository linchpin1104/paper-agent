"""논문 프로젝트 정본 DB. 표준 라이브러리만 사용.

CLI:
  python scripts/db.py init  --project SLUG
  python scripts/db.py list  --project SLUG [--status shortlist] [--favorite]
  python scripts/db.py text  --project SLUG --paper ID        # 추출 원문을 쪽 구분으로 출력
  python scripts/db.py note  --project SLUG --paper ID --section 연구질문 --content "..." [--quote "..."] [--page 3]
  python scripts/db.py notes --project SLUG --paper ID                # 노트·변수·가설 + 비어 있는 항목
  python scripts/db.py var   --project SLUG --paper ID --role IV --name "..." [--definition] [--measure] [--source] [--items 5] [--alpha .87] [--page 7]
  python scripts/db.py hyp   --project SLUG --paper ID --code H1 --statement "..." [--iv] [--dv] [--mediator] [--moderator] [--direction +] [--result 지지] [--stats "β=.21, p<.01"] [--page 9]
  python scripts/db.py outline --project SLUG --paper ID --heading "2. Theory" --start 3 --end 6 --summary "이 절의 요지"   # 논문 구조 맵. 순서대로 넣는다
  python scripts/db.py flow  --project SLUG --paper ID --step 문제의식 --claim "1~2문장" --page 2 [--fig "Figure 1"]   # 논증 흐름
  python scripts/db.py memos --project SLUG [--paper ID]      # 사용자가 읽으며 남긴 형광펜 메모
  python scripts/db.py pick    --project SLUG --paper ID --tier 리뷰|고전|최전선|직결 --reason "고른 이유 1문장"
  python scripts/db.py unpick  --project SLUG --paper ID
  python scripts/db.py reading --project SLUG              # 읽을 목록 제안 보기
  python scripts/db.py clear --project SLUG --paper ID                 # 그 논문의 노트·변수·가설 삭제 (재분석 전)
"""
import argparse, datetime, json, os, pathlib, re, sqlite3, sys
try:  # python.org 빌드는 시스템 인증서를 못 읽는다
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent  # 플러그인 폴더 (도구)
HOME = pathlib.Path(os.environ.get("PAPER_AGENT_HOME") or pathlib.Path.cwd())  # 작업 폴더 (데이터: projects/, .env)
# 분석 항목. 순서 = 화면 순서. [평가]·[해석] 은 원문 요약이 아니라 분석자 판단.
SECTIONS = ["한 줄 요약", "연구 배경·문제의식", "연구질문", "이론 기반", "핵심 개념·정의", "연구 모형",
            "가설 또는 명제", "표본·맥락", "측정 또는 자료", "분석 기법", "주요 결과", "이론적 기여",
            "실무적 시사점", "한계", "향후 연구 제안", "[평가] 방법론", "[해석] 비운 자리",
            "[해석] 내 연구와의 연결", "인용할 문장", "핵심 참고문헌"]
# 내 메모 색 = 의미. 이름: (형광 RGB, 화면 표시색)
MEMO_COLORS = {"중요": ((1.0, 0.86, 0.2), "#f2c200"), "내 연구에 활용": ((0.55, 0.88, 0.55), "#3f9d4f"),
               "의문·반박": ((1.0, 0.6, 0.75), "#d9487a"), "인용 후보": ((0.55, 0.78, 1.0), "#3a7bd5")}

# 논증 흐름: 이 논문이 왜 → 무엇을 근거로 → 무엇을 주장하고 → 어떻게 보였고 → 그래서 무엇이 새로운가
FLOW = ["문제의식", "연구 공백", "연구 목적", "이론적 근거", "가설·주장", "연구 방법", "핵심 발견", "기여", "한계·과제"]
ROLES = ["IV", "DV", "MED", "MOD", "CTRL", "기타"]  # 독립·종속·매개·조절·통제
# 읽을 목록 제안용 칸: 묶음(tier)·선정 이유·후보들이 인용한 횟수·핵심 논문과의 연결 수·리뷰 여부
PAPER_EXTRA = [("tier", "TEXT"), ("reason", "TEXT"), ("local_cites", "INTEGER"), ("core_links", "INTEGER"),
               ("is_review", "INTEGER"),
               # 검토: 사람이 원문을 보고 확인한 결과. title_check 는 PDF 첫 쪽에 기록된 제목이 있는지 자동 검사
               ("review", "TEXT"), ("review_note", "TEXT"), ("reviewed_at", "TEXT"), ("title_check", "TEXT")]
# 인용 관계 검증: 기록한 출처 목록, 검증 단계, 근거(원문 쪽·문구)
EDGE_EXTRA = [("sources", "TEXT"), ("verified", "TEXT"), ("evidence", "TEXT")]
NOTE_EXTRA = [("quote_ok", "INTEGER"), ("checked", "INTEGER")]
REVIEW = ["미검토", "원문 확인함", "문제 있음"]
# 인용 검증 단계 (낮은 → 높은). miss = 원문이 있는데 참고문헌에서 못 찾음 → 사람 확인 필요
VERIFY = {"db1": "DB 1곳 기록", "db2": "DB 2곳 일치", "miss": "원문에서 못 찾음", "text": "원문 참고문헌 확인", "human": "사람 확인"}
TIERS = ["리뷰", "고전", "최전선", "직결"]
STATUSES = ["candidate", "shortlist", "fulltext", "analyzed", "rejected"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers(
  id INTEGER PRIMARY KEY, doi TEXT UNIQUE, title TEXT NOT NULL, norm_title TEXT,
  authors TEXT, year INTEGER, venue TEXT, abstract TEXT, cited_by INTEGER DEFAULT 0,
  oa_url TEXT, url TEXT, pdf_path TEXT, status TEXT DEFAULT 'candidate',
  favorite INTEGER DEFAULT 0, index_tag TEXT, added_at TEXT);
CREATE INDEX IF NOT EXISTS papers_norm ON papers(norm_title);
CREATE TABLE IF NOT EXISTS sources(paper_id INTEGER, source TEXT, source_id TEXT, url TEXT, raw TEXT,
  UNIQUE(source, source_id));
CREATE TABLE IF NOT EXISTS fulltext(paper_id INTEGER PRIMARY KEY, pages TEXT, extracted_at TEXT);
CREATE TABLE IF NOT EXISTS edges(from_id INTEGER, to_id INTEGER, kind TEXT, UNIQUE(from_id, to_id, kind));
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, paper_id INTEGER, section TEXT, content TEXT,
  quote TEXT, page INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS variables(id INTEGER PRIMARY KEY, paper_id INTEGER, role TEXT, name TEXT,
  definition TEXT, measure TEXT, source TEXT, items INTEGER, alpha REAL, page INTEGER);
CREATE TABLE IF NOT EXISTS hypotheses(id INTEGER PRIMARY KEY, paper_id INTEGER, code TEXT, statement TEXT,
  iv TEXT, dv TEXT, mediator TEXT, moderator TEXT, direction TEXT, result TEXT, stats TEXT, page INTEGER);
CREATE TABLE IF NOT EXISTS outline(id INTEGER PRIMARY KEY, paper_id INTEGER, heading TEXT, page_start INTEGER,
  page_end INTEGER, summary TEXT);
CREATE TABLE IF NOT EXISTS figures(id INTEGER PRIMARY KEY, paper_id INTEGER, label TEXT, kind TEXT, page INTEGER,
  x0 REAL, y0 REAL, x1 REAL, y1 REAL, caption TEXT, role TEXT, note TEXT, rot INTEGER DEFAULT 0, UNIQUE(paper_id, label));
CREATE TABLE IF NOT EXISTS flow(id INTEGER PRIMARY KEY, paper_id INTEGER, step TEXT, claim TEXT, page INTEGER, fig TEXT);
CREATE TABLE IF NOT EXISTS memos(id INTEGER PRIMARY KEY, paper_id INTEGER, page INTEGER, x0 REAL, y0 REAL,
  x1 REAL, y1 REAL, color TEXT, excerpt TEXT, memo TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS hits(paper_id INTEGER, query TEXT, UNIQUE(paper_id, query));
CREATE TABLE IF NOT EXISTS searches(id INTEGER PRIMARY KEY, source TEXT, query TEXT, run_at TEXT, n INTEGER);
"""


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def load_env():
    """작업 폴더 .env 의 KEY=VALUE 를 dict 로. 없으면 빈 dict."""
    env = {}
    p = HOME / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def project_dir(slug):
    d = HOME / "projects" / slug
    if not d.exists():
        sys.exit(f"프로젝트 없음: {d}")
    return d


def connect(slug):
    return connect_dir(project_dir(slug))


def connect_dir(d):
    """프로젝트가 아닌 폴더(예: 학회지 구독 journals/)에도 같은 DB 구조를 쓴다."""
    d = pathlib.Path(d)
    d.mkdir(parents=True, exist_ok=True)
    (d / "pdf").mkdir(exist_ok=True)
    (d / "gaps").mkdir(exist_ok=True)
    (d / "export").mkdir(exist_ok=True)
    con = sqlite3.connect(d / "library.db")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for table, extra in (("papers", PAPER_EXTRA), ("edges", EDGE_EXTRA), ("notes", NOTE_EXTRA)):
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, typ in extra:
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    return con


def read_brief(slug):
    """brief.md 의 '- 키: 값' 줄을 dict 로. keywords/exclude 는 리스트, years 는 (시작, 끝)."""
    text = (project_dir(slug) / "brief.md").read_text()
    b = {}
    for m in re.finditer(r"^- *([^:：]+?)[ \t]*[:：][ \t]*(.*)$", text, re.M):
        b[m.group(1).strip()] = m.group(2).strip()
    b["keywords"] = [k.strip() for k in re.split(r"[,;]", b.get("주제 씨앗", "")) if k.strip()]
    b["keywords_ko"] = [k.strip() for k in re.split(r"[,;]", b.get("국문 키워드", "")) if k.strip() and "(" not in k]
    b["exclude"] = [k.strip() for k in re.split(r"[,;]", b.get("제외 키워드", "")) if k.strip()]
    ys = re.findall(r"\d{4}", b.get("연도 범위", ""))
    b["years"] = (int(ys[0]), int(ys[-1])) if ys else (2015, datetime.date.today().year)
    return b


def norm_doi(doi):
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def norm_title(t):
    return re.sub(r"[^a-z0-9가-힣]", "", (t or "").lower())[:120]


def upsert_paper(con, rec, source, source_id, raw=None):
    """rec: doi,title,authors,year,venue,abstract,cited_by,oa_url,url. DOI → 제목 순으로 중복 제거. paper id 반환."""
    doi, nt = norm_doi(rec.get("doi")), norm_title(rec.get("title"))
    if not nt:
        return None
    row = None
    if doi:
        row = con.execute("SELECT id FROM papers WHERE doi=?", (doi,)).fetchone()
    if row is None:
        row = con.execute("SELECT id FROM papers WHERE norm_title=?", (nt,)).fetchone()
    if row is None:
        cur = con.execute(
            "INSERT INTO papers(doi,title,norm_title,authors,year,venue,abstract,cited_by,oa_url,url,added_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (doi, rec["title"], nt, rec.get("authors"), rec.get("year"), rec.get("venue"), rec.get("abstract"),
             rec.get("cited_by") or 0, rec.get("oa_url"), rec.get("url"), now()))
        pid = cur.lastrowid
    else:
        pid = row["id"]
        # 비어 있는 칸만 채운다. 인용수는 큰 값으로.
        con.execute(
            "UPDATE papers SET doi=COALESCE(doi,?), authors=COALESCE(authors,?), year=COALESCE(year,?),"
            " venue=COALESCE(venue,?), abstract=COALESCE(abstract,?), cited_by=MAX(cited_by,?),"
            " oa_url=COALESCE(oa_url,?), url=COALESCE(url,?) WHERE id=?",
            (doi, rec.get("authors"), rec.get("year"), rec.get("venue"), rec.get("abstract"),
             rec.get("cited_by") or 0, rec.get("oa_url"), rec.get("url"), pid))
    con.execute("INSERT OR IGNORE INTO sources(paper_id,source,source_id,url,raw) VALUES(?,?,?,?,?)",
                (pid, source, str(source_id), rec.get("url"), json.dumps(raw, ensure_ascii=False) if raw else None))
    return pid


def add_edge(con, a, b, kind, source=None):
    """a → b 관계. source(openalex/s2)가 다르면 출처 목록에 더한다 — 두 곳이 같은 인용을 기록하면 신뢰도가 오른다."""
    if not (a and b and a != b):
        return
    con.execute("INSERT OR IGNORE INTO edges(from_id,to_id,kind) VALUES(?,?,?)", (a, b, kind))
    if source:
        r = con.execute("SELECT sources FROM edges WHERE from_id=? AND to_id=? AND kind=?", (a, b, kind)).fetchone()
        have = set(filter(None, (r["sources"] or "").split(",")))
        if source not in have:
            have.add(source)
            con.execute("UPDATE edges SET sources=? WHERE from_id=? AND to_id=? AND kind=?", (",".join(sorted(have)), a, b, kind))


def log_hits(con, pids, query):
    """이 검색어로 걸린 논문 기록. 흐름별 고전 계산에 쓴다."""
    con.executemany("INSERT OR IGNORE INTO hits(paper_id, query) VALUES(?,?)", [(p, query) for p in pids if p])


def log_search(con, source, query, n):
    con.execute("INSERT INTO searches(source,query,run_at,n) VALUES(?,?,?,?)", (source, query, now(), n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["init", "list", "text", "note", "notes", "var", "hyp", "outline", "flow", "memos", "pick", "unpick", "reading", "clear"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--paper", type=int)
    ap.add_argument("--status")
    ap.add_argument("--favorite", action="store_true")
    for f in ["section", "content", "quote", "role", "name", "definition", "measure", "source", "code", "statement",
              "iv", "dv", "mediator", "moderator", "direction", "result", "stats", "heading", "summary", "step", "claim", "fig", "tier", "reason"]:
        ap.add_argument("--" + f)
    ap.add_argument("--page", type=int)
    ap.add_argument("--items", type=int)
    ap.add_argument("--alpha", type=float)
    ap.add_argument("--start", type=int)
    ap.add_argument("--end", type=int)
    a = ap.parse_args()
    con = connect(a.project)
    if a.cmd in ("note", "var", "hyp", "outline", "flow", "notes", "text", "clear", "pick", "unpick") and not a.paper:
        sys.exit("--paper 필요")
    if a.cmd == "init":
        print("ok", project_dir(a.project) / "library.db")
    elif a.cmd == "list":
        q, p = "SELECT id,year,cited_by,status,favorite,pdf_path IS NOT NULL AS pdf,title,venue FROM papers WHERE 1", []
        if a.status:
            q, p = q + " AND status=?", p + [a.status]
        if a.favorite:
            q += " AND favorite=1"
        for r in con.execute(q + " ORDER BY cited_by DESC", p):
            print(f"{r['id']:>4} {r['year'] or '----'} c{r['cited_by']:<5} {r['status']:<9} {'★' if r['favorite'] else ' '} "
                  f"{'pdf' if r['pdf'] else '   '} {r['title'][:90]} — {r['venue'] or ''}")
    elif a.cmd == "text":
        r = con.execute("SELECT pages FROM fulltext WHERE paper_id=?", (a.paper,)).fetchone()
        if not r:
            sys.exit("원문 없음")
        for i, pg in enumerate(json.loads(r["pages"]), 1):
            print(f"\n=== p.{i} ===\n{pg}")
    elif a.cmd == "note":
        if a.section not in SECTIONS:
            sys.exit(f"section 은 다음 중 하나: {SECTIONS}")
        ok = quote_on_page(con, a.paper, a.page, a.quote) if (a.quote and a.page) else None
        con.execute("INSERT INTO notes(paper_id,section,content,quote,page,created_at,quote_ok) VALUES(?,?,?,?,?,?,?)",
                    (a.paper, a.section, a.content, a.quote, a.page, now(), ok))
        mark_analyzed(con, a.paper)
        print("ok")
        if ok is False:
            print(f"경고: 인용문이 p.{a.page} 원문에서 그대로 찾아지지 않습니다. 철자·쪽 번호를 확인하세요.")
    elif a.cmd == "var":
        if a.role not in ROLES or not a.name:
            sys.exit(f"--role 은 {ROLES} 중 하나, --name 필요")
        con.execute("INSERT INTO variables(paper_id,role,name,definition,measure,source,items,alpha,page) VALUES(?,?,?,?,?,?,?,?,?)",
                    (a.paper, a.role, a.name, a.definition, a.measure, a.source, a.items, a.alpha, a.page))
        mark_analyzed(con, a.paper)
        print("ok")
    elif a.cmd == "hyp":
        if not (a.code and a.statement):
            sys.exit("--code, --statement 필요")
        con.execute("INSERT INTO hypotheses(paper_id,code,statement,iv,dv,mediator,moderator,direction,result,stats,page)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (a.paper, a.code, a.statement, a.iv, a.dv, a.mediator, a.moderator, a.direction, a.result, a.stats, a.page))
        mark_analyzed(con, a.paper)
        print("ok")
    elif a.cmd == "outline":
        if not (a.heading and a.start):
            sys.exit("--heading, --start 필요")
        con.execute("INSERT INTO outline(paper_id,heading,page_start,page_end,summary) VALUES(?,?,?,?,?)",
                    (a.paper, a.heading, a.start, a.end or a.start, a.summary))
        print("ok")
    elif a.cmd == "flow":
        if a.step not in FLOW or not a.claim:
            sys.exit(f"--step 은 {FLOW} 중 하나, --claim 필요")
        con.execute("DELETE FROM flow WHERE paper_id=? AND step=?", (a.paper, a.step))  # 단계당 하나
        con.execute("INSERT INTO flow(paper_id,step,claim,page,fig) VALUES(?,?,?,?,?)", (a.paper, a.step, a.claim, a.page, a.fig))
        print("ok")
    elif a.cmd == "pick":
        if a.tier not in TIERS or not a.reason:
            sys.exit(f"--tier 는 {TIERS} 중 하나, --reason 필요")
        con.execute("UPDATE papers SET tier=?, reason=? WHERE id=?", (a.tier, a.reason, a.paper))
        print("ok")
    elif a.cmd == "unpick":
        con.execute("UPDATE papers SET tier=NULL, reason=NULL WHERE id=?", (a.paper,))
        print("ok")
    elif a.cmd == "reading":
        for t in TIERS:
            rows = con.execute("SELECT id,year,title,venue,local_cites,reason,status FROM papers WHERE tier=? "
                               "ORDER BY COALESCE(local_cites,0) DESC, year", (t,)).fetchall()
            print(f"\n[{t}] {len(rows)}편")
            for r in rows:
                print(f"  #{r['id']} {r['year']} {r['title'][:80]} — {r['venue'] or ''} (후보 인용 {r['local_cites'] or 0})\n     {r['reason']}")
    elif a.cmd == "memos":
        q = "SELECT m.*, p.title FROM memos m JOIN papers p ON p.id=m.paper_id"
        rows = con.execute(q + " WHERE m.paper_id=? ORDER BY m.page, m.id", (a.paper,)) if a.paper else con.execute(q + " ORDER BY m.paper_id, m.page")
        for r in rows:
            print(f"#{r['paper_id']} p.{r['page']} [{r['color']}] \"{(r['excerpt'] or '')[:160]}\"\n   → {r['memo'] or ''}")
    elif a.cmd == "clear":
        for t in ("notes", "variables", "hypotheses", "outline", "flow"):
            con.execute(f"DELETE FROM {t} WHERE paper_id=?", (a.paper,))
        con.execute("UPDATE papers SET status='fulltext' WHERE id=? AND status='analyzed'", (a.paper,))
        print("cleared")
    elif a.cmd == "notes":
        have = set()
        for r in con.execute("SELECT section,content,quote,page FROM notes WHERE paper_id=? ORDER BY id", (a.paper,)):
            have.add(r["section"])
            print(f"## {r['section']}\n{r['content']}" + (f'\n> "{r["quote"]}" (p.{r["page"]})' if r["quote"] else "") + "\n")
        for r in con.execute("SELECT * FROM variables WHERE paper_id=? ORDER BY id", (a.paper,)):
            print(f"[변수] {r['role']} {r['name']} | {r['measure'] or ''} | {r['source'] or ''} | 문항 {r['items']} α {r['alpha']} (p.{r['page']})")
        for r in con.execute("SELECT * FROM hypotheses WHERE paper_id=? ORDER BY id", (a.paper,)):
            print(f"[가설] {r['code']} {r['statement']} → {r['result'] or '?'} {r['stats'] or ''} (p.{r['page']})")
        for r in con.execute("SELECT * FROM outline WHERE paper_id=? ORDER BY id", (a.paper,)):
            print(f"[구조] p.{r['page_start']}–{r['page_end']} {r['heading']} — {r['summary'] or ''}")
        missing = [x for x in SECTIONS if x not in have]
        for r in con.execute("SELECT * FROM flow WHERE paper_id=? ORDER BY id", (a.paper,)):
            print(f"[흐름] {r['step']}: {r['claim']} (p.{r['page']})" + (f" [{r['fig']}]" if r["fig"] else ""))
        have_flow = {r[0] for r in con.execute("SELECT step FROM flow WHERE paper_id=?", (a.paper,))}
        missing = [f"(흐름) {x}" for x in FLOW if x not in have_flow] + missing
        if not con.execute("SELECT 1 FROM outline WHERE paper_id=?", (a.paper,)).fetchone():
            missing.insert(0, "(절 목차)")
        print("\n비어 있는 항목:", ", ".join(missing) if missing else "없음")
    con.commit()


def quote_on_page(con, pid, page, quote):
    """인용문이 해당 쪽 원문에 있는지. 줄바꿈·공백·소프트 하이픈 차이는 무시."""
    r = con.execute("SELECT pages FROM fulltext WHERE paper_id=?", (pid,)).fetchone()
    if not r:
        return True  # 원문이 없으면 확인할 수 없음
    pages = json.loads(r["pages"])
    if not 1 <= page <= len(pages):
        return False
    norm = lambda t: re.sub(r"\s+", " ", t.replace("\xad", "").replace("-\n", "")).strip().lower()
    return norm(quote) in norm(pages[page - 1])


def mark_analyzed(con, pid):
    con.execute("UPDATE papers SET status='analyzed' WHERE id=? AND status!='rejected'", (pid,))


if __name__ == "__main__":
    main()
