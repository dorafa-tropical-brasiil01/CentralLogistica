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

    Regra: max(taxa_zona, taxa_distancia).
    - Se o endereço cai em uma zona, usa max(taxa_zona, taxa_distancia).
    - Se não cai em zona, usa só taxa_distancia (haversine).
    - Se a zona é grátis (taxa=0), o cliente paga 0.
    - Zona específica da empresa tem prioridade sobre zona global.

    Retorna None se não houver configuração ou não for possível calcular.
    """
    client_url = str(client_maps_url or "").strip()

    # --- Calcula taxa por zona (se houver) ---
    zone_fee: float | None = None
    zone_name: str | None = None
    zone_gratis: bool = False

    if client_url:
        from app.repositories import areas as areas_repo

        # 1. Zona específica da empresa (override) tem prioridade
        areas_emp = areas_repo.listar_ativas_por_empresa(empresa_id)
        if areas_emp:
            zone_calc = frete_calc.compute_fee_by_zone(
                client_maps_url=client_url,
                areas=areas_emp,
            )
            if zone_calc:
                zone_fee = float(zone_calc["fee"])
                zone_name = zone_calc.get("zone")
                logger.info(
                    "frete por zona empresa=%s zona=%s fee=%.2f",
                    empresa_id, zone_name, zone_fee,
                )

        # 2. Zona global (todas as cidades ativas)
        if zone_fee is None:
            areas = areas_repo.listar_todas_ativas()
            if areas:
                zone_calc = frete_calc.compute_fee_by_zone(
                    client_maps_url=client_url,
                    areas=areas,
                )
                if zone_calc:
                    zone_fee = float(zone_calc["fee"])
                    zone_name = zone_calc.get("zone")
                    logger.info(
                        "frete por zona global zona=%s cidade=%s fee=%.2f",
                        zone_name, zone_calc.get("cidade"), zone_fee,
                    )

    # --- Calcula taxa por distância (haversine) ---
    distance_fee: float | None = None
    cfg = frete_repo.get(empresa_id)
    if cfg and bool(cfg.get("enabled") or False):
        origin = str(cfg.get("origin_maps_url") or origin_maps_url or "").strip()
        if origin and client_url:
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
                client_maps_url=client_url,
            )
            if calc:
                distance_fee = float(calc["fee"])
                logger.info(
                    "frete por distancia empresa=%s distancia=%.2fkm fee=%.2f",
                    empresa_id, calc["distance_km"], distance_fee,
                )

    # --- Regra final: max(zona, distancia) ---
    if zone_fee is not None and zone_fee == 0:
        # Zona grátis: cliente paga 0
        logger.info("frete final: zona gratis (%s) → 0.00", zone_name)
        return 0.0

    if zone_fee is not None and distance_fee is not None:
        final_fee = max(float(zone_fee), float(distance_fee))
        logger.info(
            "frete final: max(zona=%.2f, distancia=%.2f) = %.2f [%s]",
            zone_fee, distance_fee, final_fee, zone_name,
        )
        return float(final_fee)

    if zone_fee is not None:
        logger.info("frete final: zona apenas = %.2f [%s]", zone_fee, zone_name)
        return float(zone_fee)

    if distance_fee is not None:
        logger.info("frete final: distancia apenas = %.2f", distance_fee)
        return float(distance_fee)

    logger.info("frete nao calculado para empresa %s", empresa_id)
    return None


def atualizar_status(
    *,
    ordem_id: int,
    status: str,
    entregador_id: int | None = None,
) -> dict[str, Any]:
    with transaction() as conn:
        # Se o entregador cancela a corrida, a ordem volta para PENDENTE
        # (disponível para outros entregadores) em vez de ficar CANCELADO.
        if status == "CANCELADO":
            ordens.update_status(conn, ordem_id, "PENDENTE", clear_entregador=True)
        else:
            ordens.update_status(conn, ordem_id, status, entregador_id=entregador_id)

        # Comissão automática do entregador quando entrega é concluída
        if status == "ENTREGUE":
            _registrar_comissao(conn, ordem_id)

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


def _registrar_comissao(conn, ordem_id: int) -> None:
    """Registra comissão do entregador (percentual da taxa).

    Idempotente: se já existe comissão para a ordem, não faz nada.
    Percentual padrão: 70% da taxa. Configurável por empresa em
    empresas.config.comissao_entregador_pct.
    """
    import psycopg2.extras

    cur = conn.cursor()
    # Verifica se já existe comissão
    cur.execute(
        "SELECT id FROM comissoes_entregador WHERE ordem_id = %s",
        (ordem_id,),
    )
    if cur.fetchone():
        return

    # Busca a ordem
    cur.execute(
        "SELECT id, entregador_id, taxa, empresa_id FROM ordens_servico WHERE id = %s",
        (ordem_id,),
    )
    row = cur.fetchone()
    if not row or not row["entregador_id"]:
        return

    taxa_total = float(row["taxa"] or 0)
    entregador_id = row["entregador_id"]
    empresa_id = row["empresa_id"]

    # Busca percentual de comissão da empresa
    pct = 70.0  # padrão
    cur.execute("SELECT config FROM empresas WHERE id = %s", (empresa_id,))
    emp_row = cur.fetchone()
    if emp_row and emp_row["config"]:
        config = emp_row["config"]
        if isinstance(config, str):
            import json
            try:
                config = json.loads(config)
            except Exception:
                config = {}
        if isinstance(config, dict):
            pct = float(config.get("comissao_entregador_pct", 70.0))

    valor_comissao = round(taxa_total * pct / 100, 2)

    cur.execute(
        """
        INSERT INTO comissoes_entregador
            (entregador_id, ordem_id, taxa_total, pct_comissao, valor_comissao, status)
        VALUES (%s, %s, %s, %s, %s, 'PENDENTE')
        """,
        (entregador_id, ordem_id, taxa_total, pct, valor_comissao),
    )
