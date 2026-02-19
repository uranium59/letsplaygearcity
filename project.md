# Project Specification: GearCity Autonomous Agent (Prototype)

## 1. Project Overview
**Goal**: 개발 중인 게임(RQI)의 기술 검증을 위한 프로토타입으로, 경영 시뮬레이션 게임 **'GearCity'**를 플레이하는 AI 에이전트를 구축한다.
**Core Concept**: 단순한 RAG 챗봇이 아닌, **LangGraph**를 이용한 순환형 사고(Thinking Loop)와 **SQLite** 데이터베이스 직접 제어(Text-to-SQL)를 통해 자율적으로 전략을 수립하고 실행하는 'AI CEO'를 목표로 한다.

## 2. Technical Environment & Constraints
* **OS**: Windows (Local Environment)
* **LLM**: `Qwen 3 30B` (via **Ollama**)
    * *Feature*: 256k Context Window 지원. 토큰 절약보다는 **Full Context 주입** 전략 사용.
* **Database**: **SQLite** (`.db` single file save format)
* **Language**: Python 3.11+
* **Key Libraries**:
    * Orchestration: `langgraph`, `langchain`
    * LLM Interface: `langchain-ollama`
    * Data Handling: `pandas`, `sqlalchemy`, `sqlite3`
    * Dependency Management: `poetry`

## 3. Phase 1: Foundation Setup (Current Mission)
우리는 현재 **'환경 구축 및 데이터 분석'** 단계에 있다. 아래의 요구사항에 맞춰 Python 프로젝트 세팅 가이드와 초기 분석 스크립트를 작성하라.

### 3.1. Project Structure
확장성을 고려한 폴더 구조를 제안하라.
* `src/`: 메인 로직
* `data/save/`: GearCity `.db` 파일 저장소
* `data/schema/`: 추출된 스키마 정보 저장소
* `notebooks/`: 데이터 분석용 Jupyter Notebook

### 3.2. Dependency Management
`poetry`를 기준으로 필요한 패키지 리스트(`pyproject.toml` or `poetry add` commands)를 정의하라.
* 필수 포함: `langgraph`, `langchain-ollama`, `pandas`, `sqlalchemy`

### 3.3. Core Task: The "Schema Inspector" Script
GearCity의 세이브 파일(`*.db`)을 분석하여 LLM이 이해할 수 있는 **'데이터베이스 지도(Map)'**를 생성하는 Python 스크립트(`inspect_db.py`)를 작성하라.

**Requirements for the Script:**
1.  **Table & Column Extraction**: 모든 테이블의 이름과 컬럼 정보(Type, PK, FK)를 추출한다.
2.  **Data Sampling**: 컬럼 이름만으로는 의미를 알 수 없는 경우가 많으므로, 각 테이블에서 **실제 데이터 3~5행**을 샘플링하여 함께 출력한다.
3.  **Output Format**: LLM(Qwen)이 읽기 편하도록 **Markdown** 또는 **YAML** 형식으로 `data/schema/gearcity_schema.md` 파일에 저장한다.
4.  **Error Handling**: 파일 경로 오류나 DB 잠금 상태에 대한 예외 처리를 포함한다.

### 3.4. Verification: "Hello World"
환경이 정상적으로 세팅되었는지 확인하기 위한 `test_env.py`를 작성하라.
1.  **Ollama Connection**: 로컬 Qwen 모델에 간단한 질문("Who are you?")을 던져 응답을 받는다.
2.  **DB Connection**: 샘플 `.db` 파일에 연결하여 테이블 개수를 카운트한다.

---

## 4. Deliverables
위 명세를 바탕으로 다음을 순서대로 출력하라:
1.  터미널에서 실행할 **Poetry 세팅 명령어**
2.  **프로젝트 폴더 구조** 트리
3.  **`inspect_db.py`** 전체 코드 (주석 포함)
4.  **`test_env.py`** 전체 코드