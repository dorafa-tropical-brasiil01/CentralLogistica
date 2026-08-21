"""Repositório de áreas de cobertura."""

from __future__ import annotations

import json
from typing import Any

from app.core.db import connect


def listar_ativas_por_empresa(empresa_id: str) -> list[dict[str, Any]]:
    """Lista áreas ativas de uma empresa com polígonos."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nome, cidade, taxa, poligono, status
            FROM areas_cobertura
            WHERE empresa_id = %s AND status = 'ATIVO'
            ORDER BY taxa ASC
        """, (empresa_id,))
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            poligono = r.get("poligono")
            if isinstance(poligono, str):
                try:
                    poligono = json.loads(poligono)
                except Exception:
                    poligono = None
            items.append({
                "id": r["id"],
                "nome": r["nome"],
                "cidade": r.get("cidade"),
                "taxa": float(r["taxa"] or 0),
                "poligono": poligono,
            })
    return items


def listar_todas_ativas() -> list[dict[str, Any]]:
    """Lista todas as áreas ativas (todas as empresas)."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, empresa_id, nome, cidade, taxa, poligono, status
            FROM areas_cobertura
            WHERE status = 'ATIVO'
            ORDER BY empresa_id, taxa ASC
        """)
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            poligono = r.get("poligono")
            if isinstance(poligono, str):
                try:
                    poligono = json.loads(poligono)
                except Exception:
                    poligono = None
            items.append({
                "id": r["id"],
                "empresa_id": r.get("empresa_id"),
                "nome": r["nome"],
                "cidade": r.get("cidade"),
                "taxa": float(r["taxa"] or 0),
                "poligono": poligono,
            })
    return items
