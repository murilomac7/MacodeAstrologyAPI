# Copyright (C) 2026 murilomac7
# SPDX-License-Identifier: AGPL-3.0-only
"""Natal wheel chart SVG generator for MacodeAstrologyAPI.

Generates an SVG natal chart wheel compatible with the output style of
json.astrologyapi.com/v1/natal_wheel_chart.

IMPORTANT: The first 12 ``stroke="#000000"`` occurrences in the output SVG are
the 12 zodiac-sign sector paths, ordered Aries → Pisces (sign_id 0-11).
SolApp replaces them with its SIGN_COLORS palette, so order matters.
"""
from __future__ import annotations

import math
from typing import Any

# ─── Glyph tables ────────────────────────────────────────────────────────────

PLANET_GLYPHS: dict[str, str] = {
    "Sun":             "☉",
    "Moon":            "☽",
    "Mercury":         "☿",
    "Venus":           "♀",
    "Mars":            "♂",
    "Jupiter":         "♃",
    "Saturn":          "♄",
    "Uranus":          "♅",
    "Neptune":         "♆",
    "Pluto":           "♇",
    "North Node":      "☊",
    "Chiron":          "⚷",
    "Lilith":          "⚸",
    "Part of Fortune": "⊕",
}

SIGN_GLYPHS: list[str] = [
    "♈", "♉", "♊", "♋", "♌", "♍",
    "♎", "♏", "♐", "♑", "♒", "♓",
]

# aspect type → stroke colour
ASPECT_COLORS: dict[str, str] = {
    "Conjunction":  "#888888",
    "Opposition":   "#CC0000",
    "Square":       "#CC0000",
    "Semi-square":  "#CC6600",
    "Trine":        "#008800",
    "Sextile":      "#008800",
    "Quincunx":     "#996600",
    "Semi-sextile": "#009900",
}


# ─── Geometry helpers ─────────────────────────────────────────────────────────

def _svg_angle(lon: float, asc_lon: float) -> float:
    """Convert ecliptic longitude → SVG angle (degrees, 0 = right, clockwise).

    The Ascendant (asc_lon) is always placed at 180° (left / 9-o'clock).
    Increasing ecliptic longitude → decreasing SVG angle (counterclockwise
    on screen), matching the standard western natal-chart convention.
    """
    return (180.0 + asc_lon - lon) % 360.0


