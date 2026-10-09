# 논문 에이전트 기획 v3 — 수집 + 리서치 (범용)

> 2026-10-09 1차 구현 완료 → 같은 날 Claude Code 플러그인으로 재구성. 사용법은 README.md. 흐름: 연구 방향 대화 → 핵심 논문(리뷰·고전·최전선·직결) 선정 → 원문 → 심층 분석 → 형광펜 메모 → 갭.

작성일 2026-10-09 · 용도: SSCI/SCI급 사회과학 논문용 도구. 주제를 바꿔가며 반복 사용

---

## 1. 목표

- 논문 프로젝트 하나당 **정본 폴더 하나**. 검색 기록, 후보 목록, 원문 PDF, 추출 텍스트, 분석 노트, 갭·가설, 결정 기록이 전부 그 안에 있다
- 문헌은 열 수 있는 채널을 전부 연다. 해외·국내·OA·도서관
- 좋아하는 논문을 표시하면 그 논문의 인용망·유사논문을 따라 확장 수집한다
- 목록만 받지 않는다. 선별한 논문은 원문을 받아 DB에 저장하고 분석은 원문 인용과 쪽수로 뒷받침한다
- 페이지에서 목록을 보고 체크하고 원문과 분석을 읽는다. 구조는 프로젝트가 진행될수록 쌓인다
- 1차 범위는 수집 + 리서치. 집필·통계 분석은 2차 이후

---

## 2. 논문 작성 프로세스 (SSCI 사회과학 기준)

| 단계 | 하는 일 | 산출물 | 통과 기준 |
| --- | --- | --- | --- |
| 1. 주제 탐색 | 최근 5년 문헌 지도. 리뷰논문·"future research" 절에서 미해결 질문 수집 | 후보 목록, 갭 후보 | 갭 후보마다 근거 논문 3편 이상 |
| 2. 연구질문·가설 | 이론 기반 확정, RQ → 가설, 기여 한 문장 | RQ, 가설 3~6개 | 가설마다 이론 근거 + 선행 실증 1편 |
| 3. 문헌 심층 분석 | 핵심 논문 30~60편을 같은 틀로 분해 | 분석노트, 증거 매트릭스 | 매트릭스 빈 칸 없음 |
| 4. 연구 설계 | 자료 원천, 측정, 분석기법 | 설계서 | 지도교수 승인 |
| 5. 수집·분석 | IRB, 수집, 분석, 강건성 | 결과표, 스크립트 | 재현 가능 |
| 6. 집필 | Intro–Theory–Method–Results–Discussion | 원고 | 저널 가이드라인 |
| 7. 투고·심사 | 저널 선정(SSCI 등재 확인), 리비전 | 투고본, 응답서 | — |

1차 도구는 1·2·3단계를 맡는다. 4단계부터는 사람이 결정한다.

---

## 3. 정본 — 프로젝트 폴더

```
projects/{slug}/
├── brief.md          ← 주제 씨앗, 연도, 연구 유형, 대상 저널, 이론 후보, 지도교수 지침
├── library.db        ← SQLite. 아래 모든 것의 정본
├── pdf/              ← 원문 PDF (파일명 = DOI 또는 내부 id)
├── gaps/             ← 증거 매트릭스, 가설 후보 (gap-finder 산출)
├── decisions.md      ← 결정 기록. 날짜 + 결정 + 이유. 반대로 정한 것도 적는다
└── export/           ← 정적 HTML 스냅샷 (아티팩트·지도교수 공유용)
```

`library.db` 테이블

| 테이블 | 내용 |
| --- | --- |
| papers | id, doi, 제목, 저자, 연도, 저널, 초록, 인용수, 상태(candidate→shortlist→fulltext→analyzed), favorite, 등재구분(SSCI/SCI/KCI/없음) |
| sources | 논문 ↔ 어느 채널에서 어떤 id·URL로 왔는지. 같은 논문이 여러 채널에서 와도 한 행으로 합침 |
| fulltext | 논문 ↔ pdf 경로, 추출 텍스트(쪽 구분 유지), 추출 일시 |
| edges | 논문 ↔ 논문 관계. cites / cited_by / similar / recommended |
| notes | 분석노트. 논문 × 항목(연구질문, 이론, 가설…) × 내용 × 원문 인용 × 쪽수 |
| searches | 채널, 질의, 실행 일시, 건수 |

