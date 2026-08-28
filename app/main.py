# Copyright (C) 2026 murilomac7
# SPDX-License-Identifier: AGPL-3.0-only
"""MacodeAstrologyAPI — FastAPI application.

Drop-in replacement for json.astrologyapi.com/v1/western_horoscope
and json.astrologyapi.com/v1/natal_wheel_chart.
Uses pyswisseph (Moshier algorithm) — no external ephemeris files required.
"""
from __future__ import annotations

import secrets
import os
import uuid
import json
import base64
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from app.chart import calculate_western_horoscope
from app.wheel import generate_wheel_svg

# ─── auth ────────────────────────────────────────────────────────────────────

_API_USER_ID: str = os.getenv("API_USER_ID", "alex")
_API_KEY: str = os.getenv("API_KEY", "")
_SKIP_AUTH: bool = os.getenv("SKIP_AUTH", "false").lower() in {"1", "true", "yes"}

_SOURCE_URL = "https://github.com/murilomac7/MacodeAstrologyAPI"

security = HTTPBasic(auto_error=False)


def _verify(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    if _SKIP_AUTH:
        return
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais em falta",
            headers={"WWW-Authenticate": "Basic"},
        )
    ok_user = secrets.compare_digest(credentials.username.encode(), _API_USER_ID.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), _API_KEY.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Basic"},
        )


# ─── app ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="MacodeAstrologyAPI",
    description=(
        "Local Swiss Ephemeris western natal chart API. "
        "Substitui 100% json.astrologyapi.com/v1/western_horoscope "
        "com cálculo local (sem dependência de API paga).\n\n"
        "Licensed under GNU AGPL v3. Corresponding source (AGPL §13): "
        f"{_SOURCE_URL}"
    ),
    version="1.0.0",
    license_info={
        "name": "GNU Affero General Public License v3.0",
        "identifier": "AGPL-3.0-only",
        "url": "https://www.gnu.org/licenses/agpl-3.0.html",
    },
)


# ─── Chart token helpers ──────────────────────────────────────────────────────
# Instead of storing SVGs in memory (which breaks with Railway load balancing),
# we encode the chart parameters into a URL-safe base64 token.
# The GET endpoint decodes the token and regenerates the SVG on the fly.

def _encode_token(req: "WheelChartRequest") -> str:
    """Compact URL-safe base64 encoding of chart parameters."""
    data = {
        "d": req.day, "m": req.month, "y": req.year,
        "h": req.hour, "n": req.min,
        "la": req.lat, "lo": req.lon, "tz": req.tzone,
        "hs": req.house_type, "cs": req.chart_size,
        "pic": req.planet_icon_color,
        "icb": req.inner_circle_background,
        "sic": req.sign_icon_color,
        "sb":  req.sign_background,
    }
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_token(token: str) -> dict:
    """Decode chart parameters from a URL-safe base64 token."""
    pad = (-len(token)) % 4
    return json.loads(base64.urlsafe_b64decode(token + "=" * pad).decode())


# ─── models ──────────────────────────────────────────────────────────────────

class HoroscopeRequest(BaseModel):
    day: int = Field(..., ge=1, le=31, description="Day of birth")
    month: int = Field(..., ge=1, le=12, description="Month of birth")
    year: int = Field(..., ge=1800, le=2100, description="Year of birth")
    hour: int = Field(..., ge=0, le=23, description="Hour of birth (local time)")
    min: int = Field(0, ge=0, le=59, description="Minute of birth (local time)")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Birth latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Birth longitude")
    tzone: float = Field(0.0, description="UTC offset in hours (e.g. -3 for Brasília)")
    house_type: str = Field("placidus", description="House system (placidus, koch, equal, whole …)")
    is_asteroids: str = Field("true", description="Kept for API compatibility; always returns Chiron")


class WheelChartRequest(BaseModel):
    """Parameters for natal_wheel_chart — superset of HoroscopeRequest."""
    day: int = Field(..., ge=1, le=31)
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=1800, le=2100)
    hour: int = Field(..., ge=0, le=23)
    min: int = Field(0, ge=0, le=59)
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    tzone: float = Field(0.0)
    house_type: str = Field("placidus")
    is_asteroids: str = Field("true")
    # Visual parameters (kept for AstrologyAPI compatibility)
    aspects: str = Field("all", description="Ignored — all aspects always returned")
    is_asteroid: bool = Field(True, description="Ignored — always returns Chiron")
    planet_icon_color: str = Field("#333333")
    inner_circle_background: str = Field("#FFF8E1")
    sign_icon_color: str = Field("#000000")
    sign_background: str = Field("#ffffff")
    chart_size: int = Field(500, ge=100, le=2000)
    image_type: str = Field("svg")


