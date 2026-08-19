"""Repositório de empresas."""

from __future__ import annotations

import psycopg2.extras
from typing import Any

from app.core.db import transaction


def create(empresa_id: str, nome: str, **campos: Any) -> dict[str, Any]:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO empresas (id, nome, cnpj, telefone, email, endereco, config)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                empresa_id,
                nome,
                campos.get("cnpj"),
                campos.get("telefone"),
                campos.get("email"),
                psycopg2.extras.Json(campos.get("endereco")) if campos.get("endereco") else None,
                psycopg2.extras.Json(campos.get("config")) if campos.get("config") else None,
            ),
        )
        row = cur.fetchone()

        cur.execute(
            """
            INSERT INTO carteiras (empresa_id, saldo_atual)
            VALUES (%s, 0)
            RETURNING *
            """,
            (empresa_id,),
        )

        return dict(row)


def get(empresa_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM empresas WHERE id = %s", (empresa_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_all() -> list[dict[str, Any]]:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM empresas WHERE ativo = TRUE ORDER BY nome")
        return [dict(r) for r in cur.fetchall()]
