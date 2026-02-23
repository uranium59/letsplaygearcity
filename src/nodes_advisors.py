"""
GearCity Advisor Nodes — 전문 자문 노드
========================================
design_advisor, forecast_advisor
"""

import sqlite3

import pandas as pd

from src.graph_state import GraphState
from src.prompts import DESIGN_ADVISOR_PROMPT, FORECAST_ADVISOR_PROMPT
from src.queries import (
    DESIGN_VEHICLE_SQL, CURRENT_YEAR_SQL, CURRENT_TURN_SQL,
    TECH_SKILL_SQL, AVAILABLE_COMPONENTS_SQL_TEMPLATE, PLAYER_CITY_IDS_SQL,
)
from src.graph_utils import create_llm, strip_think_tags
from src.design_formulas import (
    EngineParams,
    VehicleParams,
    calc_staleness,
    compare_ratings,
    check_torque_compatibility,
    estimate_modification_cost,
    simulate_bore_change,
    format_design_report,
)
from src.event_timeline import get_timeline
from src.session_memory import get_memory


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


def _calculate_design_metrics(rows: list[dict], current_year: int) -> str:
    """Step 2: Python 계산 (노후화, 개선비용, 토크, 레이팅, 보어 시뮬)."""
    try:
        all_reports = []
        for row in rows:
            engine = EngineParams(
                engine_id=row.get("Engine_ID", 0),
                bore=row.get("bore", 0) or 0,
                stroke=row.get("stroke", 0) or 0,
                cylinders=row.get("cylinders", 0) or 0,
                hp=row.get("engine_hp", 0) or 0,
                torque=row.get("engine_torque", 0) or 0,
                rpm=row.get("engine_rpm", 0) or 0,
                weight=row.get("engine_weight", 0) or 0,
                size_cc=row.get("size_cc", 0) or 0,
                fuel_milage=row.get("fuelmilage", 0) or 0,
                year_built=row.get("engine_year", 0) or 0,
                mod_year=row.get("engine_mod_year", 0) or 0,
                design_cost=row.get("engine_designcost", 0) or 0,
                static_power=row.get("StaticenginePower", 0) or 0,
                static_fuel_eco=row.get("StaticengineFuelEco", 0) or 0,
                static_reliability=row.get("StaticengineReliability", 0) or 0,
                static_smooth=row.get("StaticRating_Smooth", 0) or 0,
                current_power=row.get("enginePower", 0) or 0,
                current_fuel_eco=row.get("engineFuelEco", 0) or 0,
                current_reliability=row.get("engineReliability", 0) or 0,
                current_smooth=row.get("Rating_Smooth", 0) or 0,
            )

            vehicle = VehicleParams(
                car_id=row.get("Car_ID", 0),
                name=row.get("Name", ""),
                trim=row.get("Trim", ""),
                car_type=row.get("CarType", ""),
                year_built=row.get("car_year", 0) or 0,
                design_cost=row.get("car_designcost", 0) or 0,
                mod_amount=row.get("ModAmount", 0) or 0,
                parent_car_id=row.get("ParentCarID", -1) or -1,
                engine_id=row.get("Engine_ID", 0),
                chassis_id=row.get("Chassis_ID", 0),
                gearbox_id=row.get("Gearbox_ID", 0),
                spec_hp=row.get("Spec_HP", 0) or 0,
                spec_torque=row.get("Spec_Torque", 0) or 0,
                spec_rpm=row.get("Spec_RPM", 0) or 0,
                spec_weight=row.get("Spec_Weight", 0) or 0,
                spec_top_speed=row.get("Spec_TopSpeed", 0) or 0,
                spec_fuel=row.get("Spec_Fuel", 0) or 0,
                rating_performance=row.get("Rating_Performance", 0) or 0,
                rating_drivability=row.get("Rating_Drivability", 0) or 0,
                rating_luxury=row.get("Rating_Luxury", 0) or 0,
                rating_safety=row.get("Rating_Safety", 0) or 0,
            )

            # 노후화
            engine_effective_year = engine.mod_year if engine.mod_year > engine.year_built else engine.year_built
            chassis_year = row.get("chassis_year", 0) or 0
            chassis_mod_year = row.get("chassis_mod_year", 0) or 0
            chassis_effective = chassis_mod_year if chassis_mod_year > chassis_year else chassis_year
            gearbox_year = row.get("gearbox_year", 0) or 0
            gearbox_mod_year = row.get("gearbox_mod_year", 0) or 0
            gearbox_effective = gearbox_mod_year if gearbox_mod_year > gearbox_year else gearbox_year

            staleness = calc_staleness(
                current_year, vehicle.year_built,
                engine_effective_year, chassis_effective, gearbox_effective,
            )

            # 개선 비용 (4가지 시나리오)
            mod_base = estimate_modification_cost(vehicle.design_cost)
            mod_engine = estimate_modification_cost(vehicle.design_cost, engine_change=True)
            mod_gearbox = estimate_modification_cost(vehicle.design_cost, gearbox_change=True)
            mod_chassis = estimate_modification_cost(vehicle.design_cost, chassis_change=True)
            mod_costs = {
                "cost_breakdown_text": (
                    f"기본 New Gen: ${mod_base['estimated_cost']:,} ({mod_base['total_percent']}%)\n"
                    f"+ 엔진 변경: ${mod_engine['estimated_cost']:,} ({mod_engine['total_percent']}%)\n"
                    f"+ 기어박스만: ${mod_gearbox['estimated_cost']:,} ({mod_gearbox['total_percent']}%)\n"
                    f"+ 샤시 변경: ${mod_chassis['estimated_cost']:,} ({mod_chassis['total_percent']}%)"
                ),
            }

            # 토크 호환성
            torque_check = check_torque_compatibility(
                engine.torque, row.get("MaxTorqueInput", 0) or 0,
            )

            # 엔진 레이팅 변화
            engine_rating_deltas = compare_ratings(
                {"Power": engine.static_power, "FuelEco": engine.static_fuel_eco,
                 "Reliability": engine.static_reliability, "Smooth": engine.static_smooth},
                {"Power": engine.current_power, "FuelEco": engine.current_fuel_eco,
                 "Reliability": engine.current_reliability, "Smooth": engine.current_smooth},
            )

            # 샤시 레이팅 변화
            chassis_rating_deltas = compare_ratings(
                {"Strength": row.get("StaticOverallStrength", 0) or 0,
                 "Comfort": row.get("StaticOverallComfort", 0) or 0,
                 "Performance": row.get("StaticOverallPerformance", 0) or 0,
                 "Dependability": row.get("StaticOverallDependabilty", 0) or 0},
                {"Strength": row.get("Overall_Strength", 0) or 0,
                 "Comfort": row.get("Overall_Comfort", 0) or 0,
                 "Performance": row.get("Overall_Performance", 0) or 0,
                 "Dependability": row.get("Overall_Dependabilty", 0) or 0},
            )

            # 보어 시뮬레이션 (+5mm)
            bore_sim = None
            if engine.bore > 0:
                bore_sim = simulate_bore_change(engine, engine.bore + 5)

            report = format_design_report(
                vehicle=vehicle,
                staleness=staleness,
                mod_costs=mod_costs,
                torque_check=torque_check,
                rating_deltas={**engine_rating_deltas, **chassis_rating_deltas},
                bore_sim=bore_sim,
            )
            all_reports.append(f"--- {vehicle.name} {vehicle.trim} (ID: {vehicle.car_id}) ---\n{report}")

        return "\n\n".join(all_reports) if all_reports else "(계산 대상 차량 없음)"

    except Exception as e:
        return f"(Python 계산 오류: {e})"


