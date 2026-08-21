"""Portal do Cliente (empresa/restaurante) da REMO.

O cliente acessa via web para:
- Ver saldo da carteira
- Recarregar crédito via PIX
- Ver histórico de ordens (últimas 24h)
- Ver extrato completo
"""

from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, jsonify, request

from app.core.db import connect
from app.repositories import carteiras as cart_repo
from app.services import auth as auth_service

bp = Blueprint("portal", __name__)


def _extrair_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return ""


def _usuario_atual() -> dict | None:
    return auth_service.verificar_token(_extrair_token())


def _requer_cliente() -> dict | None:
    """Retorna usuário atual se for cliente (perfil EMPRESA/CLIENTE), senão None."""
    user = _usuario_atual()
    if not user:
        return None
    if user.get("perfil") not in ("EMPRESA", "CLIENTE", "ADMIN"):
        return None
    return user


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


# ============================================================
# Autenticação
# ============================================================

@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    senha = str(data.get("senha") or "").strip()
    if not username or not senha:
        return _err("credenciais_obrigatorias", 400)

    result = auth_service.login(username, senha)
    if not result:
        return _err("credenciais_invalidas", 401)

    perfil = result["usuario"].get("perfil")
    # Cliente pode ser EMPRESA, CLIENTE ou ADMIN (admin pode testar)
    if perfil not in ("EMPRESA", "CLIENTE", "ADMIN"):
        return _err("acesso_negado_portal_cliente", 403)

    return jsonify({
        "ok": True,
        "token": result["token"],
        "usuario": {
            "id": result["usuario"]["usuario_id"],
            "nome": result["usuario"].get("nome"),
            "perfil": result["usuario"].get("perfil"),
            "username": result["usuario"].get("username"),
            "empresa_id": result["usuario"].get("empresa_id"),
        },
    })


@bp.get("/me")
def me():
    user = _requer_cliente()
    if not user:
        return _err("nao_autenticado", 401)
    return jsonify({"ok": True, "usuario": {
        "id": user["usuario_id"],
        "nome": user.get("nome"),
        "perfil": user.get("perfil"),
        "username": user.get("username"),
        "empresa_id": user.get("empresa_id"),
    }})


# ============================================================
# Carteira — saldo e extrato
# ============================================================

@bp.get("/carteira")
def carteira():
    """Saldo atual da carteira da empresa do cliente."""
    user = _requer_cliente()
    if not user:
        return _err("nao_autenticado", 401)

    empresa_id = user.get("empresa_id")
    if not empresa_id:
        return _err("sem_empresa_vinculada", 400)

    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.empresa_id, e.nome as empresa_nome,
                   c.saldo_atual, c.ativo, c.criado_em
            FROM carteiras c
            LEFT JOIN empresas e ON e.id = c.empresa_id
            WHERE c.empresa_id = %s
        """, (empresa_id,))
        row = cur.fetchone()
        if not row:
            return _err("carteira_nao_encontrada", 404)
        c = dict(row)

    return jsonify({
        "ok": True,
        "carteira": {
            "id": c["id"],
            "empresa": c.get("empresa_nome"),
            "empresa_id": c.get("empresa_id"),
            "saldo": float(c["saldo_atual"] or 0),
            "ativo": c.get("ativo"),
        },
    })


@bp.get("/extrato")
def extrato():
    """Extrato da carteira com filtros."""
    user = _requer_cliente()
    if not user:
        return _err("nao_autenticado", 401)

    empresa_id = user.get("empresa_id")
    if not empresa_id:
        return _err("sem_empresa_vinculada", 400)

    status = request.args.get("status")
    tipo = request.args.get("tipo")
    data_ini = request.args.get("data_ini")
    data_fim = request.args.get("data_fim")
    limit = min(int(request.args.get("limit", 100)), 500)

    where = ["m.carteira_id = c.id", "c.empresa_id = %s"]
    params: list[Any] = [empresa_id]
    if status:
        where.append("m.status = %s")
        params.append(status)
    if tipo:
        where.append("m.tipo = %s")
        params.append(tipo)
    if data_ini:
        where.append("m.criado_em >= %s")
        params.append(data_ini)
    if data_fim:
        where.append("m.criado_em <= %s")
        params.append(data_fim)

    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT m.id, m.uuid, m.tipo, m.descricao, m.valor,
                   m.saldo_anterior, m.saldo_final, m.status, m.criado_em
            FROM movimentacoes_carteira m, carteiras c
            WHERE {' AND '.join(where)}
            ORDER BY m.criado_em DESC
            LIMIT %s
        """, params + [limit])
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            items.append({
                "id": r["id"],
                "tipo": r.get("tipo"),
                "descricao": r.get("descricao"),
                "valor": float(r["valor"] or 0),
                "saldo_anterior": float(r["saldo_anterior"] or 0),
                "saldo_final": float(r["saldo_final"] or 0),
                "status": r.get("status"),
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
            })

    return jsonify({"ok": True, "extrato": items})


