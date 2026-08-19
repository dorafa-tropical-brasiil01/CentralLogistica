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
        logger.info("Schema aplicado com sucesso")
