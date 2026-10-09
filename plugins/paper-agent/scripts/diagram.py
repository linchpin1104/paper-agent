"""논문 한눈에 보기: 연구 모형 도식(DOT·Mermaid), 구조 맵, 요약 카드. 데이터는 variables·hypotheses·outline·notes."""
import re

RESULT_COLOR = {"지지": "#3a8a5c", "부분지지": "#c27a1a", "기각": "#8a8f98"}
ROLE_FILL = {"IV": "#dbe7f3", "DV": "#e3efe6", "MED": "#efe6f3", "MOD": "#f6ecd9", "CTRL": "#eceef1", "기타": "#f6ecd9"}
# 논증 흐름 단계 → (묶음, 색). 왜 → 무엇을 → 어떻게 → 그래서
PHASE = {"문제의식": ("왜", "#2f6db0"), "연구 공백": ("왜", "#2f6db0"), "연구 목적": ("왜", "#2f6db0"),
         "이론적 근거": ("무엇을", "#7a4fa8"), "가설·주장": ("무엇을", "#7a4fa8"),
         "연구 방법": ("어떻게", "#2f7a4f"), "핵심 발견": ("어떻게", "#2f7a4f"),
         "기여": ("그래서", "#b2661a"), "한계·과제": ("그래서", "#b2661a")}


def split(v):
    return [x.strip() for x in re.split(r";", v or "") if x.strip()]


def model(con, pid):
    """(nodes {이름: 역할}, paths [(iv, dv, [코드], 결과색, 점선여부, [(조절변수, 코드)], 매개변수|None)])"""
    nodes = {r["name"]: r["role"] for r in con.execute("SELECT name, role FROM variables WHERE paper_id=? ORDER BY id", (pid,))}
    paths = {}
    for h in con.execute("SELECT * FROM hypotheses WHERE paper_id=? ORDER BY id", (pid,)):
        mods = split(h["moderator"])
        meds = split(h["mediator"]) or [None]
        for iv in split(h["iv"]):
            for dv in split(h["dv"]):
                for med in meds:
                    for n, role in ((iv, "IV"), (dv, "DV"), (med, "MED")):
                        if n:
                            nodes.setdefault(n, role)
                    for m in mods:
                        nodes.setdefault(m, "MOD")
                    p = paths.setdefault((iv, dv, med), {"codes": [], "results": [], "null": False, "mods": []})
                    if mods:
                        p["mods"] += [(m, h["code"], h["result"]) for m in mods]
                    else:
                        p["codes"].append(h["code"])
                        p["results"].append(h["result"] or "")
                        p["null"] |= "무" in (h["direction"] or "")
    return nodes, paths


MARK = {"지지": "✓", "부분지지": "△", "기각": "✕"}


def mod_groups(nodes, paths):
    """같은 조절변수 집합을 가진 경로들을 묶는다. {(이름들): {"label": [...], "results": [...], "paths": [key...]}}"""
    groups = {}
    for key, p in paths.items():
        if not p["mods"]:
            continue
        order = {}
        for m, code, _ in p["mods"]:
            order.setdefault(m, int(re.sub(r"\D", "", code) or 0))
        names = tuple(sorted(order, key=order.get))  # 가설 번호순
        g = groups.setdefault(names, {"lines": {}, "results": [], "paths": []})
        g["paths"].append(key)
        for m, code, r in p["mods"]:
            g["lines"][m] = f"{m}  {code} {MARK.get(r, '')}".strip()
            g["results"].append(r)
    for names in groups:
        for m in names:
            nodes.pop(m, None)  # 개별 노드 대신 묶음 상자로
    return groups


def color(results):
    rs = [r for r in results if r]
    if not rs:
        return "#5b6474"
    if all(r == "지지" for r in rs):
        return RESULT_COLOR["지지"]
    if all(r == "기각" for r in rs):
        return RESULT_COLOR["기각"]
    return RESULT_COLOR["부분지지"]


def to_dot(con, pid):
    nodes, paths = model(con, pid)
    if not paths:
        return None
    groups = mod_groups(nodes, paths)
    ids = {n: f"n{i}" for i, n in enumerate(nodes)}
    out = ['digraph G { rankdir=LR; bgcolor="transparent"; nodesep=0.3; ranksep=0.8; splines=true;',
           'node [shape=box style="rounded,filled" fontname="Apple SD Gothic Neo" fontsize=11 color="#9aa3b2"];',
           'edge [fontname="Helvetica" fontsize=10];']
    for n, role in nodes.items():
        out.append(f'{ids[n]} [label="{n}\\n[{role}]" fillcolor="{ROLE_FILL.get(role, "#eceef1")}"];')
    junction = {}
    for k, ((iv, dv, med), p) in enumerate(paths.items()):
        c = color(p["results"] + [r for _, _, r in p["mods"]])
        style = "dashed" if p["null"] else "solid"
        lab = ",".join(p["codes"])
        a, b = ids[iv], ids[dv]
        if med:
            out.append(f'{a} -> {ids[med]} [color="{c}" style={style}]; {ids[med]} -> {b} [label="{lab}" color="{c}" style={style}];')
        elif p["mods"]:
            j = junction[(iv, dv, med)] = f"j{k}"
            out.append(f'{j} [shape=point width=0.08 color="{c}"];')
            out.append(f'{a} -> {j} [arrowhead=none color="{c}" style={style}]; {j} -> {b} [label="{lab}" color="{c}" fontcolor="{c}" style={style}];')
        else:
            out.append(f'{a} -> {b} [label="{lab}" color="{c}" fontcolor="{c}" style={style}];')
    for gi, (names, g) in enumerate(groups.items()):
        c = color(g["results"])
        label = "조절변수\\l" + "\\l".join(g["lines"][m] for m in names) + "\\l"
        out.append(f'g{gi} [label="{label}" fillcolor="{ROLE_FILL["MOD"]}" fontsize=10];')
        for key in g["paths"]:
            out.append(f'g{gi} -> {junction[key]} [color="{c}" style=dashed];')
    out.append("}")
    return "\n".join(out)


