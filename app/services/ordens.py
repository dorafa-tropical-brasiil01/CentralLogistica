"""Serviço de ordens de serviço de logística."""

from __future__ import annotations

import logging
from typing import Any

from app.core import frete as frete_calc
from app.core.db import transaction
from app.core.ids import new_uuid
from app.repositories import carteiras, empresas, frete as frete_repo, ordens
from app.services import movimentacoes, webhooks_enviados

logger = logging.getLogger(__name__)


def criar(
    *,
    empresa_id: str,
    solicitacao_id: str,
    taxa_cliente: float = 0.0,
    origin_maps_url: str | None = None,
    client_maps_url: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Cria ordem de serviço calculando e debitando o frete real da REMO.

    A taxa enviada pelo Cardápio (taxa_cliente) é apenas informativa.
    O valor debitado é calculado pela REMO com sua própria configuração.
    """
    empresa = empresas.get(empresa_id)
    if not empresa:
        raise RuntimeError("empresa_nao_encontrada")

    carteira = carteiras.get_by_empresa(empresa_id)
    if not carteira:
        raise RuntimeError("carteira_nao_encontrada")

    # Calcula frete real pela configuração da REMO
    taxa_real = _calcular_frete_real(
        empresa_id=empresa_id,
        origin_maps_url=origin_maps_url,
        client_maps_url=client_maps_url,
    )

    # Se não há configuração de frete na REMO, usa a taxa do cliente como fallback
    if taxa_real is None:
        taxa_real = float(taxa_cliente or 0.0)

    if taxa_real < 0:
        raise RuntimeError("taxa_invalida")

    with transaction() as conn:
        # Evita duplicidade por solicitacao
        ordem_existente = ordens.get_by_solicitacao(empresa_id, solicitacao_id)
        if ordem_existente:
            return ordem_existente

        try:
            mov = movimentacoes.criar(
                conn=conn,
                carteira_id=carteira["id"],
                tipo="DEBITO",
                valor=taxa_real,
                descricao=f"Taxa de entrega pedido {solicitacao_id}",
                idempotency_key=idempotency_key,
            )
        except RuntimeError as e:
            if str(e) == "saldo_insuficiente":
                raise RuntimeError("saldo_insuficiente")
            raise

        protocolo = f"OS-{new_uuid().replace('-', '')[:12].upper()}"

        # Adiciona dados de frete no payload
        payload_completo = dict(payload or {})
        payload_completo["taxa_cliente"] = float(taxa_cliente or 0.0)
        payload_completo["taxa_real"] = float(taxa_real)
        payload_completo["origin_maps_url"] = origin_maps_url
        payload_completo["client_maps_url"] = client_maps_url

        ordem = ordens.create(
            conn=conn,
            empresa_id=empresa_id,
            solicitacao_id=solicitacao_id,
            movimentacao_id=mov["id"],
            taxa=taxa_real,
            payload=payload_completo,
            protocolo=protocolo,
        )

        return ordem


def _calcular_frete_real(
    *,
    empresa_id: str,
    origin_maps_url: str | None,
    client_maps_url: str | None,
) -> float | None:
    """Calcula o frete real usando a configuração da REMO.

    Retorna None se não houver configuração ou não for possível calcular.
    """
    cfg = frete_repo.get(empresa_id)
    if not cfg:
        logger.info("frete_config nao encontrada para empresa %s", empresa_id)
        return None

    if not bool(cfg.get("enabled") or False):
        logger.info("frete desabilitado para empresa %s", empresa_id)
        return None

    origin = str(cfg.get("origin_maps_url") or origin_maps_url or "").strip()
    client = str(client_maps_url or "").strip()
    if not origin or not client:
        logger.info("coordenadas insuficientes: origin=%s client=%s", bool(origin), bool(client))
        return None

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
        origin_maps_url=origin,
        client_maps_url=client,
    )
    if not calc:
        logger.info("calculo de frete retornou None para empresa %s", empresa_id)
        return None

    logger.info(
        "frete calculado empresa=%s distancia=%.2fkm fee=%.2f",
        empresa_id, calc["distance_km"], calc["fee"],
    )
    return float(calc["fee"])


def atualizar_status(
    *,
    ordem_id: int,
    status: str,
    entregador_id: int | None = None,
) -> dict[str, Any]:
    with transaction() as conn:
        ordens.update_status(conn, ordem_id, status, entregador_id=entregador_id)

    ordem = ordens.get(ordem_id) or {}

    # Notifica Cardápio sobre mudança de status
    if status in ("ATRIBUIDO", "EM_ROTA", "ENTREGUE"):
        webhooks_enviados.enviar_status(
            solicitacao_id=str(ordem.get("solicitacao_id") or ""),
            status=status,
            empresa_id=str(ordem.get("empresa_id") or ""),
            ordem_uuid=ordem.get("uuid"),
            protocolo=ordem.get("protocolo"),
        )

    return ordem
