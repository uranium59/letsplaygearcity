# Gearbox Design Slider Reference

## Specification Sliders (in DB as LoRatio, HiRatio, TorqueInputRatio)
### Low-End Gearing (LoRatio)
- Affects torque support: 35 × year_exp × (1-slider) — lower ratio = more torque support
- Fuel rating: 13 × slider — higher ratio = better fuel economy
- Performance rating: 15 × (1-slider) — lower ratio = more performance
- Weight impact: not directly slider-based
- **Tradeoff**: Low ratio → power/performance, High ratio → fuel economy

### High-End Gearing (HiRatio)
- Torque support: 15 × year_exp × (1-slider)
- Fuel rating: 10 × slider
- Performance rating: 10 × slider (opposite to low gear!)
- Affects top speed significantly
- **Tradeoff**: Increases both fuel economy and performance (rare win-win)

### Maximum Torque Input (TorqueInputRatio)
- Primary driver of torque support capacity
- Formula: 75 × year_exp × slider
- Weight: 50 × slider (heavy)
- Reliability: 15 × slider (helps)
- Unit cost: 30 × year_exp × slider²
- **Critical**: Must exceed engine torque to avoid quality/reliability penalties

## Design Focus Sliders
### Performance (de_performance)
- Performance rating: 10 × slider
- Reduces weight: -50 × slider
- Unit cost: 20 × year_exp × slider²
- Design cost: 2500 × year_exp × slider²
- Hurts fuel rating: 5 × (1-slider) fuel bonus lost

### Fuel Economy (de_fuel)
- Fuel rating: 15 × slider
- Unit cost: 25 × year_exp × slider²
- Design cost: 3500 × year_exp × slider²

### Dependability (de_depend)
- Reliability: 10 × slider
- Torque support: 5 × year_exp × slider
- Unit cost: 45 × year_exp × slider² (most expensive design slider!)
- Design cost: 8000 × year_exp × slider²
- Manufacturing: 13 × slider contribution

### Comfort/Shifting Ease (de_comfort)
- Comfort rating: 40 × slider (dominant factor!)
- Unit cost: 20 × year_exp × slider²
- Design cost: 4000 × year_exp × slider²
- Hurts reliability: 5 × (1-slider) penalty

## Technology Sliders
### Material (Tech_Material)
- Fuel: 6 × slider, Performance: 6 × slider
- Reliability: 10 × slider
- Reduces weight: -30 × (1-slider)
- Unit cost: 55 × year_exp × slider² (grouped)
- Design cost: 2200 × year_exp × slider²

### Parts/Components (Tech_Parts)
- Performance: 7 × slider
- Reliability: 10 × slider
- Torque support: 10 × year_exp × slider
- Same unit cost group as materials

### Techniques (Tech_Techniques)
- Performance: 6 × slider
- Unit cost: same group
- Design cost: 2200 × year_exp × slider²
- Manufacturing: 7 × slider

### Technology (Tech_Tech)
- Performance: 7 × slider
- Fuel: 6 × slider
- Unit cost: 40 × year_exp × (0.5 + slider²) — separate, more expensive
- Hurts reliability: 10 × (1-slider) penalty
- Design cost: 2500 × year_exp × (0.5 + slider²)

## Additional Features (Boolean)
- **Reverse Gear**: +weight, +comfort, -reliability, +design req
- **Overdrive**: +fuel (+6), +weight (+15), +unit cost, increases complexity
- **Limited Slip**: +performance (+4), +comfort (+10), +weight, +cost
- **Transaxle**: +performance (+2), -weight (-20), +unit cost (+65)

## Design Pace (DesignPace)
- Same formula as engine: (cost/5) + (cost × pace² × 4.5)
- < 0.5 = slower but fewer engineers
- > 0.5 = faster but more engineers

## Cost Structure
- **Unit cost**: Dominated by gearbox type costs, gear count, and design sliders (all squared)
- **Design cost**: Multiplied by gear count — more gears = proportionally more expensive
- **Hyper-slider**: average of all sliders to 4th power × 500 × 1.04^year
- Number of gears increases all costs linearly

## Key Strategy
- **Budget builds**: Low tech sliders, few gears, no extras
- **Dependability is expensive**: 45× unit cost + 8000× design cost per slider²
- **Performance is efficient**: Good rating boost with moderate cost
- **Torque input**: Must match or exceed engine torque — oversizing wastes cost
- **Gears**: More gears = better fuel/performance but proportionally higher design cost

## Extreme Value Warnings

### Hyper-Slider Penalty
- 9개 슬라이더 평균의 4제곱 × 500 × 1.04^year
- 슬라이더 수가 적어 각 슬라이더의 평균 기여가 큼 — 2~3개만 높여도 평균 상승

### 극단값 주의
- **de_depend > 0.7**: 유닛비용 45×year×slider² (최고가 슬라이더!) — 비용 폭발
- **de_comfort > 0.8**: 컴포트 40×slider는 좋지만 신뢰성 5×(1-slider) 패널티
- **Tech_Tech > 0.7**: 유닛비용 40×year×(0.5+slider²) + 신뢰성 10×(1-slider) 패널티
- **TorqueInput 과도하게 높음**: 75×year×slider 토크 용량이지만 무게 50×slider 급증

### 비용 효율 팁
- **de_performance**: 가장 효율적 — 10× 성능 + 체중 감소, 비용 20×year
- **Tech_Material + Tech_Parts**: 교차 혜택(성능+신뢰성) 대비 비용 합리적
- 기어 수 증가: 모든 비용을 선형으로 곱함 — 기어 추가 전 슬라이더 비용 먼저 확인
