# GearCity Autonomous Agent

> An AI advisor ('AI CEO') for the business management simulation **[GearCity](https://store.steampowered.com/app/285110/GearCity/)**.
> Uses a LangGraph multi-step SQL pipeline with a local LLM for strategic analysis.

[한국어 README](READMEKR.md)

---

## Why This Project Exists

My upcoming business simulation game, **'RedQueen Industry (RQI)'**, is planned to ship with an LLM-based AI advisor that assists players drowning in data during the mid-to-late game — a secretary that understands context and can tell you *"Boss, your London branch inventory is critical"* at exactly the right moment. (It will likely be distributed separately via GitHub.) Why not just build it myself?

However, the typical chatbot integration approach has clear limitations. A general-purpose LLM, starting from zero context, can barely grasp a game's complex internal rules and real-time data from user questions or screen recognition alone. Before integrating this system into RQI proper, I needed a proving ground to validate whether an AI agent can actually analyze intricately interconnected game data and produce meaningful strategic advice.

### Why GearCity?

While searching for a simulation game to serve as this proof-of-concept, GearCity stood out. It has an almost perfect structure for external AI integration:

- **Turn-based System** — No real-time latency constraints; the agent can focus on careful per-turn data analysis and reasoning.
- **Accessible State Data** — Save files are managed as a single SQLite database, making it straightforward for the agent to query and track all in-game state via SQL.
- **Structured Knowledge** — A nearly comprehensive DokuWiki covering game mechanics is available, ideal for building a RAG (Retrieval-Augmented Generation) knowledge base for the LLM.

On top of these conditions, the fact that I've already played GearCity extensively — and know exactly *where* players struggle and *where* they need help — was an important factor.

This project goes beyond a simple 'chatbot toy'. It's the first prototype toward a genuine **gameplay advisor** that extracts meaningful insights from database state, understands rules via wiki knowledge, and discusses business strategy with the player.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 / Poetry |
| LLM | Qwen 3 30B-A3B via Ollama (local, 256k context) |
| Orchestration | LangGraph + LangChain |
| DB | SQLite (GearCity save file = `.db`) |
| Data | pandas, tabulate |

## Quick Start

```bash
# Install dependencies
poetry install

# Verify environment (Ollama server must be running)
poetry run python src/test_env.py

# Extract DB schema (run when save file changes)
poetry run python src/db_inspector.py "D:\path\to\save.db"

# Run the AI agent
poetry run python src/db_query_graph.py -q "How much cash does my company have?"
```

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Windows 10 / Linux / macOS | Windows 11 |
| Python | 3.12+ | 3.12 |
| RAM | 16GB | 32GB+ |
| VRAM | — (CPU inference possible, very slow) | 24GB+ (RTX 3090/4090, etc.) |
| Disk | 20GB (model files + dependencies) | — |

Qwen 3 30B-A3B (Q4_K_M quantization) loads ~20GB of model weights.
If GPU VRAM is sufficient, Ollama automatically loads the model onto the GPU; otherwise it falls back to CPU/RAM.
GPU inference takes ~2-5 minutes per full pipeline run; CPU inference may take 10+ minutes.

### Why Local LLM Only?

This project is designed exclusively for **local LLM inference via Ollama**.
There are no plans to support cloud API LLMs (OpenAI, Anthropic, Google, etc.).

- Game data (save files) is local, so keeping inference local is a natural fit
- Zero running cost — each question triggers 5-10 LLM calls, making API pricing impractical
- The project's goal is to explore how far a local LLM can go as a game agent

## Prerequisites

- **Python 3.12+**
- **Ollama** — `ollama serve` running, model `qwen3:30b-a3b-instruct-2507-q4_K_M` pulled
- **GearCity save file** (`.db`)

## Architecture

The agent uses a LangGraph StateGraph with conditional routing. Questions are classified and routed through specialized pipelines:

```
User Question
      |
  [Pre-Router] -- keyword-based fast classification (no LLM call)
      |
      +-- forecast/design --> specialized advisors (bypass SQL pipeline)
      |
      +-- other questions:
            |
        [Planner] -- decompose into 1-5 sub-queries, select tables
            |
        [Load Schema] -- extract only selected table schemas
            |
        [SQL Generator] -- generate SQL for each sub-query
            |
        [Executor] -- SQLite read-only execution
            |
        [Router] -- error -> retry (max 2) / next sub-query / done -> analyst
            |
        [Analyst] -- synthesize results into final answer
            |
        [Classifier] -- categorize: factual / analytical / strategic / design / forecast
            |
            +-- factual/analytical --> END (analyst answer is final)
            +-- strategic --> [Strategist] -> [Evaluators x N] -> [Aggregator] -> END
            +-- design --> [Design Advisor] -> END
            +-- forecast --> [Forecast Advisor] -> END
```

### Specialized Pipelines

| Pipeline | Trigger | What It Does |
|----------|---------|-------------|
| **Strategic** | "How to improve profitability?" | Generates 2-4 strategy candidates, evaluates each with additional SQL, aggregates into ranked recommendation |
| **Design Advisor** | "What if I increase bore by 5mm?" | Python calculation engine (displacement, HP, staleness, mod costs) + LLM synthesis |
| **Forecast Advisor** | "Will there be a war soon?" | Pre-parsed TurnEvents.xml timeline (wars, recessions, oil crises) + player asset risk cross-reference |

### Session Memory

In interactive mode, a domain-based TTL cache reuses data from previous questions within the same session:

| Domain | TTL (turns) | Cached Data |
|--------|-------------|-------------|
| `game_state` | 3 | Year/month/cash/company name |
| `sales_market` | 5 | Sales/demand/per-city performance |
| `vehicle_design` | 12 | Vehicle/component specs |
| `factory` | 6 | Factory/production lines |
| `forecast` | 60 | War/economic forecasts |

## Key Modules

### `src/db_query_graph.py` — Graph Builder + CLI

Builds the LangGraph StateGraph via `build_graph()` and provides `run_query()`/`run_interactive()` entry points.
Node implementations are split across `nodes_pipeline.py`, `nodes_analysis.py`, and `nodes_advisors.py`.
Progress output uses `_NODE_FORMATTERS` dict dispatch.

```bash
poetry run python src/db_query_graph.py                    # Interactive mode
poetry run python src/db_query_graph.py -q "query here"    # Single question
poetry run python src/db_query_graph.py --test             # Run all test queries (Q1-Q15)
poetry run python src/db_query_graph.py "path/to/save.db" -q "..."
```

### `src/graph_state.py` — Graph State Definition

`GraphState` TypedDict, `StrategyCandidate` TypedDict, `MAX_RETRIES`, `CORE_TABLES` constants.

### `src/nodes_pipeline.py` — SQL Pipeline Nodes

Pre-Router, Planner, Load Schema, SQL Generator, Executor, Router, Retry, Advance nodes.

### `src/nodes_analysis.py` — Analysis + Strategy Nodes

Analyst, Classifier, Strategist, Aggregator nodes.

### `src/nodes_advisors.py` — Specialized Advisor Nodes

- **Design Advisor**: `_fetch_vehicle_data()` → `_fetch_tech_components()` → `_calculate_design_metrics()` → LLM synthesis
- **Forecast Advisor**: Timeline load → player asset risk analysis → LLM synthesis

### `src/design_formulas.py` — Vehicle Design Calculation Engine

Pure Python module with no DB/LLM dependencies. Implements GearCity wiki formulas.
Named constants at module top (`DISPLACEMENT_CONSTANT`, `HP_CONVERSION_FACTOR`, `COMPONENT_SAFE_AGE`, etc.).

- **Engine**: `calc_displacement()`, `calc_hp()`, `simulate_bore_change()`, `simulate_stroke_change()`
- **Vehicle**: `calc_top_speed()`, `calc_acceleration()`
- **Modification costs**: `estimate_modification_cost()` (`MOD_BASE_PERCENT`/`MOD_CHASSIS_PERCENT` constants)
- **Staleness**: `calc_staleness()` (component aging penalties, `URGENCY_*` thresholds)
- **Compatibility**: `check_torque_compatibility()`, `compare_ratings()`

### `src/event_timeline.py` — War & Economic Forecast Module

Loads pre-parsed `data/turn_events_timeline.json` (extracted from TurnEvents.xml) and provides forecasts.
Threshold constants at module top (`BUYRATE_DOWNTURN_THRESHOLD`, `GAS_SPIKE_THRESHOLD`, etc.)
with `ECONOMIC_EVENT_CONFIGS` dict and `WAR_SEVERITY_RANK`/`RISK_YEARS_*` constants.

- `get_upcoming_wars()` / `get_active_wars()` — per-city war forecasting
- `get_upcoming_economic_events()` — recession, gas spike, interest spike detection
- `check_player_asset_risks()` — cross-reference player factory/branch cities with future war zones
- `format_forecast_summary()` — condensed LLM-ready event forecast

**Coverage**: 196/205 cities have conflict history (1899-2019). 9 permanent safe havens identified.

### `src/session_memory.py` — Domain-Based Session Cache

Reuses query results across questions in interactive mode.
- `SessionMemory` class: domain-aware TTL cache (get/put/format_context/classify_tables/get_valid_domains)
- `get_memory()` / `reset_memory()`: module-level singleton
- Injects cache context into Planner/Analyst prompts to reduce redundant SQL calls

### `src/db_inspector.py` — DB Schema Extractor

Extracts all 71 table schemas from save files into `data/schema/db_schema_map.txt` for LLM consumption.

### `crawler.py` — Wiki Crawler

BFS crawler for GearCity wiki (wiki.gearcity.info). Saves pages as JSON to `data/wiki/`.

### `parse_turn_events.py` — TurnEvents.xml Analyzer

Standalone analysis script for extracting economic variables and war timelines from game data files.
Generates `data/turn_events_timeline.json`.
XML path is configurable via `GEARCITY_TURN_EVENTS_XML` env variable or CLI argument.

```bash
poetry run python parse_turn_events.py                              # Load path from .env
poetry run python parse_turn_events.py "D:\path\to\TurnEvents.xml"  # Direct path
```

## Project Structure

```
letsplaygearcity/
├── CLAUDE.md                     # AI assistant project context
├── README.md                     # This file (English)
├── READMEKR.md                   # Korean README
├── project.md                    # Original project spec
├── pyproject.toml                # Poetry dependencies
├── .env                          # GEARCITY_DB_PATH, OLLAMA_MODEL, GEARCITY_TURN_EVENTS_XML
├── crawler.py                    # Wiki crawler
├── parse_turn_events.py          # TurnEvents.xml analysis tool
├── src/
│   ├── db_query_graph.py         # ★ Graph builder + CLI entry point
│   ├── graph_state.py            # GraphState TypedDict + constants
│   ├── graph_utils.py            # Shared utilities (create_llm, etc.)
│   ├── prompts.py                # LLM prompt templates
│   ├── queries.py                # SQL query constants
│   ├── nodes_pipeline.py         # SQL pipeline nodes (pre_router~advance)
│   ├── nodes_analysis.py         # Analysis nodes (analyst, classifier, strategist, aggregator)
│   ├── nodes_advisors.py         # Advisor nodes (design_advisor, forecast_advisor)
│   ├── design_formulas.py        # Vehicle design calculation engine (named constants)
│   ├── event_timeline.py         # War & economic event forecast (threshold constants)
│   ├── session_memory.py         # Domain-based session cache
│   ├── db_agent.py               # ReAct SQL agent (v1, deprecated)
│   ├── db_inspector.py           # DB schema -> text extraction
│   ├── inspect_db.py             # DB schema analyzer (Markdown)
│   └── test_env.py               # Environment verification
├── data/
│   ├── save/                     # GearCity .db save files
│   ├── schema/                   # db_schema_map.txt (71 tables)
│   ├── wiki/                     # Crawled wiki data (JSON)
│   └── turn_events_timeline.json # Pre-parsed war & economic timeline
└── notebooks/                    # Jupyter analysis notebooks
```

## Development Phases

1. **Phase 1** (done): Environment setup + data analysis — wiki crawling, DB schema extraction
2. **Phase 2** (current): LangGraph agent — multi-step Text-to-SQL with strategic/design/forecast pipelines
3. **Phase 3**: Autonomous play — strategy execution, game state monitoring
