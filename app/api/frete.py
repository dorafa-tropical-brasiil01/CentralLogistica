"""Rotas de configuração de frete da REMO."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core import config
from app.repositories import frete as frete_repo

bp = Blueprint("frete", __name__)


def _autorizar():
    header_key = request.headers.get("x-api-key", "")
    if header_key != config.CENTRAL_LOGISTICA_API_KEY:
        return False
    return True


@bp.get("/frete/<empresa_id>")
def obter_config(empresa_id: str):
    if not _autorizar():
        return jsonify({"error": "nao_autorizado"}), 401
    cfg = frete_repo.get(empresa_id)
    if not cfg:
        return jsonify({"ok": True, "enabled": False, "config": None})
    return jsonify({"ok": True, "enabled": cfg.get("enabled"), "config": cfg})


@bp.post("/frete/<empresa_id>")
def salvar_config(empresa_id: str):
    if not _autorizar():
        return jsonify({"error": "nao_autorizado"}), 401

    data = request.get_json(silent=True) or {}

    try:
        cfg = frete_repo.upsert(
            empresa_id=empresa_id,
            enabled=data.get("enabled"),
            origin_maps_url=data.get("origin_maps_url"),
            base=float(data["base"]) if data.get("base") is not None else None,
            per_km=float(data["per_km"]) if data.get("per_km") is not None else None,
            min_v=float(data["min"]) if data.get("min") is not None else None,
            max_v=float(data["max"]) if data.get("max") is not None else None,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"ok": True, "enabled": cfg.get("enabled"), "config": cfg})


@bp.post("/frete/<empresa_id>/habilitar")
def habilitar(empresa_id: str):
    if not _autorizar():
        return jsonify({"error": "nao_autorizado"}), 401
    cfg = frete_repo.upsert(empresa_id=empresa_id, enabled=True)
    return jsonify({"ok": True, "enabled": True})


@bp.post("/frete/<empresa_id>/desabilitar")
def desabilitar(empresa_id: str):
    if not _autorizar():
        return jsonify({"error": "nao_autorizado"}), 401
    cfg = frete_repo.upsert(empresa_id=empresa_id, enabled=False)
    return jsonify({"ok": True, "enabled": False})


@bp.post("/frete/<empresa_id>/preview")
def preview(empresa_id: str):
    """Calcula o frete com base na configuração atual e nas coordenadas enviadas."""
    if not _autorizar():
        return jsonify({"error": "nao_autorizado"}), 401

    data = request.get_json(silent=True) or {}
    client_maps_url = str(data.get("client_maps_url") or "").strip()
    if not client_maps_url:
        return jsonify({"error": "client_maps_url_obrigatorio"}), 400

    from app.core import frete as frete_calc

    cfg = frete_repo.get(empresa_id)
    if not cfg:
        return jsonify({"ok": False, "enabled": False, "reason": "nao_configurado"})

    config_dict = {
        "enabled": cfg.get("enabled"),
        "origin_maps_url": cfg.get("origin_maps_url"),
        "base": cfg.get("base"),
        "per_km": cfg.get("per_km"),
        "min": cfg.get("min_v"),
        "max": cfg.get("max_v"),
    }

    calc = frete_calc.compute_fee(
        config=config_dict,
        origin_maps_url=str(cfg.get("origin_maps_url") or ""),
        client_maps_url=client_maps_url,
    )
    if not calc:
        return jsonify({"ok": False, "enabled": bool(cfg.get("enabled")), "reason": "nao_calculado"})

    return jsonify({"ok": True, "enabled": True, "fee": calc["fee"], "distance_km": calc["distance_km"]})
