"""
GearCity DB Query Graph (LangGraph Multi-Step SQL Agent)
=========================================================
LangGraph StateGraph 기반 멀티스텝 SQL 분석 에이전트.
LLM은 SQL 생성과 데이터 해석만 담당하고, 워크플로우 라우팅은 Python 코드가 담당한다.

Architecture:
    User Question → Planner → Load Schema → SQL Generator → Executor
    → Router (retry/advance/analyst) → Analyst → END

Usage:
    poetry run python src/db_query_graph.py                          # 대화형 모드
    poetry run python src/db_query_graph.py -q "내 현금이 얼마야?"     # 단일 질문
    poetry run python src/db_query_graph.py --test                   # 테스트 쿼리 실행
    poetry run python src/db_query_graph.py "D:\\path\\to\\save.db" -q "..."
"""

import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import TypedDict

import pandas as pd
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

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


class GraphState(TypedDict):
    user_question: str
    db_path: str  # SQLite DB 파일 경로
    sub_queries: list[SubQuery]
    current_index: int
    schema_context: str
    final_answer: str
    max_retries: int
    error_log: list[str]


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


# ── 노드 함수들 ─────────────────────────────────────────────────

PLANNER_PROMPT = """\
You are a database query planner for the game GearCity.
Your job is to break down the user's question into 1-5 sub-queries that can each be answered with a single SQL query.

## Available Tables (71 total)
{catalog}

## KEY SCHEMA HINTS
- PlayerInfo is a KEY-VALUE table: Player_Varible / Player_Data. Rows: Company_Name, Player_Name, Company_ID.
  → Player company ID: SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID'
- GameInfo is a KEY-VALUE table: GameInfo_Varible / GameInfo_Data. Rows include: Current_Year, Current_Turn, Starting_Year.
- CompanyList: ID = company ID, COMPANY_NAME, FUNDS_ONHAND = cash.
- CarInfo: Car_ID, Company_ID, Name, Trim, CarType, sellprice, unitcost, sold_all_time, Rating_Overall.
- CarDistro: per-city sales. Company_ID, City_ID, Car_ID, SellPrice, Sold_This_Month, Possible_Sales.
- FactoryInfo: Factory_ID, Company_ID, City_ID, CarsInProduction, MaxCarsInProduction.
- CarManufactor: production lines per factory. Factory_ID, Lines, Car_ID, Current_Employees, Unit_Cost.
- CitiesInfo: City_ID, City_NAME, City_COUNTRY, City_POPULATION.

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

    prompt = PLANNER_PROMPT.format(
        catalog=catalog,
        question=state["user_question"],
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

    return {"sub_queries": sub_queries, "current_index": 0}


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
- To filter by player company, use subquery: Company_ID = (SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID')

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

Below are the results from database queries. Analyze them and provide a clear, comprehensive answer.

{results_section}

{errors_section}

Provide your analysis in a clear format. Use bullet points or tables where helpful.
Answer in the same language as the user's question.
Keep the response concise but thorough."""


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

    prompt = ANALYST_PROMPT.format(
        question=state["user_question"],
        results_section=results_section,
        errors_section=errors_section,
    )
    response = llm.invoke(prompt)
    answer = strip_think_tags(response.content)
    return {"final_answer": answer}


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

    # 엣지 연결
    graph.set_entry_point("planner")
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

    # analyst → END
    graph.add_edge("analyst", END)

    return graph


# ── 실행 함수 ────────────────────────────────────────────────────

def run_query(question: str, db_path: Path) -> str:
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
    }

    result = app.invoke(initial_state)
    return result["final_answer"]


# ── 테스트 쿼리 ──────────────────────────────────────────────────

TEST_QUERIES = [
    {"label": "Q1. 현재 게임 날짜와 현금", "query": "현재 게임 연도와 턴, 그리고 내 회사의 현금 보유액을 알려줘."},
    {"label": "Q2. 가장 많이 팔린 차", "query": "내 회사에서 역대 가장 많이 팔린 자동차 모델 상위 5개를 알려줘."},
    {"label": "Q3. 공장 현황", "query": "내 공장 목록과 각 공장의 위치, 생산 라인 수를 알려줘."},
    {"label": "Q4. 복합 분석", "query": "내 회사의 차종별 월 판매량과 마진율을 비교 분석해줘."},
]


def run_tests(db_path: Path):
    """사전 정의된 테스트 질문을 실행한다."""
    for t in TEST_QUERIES:
        print(f"\n{'=' * 60}")
        print(f">>> {t['label']}")
        print(f"    {t['query']}")
        print(f"{'=' * 60}")
        try:
            answer = run_query(t["query"], db_path)
            print(f"\n{answer}")
        except Exception as e:
            print(f"\nError: {e}")
        print()


def run_interactive(db_path: Path):
    """대화형 모드: 사용자가 자유롭게 질문한다."""
    print("\n[대화형 모드] 질문을 입력하세요 (quit으로 종료).")
    print("한국어/영어 모두 가능합니다.\n")
    while True:
        try:
            question = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in ("quit", "exit", "q"):
            break
        try:
            print("\n분석 중...\n")
            answer = run_query(question, db_path)
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

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("-q", "--query") and i + 1 < len(args):
            question = args[i + 1]
            i += 1
        elif args[i] == "--test":
            test_mode = True
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
        run_tests(db_path)
    elif question:
        print(f"Question: {question}\n")
        print("분석 중...\n")
        answer = run_query(question, db_path)
        sys.stdout.buffer.write(answer.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()
    else:
        run_interactive(db_path)


if __name__ == "__main__":
    main()
