"""Factory da aplicação Flask."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from app.core import config
from app.migracoes.runner import ensure_schema
from app.pix.webhook import processar as processar_webhook_pix

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(BASE_DIR / "static"),
        template_folder=str(BASE_DIR / "templates"),
    )
    app.secret_key = config.SECRET_KEY

    ensure_schema()

    # Blueprints
    from app.api import admin, financeiro, frete, ordens, portal, pwa
    app.register_blueprint(financeiro.bp, url_prefix="/api/v1")
    app.register_blueprint(ordens.bp, url_prefix="/api/v1")
    app.register_blueprint(frete.bp, url_prefix="/api/v1")
    app.register_blueprint(pwa.bp, url_prefix="/api/pwa")
    app.register_blueprint(admin.bp, url_prefix="/api/admin")
    app.register_blueprint(portal.bp, url_prefix="/api/portal")

    # PWA — página do entregador
    @app.route("/")
    def index_page():
        return render_template("index.html")

    # Admin — painel administrativo
    @app.route("/admin")
    def admin_page():
        return render_template("admin/index.html")

    # Portal — área do cliente
    @app.route("/portal")
    def portal_page():
        return render_template("portal/index.html")

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
