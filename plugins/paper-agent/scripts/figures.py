"""원문 그림·표 찾기와 잘라내기.
  python scripts/figures.py detect --project SLUG --paper ID        # 캡션 기준 자동 탐지 → figures 테이블 (다시 돌리면 덮어씀)
  python scripts/figures.py list   --project SLUG --paper ID
  python scripts/figures.py set    --project SLUG --id FID [--role 연구 모형|주요 결과|과정|기타] [--bbox x0,y0,x1,y1] [--note "왜 중요한지"]
  python scripts/figures.py png    --project SLUG --id FID --out x.png   # 잘라낸 이미지 저장 (눈으로 확인용)
  python scripts/figures.py sheet  --project SLUG --paper ID --out sheet.png  # 전체 그림·표 한 장 미리보기
좌표는 PDF 포인트 단위 (쪽 왼쪽 위 0,0).
"""
import argparse, pathlib, re, sys
import fitz
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import connect, project_dir

# 캡션: "Figure 1." "TABLE 2 |" "Table 3 Regression…"(번호 뒤 대문자) "Table A1 …". 본문 언급("Table 2 also …")과 "Table 8. Cont." 는 제외
CAP = re.compile(r"^(FIGURE|Figure|Fig\.|TABLE|Table)\s*([A-Z]?\d+)(?:\s*[.:|]|\s+(?=[A-Z(]))(?!\s*Cont)", re.S)
ROLE_HINTS = [("연구 모형", r"model|framework|hypothes|conceptual"),
              ("주요 결과", r"result|coefficient|regression|structural|moderat|mediat|path|estimat|interaction|test"),
              ("과정", r"protocol|process|procedure|stage|flow|design")]
ROLES = ["연구 모형", "주요 결과", "과정", "기타"]


def check():
    """캡션 정규식 자체 점검: python figures.py check --project x"""
    cases = {"Table 3 Regression analysis.": "Table 3", "Table A1 Digital level.": "Table A1", "TABLE 1 | Fit": "TABLE 1",
             "Figure 1. Protocol": "Figure 1", "FIGURE 1 | Model": "FIGURE 1", "Fig. 2: Loop": "Fig. 2",
             "Table 2 also highlights": None, "Figure 6 represents": None, "Table 8. Cont.": None, "Table 8 Cont.": None}
    for t, want in cases.items():
        m = CAP.match(t)
        got = f"{m.group(1)} {m.group(2)}" if m else None
        assert got == want, (t, got)
    print(f"캡션 점검 {len(cases)}건 통과")


def guess_role(caption):
    for role, pat in ROLE_HINTS:
        if re.search(pat, caption, re.I):
            return role
    return "기타"


def graphics(page):
    rects = [fitz.Rect(d["rect"]) for d in page.get_drawings() if d["rect"].width > 2 or d["rect"].height > 2]
    rects += [fitz.Rect(i["bbox"]) for i in page.get_image_info()]
    return [r for r in rects if r.width < page.rect.width * 0.98 or r.height < page.rect.height * 0.9]