볼트와의 관계 — 논문 데이터(DB·PDF·노트)의 정본은 프로젝트 폴더. 볼트에는 세션 예치본과 결정 요약만 간다. 예치본에 프로젝트 폴더 경로를 적는다.

---

## 4. 수집 채널

| 채널 | 얻는 것 | 접근 | 상태 |
| --- | --- | --- | --- |
| OpenAlex | 메타, 인용망(참고문헌·피인용), OA 링크 | 키 없음 | 즉시 |
| Semantic Scholar | 메타, 인용망, **추천 논문**(좋아하는 논문 기반 확장에 사용) | 키 선택 | 즉시 |
| Crossref | DOI 메타 보강 | 키 없음 | 즉시 |
| Unpaywall | OA PDF 위치 | 이메일 | 즉시 |
| DBpia | 국내 논문 메타·상세 링크. 등재정보(dreg_name) 포함 | API 키 발급 필요 | 키 발급 후 |
| KCI | 국내 등재지 메타·인용 | 오픈API 인증키 신청 | 확인 필요 |
| RISS | 국내 학위논문·학술지 | 공식 API 유무 확인 필요 | 확인 필요 |
| Google Scholar | 폭넓은 검색 | 공식 API 없음 | 아래 결정 |
| 고려대 도서관 | 유료 원문 | 로그인 세션 | 브라우저로 받기 |

Google Scholar 처리 — 공식 API가 없고 스크래핑은 차단된다. 선택지는 둘이다.
① SerpAPI 같은 유료 중계 서비스. ② Publish or Perish로 검색 결과를 CSV로 내보내 가져오기. 메타데이터는 OpenAlex·Semantic Scholar가 Scholar와 대부분 겹치므로 ②로 시작해도 손실이 작다.

원문 수집 순서 — OA(Unpaywall·OpenAlex) 자동 → DBpia 무료 콘텐츠 자동 → 나머지는 도서관 링크를 페이지에 띄우고 사람이 로그인 세션으로 받거나, 브라우저 자동화로 받는다. 받은 PDF는 `pdftotext`로 쪽 단위 텍스트를 추출해 DB에 넣는다. (pdftotext·PyMuPDF 로컬 설치 확인함)

---

## 5. 에이전트

### 5-1. 수집 에이전트 (collector)

- 입력: `brief.md`, DB의 favorite 논문
- 하는 일
  - 채널별 검색 스크립트 실행 → 결과를 같은 형태로 정규화 → DOI·제목으로 중복 제거 → DB upsert (상태 candidate)
  - favorite 논문마다 참고문헌·피인용·추천 논문을 1홉 수집 → edges 기록, 신규 논문은 candidate로 추가
  - shortlist 논문의 원문 수집 → pdf/ 저장 → 텍스트 추출 → fulltext 기록, 상태 fulltext
  - 저널 등재구분 표시 (Clarivate Master Journal List, KCI)
- 출력: DB 갱신 + 수집 보고(채널별 건수, 원문 확보율, 못 받은 목록)

### 5-2. 리서치 에이전트 (researcher)

세 단계를 순서대로 돈다.

**a. 선별** — candidate를 brief 기준으로 읽고 shortlist 추천. 사유를 한 줄씩. 최종 체크는 페이지에서 사람이 한다

**b. 심층 분석 (paper-analyst)** — fulltext 있는 shortlist 논문을 아래 틀로 분해. 항목마다 원문 인용 + 쪽수. 추론은 "[해석]"으로 분리. 양적·질적 공통

```
연구질문 / 이론 기반 / 가설 또는 명제 (지지·기각) / 표본·맥락 / 측정 또는 자료
분석 기법 / 주요 결과 (계수·효과크기) / 한계 (저자 명시) / 향후 연구 제안 (저자 명시)
[해석] 이 논문이 비운 자리 / 인용할 문장 (쪽수)
```

**c. 갭·가설 발굴 (gap-finder)** — notes 전체로 증거 매트릭스(논문 × 이론·맥락·방법·결과). 빈 조합 → 갭 후보 → RQ → 가설(양적) 또는 명제(질적). 근거 논문 3편 미만은 제외

