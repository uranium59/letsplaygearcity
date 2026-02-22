"""
GearCity DB Query Graph (LangGraph Multi-Step SQL Agent)
=========================================================
LangGraph StateGraph 기반 멀티스텝 SQL 분석 에이전트.
LLM은 SQL 생성과 데이터 해석만 담당하고, 워크플로우 라우팅은 Python 코드가 담당한다.

Architecture:
    User Question → Pre-Router → (forecast/design 직행 or SQL 파이프라인)
    SQL Pipeline: Planner → Load Schema → SQL Generator → Executor
    → Router (retry/advance/analyst) → Analyst → Classifier
    → (factual/analytical → END)
    → (strategic → Strategist → Aggregator → END)
    → (design → Design Advisor → END)
    → (forecast → Forecast Advisor → END)

Usage:
    poetry run python src/db_query_graph.py                          # 대화형 모드
    poetry run python src/db_query_graph.py -q "내 현금이 얼마야?"     # 단일 질문
    poetry run python src/db_query_graph.py --test                   # 테스트 쿼리 실행
    poetry run python src/db_query_graph.py "D:\\path\\to\\save.db" -q "..."
"""

import os
import re
import sys
import time as _time
from pathlib import Path

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

from src.graph_state import GraphState, MAX_RETRIES
from src.graph_utils import build_table_catalog, MODEL_NAME, SCHEMA_MAP_PATH
from src.session_memory import get_memory, reset_memory
from src.nodes_pipeline import (
    pre_router_node, pre_router_router,
    planner_node, load_schema_node, sql_generator_node,
    executor_node, router_node, retry_node, advance_node,
)
from src.nodes_analysis import (
    analyst_node, classifier_node, classifier_router,
    strategist_node, aggregator_node,
)
from src.nodes_advisors import design_advisor_node, forecast_advisor_node

load_dotenv()

# ── 설정 ─────────────────────────────────────────────────────────
_db_env = os.getenv("GEARCITY_DB_PATH")
if not _db_env:
    raise EnvironmentError("GEARCITY_DB_PATH 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
DEFAULT_DB_PATH = Path(_db_env)


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

    # strategist → aggregator (evaluator 제거: analyst 데이터로 직접 비교)
    graph.add_edge("strategist", "aggregator")
    graph.add_edge("aggregator", END)

    return graph


# ── 실행 함수 ────────────────────────────────────────────────────

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
