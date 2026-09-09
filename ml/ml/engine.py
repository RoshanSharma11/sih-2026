"""Orchestrator: process_aws_data(...) → runtime JSON."""

from __future__ import annotations

import pandas as pd

from .buddy_check import evaluate_tier3
from .catalog import build_buddy_graph, load_catalog
from .config import CONFIDENCE_K, FEATURES
from .lstm_inference import LSTMInference, _to_naive
from .physical_rules import evaluate_tier1
from .root_cause import (
    HealthTracker,
    affected_from_contributions,
    build_reason,
    infer_fault_type,
)

LABELS = (
    "CLEAN",
    "PHYSICAL_FAULT",
    "GENUINE_WEATHER_EVENT",
    "HARDWARE_ANOMALY",
    "UNCONFIRMED_ANOMALY",
)

SENSOR_HEALTH_LABELS = {
    "PHYSICAL_FAULT",
    "HARDWARE_ANOMALY",
    "UNCONFIRMED_ANOMALY",
}


class UnknownStationError(ValueError):
    pass


def _confidence(window_mse: float | None, threshold: float | None, suspicious: bool) -> float:
    if not suspicious:
        return 0.0
    if window_mse is None or threshold is None or threshold <= 0:
        return 1.0
    ratio = window_mse / threshold
    return float(max(0.0, min(1.0, (ratio - 1.0) / CONFIDENCE_K)))


def _as_dict(item) -> dict:
    if item is None:
        return {}
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if isinstance(item, dict):
        return item
    return dict(item)


def _rows_from_window(window) -> pd.DataFrame | None:
    if not window:
        return None
    rows = []
    for item in window:
        row = _as_dict(item)
        rows.append(
            {
                "timestamp": _to_naive(row["timestamp"]),
                "temp": row.get("temp"),
                "rhum": row.get("rhum"),
                "pres": row.get("pres"),
            }
        )
    return pd.DataFrame(rows)


def _normalize_buddies(raw) -> list[dict]:
    out = []
    for item in raw or []:
        buddy = _as_dict(item)
        buddy["station_id"] = str(buddy.get("station_id", ""))
        window = buddy.get("window") or []
        buddy["window"] = [_as_dict(row) for row in window]
        out.append(buddy)
    return out


