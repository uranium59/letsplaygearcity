# GearCity Autonomous Agent

## Project Goal
경영 시뮬레이션 게임 **GearCity**를 자율적으로 플레이하는 AI 에이전트('AI CEO') 프로토타입.
개발 중인 게임(RQI)의 기술 검증 목적으로, LangGraph 기반 멀티스텝 SQL 파이프라인과 로컬 LLM으로 전략을 수립/실행한다.

## Tech Stack
- **Python 3.12** / **Poetry** (의존성 관리)
- **LLM**: Qwen 3 30B via **Ollama** (로컬, 256k context)
- **Orchestration**: LangGraph + LangChain
- **DB**: SQLite (GearCity 세이브 파일 = `.db`)
- **Data**: pandas, tabulate

## Project Structure
```
letsplaygearcity/
├── CLAUDE.md               # 이 파일
├── README.md               # 영문 README
├── READMEKR.md             # 한국어 README
├── project.md              # 원본 프로젝트 명세
├── pyproject.toml          # Poetry 의존성
├── .env                    # GEARCITY_DB_PATH, OLLAMA_MODEL, GEARCITY_TURN_EVENTS_XML 설정
├── crawler.py              # GearCity 위키 크롤러
├── parse_turn_events.py    # TurnEvents.xml 분석 도구
├── src/
│   ├── db_query_graph.py   # ★ LangGraph 그래프 빌더 + CLI (메인 진입점)
│   ├── graph_state.py      # GraphState TypedDict + 상수 (MAX_RETRIES 등)
│   ├── graph_utils.py      # 공용 유틸 (create_llm, build_table_catalog 등)
│   ├── prompts.py          # LLM 프롬프트 템플릿 모음
│   ├── queries.py          # SQL 쿼리 상수 모음
│   ├── nodes_pipeline.py   # SQL 파이프라인 노드 (pre_router~advance)
│   ├── nodes_analysis.py   # 분석 노드 (analyst, classifier, strategist, aggregator)
│   ├── nodes_advisors.py   # 전문 자문 노드 (design_advisor, forecast_advisor)
│   ├── design_formulas.py  # 차량 설계 계산 엔진 (상수 + 순수 함수)
│   ├── event_timeline.py   # 전쟁/경제 이벤트 예측 모듈 (임계값 상수 포함)
│   ├── session_memory.py   # 도메인 기반 세션 캐시
│   ├── db_agent.py         # ReAct SQL 에이전트 (Phase 1, deprecated)
│   ├── db_inspector.py     # DB 스키마 → LLM 프롬프트용 텍스트 추출
│   ├── inspect_db.py       # DB 스키마 분석기 (Markdown 출력)
│   └── test_env.py         # 환경 검증 (Ollama + DB 연결 테스트)
├── data/
│   ├── save/               # GearCity .db 세이브 파일
│   ├── schema/             # db_schema_map.txt (71개 테이블)
│   ├── wiki/               # 크롤링된 위키 데이터 (JSON)
│   └── turn_events_timeline.json  # 사전 파싱된 전쟁/경제 타임라인
└── notebooks/              # Jupyter 분석 노트북
```

## Graph Architecture

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
키워드 매칭 실패 시 기존 SQL 파이프라인 → Classifier 경로로 폴백.

SessionMemory가 pre_router에서 현재 게임 턴을 감지하고, analyst/forecast/design 노드에서
결과를 도메인별 캐시에 저장한다. 다음 질문에서 Planner/Analyst에 캐시 컨텍스트가 주입된다.

## Key Scripts

### src/db_query_graph.py — 그래프 빌더 + CLI ★
`build_graph()`로 StateGraph 구성, `run_query()`/`run_interactive()`로 실행.
노드 구현은 `nodes_pipeline.py`, `nodes_analysis.py`, `nodes_advisors.py`에 분리.
노드별 진행 상황 출력은 `_NODE_FORMATTERS` dict dispatch 패턴 사용.
```bash
poetry run python src/db_query_graph.py                          # 대화형 모드
poetry run python src/db_query_graph.py -q "내 현금이 얼마야?"     # 단일 질문
poetry run python src/db_query_graph.py --test                   # 테스트 쿼리 Q1~Q15
poetry run python src/db_query_graph.py "D:\path\to\save.db" -q "..."
```

### src/graph_state.py — 그래프 상태 정의
`GraphState` TypedDict, `StrategyCandidate` TypedDict, `MAX_RETRIES`, `CORE_TABLES` 상수.

### src/graph_utils.py — 공용 유틸리티
`create_llm()`, `build_table_catalog()`, `strip_think_tags()`, `MODEL_NAME`, `SCHEMA_MAP_PATH` 등.

### src/prompts.py — LLM 프롬프트 템플릿
Planner, SQL Generator, Analyst, Classifier, Strategist, Aggregator, Design Advisor, Forecast Advisor 프롬프트.

### src/queries.py — SQL 쿼리 상수
`CURRENT_YEAR_SQL`, `CURRENT_TURN_SQL`, `DESIGN_VEHICLE_SQL`, `TECH_SKILL_SQL`,
`AVAILABLE_COMPONENTS_SQL_TEMPLATE`, `PLAYER_CITY_IDS_SQL` 등 반복 사용되는 SQL.

### src/nodes_pipeline.py — SQL 파이프라인 노드
Pre-Router, Planner, Load Schema, SQL Generator, Executor, Router, Retry, Advance 노드.

### src/nodes_analysis.py — 분석 + 전략 파이프라인 노드
Analyst, Classifier, Strategist, Aggregator 노드.

