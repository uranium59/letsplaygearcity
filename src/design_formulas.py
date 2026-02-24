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

# ── 엔진/물리 공식 상수 ──────────────────────────────────────────
DISPLACEMENT_CONSTANT = 0.7854      # π/4, 실린더 체적 공식
HP_CONVERSION_FACTOR = 5252         # HP = (torque × RPM) / 5252
HP_TO_WATTS = 745.7                 # 1 HP = 745.7W
AIR_DENSITY = 1.225                 # kg/m³ (해수면 표준)
SQFT_TO_SQM = 0.0929               # ft² → m² 변환
MS_TO_KMH = 3.6                    # m/s → km/h 변환
ACCEL_EMPIRICAL_K = 28.0           # 0-100kph 경험 상수
GEAR_EXPONENT = 0.15               # 기어 수 지수

# ── 노후화 (Staleness) ──────────────────────────────────────────
COMPONENT_SAFE_AGE = 12            # 컴포넌트 안전 연수
COMPONENT_STEEP_AGE = 15           # 가속 페널티 시작 연수
COMPONENT_PENALTY_RATE = 0.05      # 12~15년 연간 페널티
COMPONENT_STEEP_RATE = 0.25        # 15년 이후 연간 페널티
VEHICLE_AGE_OFFSET = 4             # 차량 유효 나이 보정
VEHICLE_STALENESS_TRIGGER = 9      # 페널티 시작 유효 나이
VEHICLE_STALENESS_DIVISOR = 10.0   # 정규화 제수
VEHICLE_STALENESS_EXPONENT = 1.6   # 차량 노후화 지수
BUYER_DIVISOR_EXPONENT = 1.2       # 구매자 평가 감소 지수
SAFE_VEHICLE_AGE = 5               # 차량 안전 연수 (리포트용)

# ── 노후화 긴급도 임계값 ─────────────────────────────────────────
URGENCY_CRITICAL = 3.0
URGENCY_HIGH = 2.0
URGENCY_MEDIUM = 1.5
URGENCY_LOW = 1.0

# ── 개선 비용 비율 (%) ──────────────────────────────────────────
MOD_BASE_PERCENT = 15              # 기본 New Generation
MOD_ENGINE_PERCENT = 5             # 엔진 변경 추가
MOD_GEARBOX_PERCENT = 5           # 기어박스 변경 추가
MOD_CHASSIS_PERCENT = 100          # 샤시 변경 (전체 재설계)


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
    """배기량 계산: CC = DISPLACEMENT_CONSTANT * (bore/10)^2 * (stroke/10) * cylinders"""
    bore_cm = bore_mm / 10.0
    stroke_cm = stroke_mm / 10.0
    cc = DISPLACEMENT_CONSTANT * (bore_cm ** 2) * stroke_cm * cylinders
    return round(cc)


def calc_hp(torque: int, rpm: int) -> int:
    """마력 계산: HP = (torque * rpm) / HP_CONVERSION_FACTOR"""
    if rpm <= 0:
        return 0
    return round((torque * rpm) / HP_CONVERSION_FACTOR)


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

    power_watts = HP * HP_TO_WATTS
    v_cubed = power_watts / (Cd * 0.5 * AIR_DENSITY * area * SQFT_TO_SQM)
    top_speed = v_cubed^(1/3) * MS_TO_KMH  (m/s → km/h)
    """
    if hp <= 0 or drag_coeff <= 0 or area <= 0:
        return 0.0

    power_w = hp * HP_TO_WATTS
    # area는 게임 내부 단위 (sq ft → sq m 변환)
    denominator = drag_coeff * 0.5 * AIR_DENSITY * area * SQFT_TO_SQM
    if denominator <= 0:
        return 0.0

    v_cubed = power_w / denominator
    v_ms = v_cubed ** (1.0 / 3.0)
    return round(v_ms * MS_TO_KMH, 1)


def calc_acceleration(hp: int, torque: int, weight_kg: float,
                      drag_coeff: float, lo_ratio: float, gears: int) -> float:
    """0-100kph 가속 시간 추정 (초).

    간소화된 공식:
    effective_force = torque * lo_ratio * (gears^GEAR_EXPONENT) / weight_kg
    time_100 ≈ ACCEL_EMPIRICAL_K / effective_force
    """
    if weight_kg <= 0 or lo_ratio <= 0 or torque <= 0:
        return 0.0

    gear_factor = max(gears, 1) ** GEAR_EXPONENT
    effective_force = (torque * lo_ratio * gear_factor) / weight_kg

    if effective_force <= 0:
        return 0.0

    return round(ACCEL_EMPIRICAL_K / effective_force, 1)


# ── A4. 개선(Modification) 비용 추정 ────────────────────────────

def estimate_modification_cost(
    vehicle_design_cost: int,
    engine_change: bool = False,
    gearbox_change: bool = False,
    chassis_change: bool = False,
) -> dict:
    """위키 규칙에 따른 New Generation/Trim 개선 비용 추정.

    | 변경 내용               | 비율                |
    |------------------------|---------------------|
    | 기본 (변경 없음)         | MOD_BASE_PERCENT    |
    | 기어박스만 변경           | +MOD_GEARBOX_PERCENT|
    | 엔진만 변경 (기어박스     | +ENGINE+GEARBOX     |
    |   자동 포함)             |                     |
    | 엔진+기어박스 변경        | +ENGINE+GEARBOX     |
    | 샤시 변경               | MOD_CHASSIS_PERCENT |
    """
    if chassis_change:
        return {
            "base_percent": MOD_CHASSIS_PERCENT,
            "component_percents": {"chassis": MOD_CHASSIS_PERCENT},
            "total_percent": MOD_CHASSIS_PERCENT,
            "estimated_cost": vehicle_design_cost,
            "cost_breakdown_text": (
                f"샤시 변경 시 {MOD_CHASSIS_PERCENT}% 비용 (사실상 신규 설계와 동일).\n"
                f"예상 비용: ${vehicle_design_cost:,}"
            ),
        }

    base_percent = MOD_BASE_PERCENT
    component_percents = {"base_new_generation": MOD_BASE_PERCENT}

    if engine_change and gearbox_change:
        component_percents["engine+gearbox"] = MOD_ENGINE_PERCENT + MOD_GEARBOX_PERCENT
        total = base_percent + MOD_ENGINE_PERCENT + MOD_GEARBOX_PERCENT
    elif engine_change:
        # 엔진 변경 시 기어박스도 자동 포함
        component_percents["engine"] = MOD_ENGINE_PERCENT
        component_percents["gearbox_auto"] = MOD_GEARBOX_PERCENT
        total = base_percent + MOD_ENGINE_PERCENT + MOD_GEARBOX_PERCENT
    elif gearbox_change:
        component_percents["gearbox"] = MOD_GEARBOX_PERCENT
        total = base_percent + MOD_GEARBOX_PERCENT
    else:
        total = base_percent

    estimated_cost = round(vehicle_design_cost * total / 100)

    lines = [f"기본 New Generation: {base_percent}%"]
    if engine_change and gearbox_change:
        lines.append(f"엔진+기어박스 변경: +{MOD_ENGINE_PERCENT + MOD_GEARBOX_PERCENT}%")
    elif engine_change:
        lines.append(f"엔진 변경: +{MOD_ENGINE_PERCENT}% (기어박스 자동 +{MOD_GEARBOX_PERCENT}% 포함)")
    elif gearbox_change:
        lines.append(f"기어박스 변경: +{MOD_GEARBOX_PERCENT}%")
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

    age > COMPONENT_SAFE_AGE → (age-COMPONENT_SAFE_AGE)*COMPONENT_PENALTY_RATE
    age > COMPONENT_STEEP_AGE → 추가로 (age-COMPONENT_STEEP_AGE)*COMPONENT_STEEP_RATE
    """
    penalty = 0.0
    if age > COMPONENT_SAFE_AGE:
        penalty += (age - COMPONENT_SAFE_AGE) * COMPONENT_PENALTY_RATE
    if age > COMPONENT_STEEP_AGE:
        penalty += (age - COMPONENT_STEEP_AGE) * COMPONENT_STEEP_RATE
    return penalty


