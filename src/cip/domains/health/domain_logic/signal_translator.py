"""Deterministic signal translation: raw health data -> Mantic layer inputs.

Each compute function takes raw health data dicts and returns:
    (signal_value: float, details: dict)

Signal values are always clamped to [0, 1].
All formulas are deterministic — no LLM, no randomness.
"""

from __future__ import annotations

from cip.domains.health.domain_logic.signal_models import (
    FALLBACK_GOOD_DEFAULT,
    FALLBACK_NO_DATA,
    FALLBACK_NO_LABS,
    FALLBACK_PARTIAL_DATA,
    HealthSignals,
)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, value))


def _num(val, default: float = 0.0) -> float:
    """Safely convert to float, returning default for None or non-numeric."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Signal 1: Vital Stability
# ---------------------------------------------------------------------------

def compute_vital_stability(vitals_data: dict) -> tuple[float, dict]:
    """Compute vital stability signal from heart rate, BP, HRV, SpO2.

    Sub-signals:
        HR stability (30%): Deviation from optimal resting HR (~65 bpm)
        BP stability (35%): Deviation from optimal BP (120/80)
        HRV quality (20%): Heart rate variability (higher = better)
        SpO2 quality (15%): Blood oxygen saturation

    Returns:
        (signal in [0,1], details dict)
    """
    if not vitals_data:
        return FALLBACK_NO_DATA, {"fallback": "no_vitals_data"}

    details: dict = {}

    # --- Heart rate stability (30%) ---
    rhr_data = vitals_data.get("resting_heart_rate", {})
    rhr = _num(rhr_data.get("current_bpm"), default=70)
    rhr_trend = _num(rhr_data.get("trend_30d"), default=0)
    hr_signal = _clamp(1.0 - abs(rhr - 65) / 25)
    # Improving trend (negative = HR decreasing = good): bonus
    if rhr_trend < 0:
        hr_signal = _clamp(hr_signal + 0.05)
    elif rhr_trend > 3:
        hr_signal = _clamp(hr_signal - 0.05)
    details["hr_signal"] = round(hr_signal, 4)
    details["resting_hr_bpm"] = rhr

    # --- Blood pressure stability (35%) ---
    bp_data = vitals_data.get("blood_pressure", {})
    systolic = _num(bp_data.get("systolic_avg"), default=120)
    diastolic = _num(bp_data.get("diastolic_avg"), default=80)
    bp_penalty = (max(0, systolic - 120) / 40 + max(0, diastolic - 80) / 20) / 2
    bp_signal = _clamp(1.0 - bp_penalty)
    details["bp_signal"] = round(bp_signal, 4)
    details["bp_systolic"] = systolic
    details["bp_diastolic"] = diastolic

    # --- HRV quality (20%) ---
    hrv_data = vitals_data.get("hrv", {})
    hrv_ms = _num(hrv_data.get("avg_ms"), default=30)
    hrv_signal = _clamp(hrv_ms / 60)
    details["hrv_signal"] = round(hrv_signal, 4)
    details["hrv_ms"] = hrv_ms

    # --- SpO2 quality (15%) ---
    spo2_data = vitals_data.get("spo2", {})
    avg_spo2 = _num(spo2_data.get("avg_pct"), default=97)
    spo2_signal = _clamp((avg_spo2 - 90) / 8)
    details["spo2_signal"] = round(spo2_signal, 4)
    details["spo2_avg"] = avg_spo2

    # --- Weighted blend ---
    signal = (
        0.30 * hr_signal
        + 0.35 * bp_signal
        + 0.20 * hrv_signal
        + 0.15 * spo2_signal
    )

    return _clamp(signal), details


# ---------------------------------------------------------------------------
# Signal 2: Metabolic Balance
# ---------------------------------------------------------------------------

def compute_metabolic_balance(
    lab_results: list[dict], biometrics: dict
) -> tuple[float, dict]:
    """Compute metabolic balance from lab results and biometrics.

    Sub-signals:
        Glucose health (30%): Fasting glucose and HbA1c
        Cholesterol health (35%): LDL/HDL ratio
        BMI trend (20%): BMI proximity to optimal + trend
        Triglycerides (15%): Triglyceride level

    Returns:
        (signal in [0,1], details dict)
    """
    if not lab_results and not biometrics:
        return FALLBACK_NO_LABS, {"fallback": "no_labs_or_biometrics"}

    details: dict = {}
    sub_signals: list[tuple[float, float]] = []  # (weight, value)

    # Build lab lookup (case-insensitive)
    lab_map: dict[str, dict] = {}
    for lab in (lab_results or []):
        name = lab.get("test_name", "").lower().strip()
        lab_map[name] = lab

    # --- Glucose health (30%) ---
    glucose_vals = []
    glucose_lab = lab_map.get("fasting glucose")
    if glucose_lab:
        g = _num(glucose_lab.get("value"))
        glucose_signal = _clamp(1.0 - max(0, g - 85) / 40)
        glucose_vals.append(glucose_signal)
        details["glucose_value"] = g
        details["glucose_signal"] = round(glucose_signal, 4)

    hba1c_lab = lab_map.get("hba1c")
    if hba1c_lab:
        h = _num(hba1c_lab.get("value"))
        hba1c_signal = _clamp(1.0 - max(0, h - 5.0) / 1.5)
        glucose_vals.append(hba1c_signal)
        details["hba1c_value"] = h
        details["hba1c_signal"] = round(hba1c_signal, 4)

    if glucose_vals:
        glucose_composite = sum(glucose_vals) / len(glucose_vals)
        sub_signals.append((0.30, glucose_composite))
        details["glucose_composite"] = round(glucose_composite, 4)
    else:
        sub_signals.append((0.30, FALLBACK_NO_LABS))

    # --- Cholesterol health (35%) ---
    ldl_lab = lab_map.get("ldl cholesterol")
    hdl_lab = lab_map.get("hdl cholesterol")

    if ldl_lab or hdl_lab:
        ldl_signal = 0.5  # neutral default
        hdl_signal = 0.5
        if ldl_lab:
            ldl = _num(ldl_lab.get("value"))
            ldl_signal = _clamp(1.0 - max(0, ldl - 70) / 100)
            details["ldl_value"] = ldl
            details["ldl_signal"] = round(ldl_signal, 4)
        if hdl_lab:
            hdl = _num(hdl_lab.get("value"))
            hdl_signal = _clamp((hdl - 30) / 40)
            details["hdl_value"] = hdl
            details["hdl_signal"] = round(hdl_signal, 4)
        chol_signal = 0.6 * ldl_signal + 0.4 * hdl_signal
        sub_signals.append((0.35, chol_signal))
        details["cholesterol_composite"] = round(chol_signal, 4)
    else:
        sub_signals.append((0.35, FALLBACK_NO_LABS))

    # --- BMI trend (20%) ---
    if biometrics:
        bmi = _num(biometrics.get("bmi"), default=0)
        bmi_trend = _num(biometrics.get("bmi_trend_90d"), default=0)
        if bmi > 0:
            bmi_signal = _clamp(1.0 - max(0, abs(bmi - 22) - 3) / 8)
            # Improving trend bonus
            if bmi_trend < 0:
                bmi_signal = _clamp(bmi_signal + 0.05)
            details["bmi_value"] = bmi
            details["bmi_signal"] = round(bmi_signal, 4)
            sub_signals.append((0.20, bmi_signal))
        else:
            sub_signals.append((0.20, FALLBACK_PARTIAL_DATA))
    else:
        sub_signals.append((0.20, FALLBACK_PARTIAL_DATA))

    # --- Triglycerides (15%) ---
    trig_lab = lab_map.get("triglycerides")
    if trig_lab:
        trig = _num(trig_lab.get("value"))
        trig_signal = _clamp(1.0 - max(0, trig - 100) / 100)
        sub_signals.append((0.15, trig_signal))
        details["triglycerides_value"] = trig
        details["triglycerides_signal"] = round(trig_signal, 4)
    else:
        sub_signals.append((0.15, FALLBACK_NO_LABS))

    # --- Weighted blend ---
    total_weight = sum(w for w, _ in sub_signals)
    signal = sum(w * v for w, v in sub_signals) / total_weight if total_weight > 0 else FALLBACK_NO_LABS

    return _clamp(signal), details


# ---------------------------------------------------------------------------
# Signal 3: Activity & Recovery
# ---------------------------------------------------------------------------

def compute_activity_recovery(activity_data: dict) -> tuple[float, dict]:
    """Compute activity/recovery signal from exercise, sleep, recovery data.

    Sub-signals:
        Exercise consistency (35%): Frequency + consistency
        Sleep quality (35%): Duration adequacy + quality score
        Recovery balance (30%): Recovery score + strain balance

    Returns:
        (signal in [0,1], details dict)
    """
    if not activity_data:
        return FALLBACK_NO_DATA, {"fallback": "no_activity_data"}

    details: dict = {}

    # --- Exercise consistency (35%) ---
    exercise = activity_data.get("exercise", {})
    sessions = _num(exercise.get("sessions_per_week"), default=0)
    consistency = _num(exercise.get("consistency_pct"), default=50)
    freq_signal = _clamp(sessions / 4)  # 4+ sessions/week = 1.0
    consistency_signal = consistency / 100
    exercise_signal = 0.6 * freq_signal + 0.4 * consistency_signal
    details["exercise_signal"] = round(exercise_signal, 4)
    details["sessions_per_week"] = sessions

    # --- Sleep quality (35%) ---
    sleep = activity_data.get("sleep", {})
    duration = _num(sleep.get("avg_duration_hours"), default=7)
    quality = _num(sleep.get("avg_quality_score"), default=50)
    duration_signal = _clamp(1.0 - abs(duration - 8.0) / 3)  # 8h optimal
    quality_signal = quality / 100
    sleep_signal = 0.5 * duration_signal + 0.5 * quality_signal
    details["sleep_signal"] = round(sleep_signal, 4)
    details["sleep_duration_hours"] = duration
    details["sleep_quality_score"] = quality

    # --- Recovery balance (30%) ---
    recovery = activity_data.get("recovery", {})
    recovery_score = _num(recovery.get("avg_recovery_score"), default=50)
    strain = recovery.get("strain_balance", "balanced")
    recovery_signal = recovery_score / 100
    if strain == "high":
        recovery_signal = _clamp(recovery_signal - 0.1)
    details["recovery_signal"] = round(recovery_signal, 4)
    details["strain_balance"] = strain

    # --- Weighted blend ---
    signal = (
        0.35 * exercise_signal
        + 0.35 * sleep_signal
        + 0.30 * recovery_signal
    )

    return _clamp(signal), details


# ---------------------------------------------------------------------------
# Signal 4: Preventive Readiness
# ---------------------------------------------------------------------------

def compute_preventive_readiness(preventive_care: dict) -> tuple[float, dict]:
    """Compute preventive readiness from screening, vaccination, medication data.

    Sub-signals:
        Screening currency (40%): Fraction of screenings that are current
        Vaccination currency (30%): Fraction of vaccinations that are current
        Medication adherence (30%): Adherence percentage (or good default if no Rx)

    Returns:
        (signal in [0,1], details dict)
    """
    if not preventive_care:
        return FALLBACK_PARTIAL_DATA, {"fallback": "no_preventive_data"}

    details: dict = {}

    # --- Screening currency (40%) ---
    screenings = preventive_care.get("screenings", {})
    if screenings:
        total = len(screenings)
        current = sum(
            1 for s in screenings.values()
            if isinstance(s, dict) and s.get("status") == "current"
        )
        screening_signal = current / total if total > 0 else FALLBACK_PARTIAL_DATA
        details["screenings_current"] = current
        details["screenings_total"] = total
        details["screening_signal"] = round(screening_signal, 4)
    else:
        screening_signal = FALLBACK_PARTIAL_DATA

    # --- Vaccination currency (30%) ---
    vaccinations = preventive_care.get("vaccinations", {})
    if vaccinations:
        total_vaxx = len(vaccinations)
        current_vaxx = sum(
            1 for v in vaccinations.values()
            if isinstance(v, dict) and v.get("status") == "current"
        )
        vaxx_signal = current_vaxx / total_vaxx if total_vaxx > 0 else FALLBACK_PARTIAL_DATA
        details["vaccinations_current"] = current_vaxx
        details["vaccinations_total"] = total_vaxx
        details["vaccination_signal"] = round(vaxx_signal, 4)
    else:
        vaxx_signal = FALLBACK_PARTIAL_DATA

    # --- Medication adherence (30%) ---
    medications = preventive_care.get("medications", {})
    active_rx = _num(medications.get("active_prescriptions"), default=0)
    if active_rx > 0:
        adherence = _num(medications.get("adherence_pct"), default=50)
        med_signal = adherence / 100
        details["medication_adherence_pct"] = adherence
    else:
        med_signal = FALLBACK_GOOD_DEFAULT
        details["medication_note"] = "no_active_prescriptions"
    details["medication_signal"] = round(med_signal, 4)

    # --- Weighted blend ---
    signal = (
        0.40 * screening_signal
        + 0.30 * vaxx_signal
        + 0.30 * med_signal
    )

    return _clamp(signal), details


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def translate_health_to_mantic(
    vitals_data: dict,
    lab_results: list[dict],
    activity_data: dict,
    preventive_care: dict,
    biometrics: dict,
) -> HealthSignals:
    """Translate raw health data into Mantic layer signals.

    This is the main entry point for signal translation. It calls all four
    compute functions and returns a typed HealthSignals object.

    All computation is deterministic — no LLM, no randomness.
    """
    vital, vital_details = compute_vital_stability(vitals_data)
    metabolic, metabolic_details = compute_metabolic_balance(lab_results, biometrics)
    activity, activity_details = compute_activity_recovery(activity_data)
    preventive, preventive_details = compute_preventive_readiness(preventive_care)

    return HealthSignals(
        vital_stability=vital,
        metabolic_balance=metabolic,
        activity_recovery=activity,
        preventive_readiness=preventive,
        details={
            "vital_stability": vital_details,
            "metabolic_balance": metabolic_details,
            "activity_recovery": activity_details,
            "preventive_readiness": preventive_details,
        },
    )
