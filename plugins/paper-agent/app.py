"""논문 프로젝트 페이지.  실행: streamlit run app.py"""
import base64, html, json, pathlib, re, shutil, subprocess, sys
import streamlit as st
import streamlit.components.v1 as components

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT / "scripts"))
import db  # noqa: E402
import diagram  # noqa: E402
import figures  # noqa: E402
import seeds as seedmod  # noqa: E402
import verify  # noqa: E402
import journals as jmod  # noqa: E402
import fetch_openalex  # noqa: E402

st.set_page_config(page_title="논문 에이전트", layout="wide", initial_sidebar_state="expanded")
st.markdown("<style>.block-container{padding-top:1.5rem;padding-bottom:2rem}</style>", unsafe_allow_html=True)
highlighter = components.declare_component("pdf_highlighter", path=str(ROOT / "components/pdf_highlighter"))

# 화면에 보이는 상태 이름 (DB 값 → 한국어)
STATUS_KO = {"candidate": "후보", "shortlist": "읽을 목록", "fulltext": "원문 있음", "analyzed": "분석됨", "rejected": "제외"}
KO_STATUS = {v: k for k, v in STATUS_KO.items()}


def run(*args):
    args = [str(ROOT / a) if a.startswith("scripts/") else a for a in args]
    with st.spinner(pathlib.Path(args[0]).stem):
        r = subprocess.run([sys.executable, *args], cwd=db.HOME, capture_output=True, text=True)
    st.code((r.stdout + r.stderr)[-4000:] or "(출력 없음)")


# ── 학회지 구독 (프로젝트와 별개) ───────────────────────────
def journal_card(j):
    pr = j.get("profile")
    issn = j.get("issn")
    head = j["name"] + (f" · ISSN {issn}" if issn else "") + (f" · {j['publisher']}" if j.get("publisher") else "")
    with st.expander(head):
        if issn:
            st.markdown(f"[SSCI·SCIE 등재 확인 (Clarivate)](https://mjl.clarivate.com/search-results?issn={issn})")
        if not pr:
            st.caption("아직 분석 전입니다.")
        else:
            st.caption(f"최근 {pr['period']} 분석 · {pr['at'][:10]}")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**연도별 게재 편수**  \n" + " · ".join(f"{y} {n}편" for y, n in pr["years"]))
                st.markdown("**주요 주제**  \n" + "  \n".join(f"{t} ({n})" for t, n in pr["topics"][:5]))
            with c2:
                st.markdown("**저자 국가**  \n" + " · ".join(f"{c} {n}" for c, n in pr["countries"][:6])
                            + (f"  \n한국 저자 논문 **{pr['korea']}편**" if "korea" in pr else ""))
                st.markdown("**최근 고인용**  \n" + "  \n".join(f"{y} · {t} ({c}회)" for y, t, c in pr["top"][:5]))
            for proj, f in (j.get("fit") or {}).items():
                st.markdown(f"**프로젝트 '{proj}' 와의 맞춤도** · {(f.get('at') or '')[:10]}")
                c1, c2 = st.columns(2)
                c1.dataframe([{"주제 키워드": k, "편수": n} for k, n in f["my_keywords"].items()], hide_index=True, width="stretch")
                c2.dataframe([{"핵심 논문을 인용한 최근 논문": k[:60], "편수": n} for k, n in f["cites_my_seeds"].items()],
                             hide_index=True, width="stretch")
        a, b, c = st.columns([1, 2, 1])
        if a.button("분석", key=f"jp{j['source']}", help="최근 3년 게재 경향"):
            run("scripts/journals.py", "profile", "--source", j["source"])
            st.rerun()
        fit_proj = b.selectbox("맞춤도 볼 프로젝트", ["—"] + projects, key=f"jf{j['source']}", label_visibility="collapsed")
        if fit_proj != "—" and b.button("이 프로젝트와 맞춤도 분석", key=f"jfb{j['source']}"):
            run("scripts/journals.py", "profile", "--source", j["source"], "--project", fit_proj)
            st.rerun()
        if c.button("구독 해제", key=f"jr{j['source']}"):
            run("scripts/journals.py", "remove", "--source", j["source"])
            st.rerun()


def journal_page():
    st.caption("구독한 학회지에 새로 실린 논문을 키워드로 거르지 않고 모두 받아, 학회지별로 무엇이 나왔는지 정리합니다. "
               "연구 프로젝트와는 별개이고, 원하면 고른 논문을 프로젝트로 보낼 수 있습니다.")
    jd = jmod.load()
    t_new, t_sum, t_list = st.tabs([f"새 논문 {len(jd['new'])}", "요약", f"구독 학회지 {len(jd['journals'])}"])
    with t_list:
        for j in jd["journals"]:
            journal_card(j)
        with st.expander("학회지 추가", expanded=not jd["journals"]):
            jq = st.text_input("학회지 이름 또는 ISSN", key="jq")
            if st.button("찾기", key="jfind") and jq.strip():
                try:
                    st.session_state["jcands"] = jmod.find(jq)
                except fetch_openalex.BudgetError as e:
                    st.error(str(e))
            jc = st.session_state.get("jcands", [])
            if jc:
                lab = {c["source"]: f"{c['name']} · ISSN {c['issn']} · {c['publisher'] or ''} · 논문 {c['works']} · h {c['h']}"
                       for c in jc}
                pick = st.radio("후보 (이름이 비슷한 다른 학회지가 섞일 수 있습니다)", list(lab), format_func=lab.get, key="jpick")
                if st.button("구독", key="jadd", type="primary"):
                    run("scripts/journals.py", "add", "--source", pick)
                    run("scripts/journals.py", "profile", "--source", pick)
                    st.session_state.pop("jcands", None)
                    st.rerun()
    with t_new:
        last = max((j.get("last_checked") or "" for j in jd["journals"]), default="")
        c1, c2 = st.columns([1, 3], vertical_alignment="center")
        if c1.button("새 논문 받기", type="primary", disabled=not jd["journals"],
                     help="지난 확인 이후 실린 논문을 모두 가져옵니다 (처음엔 최근 90일)"):
            run("scripts/journals.py", "update")
            st.rerun()
        c2.caption(f"마지막 확인 {last or '없음'} · 매주 자동으로 받으려면 Claude 에게 '학회지 구독 매주 받아서 요약해줘'라고 하세요")
        items = jmod.new_list()
        if not items:
            st.caption("확인하지 않은 새 논문이 없습니다.")
        groups = {}
        for r in items:
            groups.setdefault(r["journal"] or "기타", []).append(r)
        for jname, rows in groups.items():
            with st.expander(f"{jname} · {len(rows)}편", expanded=False):
                for r in rows:
                    a, b = st.columns([1, 20])
                    a.checkbox("보내기", key=f"js{r['id']}", label_visibility="collapsed")
                    b.markdown(f"<div style='font-size:13px;line-height:1.45;margin-bottom:10px'><b>{html.escape(r['title'])}</b> · {r['date']}"
                               f"<br><span style='color:#5b6474'>{html.escape((r['abstract'] or '(초록 없음)')[:420])}</span></div>",
                               unsafe_allow_html=True)
        if items:
            st.divider()
            c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")
            target = c1.selectbox("체크한 논문을 보낼 프로젝트", projects or ["(프로젝트 없음)"], key="jsend_to")
            if c2.button("프로젝트 읽을 목록으로 보내기", disabled=not projects):
                ids = [r["id"] for r in items if st.session_state.get(f"js{r['id']}")]
                if ids:
                    run("scripts/journals.py", "send", "--project", target, "--ids", ",".join(map(str, ids)))
            if c3.button("모두 확인함", help="새 논문 목록을 비웁니다. 다음 받기부터 새로 쌓입니다"):
                run("scripts/journals.py", "seen")
                st.rerun()
    with t_sum:
        digests = sorted((jmod.jdir() / "feeds").glob("*.md"), reverse=True)
        if not digests:
            st.caption("아직 요약이 없습니다. Claude 에게 '학회지 새 논문 요약해줘'라고 하면 학회지별로 이번에 나온 주제·방법·눈에 띄는 논문을 정리해 여기에 올립니다.")
        else:
            pick = st.selectbox("요약", [d.stem for d in digests], key="jdig")
            st.markdown((jmod.jdir() / "feeds" / f"{pick}.md").read_text())


