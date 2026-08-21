"""Rotas do PWA da Central Logística (despachador + entregador)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from app.repositories import ordens as ordens_repo
from app.repositories import usuarios as usuarios_repo
from app.services import auth as auth_service
from app.services import ordens as ordens_service

bp = Blueprint("pwa", __name__)


def _extrair_token() -> str:
    # Token pode vir no header Authorization ou na sessão
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return session.get("remo_token", "")


def _usuario_atual() -> dict | None:
    token = _extrair_token()
    return auth_service.verificar_token(token)


def _requer_login() -> dict | None:
    """Retorna usuário atual ou None (para a rota retornar 401)."""
    return _usuario_atual()


# --- Autenticação ---

@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    senha = str(data.get("senha") or "").strip()

    if not username or not senha:
        return jsonify({"error": "credenciais_obrigatorias"}), 400

    result = auth_service.login(username, senha)
    if not result:
        return jsonify({"error": "credenciais_invalidas"}), 401

    session["remo_token"] = result["token"]
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


@bp.post("/logout")
def logout():
    token = _extrair_token()
    auth_service.logout(token)
    session.pop("remo_token", None)
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    user = _requer_login()
    if not user:
        return jsonify({"error": "nao_autenticado"}), 401
    return jsonify({
        "ok": True,
        "usuario": {
            "id": user["usuario_id"],
            "nome": user.get("nome"),
            "perfil": user.get("perfil"),
            "username": user.get("username"),
            "empresa_id": user.get("empresa_id"),
        },
    })


# --- Despachador: ordens pendentes ---

@bp.get("/ordens")
def listar_ordens():
    user = _requer_login()
    if not user:
        return jsonify({"error": "nao_autenticado"}), 401

    status = request.args.get("status", "PENDENTE")
    if status == "PENDENTE":
        ordens = ordens_repo.list_pendentes()
    elif status == "ATIVAS":
        ordens = ordens_repo.list_ativas()
    elif status == "ENTREGUES":
        ordens = ordens_repo.list_recent_entregues(limit=20)
    else:
        ordens = ordens_repo.list_pendentes()

    return jsonify({"ok": True, "ordens": [_serializar_ordem(o) for o in ordens]})


# --- Despachador: entregadores ---

@bp.get("/entregadores")
def listar_entregadores():
    user = _requer_login()
    if not user:
        return jsonify({"error": "nao_autenticado"}), 401

    entregadores = usuarios_repo.list_entregadores()

    # Adiciona info de corrida ativa
    ativas = ordens_repo.list_ativas()
    por_entregador: dict[int, list] = {}
    for o in ativas:
        eid = o.get("entregador_id")
        if eid:
            por_entregador.setdefault(eid, []).append(o)

    result = []
    for e in entregadores:
        corridas = por_entregador.get(e["id"], [])
        result.append({
            "id": e["id"],
            "nome": e.get("nome"),
            "username": e.get("username"),
            "telefone": e.get("telefone"),
            "status": "busy" if corridas else "online",
            "corridas_ativas": len(corridas),
            "localizacao": e.get("localizacao_atual"),
            "ultima_localizacao_em": e.get("ultima_localizacao_em"),
        })

    return jsonify({"ok": True, "entregadores": result})


# --- Despachador: atribuir ordem ---

@bp.post("/ordens/<int:ordem_id>/atribuir")
def atribuir_ordem(ordem_id: int):
    user = _requer_login()
    if not user:
        return jsonify({"error": "nao_autenticado"}), 401

    data = request.get_json(silent=True) or {}
    entregador_id = data.get("entregador_id")
    if not entregador_id:
        return jsonify({"error": "entregador_id_obrigatorio"}), 400

    ordem = ordens_repo.get(ordem_id)
    if not ordem:
        return jsonify({"error": "ordem_nao_encontrada"}), 404

    if ordem.get("status") not in ("PENDENTE", "ATRIBUIDO"):
        return jsonify({"error": "ordem_nao_pode_ser_atribuida"}), 400

    try:
        ordem = ordens_service.atualizar_status(
            ordem_id=ordem_id,
            status="ATRIBUIDO",
            entregador_id=int(entregador_id),
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"ok": True, "ordem": _serializar_ordem(ordem)})


# --- Entregador: minhas corridas ---

@bp.get("/minhas-corridas")
def minhas_corridas():
    user = _requer_login()
    if not user:
        return jsonify({"error": "nao_autenticado"}), 401

    ordens = ordens_repo.list_by_entregador(user["usuario_id"])
    return jsonify({"ok": True, "corridas": [_serializar_ordem(o) for o in ordens]})


# --- Entregador: ordens disponíveis para reivindicar ---

@bp.get("/disponiveis")
def ordens_disponiveis():
    """Lista ordens pendentes que o entregador pode reivindicar."""
    user = _requer_login()
    if not user:
        return jsonify({"error": "nao_autenticado"}), 401

    # Entregador com corrida ativa não pode ver disponíveis
    ativas = ordens_repo.list_by_entregador(user["usuario_id"])
    if ativas:
        return jsonify({"ok": True, "disponiveis": [], "motivo": "ja_tem_corrida_ativa"})

    pendentes = ordens_repo.list_pendentes()
    return jsonify({"ok": True, "disponiveis": [_serializar_ordem(o) for o in pendentes]})


# --- Entregador: reivindicar ordem ---

@bp.post("/ordens/<int:ordem_id>/reivindicar")
def reivindicar_ordem(ordem_id: int):
    """Entregador reivindica uma ordem. Primeiro chega, primeiro leva.
    Desempate por proximidade se dois reivindicam no mesmo segundo.
    """
    user = _requer_login()
    if not user:
        return jsonify({"error": "nao_autenticado"}), 401

    if user.get("perfil") != "ENTREGADOR":
        return jsonify({"error": "apenas_entregador_pode_reivindicar"}), 403

    # Verifica se já tem corrida ativa
    ativas = ordens_repo.list_by_entregador(user["usuario_id"])
    if ativas:
        return jsonify({"error": "ja_tem_corrida_ativa"}), 403

    # Reivindicação atômica com FOR UPDATE
    from app.core.db import transaction
    from app.core import frete as frete_calc

    try:
        with transaction() as conn:
            cur = conn.cursor()
            # Bloqueia a ordem para evitar race condition
            cur.execute(
                "SELECT * FROM ordens_servico WHERE id = %s FOR UPDATE",
                (ordem_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "ordem_nao_encontrada"}), 404

            ordem = dict(row)

            if ordem.get("status") not in ("PENDENTE",):
                return jsonify({"error": "ordem_ja_atribuida", "status": ordem.get("status")}), 409

            # Atribui ao entregador
            ordens_repo.update_status(
                conn, ordem_id, "ATRIBUIDO", entregador_id=user["usuario_id"]
            )
            cur.execute("SELECT * FROM ordens_servico WHERE id = %s", (ordem_id,))
            ordem = dict(cur.fetchone())

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Notifica outros entregadores (push notification — futuro)
    # Por enquanto, apenas retorna sucesso
    return jsonify({"ok": True, "ordem": _serializar_ordem(ordem)})


# --- Entregador: atualizar status ---

@bp.post("/ordens/<int:ordem_id>/status")
def atualizar_status(ordem_id: int):
    user = _requer_login()
    if not user:
        return jsonify({"error": "nao_autenticado"}), 401

    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or "").strip().upper()

    permitidos = {"EM_ROTA", "ENTREGUE", "CANCELADO", "DEVOLVIDO"}
    if status not in permitidos:
        return jsonify({"error": "status_invalido", "permitidos": list(permitidos)}), 400

    ordem = ordens_repo.get(ordem_id)
    if not ordem:
        return jsonify({"error": "ordem_nao_encontrada"}), 404

    # Entregador só pode atualizar suas próprias ordens
    if user.get("perfil") == "ENTREGADOR" and ordem.get("entregador_id") != user["usuario_id"]:
        return jsonify({"error": "ordem_nao_pertence_ao_entregador"}), 403

    try:
        ordem = ordens_service.atualizar_status(ordem_id=ordem_id, status=status)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"ok": True, "ordem": _serializar_ordem(ordem)})


# --- Entregador: enviar localização ---

@bp.post("/localizacao")
def enviar_localizacao():
    user = _requer_login()
    if not user:
        return jsonify({"error": "nao_autenticado"}), 401

    data = request.get_json(silent=True) or {}
    lat = data.get("lat")
    lng = data.get("lng")
    precisao = data.get("precisao")

    if lat is None or lng is None:
        return jsonify({"error": "lat_e_lng_obrigatorios"}), 400

    try:
        usuarios_repo.update_localizacao(
            usuario_id=user["usuario_id"],
            lat=float(lat),
            lng=float(lng),
            precisao=float(precisao) if precisao is not None else None,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"ok": True})


# --- Helpers ---

def _serializar_ordem(o: dict) -> dict:
    return {
        "id": o.get("id"),
        "uuid": o.get("uuid"),
        "protocolo": o.get("protocolo"),
        "solicitacao_id": o.get("solicitacao_id"),
        "empresa_id": o.get("empresa_id"),
        "status": o.get("status"),
        "taxa": float(o.get("taxa") or 0),
        "entregador_id": o.get("entregador_id"),
        "payload": o.get("payload_json"),
        "criado_em": o.get("criado_em"),
        "atribuido_em": o.get("atribuido_em"),
        "em_rota_em": o.get("em_rota_em"),
        "entregue_em": o.get("entregue_em"),
    }


# --- Admin: criar usuários (protegido por API key) ---

@bp.post("/admin/usuarios")
def admin_criar_usuario():
    from app.core import config as cfg
    header_key = request.headers.get("x-api-key", "")
    if header_key != cfg.CENTRAL_LOGISTICA_API_KEY:
        return jsonify({"error": "nao_autorizado"}), 401

    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    nome = str(data.get("nome") or "").strip()
    perfil = str(data.get("perfil") or "").strip().upper()
    senha = str(data.get("senha") or "").strip()
    telefone = str(data.get("telefone") or "").strip() or None
    empresa_id = str(data.get("empresa_id") or "").strip() or None

    if not username or not nome or not perfil or not senha:
        return jsonify({"error": "username, nome, perfil e senha obrigatorios"}), 400

    if perfil not in ("ADMIN", "CENTRAL", "ENTREGADOR", "OPERADOR", "EMPRESA", "CLIENTE"):
        return jsonify({"error": "perfil_invalido"}), 400

    from app.repositories import usuarios as usuarios_repo
    existente = usuarios_repo.get_by_username(username)
    if existente:
        return jsonify({"error": "username_ja_existe"}), 409

    user = usuarios_repo.create(username=username, nome=nome, perfil=perfil, empresa_id=empresa_id, telefone=telefone)
    auth_service.definir_senha(user["id"], senha)

    return jsonify({"ok": True, "usuario": {"id": user["id"], "username": user.get("username"), "nome": user.get("nome"), "perfil": user.get("perfil")}}), 201
