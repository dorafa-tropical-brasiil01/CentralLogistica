"""Cálculo de frete independente da REMO.

Espelha o mecanismo de haversine do Cardápio/PDV, mas com configuração própria
para que a REMO calcule o custo real da entrega independentemente do que o
cliente pagou.
"""

from __future__ import annotations

import math
import re
from typing import Any


def _parse_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("R$", "").strip()
    s = s.replace(".", "").replace(",", ".") if "," in s else s
    try:
        return float(s)
    except Exception:
        return None


def resolve_short_url(url: str) -> str:
    """Segue redirects de URLs encurtadas (maps.app.goo.gl, goo.gl, bit.ly, etc)."""
    url = str(url or "").strip()
    if not url:
        return url
    # Só tenta resolver se for URL encurtada
    if "maps.app.goo.gl" not in url and "goo.gl/" not in url and "bit.ly/" not in url:
        return url
    try:
        import requests
        r = requests.get(url, allow_redirects=True, timeout=5)
        return r.url  # URL final após redirects
    except Exception:
        return url


def extract_lat_lng(s: str) -> tuple[float, float] | None:
    """Extrai latitude/longitude de uma URL ou texto do Google Maps."""
    s = str(s or "").strip()
    if not s:
        return None

    # Resolve URLs encurtadas antes de tentar extrair coordenadas
    s = resolve_short_url(s)

    m = re.search(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", s)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except Exception:
            return None

    m = re.search(r"q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", s)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except Exception:
            return None

    m = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", s)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except Exception:
            return None

    m = re.search(r"(?:\?|&|#)ll=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", s)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except Exception:
            return None

    m = re.search(r"(?:\?|&|#)query=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", s)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except Exception:
            return None

    return None


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def compute_fee(
    *,
    config: dict[str, Any],
    origin_maps_url: str,
    client_maps_url: str,
) -> dict[str, Any] | None:
    """Calcula o frete baseado na configuração da REMO e nas coordenadas.

    Retorna dict com fee, distance_km, etc. ou None se não for possível calcular.
    """
    if not isinstance(config, dict):
        return None

    enabled = config.get("enabled")
    v = str(enabled or "").strip().lower()
    if v not in ("1", "true", "yes", "y", "on"):
        if not bool(enabled):
            return None

    origin_url = str(config.get("origin_maps_url") or origin_maps_url or "").strip()
    if not origin_url:
        return None

    a = extract_lat_lng(origin_url)
    b = extract_lat_lng(str(client_maps_url or "").strip())
    if a is None or b is None:
        return None

    dist_km = haversine_km(a, b)

    base = _parse_float(config.get("base")) or 0.0
    per_km = _parse_float(config.get("per_km")) or 0.0
    min_v = _parse_float(config.get("min"))
    max_v = _parse_float(config.get("max"))

    fee = float(base) + float(per_km) * float(dist_km)

    if min_v is not None:
        fee = max(fee, float(min_v))
    if max_v is not None:
        fee = min(fee, float(max_v))

    # Arredondamento para valor cheio em reais
    try:
        floor_v = math.floor(float(fee))
        frac = float(fee) - float(floor_v)
        fee_int = int(floor_v + (1 if frac >= 0.5 else 0))
        fee = float(fee_int)
    except Exception:
        pass

    if min_v is not None:
        fee = max(fee, float(min_v))
    if max_v is not None:
        fee = min(fee, float(max_v))

    fee = round(fee + 1e-9, 2)
    dist_km = round(float(dist_km) + 1e-9, 3)

    return {
        "enabled": True,
        "fee": fee,
        "distance_km": dist_km,
        "origin_maps_url": origin_url,
        "client_maps_url": str(client_maps_url or "").strip(),
        "method": "haversine",
    }


def point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    """Verifica se um ponto (lat, lng) está dentro de um polígono [[lat,lng],...].

    Usa o algoritmo ray-casting.
    """
    if not polygon or len(polygon) < 3:
        return False

    lat, lng = point
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i][0], polygon[i][1]
        yj, xj = polygon[j][0], polygon[j][1]

        intersect = ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi
        )
        if intersect:
            inside = not inside
        j = i

    return inside


def compute_fee_by_zone(
    *,
    client_maps_url: str,
    areas: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Calcula o frete baseado na zona de cobertura onde o endereço cai.

    areas: lista de dicts com 'nome', 'taxa', 'poligono' ([[lat,lng],...])
    Retorna o primeiro match (menor taxa primeiro se houver empate).
    """
    client_url = str(client_maps_url or "").strip()
    if not client_url:
        return None

    coords = extract_lat_lng(client_url)
    if coords is None:
        return None

    for area in areas:
        poligono = area.get("poligono")
        if not poligono or len(poligono) < 3:
            continue
        if point_in_polygon(coords, poligono):
            return {
                "enabled": True,
                "fee": float(area.get("taxa") or 0),
                "distance_km": 0,
                "zone": area.get("nome"),
                "cidade": area.get("cidade"),
                "client_maps_url": client_url,
                "method": "zone",
            }

    return None
