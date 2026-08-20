"""Envio de webhooks da REMO para o Cardápio."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from app.core import config

logger = logging.getLogger(__name__)


def enviar_status(
    *,
    solicitacao_id: str,
    status: str,
    empresa_id: str,
    ordem_uuid: str | None = None,
    protocolo: str | None = None,
    entregador: dict[str, Any] | None = None,
    nota: str | None = None,
) -> bool:
    url = str(config.CARDAPIO_WEBHOOK_URL or "").strip()
    if not url:
        logger.warning("CARDAPIO_WEBHOOK_URL nao configurado; webhook nao enviado")
        return False

    payload = {
        "empresa_id": empresa_id,
        "solicitacao_id": solicitacao_id,
        "status": status,
        "evento": status,
        "ordem_uuid": ordem_uuid,
        "protocolo": protocolo,
        "entregador": entregador or {},
        "nota": nota,
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.CARDAPIO_WEBHOOK_SECRET or ''}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return int(resp.status) == 200
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        logger.warning("webhook Cardapio retornou %s: %s", e.code, raw[:500])
        return False
    except Exception:
        logger.exception("falha ao enviar webhook para Cardapio")
        return False
