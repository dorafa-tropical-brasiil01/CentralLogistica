"""Executor de migrações/schema."""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.db import is_enabled, transaction

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def ensure_schema() -> None:
    if not is_enabled():
        logger.warning("DATABASE_URL não configurado; schema não criado")
        return

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

        # Migração: push_subscriptions — adicionar colunas p256dh/auth se não existirem
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'push_subscriptions' AND column_name = 'p256dh'
        """)
        if not cur.fetchone():
            cur.execute("""
                ALTER TABLE push_subscriptions
                ADD COLUMN IF NOT EXISTS p256dh TEXT,
                ADD COLUMN IF NOT EXISTS auth TEXT
            """)
            # Migra dados de keys_json se existir
            cur.execute("""
                UPDATE push_subscriptions
                SET p256dh = COALESCE(keys_json->>'p256dh', ''),
                    auth = COALESCE(keys_json->>'auth', '')
                WHERE keys_json IS NOT NULL AND p256dh IS NULL
            """)
            logger.info("Migração push_subscriptions: colunas p256dh/auth adicionadas")

        # Migração: areas_cobertura — adicionar coluna cor se não existir
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'areas_cobertura' AND column_name = 'cor'
        """)
        if not cur.fetchone():
            cur.execute("ALTER TABLE areas_cobertura ADD COLUMN IF NOT EXISTS cor TEXT DEFAULT '#00d4aa'")
            logger.info("Migração areas_cobertura: coluna cor adicionada")

        # Migração: areas_cobertura — tornar empresa_id opcional (NULL = zona global)
        cur.execute("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'areas_cobertura' AND column_name = 'empresa_id'
        """)
        row = cur.fetchone()
        if row and row["is_nullable"] == "NO":
            cur.execute("ALTER TABLE areas_cobertura ALTER COLUMN empresa_id DROP NOT NULL")
            logger.info("Migração areas_cobertura: empresa_id agora é opcional (zona global por cidade)")

        # Migração: limpar empresa_id das zonas existentes (viram globais da cidade)
        cur.execute("UPDATE areas_cobertura SET empresa_id = NULL WHERE empresa_id IS NOT NULL")
        if cur.rowcount > 0:
            logger.info("Migração areas_cobertura: %d zonas convertidas para global (empresa_id=NULL)", cur.rowcount)

        logger.info("Schema aplicado com sucesso")
