"""프로젝트를 정적 HTML 한 파일로. 아티팩트 게시·지도교수 공유용.
  python scripts/export_html.py --project SLUG   → projects/SLUG/export/report.html
원문 전문은 넣지 않는다 (저작권). 노트의 인용문과 쪽수, 원문 링크만.
"""
import argparse, collections, datetime, html, pathlib, re, sys, unicodedata
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import connect, project_dir, read_brief, SECTIONS
import base64
import diagram
import figures

e = html.escape


def md(text):
    """gaps/*.md 용 최소 변환: 헤딩, 목록, 표, 인용, 굵게."""
    out, lines, i = [], text.splitlines(), 0
    inline = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", e(s))
    while i < len(lines):
        ln = lines[i]
        if m := re.match(r"(#{1,4})\s+(.*)", ln):
            lv = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{lv}>{inline(m.group(2))}</h{lv}>")
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            i -= 1
            head = "".join(f"<th>{inline(c)}</th>" for c in rows[0])
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
            out.append(f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
        elif re.match(r"\s*[-*]\s+", ln):
            items = []
            while i < len(lines) and re.match(r"\s*[-*]\s+", lines[i]):
                item = re.sub(r"^\s*[-*]\s+", "", lines[i])
                items.append(f"<li>{inline(item)}</li>")
                i += 1
            i -= 1
            out.append("<ul>" + "".join(items) + "</ul>")
        elif ln.startswith(">"):
            out.append(f"<blockquote>{inline(ln.lstrip('> '))}</blockquote>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    return "\n".join(out)



STATUS_KO = {"candidate": "후보", "shortlist": "읽을 목록", "fulltext": "원문 있음", "analyzed": "분석됨", "rejected": "제외"}
# 목록에 넣지 않을 것: 학술지 공지·정정·서평 (논문이 아님)
NOT_PAPER = re.compile(r"^(issue information|correction|corrigendum|erratum|retraction|editorial board|book review)|\bbook review\b"
                       r"|^review of\b|, (ed|eds)\.|\(eds?\.\)", re.I)
U = lambda s: " ".join(html.unescape(s or "").split())  # noqa: E731  &amp; 를 풀고 제목 속 줄바꿈·겹친 공백을 한 칸으로
Q = lambda s: unicodedata.normalize("NFKC", s or "")  # noqa: E731  인용문의 합자(ﬁ·ﬂ)를 일반 글자로

CSS = """
:root{
  /* 앱 화면과 같은 구조: 위쪽 탭(연구 주제·핵심 논문·읽기·모아보기), 읽기는 왼쪽 목록 + 오른쪽 논문 */
  --bg:#f6f7f9; --surface:#ffffff; --fg:#1b2230; --muted:#5b6474; --line:#dde1e8; --side:#eef1f5;
  --accent:#d1453b; --accent-soft:rgba(209,69,59,.10); --link:#2f5d8a; --quote:#eef2f7; --ok:#2f7a4f; --warn:#a46412;
  --display:"Noto Serif KR",Georgia,serif; --body:"IBM Plex Sans KR",-apple-system,"Apple SD Gothic Neo",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#12161d; --surface:#1a2029; --fg:#e4e8ef; --muted:#9aa3b2; --line:#2c3440; --side:#161b23;
  --accent:#ef7a70; --accent-soft:rgba(239,122,112,.14); --link:#8db4dc; --quote:#212a36; --ok:#7cc79b; --warn:#e0a85a; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#12161d; --surface:#1a2029; --fg:#e4e8ef; --muted:#9aa3b2; --line:#2c3440; --side:#161b23;
  --accent:#ef7a70; --accent-soft:rgba(239,122,112,.14); --link:#8db4dc; --quote:#212a36; --ok:#7cc79b; --warn:#e0a85a; color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 var(--body)}
a{color:var(--link)} a:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
h1,h2,h3{font-family:var(--display);line-height:1.3;margin:0;text-wrap:balance}
h1{font-size:1.5rem} h2{font-size:1.25rem} h3{font-size:1.05rem}
.meta{color:var(--muted);font-size:.86rem}
.pg{font:.74rem var(--mono);color:var(--muted)}
.top{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--surface);border-bottom:1px solid var(--line);
  padding-block:12px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:10px}
.top .row{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px;justify-content:space-between}
.top .stats{font:.8rem var(--mono);color:var(--muted)}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;flex-wrap:wrap}
.seg button{border:0;background:transparent;color:var(--fg);font:inherit;font-size:.92rem;padding:6px 14px;cursor:pointer}
.seg button+button{border-left:1px solid var(--line)}
.seg button[aria-selected=true]{background:var(--accent-soft);color:var(--accent);font-weight:600}
.view{display:none;padding-block:20px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px));max-width:1280px;margin:0 auto}
.view.on{display:block}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:16px 18px;display:grid;gap:10px;min-width:0}
.stack{display:grid;gap:16px}
dl.brief{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;margin:0}
dl.brief dt{color:var(--muted)} dl.brief dd{margin:0;min-width:0}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.86rem;font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:.78rem}
.chip{display:inline-block;font-size:.76rem;padding:1px 9px;border:1px solid var(--line);border-radius:999px;color:var(--muted);white-space:nowrap}
.chip.on{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}
.score{font:600 .8rem var(--mono);display:inline-block;min-width:1.6em;text-align:center;border-radius:4px;background:var(--quote)}
.score.s3{background:var(--accent-soft);color:var(--accent)}
.warn{border-left:3px solid var(--warn);background:var(--quote);padding:8px 12px;border-radius:4px;font-size:.9rem}
/* 읽기: 왼쪽 목록 + 오른쪽 논문 */
.read{display:grid;grid-template-columns:300px 1fr;gap:20px;align-items:start}
.side{position:sticky;top:110px;max-height:calc(100vh - 130px);overflow:auto;background:var(--side);border-radius:8px;padding:12px}
.side input{width:100%;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--fg);font:inherit}
.side .grp{margin:14px 0 4px 6px;font-size:.8rem;color:var(--muted)}
.side button{display:block;width:100%;text-align:left;border:0;background:transparent;color:var(--fg);font:inherit;font-size:.86rem;
  line-height:1.4;padding:6px 8px;border-radius:6px;cursor:pointer}
.side button:hover{background:var(--surface)}
.side button[aria-current=true]{background:var(--accent-soft);color:var(--accent)}
.paper{display:none;gap:14px} .paper.on{display:grid}
.paper header{display:grid;gap:4px}
details.box{border:1px solid var(--line);border-radius:8px;background:var(--surface)}
details.box>summary{cursor:pointer;padding:10px 14px;font-weight:600}
details.box>.in{padding:0 14px 14px;display:grid;gap:12px;min-width:0}
.one{font-weight:600}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.tabs button{border:0;background:transparent;color:var(--muted);font:inherit;font-size:.9rem;padding:6px 12px;cursor:pointer;border-bottom:2px solid transparent}
.tabs button[aria-selected=true]{color:var(--accent);border-bottom-color:var(--accent)}
.tp{display:none;min-width:0} .tp.on{display:block}
figure{margin:0;display:grid;gap:4px;min-width:0} figcaption{font-size:.8rem;color:var(--muted)}
figure.orig img{width:100%;background:#fff;border:1px solid var(--line);border-radius:4px}
.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}
pre.mermaid{background:transparent;padding:8px 0;margin:0;min-width:480px}
ol.flow{list-style:none;margin:0;padding:0}
ol.flow li{display:grid;grid-template-columns:6.5em 1fr;gap:12px;padding:8px 0 8px 10px;border-left:4px solid var(--c);font-size:.9rem}
ol.flow li+li{border-top:1px dashed var(--line)}
ol.flow .ph{font-size:.74rem;color:var(--c);line-height:1.3} ol.flow .ph b{color:var(--fg);font-size:.82rem}
.sec{display:grid;grid-template-columns:9em 1fr;gap:12px;border-top:1px dashed var(--line);padding-top:8px}
.sec>div{min-width:0} .sec .lab{font-size:.82rem;color:var(--link);font-weight:600}
.interp{color:var(--muted)}
blockquote{margin:6px 0 0;padding:8px 12px;background:var(--quote);border-radius:4px;font-size:.92rem}
ul.memos{list-style:none;margin:0;padding:0;display:grid;gap:8px;font-size:.88rem}
ul.memos li{border-left:3px solid var(--c);padding-left:10px} ul.memos b{color:var(--c)}
ul.toc{margin:0;padding-left:1em;font-size:.88rem}
.md h3,.md h4,.md h5{margin:.9em 0 .3em} .md p{margin:.4em 0}
@media (max-width:820px){.read{grid-template-columns:1fr}.side{position:static;max-height:340px}
  .sec,dl.brief,ol.flow li{grid-template-columns:1fr;gap:2px}}
"""


def build(slug):
    con = connect(slug)
    b = read_brief(slug)
    name = (project_dir(slug) / "brief.md").read_text().splitlines()[0].lstrip("# ").strip()
    stat = dict(con.execute("SELECT status, COUNT(*) FROM papers GROUP BY status").fetchall())
    stats = " · ".join(f"{STATUS_KO.get(k, k)} {v}" for k, v in stat.items() if k != "rejected")
    brief = "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in b.items()
                    if isinstance(v, str) and v and not v.startswith("("))
    is_paper = lambda r: not NOT_PAPER.search(U(r["title"]))  # noqa: E731

    # ── 핵심 논문 ──
    core = [r for r in con.execute("SELECT * FROM papers WHERE favorite=1 "
                                   "ORDER BY anchor IS NULL, key_role IS NULL, COALESCE(abs_score, -1) DESC, year DESC") if is_paper(r)]
    core_rows = "".join(
        f"<tr><td>{r['year'] or ''}</td><td>{e(U(r['title']))}</td><td>{e((U(r['authors'])).split(';')[0])}</td>"
        f"<td>{e(U(r['venue']))}</td><td>{'<span class=\'chip on\'>기준</span> ' if r['anchor'] else ''}{e(r['key_role'] or '')}</td><td>{STATUS_KO.get(r['status'], r['status'])}</td></tr>" for r in core)
    scr = [r for r in con.execute("SELECT * FROM papers WHERE abs_at IS NOT NULL AND abs_score >= 2 "
                                  "ORDER BY abs_score DESC, year DESC") if is_paper(r)]
    scr_rows = "".join(
        f"<tr data-s='{r['abs_score']}'><td><span class='score s{r['abs_score']}'>{r['abs_score']}</span></td>"
        f"<td>{e(r['abs_role'] or '')}</td><td>{e(U(r['title']))}<div class='meta'>{r['year'] or ''} · {e(U(r['venue']))}</div></td>"
        f"<td>{e(r['abs_theory'] or '')}</td><td>{e(r['abs_method'] or '')}</td><td>{e(r['abs_note'] or '')}</td></tr>" for r in scr)
    n_abs = con.execute("SELECT COUNT(*) FROM papers WHERE abs_at IS NOT NULL").fetchone()[0]
    core_view = (f'<div class="stack"><div class="card"><h2>핵심 논문 {len(core)}편</h2>'
                 '<p class="meta">이 연구가 기대는 논문. 인용 관계를 따라 연관 논문을 넓히는 기준입니다.</p>'
                 '<div class="scroll"><table><thead><tr><th>연도</th><th>제목</th><th>1저자</th><th>저널</th><th>내 논문에서의 역할</th><th>상태</th></tr></thead>'
                 f'<tbody>{core_rows}</tbody></table></div></div>')
    if scr:
        core_view += (f'<div class="card"><h2>초록으로 추린 후보</h2>'
                      f'<p class="meta">모은 논문 중 {n_abs}편의 초록을 Claude 가 읽고 관련도(3 핵심 후보 · 2 꼭 읽을 것)·역할·이론·방법을 제안한 결과입니다. 초록 기준 판단이라 원문 확인이 필요합니다.</p>'
                      '<div class="seg" role="tablist" aria-label="관련도"><button aria-selected="true" data-min="3">관련도 3</button><button aria-selected="false" data-min="2">2 이상</button></div>'
                      '<div class="scroll"><table id="scr"><thead><tr><th>관련도</th><th>제안 역할</th><th>논문</th><th>이론</th><th>방법</th><th>이유</th></tr></thead>'
                      f'<tbody>{scr_rows}</tbody></table></div></div>')
    core_view += "</div>"

    # ── 읽기: 왼쪽 목록 + 오른쪽 논문 ──
    rows = [r for r in con.execute("SELECT * FROM papers WHERE status IN ('shortlist','fulltext','analyzed') OR favorite=1 "
                                   "ORDER BY anchor IS NULL, favorite DESC, year DESC") if is_paper(r)]
    groups = {"analyzed": "분석됨", "fulltext": "원문 있음"}
    side, panes = [], []
    for g in ["analyzed", "fulltext", None]:
        items = [r for r in rows if (r["status"] if r["status"] in groups else None) == g]
        if not items:
            continue
        side.append(f'<div class="grp">{groups.get(g, "원문 없음")} {len(items)}</div>')
        for r in items:
            first = (U(r["authors"]).split(";")[0].split() or [""])[-1]
            t = U(r["title"])
            side.append(f'<button data-p="{r["id"]}" data-q="{e((t + " " + U(r["authors"])).lower())}">'
                        f'{"[기준] " if r["anchor"] else "★ " if r["favorite"] else ""}{e(first)} {r["year"] or ""} — {e(t[:60] + ("…" if len(t) > 60 else ""))}</button>')
            panes.append(paper_pane(con, slug, r))

    # ── 모아보기 ──
    from db import checkup, KEY_ROLES
    ck = checkup(con)
    warns = "".join(f'<div class="warn">{e(w)}</div>' for w in ck["warn"])
    roles = "".join(f"<tr><td>{e(k)}</td><td>{len(rs)}</td><td>{e(' / '.join(U(r['title'])[:50] for r in rs)) or '—'}</td><td class='meta'>{e(KEY_ROLES[k])}</td></tr>"
                    for k, rs in ck["roles"].items())
    titles = {"design": "연구 설계 추천", "candidates": "갭·가설 후보", "matrix": "증거 매트릭스"}
    files = sorted((project_dir(slug) / "gaps").glob("*.md"), key=lambda f: (list(titles).index(f.stem) if f.stem in titles else 9, f.stem))
    ideas = "".join(f'<details class="box"{" open" if f.stem == "design" else ""}><summary>{e(titles.get(f.stem, f.stem))}</summary>'
                    f'<div class="in md">{md(f.read_text())}</div></details>' for f in files)
    memos = con.execute("SELECT m.*, p.title FROM memos m JOIN papers p ON p.id=m.paper_id ORDER BY m.paper_id, m.page").fetchall()
    collect_view = (f'<div class="stack"><div class="card"><h2>문헌 점검</h2>'
                    f'<p class="meta">읽을 목록 {ck["n"]}편 · 최근 5년 {ck["recent"]}편 · 국내 {ck["ko"]}편 · 연도 '
                    + " · ".join(f"{k} {v}" for k, v in ck["years"].items()) + f"</p>{warns}"
                    '<div class="scroll"><table><thead><tr><th>역할</th><th>편수</th><th>논문</th><th>뜻</th></tr></thead>'
                    f"<tbody>{roles}</tbody></table></div></div>"
                    + (f'<div class="card"><h2>연구 아이디어 · 연구 설계</h2>{ideas}</div>' if ideas else "")
                    + (f'<div class="card"><h2>내 메모 {len(memos)}개</h2>{memo_list(memos, True)}</div>' if memos else "")
                    + "</div>")

    anc = con.execute("SELECT * FROM papers WHERE anchor=1").fetchone()
    anchor_line = (f'<div class="meta"><b>기준 논문</b> · <a href="#" data-go="{anc["id"]}">{e(U(anc["title"]))}</a> · '
                   f'{e((U(anc["authors"]).split(";")[0]))} {anc["year"] or ""} · <em>{e(U(anc["venue"]))}</em></div>') if anc else ""
    return f"""<title>{e(slug)} 문헌 보고서</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+KR:wght@400;600&family=Noto+Serif+KR:wght@600&display=swap">
<style>{CSS}</style>
<div class="top">
  <div class="row"><h1>{e(name)}</h1><span class="stats">{e(slug)} · {datetime.date.today().isoformat()} · {e(stats)}</span></div>
  {anchor_line}
  <div class="seg" role="tablist" aria-label="화면" id="nav">
    <button aria-selected="false" data-v="brief">연구 주제</button><button aria-selected="false" data-v="core">핵심 논문</button>
    <button aria-selected="true" data-v="read">읽기</button><button aria-selected="false" data-v="collect">모아보기</button>
  </div>
</div>
<main>
<section class="view" id="v-brief"><div class="card"><h2>연구 주제</h2><dl class="brief">{brief}</dl></div></section>
<section class="view" id="v-core">{core_view}</section>
<section class="view on" id="v-read"><div class="read">
  <nav class="side" aria-label="논문 목록"><input id="q" type="search" placeholder="제목·저자" aria-label="논문 찾기">{"".join(side)}
    <p class="meta" style="margin:12px 6px 0">★ 핵심 논문</p></nav>
  <div>{"".join(panes) or '<p class="meta">아직 읽을 논문이 없습니다.</p>'}</div>
</div></section>
<section class="view" id="v-collect">{collect_view}</section>
</main>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script>
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
let mmOk=false; try{{mermaid.initialize({{startOnLoad:false,securityLevel:'loose'}});mmOk=true}}catch(err){{console.error(err)}}
function drawModels(root){{ if(!mmOk) return; const els=$$('.tp.on pre.mermaid:not([data-processed])',root);
  if(els.length) try{{mermaid.run({{nodes:els}})}}catch(err){{console.error(err)}} }}
function view(v){{ $$('#nav button').forEach(b=>b.setAttribute('aria-selected',b.dataset.v===v)); $$('.view').forEach(s=>s.classList.toggle('on',s.id==='v-'+v)); }}
$$('#nav button').forEach(b=>b.onclick=()=>view(b.dataset.v));
function pick(id){{ $$('.side button').forEach(b=>b.setAttribute('aria-current',b.dataset.p===id));
  $$('.paper').forEach(p=>p.classList.toggle('on',p.id==='p'+id)); const p=$('#p'+id); if(p){{drawModels(p);window.scrollTo({{top:0}})}} }}
$$('.side button').forEach(b=>b.onclick=()=>pick(b.dataset.p));
$('#q').oninput=ev=>{{const v=ev.target.value.toLowerCase(); $$('.side button').forEach(b=>b.hidden=v&&!b.dataset.q.includes(v))}};
$$('.tabs').forEach(t=>$$('button',t).forEach(b=>b.onclick=()=>{{ $$('button',t).forEach(x=>x.setAttribute('aria-selected',x===b));
  const box=t.parentElement; $$(':scope>.tp',box).forEach(p=>p.classList.toggle('on',p.dataset.t===b.dataset.t)); drawModels(box); }}));
const segs=$$('#v-core .seg button'); segs.forEach(b=>b.onclick=()=>{{ segs.forEach(x=>x.setAttribute('aria-selected',x===b));
  $$('#scr tbody tr').forEach(r=>r.hidden=+r.dataset.s<+b.dataset.min) }}); if(segs[0]) segs[0].click();
$$('[data-go]').forEach(a=>a.onclick=ev=>{{ev.preventDefault(); view('read'); pick(a.dataset.go)}});
const first=$('.side button'); if(first) pick(first.dataset.p);
</script>
"""


def memo_list(rows, show_paper=False):
    from db import MEMO_COLORS
    return '<ul class="memos">' + "".join(
        f'<li style="--c:{MEMO_COLORS.get(m["color"], MEMO_COLORS["중요"])[1]}"><b>{e(m["color"])}</b> · p.{m["page"]}'
        + (f' · {e(U(m["title"])[:60])}' if show_paper else "")
        + f'<br><span class="meta">“{e((m["excerpt"] or "(그림 영역)")[:240])}”</span><br>{e(m["memo"] or "")}</li>'
        for m in rows) + "</ul>"


def paper_pane(con, slug, p):
    """오른쪽 논문 화면: 제목 → 역할·검토 → 한눈에 보기(탭) → 분석 항목 → 가설·변수 → 내 메모."""
    pid = p["id"]
    link = f"https://doi.org/{p['doi']}" if p["doi"] else p["url"]
    head = (f'<header><div class="pg">#{pid} · {p["year"] or ""} · 인용 {p["cited_by"] or 0}</div><h2>{e(U(p["title"]))}</h2>'
            f'<div class="meta">{e(U(p["authors"]))} · <em>{e(U(p["venue"]))}</em>'
            + (f' · <a href="{e(link)}" target="_blank" rel="noopener">원문 페이지</a>' if link else "") + "</div></header>")
    chips = '<span class="chip on">기준 논문</span> ' if p["anchor"] else ""
    chips += f'<span class="chip on">{e(p["key_role"])}</span>' if p["key_role"] else ""
    chips += f' <span class="chip">{e(p["review"])}</span>' if p["review"] else ""
    chips += f' <span class="meta">{e(p["key_role_note"] or "")}</span>' if p["key_role_note"] else ""
    by = collections.defaultdict(list)
    for n in con.execute("SELECT * FROM notes WHERE paper_id=? ORDER BY id", (pid,)):
        by[n["section"]].append(n)
    body = [head, f"<div>{chips}</div>" if chips else ""]
    if not by:  # 아직 분석 전: 초록 분석 판단이 있으면 보여준다
        if p["abs_note"]:
            body.append(f'<div class="card"><div><span class="score s{p["abs_score"]}">{p["abs_score"]}</span> '
                        f'<span class="chip">{e(p["abs_role"] or "")}</span></div><p class="meta" style="margin:0">초록 기준 · {e(p["abs_note"])}</p>'
                        f'<p class="meta" style="margin:0">이론 {e(p["abs_theory"] or "—")} · 방법 {e(p["abs_method"] or "—")} · 맥락 {e(p["abs_context"] or "—")}</p></div>')
        body.append(f'<p class="meta">아직 심층 분석 전입니다.{" 원문을 받으면 분석할 수 있습니다." if p["status"] not in ("fulltext",) else ""}</p>')
        return f'<article class="paper" id="p{pid}">{"".join(body)}</article>'

    # 한눈에 보기: 앱과 같은 탭
    figs = con.execute("SELECT * FROM figures WHERE paper_id=? ORDER BY page, id", (pid,)).fetchall()
    oa = bool(p["oa_url"])  # 공개 접근 논문만 원문 그림을 넣는다

    def fig_html(f):
        img = (f'<img src="data:image/png;base64,{base64.b64encode(figures.crop_png(con, slug, f["id"], 1.6)).decode()}" alt="{e(f["label"])}">'
               if oa else "")
        return (f'<figure class="orig">{img}<figcaption><b>{e(f["label"])}</b> · p.{f["page"]} · {e(f["note"] or (f["caption"] or "")[:160])}'
                + ("" if oa else " <span class='pg'>(유료 논문이라 그림은 넣지 않았습니다)</span>") + "</figcaption></figure>")
    tabs, panes = [], []
    model = "".join(fig_html(f) for f in figs if f["role"] == "연구 모형")
    mm = diagram.to_mermaid(con, pid)
    if mm:
        model += ('<figure><figcaption>가설 판정 반영 · 초록 지지 · 주황 부분지지 · 회색 기각 · 점선 조절·무효과</figcaption>'
                  f'<div class="scroll"><pre class="mermaid">{e(mm)}</pre></div></figure>')
    if model:
        tabs.append("연구 모형"); panes.append(f'<div class="gallery">{model}</div>')
    flows = {r["step"]: r for r in con.execute("SELECT * FROM flow WHERE paper_id=?", (pid,))}
    if flows:
        import db as _db
        li = "".join(f'<li style="--c:{diagram.PHASE[s][1]}"><span class="ph">{diagram.PHASE[s][0]}<br><b>{s}</b></span>'
                     f'<span>{e(flows[s]["claim"])} <span class="pg">p.{flows[s]["page"] or ""}</span>'
                     + (f' <span class="pg">{e(flows[s]["fig"])}</span>' if flows[s]["fig"] else "") + "</span></li>"
                     for s in _db.FLOW if s in flows)
        tabs.append("논증 흐름"); panes.append(f'<ol class="flow">{li}</ol>')
    key = [f for f in figs if f["role"] in ("주요 결과", "과정")]
    if key:
        tabs.append(f"원문 그림·표 {len(key)}"); panes.append(f'<div class="gallery">{"".join(fig_html(f) for f in key)}</div>')
    ol = diagram.outline(con, pid)
    if ol:
        tabs.append("절 목차")
        panes.append('<ul class="toc">' + "".join(f'<li><span class="pg">p.{o["page_start"]}</span> <b>{e(o["heading"])}</b> '
                                                  f'<span class="meta">{e(o["summary"] or "")}</span></li>' for o in ol) + "</ul>")
    one = by.get("한 줄 요약")
    glance = (f'<p class="one" style="margin:0">{e(one[0]["content"])}</p>' if one else "")
    if tabs:
        glance += ('<div class="tabs" role="tablist">' + "".join(f'<button aria-selected="{str(i == 0).lower()}" data-t="{i}">{t}</button>'
                                                                for i, t in enumerate(tabs)) + "</div>"
                   + "".join(f'<div class="tp{" on" if i == 0 else ""}" data-t="{i}">{x}</div>' for i, x in enumerate(panes)))
    body.append(f'<details class="box" open><summary>한눈에 보기</summary><div class="in">{glance}</div></details>')

    # 분석 항목: 채운 것만. 빠른 분석에서 비운 항목은 개수만 알린다
    secs = []
    for s in SECTIONS:
        if s == "한 줄 요약" or not by.get(s):
            continue
        txt = "".join(f'<p class="{"interp" if s.startswith("[") else ""}" style="margin:.2em 0">{e(n["content"])}</p>'
                      + (f'<blockquote>{e(Q(n["quote"]))} <span class="pg">p.{n["page"]}</span></blockquote>' if n["quote"] else "")
                      for n in by[s])
        secs.append(f'<div class="sec"><span class="lab">{e(s)}</span><div>{txt}</div></div>')
    body.append(f'<details class="box" open><summary>분석</summary><div class="in">{"".join(secs)}</div></details>')

    hy = con.execute("SELECT * FROM hypotheses WHERE paper_id=? ORDER BY id", (pid,)).fetchall()
    va = con.execute("SELECT * FROM variables WHERE paper_id=? ORDER BY id", (pid,)).fetchall()
    if hy or va:
        t = ""
        if hy:
            t += ('<div class="scroll"><table><thead><tr><th></th><th>가설</th><th>방향</th><th>결과</th><th>통계</th><th>쪽</th></tr></thead><tbody>'
                  + "".join(f"<tr><td>{e(h['code'])}</td><td>{e(h['statement'])}</td><td>{e(h['direction'] or '')}</td>"
                            f"<td>{e(h['result'] or '')}</td><td>{e(h['stats'] or '')}</td><td>{h['page'] or ''}</td></tr>" for h in hy)
                  + "</tbody></table></div>")
        if va:
            t += ('<div class="scroll"><table><thead><tr><th>역할</th><th>변수</th><th>측정</th><th>척도 출처</th><th>문항</th><th>α</th></tr></thead><tbody>'
                  + "".join(f"<tr><td>{e(v['role'])}</td><td>{e(v['name'])}</td><td>{e(v['measure'] or '')}</td>"
                            f"<td>{e(v['source'] or '')}</td><td>{v['items'] or ''}</td><td>{v['alpha'] or ''}</td></tr>" for v in va)
                  + "</tbody></table></div>")
        body.append(f'<details class="box"><summary>가설 {len(hy)} · 변수 {len(va)}</summary><div class="in">{t}</div></details>')
    mm_rows = con.execute("SELECT * FROM memos WHERE paper_id=? ORDER BY page, id", (pid,)).fetchall()
    if mm_rows:
        body.append(f'<details class="box" open><summary>내 메모 {len(mm_rows)}</summary><div class="in">{memo_list(mm_rows)}</div></details>')
    return f'<article class="paper" id="p{pid}">{"".join(body)}</article>'


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    out = project_dir(a.project) / "export" / "report.html"
    out.write_text(build(a.project))
    print(out)
