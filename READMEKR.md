# GearCity Autonomous Agent

경영 시뮬레이션 게임 **[GearCity](https://store.steampowered.com/app/285110/GearCity/)** 를 자율적으로 플레이하는 AI 에이전트('AI CEO') 프로토타입.

개발 중인 게임(RQI)의 기술 검증 목적으로, LangGraph 기반 멀티스텝 SQL 분석과 로컬 LLM으로 전략을 수립/실행한다.

[English README](README.md)

## Tech Stack

| 구분 | 기술 |
|------|------|
| Language | Python 3.12 / Poetry |
| LLM | Qwen 3 30B-A3B via Ollama (로컬, 256k context) |
| Orchestration | LangGraph + LangChain |
| DB | SQLite (GearCity 세이브 파일 = `.db`) |
| Data | pandas, tabulate |

## 시스템 요구사항

| 항목 | 최소 | 권장 |
|------|------|------|
| OS | Windows 10 / Linux / macOS | Windows 11 |
| Python | 3.12+ | 3.12 |
| RAM | 16GB | 32GB+ |
| VRAM | — (CPU 추론 가능, 매우 느림) | 24GB+ (RTX 3090/4090 등) |
| 디스크 | 20GB (모델 파일 + 의존성) | — |

Qwen 3 30B-A3B (Q4_K_M 양자화)는 약 20GB의 모델 파일을 로드한다.
GPU VRAM이 충분하면 Ollama가 자동으로 GPU에 로드하며, 부족하면 CPU/RAM 폴백한다.
GPU 추론 시 전체 파이프라인 약 2~5분, CPU 추론 시 10분 이상 소요될 수 있다.

### 왜 로컬 LLM인가?

이 프로젝트는 **Ollama 기반 로컬 LLM 전용**으로 설계되었다.
OpenAI, Anthropic, Google 등 클라우드 API LLM 연동은 계획에 없다.

- 게임 데이터(세이브 파일)가 로컬에 있으므로, 추론도 로컬에서 완결하는 것이 자연스럽다
- 실행 비용이 제로 — 한 질문당 LLM 호출 5~10회가 발생하므로, API 과금 모델은 비실용적
- 이 프로젝트의 목적은 "로컬 LLM으로 게임 에이전트를 어디까지 만들 수 있는가"의 기술 검증

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

## 아키텍처

LangGraph StateGraph 기반 조건부 라우팅. 질문 유형별 전용 파이프라인으로 분기한다.

```
User Question → [Pre-Router] (키워드 기반, LLM 호출 없음)
                    ├── forecast → ForecastAdvisor → END
                    ├── design → DesignAdvisor → END
                    └── other → Planner → LoadSchema → SQLGen → Executor
                                    → Router (retry/advance/analyst)
                                    → Analyst → Classifier
                                        ├── factual/analytical → END
                                        ├── strategic → Strategist → Evaluators×N → Aggregator → END
                                        ├── design → DesignAdvisor → END
                                        └── forecast → ForecastAdvisor → END
```

Pre-Router는 키워드 기반 사전분류로, forecast/design 질문을 SQL 파이프라인 없이 직행시켜 LLM 호출을 5회→1회로 줄인다.

### 전용 파이프라인

| 파이프라인 | 트리거 예시 | 동작 |
|-----------|-----------|------|
| **Strategic** | "수익성을 높이려면?" | 전략 후보 2~4개 생성 → 추가 SQL로 각각 평가 → 종합 추천 |
| **Design Advisor** | "보어를 5mm 늘리면?" | Python 계산 엔진 (배기량, HP, 노후화, 개선비용) + LLM 합성 |
| **Forecast Advisor** | "앞으로 전쟁이 일어나?" | TurnEvents.xml 타임라인 (전쟁, 침체, 유가) + 플레이어 자산 위험 교차분석 |

### 세션 메모리

대화형 모드에서 도메인별 TTL 캐시로 이전 질문의 결과를 재활용한다.

| 도메인 | TTL (턴) | 캐시 내용 |
|--------|----------|-----------|
| `game_state` | 3 | 연도/월/현금/회사명 |
| `sales_market` | 5 | 판매/수요/도시별 실적 |
| `vehicle_design` | 12 | 차량/부품 스펙 |
| `factory` | 6 | 공장/생산라인 |
| `forecast` | 60 | 전쟁/경제 예측 |

## 핵심 스크립트

### `src/db_query_graph.py` — LangGraph 멀티스텝 SQL 에이전트

16개 노드의 StateGraph. 질문 유형별 5가지 파이프라인 제공.

```bash
poetry run python src/db_query_graph.py                          # 대화형 모드
poetry run python src/db_query_graph.py -q "내 현금이 얼마야?"     # 단일 질문
poetry run python src/db_query_graph.py --test                   # 테스트 쿼리 Q1~Q15
poetry run python src/db_query_graph.py "D:\path\to\save.db" -q "..."  # 커스텀 DB
```

### `src/design_formulas.py` — 차량 설계 계산 엔진

DB/LLM 의존성 없는 순수 Python 계산 모듈. GearCity 위키 공식 구현.
- 엔진: `calc_displacement()`, `calc_hp()`, `simulate_bore_change()`, `simulate_stroke_change()`
- 차량: `calc_top_speed()`, `calc_acceleration()`
- 개선 비용: `estimate_modification_cost()` (15%/20%/25%/100% 규칙)
- 노후화: `calc_staleness()` (컴포넌트 에이징 페널티, buyer divisor)
- 호환성: `check_torque_compatibility()`, `compare_ratings()`

### `src/event_timeline.py` — 전쟁/경제 이벤트 예측 모듈

`data/turn_events_timeline.json`(TurnEvents.xml에서 추출)을 로드하여 예측 제공.
- `get_upcoming_wars()` / `get_active_wars()`: 도시별 전쟁 예측
- `get_upcoming_economic_events()`: 침체, 유가 급등, 금리 급등 감지
- `check_player_asset_risks()`: 플레이어 공장/지점 도시와 미래 전쟁 교차분석
- `format_forecast_summary()`: LLM 프롬프트용 축약 예측 요약
- 범위: 196/205 도시에 전쟁 이력 (1899-2019). 9개 영구 안전 도시.

### `src/session_memory.py` — 도메인 기반 세션 캐시

대화형 모드에서 질문 간 데이터를 재활용하는 세션 메모리.
- `SessionMemory`: 도메인별 TTL 캐시 (get/put/format_context)
- `get_memory()` / `reset_memory()`: 모듈 수준 싱글톤
- Planner/Analyst에게 캐시 컨텍스트를 주입하여 중복 SQL 호출 방지

### `src/db_inspector.py` — DB 스키마 추출기

세이브 파일의 71개 테이블 스키마를 LLM이 활용할 수 있는 텍스트 파일(`data/schema/db_schema_map.txt`)로 추출.

### `src/db_agent.py` — ReAct SQL 에이전트 (v1, deprecated)

LangChain `create_sql_agent` 기반 초기 버전. `db_query_graph.py`로 대체됨.

### `crawler.py` — 위키 크롤러

GearCity 위키에서 인게임 관련 페이지를 BFS로 크롤링하여 `data/wiki/`에 JSON으로 저장.

### `parse_turn_events.py` — TurnEvents.xml 분석기

게임 외부 데이터 파일에서 경제 변수와 전쟁 타임라인을 추출하는 독립 분석 도구.
`data/turn_events_timeline.json` 생성용.

## 프로젝트 구조

```
letsplaygearcity/
├── CLAUDE.md                     # AI 어시스턴트용 프로젝트 컨텍스트
├── README.md                     # 영문 README
├── READMEKR.md                   # 한국어 README (이 파일)
├── project.md                    # 원본 프로젝트 명세
├── pyproject.toml                # Poetry 의존성
├── .env                          # GEARCITY_DB_PATH, OLLAMA_MODEL 설정
├── crawler.py                    # 위키 크롤러
├── parse_turn_events.py          # TurnEvents.xml 분석 도구
├── src/
│   ├── db_query_graph.py         # ★ LangGraph 멀티스텝 SQL 에이전트 (메인)
│   ├── design_formulas.py        # 차량 설계 계산 엔진
│   ├── event_timeline.py         # 전쟁/경제 이벤트 예측 모듈
│   ├── session_memory.py         # 도메인 기반 세션 캐시
│   ├── db_agent.py               # ReAct SQL 에이전트 (v1, deprecated)
│   ├── db_inspector.py           # DB 스키마 → 텍스트 추출
│   ├── inspect_db.py             # DB 스키마 분석기 (Markdown 출력)
│   └── test_env.py               # 환경 검증 (Ollama + DB 연결)
├── data/
│   ├── save/                     # GearCity .db 세이브 파일
│   ├── schema/                   # db_schema_map.txt (71개 테이블)
│   ├── wiki/                     # 크롤링된 위키 데이터 (JSON)
│   └── turn_events_timeline.json # 사전 파싱된 전쟁/경제 타임라인
└── notebooks/                    # Jupyter 분석 노트북
```

## 개발 단계

1. **Phase 1** (완료): 환경 구축 + 데이터 분석 — 위키 크롤링, DB 스키마 추출
2. **Phase 2** (현재): LangGraph 에이전트 — 멀티스텝 Text-to-SQL + 전략/설계/예측 파이프라인
3. **Phase 3**: 자율 플레이 — 전략 수립/실행, 게임 상태 모니터링
