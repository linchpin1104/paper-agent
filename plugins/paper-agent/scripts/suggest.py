"""Claude 추천 핵심 논문 — 관찰을 이론으로 번역해 원전·선행연구를 추천받고, OpenAlex 로 실재를 확인한다.
  python scripts/suggest.py ask    --project SLUG                 # 연구 주제·대화 기록을 Claude(사용자 claude CLI)에 넘겨 추천 → 확인
  python scripts/suggest.py verify --project SLUG --file x.json   # 에이전트가 만든 추천 목록을 확인만 (형식은 아래 papers 와 같음)
결과: projects/SLUG/suggest.json — 추천마다 OpenAlex 에서 찾은 기록과 확인 상태(확인됨 / 확인 필요 / 못 찾음).
분야 제한 없음. 키워드 통계로는 못 잡는 '관찰 → 이론 원전' 연결을 Claude 가 하고, 존재 여부는 DB 가 확인한다.
"""
import argparse, difflib, json, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import project_dir
import seeds
import verify

GROUPS = ["이론 원전", "직접 선행연구", "인접 분야 연구", "방법·측정"]
SYS = """당신은 SSCI/SCI 논문을 준비하는 연구자의 지도 선배입니다. 연구 주제 설정과 대화를 읽고, 이 연구가 기대야 할 핵심 논문을 추천합니다.
- 묶음: 이론 원전(이 연구가 쓸 이론의 원 논문·책), 직접 선행연구(같은 현상·대상을 다룬 실증 연구, 최근 10년 위주, 한국 연구 포함),
  인접 분야 연구(다른 분야지만 개념·방법을 빌려올 연구), 방법·측정(척도 개발·타당화, 분석 방법의 원전).
- 사용자가 말한 관찰은 학술 개념·이론 이름으로 번역해 그 원전을 찾습니다.
  예: '엄마들은 자기가 겪은 문제에서 창업한다' → 사용자 기업가정신(Shah & Tripsas 2007).
- 분야를 가리지 않습니다. 방법이 공학·컴퓨터과학·심리학에서 왔으면 그 분야의 원전도 넣습니다.
- 실제로 존재한다고 확신하는 논문만 넣습니다. 제목은 원문(영어 논문은 영어) 그대로, 1저자 성, 출판 연도. 확실하지 않으면 빼세요.
- 묶음당 3~6편, 합계 15~22편. why 는 이 연구에 왜 필요한지 한국어 1문장."""
SCHEMA = {"type": "object", "required": ["papers"], "properties": {"papers": {"type": "array", "items": {
    "type": "object", "required": ["group", "title", "first_author", "year", "why"], "properties": {
        "group": {"type": "string", "enum": GROUPS}, "title": {"type": "string"}, "first_author": {"type": "string"},
        "year": {"type": "integer"}, "why": {"type": "string"}}}}}}


def ask(slug):
    d = project_dir(slug)
    brief = (d / "brief.md").read_text()
    chat = d / "brief_chat.json"
    talk = ""
    if chat.exists():
        hist = json.loads(chat.read_text())
        talk = "\n".join(f"{'사용자' if m['role'] == 'user' else '선배'}: {m['content']}" for m in hist[-30:])
    prompt = f"연구 주제 설정:\n{brief}\n\n지금까지의 대화:\n{talk or '(없음)'}"
    r = subprocess.run(["claude", "-p", prompt, "--system-prompt", SYS, "--tools", "", "--no-session-persistence",
                        "--model", "claude-opus-5-5", "--output-format", "json", "--json-schema", json.dumps(SCHEMA, ensure_ascii=False)],
                       capture_output=True, text=True, timeout=400)
    return json.loads(r.stdout)["structured_output"]["papers"]


def check(p):
    """추천 1편을 OpenAlex 에서 찾아 확인 상태를 붙인다. 제목 일치 + 연도(±1) + 1저자 성으로 판정."""
    def pick(cands):
        best, best_s = None, 0.0
        for c in cands:
            s = difflib.SequenceMatcher(None, seeds.norm(p["title"]), seeds.norm(c["title"] or "")).ratio()
            if s > best_s:
                best, best_s = c, s
        return best, best_s
    best, best_s = pick(seeds.find(p["title"]))
    if p.get("year") and (not best or not best["year"] or abs(best["year"] - p["year"]) > 1):
        b2, s2 = pick(seeds.find(p["title"], p["year"]))  # 재판본·다른 판이 먼저 잡혔으면 원 출판 연도로 다시
        if b2 and s2 >= max(0.6, best_s - 0.1):
            best, best_s = b2, s2
    if not best or best_s < 0.6:
        return dict(p, status="못 찾음", match=None)
    year_ok = not best["year"] or not p.get("year") or abs(best["year"] - p["year"]) <= 1
    author_ok = verify.plain(p["first_author"]).split()[-1:] and verify.plain(p["first_author"]).split()[-1] in verify.plain(best["authors"] or "")
    status = "확인됨" if best_s >= 0.85 and year_ok and author_ok else "확인 필요"
    return dict(p, status=status, match=dict(best, score=round(best_s, 2)))


def run_verify(slug, papers):
    out = []
    for p in papers:
        r = check(p)
        out.append(r)
        m = r["match"]
        print(f"[{r['status']}] {r['group']} | {r['first_author']} {r['year']} {r['title'][:70]}"
              + (f"\n      → {m['year']} {m['title'][:70]} · {m['venue'] or ''} (일치 {m['score']})" if m else ""))
    (project_dir(slug) / "suggest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    n = {s: sum(1 for r in out if r["status"] == s) for s in ("확인됨", "확인 필요", "못 찾음")}
    print("합계", n)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ask", "verify"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--file")
    a = ap.parse_args()
    papers = ask(a.project) if a.cmd == "ask" else json.loads(pathlib.Path(a.file).read_text())
    run_verify(a.project, papers)
