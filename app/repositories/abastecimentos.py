"""Repositório de abastecimentos."""

from __future__ import annotations

import psycopg2.extras
from typing import Any

from app.core.db import connect, transaction
from app.core.ids import new_uuid


def create_pix(
    *,
    conn,
    empresa_id: str,
    carteira_id: int,
    valor: float,
    pix_payload: dict[str, Any],
    transacao_externa_id: str,
    expira_em: str | None = None,
) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO abastecimentos
            (uuid, empresa_id, carteira_id, valor, metodo, status,
             pix_payload, pix_txid, pix_linha_digitavel, pix_qr_code,
             transacao_externa_id, expira_em)
        VALUES (%s, %s, %s, %s, 'PIX', 'PENDENTE',
                %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            new_uuid(),
            empresa_id,
            carteira_id,
            valor,
            psycopg2.extras.Json(pix_payload),
            pix_payload.get("txid"),
            pix_payload.get("linha_digitavel"),
            pix_payload.get("qr_code"),
            transacao_externa_id,
            expira_em,
        ),
    )
    return dict(cur.fetchone())


def create_dinheiro(
    *,
    conn,
    empresa_id: str,
    carteira_id: int,
    valor: float,
    operador_id: int,
    caixa_operacao_id: int,
) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO abastecimentos
            (uuid, empresa_id, carteira_id, valor, metodo, status,
             operador_id, caixa_operacao_id, confirmado_em)
        VALUES (%s, %s, %s, %s, 'DINHEIRO', 'APROVADO',
                %s, %s, NOW())
        RETURNING *
        """,
        (
            new_uuid(),
            empresa_id,
            carteira_id,
            valor,
            operador_id,
            caixa_operacao_id,
        ),
    )
    return dict(cur.fetchone())


def get(abastecimento_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM abastecimentos WHERE id = %s", (abastecimento_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_by_uuid(ab_uuid: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM abastecimentos WHERE uuid = %s", (ab_uuid,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_pendente_for_update(conn, abastecimento_id: int) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM abastecimentos WHERE id = %s FOR UPDATE",
        (abastecimento_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def marcar_aprovado(conn, abastecimento_id: int, transacao_externa_id: str) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE abastecimentos
        SET status = 'APROVADO',
            confirmado_em = NOW(),
            transacao_externa_id = %s
        WHERE id = %s
        """,
        (transacao_externa_id, abastecimento_id),
    )


def get_by_transacao_externa(empresa_id: str, transacao_externa_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM abastecimentos
            WHERE empresa_id = %s AND transacao_externa_id = %s
            """,
            (empresa_id, transacao_externa_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
