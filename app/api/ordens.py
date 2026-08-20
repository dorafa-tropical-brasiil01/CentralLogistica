"""Rotas de ordens de serviço."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core import config
from app.repositories import ordens as ordens_repo
from app.services import ordens as ordens_service

bp = Blueprint("ordens", __name__)


def _json() -> dict:
    return request.get_json(silent=True) or {}


def _autorizar():
    header_key = request.headers.get("x-api-key", "")
    if header_key != config.CENTRAL_LOGISTICA_API_KEY:
        return False
    return True


@bp.post("/ordens")
def criar_ordem():
    if not _autorizar():
        return jsonify({"error": "nao_autorizado"}), 401

    data = _json()
    empresa_id = str(data.get("empresa_id") or "").strip()
    solicitacao_id = str(data.get("solicitacao_id") or "").strip()
    try:
        taxa = float(data.get("taxa") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "taxa_invalida"}), 400

    if not empresa_id or not solicitacao_id:
        return jsonify({"error": "empresa_id e solicitacao_id obrigatorios"}), 400

    try:
        ordem = ordens_service.criar(
            empresa_id=empresa_id,
            solicitacao_id=solicitacao_id,
            taxa=taxa,
            payload=data.get("payload"),
            idempotency_key=data.get("idempotency_key"),
        )
    except RuntimeError as e:
        if str(e) == "saldo_insuficiente":
            return jsonify({"error": "saldo_insuficiente"}), 402
        return jsonify({"error": str(e)}), 400

    return jsonify(ordem), 201


@bp.get("/ordens/<ordem_uuid>")
def obter_ordem(ordem_uuid: str):
    if not _autorizar():
        return jsonify({"error": "nao_autorizado"}), 401
    ordem = ordens_repo.get_by_uuid(ordem_uuid)
    if not ordem:
        return jsonify({"error": "nao_encontrado"}), 404
    return jsonify(ordem)


@bp.post("/ordens/<ordem_uuid>/status")
def atualizar_status(ordem_uuid: str):
    if not _autorizar():
        return jsonify({"error": "nao_autorizado"}), 401

    data = _json()
    status = str(data.get("status") or "").strip().upper()
    entregador_id = data.get("entregador_id")

    if not status:
        return jsonify({"error": "status obrigatorio"}), 400

    ordem = ordens_repo.get_by_uuid(ordem_uuid)
    if not ordem:
        return jsonify({"error": "nao_encontrado"}), 404

    try:
        ordem = ordens_service.atualizar_status(
            ordem_id=ordem["id"],
            status=status,
            entregador_id=int(entregador_id) if entregador_id else None,
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(ordem)