def design_advisor_node(state: GraphState) -> dict:
    """설계 자문 노드: SQL 데이터 수집 → Python 계산 → LLM 합성."""
    db_path = state["db_path"]
    analyst_summary = state.get("analyst_summary", "")

    # Step 1: DB에서 차량 데이터 + 현재 연도 조회
    rows, design_context, current_year = _fetch_vehicle_data(db_path)

    # Step 1.5: 기술 레벨 + 사용 가능 컴포넌트 조회
    skill_rnd, tech_context = _fetch_tech_components(db_path, current_year)

    # Step 2: Python 계산
    calc_results = _calculate_design_metrics(rows, current_year)

    # Step 3: LLM 합성
    llm = create_llm(temperature=0.3)
    prompt = DESIGN_ADVISOR_PROMPT.format(
        question=state["user_question"],
        analyst_summary=analyst_summary,
        calc_results=calc_results,
        design_context=design_context if len(design_context) < 8000 else design_context[:8000] + "\n...(truncated)",
        skill_rnd=skill_rnd,
        current_year=current_year,
        tech_context=tech_context if len(tech_context) < 4000 else tech_context[:4000] + "\n...(truncated)",
    )
    response = llm.invoke(prompt)
    answer = strip_think_tags(response.content)

    # 세션 메모리에 설계 결과 캐시
    get_memory().put("vehicle_design", calc_results)

    return {
        "final_answer": answer,
        "design_calc_results": calc_results,
        "design_context": design_context,
    }


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
