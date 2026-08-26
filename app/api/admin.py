"""Painel Administrativo da REMO — controla tudo.

Módulos:
1. Monitoramento + Mapa
2. Financeiro — Histórico de pagamentos
3. Carteira e Extrato
4. Relatórios e Métricas (KPIs)
5. Histórico de Ordens
6. Áreas de Cobertura + Taxas
7. Cadastro de Entregadores
"""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg2.extras
from flask import Blueprint, jsonify, request

from app.core.db import connect, transaction
from app.repositories import empresas as empresas_repo
from app.repositories import frete as frete_repo
from app.repositories import usuarios as usuarios_repo
from app.services import auth as auth_service

bp = Blueprint("admin", __name__)


def _extrair_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return ""


def _usuario_atual() -> dict | None:
    return auth_service.verificar_token(_extrair_token())


def _requer_admin() -> dict | None:
    """Retorna usuário atual se for admin/central, senão None."""
    user = _usuario_atual()
    if not user:
        return None
    if user.get("perfil") not in ("ADMIN", "CENTRAL"):
        return None
    return user


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _resolve_coords(url: str) -> dict | None:
    """Resolve URL do Google Maps e extrai coordenadas."""
    if not url:
        return None
    try:
        from app.core.frete import extract_lat_lng, resolve_short_url
        resolved = resolve_short_url(url)
        coords = extract_lat_lng(resolved)
        if coords:
            return {"lat": coords[0], "lng": coords[1]}
    except Exception:
        pass
    return None


# ============================================================
# Autenticação
# ============================================================

@bp.post("/setup")
def setup():
    """Cria usuários padrão se não existirem. Endpoint emergencial."""
    from app.services.auth import _hash_senha, _gerar_salt
    from app.core.db import transaction
    import logging

    criados = []
    usuarios_padrao = [
        {"username": "admin", "nome": "Administrador", "perfil": "ADMIN", "senha": "admin123"},
        {"username": "empresa-teste", "nome": "Empresa Teste", "perfil": "EMPRESA", "senha": "teste123"},
    ]

    try:
        with transaction() as conn:
            cur = conn.cursor()
            for u in usuarios_padrao:
                cur.execute("SELECT id FROM usuarios WHERE username = %s", (u["username"],))
                existing = cur.fetchone()
                if not existing:
                    salt = _gerar_salt()
                    hash_senha = _hash_senha(u["senha"], salt)
                    cur.execute(
                        """INSERT INTO usuarios (username, nome, perfil, senha_hash, senha_salt, ativo)
                           VALUES (%s, %s, %s, %s, %s, true) RETURNING id""",
                        (u["username"], u["nome"], u["perfil"], hash_senha, salt),
                    )
                    new_id = cur.fetchone()["id"]
                    criados.append({"username": u["username"], "id": new_id})
                    logging.info("setup: criado usuario %s (id=%s)", u["username"], new_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Garante empresa-teste com config de frete habilitada
    try:
        from app.repositories import empresas as emp_repo, frete as frete_repo
        if not emp_repo.get("empresa-teste"):
            emp_repo.create("empresa-teste", "Empresa Teste")
        frete_repo.upsert(
            empresa_id="empresa-teste",
            enabled=True,
            base=5.0,
            per_km=1.50,
            min_v=5.0,
        )
    except Exception:
        pass

    return jsonify({"ok": True, "criados": criados, "mensagem": "Usuarios padrao criados" if criados else "Usuarios ja existiam"})

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
    if perfil not in ("ADMIN", "CENTRAL"):
        return _err("acesso_negado_apenas_admin", 403)

    return jsonify({
        "ok": True,
        "token": result["token"],
        "usuario": {
            "id": result["usuario"]["usuario_id"],
            "nome": result["usuario"].get("nome"),
            "perfil": result["usuario"].get("perfil"),
            "username": result["usuario"].get("username"),
        },
    })


@bp.get("/me")
def me():
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)
    return jsonify({"ok": True, "usuario": {
        "id": user["usuario_id"],
        "nome": user.get("nome"),
        "perfil": user.get("perfil"),
        "username": user.get("username"),
    }})


# ============================================================
# Módulo 1: Monitoramento + Mapa
# ============================================================

