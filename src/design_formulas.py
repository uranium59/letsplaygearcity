"""
GearCity Design Formulas — Python 계산 엔진
=============================================
차량/엔진/샤시/기어박스 설계 파라미터에 대한 정확한 수치 계산.
위키 공식 기반으로 displacement, HP, 노후화 페널티, 개선 비용 등을 계산한다.

이 모듈은 독립적이며 DB나 LLM 의존성이 없다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ── 데이터클래스 ─────────────────────────────────────────────────

@dataclass
class EngineParams:
    engine_id: int = 0
    name: str = ""
    bore: float = 0.0
    stroke: float = 0.0
    cylinders: int = 0
    hp: int = 0
    torque: int = 0
    rpm: int = 0
    weight: int = 0
    size_cc: int = 0
    fuel_milage: float = 0.0
    year_built: int = 0
    mod_year: int = 0
    design_cost: int = 0
    # Static ratings (설계 시점)
    static_power: int = 0
    static_fuel_eco: int = 0
    static_reliability: int = 0
    static_smooth: int = 0
    # Current ratings (현재)
    current_power: int = 0
    current_fuel_eco: int = 0
    current_reliability: int = 0
    current_smooth: int = 0


@dataclass
class ChassisParams:
    chassis_id: int = 0
    name: str = ""
    weight_kg: int = 0
    length_cm: int = 0
    width_cm: int = 0
    year_built: int = 0
    mod_year: int = 0
    design_cost: int = 0
    # Static ratings (설계 시점)
    static_strength: float = 0.0
    static_comfort: float = 0.0
    static_performance: float = 0.0
    static_dependability: float = 0.0
    # Current ratings (현재)
    current_strength: float = 0.0
    current_comfort: float = 0.0
    current_performance: float = 0.0
    current_dependability: float = 0.0


@dataclass
class GearboxParams:
    gearbox_id: int = 0
    name: str = ""
    gears: int = 0
    gearbox_type: str = ""
    lo_ratio: float = 0.0
    hi_ratio: float = 0.0
    max_torque_input: int = 0
    weight: int = 0
    year_built: int = 0
    mod_year: int = 0
    design_cost: int = 0
    # Static ratings (설계 시점)
    static_power: int = 0
    static_fuel: int = 0
    static_performance: int = 0
    static_reliability: int = 0
    static_comfort: int = 0
    # Current ratings (현재)
    current_power: int = 0
    current_fuel: int = 0
    current_performance: int = 0
    current_reliability: int = 0
    current_comfort: int = 0


@dataclass
class VehicleParams:
    car_id: int = 0
    name: str = ""
    trim: str = ""
    car_type: str = ""
    year_built: int = 0
    design_cost: int = 0
    mod_amount: int = 0
    parent_car_id: int = -1
    engine_id: int = 0
    chassis_id: int = 0
    gearbox_id: int = 0
    # Specs
    spec_hp: int = 0
    spec_torque: int = 0
    spec_rpm: int = 0
    spec_weight: int = 0
    spec_top_speed: int = 0
    spec_fuel: float = 0.0
    spec_accel_sixty: int = 0
    spec_accel_hundred: int = 0
    # Ratings
    rating_performance: int = 0
    rating_drivability: int = 0
    rating_luxury: int = 0
    rating_safety: int = 0


# ── A2. 엔진 계산 함수 ──────────────────────────────────────────

def calc_displacement(bore_mm: float, stroke_mm: float, cylinders: int) -> int:
    """배기량 계산: CC = 0.7854 * (bore/10)^2 * (stroke/10) * cylinders"""
    bore_cm = bore_mm / 10.0
    stroke_cm = stroke_mm / 10.0
    cc = 0.7854 * (bore_cm ** 2) * stroke_cm * cylinders
    return round(cc)


def calc_hp(torque: int, rpm: int) -> int:
    """마력 계산: HP = (torque * rpm) / 5252"""
    if rpm <= 0:
        return 0
    return round((torque * rpm) / 5252)


def simulate_bore_change(params: EngineParams, new_bore: float) -> dict:
    """보어 변경 시 displacement → torque(비례추정) → HP 변화 예측.

    보어 증가 → 배기량 증가 → 토크 비례 증가 → HP 증가.
    연비는 배기량에 반비례하여 감소.
    """
    old_cc = calc_displacement(params.bore, params.stroke, params.cylinders)
    new_cc = calc_displacement(new_bore, params.stroke, params.cylinders)

    if old_cc <= 0:
        return {
            "error": "현재 배기량이 0입니다. 보어/스트로크/실린더 데이터를 확인하세요.",
        }

    ratio = new_cc / old_cc
    est_torque = round(params.torque * ratio)
    est_hp = calc_hp(est_torque, params.rpm)

    return {
        "old_bore": params.bore,
        "new_bore": new_bore,
        "bore_delta": round(new_bore - params.bore, 2),
        "old_cc": old_cc,
        "new_cc": new_cc,
        "cc_delta": new_cc - old_cc,
        "old_torque": params.torque,
        "est_torque": est_torque,
        "torque_delta": est_torque - params.torque,
        "old_hp": params.hp,
        "est_hp": est_hp,
        "hp_delta": est_hp - params.hp,
        "fuel_impact": f"연비 약 {(1 - 1/ratio) * 100:+.1f}% 변화 예상" if ratio != 1 else "변화 없음",
    }


def simulate_stroke_change(params: EngineParams, new_stroke: float) -> dict:
    """스트로크 변경 시 displacement ↑, RPM ↓ 상충 효과 예측.

    스트로크 증가 → 배기량 증가 + 토크 증가, but RPM 감소 경향.
    위키: 스트로크 증가 시 RPM이 비례적으로 감소하는 경향.
    """
    old_cc = calc_displacement(params.bore, params.stroke, params.cylinders)
    new_cc = calc_displacement(params.bore, new_stroke, params.cylinders)

    if old_cc <= 0 or params.stroke <= 0:
        return {
            "error": "현재 배기량/스트로크가 0입니다. 데이터를 확인하세요.",
        }

    cc_ratio = new_cc / old_cc
    stroke_ratio = new_stroke / params.stroke

    # 토크는 배기량에 비례하여 증가
    est_torque = round(params.torque * cc_ratio)
    # RPM은 스트로크에 반비례하여 감소 (피스톤 이동거리 증가)
    est_rpm = round(params.rpm / stroke_ratio)
    est_hp = calc_hp(est_torque, est_rpm)

    return {
        "old_stroke": params.stroke,
        "new_stroke": new_stroke,
        "stroke_delta": round(new_stroke - params.stroke, 2),
        "old_cc": old_cc,
        "new_cc": new_cc,
        "cc_delta": new_cc - old_cc,
        "old_torque": params.torque,
        "est_torque": est_torque,
        "torque_delta": est_torque - params.torque,
        "old_rpm": params.rpm,
        "est_rpm": est_rpm,
        "rpm_delta": est_rpm - params.rpm,
        "old_hp": params.hp,
        "est_hp": est_hp,
        "hp_delta": est_hp - params.hp,
        "note": "스트로크 증가 → 토크↑, RPM↓ (상충). HP 변화는 두 효과의 균형에 따라 결정됨.",
    }


# ── A3. 차량 성능 계산 ──────────────────────────────────────────

def calc_top_speed(hp: int, weight_kg: float, drag_coeff: float, area: float) -> float:
    """위키 공식 간소화: 최고속도 추정 (km/h).

    power_watts = HP * 745.7
    v_cubed = power_watts / (Cd * 0.5 * 1.225 * area * 0.0929)
    top_speed = v_cubed^(1/3) * 3.6  (m/s → km/h)
    """
    if hp <= 0 or drag_coeff <= 0 or area <= 0:
        return 0.0

    power_w = hp * 745.7
    # area는 게임 내부 단위 (sq ft → sq m 변환: * 0.0929)
    denominator = drag_coeff * 0.5 * 1.225 * area * 0.0929
    if denominator <= 0:
        return 0.0

    v_cubed = power_w / denominator
    v_ms = v_cubed ** (1.0 / 3.0)
    return round(v_ms * 3.6, 1)


def calc_acceleration(hp: int, torque: int, weight_kg: float,
                      drag_coeff: float, lo_ratio: float, gears: int) -> float:
    """0-100kph 가속 시간 추정 (초).

    간소화된 공식:
    effective_force = torque * lo_ratio * (gears^0.15) / weight_kg
    time_100 ≈ 28 / effective_force  (경험적 상수)
    """
    if weight_kg <= 0 or lo_ratio <= 0 or torque <= 0:
        return 0.0

    gear_factor = max(gears, 1) ** 0.15
    effective_force = (torque * lo_ratio * gear_factor) / weight_kg

    if effective_force <= 0:
        return 0.0

    return round(28.0 / effective_force, 1)


# ── A4. 개선(Modification) 비용 추정 ────────────────────────────

def estimate_modification_cost(
    vehicle_design_cost: int,
    engine_change: bool = False,
    gearbox_change: bool = False,
    chassis_change: bool = False,
) -> dict:
    """위키 규칙에 따른 New Generation/Trim 개선 비용 추정.

    | 변경 내용               | 비율       |
    |------------------------|-----------|
    | 기본 (변경 없음)         | 15%       |
    | 기어박스만 변경           | 20%       |
    | 엔진만 변경 (기어박스 5%  | 25%       |
    |   자동 포함)             |           |
    | 엔진+기어박스 변경        | 25%       |
    | 샤시 변경               | 100%      |
    """
    if chassis_change:
        return {
            "base_percent": 100,
            "component_percents": {"chassis": 100},
            "total_percent": 100,
            "estimated_cost": vehicle_design_cost,
            "cost_breakdown_text": (
                "샤시 변경 시 100% 비용 (사실상 신규 설계와 동일).\n"
                f"예상 비용: ${vehicle_design_cost:,}"
            ),
        }

    base_percent = 15
    component_percents = {"base_new_generation": 15}

    if engine_change and gearbox_change:
        component_percents["engine+gearbox"] = 10
        total = base_percent + 10
    elif engine_change:
        # 엔진 변경 시 기어박스 5%도 자동 포함
        component_percents["engine"] = 5
        component_percents["gearbox_auto"] = 5
        total = base_percent + 10
    elif gearbox_change:
        component_percents["gearbox"] = 5
        total = base_percent + 5
    else:
        total = base_percent

    estimated_cost = round(vehicle_design_cost * total / 100)

    lines = [f"기본 New Generation: {base_percent}%"]
    if engine_change and gearbox_change:
        lines.append("엔진+기어박스 변경: +10%")
    elif engine_change:
        lines.append("엔진 변경: +5% (기어박스 자동 +5% 포함)")
    elif gearbox_change:
        lines.append("기어박스 변경: +5%")
    lines.append(f"합계: {total}% → 예상 비용: ${estimated_cost:,}")

    return {
        "base_percent": base_percent,
        "component_percents": component_percents,
        "total_percent": total,
        "estimated_cost": estimated_cost,
        "cost_breakdown_text": "\n".join(lines),
    }


# ── A5. 노후화(Staleness) 페널티 계산 ──────────────────────────

def _component_staleness(age: int) -> float:
    """컴포넌트(엔진/샤시/기어박스) 노후화 계수.

    age > 12 → (age-12)*0.05
    age > 15 → 추가로 (age-15)*0.25
    """
    penalty = 0.0
    if age > 12:
        penalty += (age - 12) * 0.05
    if age > 15:
        penalty += (age - 15) * 0.25
    return penalty


def _vehicle_staleness(age: int) -> float:
    """차량 노후화 계수: ((age+4)/10)^1.6 (age+4 > 9일 때)."""
    effective = age + 4
    if effective <= 9:
        return 0.0
    return (effective / 10.0) ** 1.6


def calc_staleness(current_year: int, car_year: int,
                   engine_year: int, chassis_year: int, gearbox_year: int) -> dict:
    """노후화 종합 분석.

    Returns:
        collective_age: 합산 노후화 계수
        buyer_divisor: collective_age > 1 시 ^1.2
        percent_retained: 구매자 레이팅 유지율 (%)
        component_details: 컴포넌트별 상세
        urgency: none/low/medium/high/critical
    """
    car_age = current_year - car_year
    engine_age = current_year - engine_year
    chassis_age = current_year - chassis_year
    gearbox_age = current_year - gearbox_year

    car_penalty = _vehicle_staleness(car_age)
    engine_penalty = _component_staleness(engine_age)
    chassis_penalty = _component_staleness(chassis_age)
    gearbox_penalty = _component_staleness(gearbox_age)

    collective_age = 1.0 + car_penalty + engine_penalty + chassis_penalty + gearbox_penalty

    if collective_age > 1.0:
        buyer_divisor = collective_age ** 1.2
    else:
        buyer_divisor = 1.0

    percent_retained = round(100.0 / buyer_divisor, 1) if buyer_divisor > 0 else 0.0

    # Urgency 판정
    if buyer_divisor >= 3.0:
        urgency = "critical"
    elif buyer_divisor >= 2.0:
        urgency = "high"
    elif buyer_divisor >= 1.5:
        urgency = "medium"
    elif buyer_divisor > 1.0:
        urgency = "low"
    else:
        urgency = "none"

    return {
        "collective_age": round(collective_age, 3),
        "buyer_divisor": round(buyer_divisor, 3),
        "percent_retained": percent_retained,
        "component_details": {
            "vehicle": {"age": car_age, "penalty": round(car_penalty, 3),
                        "note": f"차량 나이 {car_age}년" + (" (5년 이하: 안전)" if car_age <= 5 else "")},
            "engine": {"age": engine_age, "penalty": round(engine_penalty, 3),
                       "note": f"엔진 나이 {engine_age}년" + (" (12년 이하: 안전)" if engine_age <= 12 else "")},
            "chassis": {"age": chassis_age, "penalty": round(chassis_penalty, 3),
                        "note": f"샤시 나이 {chassis_age}년" + (" (12년 이하: 안전)" if chassis_age <= 12 else "")},
            "gearbox": {"age": gearbox_age, "penalty": round(gearbox_penalty, 3),
                        "note": f"기어박스 나이 {gearbox_age}년" + (" (12년 이하: 안전)" if gearbox_age <= 12 else "")},
        },
        "urgency": urgency,
    }


# ── A6. 레이팅 변화 비교 ────────────────────────────────────────

def compare_ratings(static_ratings: dict, current_ratings: dict) -> dict:
    """Static(설계 시점) vs Current(현재) 레이팅 비교.

    음수 delta = 노후화에 의한 하락.
    """
    deltas = {}
    for key in static_ratings:
        if key in current_ratings:
            s = static_ratings[key]
            c = current_ratings[key]
            delta = round(c - s, 2)
            deltas[key] = {
                "static": s,
                "current": c,
                "delta": delta,
                "status": "OK" if delta >= 0 else "degraded",
            }
    return deltas


# ── A7. 기어박스 토크 호환성 검사 ────────────────────────────────

def check_torque_compatibility(engine_torque: int, gearbox_max_torque: int) -> dict:
    """엔진 토크 > 기어박스 최대 토크 시 품질/신뢰성 레이팅 페널티 경고."""
    if gearbox_max_torque <= 0:
        return {
            "compatible": True,
            "engine_torque": engine_torque,
            "gearbox_max_torque": gearbox_max_torque,
            "overflow_percent": 0,
            "warning": "기어박스 최대 토크 데이터 없음 (0). 호환성 판단 불가.",
        }

    overflow = engine_torque - gearbox_max_torque
    overflow_pct = round(overflow / gearbox_max_torque * 100, 1) if gearbox_max_torque > 0 else 0

    if overflow > 0:
        return {
            "compatible": False,
            "engine_torque": engine_torque,
            "gearbox_max_torque": gearbox_max_torque,
            "overflow_nm": overflow,
            "overflow_percent": overflow_pct,
            "warning": (
                f"엔진 토크({engine_torque}Nm)가 기어박스 최대 토크({gearbox_max_torque}Nm)를 "
                f"{overflow_pct}% 초과합니다. 품질/신뢰성 레이팅에 페널티가 적용됩니다."
            ),
        }
    else:
        headroom = -overflow
        headroom_pct = round(headroom / gearbox_max_torque * 100, 1)
        return {
            "compatible": True,
            "engine_torque": engine_torque,
            "gearbox_max_torque": gearbox_max_torque,
            "headroom_nm": headroom,
            "headroom_percent": headroom_pct,
            "warning": None,
        }


# ── A8. 종합 설계 리포트 포맷터 ─────────────────────────────────

def format_design_report(
    vehicle: VehicleParams | None = None,
    staleness: dict | None = None,
    mod_costs: dict | None = None,
    torque_check: dict | None = None,
    rating_deltas: dict | None = None,
    bore_sim: dict | None = None,
    stroke_sim: dict | None = None,
) -> str:
    """Python 계산 결과를 LLM 프롬프트용 구조화 텍스트로 포맷."""
    sections = []

    if vehicle:
        sections.append(
            f"## 차량 정보\n"
            f"- 모델: {vehicle.name} {vehicle.trim}\n"
            f"- 유형: {vehicle.car_type}\n"
            f"- 설계연도: {vehicle.year_built}\n"
            f"- HP: {vehicle.spec_hp}, 토크: {vehicle.spec_torque}Nm, RPM: {vehicle.spec_rpm}\n"
            f"- 중량: {vehicle.spec_weight}kg, 최고속도: {vehicle.spec_top_speed}km/h"
        )

    if staleness:
        urgency_kr = {
            "none": "안전",
            "low": "경미",
            "medium": "주의",
            "high": "위험",
            "critical": "심각",
        }
        sections.append(
            f"## 노후화 분석\n"
            f"- 종합 노후화 계수: {staleness['collective_age']}\n"
            f"- 구매자 평가 제수: {staleness['buyer_divisor']}\n"
            f"- 구매자 레이팅 유지율: {staleness['percent_retained']}%\n"
            f"- 긴급도: {urgency_kr.get(staleness['urgency'], staleness['urgency'])}"
        )
        for comp, detail in staleness.get("component_details", {}).items():
            sections.append(f"  - {comp}: {detail['note']} (페널티: {detail['penalty']})")

    if mod_costs:
        sections.append(
            f"## 개선 비용 추정\n{mod_costs['cost_breakdown_text']}"
        )

    if torque_check:
        if torque_check.get("warning"):
            sections.append(f"## 토크 호환성\n- {torque_check['warning']}")
        elif torque_check.get("compatible"):
            sections.append(
                f"## 토크 호환성\n"
                f"- 호환: 엔진 {torque_check['engine_torque']}Nm / "
                f"기어박스 최대 {torque_check['gearbox_max_torque']}Nm "
                f"(여유 {torque_check.get('headroom_percent', 0)}%)"
            )

    if rating_deltas:
        lines = ["## 레이팅 변화 (Static → Current)"]
        for key, info in rating_deltas.items():
            arrow = "→" if info["delta"] == 0 else ("↓" if info["delta"] < 0 else "↑")
            lines.append(f"  - {key}: {info['static']} → {info['current']} ({info['delta']:+.1f} {arrow})")
        sections.append("\n".join(lines))

    if bore_sim:
        if "error" in bore_sim:
            sections.append(f"## 보어 변경 시뮬레이션\n- {bore_sim['error']}")
        else:
            sections.append(
                f"## 보어 변경 시뮬레이션\n"
                f"- 보어: {bore_sim['old_bore']}mm → {bore_sim['new_bore']}mm ({bore_sim['bore_delta']:+.1f}mm)\n"
                f"- 배기량: {bore_sim['old_cc']}cc → {bore_sim['new_cc']}cc ({bore_sim['cc_delta']:+d}cc)\n"
                f"- 토크: {bore_sim['old_torque']}Nm → {bore_sim['est_torque']}Nm ({bore_sim['torque_delta']:+d}Nm)\n"
                f"- HP: {bore_sim['old_hp']}hp → {bore_sim['est_hp']}hp ({bore_sim['hp_delta']:+d}hp)\n"
                f"- {bore_sim['fuel_impact']}"
            )

    if stroke_sim:
        if "error" in stroke_sim:
            sections.append(f"## 스트로크 변경 시뮬레이션\n- {stroke_sim['error']}")
        else:
            sections.append(
                f"## 스트로크 변경 시뮬레이션\n"
                f"- 스트로크: {stroke_sim['old_stroke']}mm → {stroke_sim['new_stroke']}mm ({stroke_sim['stroke_delta']:+.1f}mm)\n"
                f"- 배기량: {stroke_sim['old_cc']}cc → {stroke_sim['new_cc']}cc ({stroke_sim['cc_delta']:+d}cc)\n"
                f"- 토크: {stroke_sim['old_torque']}Nm → {stroke_sim['est_torque']}Nm ({stroke_sim['torque_delta']:+d}Nm)\n"
                f"- RPM: {stroke_sim['old_rpm']} → {stroke_sim['est_rpm']} ({stroke_sim['rpm_delta']:+d})\n"
                f"- HP: {stroke_sim['old_hp']}hp → {stroke_sim['est_hp']}hp ({stroke_sim['hp_delta']:+d}hp)\n"
                f"- {stroke_sim['note']}"
            )

    return "\n\n".join(sections) if sections else "(계산 결과 없음)"
