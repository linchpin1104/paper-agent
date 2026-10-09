---
name: analyze
description: 읽을 목록 중 원문이 있는 논문을 researcher 에이전트로 심층 분석한다. 논증 흐름, 원문 그림·표, 20개 항목, 가설·변수를 원문 인용과 쪽수로 정리한다. 인자가 "갭"이면 쌓인 분석과 내 메모로 연구 갭·가설을 찾는다.
argument-hint: "[논문 id 여러 개 | 갭]"
allowed-tools: Bash("${CLAUDE_PLUGIN_ROOT}/bin/pa" *), Bash(ls *), Bash(sqlite3 *)
---

# 심층 분석

아래의 `pa` 는 `"${CLAUDE_PLUGIN_ROOT}/bin/pa"` 를 줄인 것이다.

1. 프로젝트를 확인한다: `ls projects`. 여럿이면 어느 것인지 묻는다.
2. 인자가 "갭"이면 5번으로 간다.
3. 대상을 정한다.
   - 인자로 id 를 주면 그 논문만 한다.
   - 없으면 `pa db.py list --project {slug} --status fulltext` 의 논문을 대상으로 한다.
   - 원문이 없는 읽을 목록 논문은 `pa fulltext.py missing --project {slug}` 로 링크를 보여주고, 도서관에서 받아 '읽기' 탭에 올리도록 안내한다.
4. 논문마다 `paper-agent:researcher` 에이전트를 하나씩 띄운다. 동시에 최대 3개까지 띄운다.
   - 프롬프트: "프로젝트 {slug}, 논문 #{id} 심층 분석. 지침의 '첫 화면 재료'와 '2. 심층 분석'을 그대로 따른다. 사용자 메모(db.py memos --paper)를 먼저 읽는다. export_html.py 는 실행하지 않는다. 보고: 노트·가설·변수 수, 핵심 발견 1줄, 방법론 약점 1줄."
   - 모두 끝나면 `pa export_html.py --project {slug}` 로 보고서를 갱신한다.
   - 사용자에게 논문별 핵심 발견과 약점을 표로 알리고, '읽기' 탭에서 확인하라고 안내한다.
5. 갭·가설
   - 분석한 논문이 15편 미만이면 그 사실과 현재 편수를 알리고, 그래도 진행할지 묻는다.
   - `paper-agent:researcher` 에이전트에게 지침의 '3. 갭·가설 발굴'을 맡긴다. 사용자 메모를 출발점으로 삼게 한다.
   - 결과는 `projects/{slug}/gaps/` 에 쌓이고 화면의 '모아보기' 탭에 나온다.
