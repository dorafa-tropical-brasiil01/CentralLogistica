"""Configuração central da REMO."""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = env(key, "true" if default else "").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


DATABASE_URL = env("DATABASE_URL")
SECRET_KEY = env("SECRET_KEY") or secrets.token_hex(32)
CENTRAL_LOGISTICA_API_KEY = env("CENTRAL_LOGISTICA_API_KEY", "dev-key")
CARDAPIO_WEBHOOK_URL = env("CARDAPIO_WEBHOOK_URL", "")
CARDAPIO_WEBHOOK_SECRET = env("CARDAPIO_WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "")

PIX_PROVIDER = env("PIX_PROVIDER", "mock").lower()
PIX_TOKEN = env("PIX_TOKEN", "")
PIX_WEBHOOK_SECRET = env("PIX_WEBHOOK_SECRET", "")
PIX_SANDBOX = env("PIX_SANDBOX", "1").lower() in ("1", "true", "yes", "y", "on")

VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = env("VAPID_SUBJECT", "mailto:contato@dorafatropicalbrasil.com.br")


def is_pix_online_enabled() -> bool:
    return env_bool("REMO_PIX_ONLINE_ENABLED", True)
