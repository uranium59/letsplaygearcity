# GearCity Autonomous Agent

> 경영 시뮬레이션 게임 **[GearCity](https://store.steampowered.com/app/285110/GearCity/)** 에 조언을 주는 AI 에이전트('AI CEO').
> LangGraph 기반 멀티스텝 SQL 분석과 로컬 LLM으로 전략을 수립한다.

[English README](README.md)

---

## 이 프로젝트를 만든 이유

현재 기획 및 개발 중인 경영 시뮬레이션 게임 **'RedQueen Industry (RQI)'**에는 쏟아지는 데이터 속에서 플레이어를 보좌할 LLM 기반의 AI 조언자를 탑재할 계획입니다. (아마도 게임 본편과는 별개로 깃허브를 통해 배포할 예정입니다.) 플레이어가 중후반부의 복잡도에 허우적댈 때, 맥락을 파악하고 "사장님, 지금 런던 지사 재고가 위험합니다"라고 정확히 짚어줄 비서 말이죠. 까짓거, 직접 만들어보면 되지 않겠습니까?

하지만 흔히 알려진 챗봇 연동 방식으로는 한계가 명확합니다. 일반적인 LLM은 사전 지식 없는 제로베이스에서 유저의 단순 질문이나 화면 인식만으로 게임의 복잡한 내부 규칙과 실시간 데이터를 파악하는 것이 불가능에 가깝기 때문입니다. 따라서 RQI 본편에 이 시스템을 통합하기 전, AI 에이전트가 과연 복잡하게 얽힌 게임 데이터를 제대로 분석하고 의미 있는 조언을 도출할 수 있는지 검증할 시범 케이스가 필요했습니다.

### 왜 GearCity인가?

이러한 기술 실증(PoC)을 위해 여러 시뮬레이션 게임을 물색하던 중, GearCity가 낙점되었습니다. 이 게임은 외부 AI를 연동해 테스트하기에 정말 완벽한 구조를 가지고 있습니다.

- **Turn-based System** — 실시간 반응성(Latency)의 제약 없이, 턴 단위의 정교한 데이터 분석 및 추론에 집중할 수 있습니다.
- **Accessible State Data** — 세이브 파일이 단일 SQLite DB 형태로 관리되어, 에이전트가 SQL을 통해 직접 게임 내 모든 상태 수치를 조회하고 추적하기 용이합니다.
- **Structured Knowledge** — 게임 내 메카닉에 대한 거의 완벽한 DokuWiki가 제공되어, LLM을 위한 RAG(Retrieval-Augmented Generation) 지식 베이스를 구축하기에 최적화되어 있습니다.

위의 조건에 더불어, 이 게임을 제가 이미 딥하게 플레이해 봐서 '어떤 지점에서 어려움을 느끼는지', '어디서 도움이 필요한지'를 명확히 알고 있다는 점도 중요하게 작용했습니다.

이 프로젝트는 단순한 '챗봇 장난감'에서 한 발짝 더 나아가, 데이터베이스 내의 데이터에서 의미 있는 값을 뽑아내 상황을 인식하고, 위키를 참조해 룰을 이해하며, 유저와 경영 전략을 논의하는 진정한 의미의 **'게임 플레이 조언자'**를 향해가는 첫 번째 프로토타입입니다.

---

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