@bp.get("/monitoramento")
def monitoramento():
    """Dados para o mapa: ordens ativas, entregadores com localização, zonas."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    cidade_filtro = (request.args.get("cidade") or "").strip()

    with connect() as conn:
        cur = conn.cursor()

        # Cidades disponíveis com coordenadas centrais (do polígono das áreas)
        cur.execute("""
            SELECT DISTINCT cidade, poligono
            FROM areas_cobertura
            WHERE cidade IS NOT NULL AND cidade != ''
        """)
        cidades_coords = {}
        for r in (dict(x) for x in cur.fetchall()):
            cidade = r.get("cidade")
            poligono = r.get("poligono")
            if isinstance(poligono, str):
                try:
                    poligono = json.loads(poligono)
                except Exception:
                    poligono = None
            if poligono and isinstance(poligono, list) and len(poligono) > 0:
                # Calcula centro do polígono
                try:
                    pts = poligono if isinstance(poligono[0], list) else poligono.get("coordinates", [[]])[0]
                    if pts and isinstance(pts[0], (list, tuple)) and len(pts[0]) >= 2:
                        lats = [p[0] for p in pts]
                        lngs = [p[1] for p in pts]
                        cidades_coords[cidade] = {
                            "lat": sum(lats) / len(lats),
                            "lng": sum(lngs) / len(lngs),
                        }
                except Exception:
                    pass

        # Indicadores por status (últimas 6h)
        cur.execute("""
            SELECT status, COUNT(*) as total
            FROM ordens_servico
            WHERE criado_em > NOW() - INTERVAL '6 hours'
            GROUP BY status
        """)
        indicadores = {r["status"]: r["total"] for r in (dict(x) for x in cur.fetchall())}

        # Ordens ativas com payload
        cur.execute("""
            SELECT id, uuid, protocolo, solicitacao_id, status, taxa,
                   entregador_id, payload_json, criado_em, atribuido_em, em_rota_em
            FROM ordens_servico
            WHERE status IN ('PENDENTE', 'ATRIBUIDO', 'EM_ROTA')
            ORDER BY criado_em DESC
        """)
        ordens = []
        for r in (dict(x) for x in cur.fetchall()):
            payload = r.get("payload_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            origem_coords = _resolve_coords(payload.get("origin_maps_url", ""))
            dest_coords = _resolve_coords(payload.get("client_maps_url", ""))

            # Rota planejada via OSRM (só para ordens ativas com entregador)
            rota_planejada = None
            if origem_coords and dest_coords and r["status"] in ("ATRIBUIDO", "EM_ROTA"):
                from app.services.mapmatching import calcular_rota
                rota = calcular_rota(
                    (origem_coords["lat"], origem_coords["lng"]),
                    (dest_coords["lat"], dest_coords["lng"]),
                )
                if rota:
                    rota_planejada = [{"lat": p[0], "lng": p[1]} for p in rota]

            ordens.append({
                "id": r["id"],
                "protocolo": r.get("protocolo"),
                "solicitacao_id": r.get("solicitacao_id"),
                "status": r["status"],
                "taxa": float(r["taxa"] or 0),
                "entregador_id": r.get("entregador_id"),
                "payload": payload,
                "coords": dest_coords,
                "origem_coords": origem_coords,
                "rota_planejada": rota_planejada,
                "criado_em": r.get("criado_em").isoformat() if r.get("criado_em") else None,
            })

        # Filtra ordens por cidade (busca no client_maps_url ou solicitacao_id)
        if cidade_filtro:
            # Normaliza: remove acentos e pega a última parte após vírgula
            import unicodedata
            def normalize(s):
                return ''.join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn')
            # "Michelle, Vianópolis" -> "vianopolis"
            cidade_norm = normalize(cidade_filtro.split(",")[-1].strip())
            ordens_filtradas = []
            for o in ordens:
                url = (o.get("payload", {}).get("client_maps_url", "") or "").lower()
                sid = (o.get("solicitacao_id", "") or "").lower()
                url_norm = normalize(url)
                sid_norm = normalize(sid)
                if cidade_norm in url_norm or cidade_norm in sid_norm:
                    ordens_filtradas.append(o)
            ordens = ordens_filtradas

        # Entregadores com localização
        cur.execute("""
            SELECT id, username, nome, telefone, ativo, localizacao_atual, ultima_localizacao_em
            FROM usuarios
            WHERE perfil = 'ENTREGADOR'
        """)
        entregadores = []
        for r in (dict(x) for x in cur.fetchall()):
            loc = r.get("localizacao_atual")
            if isinstance(loc, str):
                try:
                    loc = json.loads(loc)
                except Exception:
                    loc = None
            # Verifica se tem corrida ativa
            corrida_ativa = None
            for o in ordens:
                if o.get("entregador_id") == r["id"] and o.get("status") in ("ATRIBUIDO", "EM_ROTA"):
                    corrida_ativa = o.get("status")
                    break
            entregadores.append({
                "id": r["id"],
                "nome": r.get("nome"),
                "username": r.get("username"),
                "telefone": r.get("telefone"),
                "ativo": r.get("ativo"),
                "localizacao": loc,
                "ultima_localizacao_em": r.get("ultima_localizacao_em").isoformat() if r.get("ultima_localizacao_em") else None,
                "corrida_ativa": corrida_ativa,
            })

        # Trilha de rastreamento para entregadores com localização
        from app.services.mapmatching import snap_to_road
        for ent in entregadores:
            if ent.get("localizacao"):
                cur.execute("""
                    SELECT lat, lng, criado_em
                    FROM rastreamento
                    WHERE usuario_id = %s
                    ORDER BY criado_em DESC LIMIT 50
                """, (ent["id"],))
                rows = cur.fetchall()
                trilha_raw = [(float(t["lat"]), float(t["lng"])) for t in rows]
                trilha_raw.reverse()  # ordem cronológica

                # Snap-to-roads: ajusta pontos GPS à malha viária
                trilha_snapped = None
                if len(trilha_raw) >= 2:
                    trilha_snapped = snap_to_road(trilha_raw)

                if trilha_snapped:
                    ent["trilha"] = [{"lat": p[0], "lng": p[1]} for p in trilha_snapped]
                    ent["trilha_snapped"] = True
                else:
                    ent["trilha"] = [{"lat": p[0], "lng": p[1]} for p in trilha_raw]
                    ent["trilha_snapped"] = False
                logging.info("monitoramento: trilha user=%s (%d pts, snapped=%s)",
                             ent["id"], len(ent["trilha"]), ent["trilha_snapped"])

    return jsonify({
        "ok": True,
        "cidades_coords": cidades_coords,
        "indicadores": {
            "agendadas": indicadores.get("AGENDADA", 0),
            "procurando": indicadores.get("PENDENTE", 0),
            "progresso": indicadores.get("EM_ROTA", 0) + indicadores.get("ATRIBUIDO", 0),
            "encerrados": indicadores.get("ENTREGUE", 0) + indicadores.get("CANCELADO", 0),
        },
        "ordens": ordens,
        "entregadores": entregadores,
    })


# ============================================================
# Módulo 2: Financeiro — Histórico de Pagamentos (abastecimentos)
# ============================================================

@bp.get("/financeiro/pagamentos")
def financeiro_pagamentos():
    """Histórico de abastecimentos (recargas PIX)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    empresa_id = request.args.get("empresa_id")
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))

    with connect() as conn:
        cur = conn.cursor()
        where = []
        params: list[Any] = []
        if empresa_id:
            where.append("a.empresa_id = %s")
            params.append(empresa_id)
        if status:
            where.append("a.status = %s")
            params.append(status)
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        cur.execute(f"""
            SELECT a.id, a.uuid, a.empresa_id, e.nome as empresa_nome,
                   a.valor, a.metodo, a.status, a.criado_em, a.confirmado_em,
                   a.pix_txid
            FROM abastecimentos a
            LEFT JOIN empresas e ON e.id = a.empresa_id
            {where_clause}
            ORDER BY a.criado_em DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            items.append({
                "id": r["id"],
                "uuid": r.get("uuid"),
                "empresa": r.get("empresa_nome"),
                "empresa_id": r.get("empresa_id"),
                "valor": float(r["valor"] or 0),
                "metodo": r.get("metodo"),
                "status": r.get("status"),
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
                "confirmado_em": r["confirmado_em"].isoformat() if r.get("confirmado_em") else None,
                "pix_txid": r.get("pix_txid"),
            })

        cur.execute(f"""
            SELECT COUNT(*) as total FROM abastecimentos a {where_clause}
        """, params)
        total = dict(cur.fetchone())["total"]

    return jsonify({"ok": True, "pagamentos": items, "total": total, "limit": limit, "offset": offset})


# ============================================================
# Módulo 3: Carteira e Extrato
# ============================================================

@bp.get("/financeiro/carteiras")
def financeiro_carteiras():
    """Lista carteiras com saldo."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.empresa_id, e.nome as empresa_nome,
                   c.saldo_atual, c.ativo, c.criado_em
            FROM carteiras c
            LEFT JOIN empresas e ON e.id = c.empresa_id
            ORDER BY e.nome
        """)
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            items.append({
                "id": r["id"],
                "empresa_id": r.get("empresa_id"),
                "empresa": r.get("empresa_nome"),
                "saldo": float(r["saldo_atual"] or 0),
                "ativo": r.get("ativo"),
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
            })
    return jsonify({"ok": True, "carteiras": items})


@bp.get("/financeiro/extrato/<int:carteira_id>")
def financeiro_extrato(carteira_id: int):
    """Extrato de uma carteira com filtros."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    status = request.args.get("status")
    tipo = request.args.get("tipo")
    data_ini = request.args.get("data_ini")
    data_fim = request.args.get("data_fim")
    limit = min(int(request.args.get("limit", 100)), 500)

    where = ["carteira_id = %s"]
    params: list[Any] = [carteira_id]
    if status:
        where.append("status = %s")
        params.append(status)
    if tipo:
        where.append("tipo = %s")
        params.append(tipo)
    if data_ini:
        where.append("criado_em >= %s")
        params.append(data_ini)
    if data_fim:
        where.append("criado_em <= %s")
        params.append(data_fim)

    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT id, uuid, tipo, descricao, valor, saldo_anterior, saldo_final,
                   status, criado_em, referencia_externa
            FROM movimentacoes_carteira
            WHERE {' AND '.join(where)}
            ORDER BY criado_em DESC
            LIMIT %s
        """, params + [limit])
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            items.append({
                "id": r["id"],
                "uuid": r.get("uuid"),
                "tipo": r.get("tipo"),
                "descricao": r.get("descricao"),
                "valor": float(r["valor"] or 0),
                "saldo_anterior": float(r["saldo_anterior"] or 0),
                "saldo_final": float(r["saldo_final"] or 0),
                "status": r.get("status"),
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
            })
    return jsonify({"ok": True, "extrato": items})


@bp.post("/financeiro/adicionar-saldo")
def financeiro_adicionar_saldo():
    """Admin adiciona saldo a uma carteira (dinheiro ou ajuste manual).

    Crédito direto na carteira — não passa por caixa nem PIX.
    Registra movimentação no livro-razão (movimentacoes_carteira).
    """
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    carteira_id = data.get("carteira_id")
    try:
        valor = float(data.get("valor") or 0)
    except (TypeError, ValueError):
        return _err("valor_invalido", 400)

    metodo = str(data.get("metodo") or "DINHEIRO").strip().upper()
    descricao = str(data.get("descricao") or "").strip()

    if not carteira_id or valor <= 0:
        return _err("carteira_id e valor (>0) obrigatorios", 400)

    import uuid as _uuid
    from app.repositories import carteiras as cart_repo

    with transaction() as conn:
        cur = conn.cursor()
        # Bloqueia carteira com FOR UPDATE
        saldo_anterior = cart_repo.bloquear_e_ler(conn, int(carteira_id))
        saldo_final = saldo_anterior + valor

        # Cria abastecimento (para rastreabilidade)
        cur.execute(
            """
            INSERT INTO abastecimentos (uuid, empresa_id, carteira_id, valor, metodo, status, confirmado_em, operador_id)
            SELECT %s, c.empresa_id, c.id, %s, %s, 'CONFIRMADO', NOW(), %s
            FROM carteiras c WHERE c.id = %s
            RETURNING id
            """,
            (str(_uuid.uuid4()), valor, metodo, user["usuario_id"], int(carteira_id)),
        )
        ab_row = cur.fetchone()
        if not ab_row:
            return _err("carteira_nao_encontrada", 404)
        abastecimento_id = ab_row["id"]

        # Registra movimentação no livro-razão
        cur.execute(
            """
            INSERT INTO movimentacoes_carteira
                (uuid, carteira_id, abastecimento_id, tipo, descricao, valor,
                 saldo_anterior, saldo_final, status, idempotency_key)
            VALUES (%s, %s, %s, 'CREDITO', %s, %s, %s, %s, 'CONCLUIDO', %s)
            RETURNING id
            """,
            (
                str(_uuid.uuid4()),
                int(carteira_id),
                abastecimento_id,
                descricao or f"Adição de saldo ({metodo}) — admin",
                valor,
                saldo_anterior,
                saldo_final,
                f"admin-credit-{abastecimento_id}",
            ),
        )
        mov_id = cur.fetchone()["id"]

        # Atualiza saldo materializado
        cart_repo.atualizar_saldo(conn, int(carteira_id), saldo_final)

        # Auditoria
        cur.execute(
            """
            INSERT INTO auditoria_financeira (carteira_id, abastecimento_id, tipo, referencia, dados_json)
            VALUES (%s, %s, 'CREDITO_MANUAL', %s, %s)
            """,
            (
                int(carteira_id),
                abastecimento_id,
                f"mov:{mov_id}",
                psycopg2.extras.Json({
                    "operador": user.get("username"),
                    "metodo": metodo,
                    "valor": valor,
                    "saldo_anterior": saldo_anterior,
                    "saldo_final": saldo_final,
                }),
            ),
        )

    return jsonify({
        "ok": True,
        "abastecimento_id": abastecimento_id,
        "movimentacao_id": mov_id,
        "saldo_anterior": saldo_anterior,
        "saldo_final": saldo_final,
    }), 201


# ============================================================
# Módulo 4: Relatórios e Métricas (KPIs)
# ============================================================

@bp.get("/relatorios/kpis")
def relatorios_kpis():
    """KPIs do período selecionado."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    periodo = request.args.get("periodo", "mes")  # mes, semana, 24h, 6h
    intervalos = {
        "mes": "INTERVAL '1 month'",
        "semana": "INTERVAL '7 days'",
        "24h": "INTERVAL '24 hours'",
        "6h": "INTERVAL '6 hours'",
    }
    interval = intervalos.get(periodo, intervalos["mes"])

    with connect() as conn:
        cur = conn.cursor()
        # Valor utilizado (soma de taxas de ordens entregues)
        cur.execute(f"""
            SELECT COALESCE(SUM(taxa), 0) as valor_utilizado,
                   COUNT(*) FILTER (WHERE status = 'ENTREGUE') as entregues,
                   COUNT(*) FILTER (WHERE status = 'CANCELADO') as cancelados,
                   COALESCE(AVG(taxa), 0) as valor_medio
            FROM ordens_servico
            WHERE criado_em > NOW() - {interval}
        """)
        row = dict(cur.fetchone())

        # Tempo médio (em minutos) — do criado_em ao entregue_em
        cur.execute(f"""
            SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (entregue_em - criado_em))/60), 0) as tempo_medio
            FROM ordens_servico
            WHERE status = 'ENTREGUE' AND criado_em > NOW() - {interval}
        """)
        tempo = dict(cur.fetchone())

        # Distribuição por hora do dia
        cur.execute(f"""
            SELECT EXTRACT(HOUR FROM criado_em)::int as hora, COUNT(*) as total
            FROM ordens_servico
            WHERE criado_em > NOW() - {interval}
            GROUP BY hora ORDER BY hora
        """)
        por_hora = {str(r["hora"]): r["total"] for r in (dict(x) for x in cur.fetchall())}

        # Distribuição por dia da semana (0=domingo)
        cur.execute(f"""
            SELECT EXTRACT(DOW FROM criado_em)::int as dia, COUNT(*) as total
            FROM ordens_servico
            WHERE criado_em > NOW() - {interval}
            GROUP BY dia ORDER BY dia
        """)
        por_dia = {str(r["dia"]): r["total"] for r in (dict(x) for x in cur.fetchall())}

    return jsonify({
        "ok": True,
        "periodo": periodo,
        "kpis": {
            "valor_utilizado": float(row["valor_utilizado"] or 0),
            "pedidos_entregues": row["entregues"] or 0,
            "pedidos_cancelados": row["cancelados"] or 0,
            "valor_medio_pedido": float(row["valor_medio"] or 0),
            "tempo_medio_min": float(tempo["tempo_medio"] or 0),
        },
        "graficos": {
            "por_hora": por_hora,
            "por_dia_semana": por_dia,
        },
    })


# ============================================================
# Módulo 5: Histórico de Ordens
# ============================================================

@bp.get("/ordens")
def listar_ordens():
    """Histórico de ordens com filtros avançados."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    ordem_id = request.args.get("id")
    solicitacao_id = request.args.get("solicitacao_id")
    codigo_ifood = request.args.get("codigo_ifood")
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))

    where = []
    params: list[Any] = []
    if ordem_id:
        where.append("id = %s")
        params.append(int(ordem_id))
    if solicitacao_id:
        where.append("solicitacao_id = %s")
        params.append(solicitacao_id)
    if codigo_ifood:
        where.append("payload_json::text ILIKE %s")
        params.append(f"%{codigo_ifood}%")
    if status:
        where.append("status = %s")
        params.append(status)

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT o.id, o.uuid, o.protocolo, o.solicitacao_id, o.status, o.taxa,
                   o.entregador_id, u.nome as entregador_nome,
                   o.payload_json, o.criado_em, o.entregue_em
            FROM ordens_servico o
            LEFT JOIN usuarios u ON u.id = o.entregador_id
            {where_clause}
            ORDER BY o.criado_em DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
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
                "entregador_id": r.get("entregador_id"),
                "payload": payload,
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
                "entregue_em": r["entregue_em"].isoformat() if r.get("entregue_em") else None,
            })

        cur.execute(f"SELECT COUNT(*) as total FROM ordens_servico {where_clause}", params)
        total = dict(cur.fetchone())["total"]

    return jsonify({"ok": True, "ordens": items, "total": total, "limit": limit, "offset": offset})


# ============================================================
# Módulo 6: Áreas de Cobertura + Taxas
# ============================================================

@bp.get("/areas")
def listar_areas():
    """Lista áreas de cobertura."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    empresa_id = request.args.get("empresa_id")
    cidade = request.args.get("cidade")
    status = request.args.get("status", "ATIVO")

    where = []
    params: list[Any] = []
    if empresa_id:
        where.append("empresa_id = %s")
        params.append(empresa_id)
    if cidade:
        where.append("cidade ILIKE %s")
        params.append(f"%{cidade}%")
    if status and status != "TODOS":
        where.append("status = %s")
        params.append(status)

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT id, empresa_id, nome, cidade, taxa, poligono, cor, status,
                   criado_em, atualizado_em
            FROM areas_cobertura
            {where_clause}
            ORDER BY cidade, nome
        """, params)
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            poligono = r.get("poligono")
            if isinstance(poligono, str):
                try:
                    poligono = json.loads(poligono)
                except Exception:
                    poligono = None
            items.append({
                "id": r["id"],
                "empresa_id": r.get("empresa_id"),
                "nome": r["nome"],
                "cidade": r.get("cidade"),
                "taxa": float(r["taxa"] or 0),
                "poligono": poligono,
                "cor": r.get("cor") or "#00d4aa",
                "status": r.get("status"),
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
            })

        cur.execute(f"SELECT COUNT(*) as total FROM areas_cobertura {where_clause}", params)
        total = dict(cur.fetchone())["total"]

    return jsonify({"ok": True, "areas": items, "total": total})


@bp.post("/areas")
def criar_area():
    """Cria nova área de cobertura."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    empresa_id = data.get("empresa_id")  # opcional: NULL = zona global
    nome = str(data.get("nome") or "").strip()
    cidade = str(data.get("cidade") or "").strip()
    taxa = data.get("taxa")
    poligono = data.get("poligono")
    cor = str(data.get("cor") or "#00d4aa").strip() or "#00d4aa"

    if not nome or taxa is None:
        return _err("nome e taxa sao obrigatorios", 400)

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO areas_cobertura (empresa_id, nome, cidade, taxa, poligono, cor, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'ATIVO')
            RETURNING *
            """,
            (empresa_id or None, nome, cidade or None, float(taxa),
             psycopg2.extras.Json(poligono) if poligono else None, cor),
        )
        area = dict(cur.fetchone())

    return jsonify({"ok": True, "area": {
        "id": area["id"],
        "nome": area["nome"],
        "cidade": area.get("cidade"),
        "taxa": float(area["taxa"]),
        "cor": area.get("cor") or "#00d4aa",
        "status": area.get("status"),
    }})


@bp.put("/areas/<int:area_id>")
def atualizar_area(area_id: int):
    """Atualiza área de cobertura."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    campos = {}
    for k in ("nome", "cidade", "taxa", "status", "poligono", "cor"):
        if k in data:
            campos[k] = data[k]

    if not campos:
        return _err("nada_para_atualizar", 400)

    sets = []
    params: list[Any] = []
    for k, v in campos.items():
        if k == "poligono":
            sets.append("poligono = %s")
            params.append(psycopg2.extras.Json(v) if v else None)
        elif k == "taxa":
            sets.append("taxa = %s")
            params.append(float(v))
        else:
            sets.append(f"{k} = %s")
            params.append(v)
    sets.append("atualizado_em = NOW()")
    params.append(area_id)

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE areas_cobertura SET {', '.join(sets)} WHERE id = %s RETURNING *",
            params,
        )
        row = cur.fetchone()
        if not row:
            return _err("area_nao_encontrada", 404)
        area = dict(row)

    return jsonify({"ok": True, "area": {
        "id": area["id"],
        "nome": area["nome"],
        "cidade": area.get("cidade"),
        "taxa": float(area["taxa"]),
        "status": area.get("status"),
    }})