def _xy(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    """Polar → SVG Cartesian.  deg=0 is right, increases clockwise (y-down)."""
    rad = math.radians(deg)
    return cx + r * math.cos(rad), cy + r * math.sin(rad)


def _sector(cx: float, cy: float, r_in: float, r_out: float,
            a1: float, a2: float) -> str:
    """SVG path for a filled sector between r_in and r_out.

    The outer arc sweeps CLOCKWISE from a1 to a2 (sweep=1).
    The inner arc sweeps COUNTERCLOCKWISE back from a2 to a1 (sweep=0).
    Handles wrap-around automatically via the large-arc flag.
    """
    xi1, yi1 = _xy(cx, cy, r_in,  a1)
    xo1, yo1 = _xy(cx, cy, r_out, a1)
    xo2, yo2 = _xy(cx, cy, r_out, a2)
    xi2, yi2 = _xy(cx, cy, r_in,  a2)
    diff = (a2 - a1) % 360.0
    large = 1 if diff > 180 else 0
    return (
        f"M {xi1:.2f},{yi1:.2f} "
        f"L {xo1:.2f},{yo1:.2f} "
        f"A {r_out:.2f},{r_out:.2f} 0 {large},1 {xo2:.2f},{yo2:.2f} "
        f"L {xi2:.2f},{yi2:.2f} "
        f"A {r_in:.2f},{r_in:.2f} 0 {large},0 {xi1:.2f},{yi1:.2f} Z"
    )


def _mid_angle(a1: float, a2: float) -> float:
    """Clockwise midpoint angle between a1 and a2 (handles wrap-around)."""
    diff = (a2 - a1) % 360.0
    return (a1 + diff / 2.0) % 360.0


# ─── Main generator ──────────────────────────────────────────────────────────

def generate_wheel_svg(
    chart_data: dict[str, Any],
    *,
    chart_size: int = 500,
    planet_icon_color: str = "#333333",
    inner_circle_background: str = "#FFF8E1",
    sign_icon_color: str = "#000000",
    sign_background: str = "#ffffff",
) -> str:
    """Generate a natal wheel SVG from the output of calculate_western_horoscope().

    The first 12 ``stroke="#000000"`` attributes in the returned string
    belong to the 12 zodiac-sector paths (Aries → Pisces), so SolApp's
    palette-replacement loop works correctly.
    """

    # ── Unpack chart data ────────────────────────────────────────────────────
    asc_lon = float(chart_data.get("ascendant", 0.0))
    mc_lon  = float(chart_data.get("midheaven", 0.0))
    planets  = chart_data.get("planets", [])
    houses   = chart_data.get("houses", [])
    aspects  = chart_data.get("aspects", [])
    lilith   = chart_data.get("lilith")

    # ── Layout constants ─────────────────────────────────────────────────────
    S   = float(chart_size)
    cx  = cy = S / 2.0
    pad = 5.0

    R_max      = S / 2.0 - pad       # outer zodiac edge
    R_zod_in   = R_max * 0.860       # inner zodiac = outer house ring
    R_hse_in   = R_max * 0.555       # inner house ring
    R_planet   = R_max * 0.730       # planet glyph radius
    R_deg_lbl  = R_max * 0.630       # small degree-text radius
    R_asp      = R_hse_in - 2.0      # aspect-line termination
    R_center   = R_hse_in * 0.760    # central disc radius
    R_zod_mid  = (R_max + R_zod_in) / 2.0     # sign-glyph radius
    R_hse_num  = (R_zod_in + R_hse_in) / 2.0 - 4.0   # house-number radius

    # ── Pre-compute house cusp SVG angles ────────────────────────────────────
    # houses list: [{house:1, degree:<cusp_lon>}, …, {house:12, degree:<cusp_lon>}]
    # sorted by house number so index i → house (i+1)
    sorted_houses = sorted(houses, key=lambda h: h["house"])
    h_svg = [_svg_angle(float(h["degree"]), asc_lon) for h in sorted_houses]

    # ── Planet longitude lookup ───────────────────────────────────────────────
    planet_lon: dict[str, float] = {p["name"]: float(p["full_degree"]) for p in planets}
    if lilith:
        planet_lon[lilith["name"]] = float(lilith["full_degree"])
    # Include ASC and MC so aspect lines to angles are rendered
    planet_lon["Ascendant"] = asc_lon
    planet_lon["Midheaven"] = mc_lon

    # ── SVG accumulator ──────────────────────────────────────────────────────
    out: list[str] = []

    def w(s: str) -> None:
        out.append(s)

    w(f'<svg xmlns="http://www.w3.org/2000/svg" width="{chart_size}" height="{chart_size}" '
      f'viewBox="0 0 {chart_size} {chart_size}" style="background:transparent">')

    # Font definitions: prefer fonts known to include astrological unicode glyphs
    w('<defs><style>'
      'text.glyph { font-family: "Symbola","Segoe UI Symbol","Apple Symbols",'
      '"DejaVu Serif","FreeSerif","Noto Serif","serif"; }'
      'text.label { font-family: "Helvetica Neue","Arial","sans-serif"; }'
      '</style></defs>')

    # 1. Wheel disc only — corners of the square stay transparent.
    #    Drawn before the 12 zodiac sectors so SolApp's stroke="#000000"
    #    replacement still targets those paths first.
    w(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{R_max:.1f}" '
      f'fill="{sign_background}" stroke="none"/>')

    # ══════════════════════════════════════════════════════════════════════════
    # 2. ZODIAC RING — 12 sectors, Aries first (stroke="#000000" × 12)
    #    These MUST be the first 12 stroke="#000000" elements in the SVG.
    # ══════════════════════════════════════════════════════════════════════════
    for s in range(12):
        lon_hi = 30.0 * (s + 1)   # upper bound of sign s
        lon_lo = 30.0 * s         # lower bound
        # higher ecliptic lon → lower SVG angle (counterclockwise on screen)
        a1 = _svg_angle(lon_hi, asc_lon)  # lower SVG angle
        a2 = _svg_angle(lon_lo, asc_lon)  # higher SVG angle
        # Clockwise arc from a1 to a2
        d = _sector(cx, cy, R_zod_in, R_max, a1, a2)
        w(f'<path d="{d}" fill="{sign_background}" stroke="#000000" stroke-width="0.8"/>')

    # Sign glyphs (using neutral stroke, not "#000000", to avoid breaking SolApp)
    for s in range(12):
        lon_mid = 30.0 * s + 15.0
        ang = _svg_angle(lon_mid, asc_lon)
        x, y = _xy(cx, cy, R_zod_mid, ang)
        w(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
          f'dominant-baseline="middle" class="glyph" font-size="12" '
          f'fill="{sign_icon_color}">{SIGN_GLYPHS[s]}</text>')

    # ══════════════════════════════════════════════════════════════════════════
    # 3. HOUSE RING — sectors with cusp lines (using non-black strokes)
    # ══════════════════════════════════════════════════════════════════════════
    for h in range(12):
        # House h+1 spans from cusp h+2 (lower SVG angle) to cusp h+1 (higher)
        a1 = h_svg[(h + 1) % 12]   # next cusp → lower SVG angle
        a2 = h_svg[h]               # this cusp → higher SVG angle
        d = _sector(cx, cy, R_hse_in, R_zod_in, a1, a2)
        w(f'<path d="{d}" fill="{sign_background}" stroke="#bbbbbb" stroke-width="0.4"/>')

    # House cusp radial lines
    for i, ang in enumerate(h_svg):
        is_cardinal = (i % 3 == 0)
        r_inner = R_center if is_cardinal else R_hse_in
        lw = "1.4" if is_cardinal else "0.5"
        x1, y1 = _xy(cx, cy, r_inner, ang)
        x2, y2 = _xy(cx, cy, R_max, ang)
        w(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
          f'stroke="#444444" stroke-width="{lw}"/>')

    # House numbers
    for h in range(12):
        a1  = h_svg[(h + 1) % 12]
        a2  = h_svg[h]
        mid = _mid_angle(a1, a2)
        x, y = _xy(cx, cy, R_hse_num, mid)
        w(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
          f'dominant-baseline="middle" '
          f'font-family="sans-serif" font-size="9" fill="#555555">{h + 1}</text>')

    # ══════════════════════════════════════════════════════════════════════════
    # 4. RING BORDERS
    # ══════════════════════════════════════════════════════════════════════════
    for r, lw in [(R_max, "1.2"), (R_zod_in, "0.8"), (R_hse_in, "0.8")]:
        w(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
          f'fill="none" stroke="#444444" stroke-width="{lw}"/>')

    # ══════════════════════════════════════════════════════════════════════════
    # 5. CENTRAL DISC (cream background, drawn before aspect lines)
    # ══════════════════════════════════════════════════════════════════════════
    w(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{R_center:.1f}" '
      f'fill="{inner_circle_background}" stroke="#444444" stroke-width="0.5"/>')

    # ══════════════════════════════════════════════════════════════════════════
    # 6. ASPECT LINES (inside central disc)
    # ══════════════════════════════════════════════════════════════════════════
    for asp in aspects:
        p1 = asp.get("aspecting_planet") or asp.get("planet1", "")
        p2 = asp.get("aspected_planet") or asp.get("planet2", "")
        asp_type = asp.get("type", "")
        color = ASPECT_COLORS.get(asp_type, "#aaaaaa")

        lon1 = planet_lon.get(p1)
        lon2 = planet_lon.get(p2)
        if lon1 is None or lon2 is None:
            continue

        a1 = _svg_angle(lon1, asc_lon)
        a2 = _svg_angle(lon2, asc_lon)
        x1, y1 = _xy(cx, cy, R_asp, a1)
        x2, y2 = _xy(cx, cy, R_asp, a2)

        lw = "0.6" if asp_type in ("Semi-sextile", "Semi-square", "Quincunx") else "0.9"
        w(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
          f'stroke="{color}" stroke-width="{lw}" opacity="0.85"/>')

    # ══════════════════════════════════════════════════════════════════════════
    # 7. PLANET GLYPHS (in house ring, near outer edge)
    # ══════════════════════════════════════════════════════════════════════════
    bodies: list[dict[str, Any]] = list(planets)
    if lilith:
        bodies.append(dict(lilith))

    # ── Collision-avoidance: symmetric spring/force relaxation ──────────────────
    # The classic unidirectional nudge always pushes CW, which displaces a
    # Sagittarius cluster of 7+ planets all the way into Scorpio/Libra.
    # Spring relaxation pushes overlapping pairs apart *symmetrically*, so the
    # cluster spreads around its natural centre instead of drifting in one
    # direction.  Each pair with gap < min_gap is pushed apart by (gap-dist)/2
    # in each iteration until no overlaps remain (or max_iter is reached).
    base_angles: list[float] = [_svg_angle(float(b["full_degree"]), asc_lon) for b in bodies]

    def _resolve_collisions(angles: list[float], min_gap: float = 6.0,
                            max_iter: int = 300) -> list[float]:
        res = list(angles)
        n = len(res)
        for _ in range(max_iter):
            deltas = [0.0] * n
            any_col = False
            for i in range(n):
                for j in range(i + 1, n):
                    diff = (res[j] - res[i] + 360.0) % 360.0
                    if diff > 180.0:
                        diff -= 360.0
                    dist = abs(diff)
                    if dist < min_gap:
                        any_col = True
                        push = (min_gap - dist) / 2.0
                        if diff >= 0:
                            deltas[i] -= push
                            deltas[j] += push
                        else:
                            deltas[i] += push
                            deltas[j] -= push
            if not any_col:
                break
            for i in range(n):
                res[i] = (res[i] + deltas[i]) % 360.0
        return res

    display_angles = _resolve_collisions(base_angles)

    for idx, body in enumerate(bodies):
        name = body["name"]
        lon  = float(body["full_degree"])
        base_ang    = base_angles[idx]
        display_ang = display_angles[idx]

        is_retro = str(body.get("is_retro", "false")).lower() == "true"
        glyph = PLANET_GLYPHS.get(name, name[:2])
        retro_suffix = " ℞" if is_retro else ""

        # Glyph
        px, py = _xy(cx, cy, R_planet, display_ang)
        w(f'<text x="{px:.1f}" y="{py:.1f}" text-anchor="middle" '
          f'dominant-baseline="middle" class="glyph" font-size="11" '
          f'fill="{planet_icon_color}">{glyph}{retro_suffix}</text>')

        # Degree label
        dx, dy = _xy(cx, cy, R_deg_lbl, display_ang)
        norm = int(round(float(body.get("norm_degree", lon % 30))))
        w(f'<text x="{dx:.1f}" y="{dy:.1f}" text-anchor="middle" '
          f'dominant-baseline="middle" class="label" font-size="6.5" '
          f'fill="{planet_icon_color}">{norm}°</text>')

        # Tick line at actual planet position
        tx1, ty1 = _xy(cx, cy, R_hse_in + 2, base_ang)
        tx2, ty2 = _xy(cx, cy, R_hse_in - 4, base_ang)
        w(f'<line x1="{tx1:.1f}" y1="{ty1:.1f}" x2="{tx2:.1f}" y2="{ty2:.1f}" '
          f'stroke="{planet_icon_color}" stroke-width="0.6"/>')

    # ══════════════════════════════════════════════════════════════════════════
    # 8. CARDINAL-POINT LABELS (As, Ds, Mc, Ic) on the outer ring
    # ══════════════════════════════════════════════════════════════════════════
    dsc_lon = (asc_lon + 180.0) % 360.0
    ic_lon  = (mc_lon  + 180.0) % 360.0

    for label, lon in [("As", asc_lon), ("Ds", dsc_lon), ("Mc", mc_lon), ("Ic", ic_lon)]:
        ang = _svg_angle(lon, asc_lon)
        lx, ly = _xy(cx, cy, R_max - 14.0, ang)
        w(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
          f'dominant-baseline="middle" class="label" font-size="8" font-weight="bold" '
          f'fill="#222222">{label}</text>')

    w("</svg>")
    return "\n".join(out)
