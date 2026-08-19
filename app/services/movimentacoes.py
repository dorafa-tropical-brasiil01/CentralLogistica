"""Motor de movimentação de carteira com consistência transacional."""

from __future__ import annotations

from typing import Any

from app.repositories import carteiras, movimentacoes_carteira


def calcular_saldo_final(saldo_anterior: float, tipo: str, valor: float) -> float:
    if tipo in ("CREDITO", "ESTORNO"):
        return round(saldo_anterior + valor, 2)
    if tipo == "DEBITO":
        return round(saldo_anterior - abs(valor), 2)
    if tipo == "AJUSTE":
        return round(saldo_anterior + valor, 2)
    raise RuntimeError(f"Tipo de movimentação inválido: {tipo}")


def validar_saldo(saldo_final: float) -> None:
    if saldo_final < 0:
        raise RuntimeError("saldo_insuficiente")


def criar(
    *,
    conn,
    carteira_id: int,
    tipo: str,
    valor: float,
    descricao: str | None = None,
    abastecimento_id: int | None = None,
    caixa_operacao_id: int | None = None,
    ordem_id: int | None = None,
    idempotency_key: str | None = None,
    referencia_externa: str | None = None,
) -> dict[str, Any]:
    """Cria movimentação atômica com bloqueio FOR UPDATE."""
    saldo_anterior = carteiras.bloquear_e_ler(conn, carteira_id)
    saldo_final = calcular_saldo_final(saldo_anterior, tipo, valor)
    validar_saldo(saldo_final)

    mov = movimentacoes_carteira.create(
        conn=conn,
        carteira_id=carteira_id,
        tipo=tipo,
        valor=valor,
        saldo_anterior=saldo_anterior,
        saldo_final=saldo_final,
        abastecimento_id=abastecimento_id,
        caixa_operacao_id=caixa_operacao_id,
        ordem_id=ordem_id,
        descricao=descricao,
        idempotency_key=idempotency_key,
        referencia_externa=referencia_externa,
    )

    carteiras.atualizar_saldo(conn, carteira_id, saldo_final)
    return mov