# ── 맨 위 메뉴 (사이드바 없음: 좁은 창에서도 본문을 가리지 않게) ─────────────
(db.HOME / "projects").mkdir(exist_ok=True)
projects = sorted(p.name for p in (db.HOME / "projects").iterdir() if (p / "brief.md").exists())
# 왼쪽 위: 무엇을 할지(메뉴) · 오른쪽 위: 어느 프로젝트인지
top_l, top_r = st.columns([3, 2], vertical_alignment="center")
mode = top_l.segmented_control("메뉴", ["논문 프로젝트", "학회지 구독"], default="논문 프로젝트",
                               key="mode", label_visibility="collapsed") or "논문 프로젝트"
if mode == "학회지 구독":
    journal_page()
    st.stop()

c1, c2 = top_r.columns([3, 2], vertical_alignment="center")
def first_tab(s):
    """작업 순서대로. 주제 키워드가 아직 없으면 연구 주제 설정부터 연다."""
    return "찾기" if any("(" not in k and ")" not in k for k in db.read_brief(s)["keywords"]) else "연구 주제 설정"


if "made" in st.session_state:  # 방금 만든 프로젝트를 바로 고른 상태로
    st.session_state["slug"] = st.session_state.pop("made")
    st.session_state["sec"] = "연구 주제 설정"  # 다음 할 일: 주제·키워드 채우기
slug = c1.selectbox("프로젝트", projects, key="slug", label_visibility="collapsed",
                    on_change=lambda: st.session_state.update(sec=first_tab(st.session_state["slug"])),
                    placeholder="프로젝트를 만드세요") if projects else None
with c2.popover("새 프로젝트", width="stretch"):
    new = st.text_input("영문 약칭 (예: women-founders)").strip().lower().replace(" ", "-")
    if st.button("만들기"):
        d = db.HOME / "projects" / new
        if not re.fullmatch(r"[a-z0-9-]+", new):
            st.error("영문 소문자·숫자·하이픈(-)만 쓸 수 있습니다.")
        elif (d / "brief.md").exists():
            st.error(f"'{new}' 프로젝트가 이미 있습니다.")
        else:
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / "templates/brief.md", d / "brief.md")
            shutil.copy(ROOT / "templates/decisions.md", d / "decisions.md")
            st.session_state["made"] = new
            st.rerun()
if not slug:
    st.info("오른쪽 위 '새 프로젝트'로 연구 프로젝트를 만드세요.")
    st.stop()

con = db.connect(slug)
P = ["--project", slug]
cnt = dict(con.execute("SELECT status, COUNT(*) FROM papers GROUP BY status").fetchall())
n_memo = con.execute("SELECT COUNT(*) FROM memos").fetchone()[0]
s1, s2 = st.columns([3, 2], vertical_alignment="center")
s2.markdown("<div style='text-align:right;font-size:.8rem;opacity:.6'>"
            + " · ".join([f"{STATUS_KO.get(k, k)} {v}" for k, v in cnt.items() if k != "candidate"]
                         + [f"후보 {cnt.get('candidate', 0)}", f"내 메모 {n_memo}"]) + "</div>", unsafe_allow_html=True)

first = first_tab(slug)
sec = s1.segmented_control("화면", ["연구 주제 설정", "찾기", "읽기", "모아보기"], default=first,
                           key="sec", label_visibility="collapsed") or first

# ── 찾기 ─────────────────────────────────────────────────
VERIFY_ICON = {"human": "● 사람 확인", "text": "● 원문 확인", "db2": "◐ DB 2곳", "db1": "○ DB 1곳", "miss": "⚠ 원문에 없음"}


