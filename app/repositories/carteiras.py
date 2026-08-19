"""Repositório de carteiras."""

from __future__ import annotations

from typing import Any

from app.core.db import connect, transaction


def get(carteira_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM carteiras WHERE id = %s", (carteira_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_by_empresa(empresa_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM carteiras WHERE empresa_id = %s", (empresa_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def bloquear_e_ler(conn, carteira_id: int) -> float:
    """Bloqueia a carteira com FOR UPDATE e retorna saldo atual."""
    cur = conn.cursor()
    cur.execute(
        "SELECT saldo_atual FROM carteiras WHERE id = %s FOR UPDATE",
        (carteira_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("Carteira não encontrada")
    return float(row["saldo_atual"])


def atualizar_saldo(conn, carteira_id: int, saldo: float) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE carteiras SET saldo_atual = %s WHERE id = %s",
        (saldo, carteira_id),
    )
