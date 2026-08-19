"""Testes de crédito, débito e concorrência."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.core.db import transaction
from app.migracoes.runner import ensure_schema
from app.repositories import carteiras, empresas, movimentacoes_carteira
from app.services import movimentacoes


def _require_db():
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("Defina DATABASE_URL para rodar os testes")


def _criar_empresa_carteira():
    from app.core.ids import new_uuid
    empresa_id = f"EMP_{new_uuid().replace('-','')[:8]}"
    empresas.create(empresa_id, f"Empresa Teste {empresa_id}")
    carteira = carteiras.get_by_empresa(empresa_id)
    return empresa_id, carteira["id"]


def _creditar(carteira_id: int, valor: float, descricao: str = "") -> None:
    with transaction() as conn:
        movimentacoes.criar(
            conn=conn,
            carteira_id=carteira_id,
            tipo="CREDITO",
            valor=valor,
            descricao=descricao,
        )


def test_credito_e_saldo():
    _require_db()
    ensure_schema()
    _, carteira_id = _criar_empresa_carteira()
    _creditar(carteira_id, 100.00, "Crédito teste")
    carteira = carteiras.get(carteira_id)
    assert float(carteira["saldo_atual"]) == 100.00
    print("[OK] test_credito_e_saldo")


def test_debito_saldo_insuficiente():
    _require_db()
    ensure_schema()
    _, carteira_id = _criar_empresa_carteira()
    _creditar(carteira_id, 50.00)
    try:
        with transaction() as conn:
            movimentacoes.criar(
                conn=conn,
                carteira_id=carteira_id,
                tipo="DEBITO",
                valor=60.00,
                descricao="Débito maior que saldo",
            )
    except RuntimeError as e:
        if str(e) == "saldo_insuficiente":
            print("[OK] test_debito_saldo_insuficiente")
            return
    raise AssertionError("Esperava saldo_insuficiente")


def test_concorrencia_debito():
    _require_db()
    ensure_schema()
    _, carteira_id = _criar_empresa_carteira()
    _creditar(carteira_id, 100.00)

    resultados = {"sucesso": 0, "falha": 0, "erros": []}

    def tentar_debitar(valor: float, idem: str):
        try:
            with transaction() as conn:
                movimentacoes.criar(
                    conn=conn,
                    carteira_id=carteira_id,
                    tipo="DEBITO",
                    valor=valor,
                    descricao="Débito concorrente",
                    idempotency_key=idem,
                )
            resultados["sucesso"] += 1
        except RuntimeError as e:
            if str(e) == "saldo_insuficiente":
                resultados["falha"] += 1
            else:
                resultados["erros"].append(str(e))

    threads = [
        threading.Thread(target=tentar_debitar, args=(60.00, "idem-debito-1")),
        threading.Thread(target=tentar_debitar, args=(60.00, "idem-debito-2")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    carteira = carteiras.get(carteira_id)
    saldo = float(carteira["saldo_atual"])

    assert resultados["sucesso"] == 1, f"Esperava 1 sucesso, obteve {resultados}"
    assert resultados["falha"] == 1, f"Esperava 1 falha, obteve {resultados}"
    assert saldo == 40.00, f"Saldo deveria ser 40.00, obteve {saldo}"
    print("[OK] test_concorrencia_debito")


if __name__ == "__main__":
    test_credito_e_saldo()
    test_debito_saldo_insuficiente()
    test_concorrencia_debito()