def to_mermaid(con, pid):
    nodes, paths = model(con, pid)
    if not paths:
        return None
    groups = mod_groups(nodes, paths)
    ids = {n: f"n{i}" for i, n in enumerate(nodes)}
    q = lambda s: s.replace('"', "'")
    out, styles, li = ["flowchart LR"], [], 0
    for n, role in nodes.items():
        out.append(f'  {ids[n]}["{q(n)}<br/><small>{role}</small>"]')
        styles.append(f"  style {ids[n]} fill:{ROLE_FILL.get(role, '#eceef1')},stroke:#9aa3b2,color:#1b2230")

    def link(a, b, lab, c, dashed, arrow=True):
        nonlocal li
        arr = ("-.->" if dashed else "-->") if arrow else ("-.-" if dashed else "---")
        out.append(f"  {a} {arr}" + (f"|{q(lab)}|" if lab else "") + f" {b}")
        styles.append(f"  linkStyle {li} stroke:{c},stroke-width:2px")
        li += 1

    junction = {}
    for k, ((iv, dv, med), p) in enumerate(paths.items()):
        c = color(p["results"] + [r for _, _, r in p["mods"]])
        lab = ",".join(p["codes"])
        if med:
            link(ids[iv], ids[med], "", c, p["null"])
            link(ids[med], ids[dv], lab, c, p["null"])
        elif p["mods"]:
            j = junction[(iv, dv, med)] = f"j{k}"
            out.append(f"  {j}(( ))")
            styles.append(f"  style {j} fill:{c},stroke:{c}")
            link(ids[iv], j, "", c, p["null"], arrow=False)
            link(j, ids[dv], lab, c, p["null"])
        else:
            link(ids[iv], ids[dv], lab, c, p["null"])
    for gi, (names, g) in enumerate(groups.items()):
        out.append(f'  g{gi}["<b>조절변수</b><br/>' + "<br/>".join(q(g["lines"][m]) for m in names) + '"]')
        styles.append(f"  style g{gi} fill:{ROLE_FILL['MOD']},stroke:#9aa3b2,color:#1b2230,text-align:left")
        for key in g["paths"]:
            link(f"g{gi}", junction[key], "", color(g["results"]), True)
    return "\n".join(out + styles)


def outline(con, pid):
    return [dict(r) for r in con.execute("SELECT heading, page_start, page_end, summary FROM outline WHERE paper_id=? ORDER BY id", (pid,))]


if __name__ == "__main__":  # 자체 점검: 메모리 DB 로 조절·매개·직접 경로
    import sqlite3, sys
    sys.path.insert(0, __import__("os").path.dirname(__file__))
    from db import SCHEMA
    con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row; con.executescript(SCHEMA)
    for role, name in [("IV", "X"), ("DV", "Y1"), ("DV", "Y2"), ("MOD", "W"), ("MED", "M")]:
        con.execute("INSERT INTO variables(paper_id,role,name) VALUES(1,?,?)", (role, name))
    hy = [("H1", "X", "Y1; Y2", None, None, "+", "지지"), ("H2", "X", "Y1", None, "W", "+", "기각"),
          ("H3", "X", "Y2", "M", None, "+", "지지")]
    for c, iv, dv, med, mod, d, r in hy:
        con.execute("INSERT INTO hypotheses(paper_id,code,iv,dv,mediator,moderator,direction,result) VALUES(1,?,?,?,?,?,?,?)",
                    (c, iv, dv, med, mod, d, r))
    nodes, paths = model(con, 1)
    assert set(nodes) == {"X", "Y1", "Y2", "W", "M"}, nodes
    assert paths[("X", "Y1", None)]["codes"] == ["H1"] and paths[("X", "Y1", None)]["mods"] == [("W", "H2", "기각")]
    assert ("X", "Y2", "M") in paths
    dot, mm = to_dot(con, 1), to_mermaid(con, 1)
    links = [l for l in mm.splitlines() if any(t in l for t in ("---", "-->", "-.-"))]
    assert "shape=point" in dot and "W  H2 ✕" in dot and "W  H2 ✕" in mm and mm.count("linkStyle") == len(links) == 6, mm
    print("diagram ok")
