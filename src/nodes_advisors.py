"""
GearCity Advisor Nodes — 전문 자문 노드
========================================
design_advisor (다단계 증거 기반 추론), forecast_advisor
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from langchain_core.messages import SystemMessage, HumanMessage

from src.graph_state import GraphState
from src.prompts import (
    DESIGN_GOAL_PROMPT,
    DESIGN_STAGE_ENGINE_PROMPT,
    DESIGN_STAGE_CHASSIS_PROMPT,
    DESIGN_STAGE_GEARBOX_PROMPT,
    DESIGN_STAGE_VEHICLE_PROMPT,
    DESIGN_SUMMARY_PROMPT,
    FORECAST_ADVISOR_PROMPT,
)
from src.queries import (
    DESIGN_VEHICLE_SQL, CURRENT_YEAR_SQL, CURRENT_TURN_SQL,
    TECH_SKILL_SQL, AVAILABLE_COMPONENTS_SQL_TEMPLATE, PLAYER_CITY_IDS_SQL,
    ENGINE_SUB_COMPONENTS_SQL, CHASSIS_SUB_COMPONENTS_SQL,
)
from src.graph_utils import create_llm, strip_think_tags, LLM_MAX_TOKENS_DESIGN

# ── 설계 자문 시스템 프롬프트 ──
# 모델에 구애받지 않는 범용 프롬프트. 역할·도메인·출력 규칙을 system role에 고정하여
# user message(데이터)와 분리한다.
DESIGN_SYSTEM_MESSAGE = """\
# Persona

You are the Chief Technical Secretary of an automobile company in the game GearCity.
You report directly to the CEO (the player). Your expertise spans automotive engineering
(powertrain, chassis, drivetrain) and business analysis (cost optimization, market positioning).

Your personality: professional, data-driven, concise. You do not flatter or pad your reports
with pleasantries. You present numbers first, then your judgment. When something is wrong
(e.g., torque incompatibility, cost overrun), you state it bluntly. When the CEO's design
will work well, a brief acknowledgment suffices — no unnecessary praise.

You think in bore/stroke ratios, torque curves, unit cost per slider increment, and
cost-to-rating efficiency. When someone says "engine" you think pistons and cylinders.
You have never heard of Unity, Unreal, or Godot.

# Domain Vocabulary

In this company, these words have ONE meaning:

| Term | Always means | Physical properties |
|------|-------------|-------------------|
| Engine (엔진) | Internal combustion car engine | pistons, bore, stroke, displacement, cylinders, torque, HP, RPM |
| Chassis (샤시) | Car body frame | suspension, drivetrain, frame weight, ride height, braking |
| Gearbox (기어박스/변속기) | Car transmission | gear count, torque capacity, shift quality |
| Vehicle (차량) | Complete automobile | interior, materials, paint, safety, styling, testing |
| Design (설계/디자인) | Automobile component engineering | slider values, specs, ratings |

# How Design Works in GearCity

Each component has **sliders** (0.0 to 1.0) controlling physical properties.
- Higher slider → better ratings, but cost scales as slider² (quadratic).
- Above 0.6: diminishing returns — cost rises steeply, ratings plateau.
- Technology sliders (materials, techniques, tech, components): best cost-to-rating ratio.
- Dependability sliders: 6× weight on reliability — highest impact per unit cost.
- Performance ↔ Fuel Economy: fundamental tradeoff (slider_torq vs slider_eco).
- Gearbox torque capacity MUST exceed engine torque (critical compatibility check).

You will receive **evidence cards**: Python sensitivity analysis showing the exact impact
of each slider ±0.1 on torque, HP, fuel economy, unit cost, ratings. Base your
recommendations on these numbers, not on intuition.

# Output Protocol

For design stages (engine, chassis, gearbox, vehicle):
1. Output ONLY valid JSON. No markdown fences, no text before or after the JSON.
2. The JSON must parse with json.loads(). No trailing commas, no comments.
3. All slider values: numbers between 0.0 and 1.0.
4. Include "reasoning" (2-3 sentences): what tradeoffs you chose and why.