def _vehicle_staleness(age: int) -> float:
    """차량 노후화 계수: ((age+VEHICLE_AGE_OFFSET)/VEHICLE_STALENESS_DIVISOR)^VEHICLE_STALENESS_EXPONENT."""
    effective = age + VEHICLE_AGE_OFFSET
    if effective <= VEHICLE_STALENESS_TRIGGER:
        return 0.0
    return (effective / VEHICLE_STALENESS_DIVISOR) ** VEHICLE_STALENESS_EXPONENT


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
        buyer_divisor = collective_age ** BUYER_DIVISOR_EXPONENT
    else:
        buyer_divisor = 1.0

    percent_retained = round(100.0 / buyer_divisor, 1) if buyer_divisor > 0 else 0.0

    # Urgency 판정
    if buyer_divisor >= URGENCY_CRITICAL:
        urgency = "critical"
    elif buyer_divisor >= URGENCY_HIGH:
        urgency = "high"
    elif buyer_divisor >= URGENCY_MEDIUM:
        urgency = "medium"
    elif buyer_divisor > URGENCY_LOW:
        urgency = "low"
    else:
        urgency = "none"

    return {
        "collective_age": round(collective_age, 3),
        "buyer_divisor": round(buyer_divisor, 3),
        "percent_retained": percent_retained,
        "component_details": {
            "vehicle": {"age": car_age, "penalty": round(car_penalty, 3),
                        "note": f"차량 나이 {car_age}년" + (f" ({SAFE_VEHICLE_AGE}년 이하: 안전)" if car_age <= SAFE_VEHICLE_AGE else "")},
            "engine": {"age": engine_age, "penalty": round(engine_penalty, 3),
                       "note": f"엔진 나이 {engine_age}년" + (f" ({COMPONENT_SAFE_AGE}년 이하: 안전)" if engine_age <= COMPONENT_SAFE_AGE else "")},
            "chassis": {"age": chassis_age, "penalty": round(chassis_penalty, 3),
                        "note": f"샤시 나이 {chassis_age}년" + (f" ({COMPONENT_SAFE_AGE}년 이하: 안전)" if chassis_age <= COMPONENT_SAFE_AGE else "")},
            "gearbox": {"age": gearbox_age, "penalty": round(gearbox_penalty, 3),
                        "note": f"기어박스 나이 {gearbox_age}년" + (f" ({COMPONENT_SAFE_AGE}년 이하: 안전)" if gearbox_age <= COMPONENT_SAFE_AGE else "")},
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


# ── A-2. 슬라이더 건강 진단 ──────────────────────────────────────

SLIDER_AVG_SAFE = 0.50
SLIDER_AVG_RISKY = 0.65
SLIDER_AVG_DANGER = 0.75
SLIDER_INDIVIDUAL_HIGH = 0.85
SLIDER_INDIVIDUAL_VERY_LOW = 0.05

# 부정적 교차 효과 목록: (slider_key, description)
_NEGATIVE_CROSS_EFFECTS = {
    # Engine
    "slider_rpm": "연비·신뢰성 악화",
    "slider_torq": "연비·신뢰성 악화",
    "slider_designperformance": "신뢰성 3×(1-slider) 패널티",
    # Chassis
    "ch_TECH_Tech": "내구성 감소",
    "FD_Weight": "성능 -2× 패널티 (높을 때)",
    "SUS_Comfort": "성능 저하",
    # Gearbox
    "g_Tech_Tech": "신뢰성 10×(1-slider) 패널티",
    "de_comfort": "신뢰성 5×(1-slider) 패널티",
    # Vehicle
    "Scroll_TestComf": "주행성 -2× 패널티",
    "Scroll_InteriorSafe": "설계요구 10× + 무게 1.25×",
    "Scroll_DesignDepend": "설계요구 15× + 완료시간 1.8×",
}

# 0이면 치명적인 슬라이더 목록: (slider_key, description)
_CRITICAL_IF_ZERO = {
    "Scroll_MatMatInterQual": "품질 15× 기여 상실",
    "Scroll_DesignDepend": "내구성 20× 기여 상실",
    "slider_designdependability": "엔진 신뢰성 6× 기여 상실",
    "Scroll_TestDemo": "인구통계 타겟팅 비활성화",
}


def analyze_slider_health(row: dict) -> list[str]:
    """차량 1대의 슬라이더 건강 상태를 진단, 경고 메시지 목록 반환.

    row: _fetch_vehicle_data()에서 가져온 DB 행 dict.
    """
    warnings: list[str] = []

    # ── 1. 컴포넌트별 평균 계산 + hyper 경고 ──
    _engine_keys = [
        "slider_displace", "slider_length", "slider_width", "slider_weight",
        "slider_rpm", "slider_torq", "slider_eco",
        "slider_materials", "slider_techniques", "slider_tech", "slider_compoenents",
        "slider_designperformance", "slider_designfueleco", "slider_designdependability",
    ]
    _chassis_keys = [
        "FD_Length", "FD_Width", "FD_Height", "FD_Weight",
        "FD_ENG_Width", "FD_ENG_Length",
        "SUS_Stability", "SUS_Comfort", "SUS_Performance",
        "SUS_Braking", "SUS_Durability",
        "ch_DE_Performance", "DE_Control", "DE_Str", "DE_Depend",
        "ch_TECH_Materials", "ch_TECH_Compoenents",
        "ch_TECH_Techniques", "ch_TECH_Tech",
    ]
    _gearbox_keys = [
        "g_de_performance", "de_fuel", "de_depend", "de_comfort",
        "Tech_Material", "Tech_Parts", "g_Tech_Techniques", "g_Tech_Tech",
    ]  # TorqueInputRatio는 0-1 범위가 아님(MaxTorqueInput) → 제외
    _vehicle_keys = [
        "Scroll_InteriorStyle", "Scroll_InteriorInno", "Scroll_InteriorLux",
        "Scroll_InteriorComf", "Scroll_InteriorSafe", "Scroll_InteriorTech",
        "Scroll_MatMatQual", "Scroll_MatMatInterQual",
        "Scroll_MatPaintQual", "Scroll_MatManuTech",
        "Scroll_DesignStyle", "Scroll_DesignLux", "Scroll_DesignSafety",
        "Scroll_DesignCargo", "Scroll_DesignDepend",
        "Scroll_TestDemo", "Scroll_TestPerform", "Scroll_TestFuel",
        "Scroll_TestComf", "Scroll_TestUtil", "Scroll_TestReli",
    ]

    for label, keys in [
        ("Engine", _engine_keys),
        ("Chassis", _chassis_keys),
        ("Gearbox", _gearbox_keys),
        ("Vehicle", _vehicle_keys),
    ]:
        vals = [float(row.get(k, 0) or 0) for k in keys]
        if not vals:
            continue
        avg = sum(vals) / len(vals)

        if avg >= SLIDER_AVG_DANGER:
            warnings.append(
                f"⚠ {label} 슬라이더 평균 {avg:.2f} — DANGER! "
                f"비용 폭발 구간 (hyper⁴ 페널티)"
            )
        elif avg >= SLIDER_AVG_RISKY:
            warnings.append(
                f"⚠ {label} 슬라이더 평균 {avg:.2f} — "
                f"비용 대비 레이팅 효율 낮음"
            )

    # ── 2. 개별 극단값 경고 ──
    for key, desc in _NEGATIVE_CROSS_EFFECTS.items():
        v = float(row.get(key, 0) or 0)
        if v >= SLIDER_INDIVIDUAL_HIGH:
            warnings.append(
                f"⚠ {key}={v:.2f} 매우 높음 — 부정적 교차효과: {desc}"
            )

    # ── 3. 치명적으로 낮은 슬라이더 ──
    for key, desc in _CRITICAL_IF_ZERO.items():
        v = float(row.get(key, 0) or 0)
        if v <= SLIDER_INDIVIDUAL_VERY_LOW:
            warnings.append(f"⚠ {key}={v:.2f} 거의 0 — {desc}")

    # ── 4. Design Pace 경고 ──
    for pace_key, label in [
        ("engine_design_pace", "Engine"),
        ("chassis_design_pace", "Chassis"),
        ("gearbox_design_pace", "Gearbox"),
        ("car_design_pace", "Vehicle"),
    ]:
        pace = float(row.get(pace_key, 0) or 0)
        if pace > 0.75:
            warnings.append(
                f"⚠ {label} Design Pace={pace:.2f} — "
                f"설계비 300%+, 긴급 상황 아니면 비추천"
            )

    return warnings


# ═══════════════════════════════════════════════════════════════════
# B. 위키 슬라이더 수식 전체 구현
# ═══════════════════════════════════════════════════════════════════
# 아래 함수들은 위키 pseudo-code를 Python으로 1:1 번역한 것이다.
# 모든 슬라이더는 0.0~1.0 범위, 레이팅은 0~100으로 clamp.
# sub_components dict는 *Components 테이블 컬럼명을 키로 사용.
# year exponent 계산은 _yexp 헬퍼로 통일.

# ── B0. 공용 헬퍼 ──────────────────────────────────────────────────

REF_YEAR = 1899  # 위키 수식의 기준년도

# 기본 글로벌 변수 (TurnEvents에서 동적으로 가져와야 하지만, 기본값 제공)
DEFAULT_INTEREST_RATE = 1.0
DEFAULT_CAR_PRICE_RATE = 1.0
DEFAULT_DESIGN_RANDOM_VAL = 1.0
DEFAULT_GLOBAL_LENGTHS = 95.0   # 1900년 기본값
DEFAULT_GLOBAL_WEIGHT = 230.0   # 1900년 기본값


def _yexp(base: float, year: int) -> float:
    """base^(year - 1899). 위키의 ex_1d01p_year99 등 패턴."""
    return base ** (year - REF_YEAR)


def _yexp_50r(year: int) -> float:
    """0.996^(2050-year). year > 2020이면 고정값."""
    if year > 2020:
        return 0.901037361
    return 0.996 ** (2050 - year)


def _adjusted_year(year: int) -> int:
    """AdjustedYear = year-1899, capped at 121 after 2020."""
    ay = year - REF_YEAR
    if ay > 121:
        ay = 121
    return ay


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _s(d: dict, key: str, default: float = 0.0) -> float:
    """Safe dict get with float conversion.

    Auto-tries slider_/ch_/g_ prefixes so DB column names
    (e.g. 'slider_torq', 'ch_DE_Performance', 'g_de_performance')
    match the short keys used in formulas ('torq', 'DE_Performance', 'de_performance').
    """
    for candidate in (key, f"slider_{key}", f"ch_{key}", f"g_{key}"):
        v = d.get(candidate)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return default


# ── B1. 엔진 수식 ─────────────────────────────────────────────────

def calc_engine_torque(sliders: dict, sub: dict, year: int, skill: int,
                       bore_mm: float = 70.0, stroke_mm: float = 80.0,
                       cylinders: int = 4) -> float:
    """위키 엔진 토크 공식 (lb-ft)."""
    s_torq = _s(sliders, "torq")
    s_eco = _s(sliders, "eco")
    s_dp = _s(sliders, "designperformance")
    s_dfe = _s(sliders, "designfueleco")
    s_tech_comp = _s(sliders, "compoenents")
    s_tech_mat = _s(sliders, "materials")
    s_tech_tech = _s(sliders, "tech")
    s_tech_tec = _s(sliders, "techniques")

    # Sub-component values with defaults
    lay_len = _s(sub, "Layout_Length", 1.0)
    lay_wid = _s(sub, "Layout_Width", 1.0)
    lay_pwr = _s(sub, "Layout_PowerRatings", 1.0)
    cyl_pwr = _s(sub, "Cylinders_PowerRating", 1.0)
    fuel_pwr = _s(sub, "FuelType_PowerRating", 1.0)
    indu_pwr = _s(sub, "Induction_PowerRating", 0.1)
    valve_pwr = _s(sub, "Valve_PowerRating", 1.0)
    cyl_count = _s(sub, "Cylinders_CylinderCount", cylinders)

    e01 = _yexp(1.01, year)
    e005 = _yexp(1.005, year)
    e004 = _yexp(1.004, year)
    e0024 = _yexp(1.0024, year)

    torque = 10.0 + (skill / 20.0)
    torque += (
        (25.0 * ((s_torq - 0.4) * 1.5) * e01) +
        (4.0 * (lay_len + lay_wid) * e005) -
        (14.0 * (s_eco + s_dfe) * e004) +
        (lay_pwr * 5.0 + cyl_pwr * 13.0 + fuel_pwr * 24.0 + 100.0 * indu_pwr +
         (5.0 * e004 * s_dp) +
         8.0 * (s_tech_comp + s_tech_mat + s_tech_tech + s_tech_tec)) * e0024
    )

    disp_factor = (cyl_count * stroke_mm * 0.93 * bore_mm * 0.9) * 0.000027 + 5.0
    torque = torque * disp_factor

    if year < 2050:
        torque = torque * _yexp_50r(year)

    torque = torque * valve_pwr
    return max(torque, 0.0)


def calc_engine_rpm(sliders: dict, sub: dict, year: int, skill: int) -> float:
    """위키 엔진 RPM 공식."""
    s_rpm = _s(sliders, "rpm")
    s_dp = _s(sliders, "designperformance")
    s_dfe = _s(sliders, "designfueleco")
    s_eco = _s(sliders, "eco")
    s_weight = _s(sliders, "weight")
    s_tech_comp = _s(sliders, "compoenents")
    s_tech_mat = _s(sliders, "materials")
    s_tech_tec = _s(sliders, "techniques")

    fuel_rpm = _s(sub, "FuelType_RPM", 1.0)
    valve_rpm = _s(sub, "Valve_RPM", 1.0)
    indu_pwr = _s(sub, "Induction_PowerRating", 0.1)
    stroke_mm = _s(sub, "stroke_mm", 80.0)

    ay = _adjusted_year(year)
    tmp_ay = ay
    if tmp_ay > 80:
        tmp_ay = 80 + ((ay - 80) / 5.0)

    e01 = _yexp(1.01, year)
    e005 = _yexp(1.005, year)
    e0105 = _yexp(1.0105, year)

    rpm = (
        (tmp_ay ** 4) * 0.00000420875 -
        (19.0 * (tmp_ay ** 3)) * 0.00016835 +
        (427.0 * (tmp_ay ** 2)) * 0.00126 +
        (1315.0 * tmp_ay) * 0.01515 + 620.0
    )
    rpm += 265.0 * e01 * s_dp
    rpm += 465.0 * e0105 * (s_rpm * 5.5)
    rpm -= 10.0 * e01 * indu_pwr
    rpm += 55.0 * e005 * (1.0 - s_weight)
    rpm -= 30.0 * e005 * (s_dfe + s_eco)
    rpm += 25.0 * e01 * s_tech_comp
    rpm += 25.0 * e01 * s_tech_mat
    rpm += 25.0 * e01 * s_tech_tec

    rpm = rpm * fuel_rpm
    rpm = rpm * valve_rpm

    # Stroke penalty
    if stroke_mm > 0:
        rpm = rpm - ((rpm / 1.5) * (stroke_mm / 221.136364))

    return max(rpm, 25.0)


def calc_engine_fuel_consumption(sliders: dict, sub: dict, year: int,
                                 skill: int, displacement_cc: int) -> float:
    """위키 엔진 연비 공식 (MPG)."""
    s_eco = _s(sliders, "eco")
    s_dfe = _s(sliders, "designfueleco")
    s_torq = _s(sliders, "torq")
    s_rpm = _s(sliders, "rpm")
    s_dp = _s(sliders, "designperformance")
    s_displace = _s(sliders, "displace")
    s_tech_tec = _s(sliders, "techniques")

    fuel_fuel = _s(sub, "FuelType_FuelRating", 5.0)
    cyl_fuel = _s(sub, "Cylinders_FuelRating", 1.0)
    lay_fuel = _s(sub, "Layout_FuelRatings", 1.0)
    indu_fuel = _s(sub, "Induction_FuelRating", 1.0)
    valve_fuel = _s(sub, "Valve_FuelRating", 1.0)

    e0023 = _yexp(1.0023, year)
    e0051 = _yexp(1.0051, year)

    mpg = 95.0 + (55.0 * e0023 * (s_eco + 0.1)) + (40.0 * e0023 * s_dfe)
    mpg += 12.0 * e0023 * fuel_fuel
    mpg += 7.0 * e0023 * s_tech_tec
    mpg -= 15.0 * e0051 * (s_torq + s_rpm + s_dp)
    mpg -= 20.0 * s_displace
    mpg += 10.0 * valve_fuel

    mpg = (mpg + 6.0 * cyl_fuel + 6.0 * lay_fuel) * indu_fuel + (skill / 50.0)

    divisor = 1.5 + displacement_cc / 350.0
    if divisor > 0:
        mpg = mpg / divisor

    mpg += 5.0

    if mpg < 1:
        mpg = 1.0

    # Fuel type cap for low fuel ratings
    if fuel_fuel < 5 and mpg > 30:
        if fuel_fuel > 1.5 and mpg > (30 + fuel_fuel * 2.0):
            mpg = mpg + (-mpg ** 0.85) + 18.0 + fuel_fuel * 2.0
        else:
            mpg = mpg + (-mpg ** 0.85) + 18.0

    return max(mpg, 1.0)


def calc_engine_power_rating(torque: float, year: int, cylinders: int) -> float:
    """위키 엔진 Power Rating."""
    if cylinders <= 0:
        return 0.0
    e007 = _yexp(1.007, year)
    pr = torque / ((100.0 * e007) * cylinders / 2.2)
    pr *= 50.0
    if pr > 50.0:
        pr = 50.0
    pr += 50.0 * (torque / 2000.0)
    return _clamp(pr)


def calc_engine_fuel_eco_rating(mpg: float) -> float:
    """위키 엔진 Fuel Economy Rating."""
    return _clamp((mpg / 120.0) * 100.0)


def calc_engine_reliability_rating(sliders: dict, sub: dict, year: int,
                                   skill: int, rpm: float,
                                   stroke_mm: float = 80.0) -> float:
    """위키 엔진 Reliability Rating."""
    s_dd = _s(sliders, "designdependability")
    s_dp = _s(sliders, "designperformance")
    s_torq = _s(sliders, "torq")
    s_rpm = _s(sliders, "rpm")
    s_tech_comp = _s(sliders, "compoenents")
    s_tech_mat = _s(sliders, "materials")
    s_tech_tech = _s(sliders, "tech")
    s_tech_tec = _s(sliders, "techniques")

    cyl_rel = _s(sub, "Cylinders_ReliabilityRating", 1.0)
    fuel_rel = _s(sub, "FuelType_ReliabilityRating", 1.0)
    indu_rel = _s(sub, "Induction_ReliabilityRating", 0.5)
    lay_rel = _s(sub, "Layout_Reliability", 1.0)
    valve_rel = _s(sub, "Valve_ReliabilityRating", 1.0)

    r = (6.0 * s_dd +
         3.0 * (1.0 - s_dp) +
         5.0 * (1.0 - (rpm / 10000.0)) +
         2.0 * (1.0 - s_torq) +
         3.0 * (1.0 - s_rpm) +
         3.0 * s_tech_comp +
         2.0 * s_tech_mat +
         (1.0 - s_tech_tech) +
         s_tech_tec)

    r += (1.0 * cyl_rel + 1.0 * fuel_rel +
          1.0 * (1.0 - indu_rel) + 1.0 * lay_rel +
          2.0 * valve_rel)

    r += 8.0 * (1.0 - (stroke_mm / 150.0))
    r = r / 4.5
    r = r * 10.0
    r += skill / 10.0
    return _clamp(r)


def calc_engine_smoothness_rating(sliders: dict, sub: dict, cylinders: int,
                                  skill: int) -> float:
    """위키 엔진 Smoothness Rating."""
    s_tech_comp = _s(sliders, "compoenents")
    s_tech_tech = _s(sliders, "tech")
    s_tech_tec = _s(sliders, "techniques")

    cyl_smooth = _s(sub, "Cylinders_SmoothnessRating", 1.0)
    fuel_smooth = _s(sub, "FuelType_SmoothnessRating", 1.0)
    lay_smooth = _s(sub, "Layout_Smoothness", 1.0)
    valve_smooth = _s(sub, "Valve_SmoothnessRating", 1.0)

    # Parabola peaks at 8 cylinders
    r = -(1.0 / 10.0) * ((cylinders - 8) * (cylinders - 8)) + 5.0
    r += (cyl_smooth * 2.0 + fuel_smooth * 2.0 + lay_smooth * 2.0 +
          s_tech_comp * 3.0 + s_tech_tech * 2.0 + s_tech_tec * 3.0 +
          valve_smooth * 2.0 + skill / 25.0)
    r *= 4.0
    return _clamp(r, 1.0, 100.0)


def calc_engine_unit_cost(sliders: dict, sub: dict, year: int,
                          skill: int, cylinders: int,
                          interest_rate: float = DEFAULT_INTEREST_RATE,
                          car_price_rate: float = DEFAULT_CAR_PRICE_RATE) -> float:
    """위키 엔진 Unit Cost 공식."""
    sl = _s(sliders, "length")
    sw = _s(sliders, "width")
    s_rpm = _s(sliders, "rpm")
    s_torq = _s(sliders, "torq")
    s_eco = _s(sliders, "eco")
    s_dp = _s(sliders, "designperformance")
    s_dfe = _s(sliders, "designfueleco")
    s_dd = _s(sliders, "designdependability")
    s_displace = _s(sliders, "displace")
    s_weight = _s(sliders, "weight")
    s_tech_mat = _s(sliders, "materials")
    s_tech_tec = _s(sliders, "techniques")
    s_tech_comp = _s(sliders, "compoenents")
    s_tech_tech = _s(sliders, "tech")

    cyl_uc = _s(sub, "Cylinders_UnitCosts", 1.0)
    lay_uc = _s(sub, "Layout_UnitCosts", 1.0)
    valve_uc = _s(sub, "Valve_UnitCosts", 1.0)
    indu_uc = _s(sub, "Induction_UnitCosts", 1.0)
    fuel_uc = _s(sub, "FuelType_UnitCosts", 1.0)
    cyl_count = _s(sub, "Cylinders_CylinderCount", cylinders)

    e01 = _yexp(1.01, year)
    e004 = _yexp(1.004, year)
    e008 = _yexp(1.008, year)
    e003 = _yexp(1.003, year)
    e0035 = _yexp(1.0035, year)
    e006 = _yexp(1.006, year)
    e005 = _yexp(1.005, year)
    e04 = _yexp(1.04, year)

    uc = (
        70.0 * e01 * (((1.0 - sl) + (1.0 - sw)) / 2.0) +
        220.0 * e004 * (((0.25 + s_rpm ** 2 + s_torq ** 2) / 2.0) -
                        (0.5 - s_eco ** 2)) +
        60.0 * e01 * (s_rpm ** 2 + s_torq ** 2) +
        220.0 * e008 * (0.1 + s_tech_mat ** 2 + s_tech_tec ** 2 + s_tech_comp ** 2) +
        170.0 * e008 * (s_tech_tech ** 2) +
        50.0 * e0035 * (s_dd ** 2) +
        180.0 * e0035 * (s_dp ** 2) +
        (260.0 * e006 * (2.168 * s_displace ** 1.5 - 4.44 * s_displace ** 3 +
                         2.646 * s_displace ** 4.5 + 3.126 * s_displace ** 6) +
         (70.0 * e005 * (cyl_count / 6.0) +
          0.75 + s_displace ** 1.5 - s_weight ** 2) +
         10.0 * (s_dfe ** 2) - 50.0) * e003
    )

    # Sub-component costs (power terms)
    uc += (160.0 * cyl_uc) ** e003
    uc += (120.0 * lay_uc) ** e004
    uc += (140.0 * valve_uc) ** e004
    uc += (435.0 * indu_uc) ** e004
    uc += (120.0 * fuel_uc) ** e004

    uc = uc * (0.125 + 0.12 * cyl_count)
    uc = uc * (interest_rate / 2.0) + 50.0
    uc = uc * car_price_rate

    # Hyper-slider penalty
    hyper = ((s_displace * 2.0 + (1.0 - sl) + (1.0 - sw) + (1.0 - s_weight) +
              s_rpm + s_torq + s_eco +
              s_dp + s_dfe + s_dd +
              s_tech_mat + s_tech_comp + s_tech_tec + s_tech_tech) / 13.0)
    hyper_cost = 475.0 * e04 * (hyper ** 4)

    uc = uc + hyper_cost - ((uc / 10.0) * (skill / 100.0))
    return max(uc, 0.0)


def calc_engine_design_cost(sliders: dict, sub: dict, year: int,
                            cylinders: int,
                            interest_rate: float = DEFAULT_INTEREST_RATE) -> float:
    """위키 엔진 Design Cost 공식."""
    s_displace = _s(sliders, "displace")
    s_weight = _s(sliders, "weight")
    sl = _s(sliders, "length")
    sw = _s(sliders, "width")
    s_rpm = _s(sliders, "rpm")
    s_torq = _s(sliders, "torq")
    s_eco = _s(sliders, "eco")
    s_dp = _s(sliders, "designperformance")
    s_dfe = _s(sliders, "designfueleco")
    s_dd = _s(sliders, "designdependability")
    s_tech_mat = _s(sliders, "materials")
    s_tech_tec = _s(sliders, "techniques")
    s_tech_comp = _s(sliders, "compoenents")
    s_tech_tech = _s(sliders, "tech")
    s_pace = _s(sliders, "design_pace", _s(sliders, "engine_design_pace",
               _s(sliders, "DesignPace", 0.35)))

    cyl_dc = _s(sub, "Cylinders_DesignCosts", 1.0)
    lay_dc = _s(sub, "Layout_DesignCosts", 1.0)
    indu_dc = _s(sub, "Induction_DesignCosts", 1.0)
    valve_uc = _s(sub, "Valve_UnitCosts", 1.0)
    fuel_dc = _s(sub, "FuelType_DesignCosts", 1.0)
    cyl_count = _s(sub, "Cylinders_CylinderCount", cylinders)

    e025 = _yexp(1.025, year)
    e033 = _yexp(1.033, year)
    e05 = _yexp(1.05, year)
    e039 = _yexp(1.039, year)
    e03 = _yexp(1.03, year)
    e038 = _yexp(1.038, year)
    e035 = _yexp(1.035, year)
    e01 = _yexp(1.01, year)
    e04 = _yexp(1.04, year)
    e003 = _yexp(1.003, year)

    # Tech hyper for design cost
    hyper = ((s_displace * 2.0 + (1.0 - sl) + (1.0 - sw) + (1.0 - s_weight) +
              s_rpm + s_torq + s_eco +
              s_dp + s_dfe + s_dd +
              s_tech_mat + s_tech_comp + s_tech_tec + s_tech_tech) / 13.0)
    hyper_cost = 475.0 * e04 * (hyper ** 4)

    # Focus combination exponent
    focus_exp = (0.1 + s_dp ** 2 + s_dd ** 2 + s_dfe ** 2)
    tech_base = (0.15 + s_tech_mat ** 2 + s_tech_tec ** 2 + s_tech_comp ** 2)

    dc = (
        18000.0 * (0.05 + s_displace ** 1.5) * e025 +
        4000.0 * (1.0 - s_weight ** 2) * e033 +
        5000.0 * (tech_base ** focus_exp) * e033 +
        2500.0 * ((1.01 - s_weight) ** 2) * e033 -
        2500.0 * e033 * ((1.0 - sw) + (1.0 - sl)) +
        12000.0 * (0.2 + s_dp ** 2 + s_dfe ** 2) * e05 +
        1500.0 * (3.5 + s_dd ** 2) * e039
    ) * e03

    dc += 4000.0 * (s_eco ** 2 + s_rpm ** 2 + s_torq ** 2) * e038
    dc += 3000.0 * (s_tech_tech ** 2) * e035
    dc += hyper_cost * (500.0 * e035)

    dc += (95.0 * cyl_dc) ** e01
    dc += (115.0 * lay_dc) ** e01
    dc += (195.0 * indu_dc) ** e01
    dc += (90.0 * valve_uc) ** e01
    dc += (90.0 * fuel_dc) ** e01 * interest_rate

    dc *= e003

    # Cylinder count scaling by era
    if 1910 < year < 1930:
        dc *= cyl_count * (1.0 - 0.0375 * (year - 1910))
    elif 1930 < year < 1950:
        dc *= cyl_count * (0.25 - 0.005 * (year - 1930))
    elif year > 1950:
        dc *= cyl_count * 0.15

    dc = (dc * 0.85) + (dc * 0.15 * cyl_dc)

    # Design pace
    dc = (dc / 5.0) + (dc * (s_pace ** 2 * 4.5))
    return max(dc, 0.0)


def calc_engine_finish_time(sliders: dict, sub: dict, year: int,
                            factory_val: float = 50.0) -> float:
    """위키 엔진 Finish Time (turns/months)."""
    s_displace = _s(sliders, "displace")
    s_weight = _s(sliders, "weight")
    s_rpm = _s(sliders, "rpm")
    s_torq = _s(sliders, "torq")
    s_eco = _s(sliders, "eco")
    s_dp = _s(sliders, "designperformance")
    s_dfe = _s(sliders, "designfueleco")
    s_dd = _s(sliders, "designdependability")
    s_pace = _s(sliders, "design_pace", _s(sliders, "engine_design_pace",
               _s(sliders, "DesignPace", 0.35)))

    cyl_ft = _s(sub, "Cylinders_FinishTime", 1.0)
    lay_ft = _s(sub, "Layout_FinishTime", 1.0)
    indu_ft = _s(sub, "Induction_FinishTime", 0.5)
    fuel_ft = _s(sub, "FuelType_FinishTime", 0.5)
    valve_ft = _s(sub, "Valve_FinishTime", 0.5)

    hyper = ((s_displace * 2.0 + (1.0 - _s(sliders, "length")) +
              (1.0 - _s(sliders, "width")) + (1.0 - s_weight) +
              s_rpm + s_torq + s_eco + s_dp + s_dfe + s_dd +
              _s(sliders, "materials") + _s(sliders, "compoenents") +
              _s(sliders, "techniques") + _s(sliders, "tech")) / 13.0)

    e004 = _yexp(1.004, year)
    e003 = _yexp(1.003, year)

    ft = (
        (0.55 * s_displace + (1.0 - s_weight) +
         0.45 * (s_rpm + s_torq + s_eco) +
         0.45 * (s_dd + s_dfe + s_dp)) * e004 +
        cyl_ft + lay_ft + 0.75 * indu_ft + 0.55 * fuel_ft + valve_ft +
        1.0 - (2.0 * (factory_val / 100.0)) +
        1.15 * e003 * hyper
    )

    ft += (year - 1850) / 50.0

    # Design pace adjustment
    eff_year = min(year, 2020)
    pace_denom = s_pace + 0.05
    if pace_denom <= 0:
        pace_denom = 0.05
    additional = ((eff_year - 1840) / 15.0) * ((0.5 / pace_denom) - 0.45)

    if s_pace < 0.5:
        ft += additional
    else:
        turns_off = (s_pace - 0.5) / 0.20
        ft += additional - turns_off

    return max(ft, 1.0)


def calc_engine_employees(sliders: dict, sub: dict, year: int) -> int:
    """위키 엔진 Engineers Required."""
    s_dd = _s(sliders, "designdependability")
    s_dfe = _s(sliders, "designfueleco")
    s_dp = _s(sliders, "designperformance")
    s_rpm = _s(sliders, "rpm")
    s_eco = _s(sliders, "eco")
    s_torq = _s(sliders, "torq")
    s_tech_tec = _s(sliders, "techniques")
    s_tech_tech = _s(sliders, "tech")
    s_displace = _s(sliders, "displace")
    s_weight = _s(sliders, "weight")
    sl = _s(sliders, "length")
    sw = _s(sliders, "width")
    s_pace = _s(sliders, "design_pace", _s(sliders, "engine_design_pace",
               _s(sliders, "DesignPace", 0.35)))

    cyl_dr = _s(sub, "Cylinders_DesignRequire", 1.0)
    fuel_dr = _s(sub, "FuelType_DesignRequirements", 1.0)
    valve_dr = _s(sub, "Valve_DesignRequirements", 1.0)
    indu_dr = _s(sub, "Induction_DesignRequirements", 1.0)
    lay_dr = _s(sub, "Layout_DesignRequirements", 1.0)

    dr = (5.0 * s_dd + 5.0 * s_dfe + 5.0 * s_dp +
          3.0 * s_rpm + 2.0 * s_eco + 2.0 * s_torq +
          2.0 * s_tech_tech + (1.0 - s_weight) +
          (s_displace + (1.0 - sl) + (1.0 - sw)) -
          2.0 * s_tech_tec)

    dr += cyl_dr + fuel_dr + valve_dr + 5.0 * indu_dr + 3.0 * lay_dr
    dr *= 2.7027

    ay = min(year - REF_YEAR, 121)
    eng = dr * (0.11833 * ay + 0.275)
    eng = eng / 5.0 + (eng / 1.2) * s_pace + 3.0
    return max(round(eng), 1)


def estimate_engine_full(sliders: dict, sub: dict, year: int, skill: int,
                         bore_mm: float = 70.0, stroke_mm: float = 80.0,
                         cylinders: int = 4) -> dict:
    """모든 엔진 수식을 실행, 전체 결과 dict 반환."""
    sub["stroke_mm"] = stroke_mm
    sub.setdefault("Cylinders_CylinderCount", cylinders)

    torque = calc_engine_torque(sliders, sub, year, skill, bore_mm, stroke_mm, cylinders)
    rpm = calc_engine_rpm(sliders, sub, year, skill)
    hp = calc_hp(round(torque), round(rpm))
    displacement = calc_displacement(bore_mm, stroke_mm, cylinders)
    mpg = calc_engine_fuel_consumption(sliders, sub, year, skill, displacement)

    power_r = calc_engine_power_rating(torque, year, cylinders)
    fuel_r = calc_engine_fuel_eco_rating(mpg)
    rel_r = calc_engine_reliability_rating(sliders, sub, year, skill, rpm, stroke_mm)
    smooth_r = calc_engine_smoothness_rating(sliders, sub, cylinders, skill)

    unit_cost = calc_engine_unit_cost(sliders, sub, year, skill, cylinders)
    design_cost = calc_engine_design_cost(sliders, sub, year, cylinders)
    finish_time = calc_engine_finish_time(sliders, sub, year)
    employees = calc_engine_employees(sliders, sub, year)

    return {
        "torque": round(torque, 1),
        "rpm": round(rpm),
        "hp": hp,
        "displacement_cc": displacement,
        "fuel_mpg": round(mpg, 1),
        "power_rating": round(power_r, 1),
        "fuel_eco_rating": round(fuel_r, 1),
        "reliability_rating": round(rel_r, 1),
        "smoothness_rating": round(smooth_r, 1),
        "unit_cost": round(unit_cost),
        "design_cost": round(design_cost),
        "finish_time": round(finish_time, 1),
        "employees": employees,
    }


# ── B2. 샤시 수식 ─────────────────────────────────────────────────

def calc_chassis_weight(sliders: dict, sub: dict, year: int,
                        global_weight: float = DEFAULT_GLOBAL_WEIGHT) -> float:
    """위키 샤시 중량 공식 (kg)."""
    s_w = _s(sliders, "FD_Weight")
    s_l = _s(sliders, "FD_Length")
    s_wd = _s(sliders, "FD_Width")
    s_h = _s(sliders, "FD_Height")
    s_tm = _s(sliders, "TECH_Materials")
    s_tt = _s(sliders, "TECH_Techniques")
    s_dp = _s(sliders, "DE_Performance")

    fr_wt = _s(sub, "Frame_Weight", 0.6)
    dr_wt = _s(sub, "Drive_Weight", 0.5)

    gw = global_weight

    w = 40.0 + (
        gw * (1.25 * s_w + 0.1) +
        gw * 0.5 * (6.0 * s_l + 0.1) +
        (gw / 15.0) * (3.3 * s_wd + 0.1) +
        (gw / 20.0) * (2.0 * s_h + 0.1) +
        (gw / 5.0) * (5.0 * fr_wt + 0.1) +
        (gw / 10.0) * (3.0 * dr_wt + 0.1) -
        (gw / 5.0) * s_tm -
        (gw / 8.0) * s_dp -
        (gw / 11.0) * s_tt
    )

    # Era weight divisor
    if year < 1981:
        e0_9962 = _yexp(0.9962, year)
        w /= (2.0 * e0_9962)
    else:
        w /= 1.469262941607760500229789005264

    return max(w, 10.0)


def calc_chassis_comfort_rating(sliders: dict, sub: dict, skill: int) -> float:
    """위키 샤시 Comfort Rating."""
    s_ctrl = _s(sliders, "DE_Control")
    s_w = _s(sliders, "FD_Weight")
    s_brk = _s(sliders, "SUS_Braking")
    s_comf = _s(sliders, "SUS_Comfort")
    s_stab = _s(sliders, "SUS_Stability")
    s_tc = _s(sliders, "TECH_Compoenents")
    s_tm = _s(sliders, "TECH_Materials")
    s_tt = _s(sliders, "TECH_Tech")
    s_tq = _s(sliders, "TECH_Techniques")

    dr_steer = _s(sub, "Drive_rideSteering", 0.5)
    fr_brk = _s(sub, "FrSus_Braking", 0.5)
    rr_brk = _s(sub, "RrSus_Braking", 0.5)
    fr_comf = _s(sub, "FrSus_Comfort", 0.5)
    rr_comf = _s(sub, "RrSus_Comfort", 0.5)
    fr_steer = _s(sub, "FrSus_Steering", 0.5)
    rr_steer = _s(sub, "RrSus_Steering", 0.5)

    r = (s_ctrl + dr_steer + s_w +
         (fr_brk + rr_brk + s_brk * 4.5) +
         (fr_comf + rr_comf + s_comf * 6.0) +
         (fr_steer + rr_steer + s_stab * 4.5) +
         ((s_tc + s_tm + s_tt + s_tq) / 2.0))

    r /= 2.6
    r *= 10.0
    r += 10.0 * (skill / 100.0)
    return _clamp(r)


def calc_chassis_performance_rating(sliders: dict, sub: dict, skill: int) -> float:
    """위키 샤시 Performance Rating."""
    s_brk = _s(sliders, "SUS_Braking")
    s_dp = _s(sliders, "DE_Performance")
    s_w = _s(sliders, "FD_Weight")
    s_perf = _s(sliders, "SUS_Performance")
    s_stab = _s(sliders, "SUS_Stability")
    s_l = _s(sliders, "FD_Length")
    s_wd = _s(sliders, "FD_Width")
    s_tc = _s(sliders, "TECH_Compoenents")
    s_tm = _s(sliders, "TECH_Materials")
    s_tt = _s(sliders, "TECH_Tech")
    s_tq = _s(sliders, "TECH_Techniques")

    fr_steer = _s(sub, "FrSus_Steering", 0.5)
    rr_steer = _s(sub, "RrSus_Steering", 0.5)
    fr_perf = _s(sub, "FrSus_Performance", 0.5)
    rr_perf = _s(sub, "RrSus_Performance", 0.5)
    fr_frame_perf = _s(sub, "Frame_Performance", 0.5)
    dr_perf = _s(sub, "Drive_carPerformance", 0.5)

    r = (s_brk * 2.0 + s_dp - s_w * 2.0 + s_perf * 4.0 +
         fr_steer + rr_steer +
         (s_tc + s_tm * 2.0 + s_tt + s_tq) / 2.0 +
         fr_perf + rr_perf + fr_frame_perf + dr_perf * 2.0 -
         (s_l + s_wd) + (1.0 - s_stab))

    r /= 2.0
    r *= 10.0
    r += 10.0 * (skill / 100.0)
    return _clamp(r)


def calc_chassis_strength_rating(sliders: dict, sub: dict, skill: int) -> float:
    """위키 샤시 Strength Rating."""
    s_w = _s(sliders, "FD_Weight")
    s_h = _s(sliders, "FD_Height")
    s_l = _s(sliders, "FD_Length")
    s_str = _s(sliders, "DE_Str")
    s_tc = _s(sliders, "TECH_Compoenents")
    s_tm = _s(sliders, "TECH_Materials")
    s_tt = _s(sliders, "TECH_Tech")
    s_tq = _s(sliders, "TECH_Techniques")
    s_dur = _s(sliders, "SUS_Durability")

    dr_wt = _s(sub, "Drive_Weight", 0.5)
    fr_wt = _s(sub, "Frame_Weight", 0.6)
    dr_dur = _s(sub, "Drive_Duriblity", 0.5)
    fr_dur = _s(sub, "Frame_Durability", 0.5)
    rr_dur = _s(sub, "RrSus_Durability", 0.5)
    fr_s_dur = _s(sub, "FrSus_Durability", 0.5)
    fr_str = _s(sub, "Frame_STR", 0.5)

    r = (((dr_wt + fr_wt) / 4.0) + s_w * 2.0 +
         ((dr_dur + fr_dur + rr_dur + fr_s_dur) / 6.0) +
         s_h * 5.0 + fr_str * 8.0 + s_str +
         ((s_tc * 2.0 + s_tm * 2.0 + s_tt * 2.0 + s_tq * 2.0) / 2.0) + s_l)

    r /= 2.6
    r *= 10.0
    r += 10.0 * (skill / 100.0)
    return _clamp(r)


def calc_chassis_dependability_rating(sliders: dict, sub: dict, skill: int) -> float:
    """위키 샤시 Durability/Dependability Rating."""
    s_dep = _s(sliders, "DE_Depend")
    s_dur = _s(sliders, "SUS_Durability")
    s_tc = _s(sliders, "TECH_Compoenents")
    s_tm = _s(sliders, "TECH_Materials")
    s_tt = _s(sliders, "TECH_Tech")
    s_tq = _s(sliders, "TECH_Techniques")

    dr_dur = _s(sub, "Drive_Duriblity", 0.5)
    fr_dur = _s(sub, "Frame_Durability", 0.5)
    fr_s_dur = _s(sub, "FrSus_Durability", 0.5)
    rr_dur = _s(sub, "RrSus_Durability", 0.5)

    r = (s_dep * 0.5 + dr_dur * 1.5 + fr_dur * 1.5 +
         (fr_s_dur + rr_dur) / 2.0 +
         s_dur * 2.5 +
         (s_tc + s_tm + s_tq - s_tt))

    r *= 10.0
    r += 10.0 * (skill / 100.0)
    return _clamp(r)


def calc_chassis_unit_cost(sliders: dict, sub: dict, year: int,
                           skill: int,
                           car_price_rate: float = DEFAULT_CAR_PRICE_RATE) -> float:
    """위키 샤시 Manufacturing Cost (unit cost)."""
    s_h = _s(sliders, "FD_Height")
    s_l = _s(sliders, "FD_Length")
    s_wd = _s(sliders, "FD_Width")
    s_w = _s(sliders, "FD_Weight")
    s_el = _s(sliders, "FD_ENG_Length")
    s_ew = _s(sliders, "FD_ENG_Width")
    s_brk = _s(sliders, "SUS_Braking")
    s_comf = _s(sliders, "SUS_Comfort")
    s_perf = _s(sliders, "SUS_Performance")
    s_dur = _s(sliders, "SUS_Durability")
    s_stab = _s(sliders, "SUS_Stability")
    s_tc = _s(sliders, "TECH_Compoenents")
    s_tm = _s(sliders, "TECH_Materials")
    s_tt = _s(sliders, "TECH_Tech")
    s_tq = _s(sliders, "TECH_Techniques")
    s_ctrl = _s(sliders, "DE_Control")
    s_dep = _s(sliders, "DE_Depend")
    s_dp = _s(sliders, "DE_Performance")
    s_str = _s(sliders, "DE_Str")

    dr_cost = _s(sub, "Drive_Cost", 1.0)
    fr_cost = _s(sub, "Frame_Cost", 1.0)
    fr_sus_cost = _s(sub, "FrSus_Cost", 1.0)
    rr_sus_cost = _s(sub, "RrSus_Cost", 1.0)

    e015 = _yexp(1.015, year)
    e02 = _yexp(1.02, year)
    e045 = _yexp(1.045, year)

    # Frame
    dim_sl = (s_h ** 2 + s_l ** 2 * 1.2 + s_wd ** 2 +
              (1.0 - s_w) ** 2 + s_el ** 2 * 0.8 + s_ew ** 2 * 0.8)
    c_frame = dim_sl * 25.0 * e015 * dr_cost * fr_cost * e015 * car_price_rate
    c_frame = 15.0 * e02 + c_frame + 1.0 + 0.04 * c_frame + 15.0 * e015 * dr_cost + 15.0 * e015 * fr_cost

    # Suspension
    sus_sl = (s_brk ** 2 * 0.75 + s_comf ** 2 * 1.25 +
              s_perf ** 2 * 1.2 + s_dur ** 2 * 1.35 + s_stab ** 2)
    c_sus = sus_sl * 20.0 * e02 * fr_sus_cost * rr_sus_cost * e015 * car_price_rate
    c_sus = 15.0 * e02 + c_sus + 1.0 + 0.04 * c_sus + 15.0 * e015 * fr_sus_cost + 15.0 * e015 * rr_sus_cost

    # Tech
    tech_sl = (s_tc ** 2 * 1.15 + s_tm ** 2 * 1.25 + s_tt ** 2 * 1.25 + s_tq ** 2 * 0.75)
    c_tech = tech_sl * 30.0 * e015 * car_price_rate
    c_tech = 15.0 * e015 + c_tech + 1.0 + 0.04 * c_tech

    # Hyper
    hyper = ((s_ctrl + s_dep + s_dp + s_str +
              s_l + s_wd + s_h + (1.0 - s_w) + s_ew + s_el +
              s_stab + s_comf + s_perf + s_brk + s_dur +
              s_tm + s_tc + s_tq + s_tt) / 19.0)
    c_hyper = 450.0 * e045 * (hyper ** 4)

    mc = (c_frame + c_sus + c_tech) * car_price_rate
    mc += mc - (mc / 10.0) * (skill / 100.0)
    return max(mc, 0.0)


def calc_chassis_design_cost(sliders: dict, sub: dict, year: int) -> float:
    """위키 샤시 Design Cost."""
    s_h = _s(sliders, "FD_Height")
    s_l = _s(sliders, "FD_Length")
    s_wd = _s(sliders, "FD_Width")
    s_w = _s(sliders, "FD_Weight")
    s_el = _s(sliders, "FD_ENG_Length")
    s_ew = _s(sliders, "FD_ENG_Width")
    s_brk = _s(sliders, "SUS_Braking")
    s_comf = _s(sliders, "SUS_Comfort")
    s_perf = _s(sliders, "SUS_Performance")
    s_dur = _s(sliders, "SUS_Durability")
    s_stab = _s(sliders, "SUS_Stability")
    s_tc = _s(sliders, "TECH_Compoenents")
    s_tm = _s(sliders, "TECH_Materials")
    s_tt = _s(sliders, "TECH_Tech")
    s_tq = _s(sliders, "TECH_Techniques")
    s_ctrl = _s(sliders, "DE_Control")
    s_dep = _s(sliders, "DE_Depend")
    s_dp = _s(sliders, "DE_Performance")
    s_str = _s(sliders, "DE_Str")
    s_pace = _s(sliders, "chassis_design_pace", 0.35)

    fr_design = _s(sub, "Frame_Design", 1.0)
    dr_design = _s(sub, "Drive_Design", 1.0)
    fr_sus_design = _s(sub, "FrSus_Design", 1.0)
    rr_sus_design = _s(sub, "RrSus_Design", 1.0)

    e028 = _yexp(1.028, year)
    e025 = _yexp(1.025, year)
    e032 = _yexp(1.032, year)

    # Frame design
    fd_sl = (s_el ** 2 + s_ew ** 2 + s_h ** 2 +
             s_l ** 2 * 1.2 + s_wd ** 2 * 0.8 +
             (1.0 - s_w ** 2 * 0.8))
    dc_frame = fd_sl * 7000.0 * e028
    dc_frame = (dc_frame + 5000.0) * fr_design * dr_design

    # Suspension design
    sd_sl = (s_brk ** 2 * 0.8 + s_comf ** 2 * 1.2 +
             s_dur ** 2 * 1.25 + s_perf ** 2 * 1.15 + s_stab ** 2 * 1.05)
    dc_sus = sd_sl * 9000.0 * e028
    dc_sus = (dc_sus + 2500.0) * fr_sus_design * rr_sus_design

    # Design emphasis
    dd_sl = (s_ctrl ** 2 * 10.0 + s_dep ** 2 * 10.0 +
             s_dp ** 2 * 10.0 + s_str ** 2 * 10.0)
    dc_design = dd_sl * 14000.0 * e028
    dc_design = (dc_design + 12000.0) * fr_design * dr_design * fr_sus_design * rr_sus_design

    # Tech design
    td_sl = s_tc ** 2 + s_tm ** 2 + s_tt ** 2 + s_tq ** 2
    dc_tech = td_sl * 9500.0 * e028 + 15000.0

    # Hyper
    hyper = ((s_ctrl + s_dep + s_dp + s_str +
              s_l + s_wd + s_h + (1.0 - s_w) + s_ew + s_el +
              s_stab + s_comf + s_perf + s_brk + s_dur +
              s_tm + s_tc + s_tq + s_tt) / 19.0)
    hyper_sl = hyper * 100.0 * e025

    dc = (dc_frame + dc_sus + dc_design + dc_tech + hyper_sl) * e032
    dc = (dc / 5.0) + (dc * (s_pace ** 2 * 4.5))
    return max(dc, 0.0)


def calc_chassis_finish_time(sliders: dict, sub: dict, year: int,
                             factory_val: float = 50.0) -> float:
    """위키 샤시 Finish Time."""
    s_h = _s(sliders, "FD_Height")
    s_l = _s(sliders, "FD_Length")
    s_wd = _s(sliders, "FD_Width")
    s_w = _s(sliders, "FD_Weight")
    s_el = _s(sliders, "FD_ENG_Length")
    s_ew = _s(sliders, "FD_ENG_Width")
    s_brk = _s(sliders, "SUS_Braking")
    s_comf = _s(sliders, "SUS_Comfort")
    s_perf = _s(sliders, "SUS_Performance")
    s_dur = _s(sliders, "SUS_Durability")
    s_stab = _s(sliders, "SUS_Stability")
    s_tc = _s(sliders, "TECH_Compoenents")
    s_tm = _s(sliders, "TECH_Materials")
    s_tt = _s(sliders, "TECH_Tech")
    s_ctrl = _s(sliders, "DE_Control")
    s_dep = _s(sliders, "DE_Depend")
    s_dp = _s(sliders, "DE_Performance")
    s_str = _s(sliders, "DE_Str")
    s_pace = _s(sliders, "chassis_design_pace", 0.35)

    hyper = ((s_ctrl + s_dep + s_dp + s_str +
              s_l + s_wd + s_h + (1.0 - s_w) + s_ew + s_el +
              s_stab + s_comf + s_perf + s_brk + s_dur +
              s_tm + s_tc + _s(sliders, "TECH_Techniques") + s_tt) / 19.0)

    e005 = _yexp(1.005, year)
    e003 = _yexp(1.003, year)

    ft_frame = (s_h + s_l + s_wd + (s_el + s_ew) / 1.5) / (s_w + 0.25)
    ft_sus = (s_brk * 0.5 + s_comf + s_dur + s_perf + s_stab) / 2.0
    ft_design = (s_ctrl + s_dep + s_dp + s_str) * 6.0
    ft_tech = (s_tc + s_tm + s_tt) / 1.25

    ft = 4.0 + ((ft_frame + ft_sus + ft_design + ft_tech) / 4.95) * e005 + 1.15 * e003 * hyper

    eff_year = min(year, 2020)
    pace_denom = s_pace + 0.05
    if pace_denom <= 0:
        pace_denom = 0.05
    additional = ((eff_year - 1840) / 15.0) * ((0.5 / pace_denom) - 0.45)

    if s_pace < 0.5:
        ft += additional
    else:
        turns_off = (s_pace - 0.5) / 0.20
        ft += additional - turns_off

    return max(ft, 1.0)


def estimate_chassis_full(sliders: dict, sub: dict, year: int, skill: int) -> dict:
    """모든 샤시 수식 실행, 전체 결과 dict 반환."""
    weight = calc_chassis_weight(sliders, sub, year)
    comfort_r = calc_chassis_comfort_rating(sliders, sub, skill)
    perf_r = calc_chassis_performance_rating(sliders, sub, skill)
    str_r = calc_chassis_strength_rating(sliders, sub, skill)
    dep_r = calc_chassis_dependability_rating(sliders, sub, skill)
    unit_cost = calc_chassis_unit_cost(sliders, sub, year, skill)
    design_cost = calc_chassis_design_cost(sliders, sub, year)
    finish_time = calc_chassis_finish_time(sliders, sub, year)

    return {
        "weight_kg": round(weight, 1),
        "comfort_rating": round(comfort_r, 1),
        "performance_rating": round(perf_r, 1),
        "strength_rating": round(str_r, 1),
        "dependability_rating": round(dep_r, 1),
        "unit_cost": round(unit_cost),
        "design_cost": round(design_cost),
        "finish_time": round(finish_time, 1),
    }


# ── B3. 기어박스 수식 ──────────────────────────────────────────────

def calc_gearbox_torque_capacity(sliders: dict, sub: dict, gears: int,
                                 year: int, skill: int) -> float:
    """위키 기어박스 Max Torque Support (lb-ft)."""
    s_torq = _s(sliders, "TorqueInputRatio", _s(sliders, "MaxTorqueInput",
               _s(sliders, "torque_input", 0.5)))
    s_lo = _s(sliders, "LoRatio", 0.5)
    s_hi = _s(sliders, "HiRatio", 0.5)
    s_dep = _s(sliders, "de_depend", _s(sliders, "depend", 0.3))
    s_tc = _s(sliders, "Tech_Parts", _s(sliders, "tech_parts", 0.3))

    e0225 = _yexp(1.0225, year)

    mts = (10.0 * gears + 75.0 * e0225 * s_torq +
           35.0 * e0225 * (1.0 - s_lo) +
           15.0 * e0225 * (1.0 - s_hi) +
           5.0 * e0225 * s_dep +
           5.0 * e0225 * s_tc + 5.0 * e0225 * s_tc)

    mts += skill / 5.0
    return max(mts, 0.0)


def calc_gearbox_weight(sliders: dict, sub: dict, gears: int) -> float:
    """위키 기어박스 Weight (lbs)."""
    s_torq = _s(sliders, "TorqueInputRatio", _s(sliders, "MaxTorqueInput",
               _s(sliders, "torque_input", 0.5)))
    s_dp = _s(sliders, "de_performance", _s(sliders, "performance", 0.3))
    s_tm = _s(sliders, "Tech_Material", _s(sliders, "tech_material", 0.3))
    gb_complex = _s(sub, "GB_Complexity", 0.5)
    gb_wt = _s(sub, "GB_Weight", 0.5)
    has_reverse = _s(sub, "Reverse", 1.0)
    has_od = _s(sub, "Overdrive", 0.0)
    has_ls = _s(sub, "Limited", 0.0)
    has_ta = _s(sub, "Transaxle", 0.0)

    w = (20.0 + 15.0 * (gears + has_reverse) +
         25.0 * gb_complex + 15.0 * has_od +
         15.0 * has_ls + 50.0 * s_torq -
         50.0 * s_dp + 140.0 * gb_wt +
         30.0 * (1.0 - s_tm)) - 20.0 * has_ta

    return max(w, 5.0)


def calc_gearbox_power_rating(torque_capacity: float, year: int) -> float:
    """위키 기어박스 Power Rating."""
    e0225 = _yexp(1.0225, year)
    denom = 80.0 + 150.0 * e0225 + 90.0 * e0225
    if denom <= 0:
        return 0.0
    pr = 100.0 * (torque_capacity / denom)
    return _clamp(pr)


def calc_gearbox_fuel_rating(sliders: dict, sub: dict, gears: int,
                             year: int, skill: int) -> float:
    """위키 기어박스 Fuel Economy Rating."""
    s_dfe = _s(sliders, "de_fuel", _s(sliders, "fuel", 0.3))
    s_lo = _s(sliders, "LoRatio", 0.5)
    s_hi = _s(sliders, "HiRatio", 0.5)
    s_dp = _s(sliders, "de_performance", _s(sliders, "performance", 0.3))
    s_tc = _s(sliders, "Tech_Parts", _s(sliders, "tech_parts", 0.3))
    s_tm = _s(sliders, "Tech_Material", _s(sliders, "tech_material", 0.3))
    s_tt = _s(sliders, "Tech_Tech", _s(sliders, "tech_tech", 0.3))
    gb_fuel = _s(sub, "GB_Fuel", 0.5)
    has_od = _s(sub, "Overdrive", 0.0)

    r = (15.0 * s_dfe + 15.0 * gb_fuel +
         13.0 * s_lo + 10.0 * s_hi +
         5.0 * (1.0 - s_dp) + 6.0 * has_od +
         2.0 * gears + 5.0 * s_tc +
         6.0 * s_tm + 6.0 * s_tt)

    r += skill / 10.0
    return _clamp(r)


def calc_gearbox_performance_rating(sliders: dict, sub: dict, gears: int,
                                    year: int, skill: int) -> float:
    """위키 기어박스 Performance Rating."""
    s_dp = _s(sliders, "de_performance", _s(sliders, "performance", 0.3))
    s_lo = _s(sliders, "LoRatio", 0.5)
    s_hi = _s(sliders, "HiRatio", 0.5)
    s_tc = _s(sliders, "Tech_Parts", _s(sliders, "tech_parts", 0.3))
    s_tm = _s(sliders, "Tech_Material", _s(sliders, "tech_material", 0.3))
    s_tt = _s(sliders, "Tech_Tech", _s(sliders, "tech_tech", 0.3))
    s_tq = _s(sliders, "Tech_Techniques", _s(sliders, "tech_techniques", 0.3))
    gb_perf = _s(sub, "GB_Performance", 0.5)
    has_ls = _s(sub, "Limited", 0.0)
    has_ta = _s(sub, "Transaxle", 0.0)

    r = (10.0 * s_dp + 13.0 * gb_perf + 2.0 * gears +
         7.0 * s_tt + 6.0 * s_tm + 7.0 * s_tc + 6.0 * s_tq +
         15.0 * (1.0 - s_lo) + 10.0 * s_hi +
         4.0 * has_ls + 2.0 * has_ta)

    r += skill / 10.0
    return _clamp(r)


def calc_gearbox_reliability_rating(sliders: dict, sub: dict, gears: int,
                                    year: int, skill: int) -> float:
    """위키 기어박스 Reliability Rating."""
    s_torq = _s(sliders, "TorqueInputRatio", _s(sliders, "MaxTorqueInput",
               _s(sliders, "torque_input", 0.5)))
    s_dep = _s(sliders, "de_depend", _s(sliders, "depend", 0.3))
    s_ease = _s(sliders, "de_comfort", _s(sliders, "comfort", 0.3))
    s_tc = _s(sliders, "Tech_Parts", _s(sliders, "tech_parts", 0.3))
    s_tm = _s(sliders, "Tech_Material", _s(sliders, "tech_material", 0.3))
    s_tt = _s(sliders, "Tech_Tech", _s(sliders, "tech_tech", 0.3))
    gb_complex = _s(sub, "GB_Complexity", 0.5)
    has_reverse = _s(sub, "Reverse", 1.0)
    has_ls = _s(sub, "Limited", 0.0)
    has_od = _s(sub, "Overdrive", 0.0)
    has_ta = _s(sub, "Transaxle", 0.0)

    r = (20.0 * abs(1.0 - gb_complex) +
         15.0 * s_torq - (gears + has_reverse) +
         10.0 * s_tm + 10.0 * s_tc +
         10.0 * s_dep + 5.0 * (1.0 - gb_complex) +
         5.0 * (1.0 - s_ease) + 5.0 * abs(has_ls - 1.0) +
         5.0 * abs(has_od - 1.0) + 5.0 * abs(has_ta - 1.0) +
         10.0 * (1.0 - s_tt))

    r += skill / 10.0
    return _clamp(r)


def calc_gearbox_comfort_rating(sliders: dict, sub: dict, skill: int) -> float:
    """위키 기어박스 Comfort Rating."""
    s_ease = _s(sliders, "de_comfort", _s(sliders, "comfort", 0.3))
    has_ls = _s(sub, "Limited", 0.0)
    has_reverse = _s(sub, "Reverse", 1.0)
    gb_ease = _s(sub, "GB_Comfort_Sub", _s(sub, "GB_Comfort", 0.5))
    gb_smooth = _s(sub, "GB_Smoothness", 0.5)

    r = (10.0 * has_ls + 10.0 * has_reverse +
         40.0 * s_ease + 20.0 * gb_ease + 20.0 * gb_smooth)

    r += skill / 10.0
    return _clamp(r)


def calc_gearbox_unit_cost(sliders: dict, sub: dict, gears: int,
                           year: int, skill: int,
                           interest_rate: float = DEFAULT_INTEREST_RATE,
                           car_price_rate: float = DEFAULT_CAR_PRICE_RATE) -> float:
    """위키 기어박스 Unit Cost."""
    s_dp = _s(sliders, "de_performance", _s(sliders, "performance", 0.3))
    s_dfe = _s(sliders, "de_fuel", _s(sliders, "fuel", 0.3))
    s_dep = _s(sliders, "de_depend", _s(sliders, "depend", 0.3))
    s_ease = _s(sliders, "de_comfort", _s(sliders, "comfort", 0.3))
    s_torq = _s(sliders, "TorqueInputRatio", _s(sliders, "MaxTorqueInput",
               _s(sliders, "torque_input", 0.5)))
    s_tc = _s(sliders, "Tech_Parts", _s(sliders, "tech_parts", 0.3))
    s_tm = _s(sliders, "Tech_Material", _s(sliders, "tech_material", 0.3))
    s_tt = _s(sliders, "Tech_Tech", _s(sliders, "tech_tech", 0.3))
    s_tq = _s(sliders, "Tech_Techniques", _s(sliders, "tech_techniques", 0.3))
    gb_complex = _s(sub, "GB_Complexity", 0.5)
    gb_uc = _s(sub, "GB_Costs", 1.0)
    has_reverse = _s(sub, "Reverse", 1.0)
    has_od = _s(sub, "Overdrive", 0.0)
    has_ls = _s(sub, "Limited", 0.0)
    has_ta = _s(sub, "Transaxle", 0.0)

    e01 = _yexp(1.01, year)
    e02 = _yexp(1.02, year)
    e008 = _yexp(1.008, year)
    e015 = _yexp(1.015, year)
    e04 = _yexp(1.04, year)

    uc = (20.0 * e01 + 40.0 * e02 * (gears + has_reverse) +
          60.0 * e008 * gb_complex +
          15.0 * e008 * has_od + 65.0 * e008 * has_ta +
          55.0 * e008 * has_ls +
          20.0 * e02 * s_dp ** 2 + 25.0 * e02 * s_dfe ** 2 +
          20.0 * e02 * s_ease ** 2 + 45.0 * e02 * s_dep ** 2 +
          80.0 * e02 * gb_uc +
          30.0 * e015 * s_torq ** 2 +
          40.0 * e02 * (0.5 + s_tt ** 2) +
          55.0 * e015 * (s_tm ** 2 + s_tc ** 2 + s_tq ** 2) * e01)

    uc = uc * (interest_rate / 2.1) * car_price_rate

    hyper = ((s_tm + s_tc + s_tq + s_tt +
              s_torq ** 2 +
              s_dp + s_dfe + s_dep + s_ease) / 9.0)
    hyper_cost = 500.0 * e04 * (hyper ** 4)

    uc = uc + hyper_cost - (uc / 10.0) * (skill / 100.0)
    return max(uc, 0.0)


def calc_gearbox_design_cost(sliders: dict, sub: dict, gears: int,
                             year: int) -> float:
    """위키 기어박스 Design Cost."""
    s_dp = _s(sliders, "de_performance", _s(sliders, "performance", 0.3))
    s_dfe = _s(sliders, "de_fuel", _s(sliders, "fuel", 0.3))
    s_dep = _s(sliders, "de_depend", _s(sliders, "depend", 0.3))
    s_ease = _s(sliders, "de_comfort", _s(sliders, "comfort", 0.3))
    s_torq = _s(sliders, "TorqueInputRatio", _s(sliders, "MaxTorqueInput",
               _s(sliders, "torque_input", 0.5)))
    s_tm = _s(sliders, "Tech_Material", _s(sliders, "tech_material", 0.3))
    s_tt = _s(sliders, "Tech_Tech", _s(sliders, "tech_tech", 0.3))
    s_tq = _s(sliders, "Tech_Techniques", _s(sliders, "tech_techniques", 0.3))
    s_pace = _s(sliders, "gearbox_design_pace", _s(sliders, "design_pace", 0.35))
    gb_complex = _s(sub, "GB_Complexity", 0.5)
    has_reverse = _s(sub, "Reverse", 1.0)
    has_od = _s(sub, "Overdrive", 0.0)
    has_ls = _s(sub, "Limited", 0.0)
    has_ta = _s(sub, "Transaxle", 0.0)

    e017 = _yexp(1.017, year)
    e014 = _yexp(1.014, year)
    e019 = _yexp(1.019, year)
    e027 = _yexp(1.027, year)
    e04 = _yexp(1.04, year)

    # Hyper for gearbox
    hyper = ((_s(sliders, "Tech_Material", 0.3) + _s(sliders, "Tech_Parts", 0.3) +
              _s(sliders, "Tech_Techniques", 0.3) + _s(sliders, "Tech_Tech", 0.3) +
              s_torq ** 2 + s_dp + s_dfe + s_dep + s_ease) / 9.0)
    hyper_cost = 500.0 * e04 * (hyper ** 4)

    dc = (6000.0 * e017 + 250.0 * e017 * (gears + has_reverse) +
          5000.0 * e017 * gb_complex +
          hyper_cost * 100.0 * e027 +
          2000.0 * e014 * s_torq ** 2 +
          2000.0 * e014 * has_ta + 2000.0 * e017 * has_od +
          2500.0 * e019 * has_ls +
          2500.0 * e014 * (0.5 + s_tt ** 2) +
          2500.0 * e014 * s_dp ** 2 +
          3500.0 * e014 * s_dfe ** 2 +
          4000.0 * e014 * s_ease ** 2 +
          8000.0 * e014 * s_dep ** 2 +
          2200.0 * e014 * s_tq ** 2 +
          2200.0 * e014 * s_tm ** 2)

    dc *= e014
    dc *= gears

    dc = (dc / 5.0) + (dc * (s_pace ** 2 * 4.5))
    return max(dc, 0.0)


def calc_gearbox_finish_time(sliders: dict, sub: dict, gears: int,
                             year: int, factory_val: float = 50.0) -> float:
    """위키 기어박스 Finish Time."""
    s_dp = _s(sliders, "de_performance", _s(sliders, "performance", 0.3))
    s_dfe = _s(sliders, "de_fuel", _s(sliders, "fuel", 0.3))
    s_dep = _s(sliders, "de_depend", _s(sliders, "depend", 0.3))
    s_ease = _s(sliders, "de_comfort", _s(sliders, "comfort", 0.3))
    s_tm = _s(sliders, "Tech_Material", _s(sliders, "tech_material", 0.3))
    s_tc = _s(sliders, "Tech_Parts", _s(sliders, "tech_parts", 0.3))
    s_tt = _s(sliders, "Tech_Tech", _s(sliders, "tech_tech", 0.3))
    s_tq = _s(sliders, "Tech_Techniques", _s(sliders, "tech_techniques", 0.3))
    s_pace = _s(sliders, "gearbox_design_pace", _s(sliders, "design_pace", 0.35))
    gb_complex = _s(sub, "GB_Complexity", 0.5)
    gb_ease = _s(sub, "GB_Comfort_Sub", _s(sub, "GB_Comfort", 0.5))
    gb_fuel = _s(sub, "GB_Fuel", 0.5)
    gb_perf = _s(sub, "GB_Performance", 0.5)
    gb_smooth = _s(sub, "GB_Smoothness", 0.5)
    has_reverse = _s(sub, "Reverse", 1.0)
    has_od = _s(sub, "Overdrive", 0.0)
    has_ls = _s(sub, "Limited", 0.0)
    has_ta = _s(sub, "Transaxle", 0.0)

    hyper = ((s_tm + s_tc + s_tq + s_tt +
              _s(sliders, "TorqueInputRatio", _s(sliders, "MaxTorqueInput", 0.5)) ** 2 +
              s_dp + s_dfe + s_dep + s_ease) / 9.0)

    e003 = _yexp(1.003, year)

    ft = (3.0 + 0.35 * gears + 1.5 * gb_complex +
          has_ta + 0.35 * has_od + 0.35 * has_ls +
          0.35 * (s_ease + s_dep + s_dfe + s_dp) +
          0.35 * (gb_ease + gb_fuel + gb_perf + gb_smooth) +
          0.55 * (s_tm + s_tc + s_tt + s_tq))

    ft -= 2.0 * (factory_val / 100.0)
    ft += 1.15 * e003 * hyper

    eff_year = min(year, 2020)
    pace_denom = s_pace + 0.05
    if pace_denom <= 0:
        pace_denom = 0.05
    additional = ((eff_year - 1840) / 15.0) * ((0.5 / pace_denom) - 0.45)

    if s_pace < 0.5:
        ft += additional
    else:
        turns_off = (s_pace - 0.5) / 0.20
        ft += additional - turns_off

    return max(ft, 1.0)


def estimate_gearbox_full(sliders: dict, sub: dict, gears: int,
                          year: int, skill: int) -> dict:
    """모든 기어박스 수식 실행, 전체 결과 dict 반환."""
    torque_cap = calc_gearbox_torque_capacity(sliders, sub, gears, year, skill)
    weight = calc_gearbox_weight(sliders, sub, gears)
    power_r = calc_gearbox_power_rating(torque_cap, year)
    fuel_r = calc_gearbox_fuel_rating(sliders, sub, gears, year, skill)
    perf_r = calc_gearbox_performance_rating(sliders, sub, gears, year, skill)
    rel_r = calc_gearbox_reliability_rating(sliders, sub, gears, year, skill)
    comf_r = calc_gearbox_comfort_rating(sliders, sub, skill)
    unit_cost = calc_gearbox_unit_cost(sliders, sub, gears, year, skill)
    design_cost = calc_gearbox_design_cost(sliders, sub, gears, year)
    finish_time = calc_gearbox_finish_time(sliders, sub, gears, year)

    return {
        "torque_capacity": round(torque_cap, 1),
        "weight_lbs": round(weight, 1),
        "power_rating": round(power_r, 1),
        "fuel_rating": round(fuel_r, 1),
        "performance_rating": round(perf_r, 1),
        "reliability_rating": round(rel_r, 1),
        "comfort_rating": round(comf_r, 1),
        "unit_cost": round(unit_cost),
        "design_cost": round(design_cost),
        "finish_time": round(finish_time, 1),
    }


# ── B4. 차량 수식 (Vehicle-level ratings) ──────────────────────────
# 차량 레이팅은 엔진/샤시/기어박스 레이팅 + 차량 슬라이더로 계산.
# engine_r, chassis_r, gearbox_r은 각 컴포넌트의 레이팅 dict.

def calc_vehicle_performance_rating(engine_r: dict, chassis_r: dict,
                                    gearbox_r: dict, v_sliders: dict,
                                    specs: dict) -> float:
    """위키 차량 Performance Rating (간소화)."""
    hp = _s(specs, "hp", 10)
    weight = _s(specs, "weight_kg", 1000)
    accel_kph = _s(specs, "accel_kph", 30)
    top_speed = _s(specs, "top_speed", 50)
    brake = _s(specs, "braking", 300)
    lateral_g = _s(specs, "lateral_g", 1.0)

    chassis_perf = _s(chassis_r, "performance_rating", 30)
    gearbox_perf = _s(gearbox_r, "performance_rating", 30)
    s_test_perf = _s(v_sliders, "Scroll_TestPerform", 0.3)
    s_test_demo = _s(v_sliders, "Scroll_TestDemo", 0.1)

    # Power to weight ratio
    weight_tons = max(weight * 2.205 / 2000.0, 0.01)
    pwr = -0.024 + 0.003 * (hp / weight_tons)
    pwr = _clamp(pwr, 0.01, 1.0)

    temp_accel = min(max(accel_kph, 0.5), 60.0)
    temp_brake = max(brake, 1.0)

    r = (10.0 * (chassis_perf / 100.0) +
         45.0 * pwr +
         15.0 * s_test_perf +
         5.0 * lateral_g +
         5.0 * (top_speed / 321.0) +
         5.0 * (gearbox_perf / 100.0) +
         5.0 * (50.0 / temp_brake) +
         10.0 * ((60.0 - temp_accel) / 60.0))

    return _clamp(r)


def calc_vehicle_luxury_rating(engine_r: dict, chassis_r: dict,
                               gearbox_r: dict, v_sliders: dict,
                               specs: dict, skill: int) -> float:
    """위키 차량 Luxury Rating."""
    s_dl = _s(v_sliders, "Scroll_DesignLux", 0.3)
    s_ds = _s(v_sliders, "Scroll_DesignStyle", 0.3)
    s_ic = _s(v_sliders, "Scroll_InteriorComf", 0.3)
    s_ii = _s(v_sliders, "Scroll_InteriorInno", 0.3)
    s_il = _s(v_sliders, "Scroll_InteriorLux", 0.3)
    s_is = _s(v_sliders, "Scroll_InteriorStyle", 0.3)
    s_it = _s(v_sliders, "Scroll_InteriorTech", 0.3)
    s_mi = _s(v_sliders, "Scroll_MatMatInterQual", 0.3)
    s_tc = _s(v_sliders, "Scroll_TestComf", 0.3)
    s_tu = _s(v_sliders, "Scroll_TestUtil", 0.3)

    chassis_comf = _s(chassis_r, "comfort_rating", 50)
    gearbox_comf = _s(gearbox_r, "comfort_rating", 50)
    engine_smooth = _s(engine_r, "smoothness_rating", 50)
    cargo_r = _s(specs, "cargo_rating", 30)

    r = (7.0 * s_dl + 7.0 * s_ds +
         4.0 * s_ic + 4.0 * s_ii +
         8.0 * s_il + 4.0 * s_is +
         3.0 * s_it + 5.0 * s_mi +
         5.0 * s_tc + 3.0 * s_tu +
         15.0 * (chassis_comf / 100.0) +
         8.0 * (gearbox_comf / 100.0) +
         10.0 * (engine_smooth / 100.0) +
         5.0 * (cargo_r / 100.0) +
         7.0 * (skill / 100.0))

    return _clamp(r)


def calc_vehicle_safety_rating(chassis_r: dict, v_sliders: dict,
                               specs: dict, skill: int) -> float:
    """위키 차량 Safety Rating."""
    s_dsafety = _s(v_sliders, "Scroll_DesignSafety", 0.3)
    s_isafe = _s(v_sliders, "Scroll_InteriorSafe", 0.3)
    s_it = _s(v_sliders, "Scroll_InteriorTech", 0.3)
    s_mt = _s(v_sliders, "Scroll_MatManuTech", 0.3)
    s_mi = _s(v_sliders, "Scroll_MatMatInterQual", 0.3)
    s_mq = _s(v_sliders, "Scroll_MatMatQual", 0.3)
    s_tr = _s(v_sliders, "Scroll_TestReli", 0.3)

    weight = _s(specs, "weight_kg", 1000)
    brake = max(_s(specs, "braking", 300), 1.0)
    chassis_str = _s(chassis_r, "strength_rating", 50)

    r = (10.0 * s_dsafety + 10.0 * s_isafe +
         2.0 * s_it + 2.0 * s_mt + 2.0 * s_mi +
         2.0 * s_mq + 2.0 * s_tr +
         20.0 * (weight / 4000.0) +
         15.0 * (skill / 100.0) +
         5.0 * (50.0 / brake) +
         15.0 * (chassis_str / 100.0))

    return _clamp(r)


def calc_vehicle_fuel_rating(fuel_mileage: float) -> float:
    """위키 차량 Fuel Rating = fuel_mileage * 2, capped 100."""
    return _clamp(fuel_mileage * 2.0, 1.0, 100.0)


def calc_vehicle_cargo_rating(v_sliders: dict, specs: dict) -> float:
    """위키 차량 Cargo Rating."""
    cargo_vol = _s(specs, "cargo_volume", 500)
    s_dc = _s(v_sliders, "Scroll_DesignCargo", 0.3)
    s_tu = _s(v_sliders, "Scroll_TestUtil", 0.3)

    r = 85.0 * (cargo_vol / 3200.0)
    if r > 85.0:
        r = 85.0
    r += 10.0 * s_dc + 5.0 * s_tu
    return _clamp(r)


def calc_vehicle_quality_rating(engine_r: dict, chassis_r: dict,
                                gearbox_r: dict, v_sliders: dict,
                                skill: int, torque_compatible: bool = True,
                                torque_ratio: float = 1.0) -> float:
    """위키 차량 Quality Rating."""
    s_dd = _s(v_sliders, "Scroll_DesignDepend", 0.3)
    s_dl = _s(v_sliders, "Scroll_DesignLux", 0.3)
    s_ds = _s(v_sliders, "Scroll_DesignStyle", 0.3)
    s_mt = _s(v_sliders, "Scroll_MatManuTech", 0.3)
    s_mi = _s(v_sliders, "Scroll_MatMatInterQual", 0.3)
    s_mp = _s(v_sliders, "Scroll_MatPaintQual", 0.3)
    s_tr = _s(v_sliders, "Scroll_TestReli", 0.3)
    s_tu = _s(v_sliders, "Scroll_TestUtil", 0.3)

    gb_rel = _s(gearbox_r, "reliability_rating", 50)
    ch_dur = _s(chassis_r, "dependability_rating", 50)
    eng_rel = _s(engine_r, "reliability_rating", 50)

    r = (10.0 * s_dd + 5.0 * s_dl + 5.0 * s_ds +
         5.0 * s_mt + 15.0 * s_mi + 10.0 * s_mp +
         10.0 * s_tr + 5.0 * s_tu +
         5.0 * (gb_rel / 100.0) +
         5.0 * (ch_dur / 100.0) +
         5.0 * (eng_rel / 100.0) +
         20.0 * (skill / 100.0))

    r = _clamp(r)

    if not torque_compatible and torque_ratio < 1.0:
        r = r * 0.7 + r * 0.25 * torque_ratio

    return _clamp(r)


def calc_vehicle_dependability_rating(engine_r: dict, chassis_r: dict,
                                      gearbox_r: dict, v_sliders: dict,
                                      torque_compatible: bool = True,
                                      torque_ratio: float = 1.0) -> float:
    """위키 차량 Dependability Rating."""
    s_dd = _s(v_sliders, "Scroll_DesignDepend", 0.3)
    s_mq = _s(v_sliders, "Scroll_MatMatQual", 0.3)
    s_tr = _s(v_sliders, "Scroll_TestReli", 0.3)
    s_tu = _s(v_sliders, "Scroll_TestUtil", 0.3)

    gb_rel = _s(gearbox_r, "reliability_rating", 50)
    ch_dur = _s(chassis_r, "dependability_rating", 50)
    ch_str = _s(chassis_r, "strength_rating", 50)
    eng_rel = _s(engine_r, "reliability_rating", 50)
    eng_smooth = _s(engine_r, "smoothness_rating", 50)

    r = (20.0 * s_dd + 5.0 * s_mq +
         15.0 * s_tr + 5.0 * s_tu +
         15.0 * (ch_dur / 100.0) + 5.0 * (ch_str / 100.0) +
         10.0 * (gb_rel / 100.0) +
         20.0 * (eng_rel / 100.0) +
         5.0 * (eng_smooth / 100.0))

    r = _clamp(r)

    if not torque_compatible and torque_ratio < 1.0:
        r = r * torque_ratio * 0.95

    return _clamp(r)


def calc_vehicle_unit_cost(v_sliders: dict, year: int, skill: int,
                           engine_uc: float = 0, chassis_uc: float = 0,
                           gearbox_uc: float = 0,
                           wealth_index: int = 3,
                           interest_rate: float = DEFAULT_INTEREST_RATE,
                           car_price_rate: float = DEFAULT_CAR_PRICE_RATE) -> float:
    """위키 차량 Unit Cost (simplified — vehicle-only portion)."""
    # Interior sliders
    s_ic = _s(v_sliders, "Scroll_InteriorComf", 0.3)
    s_il = _s(v_sliders, "Scroll_InteriorLux", 0.3)
    s_is = _s(v_sliders, "Scroll_InteriorSafe", 0.3)
    s_it = _s(v_sliders, "Scroll_InteriorTech", 0.3)
    s_ii = _s(v_sliders, "Scroll_InteriorInno", 0.3)
    s_ist = _s(v_sliders, "Scroll_InteriorStyle", 0.3)
    # Design sliders
    s_dc = _s(v_sliders, "Scroll_DesignCargo", 0.3)
    s_dd = _s(v_sliders, "Scroll_DesignDepend", 0.3)
    s_dsf = _s(v_sliders, "Scroll_DesignSafety", 0.3)
    s_dst = _s(v_sliders, "Scroll_DesignStyle", 0.3)
    s_dl = _s(v_sliders, "Scroll_DesignLux", 0.3)
    # Material sliders
    s_mq = _s(v_sliders, "Scroll_MatMatQual", 0.3)
    s_mt = _s(v_sliders, "Scroll_MatManuTech", 0.3)
    s_mi = _s(v_sliders, "Scroll_MatMatInterQual", 0.3)
    s_mp = _s(v_sliders, "Scroll_MatPaintQual", 0.3)
    # Testing sliders
    s_td = _s(v_sliders, "Scroll_TestDemo", 0.1)
    s_tp = _s(v_sliders, "Scroll_TestPerform", 0.3)
    s_tf = _s(v_sliders, "Scroll_TestFuel", 0.3)
    s_tc = _s(v_sliders, "Scroll_TestComf", 0.3)
    s_tu = _s(v_sliders, "Scroll_TestUtil", 0.3)
    s_tr = _s(v_sliders, "Scroll_TestReli", 0.3)

    demo_wealth = _s(v_sliders, "DemoIncome", 3)

    e02 = _yexp(1.02, year)
    e04 = _yexp(1.04, year)

    interior_sq = ((s_ic ** 2 + s_il ** 2 + s_is ** 2 + s_it ** 2 +
                    (s_ii ** 2 + s_ist ** 2) / 2.5) / 3.5)
    design_sq = (s_dc ** 2 + s_dd ** 2 + s_dsf ** 2 + s_dst ** 2 + s_dl ** 2) / 4.0
    test_sq = (s_td ** 2 + s_tp ** 2 + s_tf ** 2 + s_tc ** 2 + s_tu ** 2 + s_tr ** 2) / 7.0
    mat_sq = (s_mq ** 2 + s_mt ** 2 + s_mi ** 2 + s_mp ** 2) / 1.5

    uc = 200.0 * e02 * (interior_sq + design_sq + test_sq + mat_sq)
    uc *= (wealth_index / 3.0)
    uc *= (interest_rate / 2.1)
    uc *= car_price_rate

    uc += 130.0 * e02 * (demo_wealth / 5.0)
    uc += 150.0 * e02 * (demo_wealth / 10.0) * s_td

    # Hyper
    hyper = ((s_ist + s_ii + s_il + s_ic + s_is + s_it +
              s_mq + s_mi + s_mp + s_mt +
              s_dst + s_dl + s_dsf + s_dc + s_dd +
              s_td + s_tp + s_tf + s_tc + s_tu + s_tr) / 21.0)
    hyper_cost = 450.0 * e04 * (hyper ** 4)

    total = chassis_uc + engine_uc + gearbox_uc + uc + hyper_cost
    total -= (uc / 10.0) * (skill / 100.0)
    return max(total, 0.0)


def calc_vehicle_design_cost(v_sliders: dict, year: int,
                             engine_uc: float = 0, chassis_uc: float = 0,
                             gearbox_uc: float = 0) -> float:
    """위키 차량 Design Cost."""
    s_dc = _s(v_sliders, "Scroll_DesignCargo", 0.3)
    s_dd = _s(v_sliders, "Scroll_DesignDepend", 0.3)
    s_dl = _s(v_sliders, "Scroll_DesignLux", 0.3)
    s_dsf = _s(v_sliders, "Scroll_DesignSafety", 0.3)
    s_dst = _s(v_sliders, "Scroll_DesignStyle", 0.3)
    s_ii = _s(v_sliders, "Scroll_InteriorInno", 0.3)
    s_is = _s(v_sliders, "Scroll_InteriorSafe", 0.3)
    s_ist = _s(v_sliders, "Scroll_InteriorStyle", 0.3)
    s_tc = _s(v_sliders, "Scroll_TestComf", 0.3)
    s_td = _s(v_sliders, "Scroll_TestDemo", 0.1)
    s_tf = _s(v_sliders, "Scroll_TestFuel", 0.3)
    s_tp = _s(v_sliders, "Scroll_TestPerform", 0.3)
    s_tr = _s(v_sliders, "Scroll_TestReli", 0.3)
    s_tu = _s(v_sliders, "Scroll_TestUtil", 0.3)
    s_pace = _s(v_sliders, "car_design_pace", _s(v_sliders, "SlidersDesignPace", 0.35))
    demo_wealth = _s(v_sliders, "DemoIncome", 3)

    e03 = _yexp(1.03, year)
    e05 = _yexp(1.05, year)
    e04 = _yexp(1.04, year)

    # Hyper
    hyper = ((_s(v_sliders, "Scroll_InteriorStyle", 0.3) +
              _s(v_sliders, "Scroll_InteriorInno", 0.3) +
              _s(v_sliders, "Scroll_InteriorLux", 0.3) +
              _s(v_sliders, "Scroll_InteriorComf", 0.3) +
              _s(v_sliders, "Scroll_InteriorSafe", 0.3) +
              _s(v_sliders, "Scroll_InteriorTech", 0.3) +
              _s(v_sliders, "Scroll_MatMatQual", 0.3) +
              _s(v_sliders, "Scroll_MatMatInterQual", 0.3) +
              _s(v_sliders, "Scroll_MatPaintQual", 0.3) +
              _s(v_sliders, "Scroll_MatManuTech", 0.3) +
              s_dst + s_dl + s_dsf + s_dc + s_dd +
              s_td + s_tp + s_tf + s_tc + s_tu + s_tr) / 21.0)
    hyper_cost = 450.0 * e04 * (hyper ** 4)

    dc = (hyper_cost * 400.0 * e03 +
          chassis_uc * 400.0 * e03 +
          engine_uc * 400.0 * e03 +
          gearbox_uc * 400.0 * e03 +
          20000.0 * e05 * (s_dc ** 2 + s_dd ** 2 + s_dl ** 2 +
                           s_dsf ** 2 + s_dst ** 2 +
                           s_ii ** 2 + s_is ** 2 + s_ist ** 2 +
                           s_tc ** 2 * 2.0 + s_td ** 2 * 2.0 +
                           s_tf ** 2 * 2.0 + s_tp ** 2 * 2.0 +
                           s_tr ** 2 * 2.0 + s_tu ** 2 * 2.0) +
          40000.0 * e03 * (demo_wealth / 10.0) * s_td)

    dc = (dc / 5.0) + (dc / 1.25) * (s_pace ** 2 * 4.5)
    return max(dc, 0.0)


def calc_vehicle_finish_time(v_sliders: dict, year: int,
                             skill: int = 50,
                             factory_val: float = 50.0) -> float:
    """위키 차량 Finish Time."""
    s_ii = _s(v_sliders, "Scroll_InteriorInno", 0.3)
    s_ist = _s(v_sliders, "Scroll_InteriorStyle", 0.3)
    s_is = _s(v_sliders, "Scroll_InteriorSafe", 0.3)
    s_dc = _s(v_sliders, "Scroll_DesignCargo", 0.3)
    s_dd = _s(v_sliders, "Scroll_DesignDepend", 0.3)
    s_dl = _s(v_sliders, "Scroll_DesignLux", 0.3)
    s_dsf = _s(v_sliders, "Scroll_DesignSafety", 0.3)
    s_dst = _s(v_sliders, "Scroll_DesignStyle", 0.3)
    s_tc = _s(v_sliders, "Scroll_TestComf", 0.3)
    s_td = _s(v_sliders, "Scroll_TestDemo", 0.1)
    s_tf = _s(v_sliders, "Scroll_TestFuel", 0.3)
    s_tp = _s(v_sliders, "Scroll_TestPerform", 0.3)
    s_tr = _s(v_sliders, "Scroll_TestReli", 0.3)
    s_tu = _s(v_sliders, "Scroll_TestUtil", 0.3)
    s_pace = _s(v_sliders, "car_design_pace", _s(v_sliders, "SlidersDesignPace", 0.35))

    e005 = _yexp(1.005, year)
    e0035 = _yexp(1.0035, year)

    hyper = ((_s(v_sliders, "Scroll_InteriorStyle", 0.3) +
              _s(v_sliders, "Scroll_InteriorInno", 0.3) +
              _s(v_sliders, "Scroll_InteriorLux", 0.3) +
              _s(v_sliders, "Scroll_InteriorComf", 0.3) +
              _s(v_sliders, "Scroll_InteriorSafe", 0.3) +
              _s(v_sliders, "Scroll_InteriorTech", 0.3) +
              _s(v_sliders, "Scroll_MatMatQual", 0.3) +
              _s(v_sliders, "Scroll_MatMatInterQual", 0.3) +
              _s(v_sliders, "Scroll_MatPaintQual", 0.3) +
              _s(v_sliders, "Scroll_MatManuTech", 0.3) +
              s_dst + s_dl + s_dsf + s_dc + s_dd +
              s_td + s_tp + s_tf + s_tc + s_tu + s_tr) / 21.0)

    ft = (0.7 * (s_ii + s_ist + s_is) +
          0.9 * (s_dc + s_dd * 2.0 + s_dc + s_dl + s_dsf + s_dst) +
          1.5 * (s_tc + s_td + s_tf + s_tp + s_tr + s_tu))

    ft += 2.0 * e005 - 3.0 * e005 * (skill / 100.0)
    ft -= 2.0 * (factory_val / 100.0)
    ft += 1.25 * e0035 * hyper
    ft += (year - 1870) / 30.0

    # Design pace
    eff_year = min(year, 2020)
    pace_denom = s_pace + 0.05
    if pace_denom <= 0:
        pace_denom = 0.05
    additional = ((eff_year - 1840) / 15.0) * ((0.5 / pace_denom) - 0.45)

    if s_pace < 0.5:
        ft += additional
    else:
        turns_off = (s_pace - 0.5) / 0.20
        ft += additional - turns_off

    return max(ft, 1.0)


# ── B5. 슬라이더 변경 시뮬레이션 (범용) ──────────────────────────────

def simulate_slider_change(component_type: str, current_sliders: dict,
                           changes: dict, sub_components: dict,
                           year: int, skill: int,
                           **kwargs) -> dict:
    """슬라이더 변경 전/후 비교. before/after/diff 반환.

    component_type: 'engine', 'chassis', 'gearbox'
    changes: {slider_name: new_value} — 변경할 슬라이더만
    """
    estimate_fn = {
        "engine": estimate_engine_full,
        "chassis": estimate_chassis_full,
        "gearbox": estimate_gearbox_full,
    }.get(component_type)

    if not estimate_fn:
        return {"error": f"Unknown component type: {component_type}"}

    # Before
    if component_type == "gearbox":
        gears = kwargs.get("gears", 4)
        before = estimate_fn(dict(current_sliders), dict(sub_components), gears, year, skill)
    elif component_type == "engine":
        bore = kwargs.get("bore_mm", 70.0)
        stroke = kwargs.get("stroke_mm", 80.0)
        cyls = kwargs.get("cylinders", 4)
        before = estimate_fn(dict(current_sliders), dict(sub_components), year, skill, bore, stroke, cyls)
    else:
        before = estimate_fn(dict(current_sliders), dict(sub_components), year, skill)

    # After
    after_sliders = dict(current_sliders)
    after_sliders.update(changes)

    if component_type == "gearbox":
        after = estimate_fn(after_sliders, dict(sub_components), gears, year, skill)
    elif component_type == "engine":
        after = estimate_fn(after_sliders, dict(sub_components), year, skill, bore, stroke, cyls)
    else:
        after = estimate_fn(after_sliders, dict(sub_components), year, skill)

    # Diff
    diff = {}
    for key in before:
        if isinstance(before[key], (int, float)) and isinstance(after[key], (int, float)):
            diff[key] = round(after[key] - before[key], 2)

    return {"before": before, "after": after, "diff": diff}
