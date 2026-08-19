"""Processamento de webhooks de PIX."""

from __future__ import annotations

from typing import Any

from app.pix import service
from app.services import abastecimento


def processar(*, headers: dict[str, str], body: bytes) -> dict[str, Any] | None:
    adapter = service.build_adapter()
    event = adapter.validate_webhook(headers, body)
    if event is None:
        return None

    # Localiza abastecimento pelo provider_transaction_id
    from app.repositories import abastecimentos
    ab = abastecimentos.get_by_transacao_externa(
        empresa_id=event.provider_transaction_id.split("_")[0],
        transacao_externa_id=event.provider_transaction_id,
    )
    if ab is None:
        # Fallback por empresa_id não confiável em MOCK; busca por transacao_externa_id
        ab = _buscar_por_transacao(event.provider_transaction_id)

    if ab is None:
        return None

    return abastecimento.confirmar_pix(
        abastecimento_id=ab["id"],
        idempotency_key=event.event_id,
        transacao_externa_id=event.provider_transaction_id,
    )


def _buscar_por_transacao(transacao_externa_id: str) -> dict[str, Any] | None:
    from app.core.db import connect
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM abastecimentos WHERE transacao_externa_id = %s",
            (transacao_externa_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
