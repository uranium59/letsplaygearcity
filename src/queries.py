"""
GearCity SQL Queries — 노드에서 사용하는 SQL 쿼리 문자열
=========================================================
"""

# ── 공통 서브쿼리 ────────────────────────────────────────────────

PLAYER_COMPANY_ID_SUBQUERY = (
    "SELECT Player_Data FROM PlayerInfo WHERE Player_Varible = 'Company_ID'"
)

# ── GameInfo 조회 ────────────────────────────────────────────────

CURRENT_YEAR_SQL = (
    "SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Year'"
)

CURRENT_TURN_SQL = (
    "SELECT GameInfo_Data FROM GameInfo WHERE GameInfo_Varible = 'Current_Turn'"
)

# ── design_advisor: 플레이어 차량+엔진+샤시+기어박스 JOIN ────────

DESIGN_VEHICLE_SQL = """\
SELECT
    c.Car_ID, c.Name, c.Trim, c.CarType, c.YearBuilt AS car_year,
    c.designcost AS car_designcost, c.ModAmount, c.ParentCarID,
    c.Engine_ID, c.Chassis_ID, c.Gearbox_ID,
    c.Spec_HP, c.Spec_Torque, c.Spec_RPM, c.Spec_Weight,
    c.Spec_TopSpeed, c.Spec_Fuel,
    c.Spec_AccellerationSix, c.Spec_AccellerationHund,
    c.Rating_Performance, c.Rating_Drivability, c.Rating_Luxury, c.Rating_Safety,
    e.bore, e.stroke, e.CylinderNumberForCalculations AS cylinders,
    e.hp AS engine_hp, e.torque AS engine_torque, e.rpm AS engine_rpm,
    e.weight AS engine_weight, e.size_cc, e.fuelmilage,
    e.yearbuilt AS engine_year, e.ModYear AS engine_mod_year, e.designcost AS engine_designcost,
    e.StaticenginePower, e.StaticengineFuelEco, e.StaticengineReliability, e.StaticRating_Smooth,
    e.enginePower, e.engineFuelEco, e.engineReliability, e.Rating_Smooth,
    ch.ChassisWeightKG, ch.ChassisLengthCM, ch.ChassisWidthCM,
    ch.YearBuilt AS chassis_year, ch.ModYear AS chassis_mod_year, ch.Design_Cost AS chassis_designcost,
    ch.StaticOverallStrength, ch.StaticOverallComfort, ch.StaticOverallPerformance, ch.StaticOverallDependabilty,
    ch.Overall_Strength, ch.Overall_Comfort, ch.Overall_Performance, ch.Overall_Dependabilty,
    g.Gears, g.GearboxType, g.LoRatio, g.HiRatio, g.MaxTorqueInput, g.Weight AS gearbox_weight,
    g.YearBuilt AS gearbox_year, g.ModYear AS gearbox_mod_year, g.Design_Cost AS gearbox_designcost,
    g.StaticPowerRating, g.StaticFuelRating, g.StaticPerformanceRating,
    g.StaticReliabiltyRating, g.StaticComfortRating,
    g.PowerRating, g.FuelRating, g.PerformanceRating, g.ReliabiltyRating, g.ComfortRating
FROM CarInfo c
JOIN EngineInfo e ON c.Engine_ID = e.Engine_ID
JOIN ChassisInfo ch ON c.Chassis_ID = ch.Chassis_ID
JOIN GearboxInfo g ON c.Gearbox_ID = g.Gearbox_ID
WHERE c.Company_ID = (""" + PLAYER_COMPANY_ID_SUBQUERY + """)
  AND c.Status = 0
LIMIT 20;"""

# ── design_advisor: 플레이어 기술 레벨 조회 ──────────────────────

TECH_SKILL_SQL = """\
SELECT SKILL_RND FROM CompanyList
WHERE ID = (""" + PLAYER_COMPANY_ID_SUBQUERY + """);"""

# ── design_advisor: 기술 가용성 쿼리 템플릿 ({skill}, {year} format) ──

AVAILABLE_COMPONENTS_SQL_TEMPLATE = """\
SELECT 'Gearbox' AS category, gc.Name, gc.SkillReq, gc.Year,
       gg.Name AS gears_name, gg.Gears, gg.SkillReq AS gears_skill, gg.Year AS gears_year
FROM GearboxComponents gc
CROSS JOIN GearsComponents gg
WHERE gc.SkillReq <= {skill} AND gc.Year <= {year}
  AND gg.SkillReq <= {skill} AND gg.Year <= {year}
  AND (gc.Death IS NULL OR gc.Death > {year})
  AND (gg.Death IS NULL OR gg.Death > {year})

UNION ALL

SELECT 'Layout' AS category, Name, SkillReq, Year, NULL, NULL, NULL, NULL
FROM LayoutComponents WHERE SkillReq <= {skill} AND Year <= {year} AND (Death IS NULL OR Death > {year})

UNION ALL

SELECT 'Induction' AS category, Name, SkillReq, Year, NULL, NULL, NULL, NULL
FROM InductionComponents WHERE SkillReq <= {skill} AND Year <= {year} AND (Death IS NULL OR Death > {year})

UNION ALL

SELECT 'Fuel' AS category, Name, SkillReq, Year, NULL, NULL, NULL, NULL
FROM FuelComponents WHERE SkillReq <= {skill} AND Year <= {year} AND (Death IS NULL OR Death > {year})

UNION ALL

SELECT 'Drivetrain' AS category, Name, SkillReq, Year, NULL, NULL, NULL, NULL
FROM DrivetrainComponents WHERE SkillReq <= {skill} AND Year <= {year} AND (Death IS NULL OR Death > {year})

UNION ALL

SELECT 'Suspension' AS category, Name, SkillReq, Year, NULL, NULL, NULL, NULL
FROM SuspensionComponents WHERE SkillReq <= {skill} AND Year <= {year} AND (Death IS NULL OR Death > {year})

UNION ALL

SELECT 'Valve' AS category, Name, SkillReq, Year, NULL, NULL, NULL, NULL
FROM ValveComponents WHERE SkillReq <= {skill} AND Year <= {year} AND (Death IS NULL OR Death > {year})

UNION ALL

SELECT 'Cylinder' AS category, Name, SkillReq, Year, NULL, NULL, NULL, NULL
FROM CylinderComponents WHERE SkillReq <= {skill} AND Year <= {year} AND (Death IS NULL OR Death > {year});"""

# ── forecast_advisor: 플레이어 자산 도시 조회 ────────────────────

PLAYER_CITY_IDS_SQL = """\
SELECT DISTINCT City_ID FROM FactoryInfo
WHERE Company_ID = (""" + PLAYER_COMPANY_ID_SUBQUERY + """)
UNION
SELECT DISTINCT City_ID FROM CarDistro
WHERE Company_ID = (""" + PLAYER_COMPANY_ID_SUBQUERY + """) AND Sold_This_Month > 0"""
