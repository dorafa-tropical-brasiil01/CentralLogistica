"""Repositório de caixas."""

from __future__ import annotations

from typing import Any

from app.core.db import connect, transaction


def create(nome: str) -> dict[str, Any]:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO caixas (nome) VALUES (%s) RETURNING *",
            (nome,),
        )
        return dict(cur.fetchone())


def get(caixa_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM caixas WHERE id = %s", (caixa_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_aberto() -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM caixas WHERE status = 'ABERTO' LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None


def abrir(conn, caixa_id: int, operador_id: int, saldo_inicial: float) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE caixas
        SET status = 'ABERTO',
            operador_abertura_id = %s,
            aberto_em = NOW(),
            saldo_esperado = %s
        WHERE id = %s
        RETURNING *
        """,
        (operador_id, saldo_inicial, caixa_id),
    )
    return dict(cur.fetchone())


def fechar(conn, caixa_id: int, saldo_esperado: float) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE caixas
        SET status = 'FECHADO',
            operador_abertura_id = NULL,
            aberto_em = NULL,
            saldo_esperado = %s
        WHERE id = %s
        RETURNING *
        """,
        (saldo_esperado, caixa_id),
    )
    return dict(cur.fetchone())
