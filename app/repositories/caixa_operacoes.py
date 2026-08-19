"""Repositório de operações de caixa."""

from __future__ import annotations

from typing import Any

from app.core.db import connect


def create(
    *,
    conn,
    caixa_id: int,
    operador_id: int,
    tipo: str,
    valor: float | None = None,
    saldo_inicial: float | None = None,
    saldo_final_sistema: float | None = None,
    saldo_contado: float | None = None,
    diferenca: float | None = None,
    motivo: str | None = None,
    abastecimento_id: int | None = None,
    movimentacao_id: int | None = None,
) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO caixa_operacoes
            (caixa_id, operador_id, tipo, valor, saldo_inicial,
             saldo_final_sistema, saldo_contado, diferenca, motivo,
             abastecimento_id, movimentacao_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            caixa_id,
            operador_id,
            tipo,
            valor,
            saldo_inicial,
            saldo_final_sistema,
            saldo_contado,
            diferenca,
            motivo,
            abastecimento_id,
            movimentacao_id,
        ),
    )
    return dict(cur.fetchone())


def list_by_caixa(caixa_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM caixa_operacoes
            WHERE caixa_id = %s
            ORDER BY id
            """,
            (caixa_id,),
        )
        return [dict(r) for r in cur.fetchall()]
