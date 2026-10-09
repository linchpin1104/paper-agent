"""DBpia 검색 (국내 학술논문). .env 의 DBPIA_API_KEY 필요.
  python scripts/fetch_dbpia.py search --project SLUG [--pages 3] [--debug]
brief 의 '국문 키워드' 를 쓰고, 없으면 영문 '주제 씨앗' 을 쓴다.
"""
import argparse, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from db import connect, read_brief, upsert_paper, log_search, load_env

API = "http://api.dbpia.co.kr/v2/search/search.xml"  # 문서상 http
SRC = "dbpia"


def txt(el, path):
    """하위요소 텍스트 또는 속성 'name'. 문서의 '하위요소' 표기가 요소/속성 어느 쪽인지 몰라 둘 다 본다."""
    n = el.find(path)
    if n is None:
        return None
    if (n.text or "").strip():
        return n.text.strip()
    sub = n.find("name")
    if sub is not None and (sub.text or "").strip():
        return sub.text.strip()
    return n.get("name")


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    err = root.find(".//error") if root.tag != "error" else root
    if err is not None:
        raise SystemExit("DBpia 오류: " + ET.tostring(err, encoding="unicode")[:300])
    total = root.findtext(".//totalcount")
    items = []
    for it in root.iter("item"):
        if (it.findtext("ctype") or "article") not in ("article", "public"):
            continue
        authors = []
        for a in it.iter("author"):
            authors.append((a.findtext("name") or a.get("name") or a.text or "").strip())
        yymm = it.findtext(".//issue/yymm") or ""
        y = re.search(r"(19|20)\d{2}", yymm)
        link = it.findtext("link_url")
        items.append(dict(
            title=re.sub(r"<[^>]+>", "", it.findtext("title") or "").strip(),
            authors="; ".join(a for a in authors if a), year=int(y.group()) if y else None,
            venue=txt(it, "publication"), url=link,
            oa_url=it.findtext("preview") if it.findtext("price_yn") == "N" else None,
            _id=(re.search(r"nodeId=(\w+)", link or "") or re.search(r"(NODE\d+)", link or "")),
            _reg=it.findtext("dreg_name")))
    return int(total or 0), items


def search(con, brief, pages, debug):
    key = load_env().get("DBPIA_API_KEY")
    if not key:
        sys.exit(".env 에 DBPIA_API_KEY 가 없습니다")
    y0, y1 = brief["years"]
    total = 0
    for kw in brief["keywords_ko"] or brief["keywords"]:
        n = 0
        for page in range(1, pages + 1):
            q = dict(key=key, target="se_adv", searchall=kw, itype=1, category=2, pyear=3,
                     pyear_start=y0, pyear_end=y1, pagecount=100, pagenumber=page)
            with urllib.request.urlopen(f"{API}?{urllib.parse.urlencode(q)}", timeout=60) as r:
                raw = r.read()
            if debug and page == 1:
                print(raw[:2000].decode("utf-8", "replace"))
            tot, items = parse(raw)
            for it in items:
                if any(x.lower() in it["title"].lower() for x in brief["exclude"]):
                    continue
                sid = it["_id"].group(1) if it["_id"] else it["url"]
                pid = upsert_paper(con, it, SRC, sid, raw={"dreg_name": it["_reg"]})
                if pid and it["_reg"]:
                    con.execute("UPDATE papers SET index_tag=COALESCE(index_tag,?) WHERE id=?", (it["_reg"], pid))
                n += 1
            time.sleep(0.3)
            if page * 100 >= tot:
                break
        log_search(con, SRC, kw, n)
        con.commit()
        print(f"[dbpia] {kw!r}: {n}")
        total += n
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    print("합계", search(connect(a.project), read_brief(a.project), a.pages, a.debug))