def seed_ui():
    st.caption("① 핵심 논문을 먼저 정하고 ② 그 논문들의 인용 관계를 따라 연관 논문으로 넓힙니다. "
               "관계마다 그 인용이 실제로 있는지 검증 단계를 붙이고, 원문을 본 사람이 최종 확인합니다.")
    seeds = con.execute("SELECT id, title, year, venue, authors, doi, review FROM papers WHERE favorite=1 ORDER BY year").fetchall()
    st.markdown(f"**① 핵심 논문 {len(seeds)}편**")
    if seeds:
        rows = [dict(r, 빼기=False, 저자=(r["authors"] or "").split(";")[0], 검토=r["review"] or "미검토",
                     DOI=f"https://doi.org/{r['doi']}" if r["doi"] else None) for r in seeds]
        se = st.data_editor(rows, key=f"seeds_{slug}", hide_index=True, width="stretch",
                            column_order=["빼기", "title", "year", "저자", "venue", "검토", "DOI"],
                            disabled=["title", "year", "저자", "venue", "검토", "DOI"],
                            column_config={"빼기": st.column_config.CheckboxColumn("빼기", width="small"),
                                           "title": st.column_config.TextColumn("제목", width="large"),
                                           "year": "연도", "venue": "저널",
                                           "DOI": st.column_config.LinkColumn("DOI", display_text="열기")})
        drop = [r["id"] for r in se if r["빼기"]]
        if drop and st.button(f"체크한 {len(drop)}편을 핵심 논문에서 빼기"):
            con.executemany("UPDATE papers SET favorite=0 WHERE id=?", [(i,) for i in drop])
            con.commit()
            st.rerun()
    with st.expander("핵심 논문 추가", expanded=not seeds):
        t_ai, t_known, t_find = st.tabs(["Claude 추천", "아는 논문 입력", "인용 통계로 찾기"])
        with t_ai:
            st.caption("연구 주제와 대화 내용을 Claude 가 읽고, 관찰을 이론으로 번역해 이론 원전·직접 선행연구·인접 분야 연구·"
                       "방법·측정 논문을 추천합니다. 추천마다 OpenAlex 에서 실제로 있는지 확인합니다. 분야 제한이 없습니다.")
            if st.button("연구 주제로 핵심 논문 추천받기", key="suggest", type="primary"):
                with st.spinner("Claude 가 추천하고 OpenAlex 에서 확인하는 중 (1~2분)"):
                    run("scripts/suggest.py", "ask", *P)
            sf = db.HOME / "projects" / slug / "suggest.json"
            sug = json.loads(sf.read_text()) if sf.exists() else []
            if not sug:
                st.caption("아직 추천이 없습니다. '연구 주제 설정'을 채운 뒤 위 버튼을 누르세요.")
            else:
                mark = {"확인됨": "● 확인됨", "확인 필요": "◐ 확인 필요", "못 찾음": "○ 못 찾음"}
                rows = []
                for i, r in enumerate(sug):
                    m = r.get("match") or {}
                    rows.append({"i": i, "핵심": False, "묶음": r["group"], "확인": mark[r["status"]],
                                 "추천": f"{r['first_author']} {r['year']} · {r['title']}",
                                 "찾은 기록": f"{m.get('year')} · {m.get('title')} · {m.get('venue') or ''}" if m else "",
                                 "이유": r["why"], "DOI": m.get("doi")})
                st.caption("● 확인됨 = 제목·연도(±1)·1저자가 일치 · ◐ 확인 필요 = 비슷한 기록은 있으나 판·연도·저자가 다름 · "
                           "○ 못 찾음 = OpenAlex 에 없음 (한국 논문은 DBpia 에서 확인)")
                se = st.data_editor(rows, key=f"sug_{slug}", hide_index=True, width="stretch",
                                    column_order=["핵심", "묶음", "확인", "추천", "찾은 기록", "이유", "DOI"],
                                    disabled=["묶음", "확인", "추천", "찾은 기록", "이유", "DOI"],
                                    column_config={"핵심": st.column_config.CheckboxColumn("핵심", width="small"),
                                                   "추천": st.column_config.TextColumn("추천", width="large"),
                                                   "찾은 기록": st.column_config.TextColumn("OpenAlex 기록", width="large"),
                                                   "이유": st.column_config.TextColumn("왜 필요한가", width="large"),
                                                   "DOI": st.column_config.LinkColumn("DOI", display_text="열기")})
                if st.button("체크한 논문을 핵심 논문으로 등록", key="sug_add"):
                    added, skipped = 0, 0
                    for r in se:
                        m = sug[r["i"]].get("match")
                        if r["핵심"] and m and seedmod.add(con, m["openalex"]):
                            added += 1
                        elif r["핵심"]:
                            skipped += 1
                    st.success(f"{added}편 등록" + (f" · 못 찾은 {skipped}편은 '아는 논문 입력'에 DOI 로 넣으세요" if skipped else ""))
                    st.rerun()
        with t_known:
            lines = st.text_area("제목 또는 DOI 를 한 줄에 하나씩", key="seed_lines", height=110)
            if st.button("찾기", key="seed_find") and lines.strip():
                with st.spinner("OpenAlex 에서 찾는 중"):
                    st.session_state["seed_cands"] = {ln.strip(): seedmod.find(ln) for ln in lines.splitlines() if ln.strip()}
            cands = st.session_state.get("seed_cands", {})
            if cands:
                st.caption("같은 제목이 단행본 재수록·학회 발표본으로 여러 개 나올 수 있습니다. 저자·연도·저널·DOI 를 보고 원 논문을 고르세요.")
            for i, (line, cs) in enumerate(cands.items()):
                lab = {c["openalex"]: f"{c['year']} · {c['title']} — {(c['authors'] or '').split(';')[0]} · {c['venue'] or '출처 없음'} · "
                                      f"{c['doi'] or 'DOI 없음'} (일치 {c['match']})" for c in cs}
                st.radio(line[:90], ["건너뛰기"] + list(lab), key=f"seedpick{i}", format_func=lambda k, lab=lab: lab.get(k, k),
                         index=1 if cs and cs[0]["match"] >= 0.9 and not (len(cs) > 1 and cs[1]["match"] >= 0.9) else 0)
            if cands and st.button("고른 논문을 핵심 논문으로 등록", type="primary"):
                n = 0
                for i in range(len(cands)):
                    w = st.session_state.get(f"seedpick{i}")
                    if w and w != "건너뛰기" and seedmod.add(con, w):
                        n += 1
                st.session_state.pop("seed_cands", None)
                st.success(f"{n}편 등록")
                st.rerun()

        with t_find:
            st.caption("연구 주제 설정의 키워드마다(그리고 첫 키워드와 다음 키워드의 교차로) 가볍게 검색한 뒤, "
                       "흐름마다 공통으로 인용되는 고전 3편과 리뷰 논문을 후보로 보여줍니다. 저자·연도·저널·DOI 를 확인하고 고르세요.")
            if st.button("키워드로 핵심 논문 후보 찾기", key="discover"):
                run("scripts/keypapers.py", "discover", *P)
            # 흐름(키워드·교차 검색)마다 고전 3편씩 — 논문이 많은 흐름이 작은 흐름을 묻지 않게
            kp = db.HOME / "projects" / slug / "keypapers.json"
            streams = json.loads(kp.read_text()).get("streams", {}) if kp.exists() else {}
            cands, seen_ids = [], set()
            for label, lst in streams.items():
                for pid_, n in [x for x in lst if x[0] not in seen_ids][:3]:
                    r = con.execute("SELECT id, title, year, venue, authors, doi, favorite FROM papers WHERE id=?", (pid_,)).fetchone()
                    if r and not r["favorite"]:
                        cands.append(dict(r, kind="고전", flow=label, local_cites=n))
                        seen_ids.add(pid_)
            if not streams:  # 예전 방식으로 계산된 프로젝트
                cands = [dict(r, flow="전체") for r in con.execute(
                    "SELECT id, '고전' AS kind, local_cites, title, year, venue, authors, doi FROM papers "
                    "WHERE favorite=0 AND local_cites IS NOT NULL ORDER BY local_cites DESC LIMIT 15")]
            cands += [dict(r, flow="리뷰") for r in con.execute(
                "SELECT id, '리뷰' AS kind, local_cites, title, year, venue, authors, doi FROM papers "
                "WHERE favorite=0 AND is_review=1 ORDER BY COALESCE(core_links,0) DESC, cited_by DESC LIMIT 8")]
            if not cands:
                st.caption("아직 후보가 없습니다. 위 버튼을 누르세요. (연구 주제 설정에 키워드가 있어야 합니다)")
            else:
                for r in cands:
                    r["핵심으로"] = False
                    r["1저자"] = (r["authors"] or "").split(";")[0]
                ce = st.data_editor(cands, key=f"disc_{slug}", hide_index=True, width="stretch",
                                    column_order=["핵심으로", "flow", "local_cites", "title", "year", "1저자", "venue", "doi"],
                                    disabled=["flow", "kind", "local_cites", "title", "year", "1저자", "venue", "doi"],
                                    column_config={"핵심으로": st.column_config.CheckboxColumn("핵심", width="small"),
                                                   "flow": st.column_config.TextColumn("흐름", help="이 고전을 공통으로 인용한 검색 흐름. 리뷰는 리뷰 논문"),
                                                   "local_cites": st.column_config.NumberColumn(
                                                       "후보 인용", help="그 흐름에서 모은 논문들 중 이 논문을 인용한 수"),
                                                   "title": st.column_config.TextColumn("제목", width="large"),
                                                   "year": "연도", "venue": "저널", "doi": "DOI"})
                if st.button("체크한 논문을 핵심 논문으로 등록", key="disc_add", type="primary"):
                    ids = [r["id"] for r in ce if r["핵심으로"]]
                    con.executemany("UPDATE papers SET favorite=1 WHERE id=?", [(i,) for i in ids])
                    con.commit()
                    st.rerun()

    st.markdown("**② 연관 논문**")
    if st.button("핵심 논문의 참고문헌·인용 논문 모으고 인용 검증", disabled=not seeds,
                 help="OpenAlex·Semantic Scholar 에서 참고문헌(선행)·인용한 논문(후속)·유사 논문을 모으고, 원문이 있으면 참고문헌과 대조합니다"):
        run("scripts/seeds.py", "expand", *P, "--top", "0")
    rows = seedmod.rank(con, 0)
    if not rows:
        st.caption("핵심 논문을 등록하고 위 버튼을 누르면 연관 논문이 여기에 나옵니다.")
        return
    c1, c2 = st.columns([1, 2])
    max_n = max(r["n_seeds"] for r in rows)
    min_n = c1.slider("이어진 핵심 논문 수 ≥", 1, max(2, max_n), min(2, max_n))
    rels = c2.multiselect("관계", ["선행", "후속", "유사"], default=["선행", "후속", "유사"],
                          help="선행: 핵심 논문이 인용한 논문 · 후속: 핵심 논문을 인용한 논문 · 유사: 데이터베이스가 추천한 비슷한 논문")
    shown = [r for r in rows if r["n_seeds"] >= min_n and any(x in r["rels"] for x in rels)]
    st.caption(f"{len(shown)}편 · 인용 검증: " + " · ".join(f"{v} = {db.VERIFY[k]}" for k, v in VERIFY_ICON.items()))
    for r in shown:
        r["읽기"] = False
        r["검증"] = VERIFY_ICON.get(r["verified"], "—")
        r["검토"] = r["review"] or "미검토"
        r["상태"] = STATUS_KO.get(r["status"], r["status"])
    ed = st.data_editor(shown, key=f"rel_{slug}", hide_index=True, width="stretch", height=480,
                        column_order=["읽기", "n_seeds", "rels", "검증", "title", "year", "venue", "검토", "상태"],
                        disabled=["n_seeds", "rels", "검증", "title", "year", "venue", "검토", "상태"],
                        column_config={"읽기": st.column_config.CheckboxColumn("읽기", width="small"),
                                       "n_seeds": st.column_config.NumberColumn("핵심", help="이어진 핵심 논문 수"),
                                       "rels": "관계", "title": st.column_config.TextColumn("제목", width="large"),
                                       "year": "연도", "venue": "저널"})
    if st.button("체크한 논문을 읽을 목록에 넣기", key="rel_add", type="primary"):
        ids = [r["id"] for r in ed if r["읽기"]]
        con.executemany("UPDATE papers SET status='shortlist' WHERE id=? AND status='candidate'", [(i,) for i in ids])
        con.commit()
        st.success(f"{len(ids)}편을 읽을 목록에 넣었습니다. '키워드로 찾기' 탭의 '읽을 목록 원문 받기'로 원문을 받거나 읽기 탭에서 PDF 를 올리세요.")


