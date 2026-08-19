"""Orquestração de abastecimento de carteira."""

from __future__ import annotations

import hashlib
from typing import Any

from app.core.config import is_pix_online_enabled
from app.core.db import transaction
from app.repositories import abastecimentos, auditoria_financeira, webhooks_recebidos
from app.services import movimentacoes


def _hash_idempotencia(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def criar_pix(
    *,
    empresa_id: str,
    carteira_id: int,
    valor: float,
    pix_payload: dict[str, Any],
    transacao_externa_id: str,
    expira_em: str | None = None,
) -> dict[str, Any]:
    if not is_pix_online_enabled():
        raise RuntimeError("pix_online_desabilitado")

    with transaction() as conn:
        return abastecimentos.create_pix(
            conn=conn,
            empresa_id=empresa_id,
            carteira_id=carteira_id,
            valor=valor,
            pix_payload=pix_payload,
            transacao_externa_id=transacao_externa_id,
            expira_em=expira_em,
        )


def confirmar_pix(*, abastecimento_id: int, idempotency_key: str, transacao_externa_id: str) -> dict[str, Any]:
    with transaction() as conn:
        # Idempotência do webhook dentro da mesma transação
        if webhooks_recebidos.existe(idempotency_key, conn=conn):
            ab = abastecimentos.get(abastecimento_id)
            return ab if ab else {}

        ab = abastecimentos.get_pendente_for_update(conn, abastecimento_id)
        if not ab:
            raise RuntimeError("Abastecimento não encontrado")

        if ab["status"] == "APROVADO":
            webhooks_recebidos.registrar(
                conn=conn,
                idempotency_key=idempotency_key,
                abastecimento_id=abastecimento_id,
                origem="PAGBANK",
                payload={"reprocessamento": True},
                processado=True,
            )
            return ab

        if ab["status"] not in ("PENDENTE", "EXPIRADO"):
            raise RuntimeError(f"Abastecimento não pode ser confirmado: {ab['status']}")

        abastecimentos.marcar_aprovado(conn, abastecimento_id, transacao_externa_id)

        mov = movimentacoes.criar(
            conn=conn,
            carteira_id=ab["carteira_id"],
            tipo="CREDITO",
            valor=float(ab["valor"]),
            descricao=f"Crédito por PIX {ab['uuid']}",
            abastecimento_id=abastecimento_id,
            idempotency_key=idempotency_key,
            referencia_externa=transacao_externa_id,
        )

        webhooks_recebidos.registrar(
            conn=conn,
            idempotency_key=idempotency_key,
            abastecimento_id=abastecimento_id,
            origem="PAGBANK",
            payload={"transacao_externa_id": transacao_externa_id},
            processado=True,
        )

        auditoria_financeira.registrar(
            conn=conn,
            carteira_id=ab["carteira_id"],
            movimentacao_id=mov["id"],
            abastecimento_id=abastecimento_id,
            tipo="CREDITO_PIX",
            referencia=ab["uuid"],
            dados={"transacao_externa_id": transacao_externa_id, "valor": float(ab["valor"])},
        )

        return abastecimentos.get(abastecimento_id) or {}
