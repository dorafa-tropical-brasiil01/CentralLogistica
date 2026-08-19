"""Repositório de movimentações de carteira."""

from __future__ import annotations

from typing import Any

from app.core.db import connect
from app.core.ids import new_uuid


def create(
    *,
    conn,
    carteira_id: int,
    tipo: str,
    valor: float,
    saldo_anterior: float,
    saldo_final: float,
    abastecimento_id: int | None = None,
    caixa_operacao_id: int | None = None,
    ordem_id: int | None = None,
    descricao: str | None = None,
    idempotency_key: str | None = None,
    referencia_externa: str | None = None,
) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO movimentacoes_carteira
            (uuid, carteira_id, abastecimento_id, caixa_operacao_id, ordem_id,
             tipo, descricao, valor, saldo_anterior, saldo_final,
             idempotency_key, referencia_externa)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            new_uuid(),
            carteira_id,
            abastecimento_id,
            caixa_operacao_id,
            ordem_id,
            tipo,
            descricao,
            valor,
            saldo_anterior,
            saldo_final,
            idempotency_key,
            referencia_externa,
        ),
    )
    return dict(cur.fetchone())


def list_by_carteira(carteira_id: int, limite: int = 100) -> list[dict[str, Any]]:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM movimentacoes_carteira
            WHERE carteira_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (carteira_id, limite),
        )
        return [dict(r) for r in cur.fetchall()]


def get_by_idempotency(idempotency_key: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM movimentacoes_carteira WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
