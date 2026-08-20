"""Serviço de PIX da REMO."""

from __future__ import annotations

from typing import Any

from app.core import config
from app.core.db import transaction
from app.pix.adapter_contract import CreatePaymentRequest, PaymentMethod
from app.repositories import abastecimentos, carteiras, empresas


def build_adapter():
    from app.pix.mock_adapter import MockAdapter
    from app.pix.pagbank_adapter import PagBankAdapter

    if config.PIX_PROVIDER == "pagbank" and config.PIX_TOKEN:
        return PagBankAdapter(
            token=config.PIX_TOKEN,
            webhook_token=config.PIX_WEBHOOK_SECRET or None,
            sandbox=config.PIX_PROVIDER == "sandbox",
        )
    return MockAdapter()


def criar_cobranca(*, empresa_id: str, valor: float, descricao: str | None = None) -> dict[str, Any]:
    empresa = empresas.get(empresa_id)
    if not empresa:
        raise RuntimeError("empresa_nao_encontrada")

    carteira = carteiras.get_by_empresa(empresa_id)
    if not carteira:
        raise RuntimeError("carteira_nao_encontrada")

    adapter = build_adapter()
    reference_id = empresa_id

    result = adapter.create_payment(
        request=CreatePaymentRequest(
            amount=valor,
            payment_method=PaymentMethod.PIX,
            reference_id=reference_id,
            description=descricao or f"Abastecimento {empresa_id}",
        )
    )

    with transaction() as conn:
        ab = abastecimentos.create_pix(
            conn=conn,
            empresa_id=empresa_id,
            carteira_id=carteira["id"],
            valor=valor,
            pix_payload={
                "txid": result.provider_transaction_id,
                "linha_digitavel": result.qr_code.payload if result.qr_code else "",
                "qr_code": result.qr_code.payload if result.qr_code else "",
                "image_url": result.qr_code.image_url if result.qr_code else None,
                "expires_at": result.expires_at.isoformat() if result.expires_at else None,
            },
            transacao_externa_id=result.provider_transaction_id,
            expira_em=result.expires_at.isoformat() if result.expires_at else None,
        )

    return {
        "abastecimento_id": ab["id"],
        "uuid": ab["uuid"],
        "valor": valor,
        "qr_code": result.qr_code.payload if result.qr_code else None,
        "qr_code_image_url": result.qr_code.image_url if result.qr_code else None,
        "expires_at": result.expires_at.isoformat() if result.expires_at else None,
        "provider_transaction_id": result.provider_transaction_id,
    }
