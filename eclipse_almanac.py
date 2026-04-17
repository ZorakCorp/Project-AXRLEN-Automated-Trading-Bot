"""
Persisted last global solar eclipse (sidereal Sun longitude at maximum) for Mars/Saturn transit triggers.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "almanac_state.json"


def _almanac_path() -> str:
    return os.getenv("ALMANAC_STATE_PATH", _DEFAULT_PATH).strip() or _DEFAULT_PATH


def load_almanac() -> Dict[str, Any]:
    path = _almanac_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Could not load almanac %s: %s", path, exc)
        return {}


def save_almanac(data: Dict[str, Any]) -> None:
    path = _almanac_path()
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _find_last_solar_eclipse_sidereal(jd_until: float) -> Optional[Tuple[float, float]]:
    """(jd_maximum, sun_sidereal_lon_at_max) for last global solar eclipse strictly before jd_until."""
    try:
        import swisseph as swe
    except ImportError:
        return None

    swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    ephe_path = os.getenv("SWISSEPH_EPHE_PATH", "").strip()
    if ephe_path:
        swe.set_ephe_path(ephe_path)

    ifltype = 0  # any solar eclipse (Swiss: SE_ECL_ANY?)
    eph_modes = [swe.FLG_SWIEPH]
    if hasattr(swe, "FLG_MOSEPH"):
        eph_modes.append(swe.FLG_MOSEPH)

    for eph in eph_modes:
        iflag = swe.FLG_SPEED | swe.FLG_SIDEREAL | eph
        try:
            res = swe.sol_eclipse_when_glob(jd_until, ifltype, iflag, 1)
        except Exception as exc:
            logger.debug("sol_eclipse_when_glob not available (%s): %s", eph, exc)
            continue

        tret = None
        if isinstance(res, tuple) and len(res) >= 2:
            second = res[1]
            if isinstance(second, (list, tuple)):
                tret = list(second)
            elif hasattr(second, "tolist"):
                tret = list(second.tolist())

        if not tret or len(tret) < 1:
            continue

        jd_max = float(tret[0])
        if jd_max <= 0 or jd_max >= jd_until:
            continue

        xx, serr = swe.calc_ut(jd_max, swe.SUN, iflag)
        try:
            sun_lon = float(xx[0]) % 360.0
        except (TypeError, IndexError, ValueError):
            logger.debug("Eclipse almanac: invalid Sun calc_ut xx=%r serr=%r", xx, serr)
            continue
        if not (0.0 <= sun_lon < 360.0) or sun_lon != sun_lon:
            logger.debug("Eclipse almanac: invalid Sun lon=%s serr=%r", sun_lon, serr)
            continue
        return jd_max, sun_lon

    return None


def refresh_eclipse_anchor_if_needed(jd_now: float) -> Dict[str, Any]:
    state = load_almanac()
    refresh_days = float(os.getenv("ECLIPSE_ALMANAC_REFRESH_DAYS", "30"))
    last_lookup = float(state.get("eclipse_lookup_jd") or 0.0)
    need = state.get("last_solar_eclipse_sidereal_lon") is None
    if last_lookup > 0:
        need = need or (jd_now - last_lookup) > refresh_days

    if not need:
        return state

    found = _find_last_solar_eclipse_sidereal(jd_now)
    state["eclipse_lookup_jd"] = jd_now
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    if found:
        jd_max, sun_lon = found
        state["last_solar_eclipse_jd"] = jd_max
        state["last_solar_eclipse_sidereal_lon"] = sun_lon
        logger.info(
            "Eclipse almanac: last solar max JD=%.6f sidereal Sun lon=%.4f°",
            jd_max,
            sun_lon,
        )
    else:
        logger.warning("Eclipse almanac: could not resolve last solar eclipse (Swiss API or ephemeris).")
        state.setdefault("last_solar_eclipse_sidereal_lon", None)
    save_almanac(state)
    return state


def get_charged_eclipse_degree() -> Optional[float]:
    st = load_almanac()
    v = st.get("last_solar_eclipse_sidereal_lon")
    if v is None:
        return None
    try:
        return float(v) % 360.0
    except Exception:
        return None