@bp.delete("/areas/<int:area_id>")
def desativar_area(area_id: int):
    """Desativa área de cobertura (soft delete)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE areas_cobertura SET status = 'INATIVO', atualizado_em = NOW() WHERE id = %s RETURNING id",
            (area_id,),
        )
        row = cur.fetchone()
        if not row:
            return _err("area_nao_encontrada", 404)

    return jsonify({"ok": True})


# ============================================================
# Módulo 7: Cadastro de Entregadores
# ============================================================

@bp.get("/entregadores")
def listar_entregadores():
    """Lista todos os entregadores."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id, u.username, u.nome, u.telefone, u.empresa_id,
                   e.nome as empresa_nome, u.ativo,
                   u.localizacao_atual, u.ultima_localizacao_em, u.criado_em,
                   (SELECT COUNT(*) FROM ordens_servico o WHERE o.entregador_id = u.id AND o.status IN ('ATRIBUIDO','EM_ROTA')) as corridas_ativas,
                   (SELECT COUNT(*) FROM ordens_servico o WHERE o.entregador_id = u.id AND o.status = 'ENTREGUE') as total_entregues,
                   (SELECT COALESCE(SUM(c.valor_comissao), 0) FROM comissoes_entregador c WHERE c.entregador_id = u.id AND c.status = 'PENDENTE') as comissao_pendente,
                   (SELECT COALESCE(SUM(c.valor_comissao), 0) FROM comissoes_entregador c WHERE c.entregador_id = u.id) as comissao_total
            FROM usuarios u
            LEFT JOIN empresas e ON e.id = u.empresa_id
            WHERE u.perfil = 'ENTREGADOR'
            ORDER BY u.nome
        """)
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            loc = r.get("localizacao_atual")
            if isinstance(loc, str):
                try:
                    loc = json.loads(loc)
                except Exception:
                    loc = None
            items.append({
                "id": r["id"],
                "username": r.get("username"),
                "nome": r.get("nome"),
                "telefone": r.get("telefone"),
                "empresa": r.get("empresa_nome"),
                "empresa_id": r.get("empresa_id"),
                "ativo": r.get("ativo"),
                "localizacao": loc,
                "corridas_ativas": r.get("corridas_ativas", 0),
                "total_entregues": r.get("total_entregues", 0),
                "comissao_pendente": float(r.get("comissao_pendente") or 0),
                "comissao_total": float(r.get("comissao_total") or 0),
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
            })
    return jsonify({"ok": True, "entregadores": items})


@bp.post("/entregadores")
def criar_entregador():
    """Cadastra novo entregador."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    nome = str(data.get("nome") or "").strip()
    senha = str(data.get("senha") or "").strip()
    telefone = str(data.get("telefone") or "").strip()
    empresa_id = data.get("empresa_id")

    if not username or not nome or not senha:
        return _err("username, nome e senha sao obrigatorios", 400)

    # Verifica se username já existe
    existente = usuarios_repo.get_by_username(username)
    if existente:
        return _err("username_ja_existe", 409)

    novo = usuarios_repo.create(
        username=username, nome=nome, perfil="ENTREGADOR",
        empresa_id=empresa_id, telefone=telefone or None,
    )
    auth_service.definir_senha(novo["id"], senha)

    return jsonify({"ok": True, "entregador": {
        "id": novo["id"],
        "username": novo.get("username"),
        "nome": novo.get("nome"),
        "telefone": novo.get("telefone"),
        "empresa_id": novo.get("empresa_id"),
    }}), 201


