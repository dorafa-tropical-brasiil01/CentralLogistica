"""Serviço de map matching (snap-to-roads) e roteamento usando OSRM.

Usa a API pública do OSRM por padrão. Para produção, recomenda-se
deployar uma instância própria do OSRM com dados de mapa do Brasil.

Endpoints usados:
- /match/v1/driving/{coords}?overview=full&geometries=geojson  (snap-to-roads)
- /route/v1/driving/{coords}?overview=full&geometries=geojson  (rota planejada)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# URL do OSRM. Pode ser override via env var OSRM_URL.
# Demo público: https://router.project-osrm.org
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org").rstrip("/")


def snap_to_road(points: list[tuple[float, float]]) -> list[tuple[float, float]] | None:
    """Ajusta pontos GPS à malha viária usando OSRM map matching.

    Args:
        points: lista de (lat, lng) — máximo 100 pontos

    Returns:
        lista de (lat, lng) ajustados às ruas, ou None se falhar.
    """
    if not points or len(points) < 2:
        return None

    # OSRM aceita no máximo 100 pontos por requisição
    if len(points) > 100:
        points = points[-100:]  # pega os últimos 100

    try:
        import requests

        # OSRM espera coords no formato lng,lat;lng,lat;...
        coords_str = ";".join(f"{lng},{lat}" for lat, lng in points)
        url = f"{OSRM_URL}/match/v1/driving/{coords_str}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
            "annotations": "false",
        }

        r = requests.get(url, params=params, timeout=10)

        if r.status_code != 200:
            logger.warning("OSRM match retornou %s: %s", r.status_code, r.text[:200])
            return None

        data = r.json()
        if data.get("code") != "Ok":
            logger.warning("OSRM match code=%s: %s", data.get("code"), data.get("message", ""))
            return None

        # Extrai a geometria da rota ajustada
        matchings = data.get("matchings", [])
        if not matchings:
            logger.warning("OSRM match: sem matchings")
            return None

        geometry = matchings[0].get("geometry", {})
        coordinates = geometry.get("coordinates", [])

        if not coordinates:
            return None

        # OSRM retorna [lng, lat], converte para [lat, lng]
        snapped = [(coord[1], coord[0]) for coord in coordinates]
        logger.info("OSRM snap: %d pontos GPS → %d pontos snapped", len(points), len(snapped))
        return snapped

    except Exception as e:
        logger.error("OSRM snap erro: %s", e)
        return None


def calcular_rota(
    origem: tuple[float, float],
    destino: tuple[float, float],
) -> list[tuple[float, float]] | None:
    """Calcula rota planejada entre origem e destino usando OSRM.

    Args:
        origem: (lat, lng)
        destino: (lat, lng)

    Returns:
        lista de (lat, lng) seguindo a malha viária, ou None se falhar.
    """
    try:
        import requests

        coords_str = f"{origem[1]},{origem[0]};{destino[1]},{destino[0]}"
        url = f"{OSRM_URL}/route/v1/driving/{coords_str}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
            "alternatives": "false",
        }

        r = requests.get(url, params=params, timeout=10)

        if r.status_code != 200:
            logger.warning("OSRM route retornou %s: %s", r.status_code, r.text[:200])
            return None

        data = r.json()
        if data.get("code") != "Ok":
            logger.warning("OSRM route code=%s: %s", data.get("code"), data.get("message", ""))
            return None

        routes = data.get("routes", [])
        if not routes:
            return None

        geometry = routes[0].get("geometry", {})
        coordinates = geometry.get("coordinates", [])

        if not coordinates:
            return None

        # OSRM retorna [lng, lat], converte para [lat, lng]
        rota = [(coord[1], coord[0]) for coord in coordinates]
        logger.info("OSRM route: %d pontos na rota", len(rota))
        return rota

    except Exception as e:
        logger.error("OSRM route erro: %s", e)
        return None
