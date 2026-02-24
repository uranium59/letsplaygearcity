# Vehicle Design Slider Reference

## Interior Sliders (Scroll_Interior*)
### Style (Scroll_InteriorStyle)
- Luxury rating: 4× weight
- Manufacturing: 3× contribution
- Unit cost: slider² / 2.5 divisor (cheaper than other interiors)
- Design cost: slider² in main sum
- Moderate impact across ratings

### Innovation (Scroll_InteriorInno)
- Luxury rating: 4× weight
- Design requirement: 6× weight (high)
- Finish time: 0.7× contribution
- Unit cost: slider² / 2.5 (same as style)

### Luxury (Scroll_InteriorLux)
- Luxury rating: 8× weight (strongest interior slider)
- Adds vehicle weight
- Manufacturing: 3× contribution
- Unit cost: slider² in main interior group

### Comfort (Scroll_InteriorComf)
- Luxury rating: 4× weight
- Safety factor: adds weight
- Design requirement: 4× contribution
- Unit cost: slider² in main interior group

### Safety (Scroll_InteriorSafe)
- Safety rating: 10× weight (very strong)
- Design requirement: 10× weight (most expensive interior for design)
- Adds significant weight (1.25× factor)
- Finish time: 0.7× contribution

### Technology (Scroll_InteriorTech)
- Safety: 2× weight
- Luxury: 3× weight
- Manufacturing: 3× contribution

## Materials Sliders (Scroll_Mat*)
### Material Quality (Scroll_MatMatQual)
- Safety: 2× weight
- Adds vehicle weight (0.35× factor)
- Quality: 0 (surprisingly low direct impact)
- Dependability: 5× weight
- Manufacturing: 4× contribution

### Interior Quality (Scroll_MatMatInterQual)
- Quality rating: 15× weight (strongest quality slider!)
- Luxury: 5× weight
- Safety: 2× weight
- Manufacturing: 4× contribution

### Paint Quality (Scroll_MatPaintQual)
- Quality: 10× weight
- Manufacturing: 4× contribution
- Design requirement: only 1× (cheap for design)

### Manufacturing Techniques (Scroll_MatManuTech)
- Safety: 2× weight
- Quality: 5× weight
- Manufacturing: 7× contribution (highest!)
- Reduces weight slightly (-0.4× factor)
- Best for manufacturing efficiency

## Design Focus Sliders (Scroll_Design*)
### Style (Scroll_DesignStyle)
- Quality: 5× weight
- Luxury: 7× weight
- Design requirement: 10× weight
- Unit cost: slider² / 4.0 group

### Luxury (Scroll_DesignLux)
- Luxury: 7× weight
- Quality: 5× weight
- Design requirement: 6× weight
- Design cost: slider² in 20000× group

### Safety (Scroll_DesignSafety)
- Safety: 10× weight
- Braking improvement
- Design requirement: 10× weight
- Adds weight: slider × (1.3 - 0.3 × year_factor)

### Cargo (Scroll_DesignCargo)
- Cargo rating: 10× weight
- Also affects cargo volume calculation (0.25× factor)
- Design requirement: 5× weight
- Finish time: 0.9× contribution (appears twice in formula!)

### Dependability (Scroll_DesignDepend)
- Dependability: 20× weight (strongest single rating impact!)
- Quality: 10× weight
- Design requirement: 15× weight (most expensive design slider)
- Finish time: 0.9 × 2× = 1.8 contribution (doubled!)

## Testing Sliders (Scroll_Test*)
### Demographics (Scroll_TestDemo)
- Multiplied by demographic targeting bonuses (75× Demo × slider)
- Affects ALL ratings through demographic multiplier
- Manufacturing: increases with wealth targeting
- **Critical for demographic-targeted vehicles**

### Performance (Scroll_TestPerform)
- Performance: 15× weight
- Driveability: 12× weight
- Reduces weight slightly (-0.4× factor)
- Finish time: 1.5× contribution (expensive in time)

### Fuel Economy (Scroll_TestFuel)
- Fuel mileage: 0.7× slider direct boost
- Reduces weight (-0.4× factor)
- Finish time: 1.5× contribution

### Comfort (Scroll_TestComf)
- Luxury: 5× weight
- Hurts driveability: -2× penalty
- Finish time: 1.5× contribution

### Utility (Scroll_TestUtil)
- Cargo: 5× weight
- Quality: 5× weight
- Dependability: 5× weight
- Finish time: 1.5× contribution

### Reliability (Scroll_TestReli)
- Quality: 10× weight
- Safety: 2× weight
- Dependability: 15× weight (strong!)
- Finish time: 1.5× contribution

## Demographic Targeting
### Gender (DemoGender)
- Male: +performance/power/driveability, -fuel/safety/cargo
- Female: +fuel/safety/cargo, -performance/power/driveability
- Neutral: no bonuses or penalties

### Age (DemoAge)
- <25: +performance/fuel/dependability, -luxury/safety/quality
- 25-35: +safety/dependability/cargo, -performance/power/driveability
- 35-55: +performance/power/luxury/quality, -fuel/dependability/safety/cargo
- >55: +safety/luxury/quality/dependability, -performance/power/driveability/fuel

### Wealth (DemoIncome)
- Ultra-Low(0) to Ultra-Wealthy(7)
- Higher wealth → more luxury/safety bonuses
- Affects unit cost: 130 × year × (wealth/5) + 150 × year × (wealth/10) × demo_slider
- Quality rating bonus: 75 × (wealth/15) × demo_slider

