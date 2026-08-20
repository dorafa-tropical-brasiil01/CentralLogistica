"""Repositório de ordens de serviço."""

from __future__ import annotations

import psycopg2.extras
from typing import Any

from app.core.db import connect
from app.core.ids import new_uuid


def create(
    *,
    conn,
    empresa_id: str,
    solicitacao_id: str,
    movimentacao_id: int | None = None,
    taxa: float | None = None,
    payload: dict[str, Any] | None = None,
    protocolo: str | None = None,
) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ordens_servico
            (uuid, empresa_id, solicitacao_id, movimentacao_id, taxa, payload_json, protocolo)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            new_uuid(),
            empresa_id,
            solicitacao_id,
            movimentacao_id,
            taxa,
            psycopg2.extras.Json(payload) if payload else None,
            protocolo,
        ),
    )
    return dict(cur.fetchone())


def get(ordem_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM ordens_servico WHERE id = %s", (ordem_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_by_uuid(ordem_uuid: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM ordens_servico WHERE uuid = %s", (ordem_uuid,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_by_solicitacao(empresa_id: str, solicitacao_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM ordens_servico
            WHERE empresa_id = %s AND solicitacao_id = %s
            ORDER BY id DESC LIMIT 1
            """,
            (empresa_id, solicitacao_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_status(conn, ordem_id: int, status: str, *, entregador_id: int | None = None) -> None:
    cur = conn.cursor()
    campos = ["status = %s"]
    valores: list[Any] = [status]

    if status == "EM_ROTA":
        campos.append("em_rota_em = NOW()")
    elif status == "ENTREGUE":
        campos.append("entregue_em = NOW()")
    elif status == "CANCELADO":
        campos.append("cancelado_em = NOW()")

    if entregador_id is not None:
        campos.append("entregador_id = %s")
        valores.append(entregador_id)

    valores.append(ordem_id)
    cur.execute(
        f"UPDATE ordens_servico SET {', '.join(campos)} WHERE id = %s",
        valores,
    )