def region(page, cap_rect, kind, caps_on_page):
    """캡션 위치로 그림(캡션 위)·표(캡션 아래) 영역 추정."""
    W, H = page.rect.width, page.rect.height
    if cap_rect.height > cap_rect.width * 3:  # 세로로 돌린 표·그림 → 캡션부터 오른쪽 끝까지
        return fitz.Rect(cap_rect.x0 - 6, 20, W - 20, H - 20)
    col = fitz.Rect(min(cap_rect.x0, 40), 0, W - 30, H) if cap_rect.x0 > W * 0.4 else fitz.Rect(30, 0, W - 30, H)
    blocks = [fitz.Rect(b[:4]) for b in page.get_text("blocks")]
    if kind == "figure":
        top_limit = max([c.y1 for c in caps_on_page if c.y1 <= cap_rect.y0] + [30])
        g = [r for r in graphics(page) if r.y1 <= cap_rect.y0 + 4 and r.y0 >= top_limit - 2]
        # 캡션 바로 위에서부터 위쪽으로 이어지는 그래픽만 (간격 40pt 이내)
        g.sort(key=lambda r: -r.y1)
        box, edge = None, cap_rect.y0
        for r in g:
            if r.y1 >= edge - 40:
                box = r if box is None else box | r
                edge = min(edge, r.y0)
        if box is None:  # 그래픽이 없으면 캡션 위 본문 아닌 영역
            above = [b for b in blocks if b.y1 <= cap_rect.y0 - 2 and b.width > W * 0.35]
            y0 = max([b.y1 for b in above] + [top_limit])
            box = fitz.Rect(col.x0, y0, col.x1, cap_rect.y0)
        r = box | cap_rect
    else:
        nxt = min([c.y0 for c in caps_on_page if c.y0 > cap_rect.y1] + [H - 30])
        box = fitz.Rect(cap_rect)
        try:
            tabs = [fitz.Rect(t.bbox) for t in page.find_tables().tables if cap_rect.y0 - 5 <= t.bbox[1] < nxt]
            if tabs:  # 표 인식은 두 단 본문까지 한 표로 잡기도 해서, 가로 폭만 쓴다
                t = min(tabs, key=lambda t: t.y0)
                box |= fitz.Rect(t.x0, cap_rect.y0, t.x1, cap_rect.y1)
        except Exception:
            pass
        # 아래로 이어지는 행(텍스트·선)을 간격 14pt 이내까지 따라 내려간다
        texts = {tuple(fitz.Rect(b[:4])): b[4] for b in page.get_text("blocks")}
        items = sorted([r for r in blocks + graphics(page)
                        if r.y0 >= cap_rect.y1 - 1 and r.y1 <= nxt + 1 and r.x0 < box.x1 + 10 and r.x1 > box.x0 - 10],
                       key=lambda r: r.y0)
        edge = box.y1
        for it in items:
            gap = it.y0 - edge
            t = texts.get(tuple(it), "")
            n = len(t)
            # 본문 문단 = 길고, 넓고, 한 줄이 길다. 표 칸은 줄이 짧다(칸마다 줄바꿈)
            wide_para = n > 400 and it.width > W * 0.4 and n / (t.count("\n") + 1) > 40
            heading = t.strip().lower() in ("references", "acknowledgements", "acknowledgments", "appendix")
            if gap > 40 or (gap > 10 and n > 80) or (gap > 3 and wide_para) or heading:
                break
            box |= it
            edge = max(edge, it.y1)
        r = box
    r = fitz.Rect(r.x0 - 4, r.y0 - 4, r.x1 + 4, r.y1 + 4) & page.rect
    return r