---

## 6. 페이지

로컬 페이지 하나. 프로젝트를 고르고 아래 탭을 본다.

| 탭 | 보이는 것 | 할 수 있는 것 |
| --- | --- | --- |
| 후보 | 채널별 검색 결과 표. 제목·연도·저널·인용수·등재·원문 여부 | favorite·shortlist 체크, 필터, "관련논문 수집" 실행 |
| 원문 | 선택한 논문의 추출 텍스트 (쪽 구분) | 문장 선택 → 노트에 인용으로 넣기 |
| 분석 | 논문별 분석노트. 항목 옆에 원문 인용과 쪽수 | 노트 수정 |
| 갭 | 증거 매트릭스, 갭 후보, 가설 초안 | 채택·보류 표시 |
| 내보내기 | 프로젝트 전체를 정적 HTML 한 파일로 | 아티팩트 게시, 지도교수 공유 |

구현 — Streamlit 파일 하나. 의존성 1개로 표·체크박스·탭이 기본 제공되어 자체 서버보다 코드가 짧다. 내보내기는 표준 라이브러리로 정적 HTML 생성.

---

## 7. 구조

```
논문에이전트/
├── .claude/agents/
│   ├── collector.md
│   └── researcher.md
├── scripts/
│   ├── db.py                 ← 스키마, upsert, 중복 제거 (표준 라이브러리)
│   ├── fetch_openalex.py
│   ├── fetch_s2.py
│   ├── fetch_crossref.py
│   ├── fetch_dbpia.py
│   ├── fetch_unpaywall.py
│   ├── import_scholar_csv.py ← Publish or Perish 내보내기 가져오기
│   ├── extract_text.py       ← pdftotext → fulltext
│   └── export_html.py
├── app.py                    ← Streamlit 페이지
├── templates/
│   ├── brief.md
│   └── decisions.md
├── projects/{slug}/          ← 정본. 여기만 늘어난다
└── PLAN.md
```

새 주제 시작 = `projects/{slug}/` 만들고 brief 채우기. 나머지는 공통.

---

## 8. 흐름

1. brief 작성
2. collector — 전 채널 검색 → DB (candidate)
3. 페이지에서 favorite·shortlist 체크
4. collector — favorite 기반 관련논문 확장, shortlist 원문 수집·추출
5. researcher — 심층 분석 → notes (원문 인용·쪽수)
6. researcher — 갭·가설 → gaps/
7. 내보내기 → 아티팩트. decisions.md 갱신
8. 3~7 반복. 노트가 쌓일수록 매트릭스가 커진다

---

## 9. 지금 만들지 않는 것

- 집필·통계 분석 에이전트 — 2차
- 벡터 검색 — 한 프로젝트 원문이 100편 넘으면 검토. 그전까지 SQLite FTS로 충분
- 프로젝트 간 통합 검색 — 프로젝트 3개 넘으면 검토
- 유료 원문 자동 다운로드 — 도서관 약관 확인 전까지 사람이 받는다

---

## 10. 결정이 필요한 것

1. **DBpia API 키** — 발급은 사용자가 직접. 키는 `.env`에 두고 git에 올리지 않는다
2. **Google Scholar** — ② Publish or Perish CSV 가져오기로 시작 권장. SerpAPI 유료 필요 시 추가
3. **페이지** — Streamlit 권장. 의존성 없이 가려면 자체 서버 (코드 약 2배)
4. **KCI·RISS** — 빌드 시점에 API 유무 확인 후 붙임

---

## 11. 다음 단계

1. `scripts/db.py` + 스키마, `templates/` 2종, `projects/` 첫 폴더
2. `fetch_openalex.py`, `fetch_s2.py`, `fetch_unpaywall.py`, `extract_text.py` → 키 없는 채널부터 돌려 DB 채움
3. `app.py` 후보·원문 탭 → 체크·확장 수집 동작 확인
4. `collector.md`, `researcher.md` 에이전트 작성 → 상위 5편으로 분석 시험
5. DBpia 키 받으면 `fetch_dbpia.py`. `export_html.py`는 노트 10편 뒤
