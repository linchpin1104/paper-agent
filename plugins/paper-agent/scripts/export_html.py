"""프로젝트를 정적 HTML 한 파일로. 아티팩트 게시·지도교수 공유용.
  python scripts/export_html.py --project SLUG   → projects/SLUG/export/report.html
원문 전문은 넣지 않는다 (저작권). 노트의 인용문과 쪽수, 원문 링크만.
"""
import argparse, collections, datetime, html, pathlib, re, sys
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


CSS = """
:root{
  /* 연구 노트: 좌측 목차 없는 단일 칼럼, 논문 카드가 위에서 아래로 쌓인다 */
  --bg:#f6f7f9; --surface:#ffffff; --fg:#1b2230; --muted:#5b6474; --line:#dde1e8;
  --accent:#2f5d8a; --quote:#eef2f7; --ok:#2f7a4f; --warn:#a46412;
  --display:"Noto Serif KR",Georgia,serif; --body:"IBM Plex Sans KR",-apple-system,"Apple SD Gothic Neo",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#12161d; --surface:#1a2029; --fg:#e4e8ef; --muted:#9aa3b2; --line:#2c3440;
  --accent:#8db4dc; --quote:#212a36; --ok:#7cc79b; --warn:#e0a85a; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#12161d; --surface:#1a2029; --fg:#e4e8ef; --muted:#9aa3b2; --line:#2c3440;
  --accent:#8db4dc; --quote:#212a36; --ok:#7cc79b; --warn:#e0a85a; color-scheme:dark}
body{background:var(--bg);color:var(--fg);font:15px/1.7 var(--body)}
.wrap{max-width:880px;margin:0 auto;padding-inline:16px;padding-block:32px 64px;display:grid;gap:40px}
h1,h2,h3{font-family:var(--display);text-wrap:balance;line-height:1.3;margin:0}
h1{font-size:1.9rem} h2{font-size:1.35rem;padding-bottom:6px;border-bottom:1px solid var(--line)} h3{font-size:1.08rem}
h4,h5,h6{margin:.8em 0 .2em}
.eyebrow{font:500 .72rem var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.meta{color:var(--muted);font-size:.88rem}
.stats{display:flex;flex-wrap:wrap;gap:8px 20px;font:.85rem var(--mono);color:var(--muted);font-variant-numeric:tabular-nums}
.stats b{color:var(--fg);font-weight:600}
section{display:grid;gap:14px;min-width:0}
dl.brief{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:0}
dl.brief dt{color:var(--muted)} dl.brief dd{margin:0;min-width:0}
.paper{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:18px 20px;display:grid;gap:10px;min-width:0}
.paper .sec{display:grid;grid-template-columns:8.5em 1fr;gap:12px;border-top:1px dashed var(--line);padding-top:8px}
.paper .sec>div{min-width:0}
.paper .lab{font-size:.82rem;color:var(--accent);font-weight:600}
.paper .lab.empty{color:var(--warn)}
blockquote{margin:6px 0 0;padding:8px 12px;background:var(--quote);border-radius:4px;font-size:.92rem}
blockquote .pg{font:.78rem var(--mono);color:var(--muted);margin-left:6px}
.interp{color:var(--muted)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.86rem;font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:.78rem}
a{color:var(--accent)} a:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
input#q{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:4px;background:var(--surface);color:var(--fg);font:inherit}
.tag{font:.72rem var(--mono);padding:1px 6px;border:1px solid var(--line);border-radius:3px;color:var(--muted)}
.glance{border:1px solid var(--line);border-radius:6px;padding:10px 14px;display:grid;gap:12px;background:var(--bg)}
.glance>summary{cursor:pointer;font-weight:600;color:var(--accent)}
.glance .one{font-weight:600;margin:6px 0 0}
.glance h4{margin:6px 0 0;font-size:.82rem;letter-spacing:.06em;color:var(--muted)}
.modelrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;align-items:start}
figure{margin:0;display:grid;gap:4px;min-width:0} figcaption{font-size:.8rem;color:var(--muted)}
figure.orig img{width:100%;background:#fff;border:1px solid var(--line);border-radius:4px}
pre.mermaid{background:transparent;padding:8px 0;margin:0;min-width:480px}
ol.flow{list-style:none;margin:0;padding:0;display:grid;gap:0}
ol.flow li{display:grid;grid-template-columns:6.5em 1fr;gap:12px;padding:8px 0 8px 10px;border-left:4px solid var(--c);font-size:.9rem}
ol.flow li+li{border-top:1px dashed var(--line)}
ol.flow .ph{font-size:.74rem;color:var(--c);line-height:1.3} ol.flow .ph b{color:var(--fg);font-size:.82rem}
.pg{font:.74rem var(--mono);color:var(--muted)}
.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}
ul.memos{list-style:none;margin:0;padding:0;display:grid;gap:8px;font-size:.88rem}
ul.memos li{border-left:3px solid var(--c);padding-left:10px} ul.memos b{color:var(--c)}
ul.toc{margin:6px 0 0;padding-left:1em;font-size:.86rem}
@media (max-width:560px){.paper .sec{grid-template-columns:1fr;gap:2px} dl.brief{grid-template-columns:1fr}
  ol.flow li{grid-template-columns:1fr;gap:2px}}
"""


