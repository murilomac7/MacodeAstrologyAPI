# Copyright (C) 2026 murilomac7
# SPDX-License-Identifier: AGPL-3.0-only
"""Swiss Ephemeris natal chart calculation (drop-in for json.astrologyapi.com/v1/western_horoscope)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import swisseph as swe

# Point pyswisseph to our bundled ephemeris files (needed for Chiron/asteroids).
# Falls back to built-in Moshier if the ephe/ directory is missing.
_EPHE_DIR = Path(__file__).parent.parent / "ephe"
if _EPHE_DIR.is_dir():
    swe.set_ephe_path(str(_EPHE_DIR))

# ─── constants ───────────────────────────────────────────────────────────────

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer",
    "Leo", "Virgo", "Libra", "Scorpio",
    "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

# (swisseph_id, name_in_output)
_PLANET_CONFIGS: list[tuple[int, str]] = [
    (swe.SUN, "Sun"),
    (swe.MOON, "Moon"),
    (swe.MERCURY, "Mercury"),
    (swe.VENUS, "Venus"),
    (swe.MARS, "Mars"),
    (swe.JUPITER, "Jupiter"),
    (swe.SATURN, "Saturn"),
    (swe.URANUS, "Uranus"),
    (swe.NEPTUNE, "Neptune"),
    (swe.PLUTO, "Pluto"),
    (swe.TRUE_NODE, "North Node"),
    (swe.CHIRON, "Chiron"),
]

# (aspect_name, exact_angle, max_orb_degrees)
_ASPECTS: list[tuple[str, float, float]] = [
    ("Conjunction", 0.0, 8.0),
    ("Semi-sextile", 30.0, 2.0),
    ("Semi-square", 45.0, 2.0),
    ("Sextile", 60.0, 6.0),
    ("Square", 90.0, 7.0),
    ("Trine", 120.0, 7.0),
    ("Quincunx", 150.0, 3.0),
    ("Opposition", 180.0, 8.0),
]

# Bodies included in aspect calculation
_ASPECT_BODIES = frozenset({
    "Sun", "Moon", "Mercury", "Venus", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
    "North Node", "Chiron", "Part of Fortune", "Lilith",
    "Ascendant", "Midheaven",
})

# Planets (Sun-Pluto, Nodes): use Moshier built-in, no files required.
# Chiron/asteroids: use SE1 file (seas_18.se1); falls back silently if file absent.
_FLAGS_PLANETS = swe.FLG_MOSEPH | swe.FLG_SPEED
_FLAGS_ASTEROIDS = swe.FLG_SWIEPH | swe.FLG_SPEED

# House-system byte codes
_HOUSE_SYS = {
    "placidus": b"P",
    "topocentric": b"T",   # Polich/Page (topocentric) — results ≈ Placidus
    "koch": b"K",
    "equal": b"E",
    "whole": b"W",
    "campanus": b"C",
    "regiomontanus": b"R",
    "porphyry": b"O",
    "morinus": b"M",
    "axial": b"X",
}


# ─── helpers ─────────────────────────────────────────────────────────────────

def _sign_of(lon: float) -> tuple[str, int]:
    """Return (sign_name, sign_id) for an ecliptic longitude."""
    idx = int(lon / 30) % 12
    return SIGNS[idx], idx


def _norm_deg(lon: float) -> float:
    """Degrees within the sign (0–30)."""
    return lon % 30


def _planet_house(lon: float, cusps: tuple) -> int:
    """Return the house number (1–12) for an ecliptic longitude.

    pyswisseph swe.houses() returns a 12-element tuple (0-indexed):
      cusps[0] = ASC = house 1 cusp
      cusps[1] = house 2 cusp … cusps[11] = house 12 cusp
    """
    lon = lon % 360
    for h in range(1, 13):
        start = cusps[h - 1] % 360          # house h starts here
        end = cusps[h % 12] % 360           # house h ends at house h+1 cusp (wraps)
        if end < start:
            if lon >= start or lon < end:
                return h
        else:
            if start <= lon < end:
                return h
    return 1


def _arc(lon1: float, lon2: float) -> float:
    """Shortest angular arc between two longitudes (0–180°)."""
    diff = abs(lon1 - lon2) % 360
    return diff if diff <= 180.0 else 360.0 - diff


def _is_day_chart(sun_lon: float, asc_lon: float) -> bool:
    """True when the Sun is above the horizon (houses 7–12 in diurnal half).

    Houses 1–6 span [ASC, ASC+180°), so a planet in that window is BELOW
    the horizon (nocturnal).  Houses 7–12 span [ASC+180°, ASC+360°), i.e.
    angular distance from ASC >= 180° → above horizon → day chart.
    """
    return (sun_lon - asc_lon) % 360 >= 180.0


# ─── main calculation ────────────────────────────────────────────────────────

def calculate_western_horoscope(
    day: int,
    month: int,
    year: int,
    hour: int,
    minute: int,
    lat: float,
    lon: float,
    tzone: float,
    house_type: str = "placidus",
) -> dict[str, Any]:
    """
    Calculate a complete western natal chart.

    Returns a dict whose shape is compatible with json.astrologyapi.com/v1/western_horoscope:
    {
      sun_sign, moon_sign,
      ascendant, midheaven, vertex,   # ecliptic longitudes (float)
      planets   [ {name, full_degree, norm_degree, speed, is_retro, sign_id, sign, house} ],
      houses    [ {house, sign, degree, sign_id} ],
      aspects   [ {aspecting_planet, aspected_planet, type, orb} ],
      lilith    { name, full_degree, norm_degree, speed, is_retro, sign_id, sign, house }
    }
    """
    # Re-apply the ephemeris path on every call.
    # FLG_MOSEPH used for major planets can reset the SE's internal file search state;
    # calling set_ephe_path before the asteroid calculation (Chiron) avoids the issue.
    if _EPHE_DIR.is_dir():
        swe.set_ephe_path(str(_EPHE_DIR))

    # Convert local birth time → UTC using datetime arithmetic (handles day rollover)
    local_dt = datetime(year, month, day, hour, minute, 0)
    tzone_delta = timedelta(hours=float(tzone))
    utc_dt = local_dt - tzone_delta

    jd_ut = swe.julday(
        utc_dt.year, utc_dt.month, utc_dt.day,
        utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0,
    )

    # House system – fall back to Placidus when unknown
    hsys = _HOUSE_SYS.get((house_type or "placidus").lower().strip(), b"P")

    # For extreme latitudes Placidus is undefined; fall back to Whole Sign
    if abs(lat) > 66.5 and hsys == b"P":
        hsys = b"W"

    # cusps: 12-element tuple (0-indexed); cusps[0] = ASC = house 1 cusp
    # ascmc: ascmc[0]=ASC, ascmc[1]=MC, ascmc[3]=Vertex
    cusps, ascmc = swe.houses(jd_ut, lat, lon, hsys)
    asc_lon = ascmc[0] % 360
    mc_lon = ascmc[1] % 360
    vertex_lon = ascmc[3] % 360

    # ── planets ──────────────────────────────────────────────────────────────
    body_lons: dict[str, float] = {
        "Ascendant": asc_lon,
        "Midheaven": mc_lon,
    }
    planets_out: list[dict[str, Any]] = []

    for swe_id, name in _PLANET_CONFIGS:
        # Chiron is an asteroid and needs SE1 file; all others use Moshier built-in
        flags = _FLAGS_ASTEROIDS if swe_id == swe.CHIRON else _FLAGS_PLANETS
        try:
            res, _ = swe.calc_ut(jd_ut, swe_id, flags)
        except Exception:
            continue
        p_lon = res[0] % 360
        speed = res[3]
        sign, sign_id = _sign_of(p_lon)
        house = _planet_house(p_lon, cusps)
        body_lons[name] = p_lon
        planets_out.append({
            "name": name,
            "full_degree": round(p_lon, 4),
            "norm_degree": round(_norm_deg(p_lon), 4),
            "speed": round(speed, 6),
            "is_retro": "true" if speed < 0 else "false",
            "sign_id": sign_id,
            "sign": sign,
            "house": house,
        })

    # ── Lilith (Mean Black Moon) ──────────────────────────────────────────────
    lilith: dict[str, Any] | None = None
    try:
        lil_res, _ = swe.calc_ut(jd_ut, swe.MEAN_APOG, _FLAGS_PLANETS)
        lil_lon = lil_res[0] % 360
        lil_speed = lil_res[3]
        lil_sign, lil_sign_id = _sign_of(lil_lon)
        lil_house = _planet_house(lil_lon, cusps)
        lilith = {
            "name": "Lilith",
            "full_degree": round(lil_lon, 4),
            "norm_degree": round(_norm_deg(lil_lon), 4),
            "speed": round(lil_speed, 6),
            "is_retro": "true" if lil_speed < 0 else "false",
            "sign_id": lil_sign_id,
            "sign": lil_sign,
            "house": lil_house,
        }
        body_lons["Lilith"] = lil_lon
    except Exception:
        pass

    # ── Part of Fortune ───────────────────────────────────────────────────────
    sun_lon = body_lons.get("Sun")
    moon_lon = body_lons.get("Moon")
    if sun_lon is not None and moon_lon is not None:
        if _is_day_chart(sun_lon, asc_lon):
            pof_lon = (asc_lon + moon_lon - sun_lon) % 360
        else:
            pof_lon = (asc_lon + sun_lon - moon_lon) % 360
        pof_sign, pof_sign_id = _sign_of(pof_lon)
        pof_house = _planet_house(pof_lon, cusps)
        planets_out.append({
            "name": "Part of Fortune",
            "full_degree": round(pof_lon, 4),
            "norm_degree": round(_norm_deg(pof_lon), 4),
            "speed": 0.0,
            "is_retro": "false",
            "sign_id": pof_sign_id,
            "sign": pof_sign,
            "house": pof_house,
        })
        body_lons["Part of Fortune"] = pof_lon

    # ── Houses ────────────────────────────────────────────────────────────────
    houses_out: list[dict[str, Any]] = []
    for i in range(1, 13):
        h_lon = cusps[i - 1] % 360          # house i cusp at cusps[i-1]
        h_sign, h_sign_id = _sign_of(h_lon)
        houses_out.append({
            "house": i,
            "sign": h_sign,
            "degree": round(h_lon, 4),
            "sign_id": h_sign_id,
        })

    # ── Aspects ───────────────────────────────────────────────────────────────
    aspect_names = [n for n in body_lons if n in _ASPECT_BODIES]
    aspects_out: list[dict[str, Any]] = []
    seen_pairs: set[frozenset] = set()
    for i, n1 in enumerate(aspect_names):
        for n2 in aspect_names[i + 1:]:
            pair = frozenset({n1, n2})
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            diff = _arc(body_lons[n1], body_lons[n2])
            for asp_name, exact, max_orb in _ASPECTS:
                orb = abs(diff - exact)
                if orb <= max_orb:
                    aspects_out.append({
                        "aspecting_planet": n1,
                        "aspected_planet": n2,
                        "type": asp_name,
                        "orb": round(orb, 2),
                    })
                    break

    # ── top-level convenience fields ─────────────────────────────────────────
    sun_entry = next((p for p in planets_out if p["name"] == "Sun"), None)
    moon_entry = next((p for p in planets_out if p["name"] == "Moon"), None)

    # Derived angles (convenient for element / modality counting in the client)
    ic_lon          = (mc_lon + 180.0) % 360.0
    dsc_lon         = (asc_lon + 180.0) % 360.0
    anti_vertex_lon = (vertex_lon + 180.0) % 360.0

    ic_sign, ic_sign_id   = _sign_of(ic_lon)
    dsc_sign, dsc_sign_id = _sign_of(dsc_lon)
    av_sign, av_sign_id   = _sign_of(anti_vertex_lon)
    vtx_sign, vtx_sign_id = _sign_of(vertex_lon)

    return {
        "sun_sign": sun_entry["sign"] if sun_entry else "",
        "moon_sign": moon_entry["sign"] if moon_entry else "",
        "ascendant": round(asc_lon, 4),
        "midheaven": round(mc_lon, 4),
        "ic":        round(ic_lon, 4),
        "dsc":       round(dsc_lon, 4),
        "vertex": round(vertex_lon, 4),
        "vertex_sign": vtx_sign,
        "vertex_sign_id": vtx_sign_id,
        "anti_vertex": round(anti_vertex_lon, 4),
        "anti_vertex_sign": av_sign,
        "anti_vertex_sign_id": av_sign_id,
        "ic_sign": ic_sign,
        "ic_sign_id": ic_sign_id,
        "dsc_sign": dsc_sign,
        "dsc_sign_id": dsc_sign_id,
        "planets": planets_out,
        "houses": houses_out,
        "aspects": aspects_out,
        "lilith": lilith,
    }