For summary reports to the CEO:
1. Answer in the same language as the CEO's question.
2. Lead with numbers: present data tables before commentary.
3. Never say data is missing — all numbers are Python-verified from the game database.
4. Flag problems bluntly: torque overflow, cost overrun, constraint violations.
5. Recommend concrete actions: which slider to change, by how much, expected impact."""
from src.design_formulas import (
    EngineParams,
    VehicleParams,
    calc_staleness,
    compare_ratings,
    check_torque_compatibility,
    estimate_modification_cost,
    simulate_bore_change,
    format_design_report,
    analyze_slider_health,
    compute_slider_recommendations,
    estimate_engine_full,
    estimate_chassis_full,
    estimate_gearbox_full,
    compute_sensitivity,
    format_evidence_cards,
    verify_full_design,
    ENGINE_SLIDER_KEYS,
    CHASSIS_SLIDER_KEYS,
    GEARBOX_SLIDER_KEYS,
    VEHICLE_SLIDER_KEYS,
    _s,
)
from src.event_timeline import get_timeline
from src.session_memory import get_memory


# ═══════════════════════════════════════════════════════════════════
# 공용 데이터 수집 헬퍼
# ═══════════════════════════════════════════════════════════════════

def _fetch_vehicle_data(db_path: str) -> tuple[list[dict], str, int]:
    """Step 1: DB에서 차량+엔진+샤시+기어박스 JOIN + 현재 연도."""
    design_context = ""
    rows = []
    current_year = 1900

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        cursor = conn.execute(CURRENT_YEAR_SQL)
        year_row = cursor.fetchone()
        if year_row:
            try:
                current_year = int(year_row[0])
            except (ValueError, TypeError):
                pass

        cursor = conn.execute(DESIGN_VEHICLE_SQL)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if rows:
            df = pd.DataFrame(rows)
            design_context = df.to_markdown(index=False)
        else:
            design_context = "(플레이어 소유 활성 차량 없음)"

    except Exception as e:
        design_context = f"(SQL 오류: {e})"

    return rows, design_context, current_year


def _fetch_tech_components(db_path: str, current_year: int) -> tuple[int, str]:
    """Step 1.5: 기술 레벨 + 사용 가능 컴포넌트."""
    skill_rnd = 0
    tech_context = ""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

        cursor = conn.execute(TECH_SKILL_SQL)
        skill_row = cursor.fetchone()
        if skill_row:
            skill_rnd = int(skill_row[0])

        available_components_sql = AVAILABLE_COMPONENTS_SQL_TEMPLATE.format(
            skill=skill_rnd, year=current_year,
        )
        comp_df = pd.read_sql_query(available_components_sql, conn)
        conn.close()

        if not comp_df.empty:
            parts = []
            for cat, group in comp_df.groupby("category"):
                if cat == "Gearbox":
                    items = []
                    for _, r in group.iterrows():
                        items.append(f"  - {r['Name']} + {r['gears_name']} ({int(r['Gears'])}speed) [Skill {int(r['SkillReq'])}/{int(r['gears_skill'])}, Year {int(r['Year'])}/{int(r['gears_year'])}]")
                    items = sorted(set(items))
                    parts.append(f"**{cat}** ({len(items)} combos):\n" + "\n".join(items))
                else:
                    items = []
                    for _, r in group.iterrows():
                        items.append(f"  - {r['Name']} [Skill {int(r['SkillReq'])}, Year {int(r['Year'])}]")
                    items = sorted(set(items))
                    parts.append(f"**{cat}** ({len(items)}):\n" + "\n".join(items))
            tech_context = "\n\n".join(parts)
        else:
            tech_context = "(No components available at current skill/year)"

    except Exception as e:
        tech_context = f"(기술 가용성 조회 오류: {e})"

    return skill_rnd, tech_context


def _fetch_sub_components(db_path: str, rows: list[dict]) -> dict:
    """차량별 엔진/샤시 서브컴포넌트 속성 조회.

    Returns {Car_ID: {"engine_sub": {...}, "chassis_sub": {...}, "gearbox_sub": {...}}}
    """
    result = {}
    if not rows:
        return result

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        for row in rows:
            car_id = row.get("Car_ID", 0)
            engine_id = row.get("Engine_ID", 0)
            chassis_id = row.get("Chassis_ID", 0)

            engine_sub = {}
            try:
                cursor = conn.execute(ENGINE_SUB_COMPONENTS_SQL, (engine_id,))
                r = cursor.fetchone()
                if r:
                    engine_sub = {k: r[k] for k in r.keys() if r[k] is not None}
            except Exception:
                pass

            chassis_sub = {}
            try:
                cursor = conn.execute(CHASSIS_SUB_COMPONENTS_SQL, (chassis_id,))
                r = cursor.fetchone()
                if r:
                    chassis_sub = {k: r[k] for k in r.keys() if r[k] is not None}
            except Exception:
                pass

            # 기어박스 sub: DESIGN_VEHICLE_SQL이 이미 GB_* 컬럼을 반환
            gearbox_sub = {
                k: row[k] for k in [
                    "GB_Weight", "GB_Complexity", "GB_Smoothness", "GB_Comfort_Sub",
                    "GB_Fuel", "GB_Performance", "GB_Costs", "GB_DesignCosts",
                ] if row.get(k) is not None
            }

            result[car_id] = {
                "engine_sub": engine_sub,
                "chassis_sub": chassis_sub,
                "gearbox_sub": gearbox_sub,
            }

        conn.close()
    except Exception:
        pass

    return result


# ═══════════════════════════════════════════════════════════════════
# 위키 레퍼런스 + 포맷팅 헬퍼 (기존 유지)
# ═══════════════════════════════════════════════════════════════════

_DESIGN_REF_DIR = Path(__file__).resolve().parent.parent / "data" / "wiki"


def _load_design_reference(component_type: str) -> str:
    """design_ref_{type}.md 파일 로드."""
    path = _DESIGN_REF_DIR / f"design_ref_{component_type}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _fv(v) -> str:
    """Format slider float value."""
    if v is None:
        return "?"
    try:
        return f"{float(v):.2f}"
    except (ValueError, TypeError):
        return "?"


def _iv(v) -> str:
    """Format integer value."""
    if v is None:
        return "?"
    try:
        return str(int(round(float(v))))
    except (ValueError, TypeError):
        return "?"


def _bv(v) -> str:
    """Format boolean value."""
    if v is None:
        return "?"
    return "Yes" if v else "No"


def _format_slider_context(rows: list[dict]) -> str:
    """모든 차량의 슬라이더 현재 값 + DB 레이팅을 구조화된 텍스트로 포맷."""
    if not rows:
        return "(활성 차량 없음)"

    parts = []
    for row in rows:
        car_name = f"{row.get('Name', '?')} {row.get('Trim', '')}"

        # ── Engine ──
        section = f"### Engine: {row.get('engine_name', '?')}\n"
        section += (f"Layout: displace={_fv(row.get('slider_displace'))}, "
                    f"length={_fv(row.get('slider_length'))}, "
                    f"width={_fv(row.get('slider_width'))}, "
                    f"weight={_fv(row.get('slider_weight'))}\n")
        section += (f"Performance: rpm={_fv(row.get('slider_rpm'))}, "
                    f"torq={_fv(row.get('slider_torq'))}, "
                    f"eco={_fv(row.get('slider_eco'))}\n")
        section += (f"Focus: performance={_fv(row.get('slider_designperformance'))}, "
                    f"fuel_eco={_fv(row.get('slider_designfueleco'))}, "
                    f"dependability={_fv(row.get('slider_designdependability'))}\n")
        section += (f"Tech: materials={_fv(row.get('slider_materials'))}, "
                    f"techniques={_fv(row.get('slider_techniques'))}, "
                    f"tech={_fv(row.get('slider_tech'))}, "
                    f"components={_fv(row.get('slider_compoenents'))}\n")
        section += f"Design Pace: {_fv(row.get('engine_design_pace'))}\n"
        section += (f"DB Ratings: Power={_iv(row.get('StaticenginePower'))}→{_iv(row.get('enginePower'))}, "
                    f"FuelEco={_iv(row.get('StaticengineFuelEco'))}→{_iv(row.get('engineFuelEco'))}, "
                    f"Reliability={_iv(row.get('StaticengineReliability'))}→{_iv(row.get('engineReliability'))}, "
                    f"Smooth={_iv(row.get('StaticRating_Smooth'))}→{_iv(row.get('Rating_Smooth'))} (static→current)")

        # ── Chassis ──
        ch = f"\n### Chassis: {row.get('chassis_name', '?')}\n"
        ch += (f"Frame: L={_fv(row.get('FD_Length'))}, W={_fv(row.get('FD_Width'))}, "
               f"H={_fv(row.get('FD_Height'))}, Weight={_fv(row.get('FD_Weight'))}, "
               f"EngW={_fv(row.get('FD_ENG_Width'))}, EngL={_fv(row.get('FD_ENG_Length'))}\n")
        ch += (f"Suspension: Stability={_fv(row.get('SUS_Stability'))}, "
               f"Comfort={_fv(row.get('SUS_Comfort'))}, "
               f"Performance={_fv(row.get('SUS_Performance'))}, "
               f"Braking={_fv(row.get('SUS_Braking'))}, "
               f"Durability={_fv(row.get('SUS_Durability'))}\n")
        ch += (f"Design: Performance={_fv(row.get('ch_DE_Performance'))}, "
               f"Control={_fv(row.get('DE_Control'))}, "
               f"Strength={_fv(row.get('DE_Str'))}, "
               f"Depend={_fv(row.get('DE_Depend'))}\n")
        ch += (f"Tech: Materials={_fv(row.get('ch_TECH_Materials'))}, "
               f"Components={_fv(row.get('ch_TECH_Compoenents'))}, "
               f"Techniques={_fv(row.get('ch_TECH_Techniques'))}, "
               f"Tech={_fv(row.get('ch_TECH_Tech'))}\n")
        ch += (f"DB Ratings: STR={_iv(row.get('StaticOverallStrength'))}→{_iv(row.get('Overall_Strength'))}, "
               f"COM={_iv(row.get('StaticOverallComfort'))}→{_iv(row.get('Overall_Comfort'))}, "
               f"PERF={_iv(row.get('StaticOverallPerformance'))}→{_iv(row.get('Overall_Performance'))}, "
               f"DEP={_iv(row.get('StaticOverallDependabilty'))}→{_iv(row.get('Overall_Dependabilty'))} (static→current)")

        # ── Gearbox ──
        gb = f"\n### Gearbox: {row.get('gearbox_name', '?')} ({_iv(row.get('Gears'))} speed)\n"
        gb += (f"Design: perf={_fv(row.get('g_de_performance'))}, "
               f"fuel={_fv(row.get('de_fuel'))}, "
               f"depend={_fv(row.get('de_depend'))}, "
               f"comfort={_fv(row.get('de_comfort'))}\n")
        gb += (f"Tech: material={_fv(row.get('Tech_Material'))}, "
               f"parts={_fv(row.get('Tech_Parts'))}, "
               f"techniques={_fv(row.get('g_Tech_Techniques'))}, "
               f"tech={_fv(row.get('g_Tech_Tech'))}\n")
        gb += (f"Features: Reverse={_bv(row.get('Reverse'))}, "
               f"Overdrive={_bv(row.get('Overdrive'))}, "
               f"LimitedSlip={_bv(row.get('Limited'))}, "
               f"Transaxle={_bv(row.get('Transaxle'))}\n")
        gb += (f"DB Ratings: Power={_iv(row.get('StaticPowerRating'))}→{_iv(row.get('PowerRating'))}, "
               f"Fuel={_iv(row.get('StaticFuelRating'))}→{_iv(row.get('FuelRating'))}, "
               f"Perf={_iv(row.get('StaticPerformanceRating'))}→{_iv(row.get('PerformanceRating'))}, "
               f"Rely={_iv(row.get('StaticReliabiltyRating'))}→{_iv(row.get('ReliabiltyRating'))}, "
               f"Comfort={_iv(row.get('StaticComfortRating'))}→{_iv(row.get('ComfortRating'))} (static→current)")

        # ── Vehicle ──
        v = f"\n### Vehicle: {car_name}\n"
        v += (f"Interior: Style={_fv(row.get('Scroll_InteriorStyle'))}, "
              f"Inno={_fv(row.get('Scroll_InteriorInno'))}, "
              f"Luxury={_fv(row.get('Scroll_InteriorLux'))}, "
              f"Comfort={_fv(row.get('Scroll_InteriorComf'))}, "
              f"Safety={_fv(row.get('Scroll_InteriorSafe'))}, "
              f"Tech={_fv(row.get('Scroll_InteriorTech'))}\n")
        v += (f"Materials: MatQual={_fv(row.get('Scroll_MatMatQual'))}, "
              f"InterQual={_fv(row.get('Scroll_MatMatInterQual'))}, "
              f"PaintQual={_fv(row.get('Scroll_MatPaintQual'))}, "
              f"ManuTech={_fv(row.get('Scroll_MatManuTech'))}\n")
        v += (f"Design: Style={_fv(row.get('Scroll_DesignStyle'))}, "
              f"Luxury={_fv(row.get('Scroll_DesignLux'))}, "
              f"Safety={_fv(row.get('Scroll_DesignSafety'))}, "
              f"Cargo={_fv(row.get('Scroll_DesignCargo'))}, "
              f"Depend={_fv(row.get('Scroll_DesignDepend'))}\n")
        v += (f"Testing: Demo={_fv(row.get('Scroll_TestDemo'))}, "
              f"Perf={_fv(row.get('Scroll_TestPerform'))}, "
              f"Fuel={_fv(row.get('Scroll_TestFuel'))}, "
              f"Comfort={_fv(row.get('Scroll_TestComf'))}, "
              f"Util={_fv(row.get('Scroll_TestUtil'))}, "
              f"Reli={_fv(row.get('Scroll_TestReli'))}\n")
        v += (f"Demographics: Gender={_iv(row.get('DemoGender'))}, "
              f"Age={_iv(row.get('DemoAge'))}, "
              f"Income={_iv(row.get('DemoIncome'))}\n")
        v += (f"Vehicle Ratings: Perf={_iv(row.get('Rating_Performance'))}, "
              f"Drive={_iv(row.get('Rating_Drivability'))}, "
              f"Luxury={_iv(row.get('Rating_Luxury'))}, "
              f"Safety={_iv(row.get('Rating_Safety'))}, "
              f"Fuel={_iv(row.get('Rating_Fuel'))}, "
              f"Power={_iv(row.get('Rating_Power'))}, "
              f"Cargo={_iv(row.get('Rating_Cargo'))}, "
              f"Quality={_iv(row.get('Rating_Quality'))}, "
              f"Depend={_iv(row.get('Rating_Dependability'))}, "
              f"Overall={_iv(row.get('Rating_Overall'))}")

        # ── Slider Health Warnings ──
        health_warnings = analyze_slider_health(row)
        if health_warnings:
            health_section = "\n### ⚠ Slider Health Warnings\n" + "\n".join(health_warnings)
        else:
            health_section = "\n### ✓ Slider Health: OK (no extreme values detected)"

        parts.append(f"## {car_name}\n{section}{ch}{gb}{v}{health_section}")

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════
# 다단계 설계 자문 헬퍼
# ═══════════════════════════════════════════════════════════════════

def _write_progress(msg: str):
    """스테이지 진행 상황을 콘솔에 출력."""
    try:
        sys.stdout.buffer.write(f"  📐 {msg}\n".encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
    except Exception:
        pass


_GENERIC_PATTERNS = [
    r"구체적\s*수치는\s*설계에\s*따라",
    r"엔진을?\s*디자인할\s*때\s*조절하는",
    r"다음\s*단계\s*제안",
    r"설계가?\s*완료된\s*상태",
    r"일반적인\s*(엔진|샤시|기어박스|차량)\s*설계",
]


def _is_generic_response(text: str) -> bool:
    """응답이 제네릭(교과서적)인지 감지."""
    for pat in _GENERIC_PATTERNS:
        if re.search(pat, text):
            return True
    slider_values = re.findall(r'0\.\d{2}', text)
    if len(slider_values) < 3:
        return True
    return False


def _parse_stage_json(text: str) -> dict:
    """LLM JSON 출력 추출. strip_think_tags → json.loads → 여러 fallback.

    Qwen은 <think> 블록, 마크다운 코드펜스, 설명 텍스트 등을 혼합 출력하므로
    여러 단계로 JSON을 추출한다.
    """
    cleaned = strip_think_tags(text)

    # 1. ```json ... ``` 블록 추출
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            cleaned = json_match.group(1)

    # 2. 첫 { ~ 마지막 } 추출 (가장 바깥 중괄호 매칭)
    brace_start = cleaned.find('{')
    brace_end = cleaned.rfind('}')
    if brace_start >= 0 and brace_end > brace_start:
        candidate = cleaned[brace_start:brace_end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # 3. trailing comma, 한국어 키, 따옴표 없는 값 등 정리 시도
            fixed = re.sub(r',\s*}', '}', candidate)  # trailing comma
            fixed = re.sub(r',\s*]', ']', fixed)  # trailing comma in arrays
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

    # 4. 개별 키-값 추출 fallback (슬라이더 값이라도 건지기)
    sliders = {}
    for m in re.finditer(r'"([^"]+)"\s*:\s*([\d.]+)', cleaned):
        try:
            sliders[m.group(1)] = float(m.group(2))
        except ValueError:
            pass
    if sliders:
        # reasoning 추출 시도
        reasoning_match = re.search(r'"reasoning"\s*:\s*"([^"]*)"', cleaned)
        result = {"sliders": sliders}
        if reasoning_match:
            result["reasoning"] = reasoning_match.group(1)
        return result

    return {}


def _extract_design_goal(llm, question: str, vehicle_summary: str) -> dict:
    """Stage 0: LLM으로 목표 구조화."""
    prompt = DESIGN_GOAL_PROMPT.format(
        question=question,
        vehicle_summary=vehicle_summary,
    )
    messages = [
        SystemMessage(content=DESIGN_SYSTEM_MESSAGE),
        HumanMessage(content=prompt),
    ]
    try:
        response = llm.invoke(messages)
        raw = response.content or ""
    except Exception as e:
        _write_progress(f"  ⚠ Goal extraction failed: {type(e).__name__}: {str(e)[:200]}")
        raw = ""
    goal = _parse_stage_json(raw)

    # 기본값 보장
    goal.setdefault("mode", "new")
    goal.setdefault("car_type", "any")
    goal.setdefault("target_segment", "any")
    goal.setdefault("constraints", {})
    goal.setdefault("priority_list", [])
    goal.setdefault("specific_component", "all")

    return goal


def _build_default_sliders(keys: list[str], value: float = 0.5) -> dict:
    """신규 설계용 기본 슬라이더 dict."""
    return {k: value for k in keys}


def _format_goal_summary(goal: dict) -> str:
    """목표 dict를 LLM 프롬프트용 축약 텍스트로."""
    parts = [
        f"Mode: {goal.get('mode', 'new')}",
        f"Car Type: {goal.get('car_type', 'any')}",
        f"Segment: {goal.get('target_segment', 'any')}",
    ]
    constraints = goal.get("constraints", {})
    if constraints:
        for k, v in constraints.items():
            if v is not None:
                parts.append(f"{k}: {v}")
    priorities = goal.get("priority_list", [])
    if priorities:
        parts.append(f"Priorities: {', '.join(priorities)}")
    return " | ".join(parts)


def _format_constraints(goal: dict) -> str:
    """목표 제약을 읽기 좋게."""
    constraints = goal.get("constraints", {})
    if not constraints:
        return "(No specific constraints)"
    lines = []
    for k, v in constraints.items():
        if v is not None:
            lines.append(f"- {k}: {v}")
    return "\n".join(lines) if lines else "(No specific constraints)"


def _format_component_summary(component: str, verified: dict) -> str:
    """검증된 컴포넌트 결과를 다음 스테이지용 요약으로."""
    lines = []
    for k, v in verified.items():
        if isinstance(v, (int, float)):
            if "cost" in k:
                lines.append(f"  {k}: ${v:,.0f}")
            else:
                lines.append(f"  {k}: {v:.1f}")
    return "\n".join(lines)


def _run_stage(llm, prompt_template: str, system_message: str = DESIGN_SYSTEM_MESSAGE, **kwargs) -> dict:
    """단일 스테이지 실행: SystemMessage + HumanMessage → LLM 호출 → JSON 파싱."""
    user_prompt = prompt_template.format(**kwargs)
    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=user_prompt),
    ]
    try:
        response = llm.invoke(messages)
        raw = response.content or ""
    except Exception as e:
        _write_progress(f"  ⚠ LLM 호출 실패: {type(e).__name__}: {str(e)[:200]}")
        return {}

    # 디버그: LLM 원문 출력
    preview = raw[:800] if raw else "(EMPTY)"
    _write_progress(f"  LLM raw ({len(raw)} chars): {preview}")

    # 응답 메타데이터 (eval_count, done_reason)
    meta = getattr(response, 'response_metadata', {})
    eval_count = meta.get('eval_count', '?')
    done_reason = meta.get('done_reason', '?')
    _write_progress(f"  eval_count={eval_count}, done_reason={done_reason}")
    if done_reason == 'length':
        _write_progress(f"  ⚠ Output truncated! (num_predict 한도 도달)")

    result = _parse_stage_json(raw)
    parsed_sliders = result.get("sliders", {})
    _write_progress(f"  Parsed sliders: {len(parsed_sliders)} keys")
    if not parsed_sliders and raw:
        _write_progress(f"  ⚠ JSON parse failed. Full output ({len(raw)} chars):")
        for i in range(0, min(len(raw), 2000), 200):
            _write_progress(f"    {raw[i:i+200]}")
    return result


def _format_current_sliders(row: dict, keys: list[str]) -> str:
    """현재 슬라이더 값을 key=value 형태로 포맷."""
    if not row:
        return "(New design — no current values)"
    return ", ".join(f"{k}={_fv(row.get(k))}" for k in keys)


# ═══════════════════════════════════════════════════════════════════
# 설계 자문 노드 — 다단계 증거 기반 추론
# ═══════════════════════════════════════════════════════════════════

def design_advisor_node(state: GraphState) -> dict:
    """설계 자문 노드: 다단계 증거 기반 추론 파이프라인.

    Stage 0: 목표 추출 (1 LLM call)
    Stage 1: Engine (감도 분석 + LLM 추론)
    Stage 2: Chassis (감도 분석 + LLM 추론)
    Stage 3: Gearbox (감도 분석 + LLM 추론)
    Stage 4: Vehicle (LLM 추론)
    Stage 5: 종합 검증 + 요약 (1 LLM call)
    """
    db_path = state["db_path"]
    question = state["user_question"]
    llm = create_llm(temperature=0.3, max_tokens=LLM_MAX_TOKENS_DESIGN)

    # ── Step 1: 데이터 수집 ──
    _write_progress("DB 데이터 조회 중...")
    rows, design_context, current_year = _fetch_vehicle_data(db_path)
    skill_rnd, tech_context = _fetch_tech_components(db_path, current_year)
    _write_progress(f"조회 완료: year={current_year}, skill={skill_rnd}, vehicles={len(rows)}")

    # ── Step 1.5: 서브컴포넌트 속성 (NEW) ──
    sub_data = _fetch_sub_components(db_path, rows) if rows else {}

    # ── Stage 0: 목표 추출 (1 LLM call) ──
    _write_progress("Stage 0: 설계 목표 추출 중...")
    vehicle_summary = _format_slider_context(rows) if rows else "(신규 설계 — 활성 차량 없음)"
    if len(vehicle_summary) > 6000:
        vehicle_summary = vehicle_summary[:6000] + "\n...(truncated)"
    goal = _extract_design_goal(llm, question, vehicle_summary)
    _write_progress(f"목표: mode={goal.get('mode')}, scope={goal.get('specific_component')}, type={goal.get('car_type')}")

    # ── 타겟 차량 결정 ──
    target = rows[0] if rows else None
    mode = goal.get("mode", "new" if not target else "optimize")
    scope = goal.get("specific_component", "all")

    # ── 슬라이더/서브 준비 ──
    if target:
        car_id = target["Car_ID"]
        car_sub = sub_data.get(car_id, {})
        engine_sliders = {k: float(target.get(k, 0.5) or 0.5) for k in ENGINE_SLIDER_KEYS}
        engine_sub = car_sub.get("engine_sub", {})
        chassis_sliders = {k: float(target.get(k, 0.5) or 0.5) for k in CHASSIS_SLIDER_KEYS}
        chassis_sub = car_sub.get("chassis_sub", {})
        gearbox_sliders = {k: float(target.get(k, 0.5) or 0.5) for k in GEARBOX_SLIDER_KEYS}
        gearbox_sub = car_sub.get("gearbox_sub", {})
        vehicle_sliders = {k: float(target.get(k, 0.5) or 0.5) for k in VEHICLE_SLIDER_KEYS}
        bore_mm = float(target.get("bore", 70) or 70)
        stroke_mm = float(target.get("stroke", 80) or 80)
        cylinders = int(target.get("cylinders", 4) or 4)
        gears = int(target.get("Gears", 4) or 4)
    else:
        engine_sliders = _build_default_sliders(ENGINE_SLIDER_KEYS)
        engine_sub = {}
        chassis_sliders = _build_default_sliders(CHASSIS_SLIDER_KEYS)
        chassis_sub = {}
        gearbox_sliders = _build_default_sliders(GEARBOX_SLIDER_KEYS)
        gearbox_sub = {}
        vehicle_sliders = _build_default_sliders(VEHICLE_SLIDER_KEYS)
        bore_mm, stroke_mm, cylinders, gears = 70.0, 80.0, 4, 4

    goal_summary = _format_goal_summary(goal)
    constraints_text = _format_constraints(goal)
    stage_results = []  # 디버깅용 전체 스테이지 결과

    # ═══ Stage 1: Engine ═══
    verified_engine = {}
    engine_result = {}
    if scope in ("all", "engine"):
        _write_progress("Stage 1: 엔진 감도 분석 (14 sliders)...")
        engine_sensitivity = compute_sensitivity(
            "engine", engine_sliders, engine_sub,
            current_year, skill_rnd,
            bore_mm=bore_mm, stroke_mm=stroke_mm, cylinders=cylinders,
        )
        engine_cards = format_evidence_cards("engine", engine_sensitivity)

        _write_progress("Stage 1: 엔진 LLM 추론 중...")
        engine_result = _run_stage(
            llm, DESIGN_STAGE_ENGINE_PROMPT,
            goal_summary=goal_summary,
            engine_evidence_cards=engine_cards if len(engine_cards) < 6000 else engine_cards[:6000] + "\n...(truncated)",
            constraints=constraints_text,
            available_components=tech_context if len(tech_context) < 4000 else tech_context[:4000] + "\n...(truncated)",
            current_engine=_format_current_sliders(target, ENGINE_SLIDER_KEYS),
        )
        _sliders_parsed = bool(engine_result.get("sliders"))
        _write_progress(f"Stage 1 완료: sliders={'OK' if _sliders_parsed else 'fallback'}")

        # Python 검증
        result_sliders = engine_result.get("sliders", engine_sliders)
        result_bore = engine_result.get("bore_mm", bore_mm)
        result_stroke = engine_result.get("stroke_mm", stroke_mm)
        result_cylinders = engine_result.get("cylinders", cylinders)
        verified_engine = estimate_engine_full(
            dict(result_sliders), dict(engine_sub), current_year, skill_rnd,
            result_bore, result_stroke, result_cylinders,
        )
        engine_result["verified"] = verified_engine
        stage_results.append({"stage": "engine", "result": engine_result})
    else:
        # 기존 엔진 스펙으로 폴백
        verified_engine = estimate_engine_full(
            dict(engine_sliders), dict(engine_sub), current_year, skill_rnd,
            bore_mm, stroke_mm, cylinders,
        )

    # ═══ Stage 2: Chassis ═══
    verified_chassis = {}
    chassis_result = {}
    if scope in ("all", "chassis"):
        _write_progress("Stage 2: 샤시 감도 분석 (19 sliders)...")
        chassis_sensitivity = compute_sensitivity(
            "chassis", chassis_sliders, chassis_sub,
            current_year, skill_rnd,
        )
        chassis_cards = format_evidence_cards("chassis", chassis_sensitivity)

        _write_progress("Stage 2: 샤시 LLM 추론 중...")
        chassis_result = _run_stage(
            llm, DESIGN_STAGE_CHASSIS_PROMPT,
            goal_summary=goal_summary,
            prev_engine=_format_component_summary("engine", verified_engine),
            chassis_evidence_cards=chassis_cards if len(chassis_cards) < 6000 else chassis_cards[:6000] + "\n...(truncated)",
            constraints=constraints_text,
            current_chassis=_format_current_sliders(target, CHASSIS_SLIDER_KEYS),
        )
        _write_progress(f"Stage 2 완료: sliders={'OK' if chassis_result.get('sliders') else 'fallback'}")

        result_sliders = chassis_result.get("sliders", chassis_sliders)
        verified_chassis = estimate_chassis_full(
            dict(result_sliders), dict(chassis_sub), current_year, skill_rnd,
        )
        chassis_result["verified"] = verified_chassis
        stage_results.append({"stage": "chassis", "result": chassis_result})
    else:
        verified_chassis = estimate_chassis_full(
            dict(chassis_sliders), dict(chassis_sub), current_year, skill_rnd,
        )

    # ═══ Stage 3: Gearbox ═══
    verified_gearbox = {}
    gearbox_result = {}
    engine_torque = verified_engine.get("torque", 0)

    if scope in ("all", "gearbox"):
        _write_progress("Stage 3: 기어박스 감도 분석 (8 sliders)...")
        gearbox_sensitivity = compute_sensitivity(
            "gearbox", gearbox_sliders, gearbox_sub,
            current_year, skill_rnd, gears=gears,
        )
        gearbox_cards = format_evidence_cards("gearbox", gearbox_sensitivity)

        _write_progress("Stage 3: 기어박스 LLM 추론 중...")
        gearbox_result = _run_stage(
            llm, DESIGN_STAGE_GEARBOX_PROMPT,
            goal_summary=goal_summary,
            prev_engine=_format_component_summary("engine", verified_engine),
            prev_chassis=_format_component_summary("chassis", verified_chassis),
            gearbox_evidence_cards=gearbox_cards if len(gearbox_cards) < 6000 else gearbox_cards[:6000] + "\n...(truncated)",
            constraints=constraints_text,
            current_gearbox=_format_current_sliders(target, GEARBOX_SLIDER_KEYS),
            engine_torque=engine_torque,
        )
        _write_progress(f"Stage 3 완료: sliders={'OK' if gearbox_result.get('sliders') else 'fallback'}")

        result_sliders = gearbox_result.get("sliders", gearbox_sliders)
        result_gears = gearbox_result.get("gears", gears)
        verified_gearbox = estimate_gearbox_full(
            dict(result_sliders), dict(gearbox_sub), result_gears,
            current_year, skill_rnd,
        )
        gearbox_result["verified"] = verified_gearbox
        stage_results.append({"stage": "gearbox", "result": gearbox_result})
    else:
        verified_gearbox = estimate_gearbox_full(
            dict(gearbox_sliders), dict(gearbox_sub), gears,
            current_year, skill_rnd,
        )

    # ═══ Stage 4: Vehicle ═══
    vehicle_result = {}
    component_cost = (verified_engine.get("unit_cost", 0) +
                      verified_chassis.get("unit_cost", 0) +
                      verified_gearbox.get("unit_cost", 0))
    max_cost = goal.get("constraints", {}).get("max_unit_cost")
    cost_budget_remaining = (max_cost - component_cost) if max_cost else 500

    if scope in ("all", "vehicle"):
        _write_progress("Stage 4: 차량 LLM 추론 중...")
        vehicle_result = _run_stage(
            llm, DESIGN_STAGE_VEHICLE_PROMPT,
            goal_summary=goal_summary,
            prev_engine=_format_component_summary("engine", verified_engine),
            prev_chassis=_format_component_summary("chassis", verified_chassis),
            prev_gearbox=_format_component_summary("gearbox", verified_gearbox),
            engine_power_r=f"{verified_engine.get('power_rating', 0):.1f}",
            engine_fuel_r=f"{verified_engine.get('fuel_eco_rating', 0):.1f}",
            engine_rel_r=f"{verified_engine.get('reliability_rating', 0):.1f}",
            chassis_comfort_r=f"{verified_chassis.get('comfort_rating', 0):.1f}",
            chassis_perf_r=f"{verified_chassis.get('performance_rating', 0):.1f}",
            chassis_str_r=f"{verified_chassis.get('strength_rating', 0):.1f}",
            chassis_dep_r=f"{verified_chassis.get('dependability_rating', 0):.1f}",
            gearbox_power_r=f"{verified_gearbox.get('power_rating', 0):.1f}",
            gearbox_fuel_r=f"{verified_gearbox.get('fuel_rating', 0):.1f}",
            gearbox_perf_r=f"{verified_gearbox.get('performance_rating', 0):.1f}",
            gearbox_rel_r=f"{verified_gearbox.get('reliability_rating', 0):.1f}",
            component_cost=component_cost,
            constraints=constraints_text,
            current_vehicle=_format_current_sliders(target, VEHICLE_SLIDER_KEYS),
            cost_budget_remaining=max(cost_budget_remaining, 0),
        )
        _write_progress(f"Stage 4 완료: sliders={'OK' if vehicle_result.get('sliders') else 'fallback'}")
        stage_results.append({"stage": "vehicle", "result": vehicle_result})

    # ═══ Stage 5: 종합 검증 + 요약 ═══
    _write_progress("Stage 5: Python 종합 검증 + LLM 요약...")
    # 최종 슬라이더 결정 (각 스테이지 결과 또는 기존 값)
    final_engine_sl = engine_result.get("sliders", engine_sliders)
    final_chassis_sl = chassis_result.get("sliders", chassis_sliders)
    final_gearbox_sl = gearbox_result.get("sliders", gearbox_sliders)
    final_vehicle_sl = vehicle_result.get("sliders", vehicle_sliders)
    final_bore = engine_result.get("bore_mm", bore_mm)
    final_stroke = engine_result.get("stroke_mm", stroke_mm)
    final_cylinders = engine_result.get("cylinders", cylinders)
    final_gears = gearbox_result.get("gears", gears)

    # Python 종합 검증
    verification = verify_full_design(
        final_engine_sl, engine_sub,
        final_chassis_sl, chassis_sub,
        final_gearbox_sl, gearbox_sub,
        final_vehicle_sl,
        current_year, skill_rnd,
        final_bore, final_stroke, final_cylinders, final_gears,
    )

    # 검증 결과 요약 (scope에 맞게 필터링)
    v = verification
    verification_lines = []
    if scope in ("all", "engine"):
        verification_lines.append(
            f"Engine — Torque: {v['engine']['torque']:.1f}, HP: {v['engine']['hp']}, "
            f"RPM: {v['engine']['rpm']}, FuelEco: {v['engine']['fuel_mpg']:.1f}mpg, "
            f"Unit Cost: ${v['engine']['unit_cost']:,}"
        )
    if scope in ("all", "chassis"):
        verification_lines.append(
            f"Chassis — Weight: {v['chassis']['weight_kg']:.1f}kg, "
            f"Comfort: {v['chassis']['comfort_rating']:.1f}, "
            f"Unit Cost: ${v['chassis']['unit_cost']:,}"
        )
    if scope in ("all", "gearbox"):
        verification_lines.append(
            f"Gearbox — Torque Cap: {v['gearbox']['torque_capacity']:.1f}, "
            f"Unit Cost: ${v['gearbox']['unit_cost']:,}"
        )
    if scope == "all":
        verification_lines.append(f"Total Component Unit Cost: ${v['total_unit_cost']:,}")
    # 토크 호환성은 엔진/기어박스 관련이면 항상 표시
    if scope in ("all", "engine", "gearbox"):
        verification_lines.append(f"Torque Compatible: {v['torque_compatibility']['compatible']}")
    if v["constraint_violations"]:
        verification_lines.append(f"VIOLATIONS: {', '.join(v['constraint_violations'])}")
    else:
        verification_lines.append("All constraints satisfied.")
    verification_summary = "\n".join(verification_lines)

    # 스테이지 추론 요약
    stage_reasoning_parts = []
    for sr in stage_results:
        stage_name = sr["stage"]
        result = sr["result"]
        reasoning = result.get("reasoning", "")
        sliders = result.get("sliders", {})

        part = f"### {stage_name.title()}\n"
        if reasoning:
            part += f"Reasoning: {reasoning}\n"
        if sliders:
            slider_lines = [f"  {k}: {v:.2f}" if isinstance(v, float) else f"  {k}: {v}"
                            for k, v in sliders.items()]
            part += "Recommended sliders:\n" + "\n".join(slider_lines[:20])
        else:
            part += "(LLM did not return slider values — using defaults)"

        # 검증 결과 포함
        verified = result.get("verified", {})
        if verified:
            part += "\nVerified metrics: " + ", ".join(
                f"{k}={v:.1f}" if isinstance(v, float) else f"{k}={v}"
                for k, v in verified.items()
                if isinstance(v, (int, float))
            )
        stage_reasoning_parts.append(part)

    if not stage_reasoning_parts:
        # 스테이지 실패 시 감도 분석 증거 카드를 직접 포함
        stage_reasoning = (
            "No LLM stage reasoning available. "
            "The Python sensitivity analysis and verification results above contain all computed data."
        )
    else:
        stage_reasoning = "\n\n".join(stage_reasoning_parts)

    # 차량 상태 텍스트
    if rows:
        vehicle_status = f"- Active Vehicles: {len(rows)} ({', '.join(r.get('Name', '?') for r in rows[:5])})"
    else:
        vehicle_status = "- Active Vehicles: 0 (new game — designing from scratch)"

    # LLM 최종 요약 (1 call) — SystemMessage로 역할 고정
    summary_prompt = DESIGN_SUMMARY_PROMPT.format(
        goal_summary=goal_summary,
        verification_summary=verification_summary,
        stage_reasoning=stage_reasoning,
        skill_rnd=skill_rnd,
        current_year=current_year,
        vehicle_status=vehicle_status,
        tech_context=tech_context if len(tech_context) < 4000 else tech_context[:4000] + "\n...(truncated)",
        question=question,
        scope=scope,
    )
    summary_messages = [
        SystemMessage(content=DESIGN_SYSTEM_MESSAGE),
        HumanMessage(content=summary_prompt),
    ]
    try:
        summary_response = llm.invoke(summary_messages)
        raw_summary = summary_response.content or ""
    except Exception as e:
        _write_progress(f"  ⚠ Summary LLM 호출 실패: {type(e).__name__}: {str(e)[:200]}")
        raw_summary = ""

    _write_progress(f"  Summary raw ({len(raw_summary)} chars): {raw_summary[:500] if raw_summary else '(EMPTY)'}")

    # Summary 메타데이터 진단
    try:
        s_meta = getattr(summary_response, 'response_metadata', {})
        s_eval = s_meta.get('eval_count', '?')
        s_done = s_meta.get('done_reason', '?')
        _write_progress(f"  Summary eval_count={s_eval}, done_reason={s_done}")
        if s_done == 'length':
            _write_progress(f"  ⚠ Summary truncated! (num_predict 한도 도달)")
    except NameError:
        pass

    answer = strip_think_tags(raw_summary)
    if not answer.strip():
        _write_progress("  ⚠ Summary is empty — Python 검증 결과로 대체")
        answer = f"## 설계 검증 결과 (Python 계산)\n\n{verification_summary}\n\n(LLM 요약 생성 실패 — 위 데이터는 정확한 계산 결과입니다)"

    # 세션 메모리에 설계 결과 캐시
    get_memory().put("vehicle_design", verification_summary)

    return {
        "final_answer": answer,
        "design_calc_results": verification_summary,
        "design_context": design_context,
        "design_goal": goal,
        "design_stages": stage_results,
    }


# ═══════════════════════════════════════════════════════════════════
# 이벤트 예측 노드 (변경 없음)
# ═══════════════════════════════════════════════════════════════════

def forecast_advisor_node(state: GraphState) -> dict:
    """이벤트 예측 노드: 타임라인 데이터 로드 → 플레이어 자산 위험 분석 → LLM 합성."""
    db_path = state["db_path"]
    analyst_summary = state.get("analyst_summary", "")

    # ── Step 1: 현재 연도 + 플레이어 자산 도시 목록 조회 ──
    current_year = 1900
    current_month = 1
    player_city_ids = []

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

        # 현재 연도/월
        cursor = conn.execute(CURRENT_YEAR_SQL)
        row = cursor.fetchone()
        if row:
            try:
                current_year = int(row[0])
            except (ValueError, TypeError):
                pass

        cursor = conn.execute(CURRENT_TURN_SQL)
        row = cursor.fetchone()
        if row:
            try:
                current_month = int(row[0])
            except (ValueError, TypeError):
                pass

        # 플레이어 공장/지점 도시 목록
        cursor = conn.execute(PLAYER_CITY_IDS_SQL)
        player_city_ids = [r[0] for r in cursor.fetchall()]
        conn.close()

    except Exception:
        pass  # 조회 실패 시 빈 목록으로 진행

    # ── Step 2: 타임라인 데이터 로드 + 분석 ──
    forecast_summary = ""
    asset_risk_report = ""

    try:
        tl = get_timeline()
        forecast_summary = tl.format_forecast_summary(current_year, lookahead=15)

        if player_city_ids:
            risks = tl.check_player_asset_risks(player_city_ids, current_year, lookahead=15)
            asset_risk_report = tl.format_asset_risk_report(risks, current_year)
        else:
            asset_risk_report = "(플레이어 자산 도시 정보 없음 — 아직 공장/판매점이 없거나 게임 초기 상태)"

    except Exception as e:
        forecast_summary = f"(타임라인 데이터 로드 실패: {e})"
        asset_risk_report = "(위험 분석 불가)"

    # ── Step 3: LLM 합성 ──
    llm = create_llm(temperature=0.3)
    prompt = FORECAST_ADVISOR_PROMPT.format(
        question=state["user_question"],
        analyst_summary=analyst_summary,
        forecast_summary=forecast_summary,
        asset_risk_report=asset_risk_report,
    )
    response = llm.invoke(prompt)
    answer = strip_think_tags(response.content)

    # 세션 메모리에 예측 결과 캐시
    get_memory().put("forecast", forecast_summary + "\n\n" + asset_risk_report)

    return {
        "final_answer": answer,
        "forecast_context": forecast_summary + "\n\n" + asset_risk_report,
    }