### src/nodes_advisors.py — 전문 자문 노드
- **Design Advisor**: `_fetch_vehicle_data()` → `_fetch_tech_components()` → `_calculate_design_metrics()` → LLM 합성
- **Forecast Advisor**: 타임라인 로드 → 플레이어 자산 위험 분석 → LLM 합성

### src/design_formulas.py — 차량 설계 계산 엔진
DB/LLM 의존성 없는 순수 Python 계산 모듈. GearCity 위키 공식 구현.
모듈 상단에 명명된 상수 정의 (`DISPLACEMENT_CONSTANT`, `HP_CONVERSION_FACTOR`, `COMPONENT_SAFE_AGE` 등).
- 엔진: `calc_displacement()`, `calc_hp()`, `simulate_bore_change()`, `simulate_stroke_change()`
- 차량: `calc_top_speed()`, `calc_acceleration()`
- 개선 비용: `estimate_modification_cost()` (`MOD_BASE_PERCENT`/`MOD_CHASSIS_PERCENT` 상수)
- 노후화: `calc_staleness()` (컴포넌트 에이징 페널티, buyer divisor, `URGENCY_*` 임계값)
- 호환성: `check_torque_compatibility()`, `compare_ratings()`

### src/event_timeline.py — 전쟁/경제 이벤트 예측 모듈
`data/turn_events_timeline.json`(TurnEvents.xml에서 추출)을 로드하여 예측 제공.
모듈 상단에 경제 임계값 상수 (`BUYRATE_DOWNTURN_THRESHOLD` 등)와
`ECONOMIC_EVENT_CONFIGS` 딕셔너리, `WAR_SEVERITY_RANK`, `RISK_YEARS_*` 상수 정의.
- `get_upcoming_wars()` / `get_active_wars()`: 도시별 전쟁 예측
- `get_upcoming_economic_events()`: 침체, 유가 급등, 금리 급등 감지
- `check_player_asset_risks()`: 플레이어 공장/지점 도시와 미래 전쟁 교차분석
- `format_forecast_summary()`: LLM 프롬프트용 축약 예측 요약
- 범위: 196/205 도시에 전쟁 이력 (1899-2019). 9개 영구 안전 도시.

### src/session_memory.py — 도메인 기반 세션 캐시
대화형 모드에서 질문 간 데이터를 재활용하는 세션 메모리.
- `DOMAIN_CONFIG`: 5개 도메인별 TTL 및 테이블 매핑
- `SessionMemory`: get/put/format_context/get_relevant/classify_tables/get_valid_domains/clear
- `get_memory()` / `reset_memory()`: 모듈 수준 싱글톤
- Planner/Analyst 프롬프트에 캐시 컨텍스트 주입 → 중복 SQL 호출 방지
- 도메인별 TTL: game_state(3), sales_market(5), factory(6), vehicle_design(12), forecast(60)

### src/db_inspector.py — DB 스키마 추출기
세이브 파일(.db)의 71개 테이블 스키마를 `data/schema/db_schema_map.txt`로 추출.
```bash
poetry run python src/db_inspector.py
poetry run python src/db_inspector.py data/save/mysave.db -o data/schema/custom_map.txt
```

### crawler.py — 위키 크롤러
GearCity 위키(wiki.gearcity.info)에서 인게임 플레이 관련 페이지만 BFS로 크롤링.
```bash
poetry run python crawler.py --depth 1 --delay 5
poetry run python crawler.py --no-filter  # 전체 수집
```

### parse_turn_events.py — TurnEvents.xml 분석기
게임 외부 데이터 파일에서 경제 변수와 전쟁 타임라인을 추출하는 독립 분석 도구.
`data/turn_events_timeline.json` 생성용.
XML 경로는 `GEARCITY_TURN_EVENTS_XML` 환경변수 또는 CLI 인자로 지정 가능.
```bash
poetry run python parse_turn_events.py                          # .env에서 경로 로드
poetry run python parse_turn_events.py "D:\path\to\TurnEvents.xml"  # 직접 지정
```

### src/test_env.py — 환경 검증
Ollama(Qwen) 연결 + SQLite DB 연결을 테스트하는 Hello World.
```bash
poetry run python src/test_env.py
```

## GearCity Game Mechanics (에이전트 설계 참조)
- 1 turn = 1 month. `Current_Turn` in GameInfo = current month (1-12).
- `City_GOVERN`: 1=stable, 0=limited(-50% sales), -1=war(no sales), -2=total war(factory destruction risk)
- 전쟁은 **지역별** — 특정 도시/국가에만 영향. 전 세계 동시 X.
- 영구 안전 도시: Argentina(2), Chile(1), Ecuador(1), Peru(1), Sweden(2), Switzerland(1), Uruguay(1)
- TurnEvents.xml이 연도별 경제 변수(buyrate, gas, interest, stockrate, carprice) + cityChange(전쟁 상태) 정의
- DB는 현재 상태만 저장. 미래 이벤트 정보는 `turn_events_timeline.json`에서 제공.

## Development Phases
1. **Phase 1 (완료)**: 환경 구축 + 데이터 분석 — 위키 크롤링, DB 스키마 추출
2. **Phase 2 (현재)**: LangGraph 에이전트 — 멀티스텝 Text-to-SQL + 전략/설계/예측 파이프라인
3. **Phase 3**: 자율 플레이 — 전략 수립/실행, 게임 상태 모니터링

## Conventions
- 한국어 주석/문서, 영어 코드
- Poetry로 의존성 관리 (`poetry add`, `poetry run`)
- `pyproject.toml`에 `packages = [{include = "src"}]` 설정으로 `from src.xxx import` 패턴 동작
- 데이터 파일은 `data/` 하위에 용도별 분리
- 크롤링 시 5초 딜레이 (위키 서버 부하 방지, `.env`의 `WIKI_CRAWL_DELAY`)