if sec == "찾기":
    t_seed, t_kw, t_all = st.tabs(["핵심 논문에서 찾기", "키워드로 넓게 찾기 (참고)", "전체 후보"])
    with t_seed:
        seed_ui()
    with t_kw:
        st.caption("핵심 논문이 아직 없을 때 쓰는 길입니다. 주제 키워드로 넓게 모은 뒤 리뷰·고전·최전선·직결로 추립니다.")
        b1, b3, b4 = st.columns(3)
        if b1.button("전 채널 검색", width="stretch", help="연구 주제 설정의 키워드로 OpenAlex·Semantic Scholar·DBpia 검색"):
            run("scripts/fetch_openalex.py", "search", *P)
            run("scripts/fetch_s2.py", "search", *P)
            if db.load_env().get("DBPIA_API_KEY"):
                run("scripts/fetch_dbpia.py", "search", *P)
            else:
                st.info("DBpia 키가 없어 국내 검색은 건너뛰었습니다.")
        if b3.button("읽을 목록 원문 받기", width="stretch", help="무료 공개 원문을 자동으로 받는다. 못 받은 것은 읽기 탭에서 PDF 를 올린다"):
            run("scripts/fulltext.py", "fetch", *P)
        with b4.popover("Google Scholar 결과 가져오기", width="stretch"):
            st.caption("Publish or Perish 에서 Google Scholar 검색 후 CSV 로 저장한 파일")
            up = st.file_uploader("CSV", type="csv", label_visibility="collapsed")
            if up and st.button("가져오기"):
                tmp = db.HOME / "projects" / slug / "export" / "_scholar.csv"
                tmp.write_bytes(up.getvalue())
                run("scripts/import_scholar_csv.py", *P, "--file", str(tmp))

        # ── 읽을 목록 제안 ──
        TIER_HELP = {"리뷰": "연구 지형을 한 번에 보는 리뷰 논문", "고전": "후보 논문들이 가장 많이 인용한, 이 분야가 기대는 논문",
                     "최전선": "최근 3년, 핵심 논문을 이어받아 빠르게 인용되는 논문", "직결": "내 주제를 직접 다룬 논문"}
        picks = [dict(r) for r in con.execute(
            "SELECT id, tier, title, year, venue, local_cites, reason, status, COALESCE(url, 'https://doi.org/'||doi) AS link "
            "FROM papers WHERE tier IS NOT NULL")]
        st.subheader("읽을 목록 제안")
        if not picks:
            st.caption("아직 제안이 없습니다. Claude 에게 연구 방향을 이야기하면 "
                       "리뷰·고전·최전선·직결 네 묶음으로 읽을 논문을 골라 여기에 올립니다.")
        else:
            order = {t: i for i, t in enumerate(db.TIERS)}
            picks.sort(key=lambda r: (order[r["tier"]], -(r["local_cites"] or 0)))
            st.caption(" · ".join(f"**{t}** {TIER_HELP[t]}" for t in db.TIERS))
            for r in picks:
                r["담기"] = r["status"] in ("candidate",)
                r["status"] = STATUS_KO.get(r["status"], r["status"])
            pe = st.data_editor(
                picks, key=f"picks_{slug}", hide_index=True, width="stretch",
                column_order=["담기", "tier", "title", "year", "reason", "local_cites", "status", "link"],
                disabled=["tier", "title", "year", "reason", "local_cites", "status", "link"],
                column_config={"담기": st.column_config.CheckboxColumn("읽기", width="small"),
                               "tier": st.column_config.TextColumn("묶음", width="small"),
                               "title": st.column_config.TextColumn("제목", width="large"), "year": "연도",
                               "reason": st.column_config.TextColumn("고른 이유", width="large"),
                               "local_cites": st.column_config.NumberColumn("후보 인용", help="이 프로젝트 후보 논문 중 이 논문을 인용한 수"),
                               "status": "상태", "link": st.column_config.LinkColumn("링크", display_text="열기")})
            if st.button("체크한 논문을 읽을 목록에 넣기", type="primary"):
                ids = [r["id"] for r in pe if r["담기"]]
                con.executemany("UPDATE papers SET status='shortlist' WHERE id=? AND status='candidate'", [(i,) for i in ids])
                con.commit()
                st.success(f"{len(ids)}편을 읽을 목록에 넣었습니다. 위 ③ 버튼으로 원문을 받으세요.")

    with t_all:
        # ── 전체 후보 ──
        n_all = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        with st.expander(f"전체 후보 {n_all}편 (참고용)", expanded=not picks):
            c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
            q = c1.text_input("제목·초록 검색")
            sts = c2.multiselect("상태", list(KO_STATUS), default=["후보", "읽을 목록", "원문 있음", "분석됨"])
            y_min = c3.number_input("연도 ≥", 1900, 2100, 1900)
            only_fav = c4.checkbox("★만")
            sql = ("SELECT p.id, p.favorite, p.status, p.title, p.year, p.venue, p.local_cites, p.core_links, p.cited_by, p.index_tag,"
                   " p.pdf_path IS NOT NULL AS pdf, (SELECT group_concat(source) FROM sources s WHERE s.paper_id=p.id) AS ch,"
                   " COALESCE(p.url, 'https://doi.org/'||p.doi) AS link FROM papers p WHERE COALESCE(p.year, 9999) >= ?")
            args = [y_min]
            if sts:
                sql += f" AND p.status IN ({','.join('?' * len(sts))})"
                args += [KO_STATUS[x] for x in sts]
            if q:
                sql += " AND (p.title LIKE ? OR p.abstract LIKE ?)"
                args += [f"%{q}%"] * 2
            if only_fav:
                sql += " AND p.favorite=1"
            rows = [dict(r) for r in con.execute(
                sql + " ORDER BY p.favorite DESC, COALESCE(p.local_cites,0) DESC, COALESCE(p.core_links,0) DESC, p.cited_by DESC LIMIT 1000", args)]
            for r in rows:
                r["favorite"] = bool(r["favorite"])
                r["pdf"] = bool(r["pdf"])
                r["status"] = STATUS_KO.get(r["status"], r["status"])
            st.caption("정렬: 후보 인용 → 핵심 연결 → 전체 인용 · ★ = 좋아하는 논문(비슷한 논문 찾기의 기준)")
            edited = st.data_editor(
                rows, key=f"ed_{slug}", hide_index=True, width="stretch", height=520,
                disabled=["id", "title", "year", "venue", "local_cites", "core_links", "cited_by", "index_tag", "pdf", "ch", "link"],
                column_config={
                    "favorite": st.column_config.CheckboxColumn("★", width="small"),
                    "status": st.column_config.SelectboxColumn("상태", options=list(KO_STATUS), width="small"),
                    "title": st.column_config.TextColumn("제목", width="large"),
                    "year": "연도", "venue": "저널",
                    "local_cites": st.column_config.NumberColumn("후보 인용", help="이 프로젝트 후보 논문 중 이 논문을 인용한 수"),
                    "core_links": st.column_config.NumberColumn("핵심 연결", help="이 논문이 인용한 핵심 논문 수 (주제 적합도)"),
                    "cited_by": st.column_config.NumberColumn("전체 인용"),
                    "index_tag": "등재", "ch": "출처", "pdf": st.column_config.CheckboxColumn("원문"),
                    "link": st.column_config.LinkColumn("링크", display_text="열기"),
                })
            if st.button("저장"):
                before = {r["id"]: r for r in rows}
                n = 0
                for r in edited:
                    b_ = before[r["id"]]
                    if r["favorite"] != b_["favorite"] or r["status"] != b_["status"]:
                        con.execute("UPDATE papers SET favorite=?, status=? WHERE id=?",
                                    (int(r["favorite"]), KO_STATUS.get(r["status"], r["status"]), r["id"]))
                        n += 1
                con.commit()
                st.success(f"{n}건 저장")
        with st.expander("초록 보기"):
            pid = st.number_input("논문 id", min_value=0, step=1, key="abs_id")
            r = con.execute("SELECT title, authors, abstract FROM papers WHERE id=?", (pid,)).fetchone()
            if r:
                st.markdown(f"**{r['title']}**  \n{r['authors'] or ''}\n\n{r['abstract'] or '(초록 없음)'}")

