"""
GearCity Advisor Nodes — 전문 자문 노드
========================================
design_advisor, forecast_advisor
"""

import sqlite3
from pathlib import Path

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
    analyze_slider_health,
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


# ── 위키 레퍼런스 로드 ──────────────────────────────────────────

_DESIGN_REF_DIR = Path(__file__).resolve().parent.parent / "data" / "wiki"


def _load_design_reference(component_type: str) -> str:
    """design_ref_{type}.md 파일 로드."""
    path = _DESIGN_REF_DIR / f"design_ref_{component_type}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


_ENGINE_KW = ["엔진", "engine", "bore", "stroke", "실린더", "cylinder", "hp",
              "마력", "토크", "torque", "rpm", "배기량", "displacement"]
_CHASSIS_KW = ["샤시", "chassis", "서스펜션", "suspension", "프레임", "frame",
               "브레이크", "brake", "차체"]
_GEARBOX_KW = ["기어박스", "gearbox", "변속기", "기어", "gear", "변속"]
_GENERAL_KW = ["슬라이더", "slider", "설계", "design", "개선", "improve",
               "최적", "optim", "업그레이드", "upgrade", "전체", "모든", "all"]


def _select_design_references(question: str) -> str:
    """질문 키워드에 따라 관련 위키 레퍼런스 선택 주입."""
    q = question.lower()
    refs = [_load_design_reference("vehicle")]  # 항상 포함

    need_all = any(kw in q for kw in _GENERAL_KW)
    if need_all or any(kw in q for kw in _ENGINE_KW):
        refs.append(_load_design_reference("engine"))
    if need_all or any(kw in q for kw in _CHASSIS_KW):
        refs.append(_load_design_reference("chassis"))
    if need_all or any(kw in q for kw in _GEARBOX_KW):
        refs.append(_load_design_reference("gearbox"))

    combined = "\n\n---\n\n".join(r for r in refs if r)
    if len(combined) > 12000:
        combined = combined[:12000] + "\n...(truncated)"
    return combined


# ── 슬라이더 컨텍스트 포맷팅 ─────────────────────────────────────

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

    # Step 2.5: 슬라이더 컨텍스트 + 위키 레퍼런스 생성
    slider_context = _format_slider_context(rows)
    design_reference = _select_design_references(state["user_question"])

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
        slider_context=slider_context if len(slider_context) < 8000 else slider_context[:8000] + "\n...(truncated)",
        design_reference=design_reference,
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
