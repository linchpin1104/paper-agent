# 논문 에이전트

SSCI/SCI급 사회과학 논문을 준비하는 연구자를 위한 Claude Code 플러그인입니다.
연구 방향을 이야기하면 읽을 핵심 논문을 골라 주고, 원문을 받아 PDF 옆에 논증 흐름·연구 모형·원문 그림·표·분석을 정리합니다. 읽으면서 형광펜 메모를 남길 수 있습니다.

AI 는 각자의 Claude 구독(Claude Code)으로 돌아갑니다. 별도 API 키는 필요 없습니다.

## 설치

필요한 것: Claude Code (데스크톱 앱 Code 탭 또는 터미널), 맥 기본 파이썬 3.9 이상.

터미널에서 한 번:

```bash
claude plugin marketplace add linchpin1104/paper-agent
```

```bash
claude plugin install paper-agent@lin-papers
```

데스크톱 앱에서는 마켓플레이스를 위처럼 한 번 추가한 뒤, 세션의 **+ → Plugins → Add plugin** 에서 `paper-agent` 를 설치해도 됩니다.

처음 명령을 쓸 때 파이썬 패키지(Streamlit, PyMuPDF)를 `~/.paper-agent/venv` 에 자동으로 설치합니다. 1~2분 걸립니다.

## 업데이트

```bash
claude plugin marketplace update lin-papers
```

```bash
claude plugin update paper-agent@lin-papers
```

받은 뒤 Claude Code 를 다시 시작합니다.

## 쓰는 법

논문 작업용 폴더를 하나 만들고, 그 폴더에서 Claude Code 를 엽니다. 데이터는 그 폴더의 `projects/` 에 쌓입니다.

| 명령 | 하는 일 |
| --- | --- |
| `/paper-agent:start` | 연구 방향 대화 → 검색 전략 → 문헌 수집 → 리뷰·고전·최전선·직결 네 묶음으로 읽을 논문 20편 안팎 제안. `start 차별화` 는 내 질문과 가장 가까운 선행연구 찾기, `start 재분류` 는 연구 방향이 바뀐 뒤 읽을 목록을 남길 것·뺄 것·새로 찾을 것으로 다시 나누기 |
| `/paper-agent:open` | 화면 열기 (http://localhost:8501) |
| `/paper-agent:analyze` | 원문 있는 논문을 심층 분석. `/paper-agent:analyze 갭` 은 연구 갭·가설 찾기 |
| `/paper-agent:journals` | 학회지 구독(프로젝트와 별개). `/paper-agent:journals 요약` 은 구독 학회지에 새로 실린 논문을 모두 받아 학회지별로 요약 |

화면 왼쪽 위에서 **논문 프로젝트**와 **학회지 구독**을 고르고, 오른쪽 위에서 프로젝트를 고릅니다.

학회지 구독: 구독한 학회지에 새로 실린 논문을 키워드로 거르지 않고 모두 받아 학회지별로 보여주고, Claude 가 흐름·눈에 띄는 논문을 요약합니다. 학회지마다 최근 3년 분석(게재 추세·주제·저자 국가·한국 저자 수)과, 원하면 특정 프로젝트와의 맞춤도를 봅니다. 고른 논문은 프로젝트 읽을 목록으로 보냅니다. 저장 위치는 작업 폴더의 `journals/`.

논문 프로젝트 탭

| 탭 | 하는 일 |
| --- | --- |
| 연구 주제 설정 | 대충 말해도 Claude 와 대화하며 주제·키워드·이론 칸을 채워 감 (내 Claude Code 로그인으로 동작). 칸은 직접 고쳐도 됨 |
| 찾기 | **핵심 논문에서 찾기**: 핵심 논문을 먼저 정한다 — 아는 논문 입력(후보 중 직접 선택) 또는 모를 때 '핵심 논문 후보 찾기'(가벼운 검색 → 공통 인용 고전·리뷰) → 참고문헌·인용 논문 수집 → 인용 검증 단계와 함께 연관 논문 순위. 키워드로 찾기, 전체 후보 |
| 읽기 | 제목 아래 **내 논문에서의 역할**(이론 앵커·방법 선례·현상 선례·차별화 대상·배경)과 한 줄 메모, 검토 칸(PDF 제목 대조·원고본 표시·DOI·검토 결과·인용 관계 사람 확인), 한눈에 보기(연구 모형 원문 그림·논증 흐름·원문 그림·표), 왼쪽 PDF, 오른쪽 분석. PDF 를 드래그하면 형광펜 메모 |
| 모아보기 | 문헌 점검(연도 분포·최근 5년·국내 문헌·키논문 역할 빈칸), 내 메모 전체, 연구 아이디어(갭·가설), HTML 보고서 |

인용 검증 단계: ○ DB 1곳 기록 → ◐ OpenAlex·Semantic Scholar 일치 → ● 원문 참고문헌에서 확인 → ● 사람 확인. ⚠ 는 원문 참고문헌에서 못 찾음.
논문 검토: 미검토 / 원문 확인함 / 문제 있음 — 사람이 원문을 보고 정합니다. 분석 노트의 인용문은 원문과 자동 대조(✓/⚠)하고 검토자가 확인 표시를 합니다.

형광펜 색: 노랑 중요 · 초록 내 연구에 활용 · 분홍 의문·반박 · 파랑 인용 후보.

## 선택: API 키

작업 폴더에 `.env` 를 만들면 검색 채널이 늘어납니다. 예시는 `plugins/paper-agent/templates/env.example`.

| 키 | 효과 |
| --- | --- |
| `OPENALEX_API_KEY` | **사실상 필수.** 없으면 같은 인터넷 주소 사용자끼리 하루 무료 사용량(약 0.1달러어치)을 나눠 쓰고, 검색 몇십 번이면 바닥남. [무료 발급](https://help.openalex.org/api/authentication/) |
| `CONTACT_EMAIL` | Unpaywall 로 무료 원문을 더 찾음 |
| `S2_API_KEY` | Semantic Scholar 요청 한도 해제 |
| `DBPIA_API_KEY` | 국내 논문(DBpia) 검색 |
| `LIBRARY_PROXY` | 원문 링크를 학교 도서관 원격접속으로 열기 (유료 논문 PDF 받기). 값은 도서관 안내의 프록시 주소 앞부분 |

## 저작권

도서관에서 받은 유료 논문 PDF 는 각자 작업 폴더에만 둡니다. 다른 사람과 `projects/` 폴더를 공유하지 않습니다.
HTML 보고서에는 공개 접근(OA) 논문의 원문 그림만 들어갑니다.

## 개발

- 플러그인 본체: `plugins/paper-agent/`
- 설치 없이 시험: `claude --plugin-dir ./plugins/paper-agent`
- 검증: `claude plugin validate ./plugins/paper-agent`
- 고친 내용을 올릴 때마다 `plugins/paper-agent/.claude-plugin/plugin.json` 의 `version` 을 올립니다. 그대로면 `plugin update` 가 "이미 최신"이라며 받지 않습니다.
