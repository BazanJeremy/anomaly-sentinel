"""
Fintech transaction schema — Pydantic v2 contracts.

Defines the canonical data shape for all transaction events flowing through
the Anomaly Sentinel pipeline. Any data that fails validation is rejected
before reaching the AI classifier, ensuring the model only sees clean input.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class Currency(str, Enum):
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"
    CHF = "CHF"
    JPY = "JPY"


class TransactionType(str, Enum):
    PURCHASE = "purchase"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"
    REFUND = "refund"
    INTERNATIONAL = "international"


class MerchantCategory(str, Enum):
    RETAIL = "retail"
    FOOD = "food"
    TRAVEL = "travel"
    ENTERTAINMENT = "entertainment"
    CRYPTO = "crypto"
    GAMBLING = "gambling"
    UTILITIES = "utilities"
    HEALTHCARE = "healthcare"
    UNKNOWN = "unknown"


class GeoLocation(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    city: str = Field(..., min_length=1, max_length=100)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)


class DeviceInfo(BaseModel):
    device_id: str = Field(..., min_length=8)
    ip_address: str = Field(..., pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
    user_agent: str = Field(..., min_length=5)
    is_known_device: bool = True


class Transaction(BaseModel):
    """
    Canonical transaction event.

    Validation rules enforce business-level constraints beyond simple types,
    e.g. daily_total must always include the current transaction amount.
    """

    transaction_id: UUID
    account_id: str = Field(..., min_length=10, max_length=30)
    timestamp: datetime
    amount: Decimal = Field(..., gt=Decimal("0"), le=Decimal("999999.99"))
    currency: Currency
    transaction_type: TransactionType
    merchant_category: MerchantCategory
    merchant_name: str = Field(..., min_length=1, max_length=200)
    location: GeoLocation
    device: DeviceInfo
    previous_location: Optional[GeoLocation] = None
    previous_transaction_timestamp: Optional[datetime] = None
    account_age_days: int = Field(..., ge=0)
    daily_transaction_count: int = Field(..., ge=0)
    daily_total_amount: Decimal = Field(..., ge=Decimal("0"))

    @field_validator("amount")
    @classmethod
    def amount_precision(cls, v: Decimal) -> Decimal:
        """Enforce max 2 decimal places for fiat amounts."""
        if v != round(v, 2):
            raise ValueError("Amount must have at most 2 decimal places")
        return v

    @model_validator(mode="after")
    def daily_total_must_include_current(self) -> "Transaction":
        """Daily total must be >= current amount (current tx is included)."""
        if self.daily_total_amount < self.amount:
            raise ValueError(
                f"daily_total_amount ({self.daily_total_amount}) "
                f"cannot be less than current amount ({self.amount})"
            )
        return self

    @model_validator(mode="after")
    def previous_timestamp_must_predate_current(self) -> "Transaction":
        if (
            self.previous_transaction_timestamp
            and self.previous_transaction_timestamp >= self.timestamp
        ):
            raise ValueError("previous_transaction_timestamp must predate timestamp")
        return self

    def to_classifier_context(self) -> dict:
        """
        Serialize to a flat dict optimised for LLM prompt injection.
        Strips internal IDs; keeps only signals relevant to anomaly detection.
        """
        ctx: dict = {
            "amount": float(self.amount),
            "currency": self.currency.value,
            "type": self.transaction_type.value,
            "merchant_category": self.merchant_category.value,
            "location_country": self.location.country_code,
            "account_age_days": self.account_age_days,
            "daily_tx_count": self.daily_transaction_count,
            "daily_total_eur_equiv": float(self.daily_total_amount),
            "is_known_device": self.device.is_known_device,
        }
        if self.previous_location:
            ctx["previous_country"] = self.previous_location.country_code
        if self.previous_transaction_timestamp:
            delta = self.timestamp - self.previous_transaction_timestamp
            ctx["minutes_since_last_tx"] = round(delta.total_seconds() / 60, 1)
        return ctx
