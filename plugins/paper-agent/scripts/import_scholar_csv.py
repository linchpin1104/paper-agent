"""Google Scholar 결과 가져오기. Publish or Perish 에서 Google Scholar 검색 → File > Save as CSV.
  python scripts/import_scholar_csv.py --project SLUG --file results.csv [--query "검색어"]
"""
import argparse, csv, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from db import connect, upsert_paper, log_search


def rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("title"):
                continue
            yield dict(title=r["title"], authors=r.get("authors", "").replace(", ", "; "),
                       year=int(r["year"]) if r.get("year", "").isdigit() else None,
                       venue=r.get("source") or r.get("publisher"), doi=r.get("doi") or None,
                       cited_by=int(r["cites"]) if r.get("cites", "").isdigit() else 0,
                       url=r.get("articleurl") or r.get("fulltexturl"), oa_url=None,
                       abstract=r.get("abstract") or None), r.get("articleurl") or r["title"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--query", default="(csv)")
    a = ap.parse_args()
    con = connect(a.project)
    n = sum(1 for rec, sid in rows(a.file) if upsert_paper(con, rec, "scholar", sid))
    log_search(con, "scholar", a.query, n)
    con.commit()
    print(f"[scholar] {n}건 가져옴")