@bp.put("/entregadores/<int:entregador_id>")
def atualizar_entregador(entregador_id: int):
    """Atualiza entregador (nome, telefone, empresa, ativo, senha)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    campos = {}
    for k in ("nome", "telefone", "empresa_id", "ativo"):
        if k in data:
            campos[k] = data[k]

    senha = data.get("senha")

    with transaction() as conn:
        cur = conn.cursor()
        if campos:
            sets = [f"{k} = %s" for k in campos]
            params = list(campos.values()) + [entregador_id]
            cur.execute(
                f"UPDATE usuarios SET {', '.join(sets)} WHERE id = %s AND perfil = 'ENTREGADOR' RETURNING *",
                params,
            )
            row = cur.fetchone()
            if not row:
                return _err("entregador_nao_encontrado", 404)

        if senha:
            auth_service.definir_senha(entregador_id, str(senha))

    return jsonify({"ok": True})


@bp.delete("/entregadores/<int:entregador_id>")
def desativar_entregador(entregador_id: int):
    """Desativa entregador (soft delete)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE usuarios SET ativo = FALSE WHERE id = %s AND perfil = 'ENTREGADOR' RETURNING id",
            (entregador_id,),
        )
        row = cur.fetchone()
        if not row:
            return _err("entregador_nao_encontrado", 404)

    return jsonify({"ok": True})


