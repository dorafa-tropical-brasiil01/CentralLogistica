"""Rotas da API financeira."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.db import transaction
from app.pix import service as pix_service
from app.repositories import carteiras, empresas, movimentacoes_carteira
from app.services import abastecimento, caixa as caixa_service, movimentacoes

bp = Blueprint("financeiro", __name__)


def _json() -> dict:
    return request.get_json(silent=True) or {}


@bp.post("/empresas")
def criar_empresa():
    data = _json()
    empresa_id = str(data.get("empresa_id") or "").strip()
    nome = str(data.get("nome") or "").strip()
    if not empresa_id or not nome:
        return jsonify({"error": "empresa_id e nome obrigatórios"}), 400

    if empresas.get(empresa_id):
        return jsonify({"error": "empresa_ja_existe"}), 409

    empresa = empresas.create(empresa_id, nome)
    return jsonify(empresa), 201


@bp.get("/empresas/<empresa_id>")
def obter_empresa(empresa_id: str):
    empresa = empresas.get(empresa_id)
    if not empresa:
        return jsonify({"error": "nao_encontrado"}), 404
    return jsonify(empresa)


@bp.get("/empresas/<empresa_id>/carteira")
def obter_carteira(empresa_id: str):
    carteira = carteiras.get_by_empresa(empresa_id)
    if not carteira:
        return jsonify({"error": "nao_encontrado"}), 404
    return jsonify(carteira)


@bp.get("/carteiras/<int:carteira_id>/extrato")
def extrato(carteira_id: int):
    limite = request.args.get("limite", 100, type=int)
    movs = movimentacoes_carteira.list_by_carteira(carteira_id, limite=limite)
    return jsonify({"movimentacoes": movs})


@bp.post("/abastecimentos/pix")
def criar_abastecimento_pix():
    data = _json()
    empresa_id = str(data.get("empresa_id") or "").strip()
    try:
        valor = float(data.get("valor") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "valor_invalido"}), 400

    if valor <= 0:
        return jsonify({"error": "valor_invalido"}), 400

    try:
        resultado = pix_service.criar_cobranca(
            empresa_id=empresa_id,
            valor=valor,
            descricao=data.get("descricao"),
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(resultado), 201


@bp.post("/caixas")
def criar_caixa():
    data = _json()
    nome = str(data.get("nome") or "").strip()
    if not nome:
        return jsonify({"error": "nome_obrigatorio"}), 400
    caixa = caixa_service.create(nome)
    return jsonify(caixa), 201


@bp.post("/caixas/<int:caixa_id>/abrir")
def abrir_caixa(caixa_id: int):
    data = _json()
    operador_id = data.get("operador_id")
    saldo_inicial = float(data.get("saldo_inicial") or 0)
    if not operador_id:
        return jsonify({"error": "operador_id_obrigatorio"}), 400
    try:
        caixa = caixa_service.abrir(caixa_id, int(operador_id), saldo_inicial)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(caixa)


@bp.post("/caixas/<int:caixa_id>/fechar")
def fechar_caixa(caixa_id: int):
    data = _json()
    operador_id = data.get("operador_id")
    saldo_contado = float(data.get("saldo_contado") or 0)
    motivo = data.get("motivo")
    if not operador_id:
        return jsonify({"error": "operador_id_obrigatorio"}), 400
    try:
        caixa = caixa_service.fechar(caixa_id, int(operador_id), saldo_contado, motivo)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(caixa)


@bp.post("/caixas/<int:caixa_id>/operacoes")
def operacao_caixa(caixa_id: int):
    data = _json()
    operador_id = data.get("operador_id")
    tipo = str(data.get("tipo") or "").strip().upper()
    try:
        valor = float(data.get("valor") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "valor_invalido"}), 400
    motivo = data.get("motivo")
    if not operador_id or not tipo:
        return jsonify({"error": "operador_id e tipo obrigatórios"}), 400
    try:
        op = caixa_service.operacao_dinheiro(
            caixa_id=caixa_id,
            operador_id=int(operador_id),
            tipo=tipo,
            valor=valor,
            motivo=motivo,
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(op), 201


@bp.post("/abastecimentos/dinheiro")
def criar_abastecimento_dinheiro():
    data = _json()
    empresa_id = str(data.get("empresa_id") or "").strip()
    operador_id = data.get("operador_id")
    caixa_id = data.get("caixa_id")
    try:
        valor = float(data.get("valor") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "valor_invalido"}), 400

    if not empresa_id or not operador_id or not caixa_id or valor <= 0:
        return jsonify({"error": "empresa_id, operador_id, caixa_id e valor obrigatórios"}), 400

    carteira = carteiras.get_by_empresa(empresa_id)
    if not carteira:
        return jsonify({"error": "carteira_nao_encontrada"}), 404

    try:
        ab = caixa_service.abastecer_em_dinheiro(
            empresa_id=empresa_id,
            carteira_id=carteira["id"],
            valor=valor,
            operador_id=int(operador_id),
            caixa_id=int(caixa_id),
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(ab), 201


@bp.post("/carteiras/<int:carteira_id>/debitar")
def debitar_carteira(carteira_id: int):
    data = _json()
    try:
        valor = float(data.get("valor") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "valor_invalido"}), 400
    if valor <= 0:
        return jsonify({"error": "valor_invalido"}), 400

    descricao = str(data.get("descricao") or "Débito").strip()
    idempotency_key = data.get("idempotency_key")

    with transaction() as conn:
        try:
            mov = movimentacoes.criar(
                conn=conn,
                carteira_id=carteira_id,
                tipo="DEBITO",
                valor=valor,
                descricao=descricao,
                idempotency_key=idempotency_key,
            )
        except RuntimeError as e:
            if str(e) == "saldo_insuficiente":
                return jsonify({"error": "saldo_insuficiente"}), 402
            raise

    return jsonify(mov), 201