# ── 읽기 ─────────────────────────────────────────────────
def paper_list():
    """읽기 화면 왼쪽 고정 목록. 분석됨 / 원문 있음 / 원문 없음으로 묶고, 묶음 안에서 핵심 논문(★)이 위."""
    rows = con.execute("SELECT id, title, year, authors, status, favorite FROM papers "
                       "WHERE status IN ('shortlist','fulltext','analyzed') OR favorite=1").fetchall()
    if not rows:
        return None
    groups = {"analyzed": "분석됨", "fulltext": "원문 있음"}
    rows = sorted(rows, key=lambda r: (list(groups).index(r["status"]) if r["status"] in groups else 2,
                                       -r["favorite"], -(r["year"] or 0)))
    with st.sidebar:
        # 목록 항목은 버튼이지만 글줄처럼 보이게: 왼쪽 정렬, 테두리 없음, 선택한 줄만 배경
        st.markdown("<style>section[data-testid=stSidebar] .stButton button{justify-content:flex-start;"
                    "text-align:left;width:100%;padding:.3rem .5rem;min-height:0}"
                    "section[data-testid=stSidebar] .stButton button[kind=secondary]{border:none;"
                    "background:rgba(255,75,75,.1)}"
                    "section[data-testid=stSidebar] [data-testid=stVerticalBlock]{gap:.15rem}"
                    "section[data-testid=stSidebar] [data-testid=stCaptionContainer]{margin:.9rem 0 .2rem .5rem}</style>", unsafe_allow_html=True)
        st.markdown("**논문**")
        q = st.text_input("찾기", key="rd_q", placeholder="제목·저자", label_visibility="collapsed").lower()
        shown = [r for r in rows if not q or q in (r["title"] + " " + (r["authors"] or "")).lower()]
        if not shown:
            st.caption("맞는 논문이 없습니다.")
            return None
        if st.session_state.get("rd") not in {r["id"] for r in shown}:
            st.session_state["rd"] = shown[0]["id"]
        def label(r):
            parts = [w for w in (r["authors"] or "").split(";")[0].replace(".", " ").split() if len(w) > 1]
            first = parts[-1:] or [""]  # 끝의 이니셜(R, J.)은 건너뛴다
            t = r["title"] if len(r["title"]) <= 48 else r["title"][:46] + "…"
            return f"{'★ ' if r['favorite'] else ''}{first[0]} {r['year'] or ''} — {t}"
        def pick(i):
            st.session_state["rd"] = i
        for g in ["analyzed", "fulltext", None]:
            items = [r for r in shown if (r["status"] if r["status"] in groups else None) == g]
            if not items:
                continue
            st.caption(f"{groups.get(g, '원문 없음')} {len(items)}")
            for r in items:
                st.button(label(r), key=f"rd_{r['id']}", help=r["title"], on_click=pick, args=(r["id"],),
                          type="secondary" if r["id"] == st.session_state["rd"] else "tertiary")
        if any(r["favorite"] for r in shown):
            st.caption("★ 핵심 논문")
        return st.session_state["rd"]


def words_in(page, rect):
    """글자 중심이 영역 안에 있는 단어만 (윗줄·아랫줄 조각 제외). [(Rect, 단어)] 읽는 순서."""
    import fitz
    out = []
    for w in sorted(page.get_text("words"), key=lambda w: (w[5], w[6], w[7])):  # 문단·줄·단어 순서
        r = fitz.Rect(w[:4])
        if rect.contains(fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)):
            out.append((r, w[4]))
    return out


@st.cache_data(show_spinner=False, max_entries=64)
def render_page(path, mtime, pno, zoom, quotes, find, memos=()):
    """PDF 한 쪽을 PNG 로. 에이전트 인용은 옅은 밑줄, 검색어는 하늘색, 내 메모는 의미별 색 형광."""
    import fitz
    with fitz.open(path) as doc:
        page = doc[pno - 1]
        for q in quotes:
            rects = page.search_for(q) or page.search_for(q[:60]) or page.search_for(q[-50:])
            if rects:
                a = page.add_underline_annot(rects)
                a.set_colors(stroke=(0.85, 0.65, 0.1))
                a.update()
        for x0, y0, x1, y1, rgb in memos:
            rect = fitz.Rect(x0, y0, x1, y1)
            words = [r for r, _ in words_in(page, rect)]
            if words:
                a = page.add_highlight_annot(words)
                a.set_colors(stroke=rgb)
            else:  # 그림 영역
                a = page.add_rect_annot(rect)
                a.set_colors(stroke=rgb, fill=rgb)
                a.set_opacity(0.3)
            a.update()
        if find:
            for r in page.search_for(find):
                a = page.add_highlight_annot(r)
                a.set_colors(stroke=(0.55, 0.8, 1.0))
                a.update()
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), annots=True).tobytes("png")


def goto(key, n):
    st.session_state[key] = n


@st.cache_data(show_spinner=False, max_entries=256)
def fig_png(slug_, fid, sig):
    """원문 그림·표 잘라낸 PNG. sig(좌표·회전)가 바뀌면 다시 그린다."""
    return figures.crop_png(db.connect(slug_), slug_, fid)


def show_fig(f, PG, key, width="stretch"):
    st.image(fig_png(slug, f["id"], (f["x0"], f["y0"], f["x1"], f["y1"], f["rot"])), width=width)
    c1, c2 = st.columns([5, 1], vertical_alignment="center")
    c1.caption(f"**{f['label']}** · {f['note'] or f['caption'][:120]}")
    c2.button(f"p.{f['page']}", key=key, on_click=goto, args=(PG, f["page"]), help="왼쪽 PDF 를 이 쪽으로")


def glance(pid, PG, notes, npg):
    """한눈에 보기: 연구 모형 · 논증 흐름 · 원문 그림·표 · 절 목차."""
    flows = {r["step"]: r for r in con.execute("SELECT * FROM flow WHERE paper_id=?", (pid,))}
    figs = con.execute("SELECT * FROM figures WHERE paper_id=? ORDER BY page, id", (pid,)).fetchall()
    dot = diagram.to_dot(con, pid)
    outl = diagram.outline(con, pid)
    one = next((n["content"] for n in notes if n["section"] == "한 줄 요약"), None)
    if not (flows or figs or dot or outl or one):
        return
    by_label = {f["label"]: f for f in figs}
    with st.expander("한눈에 보기", expanded=True):
        if one:
            st.markdown(f"<div style='font-size:15px;font-weight:600;line-height:1.5'>{html.escape(one)}</div>",
                        unsafe_allow_html=True)
        t_model, t_flow, t_figs, t_toc = st.tabs(["연구 모형", "논증 흐름", f"원문 그림·표 {len(figs)}", "절 목차"])
        with t_model:
            model_figs = [f for f in figs if f["role"] == "연구 모형"]
            if model_figs and dot:
                c1, c2 = st.columns([3, 2], gap="large")
                with c1:
                    st.caption("원문 그림")
                    for f in model_figs:
                        show_fig(f, PG, f"m{f['id']}")
                with c2:
                    st.caption("가설 판정 반영 · 초록 지지 · 주황 부분지지 · 회색 기각 · 점선 조절·무효과")
                    st.graphviz_chart(dot, width="stretch")
            elif model_figs:
                for f in model_figs:
                    show_fig(f, PG, f"m{f['id']}")
            elif dot:
                st.graphviz_chart(dot, width="stretch")
            else:
                st.info("원문에 연구 모형 그림이 없습니다 (리뷰·질적 연구일 수 있음). 논증 흐름과 과정 그림을 참고하세요.")
                for f in [f for f in figs if f["role"] == "과정"][:1]:
                    show_fig(f, PG, f"mp{f['id']}")
        with t_flow:
            if not flows:
                st.caption("아직 논증 흐름이 없습니다. researcher 에이전트가 채웁니다.")
            for i, step in enumerate(db.FLOW):
                r = flows.get(step)
                if not r:
                    continue
                phase, color = diagram.PHASE[step]
                a, b, c = st.columns([1.5, 8, 1.2], vertical_alignment="center")
                a.markdown(f"<div style='border-left:4px solid {color};padding:2px 0 2px 8px;font-size:12px;line-height:1.2'>"
                           f"<span style='color:{color};font-weight:700'>{phase}</span><br>{step}</div>",
                           unsafe_allow_html=True)
                with b:
                    st.markdown(f"<div style='font-size:14px;line-height:1.5'>{html.escape(r['claim'])}</div>",
                                unsafe_allow_html=True)
                    if r["fig"] and r["fig"] in by_label:
                        with st.popover(f"{r['fig']} 보기"):
                            show_fig(by_label[r["fig"]], PG, f"pf{r['id']}")
                if r["page"]:
                    c.button(f"p.{r['page']}", key=f"fl{r['id']}", on_click=goto, args=(PG, r["page"]))
        with t_figs:
            roles = st.pills("역할", ["연구 모형", "주요 결과", "과정", "기타"], selection_mode="multi",
                             default=["연구 모형", "주요 결과", "과정"], key=f"roles{pid}")
            shown = [f for f in figs if f["role"] in (roles or [])]
            cols = st.columns(2, gap="large")
            for i, f in enumerate(shown):
                with cols[i % 2]:
                    st.markdown(f"<span style='font-size:11px;color:#5b6474'>{f['role']}</span>", unsafe_allow_html=True)
                    show_fig(f, PG, f"g{f['id']}")
            if not shown:
                st.caption("해당 역할의 그림·표가 없습니다.")
        with t_toc:
            for i, o in enumerate(outl):
                a, b = st.columns([1.2, 9], vertical_alignment="center")
                a.button(f"p.{o['page_start']}", key=f"ol{pid}_{i}", on_click=goto, args=(PG, o["page_start"]), width="stretch")
                b.markdown(f"<div style='font-size:13px'><b>{html.escape(o['heading'])}</b>"
                           f"<span style='color:#5b6474'> · {html.escape(o['summary'] or '')}</span></div>",
                           unsafe_allow_html=True)