def detect(con, slug, pid):
    path = project_dir(slug) / con.execute("SELECT pdf_path FROM papers WHERE id=?", (pid,)).fetchone()["pdf_path"]
    doc = fitz.open(path)
    con.execute("DELETE FROM figures WHERE paper_id=? AND (note IS NULL OR note='')", (pid,))
    n = 0
    for pno, page in enumerate(doc, 1):
        caps = []
        for b in page.get_text("blocks"):
            t = " ".join(b[4].split())
            m = CAP.match(t)
            if m and len(t) < 600:
                caps.append((fitz.Rect(b[:4]), m, t))
        cap_rects = [c[0] for c in caps]
        for rect, m, t in caps:
            kind = "table" if m.group(1).lower().startswith("tab") else "figure"
            label = f"{'Table' if kind == 'table' else 'Figure'} {m.group(2)}"
            if con.execute("SELECT 1 FROM figures WHERE paper_id=? AND label=?", (pid, label)).fetchone():
                continue  # 사람이·에이전트가 손본 것은 유지
            r = region(page, rect, kind, cap_rects)
            rot = 90 if rect.height > rect.width * 3 else 0  # 옆으로 인쇄된 표·그림은 세워서 보여준다
            con.execute("INSERT INTO figures(paper_id,label,kind,page,x0,y0,x1,y1,caption,role,rot) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, label, kind, pno, r.x0, r.y0, r.x1, r.y1, t[:400], guess_role(t), rot))
            n += 1
    con.commit()
    print(f"#{pid} 그림·표 {n}개 탐지")


def crop_png(con, slug, fid, zoom=2.0):
    f = con.execute("SELECT f.*, p.pdf_path FROM figures f JOIN papers p ON p.id=f.paper_id WHERE f.id=?", (fid,)).fetchone()
    clip = fitz.Rect(f["x0"], f["y0"], f["x1"], f["y1"])
    with fitz.open(project_dir(slug) / f["pdf_path"]) as doc:
        if not f["rot"]:
            return doc[f["page"] - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip).tobytes("png")
        out = fitz.open()  # 돌린 표: 새 쪽에 회전해 붙인 뒤 렌더
        pg = out.new_page(width=clip.height, height=clip.width)
        pg.show_pdf_page(pg.rect, doc, f["page"] - 1, clip=clip, rotate=-f["rot"])
        return pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["detect", "list", "set", "png", "sheet", "check"])
    ap.add_argument("--project")
    ap.add_argument("--paper", type=int)
    ap.add_argument("--id", type=int)
    ap.add_argument("--role", choices=ROLES)
    ap.add_argument("--bbox")
    ap.add_argument("--note")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "check":
        return check()
    con = connect(a.project)
    if a.cmd == "detect":
        detect(con, a.project, a.paper)
    elif a.cmd == "list":
        for f in con.execute("SELECT * FROM figures WHERE paper_id=? ORDER BY page, id", (a.paper,)):
            print(f"{f['id']:>4} p.{f['page']:<3} {f['label']:<10} {f['role']:<6} [{f['x0']:.0f},{f['y0']:.0f},{f['x1']:.0f},{f['y1']:.0f}] {f['caption'][:70]}"
                  + (f"  ※ {f['note']}" if f["note"] else ""))
    elif a.cmd == "set":
        if a.role:
            con.execute("UPDATE figures SET role=? WHERE id=?", (a.role, a.id))
        if a.bbox:
            x0, y0, x1, y1 = map(float, a.bbox.split(","))
            con.execute("UPDATE figures SET x0=?,y0=?,x1=?,y1=? WHERE id=?", (x0, y0, x1, y1, a.id))
        if a.note:
            con.execute("UPDATE figures SET note=? WHERE id=?", (a.note, a.id))
        con.commit()
        print("ok")
    elif a.cmd == "png":
        pathlib.Path(a.out).write_bytes(crop_png(con, a.project, a.id))
        print(a.out)
    elif a.cmd == "sheet":
        figs = con.execute("SELECT id FROM figures WHERE paper_id=? ORDER BY page, id", (a.paper,)).fetchall()
        pix = [fitz.Pixmap(crop_png(con, a.project, f["id"], 1.0)) for f in figs]
        W = 900
        H = sum(int(p.height * min(1, W / p.width)) + 24 for p in pix) + 10
        out = fitz.open()
        page = out.new_page(width=W, height=H)
        y = 5
        for f, p in zip(figs, pix):
            s = min(1, W / p.width)
            page.insert_text((5, y + 12), f"id {f['id']}", fontsize=10, color=(1, 0, 0))
            page.insert_image(fitz.Rect(5, y + 16, 5 + p.width * s, y + 16 + p.height * s), pixmap=p)
            page.draw_rect(fitz.Rect(5, y + 16, 5 + p.width * s, y + 16 + p.height * s), color=(1, 0, 0), width=0.6)
            y += p.height * s + 24
        out[0].get_pixmap(matrix=fitz.Matrix(1, 1)).save(a.out)
        print(a.out, len(figs))


if __name__ == "__main__":
    main()
