"""Serviço de caixa físico e abastecimento em dinheiro."""

from __future__ import annotations

from typing import Any

from app.core.db import transaction
from app.repositories import abastecimentos, caixa_operacoes, caixas, usuarios
from app.services import movimentacoes


TIPOS_DINHEIRO = {"ENTRADA", "SAIDA", "SUPRIMENTO", "SANGRIA", "AJUSTE"}


def _verificar_operador(operador_id: int) -> dict[str, Any]:
    op = usuarios.get(operador_id)
    if not op:
        raise RuntimeError("operador_nao_encontrado")
    return op


def _get_caixa_aberto(caixa_id: int) -> dict[str, Any]:
    caixa = caixas.get(caixa_id)
    if not caixa:
        raise RuntimeError("caixa_nao_encontrada")
    if caixa["status"] != "ABERTO":
        raise RuntimeError("caixa_fechado")
    return caixa


def _calcular_saldo_caixa(caixa_id: int) -> float:
    """Calcula saldo esperado do caixa a partir das operações."""
    caixa = caixas.get(caixa_id)
    if not caixa:
        return 0.0

    saldo_inicial = float(caixa.get("saldo_esperado") or 0)
    operacoes = caixa_operacoes.list_by_caixa(caixa_id)
    entradas = sum(float(o.get("valor") or 0) for o in operacoes if o["tipo"] in ("ENTRADA", "SUPRIMENTO", "ABERTURA"))
    saidas = sum(float(o.get("valor") or 0) for o in operacoes if o["tipo"] in ("SAIDA", "SANGRIA"))
    ajustes = sum(float(o.get("valor") or 0) for o in operacoes if o["tipo"] == "AJUSTE")
    return round(entradas - saidas + ajustes, 2)


def _atualizar_saldo_esperado(conn, caixa_id: int) -> None:
    novo_saldo = _calcular_saldo_caixa(caixa_id)
    cur = conn.cursor()
    cur.execute(
        "UPDATE caixas SET saldo_esperado = %s WHERE id = %s",
        (novo_saldo, caixa_id),
    )


def create(nome: str) -> dict[str, Any]:
    return caixas.create(nome)


def abrir(caixa_id: int, operador_id: int, saldo_inicial: float) -> dict[str, Any]:
    _verificar_operador(operador_id)

    with transaction() as conn:
        caixa = caixas.get(caixa_id)
        if not caixa:
            raise RuntimeError("caixa_nao_encontrada")
        if caixa["status"] == "ABERTO":
            raise RuntimeError("caixa_ja_aberto")

        if caixas.get_aberto():
            raise RuntimeError("outro_caixa_ja_aberto")

        caixa = caixas.abrir(conn, caixa_id, operador_id, saldo_inicial)
        caixa_operacoes.create(
            conn=conn,
            caixa_id=caixa_id,
            operador_id=operador_id,
            tipo="ABERTURA",
            saldo_inicial=saldo_inicial,
            saldo_final_sistema=saldo_inicial,
        )
        return caixa


def fechar(
    caixa_id: int,
    operador_id: int,
    saldo_contado: float,
    motivo: str | None = None,
) -> dict[str, Any]:
    _verificar_operador(operador_id)

    with transaction() as conn:
        caixa = _get_caixa_aberto(caixa_id)

        saldo_sistema = _calcular_saldo_caixa(caixa_id)
        diferenca = round(saldo_contado - saldo_sistema, 2)

        caixa = caixas.fechar(conn, caixa_id, saldo_sistema)
        caixa_operacoes.create(
            conn=conn,
            caixa_id=caixa_id,
            operador_id=operador_id,
            tipo="FECHAMENTO",
            saldo_inicial=float(caixa["saldo_esperado"] or 0),
            saldo_final_sistema=saldo_sistema,
            saldo_contado=saldo_contado,
            diferenca=diferenca,
            motivo=motivo,
        )
        return caixa


def operacao_dinheiro(
    *,
    caixa_id: int,
    operador_id: int,
    tipo: str,
    valor: float,
    motivo: str | None = None,
) -> dict[str, Any]:
    _verificar_operador(operador_id)

    if tipo not in TIPOS_DINHEIRO:
        raise RuntimeError(f"tipo_operacao_invalido: {tipo}")

    with transaction() as conn:
        _get_caixa_aberto(caixa_id)

        op = caixa_operacoes.create(
            conn=conn,
            caixa_id=caixa_id,
            operador_id=operador_id,
            tipo=tipo,
            valor=valor,
            motivo=motivo,
        )

        _atualizar_saldo_esperado(conn, caixa_id)
        return op


def abastecer_em_dinheiro(
    *,
    empresa_id: str,
    carteira_id: int,
    valor: float,
    operador_id: int,
    caixa_id: int,
) -> dict[str, Any]:
    _verificar_operador(operador_id)

    with transaction() as conn:
        _get_caixa_aberto(caixa_id)

        op_caixa = caixa_operacoes.create(
            conn=conn,
            caixa_id=caixa_id,
            operador_id=operador_id,
            tipo="ENTRADA",
            valor=valor,
        )

        ab = abastecimentos.create_dinheiro(
            conn=conn,
            empresa_id=empresa_id,
            carteira_id=carteira_id,
            valor=valor,
            operador_id=operador_id,
            caixa_operacao_id=op_caixa["id"],
        )

        mov = movimentacoes.criar(
            conn=conn,
            carteira_id=carteira_id,
            tipo="CREDITO",
            valor=valor,
            descricao=f"Crédito por dinheiro {ab['uuid']}",
            abastecimento_id=ab["id"],
            caixa_operacao_id=op_caixa["id"],
        )

        # Atualiza operação de caixa com referências
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE caixa_operacoes
            SET abastecimento_id = %s, movimentacao_id = %s
            WHERE id = %s
            """,
            (ab["id"], mov["id"], op_caixa["id"]),
        )

        _atualizar_saldo_esperado(conn, caixa_id)
        return ab
