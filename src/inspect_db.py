"""
GearCity DB Schema Inspector
=============================
GearCity 세이브 파일(.db)을 분석하여 LLM이 이해할 수 있는
데이터베이스 스키마 맵(Markdown)을 생성한다.

Usage:
    poetry run python src/inspect_db.py <path_to_db_file>
    poetry run python src/inspect_db.py data/save/mysave.db
"""

import sqlite3
import sys
from pathlib import Path

# 프로젝트 루트 기준 기본 출력 경로
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "schema" / "gearcity_schema.md"
SAMPLE_ROWS = 5


def get_tables(cursor: sqlite3.Cursor) -> list[str]:
    """DB 내 모든 테이블 이름을 반환한다."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    return [row[0] for row in cursor.fetchall()]


def get_table_info(cursor: sqlite3.Cursor, table: str) -> list[dict]:
    """테이블의 컬럼 정보(이름, 타입, PK 여부 등)를 반환한다."""
    cursor.execute(f"PRAGMA table_info('{table}');")
    columns = []
    for row in cursor.fetchall():
        columns.append({
            "cid": row[0],
            "name": row[1],
            "type": row[2],
            "notnull": bool(row[3]),
            "default": row[4],
            "pk": bool(row[5]),
        })
    return columns


def get_foreign_keys(cursor: sqlite3.Cursor, table: str) -> list[dict]:
    """테이블의 FK 관계를 반환한다."""
    cursor.execute(f"PRAGMA foreign_key_list('{table}');")
    fks = []
    for row in cursor.fetchall():
        fks.append({
            "from": row[3],
            "to_table": row[2],
            "to_column": row[4],
        })
    return fks


def get_row_count(cursor: sqlite3.Cursor, table: str) -> int:
    """테이블의 총 행 수를 반환한다."""
    cursor.execute(f"SELECT COUNT(*) FROM '{table}';")
    return cursor.fetchone()[0]


def get_sample_rows(cursor: sqlite3.Cursor, table: str, limit: int = SAMPLE_ROWS) -> tuple[list[str], list[tuple]]:
    """테이블에서 샘플 데이터를 가져온다. (컬럼명 리스트, 행 리스트) 반환."""
    cursor.execute(f"SELECT * FROM '{table}' LIMIT {limit};")
    col_names = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    return col_names, rows


def format_value(val) -> str:
    """Markdown 테이블에 넣기 적합하도록 값을 문자열로 변환한다."""
    if val is None:
        return "NULL"
    s = str(val)
    if len(s) > 60:
        return s[:57] + "..."
    return s


def build_markdown(db_path: Path, cursor: sqlite3.Cursor) -> str:
    """전체 스키마 정보를 Markdown 문자열로 조합한다."""
    tables = get_tables(cursor)
    lines = [
        f"# GearCity Database Schema",
        f"",
        f"- **Source**: `{db_path.name}`",
        f"- **Tables**: {len(tables)}",
        f"",
        f"---",
        f"",
    ]

    for table in tables:
        columns = get_table_info(cursor, table)
        fks = get_foreign_keys(cursor, table)
        row_count = get_row_count(cursor, table)

        # FK를 빠르게 조회하기 위한 딕셔너리
        fk_map = {fk["from"]: f"{fk['to_table']}.{fk['to_column']}" for fk in fks}

        lines.append(f"## {table} ({row_count} rows)")
        lines.append("")

        # 컬럼 정보 테이블
        lines.append("| # | Column | Type | PK | Not Null | FK Reference |")
        lines.append("|---|--------|------|----|----------|--------------|")
        for col in columns:
            pk_mark = "PK" if col["pk"] else ""
            nn_mark = "Y" if col["notnull"] else ""
            fk_ref = fk_map.get(col["name"], "")
            lines.append(
                f"| {col['cid']} | `{col['name']}` | {col['type']} | {pk_mark} | {nn_mark} | {fk_ref} |"
            )
        lines.append("")

        # 샘플 데이터
        if row_count > 0:
            col_names, rows = get_sample_rows(cursor, table)
            lines.append(f"**Sample Data** (up to {SAMPLE_ROWS} rows):")
            lines.append("")
            header = "| " + " | ".join(f"`{c}`" for c in col_names) + " |"
            separator = "| " + " | ".join("---" for _ in col_names) + " |"
            lines.append(header)
            lines.append(separator)
            for row in rows:
                row_str = "| " + " | ".join(format_value(v) for v in row) + " |"
                lines.append(row_str)
            lines.append("")
        else:
            lines.append("*(empty table)*")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def inspect(db_path: str, output_path: str | None = None) -> Path:
    """
    메인 실행 함수.
    DB 파일을 분석하여 Markdown 스키마 파일을 생성하고 경로를 반환한다.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        raise FileNotFoundError(f"DB file not found: {db_file}")
    if not db_file.suffix == ".db":
        raise ValueError(f"Expected a .db file, got: {db_file.suffix}")

    out_file = Path(output_path) if output_path else DEFAULT_OUTPUT
    out_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    except sqlite3.OperationalError as e:
        raise ConnectionError(f"Cannot open DB (file may be locked or corrupted): {e}")

    try:
        cursor = conn.cursor()
        markdown = build_markdown(db_file, cursor)
        out_file.write_text(markdown, encoding="utf-8")
        print(f"Schema exported to: {out_file}")
        print(f"Tables found: {len(get_tables(cursor))}")
        return out_file
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <path_to_db_file> [output_path]")
        sys.exit(1)

    db_arg = sys.argv[1]
    out_arg = sys.argv[2] if len(sys.argv) > 2 else None
    inspect(db_arg, out_arg)
