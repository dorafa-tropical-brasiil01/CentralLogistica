"""Repositório de usuários."""

from __future__ import annotations

from typing import Any

from app.core.db import transaction


def create(username: str, nome: str, perfil: str, empresa_id: str | None = None, **campos: Any) -> dict[str, Any]:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO usuarios (username, nome, perfil, empresa_id, telefone, ativo)
            VALUES (%s, %s, %s, %s, %s, TRUE)
            RETURNING *
            """,
            (username, nome, perfil, empresa_id, campos.get("telefone")),
        )
        return dict(cur.fetchone())


def get(usuario_id: int) -> dict[str, Any] | None:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE id = %s", (usuario_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_by_username(username: str) -> dict[str, Any] | None:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE username = %s", (username,))
        row = cur.fetchone()
        return dict(row) if row else None
