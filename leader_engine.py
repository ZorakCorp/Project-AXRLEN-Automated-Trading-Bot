from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ephemeris_engine import EphemerisEngine
from vimshottari import vimshottari_state


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

    @staticmethod
    def _parse_utc_birth(leader: LeaderProfile) -> datetime:
        raw = f"{leader.birth_date.strip()} {(leader.birth_time or '12:00').strip()}"
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return datetime.strptime(leader.birth_date.strip(), "%Y-%m-%d").replace(
            hour=12, minute=0, second=0, tzinfo=timezone.utc
        )

    def compute_dasha(self, leader: LeaderProfile) -> Dict[str, object]:
        birth = self._parse_utc_birth(leader)
        eng = EphemerisEngine()
        eng.current_date = birth
        sid = eng.get_sidereal_positions()
        moon_lon = float((sid.get("Moon") or {}).get("longitude") or 0.0)
        birth_jd = EphemerisEngine._julian_day(birth)
        now_jd = EphemerisEngine._julian_day(datetime.now(timezone.utc))
        vs = vimshottari_state(moon_lon, birth_jd, now_jd)
        return {
            "leader": leader.name,
            "country": leader.country,
            "role": leader.role,
            "birth_jd_ut": birth_jd,
            "moon_sidereal_deg_birth": moon_lon,
            "mahadasha": vs["mahadasha"],
            "antar": vs["antar"],
            "pratyaantar": "",
            "years_into_mahadasha": vs["years_into_mahadasha"],
            "transition_window_hours": 72,
            "note": str(vs.get("vimshottari_note", "")),
        }

    def get_leader_contexts(self) -> List[Dict[str, str]]:
        return [self.compute_dasha(leader) for leader in self.leaders]