# ============================================================
# Recarga via PIX
# ============================================================

@bp.post("/recarga")
def recarga():
    """Gera cobrança PIX para recarga de saldo."""
    user = _requer_cliente()
    if not user:
        return _err("nao_autenticado", 401)

    empresa_id = user.get("empresa_id")
    if not empresa_id:
        return _err("sem_empresa_vinculada", 400)

    data = request.get_json(silent=True) or {}
    try:
        valor = float(data.get("valor") or 0)
    except (TypeError, ValueError):
        return _err("valor_invalido", 400)

    if valor <= 0:
        return _err("valor_deve_ser_positivo", 400)

    from app.pix import service as pix_service

    try:
        result = pix_service.criar_cobranca(
            empresa_id=empresa_id,
            valor=valor,
            descricao=f"Recarga portal — {user.get('username')}",
        )
    except RuntimeError as e:
        return _err(str(e), 400)

    return jsonify({"ok": True, "recarga": result}), 201


@bp.get("/recargas")
def recargas():
    """Lista recargas (abastecimentos) do cliente."""
    user = _requer_cliente()
    if not user:
        return _err("nao_autenticado", 401)

    empresa_id = user.get("empresa_id")
    if not empresa_id:
        return _err("sem_empresa_vinculada", 400)

    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, uuid, valor, metodo, status, criado_em, confirmado_em, pix_txid
            FROM abastecimentos
            WHERE empresa_id = %s
            ORDER BY criado_em DESC
            LIMIT 50
        """, (empresa_id,))
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            items.append({
                "id": r["id"],
                "uuid": r.get("uuid"),
                "valor": float(r["valor"] or 0),
                "metodo": r.get("metodo"),
                "status": r.get("status"),
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
                "confirmado_em": r["confirmado_em"].isoformat() if r.get("confirmado_em") else None,
            })

    return jsonify({"ok": True, "recargas": items})


# ============================================================
# Ordens — últimas 24h
# ============================================================

@bp.get("/ordens")
def ordens():
    """Histórico de ordens do cliente (últimas 24h por padrão)."""
    user = _requer_cliente()
    if not user:
        return _err("nao_autenticado", 401)

    empresa_id = user.get("empresa_id")
    if not empresa_id:
        return _err("sem_empresa_vinculada", 400)

    horas = int(request.args.get("horas", 24))
    status = request.args.get("status")

    where = ["empresa_id = %s", "criado_em > NOW() - make_interval(hours => %s)"]
    params: list[Any] = [empresa_id, horas]
    if status:
        where.append("status = %s")
        params.append(status)

    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT id, uuid, protocolo, solicitacao_id, status, taxa,
                   entregador_id, u.nome as entregador_nome,
                   payload_json, criado_em, entregue_em
            FROM ordens_servico o
            LEFT JOIN usuarios u ON u.id = o.entregador_id
            WHERE {' AND '.join(where)}
            ORDER BY criado_em DESC
            LIMIT 200
        """, params)
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            payload = r.get("payload_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            items.append({
                "id": r["id"],
                "protocolo": r.get("protocolo"),
                "solicitacao_id": r.get("solicitacao_id"),
                "status": r["status"],
                "taxa": float(r["taxa"] or 0),
                "entregador": r.get("entregador_nome"),
                "payload": payload,
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
                "entregue_em": r["entregue_em"].isoformat() if r.get("entregue_em") else None,
            })

    return jsonify({"ok": True, "ordens": items, "horas": horas})
