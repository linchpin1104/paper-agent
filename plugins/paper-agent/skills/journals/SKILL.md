---
name: journals
description: 학회지 구독 — 연구 프로젝트와 별개로, 구독한 학회지에 새로 실린 논문을 키워드로 거르지 않고 모두 받아 학회지별로 요약한다. 학회지 구독 추가·분석도 한다. "학회지 새 논문", "이번 주 학회지", "저널 구독", "학회지 분석" 요청과 정기 실행에 사용.
argument-hint: "[요약 | 구독할 학회지 이름]"
allowed-tools: Bash("${CLAUDE_PLUGIN_ROOT}/bin/pa" *), Bash(mkdir *), Read, Write
---

# 학회지 구독

아래의 `pa` 는 `"${CLAUDE_PLUGIN_ROOT}/bin/pa"` 를 줄인 것이다. 구독은 연구 프로젝트와 별개이며, 작업 폴더의 `journals/` 에 저장된다.

## 구독 추가 (인자가 학회지 이름일 때)
- `pa journals.py find --query "이름 또는 ISSN"` → 후보를 보여주고 **사용자가 고르게 한다**. 이름이 비슷한 다른 학회지가 섞인다.
- `pa journals.py add --source S...` → `pa journals.py profile --source S...`
- 분석 보고: 최근 3년 게재 편수, 주요 주제, 저자 국가와 한국 저자 논문 수, 최근 고인용. SSCI·SCIE 등재 여부는 Clarivate 링크로 사람이 확인한다.
- 사용자가 특정 연구 프로젝트와의 맞춤도를 원하면 `pa journals.py profile --source S... --project {slug}`.

## 새 논문 요약 (인자가 "요약"이거나 정기 실행)
1. `pa journals.py update` → `pa journals.py new` 로 새 논문을 **모두** 읽는다. 키워드로 거르지 않는다.
2. `journals/feeds/YYYY-MM-DD.md` 에 쓴다 (화면 '학회지 구독 → 요약').
   - 첫 줄: 확인 기간, 전체 편수
   - 표: 학회지 · 편수 · 이번 묶음의 흐름 한 줄
   - 학회지마다: 흐름(주제가 몰린 곳, 편수 근거), 방법 경향, 눈에 띄는 논문 2~4편(제목 — 한 줄 요지). 서평·정정·목차는 세지 않는다
   - 학회지를 가로지르는 관찰 2~3줄. 한국 저자·한국 맥락 논문이 있으면 따로 적는다
   - 초록만 읽고 쓴 요약이라는 점을 밝힌다. 단정하지 않는다
3. 사용자에게 같은 내용을 짧게 알린다. 확인이 끝나면 화면에서 '모두 확인함'을 누르도록 안내한다. (`pa journals.py seen` 은 사용자가 원할 때만)
4. 사용자가 특정 논문을 연구 프로젝트에 넣고 싶어 하면 `pa journals.py send --project {slug} --ids 1,2`.

## 사용량
OpenAlex 는 키 없이 하루 사용량을 같은 인터넷 주소의 사용자끼리 나눠 쓴다. "하루 사용량을 다 썼습니다" 오류가 나면 `.env` 에 `OPENALEX_API_KEY` 를 넣도록 안내한다 (무료 발급: https://help.openalex.org/api/authentication/).