# ============================================================
# Empresas (para filtros)
# ============================================================

@bp.get("/empresas")
def listar_empresas():
    """Lista empresas para filtros/selects."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, nome, cnpj, ativo, config, endereco FROM empresas ORDER BY nome")
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            cfg = r.get("config")
            if isinstance(cfg, str):
                import json as _json
                try: cfg = _json.loads(cfg)
                except Exception: cfg = {}
            cfg = cfg or {}
            endereco = r.get("endereco")
            if isinstance(endereco, str):
                try:
                    import json as _json2
                    endereco = _json2.loads(endereco)
                except Exception:
                    endereco = None
            items.append({
                "id": r["id"],
                "nome": r["nome"],
                "cnpj": r.get("cnpj"),
                "ativo": r.get("ativo"),
                "endereco": endereco,
                "comissao_entregador_pct": float(cfg.get("comissao_entregador_pct", 70.0)),
            })
    return jsonify({"ok": True, "empresas": items})


@bp.put("/empresas/<empresa_id>/endereco")
def atualizar_endereco_empresa(empresa_id: str):
    """Atualiza endereço/coords da empresa para centralizar o mapa do portal."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    lat = data.get("lat")
    lng = data.get("lng")
    cidade = data.get("cidade")
    if lat is None or lng is None:
        return _err("lat e lng obrigatorios", 400)

    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return _err("lat e lng devem ser numeros", 400)

    import json as _json
    endereco = {"lat": lat, "lng": lng}
    if cidade:
        endereco["cidade"] = cidade

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM empresas WHERE id = %s", (empresa_id,))
        if not cur.fetchone():
            return _err("empresa_nao_encontrada", 404)
        cur.execute(
            "UPDATE empresas SET endereco = %s WHERE id = %s RETURNING id",
            (_json.dumps(endereco), empresa_id),
        )
        if not cur.fetchone():
            return _err("erro_ao_salvar", 500)

    return jsonify({"ok": True, "endereco": endereco})


