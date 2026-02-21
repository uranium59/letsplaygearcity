"""
GearCity Session Memory — 도메인 기반 세션 캐시
================================================
도메인별 TTL이 다른 세션 캐시. run_interactive() 세션 동안 유지되며,
연관 질문에서 기존 데이터를 재활용하고 Planner/Analyst에게 컨텍스트로 제공한다.

도메인:
    game_state     (TTL  3턴): GameInfo, PlayerInfo, CompanyList
    sales_market   (TTL  5턴): CarDistro, CitiesInfo, MonthlyFiscalsBreakdown, YearlyAutoBreakdown
    vehicle_design (TTL 12턴): CarInfo, EngineInfo, ChassisInfo, GearboxInfo, Researching
    factory        (TTL  6턴): FactoryInfo, CarManufactor
    contracts      (TTL  6턴): ContractRequests, ContractsGranted, ContractCustomers, ContractBids
    forecast       (TTL 60턴): (event_timeline.py 결과, DB 테이블 없음)
"""

from dataclasses import dataclass, field

# ── 도메인 설정 ─────────────────────────────────────────────────

DOMAIN_CONFIG: dict[str, dict] = {
    "game_state": {
        "ttl": 3,
        "tables": {"GameInfo", "PlayerInfo", "CompanyList"},
    },
    "sales_market": {
        "ttl": 5,
        "tables": {"CarDistro", "CitiesInfo", "MonthlyFiscalsBreakdown", "YearlyAutoBreakdown"},
    },
    "vehicle_design": {
        "ttl": 12,
        "tables": {"CarInfo", "EngineInfo", "ChassisInfo", "GearboxInfo", "Researching"},
    },
    "factory": {
        "ttl": 6,
        "tables": {"FactoryInfo", "CarManufactor"},
    },
    "contracts": {
        "ttl": 6,
        "tables": {"ContractRequests", "ContractsGranted", "ContractCustomers", "ContractBids"},
    },
    "forecast": {
        "ttl": 60,
        "tables": set(),
    },
}

# 역매핑: 테이블명 → 도메인
TABLE_TO_DOMAIN: dict[str, str] = {}
for _domain, _cfg in DOMAIN_CONFIG.items():
    for _table in _cfg["tables"]:
        TABLE_TO_DOMAIN[_table] = _domain


# ── DomainCache 데이터클래스 ────────────────────────────────────

@dataclass
class DomainCache:
    """단일 도메인의 캐시 엔트리."""
    domain: str
    data: str               # analyst_summary 또는 SQL 결과 텍스트
    turn_cached: int         # 캐시 시점의 게임 턴 (year*12 + month)
    ttl: int
    tables_used: set[str] = field(default_factory=set)

    def is_valid(self, current_turn: int) -> bool:
        """현재 턴 기준으로 캐시가 아직 유효한지 판정."""
        # turn이 0이면 턴 정보를 가져오지 못한 상태 — 만료 판정 스킵
        if current_turn == 0 or self.turn_cached == 0:
            return True
        return (current_turn - self.turn_cached) < self.ttl


# ── SessionMemory 클래스 ────────────────────────────────────────

class SessionMemory:
    """도메인별 TTL 캐시. 세션(run_interactive) 동안 유지."""

    def __init__(self):
        self._cache: dict[str, DomainCache] = {}
        self._current_turn: int = 0  # year*12 + month

    def update_turn(self, year: int, month: int):
        """현재 게임 턴 업데이트. 만료된 캐시 정리."""
        self._current_turn = year * 12 + month
        self._evict_expired()

    def get(self, domain: str) -> str | None:
        """유효한 캐시 데이터 반환. 만료/미존재 시 None."""
        entry = self._cache.get(domain)
        if entry is None:
            return None
        if not entry.is_valid(self._current_turn):
            del self._cache[domain]
            return None
        return entry.data

    def put(self, domain: str, data: str, tables_used: set[str] | None = None):
        """도메인 캐시 저장."""
        ttl = DOMAIN_CONFIG.get(domain, {}).get("ttl", 5)
        self._cache[domain] = DomainCache(
            domain=domain,
            data=data,
            turn_cached=self._current_turn,
            ttl=ttl,
            tables_used=tables_used or set(),
        )

    def get_relevant(self, tables: list[str]) -> dict[str, str]:
        """서브쿼리의 테이블 목록으로 관련 캐시 조회.
        Planner에게 "이미 알고 있는 정보"로 제공."""
        domains = self._classify_tables(tables)
        result: dict[str, str] = {}
        for domain in domains:
            cached = self.get(domain)
            if cached:
                result[domain] = cached
        return result

    def format_context(self) -> str:
        """전체 유효 캐시를 LLM 프롬프트용 텍스트로 포맷."""
        parts: list[str] = []
        for domain, entry in self._cache.items():
            if not entry.is_valid(self._current_turn):
                continue
            age = self._current_turn - entry.turn_cached if self._current_turn > 0 else 0
            # 데이터가 너무 길면 앞 500자까지만
            data_preview = entry.data if len(entry.data) <= 500 else entry.data[:500] + "\n...(truncated)"
            parts.append(f"[Cached: {domain} ({age}턴 전)]\n{data_preview}")
        return "\n\n".join(parts)

    def clear(self):
        """전체 캐시 초기화."""
        self._cache.clear()

    def _evict_expired(self):
        """TTL 만료 캐시 제거."""
        expired = [
            d for d, entry in self._cache.items()
            if not entry.is_valid(self._current_turn)
        ]
        for d in expired:
            del self._cache[d]

    def _classify_tables(self, tables: list[str]) -> set[str]:
        """테이블 목록 → 관련 도메인 집합."""
        domains: set[str] = set()
        for t in tables:
            domain = TABLE_TO_DOMAIN.get(t)
            if domain:
                domains.add(domain)
        return domains


# ── 모듈 수준 싱글톤 ────────────────────────────────────────────

_memory_instance: SessionMemory | None = None


def get_memory() -> SessionMemory:
    """싱글톤 SessionMemory 인스턴스 반환."""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = SessionMemory()
    return _memory_instance


def reset_memory():
    """세션 시작 시 호출. 인터랙티브 모드 시작 또는 단일 질문 모드."""
    global _memory_instance
    _memory_instance = SessionMemory()
