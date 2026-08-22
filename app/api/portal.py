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

    from datetime import datetime, timedelta
    limite = datetime.now() - timedelta(hours=horas)

    where = ["o.empresa_id = %s", "o.criado_em > %s"]
    params: list[Any] = [empresa_id, limite.isoformat()]
    if status:
        where.append("o.status = %s")
        params.append(status)

    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT o.id, o.uuid, o.protocolo, o.solicitacao_id, o.status, o.taxa,
                       o.entregador_id, u.nome as entregador_nome,
                       o.payload_json, o.criado_em, o.entregue_em
                FROM ordens_servico o
                LEFT JOIN usuarios u ON u.id = o.entregador_id
                WHERE {' AND '.join(where)}
                ORDER BY o.criado_em DESC
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
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


# ============================================================
# Criar ordem manual (pedido por telefone)
# ============================================================

@bp.post("/ordens/criar")
def criar_ordem_manual():
    """Cliente cria uma O.S. manualmente (pedido por telefone, etc)."""
    user = _requer_cliente()
    if not user:
        return _err("nao_autenticado", 401)

    empresa_id = user.get("empresa_id")
    if not empresa_id:
        return _err("sem_empresa_vinculada", 400)

    data = request.get_json(silent=True) or {}

    # Campos obrigatórios
    cliente_nome = str(data.get("cliente_nome") or "").strip()
    client_maps_url = str(data.get("client_maps_url") or "").strip()
    origin_maps_url = str(data.get("origin_maps_url") or "").strip()

    if not cliente_nome:
        return _err("cliente_nome_obrigatorio"), 400
    if not client_maps_url:
        return _err("endereco_destino_obrigatorio"), 400

    # Campos opcionais
    cliente_whatsapp = str(data.get("cliente_whatsapp") or "").strip() or None
    cliente_endereco = str(data.get("cliente_endereco") or "").strip() or None
    observacoes = str(data.get("observacoes") or "").strip() or None
    taxa_manual = data.get("taxa_manual")  # se o cliente quiser forçar uma taxa

    # Gera solicitacao_id único
    import uuid as _uuid
    solicitacao_id = f"MANUAL-{_uuid.uuid4().hex[:16].upper()}"

    # Payload com dados do cliente
    payload = {
        "cliente_nome": cliente_nome,
        "cliente_whatsapp": cliente_whatsapp,
        "cliente_endereco": cliente_endereco,
        "observacoes": observacoes,
        "tipo_entrega": "DELIVERY",
        "origem": "PORTAL_MANUAL",
        "total": 0.0,
    }

    try:
        from app.services import ordens as ordens_service
        taxa_cliente = float(taxa_manual) if taxa_manual else 0.0
        ordem = ordens_service.criar(
            empresa_id=empresa_id,
            solicitacao_id=solicitacao_id,
            taxa_cliente=taxa_cliente,
            origin_maps_url=origin_maps_url or None,
            client_maps_url=client_maps_url,
            payload=payload,
        )
    except RuntimeError as e:
        if str(e) == "saldo_insuficiente":
            return _err("saldo_insuficiente"), 402
        return _err(str(e)), 400

    # Notifica entregadores via push
    try:
        from app.services import push as push_service
        push_service.notificar_entregadores_disponiveis(
            ordem_id=ordem.get("id"),
            protocolo=ordem.get("protocolo", ""),
            taxa=float(ordem.get("taxa") or 0),
        )
    except Exception:
        pass

    return jsonify({"ok": True, "ordem": ordem}), 201


# ============================================================
# Calcular frete (pré-visualização antes de criar)
# ============================================================

@bp.post("/ordens/calcular-frete")
def calcular_frete():
    """Calcula o frete antes de criar a ordem."""
    user = _requer_cliente()
    if not user:
        return _err("nao_autenticado", 401)

    empresa_id = user.get("empresa_id")
    if not empresa_id:
        return _err("sem_empresa_vinculada", 400)

    data = request.get_json(silent=True) or {}
    client_maps_url = str(data.get("client_maps_url") or "").strip()
    origin_maps_url = str(data.get("origin_maps_url") or "").strip()

    if not client_maps_url:
        return _err("endereco_destino_obrigatorio"), 400

    import logging
    log = logging.getLogger("portal")
    log.info("calcular-frete: url=%s origin=%s", client_maps_url[:80], (origin_maps_url or "")[:80])

    try:
        from app.services.ordens import _calcular_frete_real
        from app.core.frete import extract_lat_lng, resolve_short_url
        # Resolve URL encurtada para debug
        resolved = resolve_short_url(client_maps_url)
        coords = extract_lat_lng(resolved)
        log.info("calcular-frete: resolved=%s coords=%s", resolved[:80] if resolved != client_maps_url else "igual", coords)
        taxa = _calcular_frete_real(
            empresa_id=empresa_id,
            origin_maps_url=origin_maps_url or None,
            client_maps_url=client_maps_url,
        )
        log.info("calcular-frete: taxa=%s", taxa)
        if taxa is None:
            taxa = 0.0
    except Exception as e:
        return _err(f"erro_calcular_frete: {e}"), 500

    # Verifica saldo
    from app.repositories import carteiras as cart_repo
    carteira = cart_repo.get_by_empresa(empresa_id)
    saldo = float(carteira["saldo_atual"]) if carteira else 0.0

    return jsonify({
        "ok": True,
        "taxa": float(taxa),
        "saldo": saldo,
        "saldo_suficiente": saldo >= float(taxa),
        "debug": {
            "url_resolvida": resolved if resolved != client_maps_url else None,
            "coords_encontradas": list(coords) if coords else None,
        },
    })
