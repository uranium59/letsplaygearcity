"""
Environment Verification Script
================================
Ollama(Qwen) 연결과 SQLite DB 연결을 확인하는 Hello World 테스트.

Usage:
    poetry run python src/test_env.py [path_to_db_file]
"""

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen3:30b")
DEFAULT_DB_PATH = os.getenv("GEARCITY_DB_PATH")


def test_ollama_connection():
    """Ollama 로컬 서버의 Qwen 모델에 간단한 질문을 보내 응답을 확인한다."""
    print("=" * 50)
    print("[Test 1] Ollama / Qwen Connection")
    print("=" * 50)

    try:
        from langchain_ollama import ChatOllama

        llm = ChatOllama(model=MODEL_NAME, temperature=0)
        response = llm.invoke("Who are you? Answer in one sentence.")
        print(f"  Model response: {response.content}")
        print("  [PASS] Ollama connection successful.")
        return True
    except Exception as e:
        print(f"  [FAIL] Ollama connection failed: {e}")
        return False


def test_db_connection(db_path: str | None = None):
    """SQLite DB 파일에 연결하여 테이블 수를 카운트한다."""
    print()
    print("=" * 50)
    print("[Test 2] SQLite DB Connection")
    print("=" * 50)

    if db_path is None:
        if DEFAULT_DB_PATH and Path(DEFAULT_DB_PATH).exists():
            db_path = DEFAULT_DB_PATH
            print(f"  Using GEARCITY_DB_PATH: {db_path}")
        else:
            # fallback: data/save/ 디렉토리에서 .db 파일 자동 탐색
            save_dir = Path(__file__).resolve().parent.parent / "data" / "save"
            db_files = list(save_dir.glob("*.db"))
            if not db_files:
                if not DEFAULT_DB_PATH:
                    print("  [SKIP] GEARCITY_DB_PATH 환경변수가 설정되지 않았습니다.")
                else:
                    print(f"  [SKIP] DB file not found: {DEFAULT_DB_PATH}")
                print(f"  data/save/ 에도 .db 파일이 없습니다.")
                return None
            db_path = str(db_files[0])
            print(f"  Auto-detected: {db_path}")

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        conn.close()

        print(f"  DB file: {db_path}")
        print(f"  Tables found: {len(tables)}")
        if tables:
            for t in tables[:10]:
                print(f"    - {t[0]}")
            if len(tables) > 10:
                print(f"    ... and {len(tables) - 10} more")
        print("  [PASS] DB connection successful.")
        return True
    except Exception as e:
        print(f"  [FAIL] DB connection failed: {e}")
        return False


if __name__ == "__main__":
    db_arg = sys.argv[1] if len(sys.argv) > 1 else None

    print()
    print("GearCity Agent - Environment Check")
    print("=" * 50)
    print()

    ollama_ok = test_ollama_connection()
    db_ok = test_db_connection(db_arg)

    print()
    print("=" * 50)
    print("Summary")
    print("=" * 50)
    print(f"  Ollama: {'PASS' if ollama_ok else 'FAIL'}")
    print(f"  DB:     {'PASS' if db_ok else 'SKIP' if db_ok is None else 'FAIL'}")
    print()
