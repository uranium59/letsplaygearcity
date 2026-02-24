# Engine Design Slider Reference

## Layout Sliders
### Bore & Stroke
- Bore and Stroke together determine **Displacement** (CC).
- Displacement = 0.7854 × (bore_cm)² × stroke_cm × cylinders
- Bore ↑ → displacement ↑ → torque ↑ → HP ↑, fuel economy ↓
- Stroke ↑ → displacement ↑ + torque ↑, but RPM ↓ (net HP may vary)
- Stroke also affects reliability: higher stroke_mm → lower reliability

### Length & Width (slider_length, slider_width)
- Control engine physical dimensions (inches)
- Higher = larger engine physically
- Affect weight: more length/width → heavier engine
- **Cost tradeoff**: Smaller (1-slider) values INCREASE unit cost
- In cost formulas these use (1-slider) — smaller engines are harder to make
- Design cost inversely affected: compact engines cost more to design

### Displacement (slider_displace)
- Calculated as average of bore and stroke sliders
- Strong impact on torque output and fuel consumption
- Cost relationship is **nonlinear** (slider^1.5, ^3, ^4.5, ^6 terms in unit cost)
- Higher displacement = significantly higher costs

### Weight (slider_weight)
- Higher weight slider = heavier engine
- Lower weight = better RPM (lighter reciprocating mass)
- **Lightweight penalty**: (1-weight) terms in cost — lighter engines cost MORE
- Design cost uses (1.01-weight)² — very expensive to make lightweight
- Tradeoff: heavy = cheap but slow, light = expensive but better RPM

## Performance Sliders
### RPM (slider_rpm / Revolutions)
- Directly increases engine RPM output
- Strong multiplier with year exponent (1.0105^year)
- Increases unit cost quadratically (slider²)
- Also increases finish time
- Hurts fuel economy and reliability

### Torque (slider_torq)
- Primary driver of torque output
- Uses (slider - 0.4) × 1.5 formula — below 0.4 reduces torque
- Increases unit cost quadratically
- Hurts fuel economy
- Hurts reliability (2×(1-slider_torq) term)

### Fuel Economy (slider_eco)
- Directly improves fuel consumption (MPG)
- Reduces torque output (penalty term)
- Increases design cost quadratically
- Moderate impact on unit cost
- Good cost-effectiveness for fuel-oriented designs

## Design Focus Sliders
### Performance Focus (slider_designperformance)
- Boosts torque and RPM
- Significant impact on design cost (12000 × slider² × year_exponent)
- Unit cost: 180 × slider² × year_exponent
- Hurts reliability: 3×(1-slider) reliability penalty
- High design requirement impact

### Fuel Economy Focus (slider_designfueleco)
- Boosts fuel consumption rating
- Reduces torque (14× penalty term)
- Design cost impact similar to performance focus
- Moderate unit cost impact (10 × slider²)

### Dependability Focus (slider_designdependability)
- Directly boosts reliability rating (6× weight in formula)
- Moderate unit cost: 50 × slider² × year_exponent
- Design cost: 1500 × (3.5 + slider²) — always has base cost
- Good cost-effectiveness for reliability improvement

### Design Pace (DesignPace)
- Controls development speed
- < 0.5: slower development, fewer engineers needed
- > 0.5: faster development, more engineers needed
- Design cost: (cost/5) + (cost × pace² × 4.5) — quadratic scaling
- Does NOT affect ratings — pure time/cost tradeoff

## Technology Sliders
### Materials (slider_materials)
- Reduces engine weight
- Improves reliability moderately
- Unit cost: 220 × slider² × 1.008^year (grouped with components/techniques)
- Boosts RPM slightly (25 × 1.01^year)
- **Best cost-effectiveness** among tech sliders for weight reduction

### Components (slider_compoenents)
- Improves reliability (3× weight)
- Improves smoothness (3× weight)
- Boosts RPM (25 × 1.01^year)
- Cost same group as materials
- Broad cross-cutting benefits

### Techniques (slider_techniques)
- Improves smoothness (3× weight)
- **Reduces design requirements** (negative 2× term)
- Unit cost in same group but with lower individual multiplier
- Best for reducing design complexity while maintaining quality

### Technology (slider_tech)
- Improves smoothness (2× weight)
- Strongest impact on unit cost: 170 × slider² × 1.008^year (separate term)
- Design cost: 3000 × slider² × 1.035^year
- Most expensive technology slider

## Cost Structure Summary
- **Unit cost**: Dominated by displacement (nonlinear), performance sliders (squared), and technology sliders (squared). Year exponents make everything more expensive over time.
- **Design cost**: Dominated by displacement, design focus combinations, and hyper-slider penalty
- **Hyper-slider penalty**: Average of all 13 sliders, raised to 4th power × 475 × 1.04^year. Penalizes raising ALL sliders uniformly.
- **Skill discount**: Higher design skill reduces costs (-cost/10 × skill/100)

## Sub-Components Impact
- Layout type determines cylinder arrangement, width, length multipliers
- Cylinder count affects cost, weight, smoothness (optimal at 8 cylinders)
- Fuel type affects RPM multiplier, fuel rating, power
- Induction type has strongest power rating impact (100× multiplier)
- Valve type affects RPM multiplier, power rating, smoothness

## Extreme Value Warnings

### Hyper-Slider Penalty (핵심!)
- 13개 슬라이더 평균을 4제곱 × 475 × 1.04^year → 유닛비용에 가산
- 평균 0.5 → 페널티 미미 (0.0625 × 475 = ~30)
- 평균 0.7 → 페널티 급증 (0.24 × 475 = ~114, 연도 지수 곱)
- 평균 0.85+ → 비용 폭발. 레이팅 향상보다 비용 증가가 훨씬 큼

### 개별 슬라이더 극단값 주의
- **slider_torq > 0.8**: 토크↑ 효과 대비 연비·신뢰성 패널티 급증
- **slider_rpm > 0.8**: RPM↑이지만 연비·신뢰성 악화 + 유닛비용 제곱 증가
- **slider_eco + slider_designfueleco 동시 최대**: 토크가 심각하게 저하
- **slider_designperformance > 0.8**: 설계비 12000×slider² 폭증, 신뢰성 3×(1-slider) 패널티
- **slider_tech > 0.8**: 유닛비용 170×slider² (최고가), 다른 Tech 슬라이더 대비 비효율

### 너무 낮은 슬라이더 주의
- **slider_weight < 0.15**: (1-weight)² 비용 폭등 — 경량화의 비용 대비 효과 감소
- **slider_length, slider_width < 0.2**: (1-slider) 비용 항이 지배 — 소형 엔진은 비쌈
- **slider_designdependability = 0**: 신뢰성에 6× 기여 완전 상실

### 비용 효율 최적 구간
- 대부분의 슬라이더: **0.2~0.6** 구간이 비용 대비 레이팅 효율 최적
- 0.6 이상부터 slider² 비용이 레이팅 향상을 압도하기 시작
- Tech 슬라이더는 예외적으로 0.5~0.7까지도 효율적 (교차 혜택 많음)
