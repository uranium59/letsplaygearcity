"""
GearCity Analysis Nodes — 분석 + 전략 파이프라인 노드
=====================================================
analyst, classifier, strategist, aggregator
"""

import re
import sqlite3

from langgraph.graph import END

from src.graph_state import GraphState, StrategyCandidate, CORE_TABLES
from src.prompts import ANALYST_PROMPT, CLASSIFIER_PROMPT, STRATEGIST_PROMPT, AGGREGATOR_PROMPT
from src.queries import CURRENT_YEAR_SQL
from src.graph_utils import (
    create_llm, build_table_catalog, strip_think_tags,
    LLM_MAX_TOKENS_CLASSIFY,
)
from src.session_memory import get_memory, DOMAIN_CONFIG
from src.event_timeline import get_timeline


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
    """질문 유형 분류: factual / analytical / strategic / design / forecast."""
    llm = create_llm(temperature=0, max_tokens=LLM_MAX_TOKENS_CLASSIFY)
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
        cursor = conn.execute(CURRENT_YEAR_SQL)
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


def aggregator_node(state: GraphState) -> dict:
    """전략 후보를 analyst_summary 데이터로 직접 비교 → 최종 추천. (LLM 1회)

    기존 evaluator 단계(전략별 SQL+LLM 평가)를 제거하고,
    이미 수집된 analyst_summary만으로 전략을 비교/추천한다.
    Qwen 30B 로컬 환경에서 evaluator 병목(전략당 2+ LLM 호출)을 방지.
    """
    candidates = state.get("strategy_candidates", [])
    analyst_summary = state.get("analyst_summary", "")

    if not candidates:
        return {"final_answer": analyst_summary}

    # 전략 후보 섹션 구성
    strategy_sections = []
    for c in candidates:
        strategy_sections.append(f"### Strategy {c['id']}: {c['name']}\n{c['description']}")
    strategies_text = "\n\n".join(strategy_sections)

    llm = create_llm(temperature=0.3)
    prompt = AGGREGATOR_PROMPT.format(
        question=state["user_question"],
        analyst_summary=analyst_summary,
        evaluations_section=strategies_text,
    )
    response = llm.invoke(prompt)
    answer = strip_think_tags(response.content)
    return {"final_answer": answer}
