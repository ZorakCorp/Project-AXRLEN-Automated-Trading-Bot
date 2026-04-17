import logging
import os
from datetime import datetime, timedelta, timezone
from math import atan2, cos, floor, pi, sin, sqrt
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

NAKSHATRAS: Tuple[str, ...] = (
    "Ashwini",
    "Bharani",
    "Krittika",
    "Rohini",
    "Mrigashira",
    "Ardra",
    "Punarvasu",
    "Pushya",
    "Ashlesha",
    "Magha",
    "Purva Phalguni",
    "Uttara Phalguni",
    "Hasta",
    "Chitra",
    "Swati",
    "Vishakha",
    "Anuradha",
    "Jyeshtha",
    "Mula",
    "Purva Ashadha",
    "Uttara Ashadha",
    "Shravana",
    "Dhanishta",
    "Shatabhisha",
    "Purva Bhadrapada",
    "Uttara Bhadrapada",
    "Revati",
)

# Vedic day hora cycle (repeats every 7 hours from a day-lord anchor).
_HORA_CYCLE: Tuple[str, ...] = ("Sun", "Venus", "Mercury", "Moon", "Saturn", "Jupiter", "Mars")
# Weekday starting Monday=0 in Python: first hora after sunrise is ruled by:
_DAY_START_LORD: Tuple[str, ...] = ("Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Sun")


