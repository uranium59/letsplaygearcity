"""
GearCity DB Inspector (LLM System Prompt Generator)
=====================================================
세이브 파일(.db)의 전체 스키마를 LLM이 SQL을 짤 수 있도록
정리된 텍스트 파일로 추출한다.

기존 inspect_db.py와의 차이:
  - LLM 시스템 프롬프트에 바로 주입 가능한 포맷
  - pandas to_markdown으로 깔끔한 샘플 테이블
  - FK 관계, row count 포함

Usage:
    poetry run python src/db_inspector.py
    poetry run python src/db_inspector.py data/save/mysave.db
    poetry run python src/db_inspector.py data/save/mysave.db -o data/schema/custom_map.txt
"""

import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

_db_env = os.getenv("GEARCITY_DB_PATH")
if not _db_env:
    raise EnvironmentError("GEARCITY_DB_PATH 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
DEFAULT_DB_PATH = Path(_db_env)
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "schema" / "db_schema_map.txt"
SAMPLE_ROWS = 3


def find_db_file(path_arg: str | None) -> Path:
    """DB 파일 경로를 결정한다. 인자가 없으면 기본 경로 사용."""
    if path_arg:
        p = Path(path_arg)
        if not p.exists():
            raise FileNotFoundError(f"DB file not found: {p}")
        return p

    if DEFAULT_DB_PATH.exists():
        print(f"Using default: {DEFAULT_DB_PATH}")
        return DEFAULT_DB_PATH

    raise FileNotFoundError(
        f"Default DB not found: {DEFAULT_DB_PATH}\n"
        "Pass the path as an argument: python src/db_inspector.py <path_to_db>"
    )


def get_tables(cursor: sqlite3.Cursor) -> list[str]:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    return [row[0] for row in cursor.fetchall()]


def get_columns(cursor: sqlite3.Cursor, table: str) -> list[dict]:
    cursor.execute(f"PRAGMA table_info('{table}');")
    return [
        {"name": r[1], "type": r[2], "pk": bool(r[5]), "notnull": bool(r[3])}
        for r in cursor.fetchall()
    ]


def get_foreign_keys(cursor: sqlite3.Cursor, table: str) -> list[dict]:
    cursor.execute(f"PRAGMA foreign_key_list('{table}');")
    return [
        {"from": r[3], "to_table": r[2], "to_column": r[4]}
        for r in cursor.fetchall()
    ]


def get_row_count(cursor: sqlite3.Cursor, table: str) -> int:
    cursor.execute(f"SELECT COUNT(*) FROM '{table}';")
    return cursor.fetchone()[0]


def build_schema_doc(db_path: Path, cursor: sqlite3.Cursor, conn: sqlite3.Connection) -> str:
    """LLM 시스템 프롬프트용 스키마 문서를 생성한다."""
    tables = get_tables(cursor)

    lines = [
        "# GearCity Database Schema Map",
        "",
        f"Source: {db_path.name}",
        f"Tables: {len(tables)}",
        "Use this document to construct valid SQL queries against the save file.",
        "",
    ]

    for table in tables:
        columns = get_columns(cursor, table)
        fks = get_foreign_keys(cursor, table)
        row_count = get_row_count(cursor, table)
        fk_map = {fk["from"]: f"-> {fk['to_table']}.{fk['to_column']}" for fk in fks}

        lines.append(f"## Table: {table} ({row_count} rows)")
        lines.append("")

        # 컬럼 정보 한 줄 요약
        col_parts = []
        for c in columns:
            desc = f"{c['name']} ({c['type']})"
            if c["pk"]:
                desc += " [PK]"
            if fk_map.get(c["name"]):
                desc += f" {fk_map[c['name']]}"
            col_parts.append(desc)
        lines.append("- Columns: " + ", ".join(col_parts))
        lines.append("")

        # 샘플 데이터 (pandas to_markdown)
        if row_count > 0:
            try:
                df = pd.read_sql_query(
                    f"SELECT * FROM '{table}' LIMIT {SAMPLE_ROWS}", conn
                )
                # 긴 값 잘라내기
                for col in df.columns:
                    df[col] = df[col].apply(
                        lambda v: str(v)[:80] + "..." if isinstance(v, str) and len(str(v)) > 80 else v
                    )
                lines.append("- Sample Data:")
                lines.append(df.to_markdown(index=False))
                lines.append("")
            except Exception as e:
                lines.append(f"- Error reading data: {e}")
                lines.append("")
        else:
            lines.append("- Sample Data: (Empty Table)")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def inspect(db_path_arg: str | None = None, output_path: str | None = None) -> Path:
    """메인 실행 함수."""
    db_path = find_db_file(db_path_arg)
    out_file = Path(output_path) if output_path else DEFAULT_OUTPUT
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # read-only로 열어서 세이브 파일을 보호
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as e:
        raise ConnectionError(f"Cannot open DB (locked or corrupted?): {e}")

    try:
        cursor = conn.cursor()
        doc = build_schema_doc(db_path, cursor, conn)
        out_file.write_text(doc, encoding="utf-8")

        tables = get_tables(cursor)
        print(f"Done! Schema map saved to: {out_file}")
        print(f"Tables: {len(tables)}")
        print(f"Hint: Open the file and search for 'cash', 'date', 'company' to find key tables.")
        return out_file
    finally:
        conn.close()


if __name__ == "__main__":
    db_arg = sys.argv[1] if len(sys.argv) > 1 else None
    out_arg = None
    if len(sys.argv) > 2 and sys.argv[2] == "-o" and len(sys.argv) > 3:
        out_arg = sys.argv[3]
    inspect(db_arg, out_arg)
