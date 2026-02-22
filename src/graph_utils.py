"""
GearCity Graph Utilities — 스키마 파싱, SQL 정리, LLM 팩토리
=============================================================
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain_ollama import ChatOllama

load_dotenv()

# ── 경로/모델 설정 ───────────────────────────────────────────────

SCHEMA_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "schema" / "db_schema_map.txt"
MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen3:30b")

# ── LLM 토큰 제한 ───────────────────────────────────────────────
# 노드 역할별 최대 출력 토큰 — 무한 생성 루프 방지
# (repeat_penalty=1 + temperature=0 조합에서 EOS 없이 반복 생성되는 문제 차단)

LLM_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
LLM_MAX_TOKENS_SQL = 512       # SQL 생성: SELECT 문 1개
LLM_MAX_TOKENS_PLAN = 1024     # Planner: SUB/TABLES 5개
LLM_MAX_TOKENS_ANALYSIS = 3000  # Analyst/Strategist/Aggregator: 종합 분석
LLM_MAX_TOKENS_CLASSIFY = 32   # Classifier: 단어 1개


def create_llm(temperature: float = 0, max_tokens: int = LLM_MAX_TOKENS_ANALYSIS) -> ChatOllama:
    return ChatOllama(
        model=MODEL_NAME,
        temperature=temperature,
        num_ctx=LLM_NUM_CTX,
        num_predict=max_tokens,
    )


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
