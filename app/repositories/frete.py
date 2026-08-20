"""Repositório de configuração de frete por empresa."""

from __future__ import annotations

from typing import Any

from app.core.db import connect, transaction


def get(empresa_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM frete_config WHERE empresa_id = %s",
            (empresa_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)


def upsert(
    *,
    empresa_id: str,
    enabled: bool | None = None,
    origin_maps_url: str | None = None,
    base: float | None = None,
    per_km: float | None = None,
    min_v: float | None = None,
    max_v: float | None = None,
) -> dict[str, Any]:
    atual = get(empresa_id) or {}

    novo_enabled = enabled if enabled is not None else bool(atual.get("enabled") or False)
    novo_origin = origin_maps_url if origin_maps_url is not None else (atual.get("origin_maps_url") or "")
    novo_base = base if base is not None else _to_float(atual.get("base"))
    novo_per_km = per_km if per_km is not None else _to_float(atual.get("per_km"))
    novo_min = min_v if min_v is not None else _to_float(atual.get("min_v"))
    novo_max = max_v if max_v is not None else _to_float(atual.get("max_v"))

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO frete_config
                (empresa_id, enabled, origin_maps_url, base, per_km, min_v, max_v)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (empresa_id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                origin_maps_url = EXCLUDED.origin_maps_url,
                base = EXCLUDED.base,
                per_km = EXCLUDED.per_km,
                min_v = EXCLUDED.min_v,
                max_v = EXCLUDED.max_v,
                atualizado_em = NOW()
            RETURNING *
            """,
            (empresa_id, novo_enabled, novo_origin, novo_base, novo_per_km, novo_min, novo_max),
        )
        row = cur.fetchone()
        return dict(row) if row else {}


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None
