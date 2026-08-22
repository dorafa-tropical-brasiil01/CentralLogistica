"""Serviço de Web Push (VAPID) para notificar entregadores."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core import config
from app.core.db import connect, transaction

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    return bool(config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY)


def _vapid_claims() -> dict[str, str]:
    return {"sub": config.VAPID_SUBJECT or "mailto:contato@dorafatropicalbrasil.com.br"}


def inscrever(*, usuario_id: int, endpoint: str, p256dh: str, auth: str) -> int:
    """Inscreve (ou atualiza) uma inscrição push para o usuário."""
    logger.info("inscrever: usuario_id=%s endpoint=%s", usuario_id, endpoint[:60])
    with transaction() as conn:
        cur = conn.cursor()
        # Remove inscrições antigas do mesmo endpoint
        cur.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
        # Verifica se a coluna keys_json existe (schema antigo)
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'push_subscriptions' AND column_name = 'keys_json'
        """)
        has_keys_json = cur.fetchone() is not None

        if has_keys_json:
            import json as _json
            cur.execute(
                """
                INSERT INTO push_subscriptions (usuario_id, endpoint, p256dh, auth, keys_json)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (usuario_id, endpoint, p256dh, auth, _json.dumps({"p256dh": p256dh, "auth": auth})),
            )
        else:
            cur.execute(
                """
                INSERT INTO push_subscriptions (usuario_id, endpoint, p256dh, auth)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (usuario_id, endpoint, p256dh, auth),
            )
        row = cur.fetchone()
        sub_id = row["id"] if row else 0
        logger.info("inscrever: OK sub_id=%s para usuario_id=%s", sub_id, usuario_id)
        return sub_id


def desinscrever(*, endpoint: str) -> bool:
    """Remove uma inscrição push."""
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM push_subscriptions WHERE endpoint = %s RETURNING id", (endpoint,))
        return cur.fetchone() is not None


def _get_subscriptions(usuario_id: int | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        cur = conn.cursor()
        if usuario_id:
            cur.execute(
                "SELECT id, usuario_id, endpoint, p256dh, auth FROM push_subscriptions WHERE usuario_id = %s",
                (usuario_id,),
            )
        else:
            cur.execute("SELECT id, usuario_id, endpoint, p256dh, auth FROM push_subscriptions")
        return [dict(x) for x in cur.fetchall()]


def _remover_inscricao_invalida(sub_id: int) -> None:
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM push_subscriptions WHERE id = %s", (sub_id,))


def enviar_notificacao(
    *,
    usuario_id: int,
    titulo: str,
    corpo: str,
    dados: dict[str, Any] | None = None,
) -> int:
    """Envia push notification para um usuário. Retorna quantas foram enviadas com sucesso."""
    if not is_enabled():
        logger.warning("Web Push desabilitado — VAPID keys não configuradas")
        return 0

    from pywebpush import webpush, WebPushException

    subs = _get_subscriptions(usuario_id)
    if not subs:
        logger.info("Sem inscrições push para usuário %s", usuario_id)
        return 0

    payload = json.dumps({
        "title": titulo,
        "body": corpo,
        "data": dados or {},
        "icon": "/static/logo-remo.png",
        "badge": "/static/logo-remo.png",
        "tag": "remo-ordem",
        "requireInteraction": True,
    })

    enviadas = 0
    # Prepara a chave privada VAPID
    # py_vapid.from_string() não detecta PEM — precisa de base64url DER
    vapid_key_raw = config.VAPID_PRIVATE_KEY
    vapid_key = vapid_key_raw
    try:
        from cryptography.hazmat.primitives.serialization import (
            load_pem_private_key, Encoding, PrivateFormat, NoEncryption
        )
        import base64 as _b64

        if "|" in vapid_key_raw:
            # Formato com | como separador — reconstrói PEM
            parts = [p.strip() for p in vapid_key_raw.split("|") if p.strip()]
            pem_str = "\n".join(parts) + "\n"
        elif "-----BEGIN" in vapid_key_raw:
            pem_str = vapid_key_raw
        else:
            pem_str = None

        if pem_str:
            # Parse PEM e converte para base64url DER (formato que py_vapid aceita)
            parsed = load_pem_private_key(pem_str.encode("utf-8"), password=None)
            der_bytes = parsed.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
            vapid_key = _b64.urlsafe_b64encode(der_bytes).decode("utf-8").rstrip("=")
            logger.info("VAPID key convertida PEM -> base64url DER (len=%s)", len(vapid_key))
        else:
            # Já está em base64url DER ou outro formato — usa direto
            logger.info("VAPID key usada direto (len=%s)", len(vapid_key))
    except Exception as e:
        logger.error("Erro ao preparar VAPID key: %s", e)

    for sub in subs:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        try:
            logger.info("Enviando push para sub %s, endpoint=%s", sub["id"], sub["endpoint"][:50])
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=vapid_key,
                vapid_claims=_vapid_claims(),
            )
            enviadas += 1
            logger.info("Push enviado com sucesso para sub %s", sub["id"])
        except WebPushException as e:
            logger.warning("Push falhou para sub %s: %s", sub["id"], e)
            if hasattr(e, "response") and e.response:
                logger.warning("Push response: %s %s", e.response.status_code, e.response.text[:200] if hasattr(e.response, 'text') else '')
                if e.response.status_code in (404, 410):
                    _remover_inscricao_invalida(sub["id"])
        except Exception as e:
            logger.error("Erro ao enviar push para sub %s: %s (%s)", sub["id"], e, type(e).__name__)

    return enviadas


def notificar_entregadores_disponiveis(*, ordem_id: int, protocolo: str, taxa: float) -> int:
    """Notifica todos os entregadores ativos sobre nova ordem disponível."""
    if not is_enabled():
        return 0

    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id, u.nome FROM usuarios u
            WHERE u.perfil = 'ENTREGADOR' AND u.ativo = TRUE
        """)
        entregadores = [dict(x) for x in cur.fetchall()]

    total_enviadas = 0
    for ent in entregadores:
        enviadas = enviar_notificacao(
            usuario_id=ent["id"],
            titulo="Nova entrega disponível!",
            corpo=f"{protocolo} — Taxa: R$ {taxa:.2f}".replace(".", ","),
            dados={"ordem_id": ordem_id, "protocolo": protocolo, "taxa": taxa, "acao": "reivindicar"},
        )
        total_enviadas += enviadas

    logger.info("Push enviado para %d entregadores, %d inscrições ativas", len(entregadores), total_enviadas)
    return total_enviadas
