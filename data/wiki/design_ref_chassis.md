# Chassis Design Slider Reference

## Frame Dimension Sliders
### Length (FD_Length)
- Controls wheelbase/chassis length in cm
- Formula: 145 + Global_Lengths × (2.3 × slider)
- Higher = longer chassis, more stable, more weight
- Affects width calculation (+20 × slider)
- Increases strength rating (+1× in formula)
- Hurts performance rating (-slider term)
- Higher cost: slider² × 1.2 in frame cost

### Width (FD_Width)
- Controls track width
- Formula: 100 + Global_Width × slider
- Higher = wider chassis, better stability
- Weight impact: Global_Weight/15 × (3.3 × slider)
- Hurts performance rating (-slider term)
- Design cost: slider² × 0.8 (cheaper than length)

### Height (FD_Height)
- Controls frame height
- Weight impact: Global_Weight/20 × (2 × slider)
- Strong strength impact: 5× multiplier in strength formula
- Increases finish time
- Design cost: slider² (standard)

### Weight (FD_Weight)
- Higher = heavier, cheaper frame
- Directly increases weight: Global_Weight × (1.25 × slider)
- Boosts comfort rating (+1× term)
- Boosts strength rating (+2× term)
- **Hurts performance rating (-2× term)**
- Cost: (1-slider)² — lighter is MORE expensive
- Design cost: 1-(slider² × 0.8)
- Finish time: appears in denominator — heavier = faster to design

### Engine Width & Length (FD_ENG_Width, FD_ENG_Length)
- Control maximum supported engine dimensions
- Higher = can fit larger engines
- Moderate weight impact
- Design cost: slider² (standard)
- Finish time: (slider/1.5) contribution

## Suspension Sliders
### Stability (SUS_Stability)
- Boosts comfort rating (4.5× weight with steering components)
- Hurts performance rating slightly (1-slider term)
- Moderate cost: slider² × 1.0 in suspension costs
- Finish time contribution

### Comfort (SUS_Comfort)
- Strong comfort rating impact (6× weight)
- Highest suspension cost multiplier: slider² × 1.25
- Good for luxury/touring vehicles

### Performance (SUS_Performance)
- Strong performance rating impact (4× weight)
- Moderate cost: slider² × 1.2
- Essential for sports/performance vehicles

### Braking (SUS_Braking)
- Boosts comfort and performance ratings
- Affects braking distance in vehicle calculations
- Lowest suspension cost: slider² × 0.75
- Good cost-effectiveness

### Durability (SUS_Durability)
- Primary durability rating driver (2.5× weight)
- Highest suspension cost: slider² × 1.35
- Also affects manufacturing requirements

## Design Emphasis Sliders
### Performance (DE_Performance)
- Boosts performance rating
- Reduces weight slightly
- Very high design cost: slider² × 10 × 14000 × year_exponent
- High design requirement impact

### Control (DE_Control)
- Boosts comfort rating
- Design cost: slider² × 10 (same category)
- Design requirement impact

### Strength (DE_Str)
- Boosts strength rating (1× weight)
- High design cost (same category multiplier)

### Dependability (DE_Depend)
- Boosts durability rating (0.5× weight)
- Also increases manufacturing requirements

## Technology Sliders
### Materials (TECH_Materials)
- Reduces chassis weight (negative weight term)
- Boosts performance slightly (2× in formula)
- Improves strength (2× weight)
- Unit cost: slider² × 1.25 in tech group
- Good cost-effectiveness for weight reduction

### Components (TECH_Compoenents)
- Improves comfort, performance, and strength ratings
- Unit cost: slider² × 1.15 in tech group
- Broad cross-cutting benefits

### Techniques (TECH_Techniques)
- Reduces weight (negative weight term)
- Reduces design requirements (negative term)
- Improves durability
- Lowest tech cost: slider² × 0.75
- **Best cost-effectiveness** — reduces design complexity

### Technology (TECH_Tech)
- Improves performance, strength
- Reduces durability (negative term in durability formula!)
- Higher cost: slider² × 1.25
- Increases design requirements

## Cost Structure
- **Manufacturing cost** = frame cost + suspension cost + tech cost, all × carPriceRate × random
- Frame cost dominated by dimension sliders (all squared)
- Suspension cost dominated by comfort and durability (highest multipliers)
- **Hyper-slider penalty**: average of all 19 sliders to 4th power × 450 × 1.045^year
- **Design cost**: separate formula for frame, suspension, design, tech sections

## Key Tradeoffs
- Weight ↔ Performance: heavy frame costs less but hurts handling
- Comfort ↔ Performance: suspension resources compete
- Strength ↔ Cost: strong frames are expensive
- TECH_Tech hurts durability while improving performance
- TECH_Techniques is always cost-effective (reduces design requirements)

## Extreme Value Warnings

### Hyper-Slider Penalty
- 19개 슬라이더 평균의 4제곱 × 450 × 1.045^year
- 슬라이더 수가 가장 많아 평균이 분산되기 쉬우나, 고르게 올리면 페널티 급증

### 극단값 주의
- **FD_Weight > 0.8**: 프레임 싸지만 성능 -2× 패널티가 지배적
- **FD_Weight < 0.15**: (1-weight)² 비용이 폭등 — 경량 프레임은 매우 비쌈
- **SUS_Comfort > 0.8**: 최고가 서스펜션(1.25× 배수) + 성능 저하
- **TECH_Tech > 0.7**: 성능·강도 향상이지만 내구성이 오히려 감소 (음수 항!)
- **DE_Performance + DE_Str 동시 높음**: 설계비 14000×year×slider² 각각 적용

### 비용 효율 팁
- **TECH_Techniques**: 설계 요구사항을 줄여줌 — 항상 효율적, 0.5~0.7 추천
- **FD_Weight 0.4~0.6**: 성능-비용 균형점
- 서스펜션: Braking이 가장 저렴 (0.75× 배수), Durability가 가장 비쌈 (1.35×)
