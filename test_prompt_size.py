"""Design advisor 프롬프트 크기 측정 — 토큰 제한 문제 진단."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src.nodes_advisors import DESIGN_SYSTEM_MESSAGE
from src.prompts import (
    DESIGN_GOAL_PROMPT, DESIGN_STAGE_ENGINE_PROMPT,
    DESIGN_STAGE_CHASSIS_PROMPT, DESIGN_STAGE_GEARBOX_PROMPT,
    DESIGN_STAGE_VEHICLE_PROMPT, DESIGN_SUMMARY_PROMPT,
)
from src.design_formulas import (
    compute_sensitivity, format_evidence_cards,
    ENGINE_SLIDER_KEYS, CHASSIS_SLIDER_KEYS, GEARBOX_SLIDER_KEYS,
)

# 시뮬레이션: 실제와 동일한 조건
year, skill = 1900, 5
engine_sliders = {k: 0.5 for k in ENGINE_SLIDER_KEYS}
chassis_sliders = {k: 0.5 for k in CHASSIS_SLIDER_KEYS}
gearbox_sliders = {k: 0.5 for k in GEARBOX_SLIDER_KEYS}

# 감도 분석
e_sens = compute_sensitivity("engine", engine_sliders, {}, year, skill)
e_cards = format_evidence_cards("engine", e_sens)

c_sens = compute_sensitivity("chassis", chassis_sliders, {}, year, skill)
c_cards = format_evidence_cards("chassis", c_sens)

g_sens = compute_sensitivity("gearbox", gearbox_sliders, {}, year, skill)
g_cards = format_evidence_cards("gearbox", g_sens)

print(f"System message: {len(DESIGN_SYSTEM_MESSAGE)} chars", flush=True)
print(f"Engine evidence cards: {len(e_cards)} chars", flush=True)
print(f"Chassis evidence cards: {len(c_cards)} chars", flush=True)
print(f"Gearbox evidence cards: {len(g_cards)} chars", flush=True)

# 실제 프롬프트 조립 (엔진 스테이지)
engine_prompt = DESIGN_STAGE_ENGINE_PROMPT.format(
    goal_summary="Mode: new, Car Type: Standard, Segment: any",
    engine_evidence_cards=e_cards,
    constraints="(no constraints)",
    available_components="Layout: I (Inline)\nFuel: Gasoline\nInduction: Naturally Aspirated\nValve: F Head",
    current_engine="(New design — no current values)",
)

total_engine = len(DESIGN_SYSTEM_MESSAGE) + len(engine_prompt)
print(f"\nEngine stage total prompt: {total_engine} chars", flush=True)

# 대략적 토큰 추정 (영문 ~4 chars/token, 혼합 ~3 chars/token)
est_tokens = total_engine / 3
print(f"Estimated tokens (chars/3): {est_tokens:.0f}", flush=True)
print(f"num_ctx: 32768, num_predict: 3000", flush=True)
print(f"Available for output: {32768 - est_tokens:.0f} tokens", flush=True)

if est_tokens > 32768 - 3000:
    print(f"\n⚠ PROBLEM: Input likely exceeds context window!", flush=True)
    print(f"  Input ~{est_tokens:.0f} + output 3000 = {est_tokens+3000:.0f} > 32768", flush=True)
elif est_tokens > 32768 - 500:
    print(f"\n⚠ PROBLEM: Almost no room for output!", flush=True)
else:
    print(f"\n✓ Should have room for output", flush=True)

# Summary 프롬프트 크기도 측정
print(f"\n--- Summary prompt template: {len(DESIGN_SUMMARY_PROMPT)} chars ---", flush=True)
