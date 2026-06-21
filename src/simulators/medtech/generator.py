"""
Medtech patient vital signs generator.

Produces labeled vital sign events for testing the AI anomaly classifier
in a clinical monitoring context. Each scenario maps to a known clinical
pattern — from stable post-op readings to critical deterioration events.

Clinical patterns implemented:
  1. stable_routine        — healthy vitals, post-surgery ward (CLEAN)
  2. spo2_desaturation     — SpO2 dropping toward hypoxia threshold (ANOMALY)
  3. hypertensive_crisis   — BP spike, risk of stroke (ANOMALY)
  4. bradycardia_event     — dangerously low heart rate (ANOMALY)
  5. hypoglycaemia_alert   — glucose crash, risk of unconsciousness (ANOMALY)
  6. sensor_drift          — plausible-but-wrong readings from degraded sensor (ANOMALY)
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from faker import Faker

from src.schemas.vital_signs import AlertLevel, DeviceSensorInfo, VitalSigns, VitalType

fake = Faker()

CALIBRATED_DEVICE = DeviceSensorInfo(
    device_id="MED-" + "A1B2C300",
    model="Philips IntelliVue MX800",
    firmware_version="3.2.1",
    last_calibration_date=datetime.now(timezone.utc) - timedelta(days=14),
    battery_level_pct=random.randint(70, 100),
)

DEGRADED_DEVICE = DeviceSensorInfo(
    device_id="MED-" + "X9Y8Z700",
    model="Generic SpO2 Monitor v1",
    firmware_version="1.0.0",
    last_calibration_date=datetime.now(timezone.utc) - timedelta(days=400),  # Overdue
    battery_level_pct=random.randint(5, 20),
)


def _ward() -> str:
    return random.choice(["WARD-4A", "WARD-ICU", "WARD-7B", "WARD-POST-OP"])


def _patient_id() -> str:
    return f"PAT-{fake.numerify('########')}"


# ---------------------------------------------------------------------------
# Scenario factories
# ---------------------------------------------------------------------------

def scenario_stable_routine() -> VitalSigns:
    """
    Stable post-op patient — labeled CLEAN.
    All vitals within normal reference ranges.
    """
    now = datetime.now(timezone.utc)
    return VitalSigns(
        reading_id=uuid.uuid4(),
        patient_id=_patient_id(),
        ward_id="WARD-POST-OP",
        timestamp=now,
        vital_type=VitalType.POST_PROCEDURE,
        device=CALIBRATED_DEVICE,
        spo2_pct=round(random.uniform(96.0, 99.5), 1),
        heart_rate_bpm=random.randint(60, 90),
        systolic_bp_mmhg=random.randint(110, 130),
        diastolic_bp_mmhg=random.randint(70, 85),
        temperature_celsius=round(random.uniform(36.4, 37.2), 1),
        respiratory_rate_bpm=random.randint(12, 18),
        minutes_since_last_reading=random.uniform(15, 30),
        previous_spo2_pct=round(random.uniform(96.0, 99.5), 1),
        alert_level=AlertLevel.NONE,
    )


def scenario_spo2_desaturation() -> VitalSigns:
    """
    SpO2 desaturation — labeled ANOMALY (critical).
    SpO2 dropping toward 85%, 5+ point fall from last reading.
    Clinical threshold for intervention: <90%.
    """
    now = datetime.now(timezone.utc)
    current_spo2 = round(random.uniform(82.0, 89.0), 1)
    previous_spo2 = round(current_spo2 + random.uniform(5.0, 9.0), 1)
    return VitalSigns(
        reading_id=uuid.uuid4(),
        patient_id=_patient_id(),
        ward_id=_ward(),
        timestamp=now,
        vital_type=VitalType.ICU,
        device=CALIBRATED_DEVICE,
        spo2_pct=current_spo2,
        heart_rate_bpm=random.randint(100, 130),  # Compensatory tachycardia
        respiratory_rate_bpm=random.randint(22, 35),  # Increased work of breathing
        temperature_celsius=round(random.uniform(37.5, 38.5), 1),
        minutes_since_last_reading=random.uniform(5, 15),
        previous_spo2_pct=min(previous_spo2, 99.5),  # Clamp to valid range
        alert_level=AlertLevel.CRITICAL,
    )


def scenario_hypertensive_crisis() -> VitalSigns:
    """
    Hypertensive crisis — labeled ANOMALY (high severity).
    Systolic BP >= 180 mmHg. Risk of haemorrhagic stroke.
    """
    now = datetime.now(timezone.utc)
    systolic = random.randint(180, 240)
    diastolic = random.randint(110, min(systolic - 30, 200))  # Clamp to schema max of 200
    return VitalSigns(
        reading_id=uuid.uuid4(),
        patient_id=_patient_id(),
        ward_id=_ward(),
        timestamp=now,
        vital_type=VitalType.ROUTINE,
        device=CALIBRATED_DEVICE,
        spo2_pct=round(random.uniform(93.0, 97.0), 1),
        heart_rate_bpm=random.randint(85, 110),
        systolic_bp_mmhg=systolic,
        diastolic_bp_mmhg=diastolic,
        temperature_celsius=round(random.uniform(36.8, 37.5), 1),
        minutes_since_last_reading=random.uniform(10, 60),
        alert_level=AlertLevel.HIGH,
    )


def scenario_bradycardia_event() -> VitalSigns:
    """
    Bradycardia event — labeled ANOMALY (high severity).
    Heart rate < 40 bpm with associated hypotension.
    """
    now = datetime.now(timezone.utc)
    return VitalSigns(
        reading_id=uuid.uuid4(),
        patient_id=_patient_id(),
        ward_id=_ward(),
        timestamp=now,
        vital_type=VitalType.ICU,
        device=CALIBRATED_DEVICE,
        spo2_pct=round(random.uniform(91.0, 95.0), 1),  # Above spo2 threshold so bradycardia rule fires
        heart_rate_bpm=random.randint(20, 39),  # Clinical bradycardia < 40
        systolic_bp_mmhg=random.randint(70, 90),  # Associated hypotension
        diastolic_bp_mmhg=random.randint(40, min(60, 89 - 10)),  # Must stay < systolic
        temperature_celsius=round(random.uniform(35.0, 36.5), 1),  # Slight hypothermia
        respiratory_rate_bpm=random.randint(6, 10),
        minutes_since_last_reading=random.uniform(5, 20),
        alert_level=AlertLevel.HIGH,
    )


def scenario_hypoglycaemia_alert() -> VitalSigns:
    """
    Hypoglycaemia — labeled ANOMALY (medium to high severity).
    Glucose < 3.5 mmol/L. Risk of unconsciousness and seizure.
    """
    now = datetime.now(timezone.utc)
    return VitalSigns(
        reading_id=uuid.uuid4(),
        patient_id=_patient_id(),
        ward_id=_ward(),
        timestamp=now,
        vital_type=VitalType.ROUTINE,
        device=CALIBRATED_DEVICE,
        heart_rate_bpm=random.randint(90, 120),  # Sympathetic response to low glucose
        temperature_celsius=round(random.uniform(36.0, 37.0), 1),
        glucose_mmol_l=round(random.uniform(1.5, 3.4), 1),
        spo2_pct=round(random.uniform(94.0, 98.0), 1),
        minutes_since_last_reading=random.uniform(30, 120),
        current_medication="Insulin glargine 20U nocte",
        alert_level=AlertLevel.MEDIUM,
    )


def scenario_sensor_drift() -> VitalSigns:
    """
    Sensor drift / fault — labeled ANOMALY (medium severity).
    Readings show an implausible oscillation pattern: SpO2 alternates
    between 99% and 91% every reading on a degraded, low-battery device.
    The patient context (low-acuity ward) makes physiological cause unlikely.
    """
    now = datetime.now(timezone.utc)
    # Simulate alternating readings typical of a dirty sensor probe
    spo2_values = [91.0, 99.0]
    current_spo2 = random.choice(spo2_values)
    previous_spo2 = [v for v in spo2_values if v != current_spo2][0]

    return VitalSigns(
        reading_id=uuid.uuid4(),
        patient_id=_patient_id(),
        ward_id="WARD-4A",   # Low-acuity ward — spike is unexpected
        timestamp=now,
        vital_type=VitalType.ROUTINE,
        device=DEGRADED_DEVICE,   # Low battery, uncalibrated
        spo2_pct=current_spo2,
        heart_rate_bpm=random.randint(65, 80),  # HR normal — contradicts SpO2 alarm
        temperature_celsius=round(random.uniform(36.5, 37.0), 1),
        minutes_since_last_reading=random.uniform(3, 6),
        previous_spo2_pct=previous_spo2,
        alert_level=AlertLevel.MEDIUM,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

MedScenarioName = Literal[
    "stable_routine",
    "spo2_desaturation",
    "hypertensive_crisis",
    "bradycardia_event",
    "hypoglycaemia_alert",
    "sensor_drift",
]

_SCENARIO_MAP: dict[MedScenarioName, callable] = {
    "stable_routine":        scenario_stable_routine,
    "spo2_desaturation":     scenario_spo2_desaturation,
    "hypertensive_crisis":   scenario_hypertensive_crisis,
    "bradycardia_event":     scenario_bradycardia_event,
    "hypoglycaemia_alert":   scenario_hypoglycaemia_alert,
    "sensor_drift":          scenario_sensor_drift,
}

SCENARIO_LABELS: dict[MedScenarioName, dict] = {
    "stable_routine":        {"is_anomaly": False, "severity": None},
    "spo2_desaturation":     {"is_anomaly": True,  "severity": "critical"},
    "hypertensive_crisis":   {"is_anomaly": True,  "severity": "high"},
    "bradycardia_event":     {"is_anomaly": True,  "severity": "high"},
    "hypoglycaemia_alert":   {"is_anomaly": True,  "severity": "medium"},
    "sensor_drift":          {"is_anomaly": True,  "severity": "medium"},
}


def generate_vital_scenario(scenario: MedScenarioName) -> VitalSigns:
    if scenario not in _SCENARIO_MAP:
        raise ValueError(f"Unknown scenario '{scenario}'. Valid: {list(_SCENARIO_MAP)}")
    return _SCENARIO_MAP[scenario]()


def generate_batch(scenario: MedScenarioName, n: int = 10) -> list[VitalSigns]:
    return [generate_vital_scenario(scenario) for _ in range(n)]


def generate_mixed_dataset(
    n_per_scenario: int = 20,
) -> list[tuple[VitalSigns, dict]]:
    dataset = []
    for scenario in _SCENARIO_MAP:
        for _ in range(n_per_scenario):
            v = generate_vital_scenario(scenario)
            dataset.append((v, SCENARIO_LABELS[scenario]))
    import random as _r
    _r.shuffle(dataset)
    return dataset
