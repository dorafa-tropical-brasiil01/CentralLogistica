"""Adapter mock para testes de PIX."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

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


class MockAdapter(PaymentProviderAdapter):
    def __init__(self) -> None:
        self._orders: dict[str, dict] = {}

    @property
    def provider_id(self) -> str:
        return "MOCK"

    def create_payment(self, request: CreatePaymentRequest) -> CreatePaymentResult:
        order_id = f"ORDE_MOCK_{uuid.uuid4().hex[:12]}"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=request.expires_in_seconds)
        self._orders[order_id] = {"status": PaymentStatus.PENDING, "amount": request.amount}
        return CreatePaymentResult(
            provider_transaction_id=order_id,
            status=PaymentStatus.PENDING,
            qr_code=QRCodeData(
                payload=f"00020126{order_id}",
                image_url=f"https://mock.psp.com/qr/{order_id}.png",
            ),
            expires_at=expires_at,
        )

    def get_payment_status(self, provider_transaction_id: str) -> PaymentStatusResult:
        order = self._orders.get(provider_transaction_id)
        if order is None:
            return PaymentStatusResult(
                provider_transaction_id=provider_transaction_id,
                status=PaymentStatus.PENDING,
            )
        return PaymentStatusResult(
            provider_transaction_id=provider_transaction_id,
            status=order["status"],
            amount=order["amount"],
        )

    def set_status(self, provider_transaction_id: str, status: PaymentStatus) -> None:
        if provider_transaction_id in self._orders:
            self._orders[provider_transaction_id]["status"] = status

    def validate_webhook(self, headers: dict[str, str], body: bytes) -> PaymentEvent | None:
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return None

        order_id = str(payload.get("id") or "")
        if not order_id:
            return None

        raw_status = str(payload.get("status", "WAITING")).upper()
        status_map = {
            "WAITING": PaymentStatus.PENDING,
            "PAID": PaymentStatus.APPROVED,
            "DECLINED": PaymentStatus.DECLINED,
            "CANCELED": PaymentStatus.CANCELLED,
        }

        return PaymentEvent(
            provider_transaction_id=order_id,
            status=status_map.get(raw_status, PaymentStatus.PENDING),
            event_id=hashlib.sha256(body).hexdigest(),
            amount=payload.get("amount"),
            occurred_at=datetime.now(timezone.utc),
        )
