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


def list_entregadores() -> list[dict[str, Any]]:
    """Lista todos os entregadores ativos."""
    from app.core.db import connect
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, username, nome, telefone, perfil, empresa_id, ativo,
                   localizacao_atual, ultima_localizacao_em
            FROM usuarios
            WHERE perfil = 'ENTREGADOR' AND ativo = TRUE
            ORDER BY nome
            """,
        )
        return [dict(r) for r in cur.fetchall()]


def update_localizacao(usuario_id: int, lat: float, lng: float, precisao: float | None = None) -> None:
    """Atualiza localização atual do entregador."""
    import psycopg2.extras
    from app.core.db import transaction
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE usuarios
            SET localizacao_atual = %s, ultima_localizacao_em = NOW()
            WHERE id = %s
            """,
            (psycopg2.extras.Json({"lat": lat, "lng": lng, "precisao": precisao}), usuario_id),
        )


def list_despachadores() -> list[dict[str, Any]]:
    """Lista despachadores/central ativos."""
    from app.core.db import connect
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, username, nome, telefone, perfil, ativo
            FROM usuarios
            WHERE perfil IN ('ADMIN', 'CENTRAL') AND ativo = TRUE
            ORDER BY nome
            """,
        )
        return [dict(r) for r in cur.fetchall()]
