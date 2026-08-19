"""Contrato do provedor de PIX."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PaymentMethod(str, Enum):
    PIX = "PIX"


@dataclass(frozen=True)
class QRCodeData:
    payload: str
    image_base64: str | None = None
    image_url: str | None = None


@dataclass(frozen=True)
class CreatePaymentRequest:
    amount: float
    payment_method: PaymentMethod
    reference_id: str
    description: str | None = None
    expires_in_seconds: int = 1800


@dataclass(frozen=True)
class CreatePaymentResult:
    provider_transaction_id: str
    status: PaymentStatus
    qr_code: QRCodeData | None
    expires_at: datetime


@dataclass(frozen=True)
class PaymentStatusResult:
    provider_transaction_id: str
    status: PaymentStatus
    amount: float | None = None


@dataclass(frozen=True)
class PaymentEvent:
    provider_transaction_id: str
    status: PaymentStatus
    event_id: str
    amount: float | None = None
    occurred_at: datetime | None = None
    raw_payload: str | None = None


class PaymentProviderAdapter(ABC):
    @property
    @abstractmethod
    def provider_id(self) -> str:
        ...

    @abstractmethod
    def create_payment(self, request: CreatePaymentRequest) -> CreatePaymentResult:
        ...

    @abstractmethod
    def get_payment_status(self, provider_transaction_id: str) -> PaymentStatusResult:
        ...

    @abstractmethod
    def validate_webhook(self, headers: dict[str, str], body: bytes) -> PaymentEvent | None:
        ...
