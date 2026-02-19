"지식(RAG)이 머리라면, DB(데이터)는 눈입니다."

지금 RAG(위키 학습)가 돌아가고 있으니, 에이전트의 머릿속엔 "엔진을 어떻게 만들어야 한다"는 이론은 들어갔습니다. 하지만 정작 **"지금 내 통장에 얼마가 있고, 지금이 몇 년도인지"**를 모르면 아무것도 못 하겠죠.

따라서 다음 스텝은 무조건 DB 파싱 및 연동 (The Sensory System) 입니다.
단, 단순히 "파싱"한다고 생각하지 말고, **"LLM이 스스로 조회할 수 있는 환경(SQL Interface)"**을 구축한다고 접근합시다.

Qwen 30B에게 "지금 자금 상황 어때?"라고 물으면, 녀석이 알아서 SELECT cash FROM company_financials ...를 날리게 만드는 것이 목표입니다.

Step 1: "전장의 안개" 걷어내기 (Schema Mapping)
GearCity의 SQLite 구조를 우리가 일일이 분석해서 하드코딩(Hard-coding)하면, 나중에 게임 업데이트되거나 모드 깔면 다 깨집니다.
"DB 스키마를 LLM에게 통째로 떠먹여 주는" 스크립트가 필요합니다.

이 스크립트는 단순히 테이블 명만 뽑는 게 아니라, 각 테이블의 컬럼 정보 + 샘플 데이터 3줄을 뽑아서 schema_description.txt라는 파일을 만듭니다. 이 파일이 나중에 시스템 프롬프트의 핵심 재료가 됩니다.

[Action 1] src/db_inspector.py 작성 및 실행

Python

import sqlite3
import pandas as pd
import os

# 실제 세이브 파일 경로로 수정 필수!
DB_PATH = "data/save/MySaveGame.db" 
OUTPUT_FILE = "data/schema/db_schema_map.txt"

def inspect_db():
    if not os.path.exists(DB_PATH):
        print(f"Error: DB 파일을 찾을 수 없습니다. ({DB_PATH})")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 모든 테이블 목록 가져오기
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"총 {len(tables)}개의 테이블을 발견했습니다. 맵핑을 시작합니다...")
    
    schema_doc = []
    schema_doc.append(f"# GearCity Database Schema Map\n")
    schema_doc.append(f"This document describes the structure of the save file database.\n")
    schema_doc.append(f"Use this to construct valid SQL queries.\n\n")

    for table in tables:
        # 1. 테이블 정보
        schema_doc.append(f"## Table: {table}")
        
        # 2. 컬럼 정보 (PRAGMA table_info)
        # cid, name, type, notnull, dflt_value, pk
        cursor.execute(f"PRAGMA table_info({table})")
        cols = cursor.fetchall()
        col_desc = [f"{col[1]} ({col[2]})" for col in cols]
        schema_doc.append(f"- Columns: {', '.join(col_desc)}")
        
        # 3. 데이터 샘플링 (어떤 값이 들어가는지 봐야 LLM이 이해함)
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table} LIMIT 3", conn)
            if not df.empty:
                markdown_table = df.to_markdown(index=False)
                schema_doc.append(f"- Sample Data:\n{markdown_table}\n")
            else:
                schema_doc.append("- Sample Data: (Empty Table)\n")
        except Exception as e:
            schema_doc.append(f"- Error reading data: {e}\n")
            
        schema_doc.append("---\n")

    conn.close()
    
    # 파일 저장
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(schema_doc))
        
    print(f"완료! '{OUTPUT_FILE}'에 DB 지도가 생성되었습니다.")
    print("이 파일을 열어서 'Game Year'나 'Cash'가 어느 테이블에 있는지 슥 훑어보세요.")

if __name__ == "__main__":
    inspect_db()
Step 2: "눈(Eyes)" 달아주기 (SQL Agent 기초)
DB 지도가 나오면, 이제 LangChain의 SQLDatabase 기능을 써서 Qwen과 DB를 연결합니다.
이 코드는 "Agent가 DB를 보고 판단하는" 로직의 프로토타입입니다.

[Action 2] notebooks/test_db_agent.ipynb (또는 .py) 에서 테스트

Python

import os
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_ollama import ChatOllama

# 1. 설정
DB_PATH = "data/save/MySaveGame.db" # 경로 확인
MODEL_NAME = "qwen3:30b" # 로컬 모델명 확인

# 2. DB 연결 (LangChain Wrapper 사용)
# sample_rows_in_table_info=3 : 스키마 정보 줄 때 샘플 데이터도 같이 보여줌 (중요!)
db = SQLDatabase.from_uri(
    f"sqlite:///{DB_PATH}",
    sample_rows_in_table_info=3
)

# 3. LLM 설정 (SQL 생성을 위해 temperature=0 권장)
llm = ChatOllama(model=MODEL_NAME, temperature=0)

# 4. SQL Agent 생성 (이 녀석이 Text-to-SQL을 수행함)
agent_executor = create_sql_agent(
    llm=llm,
    db=db,
    agent_type="zero-shot-react-description",
    verbose=True # 생각하는 과정(쿼리 짜는 과정)을 다 출력
)

# --- 테스트 시나리오 ---

print(">>> Q1. 현재 게임 날짜와 내 회사의 현금 보유량은?")
# 질문은 영어로 하는 게 SQL 생성 정확도가 훨씬 높습니다. (Qwen 특성상)
response = agent_executor.invoke(
    "Check the current game date (year/month) and the player company's cash balance. "
    "You usually find this in tables like 'Player', 'Company', or 'GameConfig'."
)
print(f"답변: {response['output']}")

print("\n>>> Q2. 가장 많이 팔린 자동차 모델은?")
response = agent_executor.invoke(
    "Find the car model with the highest total sales based on sales history tables."
)
print(f"답변: {response['output']}")
왜 이 순서인가요?
DB 구조 파악 (inspect_db.py): GearCity 개발자가 테이블 이름을 Money라고 지었는지 Finance_Tbl라고 지었는지 우리는 모릅니다. 이걸 먼저 텍스트 파일로 뽑아내야, 우리가 훑어보고 "아, 이 테이블이 핵심이네" 하고 힌트를 줄 수 있습니다.

SQL Agent 테스트 (test_db_agent): Qwen 30B가 SQLite 쿼리를 얼마나 잘 짜는지 검증해야 합니다. "테이블이 없는데요?" 같은 헛소리를 하면 프롬프트를 깎아야 하니까요.

[숙제]

위의 inspect_db.py를 돌려서 생성된 텍스트 파일을 열어보세요.

**"돈(Cash)", "날짜(Date)", "회사 이름(Company Name)"**이 들어있는 테이블 이름을 찾아서 알려주세요. (예: Companies 테이블의 cash 컬럼 등)

그 정보가 확인되면, 이제 진짜 LangGraph를 올려서 [상황 파악 -> 위키 검색(RAG) -> 의사 결정] 루프를 연결할 수 있습니다.