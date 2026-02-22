"""
GearCity Pipeline Nodes — SQL 파이프라인 핵심 노드
===================================================
pre_router, planner, load_schema, sql_generator, executor, router, retry, advance
"""

import re
import sqlite3

import pandas as pd

from src.graph_state import GraphState, SubQuery, CORE_TABLES, MAX_SUB_QUERIES, MAX_RETRIES
from src.prompts import PLANNER_PROMPT, SQL_GENERATOR_PROMPT
from src.queries import CURRENT_YEAR_SQL, CURRENT_TURN_SQL
from src.graph_utils import (
    create_llm, build_table_catalog, extract_table_schemas,
    clean_sql, strip_think_tags,
    LLM_MAX_TOKENS_PLAN, LLM_MAX_TOKENS_SQL,
)
from src.session_memory import get_memory


# ── 사전 라우터 키워드 ─────────────────────────────────────────────

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
        cur.execute(CURRENT_YEAR_SQL)
        year = int(cur.fetchone()[0])
        cur.execute(CURRENT_TURN_SQL)
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


# ── SQL 파이프라인 노드 ──────────────────────────────────────────

def planner_node(state: GraphState) -> dict:
    """질문을 1~5개 서브쿼리로 분해, 필요 테이블 선택."""
    llm = create_llm(temperature=0, max_tokens=LLM_MAX_TOKENS_PLAN)
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


def sql_generator_node(state: GraphState) -> dict:
    """서브쿼리 하나에 대해 SQL 생성."""
    llm = create_llm(temperature=0, max_tokens=LLM_MAX_TOKENS_SQL)
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
