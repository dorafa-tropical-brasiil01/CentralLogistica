"""Factory da aplicação Flask."""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, request

from app.core import config
from app.migracoes.runner import ensure_schema
from app.pix.webhook import processar as processar_webhook_pix


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY

    ensure_schema()

    # Blueprints
    from app.api import financeiro
    app.register_blueprint(financeiro.bp, url_prefix="/api/v1")

    @app.route("/")
    def index():
        return jsonify({
            "ok": True,
            "service": "Central Logística (REMO)",
            "version": "0.1.0",
            "health": "/health",
            "api": "/api/v1",
        })

    @app.route("/health")
    def health():
        return jsonify({"ok": True})

    @app.post("/api/v1/webhooks/pix")
    def webhook_pix():
        body = request.get_data() or b""
        headers = {k.lower(): v for k, v in request.headers.items()}
        try:
            result = processar_webhook_pix(headers=headers, body=body)
        except Exception as e:
            logging.exception("webhook_pix - erro")
            return jsonify({"error": str(e)}), 500

        if result is None:
            return jsonify({"ok": False, "reason": "invalid"}), 200

        return jsonify({"ok": True, "abastecimento_id": result.get("id")}), 200

    return app