@bp.put("/empresas/<empresa_id>/comissao")
def atualizar_comissao(empresa_id: str):
    """Atualiza o percentual de comissão do entregador para uma empresa."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    pct = data.get("comissao_entregador_pct")
    if pct is None:
        return _err("comissao_entregador_pct obrigatorio", 400)

    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return _err("comissao_entregador_pct deve ser numero", 400)

    if pct < 0 or pct > 100:
        return _err("comissao_entregador_pct deve estar entre 0 e 100", 400)

    with transaction() as conn:
        cur = conn.cursor()
        # Busca config atual
        cur.execute("SELECT config FROM empresas WHERE id = %s", (empresa_id,))
        row = cur.fetchone()
        if not row:
            return _err("empresa_nao_encontrada", 404)

        import json as _json
        cfg = row["config"]
        if isinstance(cfg, str):
            try: cfg = _json.loads(cfg)
            except Exception: cfg = {}
        cfg = cfg or {}
        cfg["comissao_entregador_pct"] = pct

        cur.execute(
            "UPDATE empresas SET config = %s WHERE id = %s RETURNING id",
            (_json.dumps(cfg), empresa_id),
        )
        if not cur.fetchone():
            return _err("empresa_nao_encontrada", 404)

    return jsonify({"ok": True, "comissao_entregador_pct": pct})


@bp.post("/empresas")
def criar_empresa():
    """Cria uma nova empresa (admin)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    empresa_id = (data.get("id") or "").strip()
    nome = (data.get("nome") or "").strip()
    if not empresa_id or not nome:
        return _err("id e nome obrigatórios", 400)

    if empresas_repo.get(empresa_id):
        return _err("empresa_ja_existe", 409)

    try:
        emp = empresas_repo.create(empresa_id, nome, cnpj=data.get("cnpj"), endereco=_parse_endereco(data))
    except Exception as e:
        logging.getLogger("admin").exception("Erro ao criar empresa")
        return _err(str(e), 500)

    # Cria config de frete padrão desabilitada
    try:
        frete_repo.upsert(empresa_id=empresa_id, enabled=False)
    except Exception:
        pass

    return jsonify({"ok": True, "empresa": _serializar_empresa(emp)})


@bp.put("/empresas/<empresa_id>")
def editar_empresa(empresa_id: str):
    """Edita nome, cnpj e ativo de uma empresa (admin)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    campos: dict[str, Any] = {}
    if "nome" in data:
        nome = (data.get("nome") or "").strip()
        if not nome:
            return _err("nome obrigatório", 400)
        campos["nome"] = nome
    if "cnpj" in data:
        campos["cnpj"] = (data.get("cnpj") or "").strip() or None
    if "ativo" in data:
        campos["ativo"] = bool(data.get("ativo"))
    if "endereco" in data:
        campos["endereco"] = _parse_endereco(data)

    if not campos:
        return _err("nada_para_atualizar", 400)

    try:
        emp = empresas_repo.update(empresa_id, **campos)
    except Exception as e:
        logging.getLogger("admin").exception("Erro ao editar empresa")
        return _err(str(e), 500)

    if not emp:
        return _err("empresa_nao_encontrada", 404)

    return jsonify({"ok": True, "empresa": _serializar_empresa(emp)})


@bp.get("/empresas/<empresa_id>/frete")
def obter_frete_empresa(empresa_id: str):
    """Obtém a configuração de frete de uma empresa (admin)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    if not empresas_repo.get(empresa_id):
        return _err("empresa_nao_encontrada", 404)

    cfg = frete_repo.get(empresa_id)
    if not cfg:
        return jsonify({"ok": True, "frete": {"enabled": False, "origin_maps_url": "", "base": None, "per_km": None, "min_v": None, "max_v": None}})
    return jsonify({"ok": True, "frete": cfg})


