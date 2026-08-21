"""Repositório de áreas de cobertura (zonas globais por cidade)."""

from __future__ import annotations

import json
from typing import Any

from app.core.db import connect


def _parse_poligono(raw: Any) -> list | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    return raw


def listar_ativas_por_cidade(cidade: str) -> list[dict[str, Any]]:
    """Lista áreas ativas de uma cidade (zonas globais) com polígonos."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nome, cidade, taxa, poligono, cor, status
            FROM areas_cobertura
            WHERE cidade ILIKE %s AND status = 'ATIVO'
            ORDER BY taxa ASC
        """, (cidade,))
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            items.append({
                "id": r["id"],
                "nome": r["nome"],
                "cidade": r.get("cidade"),
                "taxa": float(r["taxa"] or 0),
                "poligono": _parse_poligono(r.get("poligono")),
                "cor": r.get("cor") or "#00d4aa",
            })
    return items


def listar_ativas_por_empresa(empresa_id: str) -> list[dict[str, Any]]:
    """Lista áreas ativas vinculadas a uma empresa específica (override).

    Na maioria dos casos as zonas são globais (empresa_id=NULL).
    Este método retorna apenas zonas específicas da empresa, se houver.
    """
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nome, cidade, taxa, poligono, cor, status
            FROM areas_cobertura
            WHERE empresa_id = %s AND status = 'ATIVO'
            ORDER BY taxa ASC
        """, (empresa_id,))
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            items.append({
                "id": r["id"],
                "nome": r["nome"],
                "cidade": r.get("cidade"),
                "taxa": float(r["taxa"] or 0),
                "poligono": _parse_poligono(r.get("poligono")),
                "cor": r.get("cor") or "#00d4aa",
            })
    return items


def listar_todas_ativas() -> list[dict[str, Any]]:
    """Lista todas as áreas ativas (todas as cidades)."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, empresa_id, nome, cidade, taxa, poligono, cor, status
            FROM areas_cobertura
            WHERE status = 'ATIVO'
            ORDER BY cidade, taxa ASC
        """)
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            items.append({
                "id": r["id"],
                "empresa_id": r.get("empresa_id"),
                "nome": r["nome"],
                "cidade": r.get("cidade"),
                "taxa": float(r["taxa"] or 0),
                "poligono": _parse_poligono(r.get("poligono")),
                "cor": r.get("cor") or "#00d4aa",
            })
    return items


def listar_cidades_com_zonas() -> list[str]:
    """Lista cidades que têm zonas de cobertura ativas."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT cidade FROM areas_cobertura
            WHERE status = 'ATIVO' AND cidade IS NOT NULL
            ORDER BY cidade
        """)
        return [r["cidade"] for r in (dict(x) for x in cur.fetchall())]
