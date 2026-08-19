"""Repositório de auditoria financeira."""

from __future__ import annotations

import psycopg2.extras
from typing import Any


def registrar(
    *,
    conn,
    carteira_id: int,
    tipo: str,
    movimentacao_id: int | None = None,
    abastecimento_id: int | None = None,
    caixa_operacao_id: int | None = None,
    referencia: str | None = None,
    dados: dict[str, Any],
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO auditoria_financeira
            (carteira_id, movimentacao_id, abastecimento_id, caixa_operacao_id,
             tipo, referencia, dados_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            carteira_id,
            movimentacao_id,
            abastecimento_id,
            caixa_operacao_id,
            tipo,
            referencia,
            psycopg2.extras.Json(dados),
        ),
    )
