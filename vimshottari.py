"""
Vimshottari mahadasha / antardasha from Moon's sidereal nakshatra at birth (standard 120-year cycle).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# Three nakshatras (13°20' each) per mahadasha lord, in order:
LORDS: Tuple[str, ...] = ("Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury")
YEARS: Tuple[float, ...] = (7.0, 20.0, 6.0, 10.0, 7.0, 18.0, 16.0, 19.0, 17.0)
ARC = 360.0 / 27.0
CYCLE_TOTAL = sum(YEARS)


def _lord_index_from_moon_sidereal(moon_lon: float) -> Tuple[int, float, float]:
    """Mahadasha index (0..8), years elapsed within it at birth, years remaining in it."""
    lon = float(moon_lon) % 360.0
    nak = int(lon // ARC) % 27
    L = nak // 3
    block_start = L * 3 * ARC
    span = 3.0 * ARC
    pos_in_block = lon - block_start
    if pos_in_block < 0:
        pos_in_block += 360.0
    frac = pos_in_block / span if span > 0 else 0.0
    years_elapsed = frac * YEARS[L]
    years_remain = YEARS[L] - years_elapsed
    return L, years_elapsed, years_remain


def _antar_at(maha_idx: int, years_into_maha: float) -> str:
    """Antardasha lord within current mahadasha (BPHS-style partition of the maha)."""
    order: List[int] = [(maha_idx + k) % 9 for k in range(9)]
    y_m = YEARS[maha_idx]
    # Each antar length proportional to its full-cycle share, scaled to this maha's length.
    parts = [YEARS[i] / CYCLE_TOTAL * y_m for i in order]
    acc = 0.0
    for k in range(9):
        if years_into_maha < acc + parts[k] - 1e-12:
            return LORDS[order[k]]
        acc += parts[k]
    return LORDS[order[-1]]


def vimshottari_state(moon_sidereal_lon_birth: float, birth_jd: float, now_jd: float) -> Dict[str, object]:
    """Current mahadasha / antar from birth Moon sidereal longitude and Julian days (UT)."""
    L, years_elapsed_at_birth, years_remain_in_L = _lord_index_from_moon_sidereal(moon_sidereal_lon_birth)
    elapsed_years = (float(now_jd) - float(birth_jd)) / 365.2425
    t = float(elapsed_years)

    if t <= years_remain_in_L:
        maha_idx = L
        years_into_maha = years_elapsed_at_birth + t
    else:
        t -= years_remain_in_L
        idx = (L + 1) % 9
        while t > YEARS[idx] + 1e-12:
            t -= YEARS[idx]
            idx = (idx + 1) % 9
        maha_idx = idx
        years_into_maha = t

    antar = _antar_at(maha_idx, years_into_maha)
    return {
        "mahadasha": LORDS[maha_idx],
        "antar": antar,
        "mahadasha_years_total": YEARS[maha_idx],
        "years_into_mahadasha": round(float(years_into_maha), 4),
        "vimshottari_note": "Vimshottari from Moon nakshatra at birth (UT); antar partitioned proportionally.",
    }
