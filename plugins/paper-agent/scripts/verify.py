"""진위·인용 검증.
  python scripts/verify.py run   --project SLUG [--paper ID]   # 인용 관계 검증 단계 갱신 + PDF 제목 대조
  python scripts/verify.py check --project SLUG                 # 자체 점검

인용 관계(edges) 검증 단계:
  db1   DB 한 곳만 기록          db2  OpenAlex·Semantic Scholar 두 곳이 같은 기록
  text  인용한 논문의 원문 참고문헌에서 피인용 논문의 1저자 성 + 연도(±1)를 찾음
  miss  인용한 논문 원문이 있는데 참고문헌에서 못 찾음 → 사람 확인 필요
  human 사람이 확인 (화면에서 표시. 자동으로 덮어쓰지 않음)
"""
import argparse, json, pathlib, re, sys, unicodedata
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import connect, quote_on_page


def plain(s):
    """악센트·특수 하이픈을 없애고 소문자로."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[‐-―­]", "-", s).lower()


def ref_section(pages):
    """원문에서 참고문헌 부분. 제목을 못 찾으면 뒤쪽 35%."""
    full = "\n".join(pages)
    hits = [m.start() for m in re.finditer(r"\n\s*(references|bibliography|literature cited|참고문헌)\s*\n", full, re.I)]
    start = hits[-1] if hits else int(len(full) * 0.65)
    return plain(full[start:]), full[:start]


def surname(authors):
    first = (authors or "").split(";")[0].strip()
    if not first:
        return ""
    if "," in first:  # "Ahl, Helene" 형식
        return plain(first.split(",")[0]).strip()
    return plain(first.split()[-1])


def find_ref(reftext, last, year, window=250):
    """참고문헌 텍스트에서 성과 연도(±1)가 가까이 붙어 있는 곳. 근거 문구 반환."""
    if not last or len(last) < 2 or not year:
        return None
    for m in re.finditer(r"\b" + re.escape(last) + r"\b", reftext):
        seg = reftext[max(0, m.start() - 40): m.start() + window]
        for y in (year, year - 1, year + 1):
            if str(y) in seg:
                return " ".join(seg.split())[:160]
    return None


VERSION_HINTS = r"working paper|discussion paper|preprint|accepted manuscript|author accepted|pre-print|ssrn|nber working|this is the author"


def title_check(con, pid):
    """PDF 첫 2쪽에 기록된 제목의 앞 8단어가 있는지(엉뚱한 PDF 방지) + 원고본(워킹페이퍼·프리프린트)인지.
    결과: 일치 / 일치·원고본 / 불일치. 원고본은 쪽 번호·문장이 출판본과 다를 수 있어 인용 전에 출판본 확인이 필요하다."""
    r = con.execute("SELECT p.title, f.pages FROM papers p JOIN fulltext f ON f.paper_id=p.id WHERE p.id=?", (pid,)).fetchone()
    if not r:
        return None
    squash = lambda s: re.sub(r"[^a-z0-9가-힣]", "", plain(s))  # 띄어쓰기·하이픈 차이 무시 (Start-Up = Startup)
    head_raw = plain(" ".join(json.loads(r["pages"])[:2]))
    words = re.findall(r"[a-z0-9가-힣]+", plain(r["title"]))[:8]
    ok = squash(" ".join(words)) in squash(head_raw)
    res = ("일치·원고본" if re.search(VERSION_HINTS, head_raw[:3000]) else "일치") if ok else "불일치"
    con.execute("UPDATE papers SET title_check=? WHERE id=?", (res, pid))
    return res


def verify_edges(con, pid=None):
    """인용 관계 검증 단계 갱신. 사람이 확인한 것(human)은 건드리지 않는다."""
    q = ("SELECT e.rowid AS rid, e.from_id, e.to_id, e.sources, e.verified, t.authors, t.year "
         "FROM edges e JOIN papers t ON t.id=e.to_id WHERE e.kind='cites' AND COALESCE(e.verified,'')!='human'")
    rows = con.execute(q + (" AND e.from_id=?" if pid else ""), (pid,) if pid else ()).fetchall()
    cache, n = {}, {"text": 0, "miss": 0, "db2": 0, "db1": 0}
    for r in rows:
        if r["from_id"] not in cache:
            f = con.execute("SELECT pages FROM fulltext WHERE paper_id=?", (r["from_id"],)).fetchone()
            cache[r["from_id"]] = ref_section(json.loads(f["pages"]))[0] if f else None
        reftext = cache[r["from_id"]]
        level, ev = ("db2" if len((r["sources"] or "").split(",")) >= 2 else "db1"), None
        if reftext is not None:
            ev = find_ref(reftext, surname(r["authors"]), r["year"])
            level = "text" if ev else "miss"
        con.execute("UPDATE edges SET verified=?, evidence=? WHERE rowid=?", (level, ev, r["rid"]))
        n[level] += 1
    con.commit()
    return n


def check():
    ref = plain("Ahl, H. (2006). Why research on women entrepreneurs needs new directions. ETP.\n"
                "Delanoë‐Gueguen, S., & Fayolle, A. (2019). Crossing the entrepreneurial Rubicon.")
    assert find_ref(ref, "ahl", 2006)
    assert find_ref(ref, surname("Servane Delanoë‐Gueguen; Alain Fayolle"), 2018)  # 연도 ±1, 특수 하이픈
    assert find_ref(ref, "brush", 2009) is None
    assert surname("Ahl, Helene") == "ahl" and surname("Helene Ahl; X") == "ahl"
    print("검증 점검 4건 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "check"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--paper", type=int)
    a = ap.parse_args()
    if a.cmd == "check":
        check()
    else:
        con = connect(a.project)
        ids = [a.paper] if a.paper else [r[0] for r in con.execute("SELECT paper_id FROM fulltext")]
        t = {pid: title_check(con, pid) for pid in ids}
        con.commit()
        print("PDF 제목 대조:", {k: v for k, v in t.items()})
        print("인용 검증:", verify_edges(con, a.paper))
        for n in con.execute("SELECT id, paper_id, page, quote FROM notes WHERE quote IS NOT NULL AND page IS NOT NULL"
                             + (" AND paper_id=?" if a.paper else ""), (a.paper,) if a.paper else ()).fetchall():
            con.execute("UPDATE notes SET quote_ok=? WHERE id=?", (int(quote_on_page(con, n["paper_id"], n["page"], n["quote"])), n["id"]))
        con.commit()
        print("노트 인용 대조:", dict(con.execute("SELECT quote_ok, COUNT(*) FROM notes WHERE quote IS NOT NULL GROUP BY quote_ok").fetchall()))