@bp.put("/empresas/<empresa_id>/frete")
def salvar_frete_empresa(empresa_id: str):
    """Salva a configuração de frete de uma empresa (admin)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    if not empresas_repo.get(empresa_id):
        return _err("empresa_nao_encontrada", 404)

    data = request.get_json(silent=True) or {}

    def _num(key):
        v = data.get(key)
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    try:
        cfg = frete_repo.upsert(
            empresa_id=empresa_id,
            enabled=bool(data.get("enabled")),
            origin_maps_url=data.get("origin_maps_url"),
            base=_num("base"),
            per_km=_num("per_km"),
            min_v=_num("min_v"),
            max_v=_num("max_v"),
        )
    except Exception as e:
        logging.getLogger("admin").exception("Erro ao salvar frete")
        return _err(str(e), 500)

    return jsonify({"ok": True, "frete": cfg})


def _parse_endereco(data: dict) -> dict | None:
    """Extrai endereco do payload de criar/editar empresa."""
    endereco = data.get("endereco")
    if isinstance(endereco, dict):
        return endereco
    # Formato flat: maps_url, rua, cidade, lat, lng
    maps_url = (data.get("maps_url") or "").strip()
    rua = (data.get("rua") or "").strip()
    cidade = (data.get("cidade") or "").strip()
    lat = data.get("lat")
    lng = data.get("lng")
    if not maps_url and not rua and lat is None:
        return None
    result: dict[str, Any] = {}
    if maps_url:
        result["maps_url"] = maps_url
    if rua:
        result["rua"] = rua
    if cidade:
        result["cidade"] = cidade
    if lat is not None and lng is not None:
        try:
            result["lat"] = float(lat)
            result["lng"] = float(lng)
        except (TypeError, ValueError):
            pass
    return result or None


def _serializar_empresa(row: dict) -> dict:
    """Serializa uma empresa para resposta JSON do admin."""
    cfg = row.get("config")
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    cfg = cfg or {}
    endereco = row.get("endereco")
    if isinstance(endereco, str):
        try:
            endereco = json.loads(endereco)
        except Exception:
            endereco = None
    return {
        "id": row["id"],
        "nome": row["nome"],
        "cnpj": row.get("cnpj"),
        "ativo": row.get("ativo"),
        "endereco": endereco,
        "comissao_entregador_pct": float(cfg.get("comissao_entregador_pct", 70.0)),
    }


# ============================================================
# Clientes (usuarios com perfil EMPRESA/CLIENTE — acessam o portal)
# ============================================================

@bp.get("/clientes")
def listar_clientes():
    """Lista usuarios-cliente (perfil EMPRESA/CLIENTE)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id, u.username, u.nome, u.telefone, u.empresa_id,
                   e.nome as empresa_nome, u.ativo, u.criado_em,
                   c.saldo_atual
            FROM usuarios u
            LEFT JOIN empresas e ON e.id = u.empresa_id
            LEFT JOIN carteiras c ON c.empresa_id = u.empresa_id
            WHERE u.perfil IN ('EMPRESA', 'CLIENTE')
            ORDER BY u.nome
        """)
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            items.append({
                "id": r["id"],
                "username": r.get("username"),
                "nome": r.get("nome"),
                "telefone": r.get("telefone"),
                "empresa": r.get("empresa_nome"),
                "empresa_id": r.get("empresa_id"),
                "saldo": float(r.get("saldo_atual") or 0),
                "ativo": r.get("ativo"),
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
            })
    return jsonify({"ok": True, "clientes": items})


@bp.post("/clientes")
def criar_cliente():
    """Cadastra novo cliente (acessa o portal)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    nome = str(data.get("nome") or "").strip()
    senha = str(data.get("senha") or "").strip()
    telefone = str(data.get("telefone") or "").strip()
    empresa_id = data.get("empresa_id")

    if not username or not nome or not senha or not empresa_id:
        return _err("username, nome, senha e empresa_id obrigatorios", 400)

    existente = usuarios_repo.get_by_username(username)
    if existente:
        return _err("username_ja_existe", 409)

    novo = usuarios_repo.create(
        username=username, nome=nome, perfil="EMPRESA",
        empresa_id=empresa_id, telefone=telefone or None,
    )
    auth_service.definir_senha(novo["id"], senha)

    return jsonify({"ok": True, "cliente": {
        "id": novo["id"],
        "username": novo.get("username"),
        "nome": novo.get("nome"),
        "empresa_id": novo.get("empresa_id"),
    }}), 201


@bp.put("/clientes/<int:cliente_id>")
def atualizar_cliente(cliente_id: int):
    """Atualiza cliente."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    campos = {}
    for k in ("nome", "telefone", "empresa_id", "ativo"):
        if k in data:
            campos[k] = data[k]
    senha = data.get("senha")

    with transaction() as conn:
        cur = conn.cursor()
        if campos:
            sets = [f"{k} = %s" for k in campos]
            params = list(campos.values()) + [cliente_id]
            cur.execute(
                f"UPDATE usuarios SET {', '.join(sets)} WHERE id = %s AND perfil IN ('EMPRESA','CLIENTE') RETURNING *",
                params,
            )
            row = cur.fetchone()
            if not row:
                return _err("cliente_nao_encontrado", 404)
        if senha:
            auth_service.definir_senha(cliente_id, str(senha))

    return jsonify({"ok": True})


@bp.delete("/clientes/<int:cliente_id>")
def desativar_cliente(cliente_id: int):
    """Desativa cliente."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE usuarios SET ativo = FALSE WHERE id = %s AND perfil IN ('EMPRESA','CLIENTE') RETURNING id",
            (cliente_id,),
        )
        row = cur.fetchone()
        if not row:
            return _err("cliente_nao_encontrado", 404)

    return jsonify({"ok": True})


# ============================================================
# Comissões — pagar e listar pendentes
# ============================================================

@bp.get("/comissoes")
def listar_comissoes():
    """Lista comissões dos entregadores (filtro por status)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    status = request.args.get("status", "")
    entregador_id = request.args.get("entregador_id")

    where = ["1=1"]
    params: list[Any] = []
    if status:
        where.append("c.status = %s")
        params.append(status.upper())
    if entregador_id:
        where.append("c.entregador_id = %s")
        params.append(int(entregador_id))

    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT c.id, c.entregador_id, c.ordem_id, c.taxa_total,
                   c.pct_comissao, c.valor_comissao, c.status,
                   c.criado_em, c.pago_em,
                   u.nome as entregador_nome,
                   o.protocolo, o.solicitacao_id
            FROM comissoes_entregador c
            LEFT JOIN usuarios u ON u.id = c.entregador_id
            LEFT JOIN ordens_servico o ON o.id = c.ordem_id
            WHERE {' AND '.join(where)}
            ORDER BY c.criado_em DESC
            LIMIT 500
        """, params)
        items = []
        for r in (dict(x) for x in cur.fetchall()):
            items.append({
                "id": r["id"],
                "entregador_id": r.get("entregador_id"),
                "entregador": r.get("entregador_nome"),
                "ordem_id": r.get("ordem_id"),
                "protocolo": r.get("protocolo"),
                "taxa_total": float(r["taxa_total"] or 0),
                "pct": float(r["pct_comissao"] or 0),
                "valor": float(r["valor_comissao"] or 0),
                "status": r.get("status"),
                "criado_em": r["criado_em"].isoformat() if r.get("criado_em") else None,
                "pago_em": r["pago_em"].isoformat() if r.get("pago_em") else None,
            })
    return jsonify({"ok": True, "comissoes": items})


