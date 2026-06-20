"""
Fintech schema contract tests.

Validates that the Pydantic Transaction model enforces all business-level
constraints. These tests serve double duty:
  1. Guard the schema against accidental regressions
  2. Document every validation rule as executable specification

Naming convention: test_<field>_<rule>_<expected_outcome>
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.schemas.transaction import (
    Currency, DeviceInfo, GeoLocation,
    MerchantCategory, Transaction, TransactionType,
)
from src.simulators.fintech.generator import (
    SCENARIO_LABELS, ScenarioName, generate_batch,
    generate_fraud_scenario, generate_mixed_dataset,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def valid_transaction_payload() -> dict:
    """Minimal valid transaction — used as base for mutation tests."""
    now = datetime.now(timezone.utc)
    return {
        "transaction_id": uuid.uuid4(),
        "account_id": "ACC-1234567890",
        "timestamp": now,
        "amount": Decimal("42.50"),
        "currency": Currency.EUR,
        "transaction_type": TransactionType.PURCHASE,
        "merchant_category": MerchantCategory.RETAIL,
        "merchant_name": "Test Merchant",
        "location": GeoLocation(
            country_code="FR", city="Paris",
            latitude=48.85, longitude=2.35,
        ),
        "device": DeviceInfo(
            device_id="DEV-ABCD1234",
            ip_address="82.45.12.100",
            user_agent="Mozilla/5.0",
            is_known_device=True,
        ),
        "account_age_days": 730,
        "daily_transaction_count": 2,
        "daily_total_amount": Decimal("92.50"),
    }


# ---------------------------------------------------------------------------
# Schema validation — happy path
# ---------------------------------------------------------------------------

class TestTransactionValidHappyPath:
    def test_minimal_valid_transaction_passes(self, valid_transaction_payload):
        tx = Transaction(**valid_transaction_payload)
        assert tx.amount == Decimal("42.50")
        assert tx.currency == Currency.EUR

    def test_all_currencies_accepted(self, valid_transaction_payload):
        for currency in Currency:
            payload = {**valid_transaction_payload, "currency": currency}
            tx = Transaction(**payload)
            assert tx.currency == currency

    def test_all_merchant_categories_accepted(self, valid_transaction_payload):
        for cat in MerchantCategory:
            payload = {**valid_transaction_payload, "merchant_category": cat}
            tx = Transaction(**payload)
            assert tx.merchant_category == cat


# ---------------------------------------------------------------------------
# Amount validation
# ---------------------------------------------------------------------------

class TestAmountValidation:
    def test_amount_zero_rejected(self, valid_transaction_payload):
        payload = {**valid_transaction_payload, "amount": Decimal("0.00"),
                   "daily_total_amount": Decimal("0.00")}
        with pytest.raises(ValidationError) as exc_info:
            Transaction(**payload)
        assert "greater than 0" in str(exc_info.value)

    def test_amount_negative_rejected(self, valid_transaction_payload):
        payload = {**valid_transaction_payload, "amount": Decimal("-10.00")}
        with pytest.raises(ValidationError):
            Transaction(**payload)

    def test_amount_exceeds_max_rejected(self, valid_transaction_payload):
        payload = {**valid_transaction_payload,
                   "amount": Decimal("1000000.00"),
                   "daily_total_amount": Decimal("1000000.00")}
        with pytest.raises(ValidationError):
            Transaction(**payload)

    def test_amount_three_decimal_places_rejected(self, valid_transaction_payload):
        payload = {**valid_transaction_payload, "amount": Decimal("10.123"),
                   "daily_total_amount": Decimal("10.123")}
        with pytest.raises(ValidationError) as exc_info:
            Transaction(**payload)
        assert "decimal places" in str(exc_info.value)

    def test_amount_max_boundary_accepted(self, valid_transaction_payload):
        payload = {**valid_transaction_payload,
                   "amount": Decimal("999999.99"),
                   "daily_total_amount": Decimal("999999.99")}
        tx = Transaction(**payload)
        assert tx.amount == Decimal("999999.99")


# ---------------------------------------------------------------------------
# Cross-field validators
# ---------------------------------------------------------------------------

class TestCrossFieldValidation:
    def test_daily_total_less_than_amount_rejected(self, valid_transaction_payload):
        """daily_total_amount must be >= amount (current tx is included)."""
        payload = {
            **valid_transaction_payload,
            "amount": Decimal("100.00"),
            "daily_total_amount": Decimal("50.00"),   # Less than amount — invalid
        }
        with pytest.raises(ValidationError) as exc_info:
            Transaction(**payload)
        assert "daily_total_amount" in str(exc_info.value)

    def test_previous_timestamp_after_current_rejected(self, valid_transaction_payload):
        now = datetime.now(timezone.utc)
        payload = {
            **valid_transaction_payload,
            "timestamp": now,
            "previous_transaction_timestamp": now + timedelta(hours=1),  # Future — invalid
        }
        with pytest.raises(ValidationError) as exc_info:
            Transaction(**payload)
        assert "previous_transaction_timestamp" in str(exc_info.value)

    def test_previous_timestamp_equal_to_current_rejected(self, valid_transaction_payload):
        now = datetime.now(timezone.utc)
        payload = {
            **valid_transaction_payload,
            "timestamp": now,
            "previous_transaction_timestamp": now,
        }
        with pytest.raises(ValidationError):
            Transaction(**payload)

    def test_previous_timestamp_before_current_accepted(self, valid_transaction_payload):
        now = datetime.now(timezone.utc)
        payload = {
            **valid_transaction_payload,
            "timestamp": now,
            "previous_transaction_timestamp": now - timedelta(hours=3),
        }
        tx = Transaction(**payload)
        assert tx.previous_transaction_timestamp < tx.timestamp


# ---------------------------------------------------------------------------
# Geo location validation
# ---------------------------------------------------------------------------

class TestGeoLocationValidation:
    def test_invalid_country_code_length_rejected(self, valid_transaction_payload):
        payload = {**valid_transaction_payload,
                   "location": {"country_code": "FRA", "city": "Paris",
                                "latitude": 48.85, "longitude": 2.35}}
        with pytest.raises(ValidationError):
            Transaction(**payload)

    def test_latitude_out_of_range_rejected(self, valid_transaction_payload):
        payload = {**valid_transaction_payload,
                   "location": {"country_code": "FR", "city": "Paris",
                                "latitude": 95.0, "longitude": 2.35}}
        with pytest.raises(ValidationError):
            Transaction(**payload)

    def test_longitude_out_of_range_rejected(self, valid_transaction_payload):
        payload = {**valid_transaction_payload,
                   "location": {"country_code": "FR", "city": "Paris",
                                "latitude": 48.85, "longitude": 200.0}}
        with pytest.raises(ValidationError):
            Transaction(**payload)


# ---------------------------------------------------------------------------
# classifier_context serialisation
# ---------------------------------------------------------------------------

class TestClassifierContextSerialization:
    def test_to_classifier_context_contains_required_keys(self, valid_transaction_payload):
        tx = Transaction(**valid_transaction_payload)
        ctx = tx.to_classifier_context()
        required_keys = {"amount", "currency", "type", "merchant_category",
                         "location_country", "account_age_days",
                         "daily_tx_count", "daily_total_eur_equiv", "is_known_device"}
        assert required_keys.issubset(ctx.keys())

    def test_to_classifier_context_excludes_pii(self, valid_transaction_payload):
        tx = Transaction(**valid_transaction_payload)
        ctx = tx.to_classifier_context()
        assert "transaction_id" not in ctx
        assert "account_id" not in ctx
        assert "ip_address" not in ctx

    def test_minutes_since_last_tx_computed_when_previous_timestamp_set(
        self, valid_transaction_payload
    ):
        now = datetime.now(timezone.utc)
        payload = {
            **valid_transaction_payload,
            "timestamp": now,
            "previous_transaction_timestamp": now - timedelta(minutes=90),
        }
        tx = Transaction(**payload)
        ctx = tx.to_classifier_context()
        assert "minutes_since_last_tx" in ctx
        assert abs(ctx["minutes_since_last_tx"] - 90.0) < 1.0


# ---------------------------------------------------------------------------
# Generator integration tests
# ---------------------------------------------------------------------------

class TestFintechGenerator:
    @pytest.mark.parametrize("scenario", [
        "normal_purchase", "velocity_burst", "geo_impossible",
        "dormant_account_spike", "card_testing", "high_risk_category",
    ])
    def test_scenario_produces_valid_transaction(self, scenario: ScenarioName):
        """Every scenario must produce schema-valid output."""
        tx = generate_fraud_scenario(scenario)
        assert isinstance(tx, Transaction)

    def test_geo_impossible_locations_differ(self):
        tx = generate_fraud_scenario("geo_impossible")
        assert tx.location.country_code != tx.previous_location.country_code

    def test_velocity_burst_high_daily_count(self):
        for _ in range(5):
            tx = generate_fraud_scenario("velocity_burst")
            assert tx.daily_transaction_count >= 25

    def test_dormant_account_uses_unknown_device(self):
        for _ in range(5):
            tx = generate_fraud_scenario("dormant_account_spike")
            assert not tx.device.is_known_device

    def test_card_testing_micro_amount(self):
        for _ in range(10):
            tx = generate_fraud_scenario("card_testing")
            assert tx.amount <= Decimal("1.00")

    def test_batch_generation_count(self):
        batch = generate_batch("normal_purchase", n=15)
        assert len(batch) == 15
        assert all(isinstance(tx, Transaction) for tx in batch)

    def test_mixed_dataset_has_correct_distribution(self):
        dataset = generate_mixed_dataset(n_per_scenario=5)
        total_scenarios = 6
        assert len(dataset) == total_scenarios * 5

    def test_scenario_labels_match_expected_ground_truth(self):
        """Sanity: labels dict is consistent with anomaly scenarios."""
        assert SCENARIO_LABELS["normal_purchase"]["is_anomaly"] is False
        assert SCENARIO_LABELS["geo_impossible"]["severity"] == "critical"
        assert SCENARIO_LABELS["velocity_burst"]["severity"] == "high"

    def test_unknown_scenario_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            generate_fraud_scenario("nonexistent_fraud_type")