## Cost Structure
- **Unit cost**: Vehicle sliders (all squared) × Car_Type.Wealth_Index × interest_rate
  - + engine unit cost + chassis unit cost + gearbox unit cost
  - Hyper penalty: average of 21 sliders to 4th power × 450 × 1.04^year
- **Design cost**: (hyper × 400 × year_exp) + component costs × 400 + 20000 × slider² sums
  - Design pace: (cost/5) + (cost/1.25 × pace² × 4.5)
- **Finish time**: Interior(0.7×) + Design(0.9×) + Testing(1.5×) + year factor
  - New Generation/Trim discounts: 15% base, +5% gearbox, +5% engine, +75% chassis

## Vehicle Ratings Summary
| Rating | Primary Drivers |
|--------|----------------|
| Performance | Power-to-weight, acceleration, chassis performance, testing |
| Driveability | Chassis performance, suspension, roadholding, gearbox comfort |
| Luxury | Interior sliders, materials, chassis comfort, engine smoothness |
| Safety | Design safety, interior safety, weight, braking, chassis strength |
| Fuel | Engine fuel mileage × 2 (capped at 100) |
| Power | Engine torque, towing capacity, gearbox power rating |
| Cargo | Cargo volume, design cargo, testing utility |
| Quality | Materials interior (15×!), testing reliability, dependability |
| Dependability | Design depend (20×!), engine reliability, gearbox reliability |
| Overall | Average of all ratings + component overalls + skill |

## Torque Compatibility (Critical!)
- If gearbox max torque < engine torque:
  - Quality = (Quality × 0.7) + (Quality × 0.25 × gearbox_torque/engine_torque)
  - Dependability = Dependability × (gearbox_torque/engine_torque) × 0.95
- Always ensure gearbox torque capacity > engine torque!

## Design Pace (연구 자금 슬라이더)

모든 컴포넌트(엔진/샤시/기어박스/차량)에 존재하는 순수 시간-비용 트레이드오프 슬라이더.
**레이팅에는 전혀 영향 없음** — 오직 개발 속도, 설계비, 필요 인력만 변경.

### 설계비 영향
- 공식: `최종 설계비 = (기본비/5) + (기본비 × pace² × 4.5)`
- pace=0.0: 최종 = 기본비/5 (20%) — 최저 비용이지만 매우 느림
- pace=0.35: 최종 = 기본비/5 + 기본비×0.55 = ~75% — 합리적 기본값
- pace=0.50: 최종 = 기본비/5 + 기본비×1.125 = ~133%
- pace=0.70: 최종 = 기본비/5 + 기본비×2.205 = ~240%
- pace=1.00: 최종 = 기본비/5 + 기본비×4.5 = ~470% — 비용 4.7배!

### 개발 시간(Finish Time) 영향
- pace < 0.5: 추가 시간 = ((year-1840)/15) × ((0.5/(pace+0.05)) - 0.45)
  - pace=0.1: +약 5턴 추가
  - pace=0.3: +약 1턴 추가
- pace = 0.5: 추가 시간 없음 (기준점)
- pace > 0.5: 시간 단축 = (pace-0.5)/0.2 턴 감소
  - pace=0.7: -1턴
  - pace=1.0: -2.5턴

### 필요 인력(Employees)
- 공식: `기본인력 = 설계요구 × (연도계수)`, `최종 = 기본/5 + (기본/1.2 × pace) + 3`
- pace↑ → 필요 인력 비례 증가
- pace=0.3: 인력 최소화 (느린 개발에 적합)
- pace=0.7+: 인력 급증, 현금이 충분할 때만 사용

### 추천 전략
- **초기(자금 부족)**: pace 0.2~0.35 — 느리지만 비용·인력 최소
- **중기(안정)**: pace 0.4~0.5 — 균형점
- **긴급 개선/경쟁 필요**: pace 0.6~0.7 — 빠르지만 비용 2배+
- **pace > 0.8**: 비상 상황 외 비추천, 설계비 300%+ 폭증

## Extreme Value Warnings

### Hyper-Slider Penalty (차량)
- 21개 슬라이더 평균의 4제곱 × 450 × 1.04^year → 유닛비용에 가산
- 차량은 슬라이더 수가 가장 많아 개별 슬라이더 변화의 평균 영향이 작음
- 그러나 Interior+Materials+Design+Testing 전반을 높이면 페널티 급증

### 극단값 주의 — 너무 높을 때
- **Scroll_InteriorSafe > 0.7**: 안전 10× 좋지만 설계요구 10× + 무게 1.25× — 비용 폭발
- **Scroll_DesignDepend > 0.7**: 내구성 20× 최강이지만 설계요구 15× + 완료시간 1.8× (최대)
- **Scroll_TestPerform/Fuel/Comfort > 0.7**: 완료시간 1.5× 계수 — 테스팅 시간 급증
- **Scroll_DesignSafety > 0.7**: 안전 10× + 무게 증가, 연도가 지나면 무게 계수 감소

### 극단값 주의 — 너무 낮을 때
- **Scroll_MatMatInterQual = 0**: 품질 레이팅에 15× 기여 — 완전 무시하면 품질 파괴적
- **Scroll_DesignDepend = 0**: 내구성 20× 기여 상실 — 내구성 레이팅 치명적
- **Scroll_TestDemo = 0**: 인구통계 타겟팅 보너스 완전 비활성화

### 비용 효율 최적 구간
- **대부분의 슬라이더**: 0.2~0.55 구간이 비용 대비 최적
- **Testing 슬라이더**: 1.5× 시간 계수가 크므로 0.3~0.5 추천
- **Scroll_MatManuTech**: 제조 7× (최고) — 비용 대비 효율 최고, 0.5~0.7 추천
