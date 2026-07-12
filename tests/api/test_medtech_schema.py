"""
Medtech schema contract tests.

Each test documents a clinical validation rule that maps to a real
IEC 62304 requirement (referenced in comments). This traceability pattern
is what differentiates senior QA practice from junior practice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.schemas.vital_signs import AlertLevel, DeviceSensorInfo, VitalSigns, VitalType
from src.simulators.medtech.generator import (
    SCENARIO_LABELS, generate_batch,
    generate_mixed_dataset, generate_vital_scenario,
)


@pytest.fixture()
def calibrated_device() -> DeviceSensorInfo:
    return DeviceSensorInfo(
        device_id="MED-TEST001",
        model="Test Monitor v2",
        firmware_version="2.1.0",
        last_calibration_date=datetime.now(timezone.utc) - timedelta(days=7),
        battery_level_pct=95,
    )


@pytest.fixture()
def valid_vitals_payload(calibrated_device) -> dict:
    return {
        "reading_id": uuid.uuid4(),
        "patient_id": "PAT-12345678",
        "ward_id": "WARD-4A",
        "timestamp": datetime.now(timezone.utc),
        "vital_type": VitalType.ROUTINE,
        "device": calibrated_device,
        "spo2_pct": 97.5,
        "heart_rate_bpm": 72,
        "systolic_bp_mmhg": 120,
        "diastolic_bp_mmhg": 80,
        "temperature_celsius": 36.8,
        "alert_level": AlertLevel.NONE,
    }


# ---------------------------------------------------------------------------
# SpO2 validation — IEC 62304 ref: SR-VITALS-001
# ---------------------------------------------------------------------------

class TestSpO2Validation:
    def test_spo2_above_100_rejected(self, valid_vitals_payload):
        """SpO2 > 100% is physically impossible — sensor error."""
        payload = {**valid_vitals_payload, "spo2_pct": 101.0}
        with pytest.raises(ValidationError):
            VitalSigns(**payload)

    def test_spo2_below_70_rejected(self, valid_vitals_payload):
        """SpO2 < 70% is incompatible with consciousness — sensor fault, not clinical."""
        payload = {**valid_vitals_payload, "spo2_pct": 69.0}
        with pytest.raises(ValidationError):
            VitalSigns(**payload)

    def test_spo2_boundary_70_accepted(self, valid_vitals_payload):
        payload = {**valid_vitals_payload, "spo2_pct": 70.0}
        vs = VitalSigns(**payload)
        assert vs.spo2_pct == 70.0

    def test_spo2_drop_rate_exceeding_10pct_per_min_rejected(
        self, valid_vitals_payload, calibrated_device
    ):
        """
        A drop of >10% SpO2 per minute is physiologically impossible.
        Rule SR-VITALS-003: flag as sensor fault, not clinical event.
        """
        payload = {
            **valid_vitals_payload,
            "spo2_pct": 80.0,
            "previous_spo2_pct": 99.0,   # 19% drop
            "minutes_since_last_reading": 1.0,  # In 1 minute = 19%/min > 10% limit
        }
        with pytest.raises(ValidationError) as exc_info:
            VitalSigns(**payload)
        assert "physiological limit" in str(exc_info.value)

    def test_spo2_drop_within_acceptable_rate_accepted(self, valid_vitals_payload):
        """5% drop over 10 minutes = 0.5%/min — within acceptable range."""
        payload = {
            **valid_vitals_payload,
            "spo2_pct": 92.0,
            "previous_spo2_pct": 97.0,
            "minutes_since_last_reading": 10.0,
        }
        vs = VitalSigns(**payload)
        assert vs.spo2_pct == 92.0


# ---------------------------------------------------------------------------
# Blood pressure validation — IEC 62304 ref: SR-VITALS-002
# ---------------------------------------------------------------------------

class TestBloodPressureValidation:
    def test_diastolic_above_systolic_rejected(self, valid_vitals_payload):
        """Diastolic BP can never exceed systolic BP — physically impossible."""
        payload = {
            **valid_vitals_payload,
            "systolic_bp_mmhg": 110,
            "diastolic_bp_mmhg": 120,  # Higher than systolic — invalid
        }
        with pytest.raises(ValidationError) as exc_info:
            VitalSigns(**payload)
        assert "Diastolic BP must be lower" in str(exc_info.value)

    def test_diastolic_equal_to_systolic_rejected(self, valid_vitals_payload):
        payload = {
            **valid_vitals_payload,
            "systolic_bp_mmhg": 100,
            "diastolic_bp_mmhg": 100,
        }
        with pytest.raises(ValidationError):
            VitalSigns(**payload)

    def test_systolic_above_max_rejected(self, valid_vitals_payload):
        payload = {**valid_vitals_payload, "systolic_bp_mmhg": 301}
        with pytest.raises(ValidationError):
            VitalSigns(**payload)


# ---------------------------------------------------------------------------
# Mandatory at-least-one-vital rule
# ---------------------------------------------------------------------------

class TestAtLeastOneVitalRequired:
    def test_no_vitals_provided_rejected(self, valid_vitals_payload):
        """A reading with no vital measurements is meaningless — reject."""
        payload = {
            **valid_vitals_payload,
            "spo2_pct": None,
            "heart_rate_bpm": None,
            "systolic_bp_mmhg": None,
            "diastolic_bp_mmhg": None,
            "temperature_celsius": None,
            "respiratory_rate_bpm": None,
            "glucose_mmol_l": None,
        }
        with pytest.raises(ValidationError) as exc_info:
            VitalSigns(**payload)
        assert "at least one vital" in str(exc_info.value).lower()

    def test_glucose_only_reading_accepted(self, valid_vitals_payload, calibrated_device):
        """Glucose-only readings are valid (point-of-care glucometer scenario)."""
        payload = {
            "reading_id": uuid.uuid4(),
            "patient_id": "PAT-12345678",
            "ward_id": "WARD-4A",
            "timestamp": datetime.now(timezone.utc),
            "vital_type": VitalType.ROUTINE,
            "device": calibrated_device,
            "glucose_mmol_l": 5.5,
        }
        vs = VitalSigns(**payload)
        assert vs.glucose_mmol_l == 5.5


# ---------------------------------------------------------------------------
# Classifier context serialisation
# ---------------------------------------------------------------------------

class TestVitalClassifierContext:
    def test_context_excludes_patient_pii(self, valid_vitals_payload):
        vs = VitalSigns(**valid_vitals_payload)
        ctx = vs.to_classifier_context()
        assert "patient_id" not in ctx
        assert "reading_id" not in ctx

    def test_spo2_delta_computed_when_previous_set(self, valid_vitals_payload):
        payload = {
            **valid_vitals_payload,
            "spo2_pct": 92.0,
            "previous_spo2_pct": 97.0,
            "minutes_since_last_reading": 5.0,
        }
        vs = VitalSigns(**payload)
        ctx = vs.to_classifier_context()
        assert "spo2_delta" in ctx
        assert ctx["spo2_delta"] == pytest.approx(-5.0, abs=0.1)

    def test_none_vitals_excluded_from_context(self, valid_vitals_payload):
        vs = VitalSigns(**valid_vitals_payload)
        ctx = vs.to_classifier_context()
        # glucose is None in the base fixture — must not appear in context
        assert "glucose" not in ctx


# ---------------------------------------------------------------------------
# Generator integration
# ---------------------------------------------------------------------------

class TestMedtechGenerator:
    @pytest.mark.parametrize("scenario", [
        "stable_routine", "spo2_desaturation", "hypertensive_crisis",
        "bradycardia_event", "hypoglycaemia_alert", "sensor_drift",
    ])
    def test_scenario_produces_valid_vital_signs(self, scenario):
        vs = generate_vital_scenario(scenario)
        assert isinstance(vs, VitalSigns)

    def test_spo2_desaturation_below_clinical_threshold(self):
        for _ in range(10):
            vs = generate_vital_scenario("spo2_desaturation")
            assert vs.spo2_pct < 90.0, "SpO2 must be below clinical threshold (90%)"

    def test_hypertensive_crisis_systolic_above_180(self):
        for _ in range(10):
            vs = generate_vital_scenario("hypertensive_crisis")
            assert vs.systolic_bp_mmhg >= 180

    def test_bradycardia_heart_rate_below_40(self):
        for _ in range(10):
            vs = generate_vital_scenario("bradycardia_event")
            assert vs.heart_rate_bpm < 40

    def test_hypoglycaemia_glucose_below_threshold(self):
        for _ in range(10):
            vs = generate_vital_scenario("hypoglycaemia_alert")
            assert vs.glucose_mmol_l < 3.5

    def test_sensor_drift_uses_degraded_device(self):
        for _ in range(5):
            vs = generate_vital_scenario("sensor_drift")
            assert vs.device.battery_level_pct <= 20

    def test_batch_generation(self):
        batch = generate_batch("stable_routine", n=10)
        assert len(batch) == 10

    def test_mixed_dataset_balanced(self):
        dataset = generate_mixed_dataset(n_per_scenario=4)
        assert len(dataset) == 6 * 4

    def test_scenario_labels_ground_truth(self):
        assert SCENARIO_LABELS["stable_routine"]["is_anomaly"] is False
        assert SCENARIO_LABELS["spo2_desaturation"]["severity"] == "critical"