class EphemerisEngine:
    def __init__(self):
        self.current_date = datetime.now(timezone.utc)

    @staticmethod
    def _wrap360(deg: float) -> float:
        x = deg % 360.0
        return x + 360.0 if x < 0 else x

    @staticmethod
    def _deg_to_rad(deg: float) -> float:
        return deg * pi / 180.0

    @staticmethod
    def _rad_to_deg(rad: float) -> float:
        return rad * 180.0 / pi

    @staticmethod
    def _julian_day(dt: datetime) -> float:
        """
        Julian Day for UTC datetime.
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        y = dt.year
        m = dt.month
        d = dt.day + (dt.hour + (dt.minute + dt.second / 60.0) / 60.0) / 24.0
        if m <= 2:
            y -= 1
            m += 12
        a = floor(y / 100)
        b = 2 - a + floor(a / 4)
        jd = floor(365.25 * (y + 4716)) + floor(30.6001 * (m + 1)) + d + b - 1524.5
        return float(jd)

    @staticmethod
    def _sign_from_longitude(lon_deg: float) -> str:
        signs = [
            "Aries",
            "Taurus",
            "Gemini",
            "Cancer",
            "Leo",
            "Virgo",
            "Libra",
            "Scorpio",
            "Sagittarius",
            "Capricorn",
            "Aquarius",
            "Pisces",
        ]
        idx = int(floor((lon_deg % 360.0) / 30.0)) % 12
        return signs[idx]

    def _sun_ecliptic_longitude(self, jd: float) -> float:
        """
        Approximate apparent ecliptic longitude of the Sun (degrees).
        Good enough for dynamic day-to-day changes without external deps.
        """
        n = jd - 2451545.0
        L = self._wrap360(280.460 + 0.9856474 * n)
        g = self._wrap360(357.528 + 0.9856003 * n)
        g_rad = self._deg_to_rad(g)
        lam = L + 1.915 * sin(g_rad) + 0.020 * sin(2 * g_rad)
        return self._wrap360(lam)

    def _moon_ecliptic_longitude(self, jd: float) -> float:
        """
        Approximate ecliptic longitude of the Moon (degrees).
        """
        n = jd - 2451545.0
        L0 = self._wrap360(218.316 + 13.176396 * n)  # mean longitude
        Mm = self._wrap360(134.963 + 13.064993 * n)  # mean anomaly
        Ms = self._wrap360(357.529 + 0.9856003 * n)  # sun anomaly
        D = self._wrap360(297.850 + 12.190749 * n)   # mean elongation

        Mm_r = self._deg_to_rad(Mm)
        Ms_r = self._deg_to_rad(Ms)
        D_r = self._deg_to_rad(D)

        # Main periodic terms (very reduced series)
        lon = (
            L0
            + 6.289 * sin(Mm_r)
            + 1.274 * sin(2 * D_r - Mm_r)
            + 0.658 * sin(2 * D_r)
            + 0.214 * sin(2 * Mm_r)
            + 0.110 * sin(D_r)
            - 0.186 * sin(Ms_r)
        )
        return self._wrap360(lon)

    def _planet_geocentric_longitude(self, jd: float, *, planet: str) -> float:
        """
        Lightweight geocentric ecliptic longitude approximation for classical planets.
        Uses simplified orbital elements (Schlyter-style) for dynamic motion and retrograde.
        Accuracy is limited; intended to be *non-static and time-varying* without deps.
        """
        # days from J2000
        d = jd - 2451543.5

        # Orbital elements for J2000 with daily rates (degrees unless stated).
        # Source: well-known public-domain approximations (Paul Schlyter).
        elements = {
            "Mercury": dict(N=(48.3313, 3.24587e-5), i=(7.0047, 5.00e-8), w=(29.1241, 1.01444e-5), a=(0.387098, 0.0), e=(0.205635, 5.59e-10), M=(168.6562, 4.0923344368)),
            "Venus":   dict(N=(76.6799, 2.46590e-5), i=(3.3946, 2.75e-8), w=(54.8910, 1.38374e-5), a=(0.723330, 0.0), e=(0.006773, -1.302e-9), M=(48.0052, 1.6021302244)),
            "Mars":    dict(N=(49.5574, 2.11081e-5), i=(1.8497, -1.78e-8), w=(286.5016, 2.92961e-5), a=(1.523688, 0.0), e=(0.093405, 2.516e-9), M=(18.6021, 0.5240207766)),
            "Jupiter": dict(N=(100.4542, 2.76854e-5), i=(1.3030, -1.557e-7), w=(273.8777, 1.64505e-5), a=(5.20256, 0.0), e=(0.048498, 4.469e-9), M=(19.8950, 0.0830853001)),
            "Saturn":  dict(N=(113.6634, 2.38980e-5), i=(2.4886, -1.081e-7), w=(339.3939, 2.97661e-5), a=(9.55475, 0.0), e=(0.055546, -9.499e-9), M=(316.9670, 0.0334442282)),
        }
        if planet not in elements:
            raise ValueError(f"Unsupported planet: {planet}")

        def el(key: str) -> float:
            base, rate = elements[planet][key]
            return float(base + rate * d)

        N = self._deg_to_rad(self._wrap360(el("N")))
        i = self._deg_to_rad(el("i"))
        w = self._deg_to_rad(self._wrap360(el("w")))
        a = float(elements[planet]["a"][0])
        e = float(el("e"))
        M = self._deg_to_rad(self._wrap360(el("M")))

        # Solve Kepler's equation for eccentric anomaly E (iterative).
        E = M
        for _ in range(8):
            E = E - (E - e * sin(E) - M) / max(1.0 - e * cos(E), 1e-9)

        # True anomaly v and radius r
        xv = a * (cos(E) - e)
        yv = a * (sqrt(max(1.0 - e * e, 1e-12)) * sin(E))
        v = atan2(yv, xv)
        r = sqrt(xv * xv + yv * yv)

        # Heliocentric ecliptic coordinates
        xh = r * (cos(N) * cos(v + w) - sin(N) * sin(v + w) * cos(i))
        yh = r * (sin(N) * cos(v + w) + cos(N) * sin(v + w) * cos(i))
        zh = r * (sin(v + w) * sin(i))

        # Earth heliocentric (needed to convert to geocentric)
        # Earth elements (simplified)
        Ne = 0.0
        ie = 0.0
        we = self._deg_to_rad(self._wrap360(282.9404 + 4.70935e-5 * d))
        ae = 1.000000
        ee = 0.016709 - 1.151e-9 * d
        Me = self._deg_to_rad(self._wrap360(356.0470 + 0.9856002585 * d))

        Ee = Me
        for _ in range(8):
            Ee = Ee - (Ee - ee * sin(Ee) - Me) / max(1.0 - ee * cos(Ee), 1e-9)
        xve = ae * (cos(Ee) - ee)
        yve = ae * (sqrt(max(1.0 - ee * ee, 1e-12)) * sin(Ee))
        ve = atan2(yve, xve)
        re = sqrt(xve * xve + yve * yve)
        xhe = re * (cos(Ne) * cos(ve + we) - sin(Ne) * sin(ve + we) * cos(ie))
        yhe = re * (sin(Ne) * cos(ve + we) + cos(Ne) * sin(ve + we) * cos(ie))
        zhe = re * (sin(ve + we) * sin(ie))

        # Geocentric coordinates: planet - earth
        xg = xh - xhe
        yg = yh - yhe
        zg = zh - zhe

        lon = self._wrap360(self._rad_to_deg(atan2(yg, xg)))
        return lon

    def _is_retrograde(self, jd: float, lon_today: float, *, planet: str) -> bool:
        # Retrograde if ecliptic longitude is decreasing day-over-day (with wrap handling).
        lon_prev = None
        try:
            if planet == "Sun":
                lon_prev = self._sun_ecliptic_longitude(jd - 1.0)
            elif planet == "Moon":
                lon_prev = self._moon_ecliptic_longitude(jd - 1.0)
            elif planet == "Rahu":
                lon_prev = self._mean_lunar_ascending_node_tropical(jd - 1.0)
            elif planet == "Ketu":
                lon_prev = self._wrap360(self._mean_lunar_ascending_node_tropical(jd - 1.0) + 180.0)
            else:
                lon_prev = self._planet_geocentric_longitude(jd - 1.0, planet=planet)
        except Exception:
            return False
        delta = (lon_today - lon_prev + 540.0) % 360.0 - 180.0  # shortest signed delta
        return delta < 0.0

    @staticmethod
    def _lahiri_ayanamsa(jd: float) -> float:
        """Lahiri (Chitra paksha) ayanamsa in degrees (low-order polynomial, ~arcmin accuracy)."""
        t = (jd - 2451545.0) / 36525.0
        return float(
            22.460148
            + 1.3960423 * t
            + 3.080e-4 * t * t
            + (t**3) / 50384.0
            - (t**4) / 1_521_470.0
        )

    @staticmethod
    def _mean_lunar_ascending_node_tropical(jd: float) -> float:
        """Mean longitude of the Moon's ascending node (tropical), degrees."""
        t = (jd - 2451545.0) / 36525.0
        omega = 125.04452 - 1934.136261 * t + 0.0020708 * t * t + (t**3) / 450000.0
        return EphemerisEngine._wrap360(omega)

    @classmethod
    def _tropical_longitudes(cls, jd: float) -> Dict[str, float]:
        longs: Dict[str, float] = {}
        longs["Sun"] = cls._sun_ecliptic_longitude(jd)
        longs["Moon"] = cls._moon_ecliptic_longitude(jd)
        for p in ("Mercury", "Venus", "Mars", "Jupiter", "Saturn"):
            longs[p] = cls._planet_geocentric_longitude(jd, planet=p)
        node_t = cls._mean_lunar_ascending_node_tropical(jd)
        longs["Rahu"] = node_t
        longs["Ketu"] = cls._wrap360(node_t + 180.0)
        return longs

    def get_planet_positions(self) -> Dict[str, Dict]:
        """
        Compute time-varying planetary longitudes/signs (tropical ecliptic).

        Notes:
        - Lightweight orbital approximations (no Swiss Ephemeris dependency).
        - For Vedic trading inputs use ``get_vedic_snapshot()`` (sidereal Lahiri + nodes + luni-solar calendar).
        """
        jd = self._julian_day(self.current_date)
        longs = self._tropical_longitudes(jd)

        positions: Dict[str, Dict] = {}
        for name, lon in longs.items():
            positions[name] = {
                "longitude": float(lon),
                "latitude": 0.0,
                "sign": self._sign_from_longitude(lon),
                "retrograde": bool(self._is_retrograde(jd, lon, planet=name)),
            }
        return positions

    def get_sidereal_positions(self) -> Dict[str, Dict]:
        """Geocentric sidereal (Lahiri) longitudes for classical planets + mean nodes."""
        jd = self._julian_day(self.current_date)
        ayan = self._lahiri_ayanamsa(jd)
        trop = self._tropical_longitudes(jd)
        positions: Dict[str, Dict] = {}
        for name, lon in trop.items():
            sid = self._wrap360(float(lon) - ayan)
            positions[name] = {
                "longitude": sid,
                "latitude": 0.0,
                "sign": self._sign_from_longitude(sid),
                "retrograde": bool(self._is_retrograde(jd, lon, planet=name)),
            }
        return positions

    @staticmethod
    def _nakshatra_index(sidereal_lon: float) -> int:
        return int(floor((sidereal_lon % 360.0) / (360.0 / 27.0))) % 27

    @staticmethod
    def _tithi_index(sun_sid: float, moon_sid: float) -> int:
        """1..30 Vedic tithi from sidereal elongation (12° per tithi)."""
        elong = (moon_sid - sun_sid) % 360.0
        return int(floor(elong / 12.0)) + 1

    def _vedic_day_anchor_utc(self, dt: datetime) -> datetime:
        """Vedic weekday anchor at 06:00 UTC (documented approximation; not true sunrise)."""
        dt = dt.astimezone(timezone.utc)
        anchor = dt.replace(hour=6, minute=0, second=0, microsecond=0)
        if dt < anchor:
            anchor = anchor - timedelta(days=1)
        return anchor

    def _approximate_hora_lord(self) -> str:
        """
        Approximate Vedic hora lord using UTC with a fixed 06:00 UTC day boundary (no geolocation).
        Documented limitation: not true sunrise; suitable for gating coarse risk, not panchang precision.
        """
        dt = self.current_date.astimezone(timezone.utc)
        anchor = self._vedic_day_anchor_utc(dt)
        dow = anchor.weekday()
        hour_index = int((dt - anchor).total_seconds() // 3600)
        hour_index = max(0, min(23, hour_index))
        start = _DAY_START_LORD[dow]
        start_i = _HORA_CYCLE.index(start)
        idx = (start_i + hour_index) % 7
        return _HORA_CYCLE[idx]

    def get_vedic_snapshot(self) -> Dict:
        """
        Sidereal ephemeris + Moon nakshatra, tithi, approximate hora, Latta kick flags, entry gates.
        """
        jd = self._julian_day(self.current_date)
        sid = self.get_sidereal_positions()
        sun_lon = float(sid["Sun"]["longitude"])
        moon_lon = float(sid["Moon"]["longitude"])
        moon_nak = self._nakshatra_index(moon_lon)
        mars_nak = self._nakshatra_index(float(sid["Mars"]["longitude"]))
        sat_nak = self._nakshatra_index(float(sid["Saturn"]["longitude"]))
        tithi = self._tithi_index(sun_lon, moon_lon)
        hora_lord = self._approximate_hora_lord()

        mars_kick_target = (mars_nak + 3) % 27
        saturn_kick_target = (sat_nak + 8) % 27
        mars_latta = moon_nak == mars_kick_target
        saturn_latta = moon_nak == saturn_kick_target
        latta_active = bool(mars_latta or saturn_latta)

        blocked_tithi = tithi in {8, 14, 15, 23, 29, 30}
        saturn_hora = hora_lord == "Saturn"
        favorable_hora = hora_lord in {"Jupiter", "Mars"}

        mars_saturn_opposition = (
            abs((float(sid["Mars"]["longitude"]) - float(sid["Saturn"]["longitude"]) + 180.0) % 360.0 - 180.0) < 8.0
        )

        return {
            "jd": jd,
            "positions_sidereal": sid,
            "moon_nakshatra_index": moon_nak,
            "moon_nakshatra": NAKSHATRAS[moon_nak],
            "tithi": tithi,
            "hora_lord": hora_lord,
            "mars_latta": mars_latta,
            "saturn_latta": saturn_latta,
            "latta_active": latta_active,
            "mars_latta_target_nakshatra": NAKSHATRAS[mars_kick_target],
            "saturn_latta_target_nakshatra": NAKSHATRAS[saturn_kick_target],
            "entry_blocked_saturn_hora": saturn_hora,
            "entry_blocked_tithi": blocked_tithi,
            "entry_favorable_hora": favorable_hora,
            "mars_saturn_samasaptaka_approx": mars_saturn_opposition,
        }

    def calculate_vedha(self) -> Dict[str, bool]:
        """
        Heuristic vedha-style flags from sidereal Lahiri signs (crypto / general malefic stress).
        """
        pos = self.get_sidereal_positions()
        mars_sign = (pos.get("Mars") or {}).get("sign")
        sat_sign = (pos.get("Saturn") or {}).get("sign")
        sun_sign = (pos.get("Sun") or {}).get("sign")
        moon_sign = (pos.get("Moon") or {}).get("sign")
        jup_rx = bool((pos.get("Jupiter") or {}).get("retrograde"))
        ven_sign = (pos.get("Venus") or {}).get("sign")
        rah_sign = (pos.get("Rahu") or {}).get("sign")

        mars_saturn_vedha = bool(
            mars_sign in {"Aries", "Scorpio"} and sat_sign in {"Capricorn", "Aquarius", "Pisces"}
        )
        return {
            "mars_saturn_vedha": mars_saturn_vedha,
            "sun_moon_vedha": bool(sun_sign == moon_sign),
            "jupiter_venus_vedha": bool(jup_rx and ven_sign in {"Cancer", "Pisces", "Taurus"}),
            "rahu_intensified_fixed": bool(rah_sign in {"Taurus", "Scorpio", "Aquarius", "Leo"}),
        }

    def get_crypto_astro_signals(self) -> Dict[str, bool]:
        """
        ETH / crypto regime heuristics from sidereal state (Rahu-centric + Jupiter/Saturn regimes).
        """
        sid = self.get_sidereal_positions()
        jup_sign = (sid.get("Jupiter") or {}).get("sign")
        sat_sign = (sid.get("Saturn") or {}).get("sign")
        rah_sign = (sid.get("Rahu") or {}).get("sign")
        mars_sign = (sid.get("Mars") or {}).get("sign")
        jup_rx = bool((sid.get("Jupiter") or {}).get("retrograde"))

        earth = {"Taurus", "Virgo", "Capricorn"}
        cardinal = {"Aries", "Cancer", "Libra", "Capricorn"}
        air = {"Gemini", "Libra", "Aquarius"}

        jupiter_air_season = bool(jup_sign in air)
        saturn_crypto_winter = bool(sat_sign in earth or sat_sign in cardinal)
        rahu_fixed_axis_stress = bool(rah_sign in {"Taurus", "Scorpio"})
        mars_fire_stress = bool(mars_sign in {"Aries", "Leo", "Sagittarius"})

        return {
            "jupiter_air_bull_window": jupiter_air_season,
            "saturn_earth_cardinal_winter": saturn_crypto_winter,
            "rahu_taurus_scorpio_exchange_axis": rahu_fixed_axis_stress,
            "mars_fire_volatility": mars_fire_stress,
            "jupiter_retrograde": jup_rx,
            # Back-compat keys consumed by older configs / tests
            "mars_in_scorpio_aries": bool(mars_sign in {"Scorpio", "Aries"}),
            "saturn_in_dahana_nadi": mars_fire_stress,
            "jupiter_retro_cancer": bool(jup_rx and jup_sign == "Cancer"),
        }

    def get_oil_astro_signals(self) -> Dict[str, bool]:
        """Deprecated: Brent/oil mapping removed; use ``get_crypto_astro_signals`` for ETH."""
        return self.get_crypto_astro_signals()

    def get_red_day(self) -> bool:
        """Determine if today is a Red Day (trading halt day)."""
        override = os.getenv("DISABLE_RED_DAY_GATE", "").strip().lower()
        if override in {"1", "true", "yes", "y", "on"}:
            return False
        # Simplified: Red Day on approximate full/new moon based on Sun/Moon separation.
        jd = self._julian_day(self.current_date)
        sun_lon = self._sun_ecliptic_longitude(jd)
        moon_lon = self._moon_ecliptic_longitude(jd)
        sep = abs((moon_lon - sun_lon + 180.0) % 360.0 - 180.0)
        # New moon near 0°, full moon near 180°
        return sep < 8.0 or abs(sep - 180.0) < 8.0

    # Backwards-compatible helper for any callers that expected a phase string.
    def _get_moon_phase(self) -> str:
        jd = self._julian_day(self.current_date)
        sun_lon = self._sun_ecliptic_longitude(jd)
        moon_lon = self._moon_ecliptic_longitude(jd)
        sep = abs((moon_lon - sun_lon + 180.0) % 360.0 - 180.0)
        if sep < 8.0:
            return "New Moon"
        if abs(sep - 180.0) < 8.0:
            return "Full Moon"
        return "Waxing" if sep < 180.0 else "Waning"