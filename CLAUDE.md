# GearCity Autonomous Agent

## Project Goal
경영 시뮬레이션 게임 **GearCity**를 자율적으로 플레이하는 AI 에이전트('AI CEO') 프로토타입.
개발 중인 게임(RQI)의 기술 검증 목적으로, LangGraph 기반 순환형 사고(Thinking Loop)와 SQLite Text-to-SQL로 전략을 수립/실행한다.

## Tech Stack
- **Python 3.12** / **Poetry** (의존성 관리)
- **LLM**: Qwen 3 30B via **Ollama** (로컬, 256k context)
- **Orchestration**: LangGraph + LangChain
- **DB**: SQLite (GearCity 세이브 파일 = `.db`)
- **Data**: pandas, sqlalchemy

## Project Structure
```
letsplaygearcity/
├── CLAUDE.md               # 이 파일
├── project.md              # 원본 프로젝트 명세
├── pyproject.toml          # Poetry 의존성
├── crawler.py              # GearCity 위키 크롤러
├── src/
│   ├── db_query_graph.py   # ★ LangGraph 멀티스텝 SQL 에이전트 (Phase 2)
│   ├── db_agent.py         # ReAct SQL 에이전트 (Phase 1 프로토타입)
│   ├── db_inspector.py     # DB 스키마 → LLM 프롬프트용 텍스트 추출
│   ├── inspect_db.py       # DB 스키마 분석기 (Markdown 출력)
│   └── test_env.py         # 환경 검증 (Ollama + DB 연결 테스트)
├── data/
│   ├── save/               # GearCity .db 세이브 파일
│   ├── schema/             # 추출된 DB 스키마 (db_schema_map.txt)
│   └── wiki/               # 크롤링된 위키 데이터 (JSON)
└── notebooks/              # Jupyter 분석 노트북
```

## Key Scripts

### src/db_query_graph.py - LangGraph 멀티스텝 SQL 에이전트 ★
LangGraph StateGraph 기반 멀티스텝 분석 에이전트. LLM은 SQL 생성과 데이터 해석만 담당하고, 워크플로우 라우팅은 Python 코드가 담당.
- **Planner**: 질문을 1~5개 서브쿼리로 분해, 필요 테이블 선택
- **SQL Generator**: 서브쿼리별 SQL 생성 (선택된 테이블 스키마만 제공)
- **Executor**: SQLite read-only 실행, 에러 시 최대 2회 재시도
- **Analyst**: 수집된 결과를 종합 분석, 최종 답변 생성
- 스키마 2단계 전략: Tier 1(71개 테이블 카탈로그 ~3KB) + Tier 2(선택 테이블 전체 스키마)
- `data/schema/db_schema_map.txt`를 런타임에 파싱
```bash
poetry run python src/db_query_graph.py                          # 대화형 모드
poetry run python src/db_query_graph.py -q "내 현금이 얼마야?"     # 단일 질문
poetry run python src/db_query_graph.py --test                   # 테스트 쿼리 실행
poetry run python src/db_query_graph.py "D:\path\to\save.db" -q "..."
```

### src/db_agent.py - ReAct SQL 에이전트 (Phase 1 프로토타입)
LangChain `create_sql_agent` 기반 초기 프로토타입. ReAct 포맷 파싱 실패율이 높아 db_query_graph.py로 대체됨.
```bash
poetry run python src/db_agent.py                     # 테스트 쿼리
poetry run python src/db_agent.py --interactive       # 대화형 모드
poetry run python src/db_agent.py --analyze pricing   # 판매 가격 분석
```

### src/db_inspector.py - DB 스키마 추출기
세이브 파일(.db)의 전체 스키마를 LLM 프롬프트에 주입 가능한 텍스트로 추출. `db_schema_map.txt` 생성용.
```bash
poetry run python src/db_inspector.py
poetry run python src/db_inspector.py data/save/mysave.db -o data/schema/custom_map.txt
```

### crawler.py - 위키 크롤러
GearCity 위키(wiki.gearcity.info)에서 인게임 플레이 관련 페이지만 BFS로 크롤링.
```bash
poetry run python crawler.py --depth 1 --delay 5
poetry run python crawler.py --no-filter  # 전체 수집
```

### src/test_env.py - 환경 검증
Ollama(Qwen) 연결 + SQLite DB 연결을 테스트하는 Hello World.
```bash
poetry run python src/test_env.py
```

## Development Phases
1. **Phase 1 (완료)**: 환경 구축 + 데이터 분석 - 위키 크롤링, DB 스키마 추출
2. **Phase 2 (현재)**: LangGraph 에이전트 구현 - 멀티스텝 Text-to-SQL (`db_query_graph.py`)
3. **Phase 3**: 자율 플레이 - 전략 수립/실행, 게임 상태 모니터링

## Conventions
- 한국어 주석/문서, 영어 코드
- Poetry로 의존성 관리 (`poetry add`, `poetry run`)
- 데이터 파일은 `data/` 하위에 용도별 분리
- 크롤링 시 15초 딜레이 (위키 서버 부하 방지)