@bp.post("/comissoes/pagar")
def pagar_comissoes():
    """Marca comissões como PAGAS (lote)."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    entregador_id = data.get("entregador_id")

    if not ids and not entregador_id:
        return _err("ids ou entregador_id obrigatorio", 400)

    with transaction() as conn:
        cur = conn.cursor()
        if ids:
            id_list = [int(i) for i in ids]
            cur.execute(
                """UPDATE comissoes_entregador
                   SET status = 'PAGO', pago_em = NOW()
                   WHERE id = ANY(%s) AND status = 'PENDENTE'
                   RETURNING id""",
                (id_list,),
            )
        else:
            cur.execute(
                """UPDATE comissoes_entregador
                   SET status = 'PAGO', pago_em = NOW()
                   WHERE entregador_id = %s AND status = 'PENDENTE'
                   RETURNING id""",
                (int(entregador_id),),
            )
        pagas = cur.rowcount

    return jsonify({"ok": True, "pagas": pagas})


# ------------------------------------------------------------------
# ATRIBUIR ORDEM A ENTREGADOR (admin/despachador)
# ------------------------------------------------------------------

@bp.post("/ordens/<int:ordem_id>/atribuir")
def admin_atribuir_ordem(ordem_id: int):
    """Admin atribui uma ordem pendente a um entregador específico."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    data = request.get_json(silent=True) or {}
    entregador_id = data.get("entregador_id")
    if not entregador_id:
        return _err("entregador_id_obrigatorio", 400)

    try:
        entregador_id = int(entregador_id)
    except (TypeError, ValueError):
        return _err("entregador_id_invalido", 400)

    with transaction() as conn:
        cur = conn.cursor()
        # Verifica se a ordem existe e está pendente
        cur.execute("SELECT * FROM ordens_servico WHERE id = %s", (ordem_id,))
        row = cur.fetchone()
        if not row:
            return _err("ordem_nao_encontrada", 404)
        ordem = dict(row)
        if ordem.get("status") not in ("PENDENTE", "ATRIBUIDO"):
            return _err("ordem_nao_pode_ser_atribuida", 400)

        # Verifica se o entregador existe e está ativo
        cur.execute(
            "SELECT id, nome, ativo FROM usuarios WHERE id = %s AND perfil = 'ENTREGADOR'",
            (entregador_id,),
        )
        ent_row = cur.fetchone()
        if not ent_row:
            return _err("entregador_nao_encontrado", 404)
        if not dict(ent_row).get("ativo"):
            return _err("entregador_inativo", 400)

        # Atribui
        cur.execute(
            """UPDATE ordens_servico
               SET status = 'ATRIBUIDO', entregador_id = %s, atribuido_em = NOW()
               WHERE id = %s
               RETURNING id, uuid, protocolo, status, entregador_id, taxa""",
            (entregador_id, ordem_id),
        )
        updated = cur.fetchone()
        if not updated:
            return _err("falha_atribuir", 500)
        result = dict(updated)

    # Notifica o entregador via push
    try:
        from app.services import push as push_service
        enviadas = push_service.enviar_notificacao(
            usuario_id=entregador_id,
            titulo="Ordem atribuída a você!",
            corpo=f"{result.get('protocolo', '')} — abra o app para iniciar a rota",
            dados={"ordem_id": ordem_id, "acao": "ver"},
        )
        import logging as _log
        _log.getLogger("admin").info("Push atribuir: enviadas=%s para usuario=%s", enviadas, entregador_id)
    except Exception as e:
        import logging as _log
        _log.getLogger("admin").error("Push atribuir FALHOU: %s", e)

    return jsonify({
        "ok": True,
        "ordem": {
            "id": result.get("id"),
            "protocolo": result.get("protocolo"),
            "status": result.get("status"),
            "entregador_id": result.get("entregador_id"),
            "taxa": float(result.get("taxa") or 0),
        },
    })


# ------------------------------------------------------------------
# DEBUG: estado do push (inscrições por entregador)
# ------------------------------------------------------------------

@bp.get("/push/debug")
def admin_push_debug():
    """Retorna estado das inscrições push para debug."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    from app.core import config as cfg
    vapid_configurado = bool(cfg.VAPID_PUBLIC_KEY and cfg.VAPID_PRIVATE_KEY)

    with connect() as conn:
        cur = conn.cursor()
        # Lista entregadores com suas inscrições push
        cur.execute("""
            SELECT u.id, u.nome, u.username, u.ativo,
                   COUNT(ps.id) as total_subs,
                   MAX(ps.id) as ultima_sub_id
            FROM usuarios u
            LEFT JOIN push_subscriptions ps ON ps.usuario_id = u.id
            WHERE u.perfil = 'ENTREGADOR'
            GROUP BY u.id, u.nome, u.username, u.ativo
            ORDER BY u.nome
        """)
        entregadores = []
        for r in (dict(x) for x in cur.fetchall()):
            entregadores.append({
                "id": r["id"],
                "nome": r.get("nome"),
                "username": r.get("username"),
                "ativo": r.get("ativo"),
                "total_inscricoes": r.get("total_subs", 0),
                "tem_inscricao": (r.get("total_subs", 0) or 0) > 0,
            })

    return jsonify({
        "ok": True,
        "vapid_configurado": vapid_configurado,
        "vapid_public_key_prefix": (cfg.VAPID_PUBLIC_KEY or "")[:20] + "..." if cfg.VAPID_PUBLIC_KEY else None,
        "entregadores": entregadores,
    })


@bp.post("/push/teste/<int:entregador_id>")
def admin_push_teste_entregador(entregador_id: int):
    """Admin envia push de teste para um entregador específico."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    from app.services import push as push_service

    if not push_service.is_enabled():
        return _err("push_desabilitado_vapid_nao_configurado", 503)

    enviadas = push_service.enviar_notificacao(
        usuario_id=entregador_id,
        titulo="REMO — Notificação de teste (admin)",
        corpo="Esta é uma notificação de teste enviada pelo administrador.",
        dados={"tipo": "teste_admin"},
    )

    if enviadas == 0:
        return _err("sem_inscricoes_validas", 404)

    return jsonify({"ok": True, "enviadas": enviadas})


# ------------------------------------------------------------------
# Limpar dados de teste (ordens, comissões, localizações)
# ------------------------------------------------------------------

@bp.post("/limpar-dados")
def admin_limpar_dados():
    """Remove todas as ordens, comissões e localizações de teste."""
    user = _requer_admin()
    if not user:
        return _err("nao_autenticado", 401)

    with transaction() as conn:
        cur = conn.cursor()
        # Remove comissões
        cur.execute("DELETE FROM comissoes_entregador RETURNING id")
        comissoes = cur.rowcount
        # Remove ordens
        cur.execute("DELETE FROM ordens_servico RETURNING id")
        ordens = cur.rowcount
        # Remove localizações de entregadores
        cur.execute("UPDATE usuarios SET localizacao_atual = NULL, ultima_localizacao_em = NULL WHERE perfil = 'ENTREGADOR'")
        locs = cur.rowcount
        # Remove trilha de rastreamento
        cur.execute("DELETE FROM rastreamento RETURNING id")
        trilha = cur.rowcount
        # Remove inscrições push antigas
        cur.execute("DELETE FROM push_subscriptions RETURNING id")
        subs = cur.rowcount

    import logging as _log
    _log.getLogger("admin").info("Limpar dados: %d ordens, %d comissoes, %d locs, %d trilha, %d subs", ordens, comissoes, locs, trilha, subs)

    return jsonify({
        "ok": True,
        "removidos": {
            "ordens": ordens,
            "comissoes": comissoes,
            "localizacoes": locs,
            "rastreamento": trilha,
            "push_subscriptions": subs,
        },
    })
