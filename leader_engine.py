from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class LeaderProfile:
    name: str
    role: str
    country: str
    birth_date: str
    birth_time: str
    birth_place: str


class LeaderDashaEngine:
    """
    Optional natal Vimshottari-style context for named profiles.

    Default is empty for the ETH bot path (no synthetic “OPEC chair” dasha).
    Pass real ``LeaderProfile`` rows if you want this layer active.
    """

    def __init__(self, leaders: Optional[List[LeaderProfile]] = None):
        self.leaders = leaders or []

    def compute_dasha(self, leader: LeaderProfile) -> Dict[str, str]:
        # Placeholder implementation. Replace with a real Vimshottari Dasha calculator.
        current_year = datetime.now(timezone.utc).year
        hash_value = hash(leader.name) % 4
        mahadasha = ["Mars", "Saturn", "Jupiter", "Rahu"][hash_value]
        antar = ["Moon", "Mercury", "Venus", "Ketu"][current_year % 4]
        pratyaantar = ["Mars", "Saturn", "Ketu", "Venus"][(current_year + hash_value) % 4]
        return {
            "leader": leader.name,
            "country": leader.country,
            "role": leader.role,
            "mahadasha": mahadasha,
            "antar": antar,
            "pratyaantar": pratyaantar,
            "transition_window_hours": 72,
            "note": "Heuristic dasha labels for optional leader profiles; not a full Vimshottari engine.",
        }

    def get_leader_contexts(self) -> List[Dict[str, str]]:
        return [self.compute_dasha(leader) for leader in self.leaders]
