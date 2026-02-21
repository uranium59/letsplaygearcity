"""
GearCity DB Query Graph (LangGraph Multi-Step SQL Agent)
=========================================================
LangGraph StateGraph 기반 멀티스텝 SQL 분석 에이전트.
LLM은 SQL 생성과 데이터 해석만 담당하고, 워크플로우 라우팅은 Python 코드가 담당한다.

Architecture:
    User Question → Planner → Load Schema → SQL Generator → Executor
    → Router (retry/advance/analyst) → Analyst → Classifier
    → (factual/analytical → END)
    → (strategic → Strategist → Evaluator (sequential) → Aggregator → END)

Usage:
    poetry run python src/db_query_graph.py                          # 대화형 모드
    poetry run python src/db_query_graph.py -q "내 현금이 얼마야?"     # 단일 질문
    poetry run python src/db_query_graph.py --test                   # 테스트 쿼리 실행
    poetry run python src/db_query_graph.py "D:\\path\\to\\save.db" -q "..."
"""

import operator
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Annotated, TypedDict

import pandas as pd
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph
from src.design_formulas import (
    EngineParams,
    ChassisParams,
    GearboxParams,
    VehicleParams,
    calc_displacement,
    calc_hp,
    simulate_bore_change,
    simulate_stroke_change,
    calc_staleness,
    compare_ratings,
    check_torque_compatibility,
    estimate_modification_cost,
    format_design_report,
)
from src.event_timeline import get_timeline
from src.session_memory import get_memory, reset_memory, DOMAIN_CONFIG

load_dotenv()

