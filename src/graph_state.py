"""
GearCity Graph State — TypedDicts + 공유 상수
================================================
모든 노드 모듈이 import하는 기반 모듈.
"""

import operator
from typing import Annotated, TypedDict


# ── 테이블 목록 상수 ─────────────────────────────────────────────

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
