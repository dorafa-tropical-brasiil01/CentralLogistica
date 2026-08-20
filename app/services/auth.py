"""Serviço de autenticação da REMO (PWA)."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from app.repositories import usuarios

# Sessões em memória (MVP). Em produção, usar Redis ou DB.
_SESSOES: dict[str, dict[str, Any]] = {}
_SESSAO_TTL = 8 * 3600  # 8 horas


def _hash_senha(senha: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{senha}".encode()).hexdigest()


def _gerar_salt() -> str:
    return secrets.token_hex(16)


def _gerar_token() -> str:
    return secrets.token_urlsafe(32)


def login(username: str, senha: str) -> dict[str, Any] | None:
    """Autentica usuário e retorna token de sessão."""
    user = usuarios.get_by_username(username)
    if not user or not user.get("ativo"):
        return None

    salt = user.get("senha_salt") or ""
    hash_esperado = user.get("senha_hash") or ""

    if not salt or not hash_esperado:
        # MVP: se não tem senha configurada, aceita senha = username
        # (para facilitar testes iniciais)
        if senha == username:
            pass
        else:
            return None
    else:
        if _hash_senha(senha, salt) != hash_esperado:
            return None

    token = _gerar_token()
    _SESSOES[token] = {
        "usuario_id": user["id"],
        "username": user.get("username"),
        "nome": user.get("nome"),
        "perfil": user.get("perfil"),
        "empresa_id": user.get("empresa_id"),
        "expira_em": time.time() + _SESSAO_TTL,
    }
    return {"token": token, "usuario": _SESSOES[token]}


def verificar_token(token: str) -> dict[str, Any] | None:
    """Verifica token de sessão. Retorna dados do usuário ou None."""
    if not token:
        return None
    sessao = _SESSOES.get(token)
    if not sessao:
        return None
    if time.time() > sessao.get("expira_em", 0):
        _SESSOES.pop(token, None)
        return None
    # Renova TTL
    sessao["expira_em"] = time.time() + _SESSAO_TTL
    return sessao


def logout(token: str) -> None:
    _SESSOES.pop(token, None)


def definir_senha(usuario_id: int, senha: str) -> bool:
    """Define/atualiza senha de um usuário."""
    salt = _gerar_salt()
    hash_senha = _hash_senha(senha, salt)
    from app.core.db import transaction
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE usuarios SET senha_hash = %s, senha_salt = %s WHERE id = %s",
            (hash_senha, salt, usuario_id),
        )
    return True
