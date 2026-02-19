# GearCity Autonomous Agent

경영 시뮬레이션 게임 **[GearCity](https://store.steampowered.com/app/285110/GearCity/)** 를 자율적으로 플레이하는 AI 에이전트('AI CEO') 프로토타입.

개발 중인 게임(RQI)의 기술 검증 목적으로, LangGraph 기반 멀티스텝 SQL 분석과 로컬 LLM으로 전략을 수립/실행한다.

## Tech Stack

| 구분 | 기술 |
|------|------|
| Language | Python 3.12 / Poetry |
| LLM | Qwen 3 30B via Ollama (로컬, 256k context) |
| Orchestration | LangGraph + LangChain |
| DB | SQLite (GearCity 세이브 파일 = `.db`) |
| Data | pandas, tabulate |

## 빠른 시작

```bash
# 의존성 설치
poetry install

# 환경 검증 (Ollama 서버가 실행 중이어야 함)
poetry run python src/test_env.py

# DB 스키마 추출 (세이브 파일이 변경되었을 때)
poetry run python src/db_inspector.py "D:\path\to\save.db"

# AI 에이전트 실행
poetry run python src/db_query_graph.py -q "내 회사 현금이 얼마야?"
```

## 사전 요구사항

- **Python 3.12+**
- **Ollama** — `ollama serve` 실행 상태, `qwen3:30b-a3b-instruct-2507-q4_K_M` 모델 다운로드
- **GearCity 세이브 파일** (`.db`)

## 핵심 스크립트

### `src/db_query_graph.py` — LangGraph 멀티스텝 SQL 에이전트

자연어 질문을 받아 SQL 생성 → 실행 → 분석을 자동 수행하는 메인 에이전트.

```
User Question
      ↓
  [Planner] ─ 질문을 1~5개 서브쿼리로 분해, 필요 테이블 선택
      ↓
  [Load Schema] ─ 선택된 테이블만 스키마 추출
      ↓
  [SQL Generator] ─ 서브쿼리에 대해 SQL 생성
      ↓
  [Executor] ─ SQLite read-only 실행
      ↓
  [Router] ─ 에러 → retry (최대 2회) / 다음 서브쿼리 / 전부 완료 → analyst
      ↓
  [Analyst] ─ 결과 종합 분석, 최종 답변 생성
```

```bash
poetry run python src/db_query_graph.py                          # 대화형 모드
poetry run python src/db_query_graph.py -q "내 현금이 얼마야?"     # 단일 질문
poetry run python src/db_query_graph.py --test                   # 테스트 쿼리 4개 실행
poetry run python src/db_query_graph.py "D:\path\to\save.db" -q "..."  # 커스텀 DB
```

### `src/db_agent.py` — ReAct SQL 에이전트 (v1 프로토타입)

LangChain `create_sql_agent` 기반 초기 버전. ReAct 포맷 파싱 실패율이 높아 `db_query_graph.py`로 대체됨.

### `src/db_inspector.py` — DB 스키마 추출기

세이브 파일의 71개 테이블 스키마를 LLM이 활용할 수 있는 텍스트 파일(`data/schema/db_schema_map.txt`)로 추출.

### `crawler.py` — 위키 크롤러

GearCity 위키에서 인게임 관련 페이지를 BFS로 크롤링하여 `data/wiki/`에 JSON으로 저장.

## 프로젝트 구조

```
letsplaygearcity/
├── CLAUDE.md               # AI 어시스턴트용 프로젝트 컨텍스트
├── project.md              # 원본 프로젝트 명세
├── pyproject.toml          # Poetry 의존성
├── crawler.py              # 위키 크롤러
├── src/
│   ├── db_query_graph.py   # ★ LangGraph 멀티스텝 SQL 에이전트
│   ├── db_agent.py         # ReAct SQL 에이전트 (v1)
│   ├── db_inspector.py     # DB 스키마 → 텍스트 추출
│   ├── inspect_db.py       # DB 스키마 분석기
│   └── test_env.py         # 환경 검증
├── data/
│   ├── save/               # GearCity .db 세이브 파일
│   ├── schema/             # db_schema_map.txt (71개 테이블)
│   └── wiki/               # 크롤링된 위키 데이터 (JSON)
└── notebooks/              # Jupyter 분석 노트북
```

## 개발 단계

1. **Phase 1** (완료): 환경 구축 + 데이터 분석 — 위키 크롤링, DB 스키마 추출
2. **Phase 2** (현재): LangGraph 에이전트 구현 — 멀티스텝 Text-to-SQL
3. **Phase 3**: 자율 플레이 — 전략 수립/실행, 게임 상태 모니터링