# ─── routes ──────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": "MacodeAstrologyAPI"}


@app.get("/license", tags=["meta"])
def license_info() -> dict[str, str]:
    """AGPL §13 source offer — unauthenticated so network users can find the code."""
    return {
        "license": "AGPL-3.0-only",
        "source": _SOURCE_URL,
        "license_url": "https://www.gnu.org/licenses/agpl-3.0.html",
        "notice": "This software uses Swiss Ephemeris (Astrodienst AG) under AGPL.",
    }


@app.get("/debug/ephe", tags=["meta"])
def debug_ephe() -> dict[str, Any]:
    """Check ephemeris file state inside the container."""
    import os
    from pathlib import Path
    import swisseph as swe

    ephe_dir = Path(__file__).parent.parent / "ephe"
    seas_path = ephe_dir / "seas_18.se1"
    try:
        swe.set_ephe_path(str(ephe_dir))
        jd = swe.julday(1972, 8, 3, 4.0)  # 06:00 UTC+2 → 04:00 UT
        res, flag = swe.calc_ut(jd, swe.CHIRON, swe.FLG_SWIEPH | swe.FLG_SPEED)
        chiron_ok = True
        chiron_lon = res[0]
    except Exception as exc:
        chiron_ok = False
        chiron_lon = None
        chiron_error = str(exc)

    return {
        "ephe_dir": str(ephe_dir),
        "ephe_dir_exists": ephe_dir.is_dir(),
        "seas_18_exists": seas_path.exists(),
        "seas_18_size_bytes": seas_path.stat().st_size if seas_path.exists() else 0,
        "chiron_calc_ok": chiron_ok,
        "chiron_lon": chiron_lon if chiron_ok else None,
        "chiron_error": chiron_error if not chiron_ok else None,
    }


@app.post("/v1/western_horoscope", dependencies=[Depends(_verify)], tags=["chart"])
def western_horoscope(req: HoroscopeRequest) -> dict[str, Any]:
    """
    Calcula mapa natal ocidental com Swiss Ephemeris.

    Retorna o mesmo formato de json.astrologyapi.com/v1/western_horoscope:
    planets, houses, aspects, lilith, ascendant, midheaven, vertex.
    """
    try:
        return calculate_western_horoscope(
            day=req.day,
            month=req.month,
            year=req.year,
            hour=req.hour,
            minute=req.min,
            lat=req.lat,
            lon=req.lon,
            tzone=req.tzone,
            house_type=req.house_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no cálculo do mapa: {exc}",
        ) from exc


@app.post("/v1/natal_wheel_chart", dependencies=[Depends(_verify)], tags=["chart"])
async def natal_wheel_chart(req: WheelChartRequest, request: Request) -> dict[str, Any]:
    """
    Gera roda astral natal em SVG, equivalente a json.astrologyapi.com/v1/natal_wheel_chart.

    Os parâmetros são codificados em base64 na própria URL (sem guardar em memória),
    eliminando problemas de load-balancing e restart do serviço.
    Retorna ``{"chart_url": "https://.../v1/charts/<token>.svg"}``.
    """
    # Build the absolute base URL — Railway terminates SSL externally so the
    # internal request arrives as http://.  Honour X-Forwarded-Proto header.
    base_url = os.getenv("BASE_URL", "").rstrip("/")
    if not base_url:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host   = request.headers.get("x-forwarded-host", request.url.netloc)
        base_url = f"{scheme}://{host}"

    token     = _encode_token(req)
    chart_url = f"{base_url}/v1/charts/{token}.svg"
    return {"chart_url": chart_url}


@app.get("/v1/charts/{token}.svg", tags=["chart"])
def serve_chart_svg(token: str) -> Response:
    """Decode chart parameters from the token, calculate and return the SVG."""
    try:
        p = _decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de chart inválido.",
        )

    try:
        chart_data = calculate_western_horoscope(
            day=p["d"], month=p["m"], year=p["y"],
            hour=p["h"], minute=p["n"],
            lat=p["la"], lon=p["lo"], tzone=p["tz"],
            house_type=p.get("hs", "placidus"),
        )
        svg_content = generate_wheel_svg(
            chart_data,
            chart_size=p.get("cs", 500),
            planet_icon_color=p.get("pic", "#333333"),
            inner_circle_background=p.get("icb", "#FFF8E1"),
            sign_icon_color=p.get("sic", "#000000"),
            sign_background=p.get("sb", "#ffffff"),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao gerar SVG: {exc}",
        ) from exc

    return Response(content=svg_content, media_type="image/svg+xml")
