"""
Medtech vital signs schema — Pydantic v2 contracts.

Defines patient monitoring events. Validation encodes clinical boundary rules
(e.g. SpO2 cannot exceed 100%, heart rate floor is 20 bpm for adults).
These constraints mirror IEC 62304 traceability requirements: every rule
here has a corresponding test in tests/api/test_medtech_schema.py.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AlertLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VitalType(str, Enum):
    ROUTINE = "routine"
    POST_PROCEDURE = "post_procedure"
    ICU = "icu"
    EMERGENCY = "emergency"


class DeviceSensorInfo(BaseModel):
    device_id: str = Field(..., min_length=6)
    model: str = Field(..., min_length=2)
    firmware_version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    last_calibration_date: datetime
    battery_level_pct: int = Field(..., ge=0, le=100)


class VitalSigns(BaseModel):
    """
    Single patient vital signs reading.

    Clinical ranges used as validation boundaries:
    - SpO2: 70–100% (below 70 is incompatible with consciousness — sensor fault)
    - Heart rate: 20–250 bpm (physiological extremes for adults)
    - Systolic BP: 50–300 mmHg
    - Diastolic BP: 20–200 mmHg
    - Temperature: 30–45°C (survivable range)
    - Respiratory rate: 4–60 breaths/min
    - Glucose: 1.0–50.0 mmol/L
    """

    reading_id: UUID
    patient_id: str = Field(..., min_length=8, max_length=32)
    ward_id: str = Field(..., min_length=3, max_length=20)
    timestamp: datetime
    vital_type: VitalType
    device: DeviceSensorInfo

    # Core vitals — all optional to support partial readings from different sensors
    spo2_pct: Optional[float] = Field(None, ge=70.0, le=100.0)
    heart_rate_bpm: Optional[int] = Field(None, ge=20, le=250)
    systolic_bp_mmhg: Optional[int] = Field(None, ge=50, le=300)
    diastolic_bp_mmhg: Optional[int] = Field(None, ge=20, le=200)
    temperature_celsius: Optional[float] = Field(None, ge=30.0, le=45.0)
    respiratory_rate_bpm: Optional[int] = Field(None, ge=4, le=60)
    glucose_mmol_l: Optional[float] = Field(None, ge=1.0, le=50.0)

    # Context
    previous_spo2_pct: Optional[float] = Field(None, ge=70.0, le=100.0)
    previous_heart_rate_bpm: Optional[int] = Field(None, ge=20, le=250)
    minutes_since_last_reading: Optional[float] = Field(None, ge=0)
    current_medication: Optional[str] = None
    alert_level: AlertLevel = AlertLevel.NONE

    @model_validator(mode="after")
    def at_least_one_vital_required(self) -> "VitalSigns":
        vitals = [
            self.spo2_pct, self.heart_rate_bpm, self.systolic_bp_mmhg,
            self.diastolic_bp_mmhg, self.temperature_celsius,
            self.respiratory_rate_bpm, self.glucose_mmol_l,
        ]
        if all(v is None for v in vitals):
            raise ValueError("At least one vital sign measurement must be provided")
        return self

    @model_validator(mode="after")
    def bp_diastolic_below_systolic(self) -> "VitalSigns":
        if (
            self.systolic_bp_mmhg is not None
            and self.diastolic_bp_mmhg is not None
            and self.diastolic_bp_mmhg >= self.systolic_bp_mmhg
        ):
            raise ValueError(
                "Diastolic BP must be lower than systolic BP"
            )
        return self

    @model_validator(mode="after")
    def spo2_drop_rate_sanity(self) -> "VitalSigns":
        """Flag physiologically impossible SpO2 drops (sensor fault heuristic)."""
        if (
            self.spo2_pct is not None
            and self.previous_spo2_pct is not None
            and self.minutes_since_last_reading is not None
            and self.minutes_since_last_reading > 0
        ):
            drop = self.previous_spo2_pct - self.spo2_pct
            rate_per_min = drop / self.minutes_since_last_reading
            # >10% drop per minute is physiologically impossible — sensor error
            if rate_per_min > 10:
                raise ValueError(
                    f"SpO2 drop rate {rate_per_min:.1f}%/min exceeds physiological limit "
                    "(likely sensor fault)"
                )
        return self

    def to_classifier_context(self) -> dict:
        """Flat dict for LLM prompt injection — clinical signals only."""
        ctx: dict = {
            "vital_type": self.vital_type.value,
            "ward": self.ward_id,
            "battery_pct": self.device.battery_level_pct,
        }
        for field, key in [
            ("spo2_pct", "spo2"),
            ("heart_rate_bpm", "hr_bpm"),
            ("systolic_bp_mmhg", "sbp"),
            ("diastolic_bp_mmhg", "dbp"),
            ("temperature_celsius", "temp_c"),
            ("respiratory_rate_bpm", "rr_bpm"),
            ("glucose_mmol_l", "glucose"),
        ]:
            val = getattr(self, field)
            if val is not None:
                ctx[key] = val

        if self.previous_spo2_pct is not None:
            ctx["spo2_delta"] = round(self.spo2_pct - self.previous_spo2_pct, 1)
        if self.minutes_since_last_reading is not None:
            ctx["mins_since_last"] = self.minutes_since_last_reading
        if self.current_medication:
            ctx["medication"] = self.current_medication
        return ctx