def memo_form(pid, pdf, PG):
    """드래그로 고른 영역에 메모 달기."""
    pend = st.session_state.get(f"pend_{pid}")
    if not pend:
        return
    import fitz
    with fitz.open(pdf) as doc:
        page = doc[pend["page"] - 1]
        W, H = page.rect.width, page.rect.height
        rect = fitz.Rect(pend["x0"] * W, pend["y0"] * H, pend["x1"] * W, pend["y1"] * H)
        excerpt = " ".join(w for _, w in words_in(page, rect))
    with st.container(border=True):
        st.markdown(f"**p.{pend['page']} 선택한 부분**")
        st.caption(f"“{excerpt[:400]}”" if excerpt else "글자가 없는 영역 (그림·표)")
        color = st.radio("표시", list(db.MEMO_COLORS), horizontal=True, key=f"mc_{pid}")
        memo = st.text_area("내 생각", key=f"mt_{pid}", placeholder="이 부분에 대한 생각, 내 연구와의 연결, 반론 …")
        a, b = st.columns(2)
        if a.button("메모 저장", type="primary", width="stretch"):
            con.execute("INSERT INTO memos(paper_id,page,x0,y0,x1,y1,color,excerpt,memo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (pid, pend["page"], rect.x0, rect.y0, rect.x1, rect.y1, color, excerpt, memo, db.now()))
            con.commit()
            del st.session_state[f"pend_{pid}"]
            st.session_state.pop(f"mt_{pid}", None)
            st.rerun()
        if b.button("취소", width="stretch"):
            del st.session_state[f"pend_{pid}"]
            st.rerun()


def memo_list(memos, PG=None, show_paper=False, k="r"):
    for m in memos:
        hexc = db.MEMO_COLORS.get(m["color"], db.MEMO_COLORS["중요"])[1]
        head = f"<b style='color:{hexc}'>■ {html.escape(m['color'])}</b> · p.{m['page']}"
        if show_paper:
            head += f" · <span style='color:#5b6474'>#{m['paper_id']} {html.escape(m['title'][:70])}</span>"
        st.markdown(f"<div style='font-size:13px;line-height:1.45;border-left:3px solid {hexc};padding-left:8px'>{head}<br>"
                    f"<span style='color:#5b6474'>“{html.escape((m['excerpt'] or '(그림 영역)')[:220])}”</span><br>"
                    f"{html.escape(m['memo'] or '')}</div>", unsafe_allow_html=True)
        a, b, _ = st.columns([1, 1, 3])
        if PG:
            a.button("이 쪽 보기", key=f"{k}mg{m['id']}", on_click=goto, args=(PG, m["page"]), width="stretch")
        if b.button("삭제", key=f"{k}md{m['id']}", width="stretch"):
            con.execute("DELETE FROM memos WHERE id=?", (m["id"],))
            con.commit()
            st.rerun()


def set_edge_human(rowid):
    con.execute("UPDATE edges SET verified='human' WHERE rowid=?", (rowid,))
    con.commit()


def set_note_checked(nid):
    con.execute("UPDATE notes SET checked=? WHERE id=?", (int(st.session_state[f"ck{nid}"]), nid))
    con.commit()


def review_box(pid, p):
    """사람 검토: 진위 체크 + 검토 결과 + 인용 관계 확인."""
    label = p["review"] or "미검토"
    with st.expander(f"검토 · {label}" + (f" · {p['reviewed_at'][:10]}" if p["reviewed_at"] else ""), expanded=(label == "미검토")):
        left, right = st.columns([1, 1], gap="large")
        with left:
            st.markdown("**진위 확인**")
            tc = p["title_check"]
            st.markdown(("✓" if tc == "일치" else "⚠" if tc in ("불일치", "일치·원고본") else "·")
                        + f" PDF 첫 쪽 제목 대조: {tc or '원문 없음'} (자동)")
            if tc == "일치·원고본":
                st.caption("워킹페이퍼·프리프린트 등 출판 전 원고입니다. 쪽 번호와 문장이 출판본과 다를 수 있어, 인용 전에 출판본을 확인하세요.")
            if p["doi"]:
                st.markdown(f"· [DOI 열어 출판사 페이지와 서지 대조](https://doi.org/{p['doi']})")
            else:
                st.markdown("⚠ DOI 없음 — 출판 여부를 직접 확인")
            st.markdown(f"· 저널: {p['venue'] or '기록 없음'} — 등재(SSCI/SCI/KCI) 여부 확인")
            choice = st.radio("검토 결과", db.REVIEW, index=db.REVIEW.index(label), horizontal=True, key=f"rv{pid}")
            note = st.text_input("검토 메모", p["review_note"] or "", key=f"rvn{pid}",
                                 placeholder="예: 원문 확인. 2019 단행본 재수록본이 아닌 2006 ETP 원 논문")
            if st.button("검토 저장", key=f"rvs{pid}", type="primary"):
                con.execute("UPDATE papers SET review=?, review_note=?, reviewed_at=? WHERE id=?",
                            (None if choice == "미검토" else choice, note or None, db.now(), pid))
                con.commit()
                st.rerun()
        with right:
            seeds = {r[0] for r in con.execute("SELECT id FROM papers WHERE favorite=1")}
            rel = con.execute(
                "SELECT e.rowid AS rid, e.from_id, e.to_id, e.verified, e.evidence, e.sources, a.title AS ft, b.title AS tt "
                "FROM edges e JOIN papers a ON a.id=e.from_id JOIN papers b ON b.id=e.to_id "
                "WHERE e.kind='cites' AND ? IN (e.from_id, e.to_id)", (pid,)).fetchall()
            core = [r for r in rel if (r["from_id"] in seeds) != (r["to_id"] in seeds) or pid in seeds]
            st.markdown(f"**인용 관계** · 핵심 논문과 {sum(1 for r in rel if (r['to_id'] if r['from_id'] == pid else r['from_id']) in seeds)}건")
            own = [r for r in rel if r["from_id"] == pid]
            if own:
                cnt = {k: sum(1 for r in own if r["verified"] == k) for k in db.VERIFY}
                st.caption("이 논문의 참고문헌 대조: " + " · ".join(f"{db.VERIFY[k]} {v}" for k, v in cnt.items() if v))
            for r in sorted(rel, key=lambda r: (r["verified"] != "miss", -((r["to_id"] if r["from_id"] == pid else r["from_id"]) in seeds)))[:40]:
                other_seed = (r["to_id"] if r["from_id"] == pid else r["from_id"]) in seeds
                if not other_seed and r["verified"] != "miss":
                    continue
                arrow = f"→ {r['tt'][:55]}" if r["from_id"] == pid else f"← {r['ft'][:55]}"
                a, b = st.columns([5, 1], vertical_alignment="center")
                a.markdown(f"<div style='font-size:12px'>{'★ ' if other_seed else ''}{html.escape(arrow)}<br>"
                           f"<span style='color:#5b6474'>{VERIFY_ICON.get(r['verified'], '—')}"
                           + (f" · “{html.escape(r['evidence'][:90])}”" if r["evidence"] else "")
                           + (f" · {r['sources']}" if r["sources"] else "") + "</span></div>", unsafe_allow_html=True)
                if r["verified"] != "human":
                    b.button("확인", key=f"eh{r['rid']}", on_click=set_edge_human, args=(r["rid"],),
                             help="원문 참고문헌에서 이 인용을 직접 확인했으면 누릅니다 (사람 확인으로 표시)")
            st.caption("→ 이 논문이 인용 · ← 이 논문을 인용 · ★ 핵심 논문 · ⚠ 원문 참고문헌에서 못 찾은 것은 직접 확인이 필요합니다")


def reader(pid, p, ft):
    pages = json.loads(ft["pages"])
    npg = len(pages)
    notes = con.execute("SELECT * FROM notes WHERE paper_id=? ORDER BY id", (pid,)).fetchall()
    hyps = con.execute("SELECT * FROM hypotheses WHERE paper_id=? ORDER BY id", (pid,)).fetchall()
    vars_ = con.execute("SELECT * FROM variables WHERE paper_id=? ORDER BY id", (pid,)).fetchall()
    memos = con.execute("SELECT * FROM memos WHERE paper_id=? ORDER BY page, id", (pid,)).fetchall()
    PG = f"pg_{pid}"
    st.session_state.setdefault(PG, 1)
    glance(pid, PG, notes, npg)

    left, right = st.columns([11, 9], gap="medium")

    # 왼쪽: PDF
    with left:
        c1, c2, c3, c4 = st.columns([1, 2, 1, 3])
        c1.button("◀", on_click=goto, args=(PG, max(1, st.session_state[PG] - 1)), key="prev", width="stretch")
        c2.number_input("쪽", 1, npg, key=PG, label_visibility="collapsed")
        c3.button("▶", on_click=goto, args=(PG, min(npg, st.session_state[PG] + 1)), key="next", width="stretch")
        find = c4.text_input("원문 검색", key=f"find{pid}", placeholder="원문 검색", label_visibility="collapsed")
        if find:
            hits = [i for i, t in enumerate(pages, 1) if find.lower() in t.lower()]
            if hits:
                hc = st.columns(min(len(hits), 12) + 1)
                hc[0].caption(f"{len(hits)}쪽")
                for i, h in enumerate(hits[:12], 1):
                    hc[i].button(str(h), key=f"hit{h}", on_click=goto, args=(PG, h))
            else:
                st.caption("결과 없음")
        pg = st.session_state[PG]
        quotes = tuple(n["quote"] for n in notes if n["quote"] and n["page"] == pg)
        my = tuple((m["x0"], m["y0"], m["x1"], m["y1"], db.MEMO_COLORS.get(m["color"], db.MEMO_COLORS["중요"])[0])
                   for m in memos if m["page"] == pg)
        pdf = db.HOME / "projects" / slug / p["pdf_path"]
        if pdf.exists():
            memo_form(pid, pdf, PG)
            st.caption("드래그해서 영역을 고르면 형광펜 메모를 남길 수 있습니다 · 밑줄 = 에이전트 분석 인용")
            png = render_page(str(pdf), pdf.stat().st_mtime, pg, 2.0, quotes, find, my)
            with st.container(height=900, border=True):
                sel = highlighter(img="data:image/png;base64," + base64.b64encode(png).decode(), key=f"hl_{pid}_{pg}", default=None)
            if sel and sel.get("nonce") != st.session_state.get(f"nonce_{pid}"):
                st.session_state[f"nonce_{pid}"] = sel["nonce"]
                st.session_state[f"pend_{pid}"] = {"page": pg, **{k: sel[k] for k in ("x0", "y0", "x1", "y1")}}
                st.rerun()
        else:
            with st.container(height=900, border=True):
                st.text(pages[pg - 1])
        with st.expander(f"p.{pg} 텍스트 (복사용)"):
            st.code(pages[pg - 1], language=None, wrap_lines=True)

    # 오른쪽: 분석
    with right:
        by = {}
        for n in notes:
            by.setdefault(n["section"], []).append(n)
        done = sum(1 for s_ in db.SECTIONS if s_ in by)
        st.progress(done / len(db.SECTIONS), text=f"분석 {done}/{len(db.SECTIONS)} 항목 · 가설 {len(hyps)} · 변수 {len(vars_)}")
        with st.container(height=900, border=True):
            with st.expander(f"내 메모 {len(memos)}", expanded=bool(memos)):
                if memos:
                    memo_list(memos, PG)
                else:
                    st.caption("왼쪽 PDF 에서 드래그하면 여기에 쌓입니다.")
            if "한 줄 요약" in by:
                st.info(by["한 줄 요약"][0]["content"])
            if hyps:
                st.markdown("**가설**")
                st.dataframe([{"": h["code"], "가설": h["statement"], "결과": h["result"], "통계": h["stats"], "p": h["page"]}
                              for h in hyps], hide_index=True, width="stretch")
            if vars_:
                st.markdown("**변수·측정**")
                st.dataframe([{"역할": v["role"], "변수": v["name"], "척도 출처": v["source"], "문항": v["items"],
                               "α": v["alpha"], "p": v["page"]} for v in vars_], hide_index=True, width="stretch")
            for sec in db.SECTIONS:
                if sec == "한 줄 요약" and sec in by:
                    continue
                items = by.get(sec, [])
                with st.expander(f"{sec}" + ("" if items else "  · 미작성"), expanded=bool(items) and not sec.startswith("인용")):
                    for n in items:
                        st.markdown(n["content"])
                        if n["quote"]:
                            b1, b2 = st.columns([10, 2])
                            mark = {1: "✓ 원문 대조", 0: "⚠ 원문에서 못 찾음"}.get(n["quote_ok"], "")
                            b1.caption(f"“{n['quote']}” {mark}")
                            b1.checkbox("검토 확인", value=bool(n["checked"]), key=f"ck{n['id']}",
                                        on_change=set_note_checked, args=(n["id"],))
                            b2.button(f"p.{n['page']}", key=f"go{n['id']}", on_click=goto, args=(PG, n["page"]),
                                      help="왼쪽 PDF 를 이 쪽으로")
                        if st.button("✕", key=f"del{n['id']}", help="노트 삭제"):
                            con.execute("DELETE FROM notes WHERE id=?", (n["id"],))
                            con.commit()
                            st.rerun()
        with st.expander("노트 추가"):
            sec = st.selectbox("항목", db.SECTIONS, key="nsec")
            content = st.text_area("내용 (요약·해석)", key="ncontent")
            quote = st.text_area("원문 인용 (복사용 텍스트에서 그대로)", key="nquote")
            qpage = st.number_input("인용 쪽", 1, npg, st.session_state[PG], key="nqp")
            if st.button("노트 저장", type="primary") and content:
                con.execute("INSERT INTO notes(paper_id,section,content,quote,page,created_at) VALUES(?,?,?,?,?,?)",
                            (pid, sec, content, quote or None, qpage if quote else None, db.now()))
                con.execute("UPDATE papers SET status='analyzed' WHERE id=?", (pid,))
                con.commit()
                st.rerun()



if sec == "읽기":
    pid = paper_list()
    if pid is None:
        st.info("'찾기'에서 읽을 논문을 읽을 목록에 넣으면 여기 왼쪽 목록에 나옵니다.")
    else:
        p = con.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
        link = f"https://doi.org/{p['doi']}" if p["doi"] else p["url"]
        st.markdown(f"#### {p['title']}\n{p['authors'] or ''} · {p['year']} · *{p['venue'] or ''}* · 인용 {p['cited_by']}"
                    + (f" · [원문 페이지]({link})" if link else ""))
        review_box(pid, p)
        ft = con.execute("SELECT pages FROM fulltext WHERE paper_id=?", (pid,)).fetchone()
        if not ft:
            st.warning("원문 없음. 도서관에서 받은 PDF 를 올리세요.")
            f = st.file_uploader("PDF", type="pdf", key=f"pdf{pid}")
            if f and st.button("등록"):
                tmp = db.HOME / "projects" / slug / "export" / "_upload.pdf"
                tmp.write_bytes(f.getvalue())
                run("scripts/fulltext.py", "attach", *P, "--paper", str(pid), "--file", str(tmp))
                tmp.unlink(missing_ok=True)
        else:
            reader(pid, p, ft)

        rel = con.execute(
            "SELECT e.kind, p.id, p.title, p.year, p.cited_by FROM edges e JOIN papers p"
            " ON p.id = CASE WHEN e.from_id=? THEN e.to_id ELSE e.from_id END"
            " WHERE ? IN (e.from_id, e.to_id) ORDER BY p.cited_by DESC LIMIT 200", (pid, pid)).fetchall()
        if rel:
            with st.expander(f"연결된 논문 {len(rel)}편"):
                st.dataframe([dict(r) for r in rel], hide_index=True, width="stretch")

# ── 모아보기 ─────────────────────────────────────────────
if sec == "모아보기":
    st.subheader("내 메모")
    colors = st.pills("표시", list(db.MEMO_COLORS), selection_mode="multi", default=list(db.MEMO_COLORS), key="mm_colors")
    allm = [m for m in con.execute("SELECT m.*, p.title FROM memos m JOIN papers p ON p.id=m.paper_id ORDER BY m.paper_id, m.page, m.id")
            if m["color"] in (colors or [])]
    if allm:
        memo_list(allm, show_paper=True, k="all")
    else:
        st.caption("읽기 탭에서 PDF 를 드래그해 남긴 메모가 논문을 가로질러 여기에 모입니다.")

    st.divider()
    st.subheader("연구 아이디어 (갭·가설)")
    files = sorted((db.HOME / "projects" / slug / "gaps").glob("*.md"))
    n_an = con.execute("SELECT COUNT(*) FROM papers WHERE status='analyzed'").fetchone()[0]
    if not files:
        st.caption(f"분석한 논문이 15편 이상 쌓이면 researcher 에이전트가 갭과 가설 후보를 여기에 정리합니다. 지금 {n_an}편. "
                   "내 메모도 함께 반영합니다.")
    for f in files:
        with st.expander(f.stem, expanded=True):
            st.markdown(f.read_text())

    st.divider()
    st.subheader("보고서")
    st.caption("논문별 한눈에 보기·분석·내 메모를 HTML 한 파일로 만듭니다. Claude 에게 '보고서 게시해줘'라고 하면 아티팩트로 올립니다.")
    if st.button("HTML 보고서 만들기"):
        run("scripts/export_html.py", *P)

# ── 연구 주제 설정 ───────────────────────────────────────
BRIEF_FIELDS = [
    ("분야", "예: 창업학"),
    ("주제 씨앗", "영문 검색 키워드, 쉼표로 구분 (5~10개)"),
    ("국문 키워드", "DBpia 등 국내 검색용, 쉼표로 구분"),
    ("제외 키워드", "제목에 이 단어가 있으면 수집하지 않음"),
    ("연도 범위", "예: 2016–2026"),
    ("검색 분야", "키워드 단독 검색을 이 분야로 제한. 비우면 경영·의사결정과학·경제·심리·사회과학. "
               "공학·컴퓨터과학·의학 등을 더하거나 '전체'. 두 키워드를 묶은 교차 검색은 늘 전체 분야"),
    ("연구 유형", "양적 / 질적 / 혼합 / 미정"),
    ("대상 저널", "투고 목표 저널. 비우면 수집 결과로 후보를 제안"),
    ("이론 후보", "쓰고 싶은 이론"),
    ("지도교수 지침", "받은 방향이 있으면"),
    ("목표 노트 수", "분석할 논문 수 목표"),
]
BRIEF_SYS = """당신은 사회과학(SSCI/SCI) 논문을 준비하는 연구자의 연구 주제 정리를 돕는 지도 선배입니다.
사용자는 생각이 덜 정리된 채로 대충 말합니다. 대화하면서 연구 주제 칸을 채워 갑니다.
- 한국어 존댓말. 답은 짧게. 한 번에 질문은 1~2개만, 고르기 쉽게 예시를 붙입니다.
- 사용자의 말에서 알 수 있는 칸은 바로 채우고, 추측으로 채운 것은 reply 에서 '이렇게 넣어봤다'고 알립니다.
- 주제 씨앗은 학술 DB 검색에 쓸 영문 키워드 5~10개(쉼표 구분), 국문 키워드는 국내 DB 검색용.
  첫 키워드는 연구의 중심 개념이나 방법으로 둡니다. 첫 키워드와 다음 키워드들을 묶은 교차 검색이 자동으로 돕니다.
- 검색 분야: 기본은 '경영, 의사결정과학, 경제, 심리, 사회과학'. 방법이나 데이터가 공학·컴퓨터과학·의학 쪽에서 왔고
  그쪽 논문도 봐야 하면 더합니다(예: '경영, 의사결정과학, 경제, 공학, 컴퓨터과학'). 이유를 reply 에 한 줄로 알립니다.
- fields 에는 이번에 새로 채우거나 고칠 칸만 넣습니다. 바꿀 게 없으면 빈 객체.
- 칸이 거의 다 찼으면 '찾기' 탭에서 핵심 논문을 정하러 가자고 안내합니다."""


def brief_chat(history, cur):
    """대화 기록과 지금 칸 값을 Claude(사용자 구독의 claude CLI)에 넘겨 답과 칸 제안을 받는다."""
    keys = ["연구 주제"] + [k for k, _ in BRIEF_FIELDS]
    schema = {"type": "object", "required": ["reply", "fields"], "properties": {
        "reply": {"type": "string"},
        "fields": {"type": "object", "additionalProperties": False, "properties": {k: {"type": "string"} for k in keys}}}}
    talk = "\n".join(f"{'사용자' if m['role'] == 'user' else '나'}: {m['content']}" for m in history)
    prompt = f"지금 칸 값:\n{json.dumps(cur, ensure_ascii=False)}\n\n대화:\n{talk}"
    try:
        r = subprocess.run(["claude", "-p", prompt, "--system-prompt", BRIEF_SYS, "--tools", "",
                            "--no-session-persistence", "--model", "claude-opus-5-5", "--output-format", "json",
                            "--json-schema", json.dumps(schema, ensure_ascii=False)],
                           capture_output=True, text=True, timeout=180)
        out = json.loads(r.stdout)["structured_output"]
        return out["reply"], {k: v for k, v in out["fields"].items() if k in keys}
    except FileNotFoundError:
        return "claude 명령을 찾지 못했습니다. Claude Code 가 설치된 컴퓨터에서 화면을 여세요.", {}
    except Exception as e:  # 시간 초과·로그인 만료 등
        return f"답을 받지 못했습니다. 잠시 뒤 다시 보내 주세요. ({type(e).__name__})", {}


if sec == "연구 주제 설정":
    bf = db.HOME / "projects" / slug / "brief.md"
    chat_f = db.HOME / "projects" / slug / "brief_chat.json"
    title = bf.read_text().splitlines()[0].lstrip("# ").strip()
    cur = db.read_brief(slug)
    hints = dict(BRIEF_FIELDS)
    fk = lambda k: f"bf_{slug}_{k}"  # noqa: E731  칸 위젯 key

    def save_brief():
        v = lambda k: " ".join(st.session_state[fk(k)].split())  # noqa: E731
        bf.write_text(f"# {v('연구 주제')}\n" + "".join(f"- {k}: {v(k)}\n" for k, _ in BRIEF_FIELDS))
    if fk("연구 주제") not in st.session_state:  # 처음 열 때 brief.md 값으로. 템플릿 자리표시는 빈칸
        st.session_state[fk("연구 주제")] = "" if title.startswith("{") else title
        for k, hint in BRIEF_FIELDS:
            v = cur.get(k, "")
            st.session_state[fk(k)] = "" if v.startswith("(") or v == hint else v
    history = json.loads(chat_f.read_text()) if chat_f.exists() else []

    talk, form = st.columns([1, 1], gap="large")
    with talk:
        st.markdown("**대화로 정하기**")
        box = st.container(height=560)
        with box:
            with st.chat_message("assistant"):
                st.markdown("어떤 게 궁금하신지 편하게 말씀해 주세요. 정리가 안 됐어도 괜찮습니다. "
                            "예: *'애 키우면서 창업한 엄마들이 왜 그만두는지 궁금해요'*\n\n"
                            "이야기하면서 오른쪽 칸을 같이 채워 가겠습니다.")
            for m in history:
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
        msg = st.chat_input("생각나는 대로 적어 주세요")
        if msg:
            history.append({"role": "user", "content": msg})
            with box:
                with st.chat_message("user"):
                    st.markdown(msg)
                with st.chat_message("assistant"), st.spinner("생각하는 중… (10~30초)"):
                    now = {"연구 주제": st.session_state[fk("연구 주제")],
                           **{k: st.session_state[fk(k)] for k, _ in BRIEF_FIELDS}}
                    reply, fields = brief_chat(history, now)
            if fields:
                reply += "\n\n✎ 채운 칸: " + ", ".join(fields)
            history.append({"role": "assistant", "content": reply})
            chat_f.write_text(json.dumps(history, ensure_ascii=False, indent=1))
            for k, v in fields.items():  # 칸 위젯이 그려지기 전이라 바로 바꿀 수 있다
                st.session_state[fk(k)] = v
            if fields:
                save_brief()  # 대화로 채운 칸은 바로 저장
            st.rerun()
        if history and st.button("대화 처음부터", type="tertiary"):
            chat_f.unlink()
            st.rerun()

    with form:
        st.markdown("**연구 주제 정리**")
        st.caption("에이전트가 논문을 검색하고 분석할 때 기준으로 씁니다. 대화로 채운 칸은 바로 저장되고, 직접 고친 뒤에는 저장을 누르세요.")
        with st.form("brief", border=False):
            st.text_input("연구 주제 (한 줄)", key=fk("연구 주제"))
            for k, hint in BRIEF_FIELDS:
                (st.text_area if k in ("주제 씨앗", "국문 키워드", "지도교수 지침") else st.text_input)(
                    k, key=fk(k), help=hint, placeholder=hint)
            if st.form_submit_button("저장", type="primary"):
                save_brief()
                st.success("저장했습니다. 다음 검색부터 반영됩니다.")
