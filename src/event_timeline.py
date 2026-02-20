"""
GearCity Event Timeline — War & Economic Forecast Module
==========================================================
TurnEvents.xml에서 추출한 전쟁/경제 타임라인 데이터를 로드하고,
현재 게임 연도 기준으로 미래 이벤트 예측 및 플레이어 자산 위험 분석을 제공한다.

Data source: data/turn_events_timeline.json (parse_turn_events.py로 생성)
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

TIMELINE_PATH = Path(__file__).resolve().parent.parent / "data" / "turn_events_timeline.json"

# Gov status labels
GOV_LABELS = {
    "TOTAL_WAR": "총력전 (판매 불가, 공장 파괴 위험)",
    "WAR": "전쟁 (판매 불가)",
    "LIMITED": "제한 (판매 50% 감소)",
    "STABLE": "안정",
}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class WarPeriod:
    """도시별 전쟁 기간."""
    city_id: int
    city_name: str
    country: str
    start_year: int
    start_month: int
    end_year: int
    end_month: int
    severity: str  # TOTAL_WAR, WAR, LIMITED

    @property
    def duration_years(self) -> float:
        return (self.end_year - self.start_year) + (self.end_month - self.start_month) / 12

    @property
    def severity_label(self) -> str:
        return GOV_LABELS.get(self.severity, self.severity)

    def __str__(self) -> str:
        sm = MONTHS[self.start_month - 1] if 1 <= self.start_month <= 12 else str(self.start_month)
        em = MONTHS[self.end_month - 1] if 1 <= self.end_month <= 12 else str(self.end_month)
        return (f"{self.city_name} ({self.country}): "
                f"{self.start_year} {sm} ~ {self.end_year} {em} [{self.severity}]")


@dataclass
class EconomicEvent:
    """경제 이벤트 (침체, 유가 급등, 금리 급등 등)."""
    event_type: str  # downturn, gas_spike, interest_spike, stock_crash
    start_year: int
    end_year: int
    peak_value: float
    description: str


@dataclass
class CityRisk:
    """도시별 미래 전쟁 위험 분석."""
    city_id: int
    city_name: str
    country: str
    upcoming_wars: list[WarPeriod] = field(default_factory=list)
    risk_level: str = "SAFE"  # SAFE, LOW, MEDIUM, HIGH, CRITICAL
    years_until_conflict: float = 999.0


class EventTimeline:
    """TurnEvents 타임라인 데이터 관리자."""

    def __init__(self, timeline_path: Path = TIMELINE_PATH):
        if not timeline_path.exists():
            raise FileNotFoundError(f"Timeline data not found: {timeline_path}")
        with open(timeline_path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

        self._war_periods: list[WarPeriod] = []
        self._economic_events: list[EconomicEvent] = []
        self._safe_havens: list[dict] = self._data.get("safe_havens", [])

        self._parse_war_timeline()
        self._parse_economic_events()

    def _parse_war_timeline(self):
        """war_timeline JSON → WarPeriod 리스트."""
        for cid_str, info in self._data.get("war_timeline", {}).items():
            cid = int(cid_str)
            for p in info.get("periods", []):
                # periods are [start_year, start_month, end_year, end_month, severity]
                self._war_periods.append(WarPeriod(
                    city_id=cid,
                    city_name=info["name"],
                    country=info["country"],
                    start_year=p[0],
                    start_month=p[1],
                    end_year=p[2],
                    end_month=p[3],
                    severity=p[4],
                ))

    def _parse_economic_events(self):
        """economic_timeline JSON → EconomicEvent 리스트."""
        econ = self._data.get("economic_timeline", {})
        years = sorted(int(y) for y in econ.keys())
        if not years:
            return

        # Detect downturns (buyrate < 0.90)
        self._detect_threshold_events(
            econ, years, "buyrate", 0.90, "below", "downturn",
            lambda v: f"수요 침체 (buyrate 최저 {v:.4f})",
        )
        # Detect gas spikes (gas > 2.0)
        self._detect_threshold_events(
            econ, years, "gas", 2.0, "above", "gas_spike",
            lambda v: f"유가 급등 (gas 최고 {v:.4f})",
        )
        # Detect interest spikes (interest > 1.06)
        self._detect_threshold_events(
            econ, years, "interest", 1.06, "above", "interest_spike",
            lambda v: f"금리 급등 (interest 최고 {v:.4f})",
        )
        # Detect stock crashes (stockrate < 0.90)
        self._detect_threshold_events(
            econ, years, "stockrate", 0.90, "below", "stock_crash",
            lambda v: f"주식시장 폭락 (stockrate 최저 {v:.4f})",
        )

    def _detect_threshold_events(
        self, econ, years, key, threshold, direction, event_type, desc_fn
    ):
        in_event = False
        start_y = None
        peak = None

        for y in years:
            val = econ.get(str(y), {}).get(key)
            if val is None:
                continue

            triggered = (val < threshold) if direction == "below" else (val > threshold)

            if triggered and not in_event:
                in_event = True
                start_y = y
                peak = val
            elif triggered and in_event:
                if direction == "below":
                    peak = min(peak, val)
                else:
                    peak = max(peak, val)
            elif not triggered and in_event:
                self._economic_events.append(EconomicEvent(
                    event_type=event_type,
                    start_year=start_y,
                    end_year=y - 1,
                    peak_value=peak,
                    description=desc_fn(peak),
                ))
                in_event = False

        if in_event:
            self._economic_events.append(EconomicEvent(
                event_type=event_type,
                start_year=start_y,
                end_year=years[-1],
                peak_value=peak,
                description=desc_fn(peak),
            ))

    # ── Public API ──────────────────────────────────────────────

    def get_upcoming_wars(
        self, current_year: int, lookahead: int = 15
    ) -> list[WarPeriod]:
        """현재 연도 이후 lookahead년 내에 시작되는 전쟁 기간."""
        end_year = current_year + lookahead
        results = []
        for wp in self._war_periods:
            # 아직 시작 안 한 전쟁 또는 현재 진행 중인 전쟁
            if wp.start_year >= current_year and wp.start_year <= end_year:
                results.append(wp)
            elif wp.start_year < current_year and wp.end_year >= current_year:
                results.append(wp)  # 현재 진행 중
        results.sort(key=lambda w: (w.start_year, w.start_month, w.city_name))
        return results

    def get_active_wars(self, current_year: int, current_month: int = 1) -> list[WarPeriod]:
        """현재 진행 중인 전쟁."""
        results = []
        for wp in self._war_periods:
            start = wp.start_year * 12 + wp.start_month
            end = wp.end_year * 12 + wp.end_month
            now = current_year * 12 + current_month
            if start <= now <= end:
                results.append(wp)
        results.sort(key=lambda w: w.city_name)
        return results

    def get_upcoming_economic_events(
        self, current_year: int, lookahead: int = 15
    ) -> list[EconomicEvent]:
        """현재 연도 이후 lookahead년 내의 경제 이벤트."""
        end_year = current_year + lookahead
        results = []
        for ev in self._economic_events:
            if ev.start_year >= current_year and ev.start_year <= end_year:
                results.append(ev)
            elif ev.start_year < current_year and ev.end_year >= current_year:
                results.append(ev)  # 현재 진행 중
        results.sort(key=lambda e: e.start_year)
        return results

    def get_economic_snapshot(self, year: int) -> dict:
        """특정 연도의 경제 지표."""
        return self._data.get("economic_timeline", {}).get(str(year), {})

    def check_city_war_risk(
        self, city_id: int, current_year: int, lookahead: int = 15
    ) -> CityRisk:
        """특정 도시의 미래 전쟁 위험 분석."""
        # Find city info
        war_info = self._data.get("war_timeline", {}).get(str(city_id))
        if war_info:
            city_name = war_info["name"]
            country = war_info["country"]
        else:
            # Check safe havens
            for sh in self._safe_havens:
                if sh["id"] == city_id:
                    return CityRisk(
                        city_id=city_id,
                        city_name=sh["name"],
                        country=sh["country"],
                        risk_level="SAFE",
                        years_until_conflict=999.0,
                    )
            return CityRisk(city_id=city_id, city_name=f"Unknown_{city_id}",
                           country="Unknown", risk_level="SAFE")

        upcoming = []
        for wp in self._war_periods:
            if wp.city_id != city_id:
                continue
            # Future or ongoing
            if wp.end_year >= current_year and wp.start_year <= current_year + lookahead:
                upcoming.append(wp)

        if not upcoming:
            return CityRisk(
                city_id=city_id, city_name=city_name, country=country,
                risk_level="SAFE", years_until_conflict=999.0,
            )

        # Calculate years until next conflict
        future_starts = [wp.start_year + wp.start_month / 12
                        for wp in upcoming if wp.start_year >= current_year]
        current_time = current_year + 0.5  # mid-year estimate
        years_until = min(s - current_time for s in future_starts) if future_starts else 0.0

        # Check if currently in conflict
        active = [wp for wp in upcoming
                  if wp.start_year * 12 + wp.start_month <= current_year * 12 + 6
                  and wp.end_year * 12 + wp.end_month >= current_year * 12 + 1]

        worst_severity = "LIMITED"
        for wp in upcoming:
            if wp.severity == "TOTAL_WAR":
                worst_severity = "TOTAL_WAR"
                break
            elif wp.severity == "WAR" and worst_severity != "TOTAL_WAR":
                worst_severity = "WAR"

        if active:
            risk = "CRITICAL"
            years_until = 0.0
        elif years_until <= 2:
            risk = "HIGH"
        elif years_until <= 5:
            risk = "MEDIUM"
        elif years_until <= 10:
            risk = "LOW"
        else:
            risk = "SAFE"

        return CityRisk(
            city_id=city_id, city_name=city_name, country=country,
            upcoming_wars=upcoming, risk_level=risk,
            years_until_conflict=max(0.0, years_until),
        )

    def check_player_asset_risks(
        self, city_ids: list[int], current_year: int, lookahead: int = 15
    ) -> list[CityRisk]:
        """플레이어가 자산을 보유한 도시들의 전쟁 위험 일괄 분석."""
        results = []
        for cid in set(city_ids):
            risk = self.check_city_war_risk(cid, current_year, lookahead)
            results.append(risk)
        # 위험도 순 정렬 (CRITICAL > HIGH > MEDIUM > LOW > SAFE)
        risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "SAFE": 4}
        results.sort(key=lambda r: (risk_order.get(r.risk_level, 5), r.years_until_conflict))
        return results

    def format_forecast_summary(
        self, current_year: int, lookahead: int = 15
    ) -> str:
        """LLM 프롬프트에 주입할 축약된 예측 요약."""
        lines = [f"=== EVENT FORECAST (Year {current_year}, next {lookahead} years) ==="]

        # Economic events
        econ_events = self.get_upcoming_economic_events(current_year, lookahead)
        if econ_events:
            lines.append("\n## Upcoming Economic Events")
            for ev in econ_events:
                status = "ACTIVE NOW" if ev.start_year <= current_year else f"starts {ev.start_year}"
                span = f"{ev.start_year}-{ev.end_year}" if ev.start_year != ev.end_year else str(ev.start_year)
                lines.append(f"  [{span}] {ev.description} ({status})")
        else:
            lines.append("\n## Economic Outlook: Stable (no major events expected)")

        # War events - group by country
        wars = self.get_upcoming_wars(current_year, lookahead)
        if wars:
            lines.append("\n## Upcoming/Active Wars")
            from collections import defaultdict
            by_country: dict[str, list[WarPeriod]] = defaultdict(list)
            for wp in wars:
                by_country[wp.country].append(wp)

            for country in sorted(by_country.keys()):
                wps = by_country[country]
                cities = sorted(set(wp.city_name for wp in wps))
                worst = max(wps, key=lambda w: {"TOTAL_WAR": 3, "WAR": 2, "LIMITED": 1}.get(w.severity, 0))
                min_start = min(wp.start_year for wp in wps)
                max_end = max(wp.end_year for wp in wps)
                active = any(wp.start_year <= current_year <= wp.end_year for wp in wps)
                status = "ACTIVE" if active else f"starts {min_start}"
                city_str = ", ".join(cities[:5])
                if len(cities) > 5:
                    city_str += f" +{len(cities)-5} more"
                lines.append(
                    f"  {country} [{min_start}-{max_end}] {worst.severity} ({status})"
                    f"\n    Cities: {city_str}"
                )
        else:
            lines.append("\n## War Outlook: Peaceful (no conflicts expected)")

        # Safe havens
        if self._safe_havens:
            lines.append("\n## Permanent Safe Havens (never at war)")
            for sh in self._safe_havens:
                lines.append(f"  {sh['name']} ({sh['country']})")

        return "\n".join(lines)

    def format_asset_risk_report(
        self, risks: list[CityRisk], current_year: int
    ) -> str:
        """자산 위험 분석 결과를 LLM 프롬프트용 텍스트로 포맷."""
        if not risks:
            return "(플레이어 자산 위치 정보 없음)"

        lines = [f"=== PLAYER ASSET WAR RISK ANALYSIS (Year {current_year}) ==="]
        risk_icons = {"CRITICAL": "!!!", "HIGH": "!! ", "MEDIUM": "!  ", "LOW": ".  ", "SAFE": "   "}

        at_risk = [r for r in risks if r.risk_level != "SAFE"]
        safe = [r for r in risks if r.risk_level == "SAFE"]

        if at_risk:
            lines.append("\n## AT-RISK LOCATIONS")
            for r in at_risk:
                icon = risk_icons.get(r.risk_level, "   ")
                if r.risk_level == "CRITICAL":
                    lines.append(f"  {icon} {r.city_name} ({r.country}): CURRENTLY IN CONFLICT")
                else:
                    lines.append(
                        f"  {icon} {r.city_name} ({r.country}): {r.risk_level} "
                        f"({r.years_until_conflict:.0f} years until conflict)"
                    )
                for wp in r.upcoming_wars[:3]:
                    sm = MONTHS[wp.start_month - 1] if 1 <= wp.start_month <= 12 else str(wp.start_month)
                    em = MONTHS[wp.end_month - 1] if 1 <= wp.end_month <= 12 else str(wp.end_month)
                    lines.append(
                        f"       → {wp.start_year} {sm} ~ {wp.end_year} {em}: "
                        f"{wp.severity} ({wp.severity_label})"
                    )
        else:
            lines.append("\n## All player locations are SAFE from future conflicts")

        if safe:
            safe_names = [f"{r.city_name}" for r in safe]
            lines.append(f"\n## Safe locations: {', '.join(safe_names)}")

        return "\n".join(lines)


# ── Module-level singleton ────────────────────────────────────

_timeline_instance: EventTimeline | None = None


def get_timeline() -> EventTimeline:
    """싱글톤 EventTimeline 인스턴스 반환."""
    global _timeline_instance
    if _timeline_instance is None:
        _timeline_instance = EventTimeline()
    return _timeline_instance
