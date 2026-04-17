"""
Pancha-style exit heuristics and eclipse-degree trigger checks (Zophiel-inspired, simplified).
"""

from typing import Any, Dict, Tuple


def angular_distance_deg(a: float, b: float) -> float:
    d = abs((float(a) - float(b) + 360.0) % 360.0)
    return min(d, 360.0 - d)


def malefic_conjunct_moon_sidereal(sid: Dict[str, Dict[str, Any]]) -> bool:
    moon_sign = (sid.get("Moon") or {}).get("sign")
    if not moon_sign:
        return False
    for p in ("Mars", "Saturn", "Rahu", "Ketu"):
        if (sid.get(p) or {}).get("sign") == moon_sign:
            return True
    return False


def malefic_near_moon_longitude(sid: Dict[str, Dict[str, Any]], orb_deg: float = 12.0) -> bool:
    moon_lon = float((sid.get("Moon") or {}).get("longitude") or 0.0)
    for p in ("Mars", "Saturn", "Rahu"):
        lon = float((sid.get(p) or {}).get("longitude") or 0.0)
        if angular_distance_deg(moon_lon, lon) <= orb_deg:
            return True
    return False


def pancha_vedha_exit_long(
    sid: Dict[str, Dict[str, Any]],
    vedic_snapshot: Dict[str, Any],
    vedha: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """
    Force-exit heuristic for longs when multiple stress vectors align (no name-letter: use samasaptaka as 4th axis).

    Fires when ALL of:
    - bad tithi (Ashtami / Chaturdashi family),
    - malefic conjunct Moon by sign OR within orb of Moon longitude,
    - mars_saturn_vedha OR mars_saturn_samasaptaka,
    - Rahu intensified / fixed-axis stress (vedha flag).
    """
    tithi = int(vedic_snapshot.get("tithi") or 0)
    bad_tithi = tithi in {8, 14, 15, 23, 29, 30}
    mal_sign = malefic_conjunct_moon_sidereal(sid)
    mal_lon = malefic_near_moon_longitude(sid, orb_deg=14.0)
    mal_moon = mal_sign or mal_lon
    ms_stress = bool(vedha.get("mars_saturn_vedha") or vedic_snapshot.get("mars_saturn_samasaptaka_approx"))
    rahu_stress = bool(vedha.get("rahu_intensified_fixed"))

    detail = {
        "bad_tithi": bad_tithi,
        "malefic_moon_pressure": mal_moon,
        "mars_saturn_stress": ms_stress,
        "rahu_fixed_stress": rahu_stress,
        "tithi": tithi,
    }
    fire = bool(bad_tithi and mal_moon and ms_stress and rahu_stress)
    return fire, detail


def eclipse_degree_trigger_active(
    sid: Dict[str, Dict[str, Any]],
    eclipse_sidereal_lon: float | None,
    orb_deg: float = 1.25,
) -> Tuple[bool, Dict[str, Any]]:
    """True when Mars or Saturn sidereal longitude crosses stored solar-eclipse degree within tight orb."""
    if eclipse_sidereal_lon is None:
        return False, {"reason": "no_eclipse_degree_cached"}
    ecl = float(eclipse_sidereal_lon) % 360.0
    mars = float((sid.get("Mars") or {}).get("longitude") or 0.0)
    sat = float((sid.get("Saturn") or {}).get("longitude") or 0.0)
    dm = angular_distance_deg(mars, ecl)
    ds = angular_distance_deg(sat, ecl)
    hit_mars = dm <= orb_deg
    hit_sat = ds <= orb_deg
    return bool(hit_mars or hit_sat), {
        "eclipse_sidereal_lon": ecl,
        "mars_dist": round(dm, 4),
        "saturn_dist": round(ds, 4),
        "hit_mars": hit_mars,
        "hit_saturn": hit_sat,
        "orb_deg": orb_deg,
    }
