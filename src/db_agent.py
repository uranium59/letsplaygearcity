"""
GearCity DB Agent (Text-to-SQL Prototype)
==========================================
Qwen 30B가 자연어 질문을 받아 직접 SQL을 생성하고 실행하는 프로토타입.
LangChain SQLDatabase + Ollama를 연결하여 "눈(Eyes)" 역할을 수행한다.

Usage:
    poetry run python src/db_agent.py                     # 기본 테스트 쿼리 실행
    poetry run python src/db_agent.py --interactive       # 대화형 모드
    poetry run python src/db_agent.py --analyze pricing   # 판매 가격 분석
    poetry run python src/db_agent.py "D:\\path\\to\\save.db"
"""

import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_ollama import ChatOllama

load_dotenv()

_db_env = os.getenv("GEARCITY_DB_PATH")
if not _db_env:
    raise EnvironmentError("GEARCITY_DB_PATH 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
DEFAULT_DB_PATH = Path(_db_env)
MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen3:30b")

# ── 시스템 프롬프트 힌트 (개선점 1·2·3) ─────────────────────────
AGENT_PREFIX = """\
You are an agent designed to interact with a SQL database for the game GearCity.
Given an input question, create a syntactically correct SQLite query, execute it,
and return the answer.

IMPORTANT RULES:
- NEVER wrap your SQL in markdown code fences (```). Output raw SQL only.
- When using sql_db_query or sql_db_query_checker, provide ONLY the SQL statement.
- Unless the user specifies a row limit, always LIMIT to at most 20 results.

KEY SCHEMA HINTS (read carefully):
1. PlayerInfo and GameInfo are KEY-VALUE tables (not normal tables).
   - PlayerInfo columns: Player_Varible (VARCHAR), Player_Data (VARCHAR)
     Rows: Company_Name / Player_Name / Company_ID
     → To get the player company ID: SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID'
   - GameInfo columns: GameInfo_Varible (VARCHAR), GameInfo_Data (VARCHAR)
     Rows include: Current_Year / Current_Turn / Starting_Year
     → To get the current year: SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Year'

2. CompanyList is the master company table (301 rows).
   - ID = company identifier, COMPANY_NAME = name, FUNDS_ONHAND = cash balance
   - The player's company has ID = (value from PlayerInfo Company_ID)

3. Factory & Production Lines:
   - FactoryInfo: Factory_ID, Company_ID, City_ID, CarsInProduction, MaxCarsInProduction
   - CarManufactor: actual production lines per factory.
     Columns include: Factory_ID, Lines, Speed, Car_ID, Current_Employees, Unit_Cost
     → Number of production lines in a factory = COUNT of rows in CarManufactor for that Factory_ID
     → The 'Lines' column = number of assembly lines allocated to each car.

4. Car & Sales:
   - CarInfo: Car_ID, Company_ID, Name, Trim, CarType, sellprice, unitcost, sold_all_time, sold_this_month, sold_last_year, Rating_Overall
   - CarDistro: per-city sales distribution. Company_ID, City_ID, Car_ID, Car_Name, SellPrice, Sold_This_Month, Possible_Sales
   - MonthlyAutoBreakdown: monthly sales aggregates (CompanyID, CarID, Sales, Income, Year, Month)
   - YearlyAutoBreakdown: yearly sales aggregates
   - HistoricalReportPlayerSales: player's detailed sales history per turn/city

5. Cities: CitiesInfo with City_ID, City_NAME, City_COUNTRY, City_POPULATION
"""

# 테스트 질문 (영어로 해야 SQL 생성 정확도가 높음)
TEST_QUERIES = [
    {
        "label": "Q1. 현재 게임 날짜와 현금 보유량",
        "query": (
            "What is the current game date (year and month) and the player company's "
            "cash balance? Look in tables related to game state, player, or company finances."
        ),
    },
    {
        "label": "Q2. 가장 많이 팔린 자동차 모델",
        "query": (
            "Which car model has the highest total unit sales? "
            "Check tables related to vehicle sales or production history."
        ),
    },
    {
        "label": "Q3. 보유 공장 목록과 생산 라인 수",
        "query": (
            "List all factories owned by the player, their locations, "
            "and the number of production lines in each factory."
        ),
    },
]


# ── SQL Agent (단순 질의용) ──────────────────────────────────────

def create_agent(db_path: Path):
    """DB와 LLM을 연결한 SQL Agent를 생성한다."""
    if not db_path.exists():
        raise FileNotFoundError(f"DB file not found: {db_path}")

    db = SQLDatabase.from_uri(
        f"sqlite:///{db_path}",
        sample_rows_in_table_info=3,
    )

    llm = ChatOllama(model=MODEL_NAME, temperature=0)

    agent = create_sql_agent(
        llm=llm,
        db=db,
        prefix=AGENT_PREFIX,
        verbose=True,
        agent_executor_kwargs={"handle_parsing_errors": True},
    )

    return agent, db, llm


def run_test_queries(agent):
    """사전 정의된 테스트 질문을 실행한다."""
    for t in TEST_QUERIES:
        print(f"\n{'='*60}")
        print(f">>> {t['label']}")
        print(f"{'='*60}")
        try:
            response = agent.invoke(t["query"])
            print(f"\nAnswer: {response['output']}")
        except Exception as e:
            print(f"\nError: {e}")


def run_interactive(agent):
    """대화형 모드: 사용자가 자유롭게 질문한다."""
    print("\n[Interactive Mode] Type your question (or 'quit' to exit).")
    print("Tip: Ask in English for better SQL generation accuracy.\n")
    while True:
        try:
            question = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in ("quit", "exit", "q"):
            break
        try:
            response = agent.invoke(question)
            print(f"\nAgent> {response['output']}\n")
        except Exception as e:
            print(f"\nError: {e}\n")


# ── 하이브리드 분석 (SQL 직접 실행 → LLM 해석) ──────────────────

PRICING_SQL = """\
SELECT
    ci.Name,
    ci.Trim,
    ci.CarType,
    distro.SellPrice         AS sell_price,
    ci.unitcost              AS unit_cost,
    ROUND((distro.SellPrice - ci.unitcost) * 100.0 / distro.SellPrice, 1) AS margin_pct,
    ci.sold_this_month,
    ci.sold_last_month,
    ci.sold_last_year,
    ci.sold_all_time,
    ci.Rating_Overall,
    ci.YearBuilt,
    distro.total_sold_month  AS distro_sold_month,
    distro.total_possible    AS distro_possible_sales,
    distro.city_count        AS cities_selling
FROM CarInfo ci
JOIN (
    SELECT Car_ID,
           SellPrice,
           SUM(Sold_This_Month)    AS total_sold_month,
           SUM(Possible_Sales)     AS total_possible,
           COUNT(DISTINCT City_ID) AS city_count
    FROM CarDistro
    WHERE Company_ID = (SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID')
    GROUP BY Car_ID
) distro ON ci.Car_ID = distro.Car_ID
WHERE ci.Company_ID = (SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID')
  AND ci.Status >= 0
ORDER BY margin_pct DESC;
"""

PRICING_PROMPT = """\
You are a GearCity business analyst AI. Analyze the following pricing data for the player's car lineup.

Current game year: {game_year}

## Car Pricing Data
{pricing_table}

## Instructions
Provide a concise pricing analysis in English, covering:

1. **Overview**: How many cars, average margin, overall health of the lineup
2. **Healthy margins** (>= 30%): Which cars are well-priced
3. **Low margin warnings** (< 20%): Which cars need price increases or cost reduction
4. **Demand signals**: Compare distro_sold_month vs distro_possible_sales
   - If possible_sales > 0 and sold is near possible: demand is met, consider raising price
   - If sold_this_month = 0 despite being sold in multiple cities: possibly overpriced or outdated
   - If sold_all_time is very high but sold_this_month is low: aging product, may need refresh
5. **Specific recommendations**: For the 3-5 most critical cars, suggest concrete actions (raise/lower price, redesign, discontinue)

Keep the response under 500 words. Use bullet points.
"""


def analyze_pricing(db_path: Path, llm: ChatOllama):
    """판매 가격 적절성을 분석한다: SQL 직접 실행 → LLM 해석."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        # 게임 연도 조회
        game_year = conn.execute(
            "SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Year'"
        ).fetchone()[0]

        # 가격 데이터 조회
        df = pd.read_sql_query(PRICING_SQL, conn)
    finally:
        conn.close()

    if df.empty:
        print("No active cars found for the player company.")
        return

    # 결과 테이블 출력
    print(f"\n{'='*60}")
    print(f"  Pricing Analysis (Game Year: {game_year})")
    print(f"{'='*60}")
    print(f"\n{df.to_markdown(index=False)}\n")

    # LLM에게 해석 요청
    print("Generating LLM analysis...\n")
    prompt = PRICING_PROMPT.format(
        game_year=game_year,
        pricing_table=df.to_markdown(index=False),
    )

    response = llm.invoke(prompt)
    # Windows cp949 인코딩 문제 방지
    text = response.content
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


# ── CLI ──────────────────────────────────────────────────────────

def main():
    db_path = DEFAULT_DB_PATH
    interactive = False
    analyze_target = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--interactive":
            interactive = True
        elif args[i] == "--analyze" and i + 1 < len(args):
            analyze_target = args[i + 1]
            i += 1
        elif not args[i].startswith("-"):
            db_path = Path(args[i])
        i += 1

    print(f"DB: {db_path}")
    print(f"Model: {MODEL_NAME}")
    print("Connecting...")

    agent, db, llm = create_agent(db_path)

    table_count = len(db.get_usable_table_names())
    print(f"Connected! {table_count} tables available.\n")

    if analyze_target == "pricing":
        analyze_pricing(db_path, llm)
    elif interactive:
        run_interactive(agent)
    else:
        run_test_queries(agent)


if __name__ == "__main__":
    main()
