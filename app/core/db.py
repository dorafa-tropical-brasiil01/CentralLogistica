"""Conexão e transações com PostgreSQL."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection

from . import config

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    return bool(config.DATABASE_URL)


def get_sslmode() -> str:
    return "require" if "railway" in (config.DATABASE_URL or "") else "prefer"


@contextmanager
def connect() -> Generator[connection, None, None]:
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL não configurado")

    conn = psycopg2.connect(
        dsn=config.DATABASE_URL,
        sslmode=get_sslmode(),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction() -> Generator[connection, None, None]:
    with connect() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
