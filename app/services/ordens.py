"""Serviço de ordens de serviço de logística."""

from __future__ import annotations

from typing import Any

from app.core.db import transaction
from app.core.ids import new_uuid
from app.repositories import carteiras, empresas, ordens
from app.services import movimentacoes, webhooks_enviados


def criar(
    *,
    empresa_id: str,
    solicitacao_id: str,
    taxa: float,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Cria ordem de serviço debitando a taxa da carteira."""
    empresa = empresas.get(empresa_id)
    if not empresa:
        raise RuntimeError("empresa_nao_encontrada")

    carteira = carteiras.get_by_empresa(empresa_id)
    if not carteira:
        raise RuntimeError("carteira_nao_encontrada")

    if taxa < 0:
        raise RuntimeError("taxa_invalida")

    with transaction() as conn:
        # Evita duplicidade por solicitacao
        ordem_existente = ordens.get_by_solicitacao(empresa_id, solicitacao_id)
        if ordem_existente:
            return ordem_existente

        try:
            mov = movimentacoes.criar(
                conn=conn,
                carteira_id=carteira["id"],
                tipo="DEBITO",
                valor=taxa,
                descricao=f"Taxa de entrega pedido {solicitacao_id}",
                idempotency_key=idempotency_key,
            )
        except RuntimeError as e:
            if str(e) == "saldo_insuficiente":
                raise RuntimeError("saldo_insuficiente")
            raise

        protocolo = f"OS-{new_uuid().replace('-', '')[:12].upper()}"
        ordem = ordens.create(
            conn=conn,
            empresa_id=empresa_id,
            solicitacao_id=solicitacao_id,
            movimentacao_id=mov["id"],
            taxa=taxa,
            payload=payload,
            protocolo=protocolo,
        )

        return ordem


def atualizar_status(
    *,
    ordem_id: int,
    status: str,
    entregador_id: int | None = None,
) -> dict[str, Any]:
    with transaction() as conn:
        ordens.update_status(conn, ordem_id, status, entregador_id=entregador_id)

    ordem = ordens.get(ordem_id) or {}

    # Notifica Cardápio sobre mudança de status
    if status in ("ATRIBUIDO", "EM_ROTA", "ENTREGUE"):
        webhooks_enviados.enviar_status(
            solicitacao_id=str(ordem.get("solicitacao_id") or ""),
            status=status,
            empresa_id=str(ordem.get("empresa_id") or ""),
            ordem_uuid=ordem.get("uuid"),
            protocolo=ordem.get("protocolo"),
        )

    return ordem
