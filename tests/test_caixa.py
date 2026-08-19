"""Testes de caixa físico."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.migracoes.runner import ensure_schema
from app.repositories import carteiras, empresas, usuarios
from app.services import caixa as caixa_service


def _require_db():
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("Defina DATABASE_URL para rodar os testes")


def _setup():
    from app.core.ids import new_uuid
    empresa_id = f"EMP_{new_uuid().replace('-','')[:8]}"
    empresas.create(empresa_id, f"Empresa Teste {empresa_id}")
    op = usuarios.create("operador1", "Operador 1", "OPERADOR", empresa_id=empresa_id)
    caixa = caixa_service.create("CAIXA-01")
    carteira = carteiras.get_by_empresa(empresa_id)
    return empresa_id, carteira["id"], op["id"], caixa["id"]


def test_abastecimento_dinheiro():
    _require_db()
    ensure_schema()
    empresa_id, carteira_id, operador_id, caixa_id = _setup()

    caixa_service.abrir(caixa_id, operador_id, 0)
    ab = caixa_service.abastecer_em_dinheiro(
        empresa_id=empresa_id,
        carteira_id=carteira_id,
        valor=100.00,
        operador_id=operador_id,
        caixa_id=caixa_id,
    )

    carteira = carteiras.get(carteira_id)
    assert float(carteira["saldo_atual"]) == 100.00
    assert ab["metodo"] == "DINHEIRO"
    print("[OK] test_abastecimento_dinheiro")


def test_caixa_fechado_rejeita_abastecimento():
    _require_db()
    ensure_schema()
    empresa_id, carteira_id, operador_id, caixa_id = _setup()

    try:
        caixa_service.abastecer_em_dinheiro(
            empresa_id=empresa_id,
            carteira_id=carteira_id,
            valor=50.00,
            operador_id=operador_id,
            caixa_id=caixa_id,
        )
    except RuntimeError as e:
        if str(e) == "caixa_fechado":
            print("[OK] test_caixa_fechado_rejeita_abastecimento")
            return
    raise AssertionError("Esperava caixa_fechado")


if __name__ == "__main__":
    test_abastecimento_dinheiro()
    test_caixa_fechado_rejeita_abastecimento()