# ── 설정 ─────────────────────────────────────────────────────────
_db_env = os.getenv("GEARCITY_DB_PATH")
if not _db_env:
    raise EnvironmentError("GEARCITY_DB_PATH 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
DEFAULT_DB_PATH = Path(_db_env)
SCHEMA_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "schema" / "db_schema_map.txt"
MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen3:30b")

CORE_TABLES = [
    "GameInfo", "PlayerInfo", "CompanyList", "CarInfo", "CarDistro",
    "FactoryInfo", "CarManufactor", "CitiesInfo",
    "MonthlyFiscalsBreakdown", "YearlyAutoBreakdown",
    "ContractsGranted",
]

DESIGN_TABLES = [
    "CarInfo", "EngineInfo", "ChassisInfo", "GearboxInfo",
    "GameInfo", "PlayerInfo", "Researching",
]

MAX_RETRIES = 2
MAX_SUB_QUERIES = 5

# ── State 스키마 ─────────────────────────────────────────────────

class SubQuery(TypedDict):
    id: int
    question: str
    relevant_tables: list[str]
    sql: str
    result: str
    error: str
    retry_count: int


class StrategyCandidate(TypedDict):
    id: int
    name: str
    description: str
    data_queries: list[str]
    relevant_tables: list[str]


class StrategyEvaluation(TypedDict):
    strategy_id: int
    strategy_name: str
    pros: str
    cons: str
    feasibility: str
    estimated_impact: str
    supporting_data: str
    score: float


class GraphState(TypedDict):
    user_question: str
    db_path: str  # SQLite DB 파일 경로
    sub_queries: list[SubQuery]
    current_index: int
    schema_context: str
    final_answer: str
    max_retries: int
    error_log: list[str]
    # 전략 분석 파이프라인 필드
    question_type: str  # "factual" | "analytical" | "strategic" | "design"
    analyst_summary: str  # analyst의 중간 결과 (downstream 전달용)
    strategy_candidates: list[StrategyCandidate]  # strategist 출력
    strategy_evaluations: Annotated[list[StrategyEvaluation], operator.add]  # 병렬 merge용 reducer
    # 설계 자문 파이프라인 필드
    design_calc_results: str  # Python 계산 결과 (포맷된 텍스트)
    design_context: str  # 설계 관련 추가 SQL 결과
    # 이벤트 예측 파이프라인 필드
    forecast_context: str  # 전쟁/경제 이벤트 예측 + 자산 위험 분석
    # 세션 메모리 필드
    memory_context: str  # 세션 메모리에서 가져온 캐시 컨텍스트


# ── 스키마 파싱 유틸리티 ─────────────────────────────────────────

def build_table_catalog(schema_path: Path = SCHEMA_MAP_PATH) -> str:
    """71개 테이블 요약 카탈로그 (~3KB) — Planner가 테이블 선택에 활용."""
    text = schema_path.read_text(encoding="utf-8")
    # Windows CRLF 통일
    text = text.replace("\r\n", "\n")
    lines = []
    for m in re.finditer(
        r"^## Table: (\S+) \((\d+) rows\)\s*\n\n- Columns: (.+)",
        text,
        re.MULTILINE,
    ):
        name, rows, cols_raw = m.group(1), m.group(2), m.group(3)
        # 컬럼 이름만 추출 (타입/PK 제거)
        col_names = re.findall(r"(\w+) \(", cols_raw)
        lines.append(f"- {name} ({rows} rows): {', '.join(col_names)}")
    return "\n".join(lines)


def extract_table_schemas(
    table_names: list[str], schema_path: Path = SCHEMA_MAP_PATH
) -> str:
    """선택된 테이블의 전체 스키마+샘플 데이터를 추출."""
    text = schema_path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n")
    sections = []
    for tname in table_names:
        # 각 테이블 섹션 추출: ## Table: Name ... 다음 --- 까지
        pattern = rf"(## Table: {re.escape(tname)} \(.+?\n---)"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            sections.append(m.group(1))
    return "\n\n".join(sections)


def clean_sql(raw: str) -> str:
    """LLM 출력에서 SQL만 추출. 마크다운 펜스, <think> 태그, 설명 텍스트 제거."""
    # <think>...</think> 제거
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    # 마크다운 코드 펜스에서 SQL 추출
    fence_match = re.search(r"```(?:sql)?\s*\n?(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1)
    # 앞뒤 공백 제거
    cleaned = cleaned.strip()
    # 여러 SQL 문이 있으면 첫 번째만 사용 (세미콜론 기준)
    if ";" in cleaned:
        cleaned = cleaned.split(";")[0].strip() + ";"
    # SELECT로 시작하지 않으면 SELECT 찾아서 추출
    if not cleaned.upper().startswith("SELECT"):
        select_match = re.search(r"(SELECT\s.+)", cleaned, re.DOTALL | re.IGNORECASE)
        if select_match:
            cleaned = select_match.group(1)
    return cleaned


def strip_think_tags(text: str) -> str:
    """<think>...</think> 태그를 제거한다."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# ── LLM 초기화 ──────────────────────────────────────────────────

def create_llm(temperature: float = 0) -> ChatOllama:
    return ChatOllama(model=MODEL_NAME, temperature=temperature)


# ── 사전 라우터 (키워드 기반, LLM 호출 없음) ──────────────────────

# forecast 키워드: 전쟁, 경제위기, 이벤트 예측, 안전 도시 등
_FORECAST_KW_STRONG = [
    # 강한 시그널 (단독으로 충분)
    "전쟁", "대공황", "세계대전", "safe haven", "safe city", "안전한 도시",
    "world war", "wwi", "wwii", "korean war",
]
_FORECAST_KW_WEAK = [
    # 약한 시그널 (조합 필요)
    "war", "침체", "recession", "depression",
    "유가", "oil", "gas price", "금리", "interest rate",
    "이벤트", "event", "위기", "crisis", "폭등", "폭락",
    "forecast", "예측", "전망", "outlook", "앞으로",
    "위험", "risk", "conflict", "govern", "factor", "공장",
    "경기", "경제", "economy", "recession", "downturn",
]

# design 키워드: 차량/엔진/샤시/기어박스 설계
_DESIGN_KW_STRONG = [
    "보어", "bore", "스트로크", "stroke", "배기량", "displacement",
    "노후", "staleness", "리프레시", "refresh",
    "개선", "modification", "new generation",
]
_DESIGN_KW_WEAK = [
    "마력", "horsepower", "hp", "토크", "torque",
    "샤시", "chassis", "기어박스", "gearbox", "변속기", "transmission",
    "설계", "design", "호환", "compatible", "compatibility",
    "엔진", "engine", "upgrade", "비용", "cost",
    "aging", "component", "부품",
]


def _get_current_turn(db_path: str) -> tuple[int, int]:
    """GameInfo에서 현재 연도/월 조회. 실패 시 (0, 0)."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Year'")
        year = int(cur.fetchone()[0])
        cur.execute("SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Turn'")
        month = int(cur.fetchone()[0])
        conn.close()
        return (year, month)
    except Exception:
        return (0, 0)


def pre_router_node(state: GraphState) -> dict:
    """키워드 기반 사전 분류. forecast/design이면 SQL 파이프라인 우회."""
    # 세션 메모리: 현재 게임 턴 업데이트
    year, month = _get_current_turn(state["db_path"])
    get_memory().update_turn(year, month)

    q = state["user_question"].lower()

    # 강한 키워드 1개 = 2점, 약한 키워드 1개 = 1점
    forecast_score = (
        sum(2 for kw in _FORECAST_KW_STRONG if kw in q)
        + sum(1 for kw in _FORECAST_KW_WEAK if kw in q)
    )
    design_score = (
        sum(2 for kw in _DESIGN_KW_STRONG if kw in q)
        + sum(1 for kw in _DESIGN_KW_WEAK if kw in q)
    )

    # 2점 이상이면 분류 확정
    if forecast_score >= 2 and forecast_score >= design_score:
        return {"question_type": "forecast"}
    if design_score >= 2 and design_score > forecast_score:
        return {"question_type": "design"}

    # 매치 부족 → SQL 파이프라인으로 진행 (기존 경로)
    return {"question_type": ""}


def pre_router_router(state: GraphState) -> str:
    """사전 분류 결과에 따라 직행 또는 SQL 파이프라인으로 라우팅."""
    qtype = state.get("question_type", "")
    if qtype == "forecast":
        return "forecast_advisor"
    if qtype == "design":
        return "design_advisor"
    return "planner"


# ── 노드 함수들 ─────────────────────────────────────────────────

PLANNER_PROMPT = """\
You are a database query planner for the game GearCity.
Your job is to break down the user's question into 1-5 sub-queries that can each be answered with a single SQL query.

## Available Tables (71 total)
{catalog}

## KEY SCHEMA HINTS
- PlayerInfo is a KEY-VALUE table: Player_Varible / Player_Data. Rows: Company_Name, Player_Name, Company_ID.
  → Player company ID: SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID'
- GameInfo is a KEY-VALUE table: GameInfo_Varible / GameInfo_Data. Rows include: Current_Year, Current_Turn (= current month 1-12, since 1 turn = 1 month), Starting_Year.
- CompanyList: ID = company ID, COMPANY_NAME, FUNDS_ONHAND = cash.
- CarInfo: Car_ID, Company_ID, Name, Trim, CarType, sellprice, unitcost, sold_all_time, Rating_Overall.
- CarDistro: per-city sales. Company_ID, City_ID, Car_ID, SellPrice, Sold_This_Month, Possible_Sales.
- NOTE: In GearCity, 1 turn = 1 month. "Current_Turn" means current month (1-12) within Current_Year.
- FactoryInfo: Factory_ID, Company_ID, City_ID, CarsInProduction, MaxCarsInProduction.
- CarManufactor: production lines per factory. Factory_ID, Lines, Car_ID, Current_Employees, Unit_Cost.
- CitiesInfo: City_ID, City_NAME, City_COUNTRY, City_POPULATION.
- ContractRequests: available contract opportunities. Active, ProjectName, CustomerName, Units, UnitsPerMonth, UnitCosts, VehicleType. Filter: Active = 1.
- ContractsGranted: awarded contracts in progress. CompID, ProjectName, UnitPrice, UnitsMovedMonth, UnitsMovedTotal, UnitsNeeded, Active, Penalty.
  → Player contracts: WHERE CompID = (SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID')
- ContractCustomers: contract customer profiles with spec requirements (HP, weight, fuel, engine size limits). IsMilitary flag.
- CarInfo has license/rebadge columns: Creator_ID (original designer), RoyalityComp/RoyalityPayment (royalty), RebadgeBuyFromCompID/RebadgeBuyPrice (rebadge purchase), OutSourced_Units/OutSourced_Income (outsourcing).
  → Licensed cars: WHERE Creator_ID != Company_ID OR RoyalityComp != -1
  → Rebadged cars: WHERE RebadgeBuyFromCompID != -1

## Previously Retrieved Information (from this session)
{memory_context}

Use this cached data to avoid redundant queries. If the cached data already answers
a sub-question, you can skip that sub-query or reduce the number of sub-queries needed.

## User Question
{question}

## Output Format (STRICTLY follow this format, one sub-query per line)
SUB1: <sub-question in English>
TABLES1: <comma-separated table names>
SUB2: <sub-question in English>
TABLES2: <comma-separated table names>
...

Output ONLY the sub-queries. No explanations, no markdown, no extra text.
If the question is simple enough for one query, output just SUB1/TABLES1."""


def planner_node(state: GraphState) -> dict:
    """질문을 1~5개 서브쿼리로 분해, 필요 테이블 선택."""
    llm = create_llm(temperature=0)
    catalog = build_table_catalog()

    memory = get_memory()
    mem_ctx = memory.format_context()

    prompt = PLANNER_PROMPT.format(
        catalog=catalog,
        question=state["user_question"],
        memory_context=mem_ctx if mem_ctx else "(No cached data)",
    )
    response = llm.invoke(prompt)
    raw = strip_think_tags(response.content)

    # 파싱: SUB1: ... / TABLES1: ... 패턴
    sub_queries: list[SubQuery] = []
    sub_matches = re.findall(r"SUB(\d+):\s*(.+)", raw)
    table_matches = re.findall(r"TABLES(\d+):\s*(.+)", raw)

    table_map = {}
    for idx_str, tables_str in table_matches:
        table_map[idx_str] = [t.strip() for t in tables_str.split(",") if t.strip()]

    for idx_str, question in sub_matches:
        tables = table_map.get(idx_str, CORE_TABLES[:5])
        sub_queries.append(SubQuery(
            id=int(idx_str),
            question=question.strip(),
            relevant_tables=tables,
            sql="",
            result="",
            error="",
            retry_count=0,
        ))

    # 파싱 실패 시 폴백: 전체 질문을 단일 쿼리로
    if not sub_queries:
        sub_queries.append(SubQuery(
            id=1,
            question=state["user_question"],
            relevant_tables=CORE_TABLES,
            sql="",
            result="",
            error="",
            retry_count=0,
        ))

    # 최대 5개로 제한
    sub_queries = sub_queries[:MAX_SUB_QUERIES]

    return {"sub_queries": sub_queries, "current_index": 0, "memory_context": mem_ctx}


def load_schema_node(state: GraphState) -> dict:
    """현재 서브쿼리에 필요한 테이블 스키마를 추출."""
    idx = state["current_index"]
    sq = state["sub_queries"][idx]
    schema_text = extract_table_schemas(sq["relevant_tables"])
    if not schema_text:
        # 테이블을 찾지 못하면 코어 테이블로 폴백
        schema_text = extract_table_schemas(CORE_TABLES)
    return {"schema_context": schema_text}


SQL_GENERATOR_PROMPT = """\
You are a SQLite SQL expert for the game GearCity.
Write a single SELECT query to answer the question below.

## Database Schema
{schema}

## KEY RULES
- Output ONLY the raw SQL. No markdown fences, no explanation, no comments.
- Use LIMIT 20 unless the question needs all rows.
- PlayerInfo is KEY-VALUE: SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID'
- GameInfo is KEY-VALUE: SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Year'
- Current_Turn in GameInfo = current month (1-12). 1 turn = 1 month in GearCity.
- To filter by player company, use subquery: Company_ID = (SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID')
- ContractRequests: Active contracts available for bidding. Filter Active = 1.
- ContractsGranted: Awarded contracts. Filter by player company same as CarInfo.
- License/rebadge in CarInfo: RoyalityComp != -1 means licensed, RebadgeBuyFromCompID != -1 means rebadged.

## Question
{question}
{error_context}
## SQL"""


def sql_generator_node(state: GraphState) -> dict:
    """서브쿼리 하나에 대해 SQL 생성."""
    llm = create_llm(temperature=0)
    idx = state["current_index"]
    sq = state["sub_queries"][idx]

    error_context = ""
    if sq["error"]:
        error_context = f"\n## Previous Error (fix this)\n{sq['error']}\n"

    prompt = SQL_GENERATOR_PROMPT.format(
        schema=state["schema_context"],
        question=sq["question"],
        error_context=error_context,
    )
    response = llm.invoke(prompt)
    raw = strip_think_tags(response.content)
    sql = clean_sql(raw)

    # sub_queries 업데이트 (불변 리스트이므로 새로 생성)
    updated = list(state["sub_queries"])
    updated[idx] = {**updated[idx], "sql": sql}
    return {"sub_queries": updated}


def executor_node(state: GraphState) -> dict:
    """SQLite에서 SQL 실행 (read-only), 결과 or 에러 수집."""
    idx = state["current_index"]
    sq = state["sub_queries"][idx]
    sql = sq["sql"]

    updated = list(state["sub_queries"])
    error_log = list(state.get("error_log", []))

    if not sql or not sql.strip():
        updated[idx] = {**updated[idx], "error": "Empty SQL generated", "result": ""}
        error_log.append(f"Sub{sq['id']}: Empty SQL")
        return {"sub_queries": updated, "error_log": error_log}

    try:
        conn = sqlite3.connect(f"file:{state['db_path']}?mode=ro", uri=True)
        df = pd.read_sql_query(sql, conn)
        conn.close()

        if df.empty:
            result_str = "(No results)"
        else:
            # 최대 30행으로 제한
            result_str = df.head(30).to_markdown(index=False)

        updated[idx] = {**updated[idx], "result": result_str, "error": ""}
        return {"sub_queries": updated, "error_log": error_log}

    except Exception as e:
        err_msg = str(e)
        updated[idx] = {**updated[idx], "error": err_msg, "result": ""}
        error_log.append(f"Sub{sq['id']} (try {sq['retry_count'] + 1}): {err_msg}")
        return {"sub_queries": updated, "error_log": error_log}


def router_node(state: GraphState) -> str:
    """에러 → retry / 다음 서브쿼리 → advance / 전부 완료 → analyst."""
    idx = state["current_index"]
    sq = state["sub_queries"][idx]

    # 에러가 있고 재시도 여유가 있으면 retry
    if sq["error"] and sq["retry_count"] < state.get("max_retries", MAX_RETRIES):
        return "retry"

    # 다음 서브쿼리가 있으면 advance
    if idx + 1 < len(state["sub_queries"]):
        return "advance"

    # 모두 완료
    return "analyst"


def retry_node(state: GraphState) -> dict:
    """재시도: retry_count 증가 후 다시 SQL Generator로."""
    idx = state["current_index"]
    updated = list(state["sub_queries"])
    updated[idx] = {**updated[idx], "retry_count": updated[idx]["retry_count"] + 1}
    return {"sub_queries": updated}


def advance_node(state: GraphState) -> dict:
    """다음 서브쿼리로 이동."""
    return {"current_index": state["current_index"] + 1}


ANALYST_PROMPT = """\
You are a GearCity business analyst AI.
The user asked: "{question}"

## Previously Known Information
{memory_context}

Below are the results from database queries. Analyze them and provide a clear, comprehensive answer.

{results_section}

{errors_section}

Provide your analysis in a clear format. Use bullet points or tables where helpful.
Answer in the same language as the user's question.
Keep the response concise but thorough."""


CLASSIFIER_PROMPT = """\
You are a question classifier for a GearCity business analysis system.
Classify the user's question into exactly one of five categories:

- **factual**: Simple data lookup (e.g., "How much cash do I have?", "What year is it?")
- **analytical**: Data comparison or trend analysis, but no strategic recommendation needed (e.g., "Compare margins by car model", "Show sales trends")
- **strategic**: Requires strategic recommendations, action plans, or "what should I do?" decisions (e.g., "How can I improve profitability?", "Should I expand to new cities?")
- **design**: Questions about vehicle/component design parameters, "what if" simulations, modification/improvement costs, staleness/aging analysis, or design refresh timing (e.g., "What if I increase bore by 5mm?", "How much to upgrade my car?", "How old are my components?", "Is my engine torque compatible with the gearbox?")
- **forecast**: Questions about future wars, economic crises, global events, or risk to player assets from upcoming conflicts (e.g., "Will there be a war soon?", "Is my factory safe?", "When is the next recession?", "Which cities will be affected by war?", "What global events are coming?")

## User Question
{question}

## Analyst Summary
{analyst_summary}

Output ONLY one word: factual, analytical, strategic, design, or forecast
No explanations, no extra text."""


STRATEGIST_PROMPT = """\
You are a strategic advisor for GearCity, a car company management simulation game.
Based on the analyst's data summary, generate 2-4 distinct strategic options the player could pursue.
IMPORTANT: Consider upcoming global events (wars, recessions) when formulating strategies.

## User Question
{question}

## Data Analysis Summary
{analyst_summary}

## Upcoming Global Events (next 15 years)
{event_forecast}

## Available Tables for Further Analysis
{catalog}

## Output Format (STRICTLY follow this — one strategy per block)
STRATEGY1_NAME: <short name>
STRATEGY1_DESC: <1-2 sentence description>
STRATEGY1_QUERIES: <comma-separated data questions to validate this strategy>
STRATEGY1_TABLES: <comma-separated table names needed>

STRATEGY2_NAME: <short name>
STRATEGY2_DESC: <1-2 sentence description>
STRATEGY2_QUERIES: <comma-separated data questions to validate this strategy>
STRATEGY2_TABLES: <comma-separated table names needed>

(up to STRATEGY4)

Output ONLY the strategies. No explanations, no markdown, no extra text."""


EVALUATOR_SQL_PROMPT = """\
You are a SQLite SQL expert for the game GearCity.
Write a single SELECT query to answer the question below.

## Database Schema
{schema}

## KEY RULES
- Output ONLY the raw SQL. No markdown fences, no explanation, no comments.
- Use LIMIT 20 unless the question needs all rows.
- PlayerInfo is KEY-VALUE: SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID'
- GameInfo is KEY-VALUE: SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Year'
- Current_Turn in GameInfo = current month (1-12). 1 turn = 1 month in GearCity.
- To filter by player company, use subquery: Company_ID = (SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID')

## Question
{question}

## SQL"""


EVALUATOR_PROMPT = """\
You are evaluating a specific strategy for a GearCity player.

## User Question
{question}

## Strategy: {strategy_name}
{strategy_description}

## Data Analysis (from earlier queries)
{analyst_summary}

## Additional Data (from strategy-specific queries)
{additional_data}

## Evaluation Criteria
Evaluate this strategy on these dimensions:
1. PROS: Key advantages
2. CONS: Key risks/downsides
3. FEASIBILITY: How easy to implement (HIGH/MEDIUM/LOW)
4. IMPACT: Expected profit/growth impact (HIGH/MEDIUM/LOW)
5. SCORE: Overall score 1-10

## Output Format (STRICTLY follow this)
PROS: <bullet points separated by semicolons>
CONS: <bullet points separated by semicolons>
FEASIBILITY: <HIGH/MEDIUM/LOW with brief reason>
IMPACT: <HIGH/MEDIUM/LOW with brief reason>
SCORE: <number 1-10>

Output ONLY the evaluation. No extra text."""


AGGREGATOR_PROMPT = """\
You are a senior strategic advisor for GearCity.
Compare the evaluated strategies below and provide a final recommendation.

## User Question
{question}

## Data Analysis Summary
{analyst_summary}

## Strategy Evaluations
{evaluations_section}

## Instructions
1. Compare all strategies side-by-side
2. Rank them by overall value (considering score, feasibility, and impact)
3. Provide a clear final recommendation with reasoning
4. Suggest a prioritized action plan

Answer in the same language as the user's question.
Be specific and actionable. Reference the data to support your recommendations."""


def analyst_node(state: GraphState) -> dict:
    """수집된 모든 결과를 종합 분석, 최종 답변 생성."""
    llm = create_llm(temperature=0.3)

    results_parts = []
    errors_parts = []
    for sq in state["sub_queries"]:
        header = f"### Sub-query {sq['id']}: {sq['question']}"
        if sq["result"]:
            results_parts.append(f"{header}\n```sql\n{sq['sql']}\n```\n{sq['result']}")
        elif sq["error"]:
            errors_parts.append(f"{header}\nSQL: {sq['sql']}\nError: {sq['error']}")

    results_section = "\n\n".join(results_parts) if results_parts else "(No successful results)"
    errors_section = ""
    if errors_parts:
        errors_section = "## Failed Queries\n" + "\n\n".join(errors_parts)

    # 세션 메모리 컨텍스트 주입
    memory = get_memory()
    mem_ctx = memory.format_context()

    prompt = ANALYST_PROMPT.format(
        question=state["user_question"],
        results_section=results_section,
        errors_section=errors_section,
        memory_context=mem_ctx if mem_ctx else "(No cached data)",
    )
    response = llm.invoke(prompt)
    answer = strip_think_tags(response.content)

    # 서브쿼리에서 사용된 테이블 수집 → 도메인별로 분류하여 캐시 저장
    all_tables: set[str] = set()
    for sq in state["sub_queries"]:
        all_tables.update(sq.get("relevant_tables", []))

    domains = memory._classify_tables(list(all_tables))
    for domain in domains:
        domain_tables = DOMAIN_CONFIG[domain]["tables"] & all_tables
        domain_results = []
        for sq in state["sub_queries"]:
            if set(sq.get("relevant_tables", [])) & domain_tables and sq["result"]:
                domain_results.append(f"Q: {sq['question']}\n{sq['result']}")
        if domain_results:
            memory.put(domain, "\n\n".join(domain_results), domain_tables)

    return {"final_answer": answer, "analyst_summary": answer}


# ── 전략 분석 파이프라인 노드 ─────────────────────────────────────


def classifier_node(state: GraphState) -> dict:
    """질문 유형 분류: factual / analytical / strategic."""
    llm = create_llm(temperature=0)
    prompt = CLASSIFIER_PROMPT.format(
        question=state["user_question"],
        analyst_summary=state.get("analyst_summary", ""),
    )
    response = llm.invoke(prompt)
    raw = strip_think_tags(response.content).strip().lower()

    # robust 파싱: forecast/design/strategic/analytical/factual 키워드 탐색
    if "forecast" in raw:
        qtype = "forecast"
    elif "design" in raw:
        qtype = "design"
    elif "strategic" in raw:
        qtype = "strategic"
    elif "analytical" in raw:
        qtype = "analytical"
    else:
        qtype = "factual"

    return {"question_type": qtype}


def classifier_router(state: GraphState) -> str:
    """forecast → forecast_advisor, design → design_advisor, strategic → strategist, 나머지 → END."""
    if state.get("question_type") == "forecast":
        return "forecast_advisor"
    if state.get("question_type") == "design":
        return "design_advisor"
    if state.get("question_type") == "strategic":
        return "strategist"
    return END


def strategist_node(state: GraphState) -> dict:
    """전략 후보 2~4개 생성."""
    llm = create_llm(temperature=0.5)
    catalog = build_table_catalog()

    # 이벤트 예측 컨텍스트 주입
    event_forecast = "(이벤트 데이터 없음)"
    try:
        tl = get_timeline()
        # DB에서 현재 연도 조회
        conn = sqlite3.connect(f"file:{state['db_path']}?mode=ro", uri=True)
        cursor = conn.execute(
            "SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Year';"
        )
        row = cursor.fetchone()
        conn.close()
        current_year = int(row[0]) if row else 1900
        event_forecast = tl.format_forecast_summary(current_year, lookahead=15)
    except Exception:
        pass

    prompt = STRATEGIST_PROMPT.format(
        question=state["user_question"],
        analyst_summary=state.get("analyst_summary", ""),
        event_forecast=event_forecast,
        catalog=catalog,
    )
    response = llm.invoke(prompt)
    raw = strip_think_tags(response.content)

    # 파싱: STRATEGY1_NAME/DESC/QUERIES/TABLES 패턴
    candidates: list[StrategyCandidate] = []
    for i in range(1, 5):
        name_m = re.search(rf"STRATEGY{i}_NAME:\s*(.+)", raw)
        desc_m = re.search(rf"STRATEGY{i}_DESC:\s*(.+)", raw)
        queries_m = re.search(rf"STRATEGY{i}_QUERIES:\s*(.+)", raw)
        tables_m = re.search(rf"STRATEGY{i}_TABLES:\s*(.+)", raw)

        if name_m and desc_m:
            queries = [q.strip() for q in (queries_m.group(1) if queries_m else "").split(",") if q.strip()]
            tables = [t.strip() for t in (tables_m.group(1) if tables_m else "").split(",") if t.strip()]
            candidates.append(StrategyCandidate(
                id=i,
                name=name_m.group(1).strip(),
                description=desc_m.group(1).strip(),
                data_queries=queries if queries else [state["user_question"]],
                relevant_tables=tables if tables else CORE_TABLES[:5],
            ))

    # 파싱 실패 시 단일 일반 전략 fallback
    if not candidates:
        candidates.append(StrategyCandidate(
            id=1,
            name="General Improvement",
            description="Analyze current performance and suggest general improvements.",
            data_queries=[state["user_question"]],
            relevant_tables=CORE_TABLES,
        ))

    return {"strategy_candidates": candidates}


def strategy_evaluator_node(state: GraphState) -> dict:
    """모든 전략 후보를 순차 평가. (Send() 병렬 실행 시 GPU 경쟁→데드락 방지)

    각 전략에 대해: 추가 SQL 1개 실행 + LLM 평가를 순차적으로 수행한다.
    """
    candidates = state.get("strategy_candidates", [])
    db_path = state["db_path"]
    analyst_summary = state.get("analyst_summary", "")
    all_evaluations: list[StrategyEvaluation] = []

    for strategy in candidates:
        # 추가 데이터 수집: 전략별 SQL 최대 1개
        additional_data_parts = []
        schema_text = extract_table_schemas(strategy["relevant_tables"])
        if not schema_text:
            schema_text = extract_table_schemas(CORE_TABLES)

        llm = create_llm(temperature=0)
        for query_text in strategy["data_queries"][:1]:
            # SQL 생성
            sql_prompt = EVALUATOR_SQL_PROMPT.format(
                schema=schema_text,
                question=query_text,
            )
            sql_response = llm.invoke(sql_prompt)
            sql_raw = strip_think_tags(sql_response.content)
            sql = clean_sql(sql_raw)

            if not sql or not sql.strip():
                continue

            # SQL 실행
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                df = pd.read_sql_query(sql, conn)
                conn.close()
                if df.empty:
                    result_str = "(No results)"
                else:
                    result_str = df.head(20).to_markdown(index=False)
                additional_data_parts.append(f"Q: {query_text}\n{result_str}")
            except Exception:
                additional_data_parts.append(f"Q: {query_text}\n(Query failed)")

        additional_data = "\n\n".join(additional_data_parts) if additional_data_parts else "(No additional data)"

        # LLM 평가
        eval_llm = create_llm(temperature=0.3)
        eval_prompt = EVALUATOR_PROMPT.format(
            question=state["user_question"],
            strategy_name=strategy["name"],
            strategy_description=strategy["description"],
            analyst_summary=analyst_summary,
            additional_data=additional_data,
        )
        eval_response = eval_llm.invoke(eval_prompt)
        eval_raw = strip_think_tags(eval_response.content)

        # 파싱
        pros = _extract_field(eval_raw, "PROS", "N/A")
        cons = _extract_field(eval_raw, "CONS", "N/A")
        feasibility = _extract_field(eval_raw, "FEASIBILITY", "MEDIUM")
        impact = _extract_field(eval_raw, "IMPACT", "MEDIUM")
        score_str = _extract_field(eval_raw, "SCORE", "5")
        try:
            score = float(re.search(r"[\d.]+", score_str).group())
        except (AttributeError, ValueError):
            score = 5.0

        all_evaluations.append(StrategyEvaluation(
            strategy_id=strategy["id"],
            strategy_name=strategy["name"],
            pros=pros,
            cons=cons,
            feasibility=feasibility,
            estimated_impact=impact,
            supporting_data=additional_data,
            score=score,
        ))

    return {"strategy_evaluations": all_evaluations}


def _extract_field(text: str, field_name: str, default: str) -> str:
    """평가 출력에서 필드 값 추출."""
    m = re.search(rf"{field_name}:\s*(.+?)(?:\n[A-Z_]+:|$)", text, re.DOTALL)
    return m.group(1).strip() if m else default


def aggregator_node(state: GraphState) -> dict:
    """전략 평가를 종합 비교, 우선순위 매기기, 최종 답변 생성."""
    evaluations = state.get("strategy_evaluations", [])

    # 평가 결과가 없으면 analyst_summary + 경고 반환
    if not evaluations:
        warning = "\n\n⚠️ 전략 평가를 수행하지 못했습니다. 위의 분석 결과를 참고해 주세요."
        return {"final_answer": state.get("analyst_summary", "") + warning}

    # 점수 기준 정렬
    sorted_evals = sorted(evaluations, key=lambda e: e["score"], reverse=True)

    # 평가 섹션 구성
    eval_sections = []
    for rank, ev in enumerate(sorted_evals, 1):
        section = (
            f"### #{rank}: {ev['strategy_name']} (Score: {ev['score']}/10)\n"
            f"- **Pros**: {ev['pros']}\n"
            f"- **Cons**: {ev['cons']}\n"
            f"- **Feasibility**: {ev['feasibility']}\n"
            f"- **Impact**: {ev['estimated_impact']}\n"
            f"- **Supporting Data**: {ev['supporting_data']}"
        )
        eval_sections.append(section)
    evaluations_section = "\n\n".join(eval_sections)

    llm = create_llm(temperature=0.3)
    prompt = AGGREGATOR_PROMPT.format(
        question=state["user_question"],
        analyst_summary=state.get("analyst_summary", ""),
        evaluations_section=evaluations_section,
    )
    response = llm.invoke(prompt)
    answer = strip_think_tags(response.content)
    return {"final_answer": answer}


# ── 설계 자문 파이프라인 ──────────────────────────────────────────

DESIGN_ADVISOR_PROMPT = """\
You are a GearCity vehicle design advisor with deep knowledge of game mechanics.
Use the Python-calculated data below AND your knowledge of design formulas to give precise, actionable advice.

## Key Design Formulas (reference)
- Displacement: CC = 0.7854 * (bore_cm)^2 * stroke_cm * cylinders
- HP = (torque * rpm) / 5252
- Bore ↑ → displacement ↑ → torque ↑ → HP ↑ (fuel economy ↓)
- Stroke ↑ → displacement ↑ + torque ↑, but RPM ↓ (net HP may vary)

## Modification Cost Rules
- New Generation (no component change): 15% of original design cost
- + Gearbox change: +5% (total 20%)
- + Engine change: +5% + auto gearbox 5% (total 25%)
- + Engine & Gearbox: +10% (total 25%)
- Chassis change: 100% (full redesign cost)

## Staleness Thresholds
- Vehicle: safe under ~5 years, penalty starts at age+4 > 9
- Components (engine/chassis/gearbox): safe under 12 years, steep after 15
- Combined staleness > 1.0 → buyer rating divided by staleness^1.2

## Torque Compatibility
- Engine torque > gearbox max torque → quality/reliability penalty
- Always check headroom when changing engines

## Rating Interpretation
- Static = at design time, Current = now (with tech progression)
- Negative delta = design is falling behind current technology

## User Question
{question}

## Analyst Summary (from SQL data)
{analyst_summary}

## Python Calculation Results
{calc_results}

## Additional Design Data (from SQL)
{design_context}

Instructions:
1. Reference the specific numbers from calculations (don't re-calculate)
2. Give concrete recommendations with expected numeric outcomes
3. Prioritize by cost-effectiveness (biggest improvement per dollar)
4. Warn about any compatibility issues or urgent staleness
5. Answer in the same language as the user's question."""


def design_advisor_node(state: GraphState) -> dict:
    """설계 자문 노드: SQL 데이터 수집 → Python 계산 → LLM 합성."""
    db_path = state["db_path"]
    analyst_summary = state.get("analyst_summary", "")

    # ── Step 1: 추가 SQL — 플레이어 차량+엔진+샤시+기어박스 JOIN ──
    design_sql = """\
SELECT
    c.Car_ID, c.Name, c.Trim, c.CarType, c.YearBuilt AS car_year,
    c.designcost AS car_designcost, c.ModAmount, c.ParentCarID,
    c.Engine_ID, c.Chassis_ID, c.Gearbox_ID,
    c.Spec_HP, c.Spec_Torque, c.Spec_RPM, c.Spec_Weight,
    c.Spec_TopSpeed, c.Spec_Fuel,
    c.Spec_AccellerationSix, c.Spec_AccellerationHund,
    c.Rating_Performance, c.Rating_Drivability, c.Rating_Luxury, c.Rating_Safety,
    e.bore, e.stroke, e.CylinderNumberForCalculations AS cylinders,
    e.hp AS engine_hp, e.torque AS engine_torque, e.rpm AS engine_rpm,
    e.weight AS engine_weight, e.size_cc, e.fuelmilage,
    e.yearbuilt AS engine_year, e.ModYear AS engine_mod_year, e.designcost AS engine_designcost,
    e.StaticenginePower, e.StaticengineFuelEco, e.StaticengineReliability, e.StaticRating_Smooth,
    e.enginePower, e.engineFuelEco, e.engineReliability, e.Rating_Smooth,
    ch.ChassisWeightKG, ch.ChassisLengthCM, ch.ChassisWidthCM,
    ch.YearBuilt AS chassis_year, ch.ModYear AS chassis_mod_year, ch.Design_Cost AS chassis_designcost,
    ch.StaticOverallStrength, ch.StaticOverallComfort, ch.StaticOverallPerformance, ch.StaticOverallDependabilty,
    ch.Overall_Strength, ch.Overall_Comfort, ch.Overall_Performance, ch.Overall_Dependabilty,
    g.Gears, g.GearboxType, g.LoRatio, g.HiRatio, g.MaxTorqueInput, g.Weight AS gearbox_weight,
    g.YearBuilt AS gearbox_year, g.ModYear AS gearbox_mod_year, g.Design_Cost AS gearbox_designcost,
    g.StaticPowerRating, g.StaticFuelRating, g.StaticPerformanceRating,
    g.StaticReliabiltyRating, g.StaticComfortRating,
    g.PowerRating, g.FuelRating, g.PerformanceRating, g.ReliabiltyRating, g.ComfortRating
FROM CarInfo c
JOIN EngineInfo e ON c.Engine_ID = e.Engine_ID
JOIN ChassisInfo ch ON c.Chassis_ID = ch.Chassis_ID
JOIN GearboxInfo g ON c.Gearbox_ID = g.Gearbox_ID
WHERE c.Company_ID = (SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID')
  AND c.Status = 0
LIMIT 20;
"""
    # 현재 연도 조회
    year_sql = "SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Year';"

    design_context = ""
    rows = []
    current_year = 1900

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        # 현재 연도
        cursor = conn.execute(year_sql)
        year_row = cursor.fetchone()
        if year_row:
            try:
                current_year = int(year_row[0])
            except (ValueError, TypeError):
                pass

        # 차량 데이터
        cursor = conn.execute(design_sql)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if rows:
            df = pd.DataFrame(rows)
            design_context = df.to_markdown(index=False)
        else:
            design_context = "(플레이어 소유 활성 차량 없음)"

    except Exception as e:
        design_context = f"(SQL 오류: {e})"

    # ── Step 2: Python 계산 ──
    calc_results = ""
    try:
        all_reports = []
        for row in rows:
            # 데이터클래스 구성
            engine = EngineParams(
                engine_id=row.get("Engine_ID", 0),
                bore=row.get("bore", 0) or 0,
                stroke=row.get("stroke", 0) or 0,
                cylinders=row.get("cylinders", 0) or 0,
                hp=row.get("engine_hp", 0) or 0,
                torque=row.get("engine_torque", 0) or 0,
                rpm=row.get("engine_rpm", 0) or 0,
                weight=row.get("engine_weight", 0) or 0,
                size_cc=row.get("size_cc", 0) or 0,
                fuel_milage=row.get("fuelmilage", 0) or 0,
                year_built=row.get("engine_year", 0) or 0,
                mod_year=row.get("engine_mod_year", 0) or 0,
                design_cost=row.get("engine_designcost", 0) or 0,
                static_power=row.get("StaticenginePower", 0) or 0,
                static_fuel_eco=row.get("StaticengineFuelEco", 0) or 0,
                static_reliability=row.get("StaticengineReliability", 0) or 0,
                static_smooth=row.get("StaticRating_Smooth", 0) or 0,
                current_power=row.get("enginePower", 0) or 0,
                current_fuel_eco=row.get("engineFuelEco", 0) or 0,
                current_reliability=row.get("engineReliability", 0) or 0,
                current_smooth=row.get("Rating_Smooth", 0) or 0,
            )

            vehicle = VehicleParams(
                car_id=row.get("Car_ID", 0),
                name=row.get("Name", ""),
                trim=row.get("Trim", ""),
                car_type=row.get("CarType", ""),
                year_built=row.get("car_year", 0) or 0,
                design_cost=row.get("car_designcost", 0) or 0,
                mod_amount=row.get("ModAmount", 0) or 0,
                parent_car_id=row.get("ParentCarID", -1) or -1,
                engine_id=row.get("Engine_ID", 0),
                chassis_id=row.get("Chassis_ID", 0),
                gearbox_id=row.get("Gearbox_ID", 0),
                spec_hp=row.get("Spec_HP", 0) or 0,
                spec_torque=row.get("Spec_Torque", 0) or 0,
                spec_rpm=row.get("Spec_RPM", 0) or 0,
                spec_weight=row.get("Spec_Weight", 0) or 0,
                spec_top_speed=row.get("Spec_TopSpeed", 0) or 0,
                spec_fuel=row.get("Spec_Fuel", 0) or 0,
                rating_performance=row.get("Rating_Performance", 0) or 0,
                rating_drivability=row.get("Rating_Drivability", 0) or 0,
                rating_luxury=row.get("Rating_Luxury", 0) or 0,
                rating_safety=row.get("Rating_Safety", 0) or 0,
            )

            # 노후화
            engine_effective_year = engine.mod_year if engine.mod_year > engine.year_built else engine.year_built
            chassis_year = row.get("chassis_year", 0) or 0
            chassis_mod_year = row.get("chassis_mod_year", 0) or 0
            chassis_effective = chassis_mod_year if chassis_mod_year > chassis_year else chassis_year
            gearbox_year = row.get("gearbox_year", 0) or 0
            gearbox_mod_year = row.get("gearbox_mod_year", 0) or 0
            gearbox_effective = gearbox_mod_year if gearbox_mod_year > gearbox_year else gearbox_year

            staleness = calc_staleness(
                current_year, vehicle.year_built,
                engine_effective_year, chassis_effective, gearbox_effective,
            )

            # 개선 비용 (4가지 시나리오)
            mod_base = estimate_modification_cost(vehicle.design_cost)
            mod_engine = estimate_modification_cost(vehicle.design_cost, engine_change=True)
            mod_gearbox = estimate_modification_cost(vehicle.design_cost, gearbox_change=True)
            mod_chassis = estimate_modification_cost(vehicle.design_cost, chassis_change=True)
            mod_costs = {
                "cost_breakdown_text": (
                    f"기본 New Gen: ${mod_base['estimated_cost']:,} ({mod_base['total_percent']}%)\n"
                    f"+ 엔진 변경: ${mod_engine['estimated_cost']:,} ({mod_engine['total_percent']}%)\n"
                    f"+ 기어박스만: ${mod_gearbox['estimated_cost']:,} ({mod_gearbox['total_percent']}%)\n"
                    f"+ 샤시 변경: ${mod_chassis['estimated_cost']:,} ({mod_chassis['total_percent']}%)"
                ),
            }

            # 토크 호환성
            torque_check = check_torque_compatibility(
                engine.torque, row.get("MaxTorqueInput", 0) or 0,
            )

            # 엔진 레이팅 변화
            engine_rating_deltas = compare_ratings(
                {"Power": engine.static_power, "FuelEco": engine.static_fuel_eco,
                 "Reliability": engine.static_reliability, "Smooth": engine.static_smooth},
                {"Power": engine.current_power, "FuelEco": engine.current_fuel_eco,
                 "Reliability": engine.current_reliability, "Smooth": engine.current_smooth},
            )

            # 샤시 레이팅 변화
            chassis_rating_deltas = compare_ratings(
                {"Strength": row.get("StaticOverallStrength", 0) or 0,
                 "Comfort": row.get("StaticOverallComfort", 0) or 0,
                 "Performance": row.get("StaticOverallPerformance", 0) or 0,
                 "Dependability": row.get("StaticOverallDependabilty", 0) or 0},
                {"Strength": row.get("Overall_Strength", 0) or 0,
                 "Comfort": row.get("Overall_Comfort", 0) or 0,
                 "Performance": row.get("Overall_Performance", 0) or 0,
                 "Dependability": row.get("Overall_Dependabilty", 0) or 0},
            )

            # 보어 시뮬레이션 (+5mm)
            bore_sim = None
            if engine.bore > 0:
                bore_sim = simulate_bore_change(engine, engine.bore + 5)

            report = format_design_report(
                vehicle=vehicle,
                staleness=staleness,
                mod_costs=mod_costs,
                torque_check=torque_check,
                rating_deltas={**engine_rating_deltas, **chassis_rating_deltas},
                bore_sim=bore_sim,
            )
            all_reports.append(f"--- {vehicle.name} {vehicle.trim} (ID: {vehicle.car_id}) ---\n{report}")

        calc_results = "\n\n".join(all_reports) if all_reports else "(계산 대상 차량 없음)"

    except Exception as e:
        calc_results = f"(Python 계산 오류: {e})"

    # ── Step 3: LLM 합성 ──
    llm = create_llm(temperature=0.3)
    prompt = DESIGN_ADVISOR_PROMPT.format(
        question=state["user_question"],
        analyst_summary=analyst_summary,
        calc_results=calc_results,
        design_context=design_context if len(design_context) < 8000 else design_context[:8000] + "\n...(truncated)",
    )
    response = llm.invoke(prompt)
    answer = strip_think_tags(response.content)

    # 세션 메모리에 설계 결과 캐시
    get_memory().put("vehicle_design", calc_results)

    return {
        "final_answer": answer,
        "design_calc_results": calc_results,
        "design_context": design_context,
    }


# ── 이벤트 예측 파이프라인 ─────────────────────────────────────────

FORECAST_ADVISOR_PROMPT = """\
You are a GearCity strategic forecaster with access to the game's complete historical event timeline.
GearCity simulates real-world history: wars, recessions, oil crises all happen at historically accurate times.

## Key Game Mechanics for Wars
- **TOTAL_WAR** (gov=-2): No sales possible, factories may be damaged/destroyed
- **WAR** (gov=-1): No sales possible in that city
- **LIMITED** (gov=0): Sales reduced by 50%
- **STABLE** (gov=1): Normal operations

## Key Game Mechanics for Economy
- **buyrate**: Global demand multiplier. 1.0 = normal, < 0.90 = recession, < 0.80 = depression
- **gas**: Fuel price. > 2.0 = expensive, affects fuel-efficient car demand
- **interest**: Loan interest multiplier. > 1.06 = expensive borrowing
- **stockrate**: Stock market multiplier. < 0.90 = market crash

## User Question
{question}

## Analyst Summary (from SQL data)
{analyst_summary}

## Event Forecast (from TurnEvents.xml)
{forecast_summary}

## Player Asset Risk Analysis
{asset_risk_report}

## Instructions
1. Directly answer the user's question about future events, wars, or economic outlook
2. Be SPECIFIC about dates: exact years and months when events start/end
3. If the player has assets in at-risk cities, prioritize warning about those
4. Recommend concrete actions: when to sell factories, when to build in safe cities, when to stockpile cash
5. For economic events, suggest timing for expansion vs. conservation
6. Answer in the same language as the user's question
7. Reference the specific data (don't generalize - use exact numbers and dates)"""


def forecast_advisor_node(state: GraphState) -> dict:
    """이벤트 예측 노드: 타임라인 데이터 로드 → 플레이어 자산 위험 분석 → LLM 합성."""
    db_path = state["db_path"]
    analyst_summary = state.get("analyst_summary", "")

    # ── Step 1: 현재 연도 + 플레이어 자산 도시 목록 조회 ──
    current_year = 1900
    current_month = 1
    player_city_ids = []

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

        # 현재 연도/월
        cursor = conn.execute(
            "SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Year';"
        )
        row = cursor.fetchone()
        if row:
            try:
                current_year = int(row[0])
            except (ValueError, TypeError):
                pass

        cursor = conn.execute(
            "SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Turn';"
        )
        row = cursor.fetchone()
        if row:
            try:
                current_month = int(row[0])
            except (ValueError, TypeError):
                pass

        # 플레이어 공장/지점 도시 목록
        company_id_sql = "SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID'"
        cursor = conn.execute(f"""
            SELECT DISTINCT City_ID FROM FactoryInfo
            WHERE Company_ID = ({company_id_sql})
            UNION
            SELECT DISTINCT City_ID FROM CarDistro
            WHERE Company_ID = ({company_id_sql}) AND Sold_This_Month > 0
        """)
        player_city_ids = [r[0] for r in cursor.fetchall()]
        conn.close()

    except Exception:
        pass  # 조회 실패 시 빈 목록으로 진행

    # ── Step 2: 타임라인 데이터 로드 + 분석 ──
    forecast_summary = ""
    asset_risk_report = ""

    try:
        tl = get_timeline()
        forecast_summary = tl.format_forecast_summary(current_year, lookahead=15)

        if player_city_ids:
            risks = tl.check_player_asset_risks(player_city_ids, current_year, lookahead=15)
            asset_risk_report = tl.format_asset_risk_report(risks, current_year)
        else:
            asset_risk_report = "(플레이어 자산 도시 정보 없음 — 아직 공장/판매점이 없거나 게임 초기 상태)"

    except Exception as e:
        forecast_summary = f"(타임라인 데이터 로드 실패: {e})"
        asset_risk_report = "(위험 분석 불가)"

    # ── Step 3: LLM 합성 ──
    llm = create_llm(temperature=0.3)
    prompt = FORECAST_ADVISOR_PROMPT.format(
        question=state["user_question"],
        analyst_summary=analyst_summary,
        forecast_summary=forecast_summary,
        asset_risk_report=asset_risk_report,
    )
    response = llm.invoke(prompt)
    answer = strip_think_tags(response.content)

    # 세션 메모리에 예측 결과 캐시
    get_memory().put("forecast", forecast_summary + "\n\n" + asset_risk_report)

    return {
        "final_answer": answer,
        "forecast_context": forecast_summary + "\n\n" + asset_risk_report,
    }


# ── 그래프 구성 ──────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """LangGraph StateGraph를 구성한다."""
    graph = StateGraph(GraphState)

    # 노드 등록
    graph.add_node("planner", planner_node)
    graph.add_node("load_schema", load_schema_node)
    graph.add_node("sql_generator", sql_generator_node)
    graph.add_node("executor", executor_node)
    graph.add_node("retry", retry_node)
    graph.add_node("advance", advance_node)
    graph.add_node("analyst", analyst_node)

    # 전략 분석 파이프라인 노드
    graph.add_node("classifier", classifier_node)
    graph.add_node("strategist", strategist_node)
    graph.add_node("strategy_evaluator", strategy_evaluator_node)
    graph.add_node("aggregator", aggregator_node)

    # 설계 자문 파이프라인 노드
    graph.add_node("design_advisor", design_advisor_node)

    # 이벤트 예측 파이프라인 노드
    graph.add_node("forecast_advisor", forecast_advisor_node)

    # 사전 라우터 (키워드 기반, LLM 호출 없음)
    graph.add_node("pre_router", pre_router_node)

    # 엣지 연결
    graph.set_entry_point("pre_router")

    # pre_router: forecast/design → 직행, 나머지 → planner (SQL 파이프라인)
    graph.add_conditional_edges("pre_router", pre_router_router, {
        "forecast_advisor": "forecast_advisor",
        "design_advisor": "design_advisor",
        "planner": "planner",
    })
    graph.add_edge("planner", "load_schema")
    graph.add_edge("load_schema", "sql_generator")
    graph.add_edge("sql_generator", "executor")

    # Router: executor 후 조건부 라우팅
    graph.add_conditional_edges(
        "executor",
        router_node,
        {
            "retry": "retry",
            "advance": "advance",
            "analyst": "analyst",
        },
    )

    # retry → load_schema (스키마 다시 로드 후 SQL 재생성)
    graph.add_edge("retry", "load_schema")

    # advance → load_schema (다음 서브쿼리용 스키마 로드)
    graph.add_edge("advance", "load_schema")

    # analyst → classifier (전략 분석 파이프라인 진입)
    graph.add_edge("analyst", "classifier")

    # classifier: forecast/design/strategic → 전용 노드, 나머지 → END
    graph.add_conditional_edges("classifier", classifier_router, {
        "forecast_advisor": "forecast_advisor",
        "design_advisor": "design_advisor",
        "strategist": "strategist",
        END: END,
    })

    # forecast_advisor → END
    graph.add_edge("forecast_advisor", END)

    # design_advisor → END
    graph.add_edge("design_advisor", END)

    # strategist → evaluator (순차) → aggregator → END
    graph.add_edge("strategist", "strategy_evaluator")
    graph.add_edge("strategy_evaluator", "aggregator")
    graph.add_edge("aggregator", END)

    return graph


# ── 실행 함수 ────────────────────────────────────────────────────

import time as _time

def _format_node_progress(node_name: str, state: dict) -> str | None:
    """각 노드 완료 시 출력할 요약 메시지. None이면 출력 안 함."""
    if node_name == "pre_router":
        qtype = state.get("question_type", "")
        mem = get_memory()
        cached_domains = [d for d in mem._cache if mem._cache[d].is_valid(mem._current_turn)]
        cache_str = f" | 캐시: {', '.join(cached_domains)}" if cached_domains else ""
        if qtype:
            return f"사전분류: {qtype} → 전용 파이프라인 직행{cache_str}"
        return f"사전분류: SQL 파이프라인 진입{cache_str}"

    if node_name == "planner":
        sqs = state.get("sub_queries", [])
        if sqs:
            labels = [f"  {sq['id']}. {sq['question']}" for sq in sqs]
            tables_all = set()
            for sq in sqs:
                tables_all.update(sq.get("relevant_tables", []))
            return (
                f"계획 완료: 서브쿼리 {len(sqs)}개\n"
                + "\n".join(labels)
                + f"\n  테이블: {', '.join(sorted(tables_all))}"
            )
        return None

    if node_name == "load_schema":
        ctx = state.get("schema_context", "")
        # 테이블 이름 추출
        tables = re.findall(r"## Table: (\S+)", ctx)
        return f"스키마 로드: {', '.join(tables)}" if tables else None

    if node_name == "sql_generator":
        idx = state.get("current_index", 0)
        sqs = state.get("sub_queries", [])
        if idx < len(sqs):
            sq = sqs[idx]
            sql = sq.get("sql", "")
            sql_preview = sql[:120].replace("\n", " ") + ("..." if len(sql) > 120 else "")
            return f"SQL 생성 ({idx+1}/{len(sqs)}): {sql_preview}"
        return None

    if node_name == "executor":
        idx = state.get("current_index", 0)
        sqs = state.get("sub_queries", [])
        if idx < len(sqs):
            sq = sqs[idx]
            if sq.get("error"):
                return f"SQL 실행 실패 ({idx+1}/{len(sqs)}): {sq['error'][:80]}"
            result = sq.get("result", "")
            rows = result.count("\n") - 1 if result and result != "(No results)" else 0
            return f"SQL 실행 완료 ({idx+1}/{len(sqs)}): {max(0,rows)}행 반환"
        return None

    if node_name == "retry":
        idx = state.get("current_index", 0)
        sqs = state.get("sub_queries", [])
        if idx < len(sqs):
            return f"재시도 ({sqs[idx].get('retry_count',0)}/{MAX_RETRIES})"
        return None

    if node_name == "advance":
        idx = state.get("current_index", 0)
        total = len(state.get("sub_queries", []))
        return f"다음 서브쿼리로 이동 ({idx}/{total})"

    if node_name == "analyst":
        summary = state.get("analyst_summary", "")
        preview = summary[:150].replace("\n", " ") + ("..." if len(summary) > 150 else "")
        return f"분석 완료: {preview}"

    if node_name == "classifier":
        return f"질문 유형: {state.get('question_type', '?')}"

    if node_name == "strategist":
        candidates = state.get("strategy_candidates", [])
        if candidates:
            names = [f"  {c['id']}. {c['name']}" for c in candidates]
            return f"전략 후보 {len(candidates)}개 생성:\n" + "\n".join(names)
        return None

    if node_name == "strategy_evaluator":
        evals = state.get("strategy_evaluations", [])
        if evals:
            lines = [f"  {ev['strategy_name']}: {ev['score']}/10" for ev in evals]
            return f"전략 평가 완료 ({len(evals)}개, 순차):\n" + "\n".join(lines)
        return None

    if node_name == "aggregator":
        return "전략 종합 비교 완료"

    if node_name == "design_advisor":
        return "설계 자문 완료"

    if node_name == "forecast_advisor":
        return "이벤트 예측 완료"

    return None


def run_query(question: str, db_path: Path, verbose: bool = False) -> str:
    """질문을 받아 최종 답변을 반환한다."""
    if not db_path.exists():
        raise FileNotFoundError(f"DB file not found: {db_path}")
    if not SCHEMA_MAP_PATH.exists():
        raise FileNotFoundError(f"Schema map not found: {SCHEMA_MAP_PATH}")

    graph = build_graph()
    app = graph.compile()

    initial_state: GraphState = {
        "user_question": question,
        "db_path": str(db_path),
        "sub_queries": [],
        "current_index": 0,
        "schema_context": "",
        "final_answer": "",
        "max_retries": MAX_RETRIES,
        "error_log": [],
        "question_type": "",
        "analyst_summary": "",
        "strategy_candidates": [],
        "strategy_evaluations": [],
        "design_calc_results": "",
        "design_context": "",
        "forecast_context": "",
        "memory_context": "",
    }

    if not verbose:
        result = app.invoke(initial_state)
        return result["final_answer"]

    # ── verbose 모드: stream으로 노드별 진행 상황 출력 ──
    _write = lambda s: (
        sys.stdout.buffer.write(s.encode("utf-8", errors="replace")),
        sys.stdout.buffer.flush(),
    )
    step = 0
    t0 = _time.time()
    last_state = initial_state

    for chunk in app.stream(initial_state, stream_mode="updates"):
        for node_name, state_update in chunk.items():
            step += 1
            elapsed = _time.time() - t0
            # state 병합 (stream은 delta만 반환)
            last_state = {**last_state, **state_update}
            msg = _format_node_progress(node_name, last_state)
            if msg:
                header = f"[{elapsed:5.1f}s] Step {step}: {node_name}"
                _write(f"\033[90m{header}\033[0m\n")
                for line in msg.split("\n"):
                    _write(f"\033[90m  {line}\033[0m\n")
                _write("\n")

    total = _time.time() - t0
    _write(f"\033[90m[{total:.1f}s] 완료 ({step} steps)\033[0m\n\n")
    return last_state.get("final_answer", "")


# ── 테스트 쿼리 ──────────────────────────────────────────────────

TEST_QUERIES = [
    {"label": "Q1. 현재 게임 날짜와 현금", "query": "현재 게임 연도와 월, 그리고 내 회사의 현금 보유액을 알려줘."},
    {"label": "Q2. 가장 많이 팔린 차", "query": "내 회사에서 역대 가장 많이 팔린 자동차 모델 상위 5개를 알려줘."},
    {"label": "Q3. 공장 현황", "query": "내 공장 목록과 각 공장의 위치, 생산 라인 수를 알려줘."},
    {"label": "Q4. 복합 분석", "query": "내 회사의 차종별 월 판매량과 마진율을 비교 분석해줘."},
    {"label": "Q5. 전략 분석", "query": "수익성을 높이려면 어떻게 해야 할까? 가격, 생산, 판매 전략을 종합적으로 분석해줘."},
    {"label": "Q6. 확장 전략", "query": "새로운 도시로 확장해야 할까, 아니면 기존 시장에서 점유율을 높여야 할까?"},
    {"label": "Q7. 보어 변경 시뮬레이션", "query": "내 엔진의 보어를 5mm 늘리면 마력이 얼마나 올라?"},
    {"label": "Q8. 개선 비용 추정", "query": "내 차를 개선(새 세대)하면 비용이 얼마나 들어? 엔진도 바꾸면?"},
    {"label": "Q9. 노후화 분석", "query": "내 차와 부품들이 얼마나 오래됐어? 언제 리프레시해야 해?"},
    {"label": "Q10. 종합 개선 추천", "query": "내 차의 성능을 개선하려면 어떤 부품을 바꾸는 게 가장 효율적이야?"},
    {"label": "Q11. 토크 호환성", "query": "내 엔진 토크가 변속기 최대 토크보다 큰 차가 있어?"},
    {"label": "Q12. 전쟁 예측", "query": "앞으로 전쟁이 일어날 도시가 있어? 내 공장이 위험한 곳에 있어?"},
    {"label": "Q13. 경제 전망", "query": "앞으로 경기 침체나 유가 폭등이 언제 오는지 알려줘."},
    {"label": "Q14. 안전 도시", "query": "전쟁이 절대 일어나지 않는 안전한 도시는 어디야?"},
    {"label": "Q15. 확장+이벤트", "query": "새 공장을 지을 도시를 추천해줘. 전쟁 위험과 경제 전망을 고려해서."},
]


def run_tests(db_path: Path, verbose: bool = False):
    """사전 정의된 테스트 질문을 실행한다."""
    for t in TEST_QUERIES:
        print(f"\n{'=' * 60}")
        print(f">>> {t['label']}")
        print(f"    {t['query']}")
        print(f"{'=' * 60}")
        try:
            answer = run_query(t["query"], db_path, verbose=verbose)
            print(f"\n{answer}")
        except Exception as e:
            print(f"\nError: {e}")
        print()


def run_interactive(db_path: Path, verbose: bool = True):
    """대화형 모드: 사용자가 자유롭게 질문한다."""
    reset_memory()  # 새 세션 시작
    v_label = " (verbose)" if verbose else ""
    print(f"\n[대화형 모드{v_label}] 질문을 입력하세요 (quit으로 종료).")
    print("한국어/영어 모두 가능합니다.\n")
    while True:
        try:
            question = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in ("quit", "exit", "q"):
            break
        try:
            print()
            answer = run_query(question, db_path, verbose=verbose)
            # Windows cp949 인코딩 문제 방지
            sys.stdout.buffer.write(f"Agent> {answer}\n\n".encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        except Exception as e:
            print(f"\nError: {e}\n")


# ── CLI ──────────────────────────────────────────────────────────

def main():
    db_path = DEFAULT_DB_PATH
    question = None
    test_mode = False
    verbose = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("-q", "--query") and i + 1 < len(args):
            question = args[i + 1]
            i += 1
        elif args[i] == "--test":
            test_mode = True
        elif args[i] in ("-v", "--verbose"):
            verbose = True
        elif not args[i].startswith("-"):
            db_path = Path(args[i])
        i += 1

    print(f"DB: {db_path}")
    print(f"Model: {MODEL_NAME}")
    print(f"Schema: {SCHEMA_MAP_PATH}")

    if not db_path.exists():
        print(f"Error: DB file not found: {db_path}")
        sys.exit(1)
    if not SCHEMA_MAP_PATH.exists():
        print(f"Error: Schema map not found: {SCHEMA_MAP_PATH}")
        sys.exit(1)

    # 스키마 카탈로그 확인
    catalog = build_table_catalog()
    table_count = catalog.count("\n") + 1
    print(f"Tables in catalog: {table_count}")
    print()

    if test_mode:
        run_tests(db_path, verbose=verbose)
    elif question:
        reset_memory()
        print(f"Question: {question}\n")
        answer = run_query(question, db_path, verbose=verbose or True)
        sys.stdout.buffer.write(answer.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()
    else:
        run_interactive(db_path, verbose=True)


if __name__ == "__main__":
    main()
