"""Testes de PIX online."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.migracoes.runner import ensure_schema
from app.pix import service as pix_service
from app.pix.webhook import processar as processar_webhook
from app.repositories import abastecimentos, carteiras, empresas
from app.services import abastecimento


def _require_db():
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("Defina DATABASE_URL para rodar os testes")


def _setup():
    from app.core.ids import new_uuid
    empresa_id = f"EMP_{new_uuid().replace('-','')[:8]}"
    empresas.create(empresa_id, f"Empresa Teste {empresa_id}")
    return empresa_id


def test_criar_cobranca_pix():
    _require_db()
    ensure_schema()
    empresa_id = _setup()
    cobranca = pix_service.criar_cobranca(empresa_id=empresa_id, valor=50.00)

    assert cobranca["valor"] == 50.00
    assert cobranca["provider_transaction_id"]
    assert cobranca["qr_code"]

    ab = abastecimentos.get_by_uuid(cobranca["uuid"])
    assert ab["status"] == "PENDENTE"
    print("[OK] test_criar_cobranca_pix")


def test_confirmar_pix_creditando_carteira():
    _require_db()
    ensure_schema()
    empresa_id = _setup()
    cobranca = pix_service.criar_cobranca(empresa_id=empresa_id, valor=50.00)
    ab_id = cobranca["abastecimento_id"]

    body = json.dumps({"id": cobranca["provider_transaction_id"], "status": "PAID"}).encode()
    result = abastecimento.confirmar_pix(
        abastecimento_id=ab_id,
        idempotency_key=processar_webhook.__module__ + "_" + cobranca["provider_transaction_id"],
        transacao_externa_id=cobranca["provider_transaction_id"],
    )

    carteira = carteiras.get_by_empresa(empresa_id)
    assert float(carteira["saldo_atual"]) == 50.00
    assert result["status"] == "APROVADO"
    print("[OK] test_confirmar_pix_creditando_carteira")


def test_confirmar_pix_idempotente():
    _require_db()
    ensure_schema()
    empresa_id = _setup()
    cobranca = pix_service.criar_cobranca(empresa_id=empresa_id, valor=50.00)
    ab_id = cobranca["abastecimento_id"]
    idem = "idem-pix-1"

    abastecimento.confirmar_pix(
        abastecimento_id=ab_id,
        idempotency_key=idem,
        transacao_externa_id=cobranca["provider_transaction_id"],
    )

    abastecimento.confirmar_pix(
        abastecimento_id=ab_id,
        idempotency_key=idem,
        transacao_externa_id=cobranca["provider_transaction_id"],
    )

    carteira = carteiras.get_by_empresa(empresa_id)
    assert float(carteira["saldo_atual"]) == 50.00
    print("[OK] test_confirmar_pix_idempotente")


if __name__ == "__main__":
    test_criar_cobranca_pix()
    test_confirmar_pix_creditando_carteira()
    test_confirmar_pix_idempotente()
