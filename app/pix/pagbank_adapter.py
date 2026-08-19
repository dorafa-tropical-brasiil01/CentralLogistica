"""Adapter do PagBank para PIX."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from .adapter_contract import (
    CreatePaymentRequest,
    CreatePaymentResult,
    PaymentEvent,
    PaymentMethod,
    PaymentProviderAdapter,
    PaymentStatusResult,
    PaymentStatus,
    QRCodeData,
)

logger = logging.getLogger(__name__)

SANDBOX_BASE_URL = "https://sandbox.api.pagseguro.com"
PRODUCTION_BASE_URL = "https://api.pagseguro.com"

_STATUS_MAP = {
    "WAITING": PaymentStatus.PENDING,
    "IN_ANALYSIS": PaymentStatus.PENDING,
    "AUTHORIZED": PaymentStatus.PENDING,
    "PAID": PaymentStatus.APPROVED,
    "DECLINED": PaymentStatus.DECLINED,
    "CANCELED": PaymentStatus.CANCELLED,
    "EXPIRED": PaymentStatus.EXPIRED,
}


def _reais_to_centavos(reais: float) -> int:
    return int(round(reais * 100))


def _centavos_to_reais(centavos: int | float | None) -> float | None:
    if centavos is None:
        return None
    return float(centavos) / 100.0


def _normalize_status(raw: str | None) -> PaymentStatus:
    if raw is None:
        return PaymentStatus.PENDING
    return _STATUS_MAP.get(str(raw).strip().upper(), PaymentStatus.PENDING)


def _safe_str_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


class PagBankAdapter(PaymentProviderAdapter):
    def __init__(
        self,
        *,
        token: str,
        webhook_token: str | None = None,
        sandbox: bool = True,
        base_url: str | None = None,
    ) -> None:
        self._token = token
        self._webhook_token = webhook_token
        self._base_url = (
            base_url.rstrip("/")
            if base_url
            else (SANDBOX_BASE_URL if sandbox else PRODUCTION_BASE_URL)
        )

    @property
    def provider_id(self) -> str:
        return "PAGBANK"

    def _request(
        self,
        *,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "REMO/1.0",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read()
            logger.warning("PagBank API HTTPError %s url=%s body=%s", e.code, url, raw[:500])
            raise

    def create_payment(self, request: CreatePaymentRequest) -> CreatePaymentResult:
        amount_centavos = _reais_to_centavos(request.amount)
        expira = datetime.now(timezone.utc) + timedelta(seconds=request.expires_in_seconds)

        body: dict[str, Any] = {
            "reference_id": request.reference_id,
            "customer": {
                "name": "Empresa REMO",
                "email": "financeiro@dorafatropicalbrasil.com.br",
                "tax_id": "12345678909",
            },
            "items": [{
                "name": request.description or "Abastecimento",
                "quantity": 1,
                "unit_amount": amount_centavos,
            }],
            "qr_codes": [{"amount": {"value": amount_centavos}}],
        }

        resp = self._request(method="POST", path="/orders", body=body)
        order_id = str(resp.get("id") or "")
        if not order_id:
            raise RuntimeError("PagBank não retornou Order ID")

        qr = None
        qr_codes = resp.get("qr_codes") or []
        if qr_codes:
            q = qr_codes[0]
            qr = QRCodeData(
                payload=str(q.get("text") or ""),
                image_base64=None,
                image_url=self._extract_image_url(q),
            )

        raw_exp = qr_codes[0].get("expiration_date") if qr_codes else None
        expires_at = datetime.fromisoformat(raw_exp) if raw_exp else expira

        return CreatePaymentResult(
            provider_transaction_id=order_id,
            status=_normalize_status(resp.get("status")),
            qr_code=qr,
            expires_at=expires_at,
        )

    def _extract_image_url(self, qr: dict[str, Any]) -> str | None:
        for link in qr.get("links") or []:
            if isinstance(link, dict):
                media = str(link.get("media") or "").upper()
                if "IMAGE" in media or "PNG" in media:
                    return str(link.get("href") or "") or None
        return None

    def get_payment_status(self, provider_transaction_id: str) -> PaymentStatusResult:
        try:
            resp = self._request(method="GET", path=f"/orders/{provider_transaction_id}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return PaymentStatusResult(
                    provider_transaction_id=provider_transaction_id,
                    status=PaymentStatus.PENDING,
                )
            raise

        amount = None
        charges = resp.get("charges") or []
        if charges:
            amount = _centavos_to_reais(charges[0].get("amount", {}).get("value"))

        return PaymentStatusResult(
            provider_transaction_id=provider_transaction_id,
            status=_normalize_status(resp.get("status")),
            amount=amount,
        )

    def validate_webhook(self, headers: dict[str, str], body: bytes) -> PaymentEvent | None:
        if self._webhook_token:
            signature = headers.get("x-authenticity-token") or ""
            expected = hashlib.sha256(
                f"{self._webhook_token}-{body.decode('utf-8', errors='replace')}".encode()
            ).hexdigest()
            if not _safe_str_eq(signature, expected):
                logger.warning("validate_webhook - assinatura inválida")
                return None

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(payload, dict):
            return None

        order_id = str(payload.get("id") or "")
        if not order_id:
            return None

        amount = None
        charges = payload.get("charges") or []
        if charges:
            amount = _centavos_to_reais(charges[0].get("amount", {}).get("value"))

        return PaymentEvent(
            provider_transaction_id=order_id,
            status=_normalize_status(payload.get("status")),
            event_id=hashlib.sha256(body).hexdigest(),
            amount=amount,
            occurred_at=datetime.now(timezone.utc),
            raw_payload=body.decode("utf-8", errors="replace"),
        )