def build(slug):
    con = connect(slug)
    b = read_brief(slug)
    name = (project_dir(slug) / "brief.md").read_text().splitlines()[0].lstrip("# ").strip()
    stat = dict(con.execute("SELECT status, COUNT(*) FROM papers GROUP BY status").fetchall())
    chans = con.execute("SELECT source, COUNT(*) FROM sources GROUP BY source").fetchall()
    stats = " ".join(f"<span>{k} <b>{v}</b></span>" for k, v in list(stat.items()) + [(f"ch:{s}", n) for s, n in chans])
    brief = "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in b.items()
                    if isinstance(v, str) and v and not v.startswith("("))

    gaps = "".join(f"<h3>{e(f.stem)}</h3>{md(f.read_text())}" for f in sorted((project_dir(slug) / "gaps").glob("*.md")))
    gaps = gaps or '<p class="meta">아직 갭 분석이 없습니다.</p>'

    cards = []
    for p in con.execute("SELECT * FROM papers WHERE id IN (SELECT paper_id FROM notes) ORDER BY year DESC"):
        by = collections.defaultdict(list)
        for n in con.execute("SELECT * FROM notes WHERE paper_id=? ORDER BY id", (p["id"],)):
            by[n["section"]].append(n)
        link = f"https://doi.org/{p['doi']}" if p["doi"] else p["url"]
        secs = []
        for s in SECTIONS:
            if not by.get(s):
                secs.append(f'<div class="sec"><span class="lab empty">{e(s)}</span><div class="meta">미작성</div></div>')
                continue
            body = "".join(
                f'<p class="{"interp" if s.startswith("[해석]") else ""}">{e(n["content"])}</p>'
                + (f'<blockquote>{e(n["quote"])}<span class="pg">p.{n["page"]}</span></blockquote>' if n["quote"] else "")
                for n in by[s])
            secs.append(f'<div class="sec"><span class="lab">{e(s)}</span><div>{body}</div></div>')
        hy = con.execute("SELECT * FROM hypotheses WHERE paper_id=? ORDER BY id", (p["id"],)).fetchall()
        va = con.execute("SELECT * FROM variables WHERE paper_id=? ORDER BY id", (p["id"],)).fetchall()
        extra = ""
        if hy:
            extra += ('<div class="scroll"><table><thead><tr><th></th><th>가설</th><th>방향</th><th>결과</th><th>통계</th><th>p</th></tr></thead><tbody>'
                      + "".join(f"<tr><td>{e(h['code'])}</td><td>{e(h['statement'])}</td><td>{e(h['direction'] or '')}</td>"
                                f"<td>{e(h['result'] or '')}</td><td>{e(h['stats'] or '')}</td><td>{h['page'] or ''}</td></tr>" for h in hy)
                      + "</tbody></table></div>")
        if va:
            extra += ('<div class="scroll"><table><thead><tr><th>역할</th><th>변수</th><th>측정</th><th>척도 출처</th><th>문항</th><th>α</th></tr></thead><tbody>'
                      + "".join(f"<tr><td>{e(v['role'])}</td><td>{e(v['name'])}</td><td>{e(v['measure'] or '')}</td>"
                                f"<td>{e(v['source'] or '')}</td><td>{v['items'] or ''}</td><td>{v['alpha'] or ''}</td></tr>" for v in va)
                      + "</tbody></table></div>")
        glance = ""
        one = by.get("한 줄 요약")
        if one:
            glance += f'<p class="one">{e(one[0]["content"])}</p>'
        figs = con.execute("SELECT * FROM figures WHERE paper_id=? ORDER BY page, id", (p["id"],)).fetchall()
        oa = bool(p["oa_url"])  # 공개 접근 논문만 원문 그림을 보고서에 넣는다
        def fig_html(f):
            img = (f'<img src="data:image/png;base64,{base64.b64encode(figures.crop_png(con, slug, f["id"], 1.6)).decode()}" alt="{e(f["label"])}">'
                   if oa else '<div class="meta">원문 그림은 로컬 페이지에서 확인 (비공개 논문)</div>')
            return (f'<figure class="orig" id="fig-{p["id"]}-{e(f["label"]).replace(" ", "")}">{img}'
                    f'<figcaption><b>{e(f["label"])}</b> · p.{f["page"]} · {e(f["note"] or f["caption"][:160])}</figcaption></figure>')
        model = "".join(fig_html(f) for f in figs if f["role"] == "연구 모형")
        mm = diagram.to_mermaid(con, p["id"])
        if mm:
            model += ('<figure class="model"><figcaption>가설 판정 반영 · 초록 지지 · 주황 부분지지 · 회색 기각 · 점선 조절·무효과</figcaption>'
                      f'<div class="scroll"><pre class="mermaid">{e(mm)}</pre></div></figure>')
        if model:
            glance += f'<h4>연구 모형</h4><div class="modelrow">{model}</div>'
        flows = {r["step"]: r for r in con.execute("SELECT * FROM flow WHERE paper_id=?", (p["id"],))}
        if flows:
            rows = ""
            for step in __import__("db").FLOW:
                r = flows.get(step)
                if not r:
                    continue
                phase, color = diagram.PHASE[step]
                link = (f' <a href="#fig-{p["id"]}-{e(r["fig"]).replace(" ", "")}">{e(r["fig"])}</a>' if r["fig"] else "")
                rows += (f'<li style="--c:{color}"><span class="ph">{phase}<br><b>{step}</b></span>'
                         f'<span>{e(r["claim"])} <span class="pg">p.{r["page"] or ""}</span>{link}</span></li>')
            glance += f'<h4>논증 흐름</h4><ol class="flow">{rows}</ol>'
        key = [f for f in figs if f["role"] in ("주요 결과", "과정")]
        if key:
            glance += f'<h4>원문 그림·표 · 주요 결과와 과정</h4><div class="gallery">{"".join(fig_html(f) for f in key)}</div>'
        mm_rows = con.execute("SELECT * FROM memos WHERE paper_id=? ORDER BY page, id", (p["id"],)).fetchall()
        if mm_rows:
            from db import MEMO_COLORS
            glance += '<h4>내 메모</h4><ul class="memos">' + "".join(
                f'<li style="--c:{MEMO_COLORS.get(m["color"], MEMO_COLORS["중요"])[1]}"><b>{e(m["color"])}</b> · p.{m["page"]}'
                f'<br><span class="meta">“{e((m["excerpt"] or "(그림 영역)")[:240])}”</span><br>{e(m["memo"] or "")}</li>'
                for m in mm_rows) + "</ul>"
        ol = diagram.outline(con, p["id"])
        if ol:
            glance += ('<details><summary>절 목차</summary><ul class="toc">'
                       + "".join(f'<li><span class="pg">p.{o["page_start"]}</span> <b>{e(o["heading"])}</b> '
                                 f'<span class="meta">{e(o["summary"] or "")}</span></li>' for o in ol) + "</ul></details>")
        if glance:
            glance = f'<details class="glance" open><summary>한눈에 보기</summary>{glance}</details>'
        cards.append(
            f'<article class="paper" data-q="{e((p["title"] + " " + (p["authors"] or "")).lower())}">'
            f'<div class="eyebrow">#{p["id"]} · {p["year"] or ""} · 인용 {p["cited_by"]}</div>'
            f'<h3>{e(p["title"])}</h3><div class="meta">{e(p["authors"] or "")} · <em>{e(p["venue"] or "")}</em>'
            + (f' · <a href="{e(link)}" target="_blank" rel="noopener">원문</a>' if link else "")
            + "</div>" + glance + extra + "".join(secs) + "</article>")
    cards = "".join(cards) or '<p class="meta">아직 분석한 논문이 없습니다.</p>'

    sl = con.execute("SELECT id,year,title,venue,cited_by,status,index_tag,pdf_path IS NOT NULL pdf FROM papers"
                     " WHERE status IN ('shortlist','fulltext','analyzed') OR favorite=1 ORDER BY cited_by DESC").fetchall()
    rows = "".join(f"<tr><td>{r['id']}</td><td>{r['year'] or ''}</td><td>{e(r['title'])}</td><td>{e(r['venue'] or '')}</td>"
                   f"<td>{r['cited_by']}</td><td><span class='tag'>{r['status']}</span></td><td>{'○' if r['pdf'] else ''}</td></tr>"
                   for r in sl)

    return f"""<title>{e(slug)} 문헌 분석</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+KR:wght@400;600&family=Noto+Serif+KR:wght@600&display=swap">
<style>{CSS}</style>
<main class="wrap">
<header style="display:grid;gap:10px">
  <div class="eyebrow">문헌 분석 · {datetime.date.today().isoformat()}</div>
  <h1>{e(name)}</h1>
  <div class="stats">{stats}</div>
</header>
<section><h2>Brief</h2><dl class="brief">{brief}</dl></section>
<section><h2>갭·가설</h2>{gaps}</section>
<section><h2>논문 분석</h2>
  <input id="q" type="search" placeholder="제목·저자로 거르기" aria-label="논문 거르기">
  {cards}
</section>
<section><h2>선별 목록</h2><div class="scroll"><table>
<thead><tr><th>id</th><th>연도</th><th>제목</th><th>저널</th><th>인용</th><th>상태</th><th>원문</th></tr></thead>
<tbody>{rows}</tbody></table></div></section>
</main>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script>
try {{ mermaid.initialize({{startOnLoad:false, securityLevel:'loose'}}); mermaid.run({{querySelector:'pre.mermaid:not([data-processed])'}}); }} catch (err) {{ console.error(err); }}
document.getElementById('q').addEventListener('input',ev=>{{const v=ev.target.value.toLowerCase();
document.querySelectorAll('.paper').forEach(c=>c.hidden=v&&!c.dataset.q.includes(v));}});
</script>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    out = project_dir(a.project) / "export" / "report.html"
    out.write_text(build(a.project))
    print(out)
