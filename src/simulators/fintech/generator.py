"""
Fintech transaction generator.

Produces labeled transaction datasets for testing the AI anomaly classifier.
Each scenario returns a Transaction that is valid against the Pydantic schema
AND carries a known ground-truth label — essential for precision/recall tests.

Fraud patterns implemented (based on real AML/fraud detection literature):
  1. velocity_burst       — many small transactions in a short window
  2. geo_impossible       — two locations physically unreachable in elapsed time
  3. dormant_account_spike— first activity in 90+ days, high amount
  4. card_testing         — tiny probe amounts before a large hit
  5. high_risk_category   — crypto/gambling on a retail-profile account
  6. normal_purchase      — clean baseline (labeled non-anomaly)
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from faker import Faker

from src.schemas.transaction import (
    Currency, DeviceInfo, GeoLocation,
    MerchantCategory, Transaction, TransactionType,
)

fake = Faker(["en_GB", "fr_FR", "de_DE"])

# ---------------------------------------------------------------------------
# Static geo fixtures (country_code, city, lat, lon)
# ---------------------------------------------------------------------------
GEO_PARIS    = ("FR", "Paris",     48.8566,   2.3522)
GEO_LONDON   = ("GB", "London",    51.5074,  -0.1278)
GEO_ZURICH   = ("CH", "Zurich",    47.3769,   8.5417)
GEO_TOKYO    = ("JP", "Tokyo",     35.6762, 139.6503)
GEO_LAGOS    = ("NG", "Lagos",      6.5244,   3.3792)
GEO_MOSCOW   = ("RU", "Moscow",    55.7558,  37.6173)
GEO_NEW_YORK = ("US", "New York",  40.7128, -74.0060)

KNOWN_DEVICE = DeviceInfo(
    device_id="DEV-" + "A1B2C3D4",
    ip_address="82.45.12.100",
    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
    is_known_device=True,
)

UNKNOWN_DEVICE = DeviceInfo(
    device_id="DEV-" + "X9Y8Z7W6",
    ip_address="185.220.101.34",   # Tor exit node range (mock)
    user_agent="python-requests/2.31.0",
    is_known_device=False,
)


def _make_geo(geo_tuple: tuple) -> GeoLocation:
    return GeoLocation(
        country_code=geo_tuple[0], city=geo_tuple[1],
        latitude=geo_tuple[2], longitude=geo_tuple[3],
    )


def _base_account() -> dict:
    """Shared fields for a healthy retail account. Device is NOT included here —
    each scenario injects its own device to make fraud signals explicit."""
    return {
        "transaction_id": uuid.uuid4(),
        "account_id": f"ACC-{fake.numerify('##########')}",
        "currency": Currency.EUR,
    }


# ---------------------------------------------------------------------------
# Scenario factories
# ---------------------------------------------------------------------------

def scenario_normal_purchase() -> Transaction:
    """
    Typical retail purchase — labeled CLEAN.
    Low amount, home country, known device, moderate daily activity.
    """
    now = datetime.now(timezone.utc)
    amount = Decimal(str(round(random.uniform(5.0, 150.0), 2)))
    daily_total = amount + Decimal(str(round(random.uniform(10.0, 200.0), 2)))

    return Transaction(
        **_base_account(),
        timestamp=now,
        amount=amount,
        transaction_type=TransactionType.PURCHASE,
        merchant_category=MerchantCategory.RETAIL,
        merchant_name=fake.company(),
        location=_make_geo(GEO_PARIS),
        device=KNOWN_DEVICE,
        account_age_days=random.randint(365, 3650),
        daily_transaction_count=random.randint(1, 4),
        daily_total_amount=daily_total,
        previous_transaction_timestamp=now - timedelta(hours=random.randint(2, 48)),
        previous_location=_make_geo(GEO_PARIS),
    )


def scenario_velocity_burst() -> Transaction:
    """
    Velocity burst — labeled ANOMALY (high severity).
    25+ transactions in under 2 hours, typical card-sharing or account takeover.
    """
    now = datetime.now(timezone.utc)
    amount = Decimal(str(round(random.uniform(10.0, 80.0), 2)))
    # 25 previous txs + current = 26 total in the day, most within last 2h
    daily_count = random.randint(25, 40)
    daily_total = amount * daily_count + Decimal("50.00")

    return Transaction(
        **_base_account(),
        timestamp=now,
        amount=amount,
        transaction_type=TransactionType.PURCHASE,
        merchant_category=MerchantCategory.RETAIL,
        merchant_name=fake.company(),
        location=_make_geo(GEO_PARIS),
        device=KNOWN_DEVICE,
        account_age_days=random.randint(365, 3650),
        daily_transaction_count=daily_count,
        daily_total_amount=daily_total,
        previous_transaction_timestamp=now - timedelta(minutes=random.randint(3, 8)),
        previous_location=_make_geo(GEO_PARIS),
    )


def scenario_geo_impossible() -> Transaction:
    """
    Geo-impossible travel — labeled ANOMALY (critical severity).
    Previous transaction in Tokyo 45 minutes ago, current in Paris.
    Paris–Tokyo is ~9,700 km; no commercial flight covers it in <45 min.
    """
    now = datetime.now(timezone.utc)
    amount = Decimal(str(round(random.uniform(200.0, 1500.0), 2)))
    daily_total = amount + Decimal("300.00")

    return Transaction(
        **_base_account(),
        timestamp=now,
        amount=amount,
        transaction_type=TransactionType.PURCHASE,
        merchant_category=MerchantCategory.TRAVEL,
        merchant_name=fake.company(),
        location=_make_geo(GEO_PARIS),
        device=KNOWN_DEVICE,
        account_age_days=random.randint(365, 3650),
        daily_transaction_count=2,
        daily_total_amount=daily_total,
        previous_transaction_timestamp=now - timedelta(minutes=45),
        previous_location=_make_geo(GEO_TOKYO),   # Physically impossible
    )


def scenario_dormant_account_spike() -> Transaction:
    """
    Dormant account spike — labeled ANOMALY (medium severity).
    Account inactive 90–365 days, suddenly transacts a high amount
    from an unknown device.
    """
    now = datetime.now(timezone.utc)
    amount = Decimal(str(round(random.uniform(2000.0, 9999.99), 2)))
    daily_total = amount  # First transaction of the day

    return Transaction(
        **_base_account(),
        timestamp=now,
        amount=amount,
        transaction_type=TransactionType.TRANSFER,
        merchant_category=MerchantCategory.UNKNOWN,
        merchant_name="WIRE TRANSFER",
        location=_make_geo(random.choice([GEO_MOSCOW, GEO_LAGOS, GEO_NEW_YORK])),
        device=UNKNOWN_DEVICE,
        daily_transaction_count=1,
        daily_total_amount=daily_total,
        previous_transaction_timestamp=now - timedelta(days=random.randint(90, 365)),
        previous_location=_make_geo(GEO_PARIS),
        account_age_days=random.randint(365, 3650),
    )


def scenario_card_testing() -> Transaction:
    """
    Card testing probe — labeled ANOMALY (high severity).
    Tiny amount (0.01–1.00 EUR) on a new unknown device.
    Criminals test stolen card numbers with micro-transactions before large fraud.
    """
    now = datetime.now(timezone.utc)
    amount = Decimal(str(round(random.uniform(0.01, 1.00), 2)))

    return Transaction(
        **_base_account(),
        timestamp=now,
        amount=amount,
        transaction_type=TransactionType.PURCHASE,
        merchant_category=MerchantCategory.UNKNOWN,
        merchant_name="ONLINE MERCHANT",
        location=_make_geo(random.choice([GEO_LONDON, GEO_NEW_YORK])),
        device=UNKNOWN_DEVICE,
        daily_transaction_count=random.randint(3, 8),
        daily_total_amount=Decimal(str(round(random.uniform(1.00, 10.00), 2))),
        account_age_days=random.randint(30, 365),
    )


def scenario_high_risk_category() -> Transaction:
    """
    High-risk category mismatch — labeled ANOMALY (medium severity).
    Account with retail/food history suddenly transacts in crypto/gambling.
    Large amount amplifies the signal.
    """
    now = datetime.now(timezone.utc)
    amount = Decimal(str(round(random.uniform(500.0, 5000.0), 2)))
    daily_total = amount + Decimal("50.00")

    return Transaction(
        **_base_account(),
        timestamp=now,
        amount=amount,
        transaction_type=TransactionType.PURCHASE,
        merchant_category=random.choice([MerchantCategory.CRYPTO, MerchantCategory.GAMBLING]),
        merchant_name=fake.company() + " CRYPTO",
        location=_make_geo(random.choice([GEO_LONDON, GEO_NEW_YORK, GEO_ZURICH])),
        device=UNKNOWN_DEVICE,
        daily_transaction_count=random.randint(1, 3),
        daily_total_amount=daily_total,
        account_age_days=random.randint(180, 1825),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

ScenarioName = Literal[
    "normal_purchase",
    "velocity_burst",
    "geo_impossible",
    "dormant_account_spike",
    "card_testing",
    "high_risk_category",
]

_SCENARIO_MAP: dict[ScenarioName, callable] = {
    "normal_purchase": scenario_normal_purchase,
    "velocity_burst": scenario_velocity_burst,
    "geo_impossible": scenario_geo_impossible,
    "dormant_account_spike": scenario_dormant_account_spike,
    "card_testing": scenario_card_testing,
    "high_risk_category": scenario_high_risk_category,
}

# Ground-truth labels for test assertions
SCENARIO_LABELS: dict[ScenarioName, dict] = {
    "normal_purchase":      {"is_anomaly": False, "severity": None},
    "velocity_burst":       {"is_anomaly": True,  "severity": "high"},
    "geo_impossible":       {"is_anomaly": True,  "severity": "critical"},
    "dormant_account_spike":{"is_anomaly": True,  "severity": "medium"},
    "card_testing":         {"is_anomaly": True,  "severity": "high"},
    "high_risk_category":   {"is_anomaly": True,  "severity": "medium"},
}


def generate_fraud_scenario(scenario: ScenarioName) -> Transaction:
    """
    Generate a single labeled transaction for a given fraud scenario.

    Usage:
        tx = generate_fraud_scenario("geo_impossible")
        label = SCENARIO_LABELS["geo_impossible"]  # {"is_anomaly": True, "severity": "critical"}
    """
    if scenario not in _SCENARIO_MAP:
        raise ValueError(f"Unknown scenario '{scenario}'. Valid: {list(_SCENARIO_MAP)}")
    return _SCENARIO_MAP[scenario]()


def generate_batch(scenario: ScenarioName, n: int = 10) -> list[Transaction]:
    """Generate n transactions for the same scenario (randomised each call)."""
    return [generate_fraud_scenario(scenario) for _ in range(n)]


def generate_mixed_dataset(
    n_per_scenario: int = 20,
) -> list[tuple[Transaction, dict]]:
    """
    Generate a balanced labeled dataset across all scenarios.
    Returns list of (transaction, label) tuples for evaluation runs.
    """
    dataset = []
    for scenario in _SCENARIO_MAP:
        for _ in range(n_per_scenario):
            tx = generate_fraud_scenario(scenario)
            dataset.append((tx, SCENARIO_LABELS[scenario]))
    random.shuffle(dataset)
    return dataset
