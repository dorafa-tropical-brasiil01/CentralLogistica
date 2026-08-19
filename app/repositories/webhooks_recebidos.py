"""Repositório de webhooks recebidos."""

from __future__ import annotations

import psycopg2.extras
from typing import Any

from app.core.db import connect


def registrar(
    *,
    conn,
    idempotency_key: str,
    abastecimento_id: int | None,
    origem: str,
    payload: dict[str, Any],
    processado: bool = False,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO webhooks_recebidos
            (idempotency_key, abastecimento_id, origem, payload_json, processado)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (
            idempotency_key,
            abastecimento_id,
            origem,
            psycopg2.extras.Json(payload),
            processado,
        ),
    )


def existe(idempotency_key: str, conn=None) -> bool:
    if conn is None:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM webhooks_recebidos WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            return cur.fetchone() is not None

    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM webhooks_recebidos WHERE idempotency_key = %s",
        (idempotency_key,),
    )
    return cur.fetchone() is not None
