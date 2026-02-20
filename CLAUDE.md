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
├── .env                    # GEARCITY_DB_PATH, OLLAMA_MODEL 설정
├── crawler.py              # GearCity 위키 크롤러
├── parse_turn_events.py    # TurnEvents.xml 분석 도구
├── src/
│   ├── db_query_graph.py   # ★ LangGraph 멀티스텝 SQL 에이전트 (메인)
│   ├── design_formulas.py  # 차량 설계 계산 엔진
│   ├── event_timeline.py   # 전쟁/경제 이벤트 예측 모듈
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

## Key Scripts

### src/db_query_graph.py — LangGraph 멀티스텝 SQL 에이전트 ★
16개 노드의 StateGraph. 질문 유형별 5가지 파이프라인 제공.
- **Pre-Router**: 키워드 기반 사전분류 (LLM 호출 없음). forecast/design 직행.
- **Planner**: 질문을 1~5개 서브쿼리로 분해, 필요 테이블 선택
- **SQL Generator**: 서브쿼리별 SQL 생성 (선택된 테이블 스키마만 제공)
- **Executor**: SQLite read-only 실행, 에러 시 최대 2회 재시도
- **Analyst**: 수집된 결과를 종합 분석, 최종 답변 생성
- **Classifier**: 질문 유형 분류 (factual/analytical/strategic/design/forecast)
- **Strategist → Evaluators → Aggregator**: 전략 후보 생성 → 병렬 평가 → 종합 추천
- **Design Advisor**: Python 계산(배기량, HP, 노후화, 개선비용) + LLM 합성
- **Forecast Advisor**: JSON 타임라인 + 플레이어 자산 위험 교차분석 + LLM 합성
- 스키마 2단계 전략: Tier 1(71개 테이블 카탈로그 ~3KB) + Tier 2(선택 테이블 전체 스키마)
```bash
PYTHONPATH=. poetry run python src/db_query_graph.py                          # 대화형 모드
PYTHONPATH=. poetry run python src/db_query_graph.py -q "내 현금이 얼마야?"     # 단일 질문
PYTHONPATH=. poetry run python src/db_query_graph.py --test                   # 테스트 쿼리 Q1~Q15
PYTHONPATH=. poetry run python src/db_query_graph.py "D:\path\to\save.db" -q "..."
```

### src/design_formulas.py — 차량 설계 계산 엔진
DB/LLM 의존성 없는 순수 Python 계산 모듈. GearCity 위키 공식 구현.
- 엔진: `calc_displacement()`, `calc_hp()`, `simulate_bore_change()`, `simulate_stroke_change()`
- 차량: `calc_top_speed()`, `calc_acceleration()`
- 개선 비용: `estimate_modification_cost()` (15%/20%/25%/100% 규칙)
- 노후화: `calc_staleness()` (컴포넌트 에이징 페널티, buyer divisor)
- 호환성: `check_torque_compatibility()`, `compare_ratings()`

### src/event_timeline.py — 전쟁/경제 이벤트 예측 모듈
`data/turn_events_timeline.json`(TurnEvents.xml에서 추출)을 로드하여 예측 제공.
- `get_upcoming_wars()` / `get_active_wars()`: 도시별 전쟁 예측
- `get_upcoming_economic_events()`: 침체, 유가 급등, 금리 급등 감지
- `check_player_asset_risks()`: 플레이어 공장/지점 도시와 미래 전쟁 교차분석
- `format_forecast_summary()`: LLM 프롬프트용 축약 예측 요약
- 범위: 196/205 도시에 전쟁 이력 (1899-2019). 9개 영구 안전 도시.

### src/db_inspector.py — DB 스키마 추출기
세이브 파일(.db)의 71개 테이블 스키마를 `data/schema/db_schema_map.txt`로 추출.
```bash
PYTHONPATH=. poetry run python src/db_inspector.py
PYTHONPATH=. poetry run python src/db_inspector.py data/save/mysave.db -o data/schema/custom_map.txt
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
- 스크립트 실행 시 `PYTHONPATH=.` 필수 (`from src.xxx import` 패턴)
- 데이터 파일은 `data/` 하위에 용도별 분리
- 크롤링 시 5초 딜레이 (위키 서버 부하 방지, `.env`의 `WIKI_CRAWL_DELAY`)