class DetectionEngine:
    def __init__(self):
        catalog = load_catalog()
        self.buddy_graph, self.exported_ids, self.isolates = build_buddy_graph(catalog)
        self.lstm = LSTMInference()
        self.health = HealthTracker()

    def buddy_map(self) -> dict:
        return {
            "stations": sorted(self.exported_ids),
            "isolates": sorted(self.isolates),
            "buddies": self.buddy_graph,
            "model_loaded": self.lstm.loaded,
            "threshold": self.lstm.threshold,
        }

    def _reject_unknown(self, station_id: str) -> None:
        if self.lstm.loaded:
            if not self.lstm.has_scaler(station_id):
                raise UnknownStationError(
                    f"Unknown station_id {station_id}: no train scaler. "
                    "Refusing to borrow another station."
                )
            return
        if self.exported_ids and station_id not in self.exported_ids:
            raise UnknownStationError(
                f"Unknown station_id {station_id}: not in the exported catalog."
            )

    def process_aws_data(self, payload: dict) -> dict:
        payload = _as_dict(payload)
        station_id = str(payload["station_id"])
        timestamp = _to_naive(payload["timestamp"])
        temp = payload.get("temp")
        rhum = payload.get("rhum")
        pres = payload.get("pres")
        observed = {"temp": temp, "rhum": rhum, "pres": pres}

        self._reject_unknown(station_id)

        # Always keep fallback buffer in sync.
        self.lstm.buffer.update(station_id, timestamp, temp, rhum, pres)

        provided = _rows_from_window(payload.get("window"))
        if provided is None:
            provided = self.lstm.buffer.window_ending_at(station_id, timestamp)

        window_df, window_error = self.lstm.validate_hourly_window(
            provided, timestamp, temp, rhum, pres
        )

        prev_temp = prev_rhum = prev_pres = None
        if window_df is not None and len(window_df) >= 2:
            prev = window_df.iloc[-2]
            prev_temp, prev_rhum, prev_pres = prev["temp"], prev["rhum"], prev["pres"]

        tier1 = evaluate_tier1(temp, rhum, pres, prev_temp, prev_rhum, prev_pres)

        tier2 = {
            "ran": False,
            "window_mse": None,
            "threshold": self.lstm.threshold,
            "feature_contributions": {f: None for f in FEATURES},
        }
        predicted = {f: None for f in FEATURES}
        suspicious = False

        # LSTM still runs after a Tier 1 fail so predicted/reconstructed can be filled.
        if window_df is not None and self.lstm.loaded and self.lstm.has_scaler(station_id):
            inf = self.lstm.infer(station_id, window_df)
            tier2 = {
                "ran": True,
                "window_mse": inf["window_mse"],
                "threshold": inf["threshold"],
                "feature_contributions": inf["feature_contributions"],
            }
            predicted = inf["predicted"]
            suspicious = bool(inf["is_suspicious"])
        elif window_df is None:
            window_error = window_error or "INSUFFICIENT_WINDOW"
        elif not self.lstm.loaded:
            window_error = window_error or "INSUFFICIENT_WINDOW: model artifacts not loaded"

        affected = affected_from_contributions(tier2.get("feature_contributions"))
        isolate = station_id in self.isolates

        req_buddies = _normalize_buddies(payload.get("buddies"))
        dist_lookup = {
            b["station_id"]: b["distance_km"] for b in self.buddy_graph.get(station_id, [])
        }
        for buddy in req_buddies:
            if buddy.get("distance_km") is None:
                buddy["distance_km"] = dist_lookup.get(buddy["station_id"])

        run_tier3 = bool(tier1["passed"] and suspicious)
        if run_tier3:
            tier3 = evaluate_tier3(
                timestamp,
                observed,
                req_buddies,
                affected,
                isolate=isolate,
            )
        else:
            if not tier1["passed"]:
                skip = "tier1_failed"
            elif window_df is None or not tier2["ran"]:
                skip = "lstm_not_run"
            else:
                skip = "not_required"
            tier3 = {
                "performed": False,
                "buddy_ids": [],
                "idw_estimate": {f: None for f in FEATURES},
                "residual": {f: None for f in FEATURES},
                "neighbors_agree": None,
                "usable_count": 0,
                "reason_skip": skip,
            }

        if not tier1["passed"]:
            label = "PHYSICAL_FAULT"
            is_anomaly = True
        elif window_df is None or not tier2["ran"]:
            label = "UNCONFIRMED_ANOMALY"
            is_anomaly = True
        elif not suspicious:
            label = "CLEAN"
            is_anomaly = False
        elif not tier3["performed"]:
            label = "UNCONFIRMED_ANOMALY"
            is_anomaly = True
        elif tier3["neighbors_agree"]:
            label = "GENUINE_WEATHER_EVENT"
            is_anomaly = True
        else:
            label = "HARDWARE_ANOMALY"
            is_anomaly = True

        fault_type = infer_fault_type(
            communication=bool(tier1.get("communication")),
            tier1_violations=tier1.get("violations") or [],
            window_df=window_df,
            affected=affected,
            observed=observed,
            predicted=predicted if tier2["ran"] else None,
        )
        if not is_anomaly:
            fault_type = None

        confidence = _confidence(
            tier2.get("window_mse"),
            tier2.get("threshold"),
            suspicious,
        )
        if label == "PHYSICAL_FAULT":
            confidence = 1.0
        if label == "CLEAN":
            confidence = 0.0

        reason = build_reason(
            label=label,
            fault_type=fault_type,
            observed=observed,
            predicted=predicted if tier2["ran"] else None,
            affected=affected,
            tier1=tier1,
            tier2=tier2,
            tier3=tier3,
            window_error=window_error,
        )

        health = self.health.update(
            station_id, timestamp, label in SENSOR_HEALTH_LABELS
        )

        return {
            "station_id": station_id,
            "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
            "observed": observed,
            "predicted": predicted,
            "reconstructed": predicted,
            "is_anomaly": is_anomaly,
            "confidence": round(confidence, 4),
            "label": label,
            "fault_type": fault_type,
            "affected_variables": affected if is_anomaly else [],
            "reason": reason,
            "tier1": {
                "passed": tier1["passed"],
                "violations": tier1["violations"],
            },
            "tier2": tier2,
            "tier3": {
                "performed": tier3["performed"],
                "buddy_ids": tier3.get("buddy_ids") or [],
                "idw_estimate": tier3.get("idw_estimate"),
                "residual": tier3.get("residual"),
                "neighbors_agree": tier3.get("neighbors_agree"),
                "usable_count": tier3.get("usable_count", 0),
                "reason_skip": tier3.get("reason_skip"),
            },
            "health": health,
        }


_ENGINE: DetectionEngine | None = None


def get_engine() -> DetectionEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = DetectionEngine()
    return _ENGINE


def process_aws_data(payload: dict) -> dict:
    return get_engine().process_aws_data(payload)
