"""초록으로 전체를 훑어 핵심 논문을 다시 추린다. 심층 분석(원문) 전에 쓰는 넓고 얕은 단계.
  python scripts/screen.py prefilter --project SLUG [--top 400]          # ① 1차 거르기: 키워드·핵심 논문 인용 연결·연도로 점수 (AI 없음)
  python scripts/screen.py run       --project SLUG [--top 400] [--redo] # ② 초록 분석: 상위 N편을 40편씩 Claude 에게. 관련도·이론·방법·맥락·역할 제안
  python scripts/screen.py summary   --project SLUG                      # 결과 요약: 이론·방법·맥락 빈도와 관련도 높은 논문 (갭·설계 단계의 재료)
결과는 papers 의 pre_score / abs_* 칸. 상태(status)·핵심(★)은 바꾸지 않는다 — 사람이 화면에서 고른다.
"""
import argparse, collections, concurrent.futures as cf, datetime, json, pathlib, re, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import connect, project_dir, read_brief, now, KEY_ROLES

BATCH = 40
MODEL = "claude-opus-5-5"
ROLES = list(KEY_ROLES) + ["무관"]


def terms(k):
    """키워드 하나 → 모두 들어 있어야 하는 단어들 (따옴표는 구문 그대로)."""
    k = k.lower().strip()
    return re.findall(r'"([^"]+)"', k) or [w for w in re.findall(r"[a-z0-9가-힣-]+", k) if len(w) > 2]


def prefilter(con, slug, top):
    """초록 있는 논문마다 점수: 키워드 일치(앞 3개는 2배) + 핵심 논문과의 인용 연결 + 후보 인용 + 최근성."""
    b = read_brief(slug)
    kws = [(terms(k), 2 if i < 3 else 1) for i, k in enumerate(b["keywords"])] + [(terms(k), 1) for k in b["keywords_ko"]]
    excl = [k.lower() for k in b["exclude"]]
    seeds = {r[0] for r in con.execute("SELECT id FROM papers WHERE favorite=1")}
    links = collections.Counter()
    for a, c in con.execute("SELECT from_id, to_id FROM edges"):
        if a in seeds and c not in seeds:
            links[c] += 1
        elif c in seeds and a not in seeds:
            links[a] += 1
    this = datetime.date.today().year
    rows = con.execute("SELECT id, title, abstract, year, local_cites FROM papers "
                       "WHERE status != 'rejected' AND abstract IS NOT NULL AND length(abstract) > 100").fetchall()
    scored = []
    for r in rows:
        text = f"{r['title']} {r['abstract']}".lower()
        if any(e in text for e in excl):
            score = 0.0
        else:
            kw = sum(w for ts, w in kws if ts and all(t in text for t in ts))
            score = kw * 2 + min(links[r["id"]], 5) * 3 + min(r["local_cites"] or 0, 10) * 0.5 \
                + (1 if (r["year"] or 0) >= this - 5 else 0) + (5 if r["id"] in seeds else 0)
        scored.append((score, r["id"]))
    con.executemany("UPDATE papers SET pre_score=? WHERE id=?", scored)
    con.commit()
    scored.sort(reverse=True)
    picked = [s for s in scored if s[0] > 0][:top]
    print(f"초록 있는 논문 {len(rows)}편 중 점수가 있는 {sum(1 for s in scored if s[0] > 0)}편, 상위 {len(picked)}편을 초록 분석 대상으로 둡니다.")
    if picked:
        print(f"점수 범위 {picked[-1][0]:.1f} ~ {picked[0][0]:.1f}")
    return [i for _, i in picked]


SYS = """당신은 사회과학(SSCI/SCI) 논문을 준비하는 연구자를 돕는 문헌 선별자입니다.
연구 주제(brief)를 기준으로 논문 초록을 읽고, 논문마다 판단을 남깁니다. 초록에 있는 것만 근거로 씁니다.
- score: 이 연구에 얼마나 쓸모 있는가. 3=핵심 후보(질문·이론·방법 중 둘 이상이 직접 겹침), 2=꼭 읽을 것, 1=배경 정도, 0=무관
- role: 이 연구 안에서 맡을 역할. 이론 앵커(검증·확장할 이론의 원전) / 방법 선례(같은 방법·자료) / 현상 선례(같은 현상, 다른 맥락·방법) /
  차별화 대상(질문이 거의 같아 차이를 밝혀야 함) / 배경 / 무관
- theory: 초록에 나온 이론·관점 (없으면 빈 문자열). method: 연구 방법·자료 (예: 패널 회귀, LinkedIn 텍스트, 사례연구). context: 표본·국가·산업
- reason: 왜 그 점수인지 한국어 한 문장. 쉬운 말로.
모든 논문에 하나씩 답합니다. id 는 받은 그대로 씁니다."""

SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["id", "score", "role", "theory", "method", "context", "reason"],
    "properties": {"id": {"type": "integer"}, "score": {"type": "integer", "minimum": 0, "maximum": 3},
                   "role": {"type": "string", "enum": ROLES}, "theory": {"type": "string"}, "method": {"type": "string"},
                   "context": {"type": "string"}, "reason": {"type": "string"}}}}}}


def ask(brief_text, papers):
    body = "\n\n".join(f"[id {p['id']}] {p['title']} ({p['year']}, {p['venue'] or ''})\n{(p['abstract'] or '')[:1800]}" for p in papers)
    r = subprocess.run(["claude", "-p", f"연구 주제(brief):\n{brief_text}\n\n논문 {len(papers)}편:\n\n{body}",
                        "--system-prompt", SYS, "--tools", "", "--no-session-persistence", "--model", MODEL,
                        "--output-format", "json", "--json-schema", json.dumps(SCHEMA, ensure_ascii=False)],
                       capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    res = json.loads(r.stdout)
    if res.get("is_error") or not res.get("structured_output"):
        raise RuntimeError(str(res.get("result") or r.stderr)[:300])
    return res["structured_output"]["items"]


def run(con, slug, top, redo):
    ids = prefilter(con, slug, top)
    q = f"SELECT id, title, abstract, year, venue FROM papers WHERE id IN ({','.join('?' * len(ids))})" + ("" if redo else " AND abs_at IS NULL")
    todo = con.execute(q, ids).fetchall() if ids else []
    if not todo:
        print("새로 분석할 초록이 없습니다 (다시 하려면 --redo).", flush=True)
        return
    brief_text = (project_dir(slug) / "brief.md").read_text()
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    print(f"초록 {len(todo)}편을 {len(batches)}묶음으로 분석합니다 (묶음당 1~3분, 3묶음씩 동시에).", flush=True)
    done = 0
    with cf.ThreadPoolExecutor(3) as ex:
        futs = {ex.submit(ask, brief_text, b): b for b in batches}
        for f in cf.as_completed(futs):
            done += 1
            try:
                items = f.result()
            except Exception as e:  # 한 묶음 실패는 건너뛰고 다음에 다시 (abs_at 이 비어 남는다)
                print(f"[{done}/{len(batches)}] 묶음 실패: {e}", flush=True)
                continue
            ok = {p["id"] for p in futs[f]}
            con.executemany("UPDATE papers SET abs_score=?, abs_role=?, abs_theory=?, abs_method=?, abs_context=?, abs_note=?, abs_at=? WHERE id=?",
                            [(it["score"], it["role"], it["theory"], it["method"], it["context"], it["reason"], now(), it["id"])
                             for it in items if it["id"] in ok])
            con.commit()
            print(f"[{done}/{len(batches)}] 묶음 끝 · {len(items)}편 기록", flush=True)
    summary(con)


def summary(con):
    rows = con.execute("SELECT id, year, title, abs_score, abs_role, abs_theory, abs_method, abs_context, abs_note, status, favorite "
                       "FROM papers WHERE abs_at IS NOT NULL").fetchall()
    if not rows:
        print("초록 분석 결과가 없습니다.")
        return
    n = collections.Counter(r["abs_score"] for r in rows)
    print(f"\n초록 분석 {len(rows)}편 · 관련도 3: {n[3]} · 2: {n[2]} · 1: {n[1]} · 0: {n[0]}")
    print("제안 역할: " + " · ".join(f"{k} {v}" for k, v in collections.Counter(r["abs_role"] for r in rows if r["abs_score"] >= 2).most_common()))
    for col, name in (("abs_theory", "이론"), ("abs_method", "방법"), ("abs_context", "맥락")):
        c = collections.Counter(t.strip() for r in rows if r["abs_score"] >= 2 for t in re.split(r"[;,/·]", r[col] or "") if t.strip())
        print(f"{name} (관련도 2 이상, 많이 나온 순): " + ", ".join(f"{k} {v}" for k, v in c.most_common(15)))
    print("\n관련도 3 (핵심 후보):")
    for r in sorted((r for r in rows if r["abs_score"] == 3), key=lambda r: -(r["year"] or 0)):
        mark = "★" if r["favorite"] else " "
        print(f" {mark}#{r['id']} {r['year']} [{r['abs_role']}] {r['title'][:80]}\n      {r['abs_note']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prefilter", "run", "summary"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--top", type=int, default=400)
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    con = connect(a.project)
    if a.cmd == "prefilter":
        prefilter(con, a.project, a.top)
    elif a.cmd == "run":
        run(con, a.project, a.top, a.redo)
    else:
        summary(con)
