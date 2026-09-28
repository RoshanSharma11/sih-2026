"""V2 orchestrator: process_aws_data(...) → contract JSON."""

from __future__ import annotations

try:
    import torch as _torch  # noqa: F401
except ImportError:
    pass

import pandas as pd
import numpy as np

from .buddy_check import evaluate_tier3, neighbor_estimate
from .drift import detect_drift
from .catalog import build_buddy_graph, load_catalog
from .config import CONFIDENCE_K, FEATURES, STGNN_ON_INGEST, WINDOW_HOURS
from .lstm_inference import LSTMInference, _to_naive
from .overlay_inference import OverlayInference
from .physical_rules import channels_from_violations, evaluate_tier1, is_soft_t1
from .stgnn_inference import STGNNInference
from .timing import TimingService
from .root_cause import (
    HealthTracker,
    affected_from_contributions,
    build_reason,
    infer_fault_type,
)

SENSOR_HEALTH_LABELS = {"PHYSICAL_FAULT", "HARDWARE_ANOMALY", "UNCONFIRMED_ANOMALY"}
NO_OVERLAY_LABELS = {"CLEAN", "GENUINE_WEATHER_EVENT"}


class UnknownStationError(ValueError):
    pass


def _confidence(score: float | None, threshold: float | None, suspicious: bool) -> float:
    if not suspicious:
        return 0.0
    if score is None or threshold is None or threshold <= 0:
        return 1.0
    return float(max(0.0, min(1.0, (score / threshold - 1.0) / CONFIDENCE_K)))


def _as_dict(item) -> dict:
    if item is None:
        return {}
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if isinstance(item, dict):
        return item
    return dict(item)


def _rows_from_window(window):
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
        buddy["window"] = [_as_dict(row) for row in (buddy.get("window") or [])]
        out.append(buddy)
    return out


def _copy_obs(observed: dict) -> dict:
    return {f: observed.get(f) for f in FEATURES}


class DetectionEngine:
    def __init__(self, use_stgnn: bool | None = None, timing_async: bool = False):
        catalog = load_catalog()
        self.buddy_graph, self.exported_ids, self.isolates = build_buddy_graph(catalog)
        self.lstm = LSTMInference()
        self.stgnn = STGNNInference(scalers=self.lstm.scalers)
        self.overlay = OverlayInference(scalers=self.lstm.scalers)
        self.health = HealthTracker()
        self.use_stgnn = STGNN_ON_INGEST if use_stgnn is None else bool(use_stgnn)
        self.timing_async = bool(timing_async)
        self.timing = TimingService(self.lstm) if self.timing_async else None

    def buddy_map(self) -> dict:
        return {
            "stations": sorted(self.exported_ids),
            "isolates": sorted(self.isolates),
            "buddies": self.buddy_graph,
            "model_loaded": self.lstm.loaded,
            "stgnn_loaded": self.stgnn.loaded,
            "stgnn_on": self.use_stgnn,
            "overlay_loaded": self.overlay.loaded,
            "timing_async": self.timing_async,
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
            raise UnknownStationError(f"Unknown station_id {station_id}: not in the exported catalog.")

    def _stgnn_override(self, station_id: str, window_df, buddies: list[dict]) -> dict | None:
        if not self.use_stgnn or not self.stgnn.loaded or window_df is None or len(window_df) < WINDOW_HOURS:
            return None
        primary = window_df[FEATURES].to_numpy(dtype=np.float64)[-WINDOW_HOURS:]
        neighbor_phys, distances, nids = [], [], []
        for buddy in buddies:
            rows = buddy.get("window") or []
            if len(rows) < WINDOW_HOURS:
                continue
            mat = np.zeros((WINDOW_HOURS, 3), dtype=np.float64)
            for i, raw in enumerate(rows[-WINDOW_HOURS:]):
                row = _as_dict(raw)
                for j, feat in enumerate(FEATURES):
                    v = row.get(feat)
                    mat[i, j] = float(v) if v is not None and v == v else np.nan
            neighbor_phys.append(mat)
            distances.append(float(buddy.get("distance_km") or 1.0))
            nids.append(str(buddy.get("station_id", "")))
        return self.stgnn.infer(station_id, primary, neighbor_phys, distances, nids)

    def _overlay_or_fallback(self, station_id, window_df, predicted, observed, tier2, tier3):
        mix = tier3.get("mix") or {}
        if self.overlay.loaded and window_df is not None and len(window_df) >= WINDOW_HOURS:
            phys = window_df[FEATURES].to_numpy(dtype=np.float64)[-WINDOW_HOURS:]
            got = self.overlay.infer(station_id, phys, mix if mix.get("temp") is not None else None)
            if got is not None:
                return got["predicted"], got["imputed_interval"]
        if mix.get("temp") is not None:
            overlay = {f: mix.get(f) if mix.get(f) is not None else (predicted.get(f) if tier2["ran"] else observed.get(f)) for f in FEATURES}
            return overlay, None
        overlay = predicted if tier2["ran"] else _copy_obs(observed)
        return overlay, None

    def process_aws_data(self, payload: dict) -> dict:
        payload = _as_dict(payload)
        station_id = str(payload["station_id"])
        timestamp = _to_naive(payload["timestamp"])
        temp = payload.get("temp")
        rhum = payload.get("rhum")
        pres = payload.get("pres")
        observed = {"temp": temp, "rhum": rhum, "pres": pres}
        self._reject_unknown(station_id)
        self.lstm.buffer.update(station_id, timestamp, temp, rhum, pres)

        provided = _rows_from_window(payload.get("window"))
        if provided is None:
            provided = self.lstm.buffer.window_ending_at(station_id, timestamp)
        window_df, window_error = self.lstm.validate_hourly_window(provided, timestamp, temp, rhum, pres)

        prev_temp = prev_rhum = prev_pres = None
        if window_df is not None and len(window_df) >= 2:
            prev = window_df.iloc[-2]
            prev_temp, prev_rhum, prev_pres = prev["temp"], prev["rhum"], prev["pres"]

        tier1 = evaluate_tier1(temp, rhum, pres, prev_temp, prev_rhum, prev_pres, window_df=window_df)
        thermo = tier1.get("thermo") or {"dewpoint_c": None, "td_minus_t": None, "passed": True}

        tier2 = {
            "ran": False,
            "score": None,
            "window_mse": None,
            "threshold": self.lstm.threshold,
            "feature_contributions": {f: None for f in FEATURES},
        }
        predicted = {f: None for f in FEATURES}
        suspicious = False
        corroborated = False

        if window_df is not None and self.lstm.loaded and self.lstm.has_scaler(station_id):
            inf = self.lstm.infer(station_id, window_df)
            tier2 = {
                "ran": True,
                "score": inf["score"],
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
        req_buddies = _normalize_buddies(payload.get("buddies"))
        dist_lookup = {b["station_id"]: b["distance_km"] for b in self.buddy_graph.get(station_id, [])}
        for buddy in req_buddies:
            if buddy.get("distance_km") is None:
                buddy["distance_km"] = dist_lookup.get(buddy["station_id"])

        t1_channels = channels_from_violations(tier1.get("violations") or [])
        t3_affected = t1_channels or affected
        primary_window = payload.get("window") or []
        if (not primary_window) and window_df is not None:
            primary_window = window_df.to_dict("records")
        soft_t1 = bool(tier1.get("soft")) or is_soft_t1(tier1.get("violations") or [], bool(tier1.get("communication")))
        run_tier3 = bool((tier1["passed"] and suspicious) or (soft_t1 and not tier1.get("communication")))
        est = neighbor_estimate(timestamp, observed, req_buddies, primary_window)
        if run_tier3:
            tier3 = evaluate_tier3(
                timestamp,
                observed,
                req_buddies,
                t3_affected,
                isolate=False,
                primary_window=primary_window,
            )
            gat = self._stgnn_override(station_id, window_df, req_buddies)
            if gat is not None:
                tier3["neighbors_agree"] = gat["neighbors_agree"]
                tier3["method"] = "stgnn"
                tier3["p_agree"] = gat["p_agree"]
                if gat.get("mix"):
                    tier3["mix"] = gat["mix"]
        else:
            if not tier1["passed"]:
                skip = "tier1_failed"
            elif window_df is None or not tier2["ran"]:
                skip = "lstm_not_run"
            else:
                skip = "not_required"
            tier3 = {
                "performed": False,
                "method": "cw_idw",
                "buddy_ids": [u["station_id"] for u in est["usable"]],
                "mix": est["mix"],
                "idw_estimate": est["mix"],
                "residual": est["residual"],
                "corr": est["corr"],
                "neighbors_agree": None,
                "neighbor_shock": None,
                "blend_shift": {f: None for f in FEATURES},
                "blend_baseline_delta": {f: None for f in FEATURES},
                "usable_count": len(est["usable"]),
                "reason_skip": skip,
            }

        drift = detect_drift(timestamp, primary_window, req_buddies)
        tier3["drift"] = drift

        if tier1.get("communication") or (
            not tier1["passed"] and not soft_t1
        ):
            label = "PHYSICAL_FAULT"
            is_anomaly = True
        elif not tier1["passed"] and soft_t1:
            if tier3.get("performed") and tier3.get("neighbors_agree"):
                label = "GENUINE_WEATHER_EVENT"
                is_anomaly = True
            elif tier3.get("performed") and tier3.get("neighbors_agree") is False:
                label = "HARDWARE_ANOMALY"
                is_anomaly = True
            else:
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
            if tier3.get("neighbor_shock") is False:
                # Neighbours agree with the reading and did not move themselves: the LSTM
                # found the pattern unusual, but nothing happened. Corroborated clean hour.
                label = "CLEAN"
                is_anomaly = False
                corroborated = True
            else:
                label = "GENUINE_WEATHER_EVENT"
                is_anomaly = True
        else:
            label = "HARDWARE_ANOMALY"
            is_anomaly = True

        # Residual CUSUM vs neighbours. Does not override weather (the blend moved too)
        # or a hard physical fail. Catches a slow bias the LSTM reconstructs as climate.
        if drift.get("fired") and label in {"CLEAN", "UNCONFIRMED_ANOMALY"}:
            label = "HARDWARE_ANOMALY"
            is_anomaly = True
            corroborated = False
            if drift.get("channel"):
                affected = [str(drift["channel"])]

        fault_type = infer_fault_type(
            communication=bool(tier1.get("communication")),
            tier1_violations=tier1.get("violations") or [],
            window_df=window_df,
            affected=affected,
            observed=observed,
            predicted=predicted if tier2["ran"] else None,
            neighbors_agree=tier3.get("neighbors_agree"),
            drift_fired=bool(drift.get("fired")) and label == "HARDWARE_ANOMALY",
        )
        if not is_anomaly:
            fault_type = None

        confidence = _confidence(tier2.get("score"), tier2.get("threshold"), suspicious)
        if label == "PHYSICAL_FAULT":
            confidence = 1.0
        if label == "CLEAN":
            confidence = 0.0

        if label in NO_OVERLAY_LABELS:
            overlay = _copy_obs(observed)
            interval = None
        elif label in {"HARDWARE_ANOMALY", "PHYSICAL_FAULT"}:
            overlay, interval = self._overlay_or_fallback(station_id, window_df, predicted, observed, tier2, tier3)
        else:
            overlay = predicted if tier2["ran"] else {f: None for f in FEATURES}
            interval = None

        reason = build_reason(
            label=label,
            fault_type=fault_type,
            observed=observed,
            predicted=overlay,
            affected=affected,
            tier1=tier1,
            tier2=tier2,
            tier3=tier3,
            window_error=window_error,
            corroborated=corroborated,
        )
        health = self.health.update(station_id, timestamp, label in SENSOR_HEALTH_LABELS)

        climo = None
        if window_df is not None and "temp" in window_df.columns:
            climo = {"temp_p999_train": None, "last_vs_p999": None}

        if self.timing_async and is_anomaly and window_df is not None and self.timing is not None and self.timing.available:
            self.timing.enqueue(station_id, timestamp, window_df)

        return {
            "station_id": station_id,
            "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
            "observed": observed,
            "predicted": overlay,
            "reconstructed": overlay,
            "imputed_interval": interval,
            "is_anomaly": is_anomaly,
            "confidence": round(confidence, 4),
            "label": label,
            "fault_type": fault_type,
            "affected_variables": affected if is_anomaly else [],
            "reason": reason,
            "thermo": thermo,
            "tier1": {"passed": tier1["passed"], "violations": tier1["violations"]},
            "tier2": tier2,
            "tier3": {
                "performed": tier3["performed"],
                "method": tier3.get("method") or "cw_idw",
                "neighbors_agree": tier3.get("neighbors_agree"),
                "buddy_ids": tier3.get("buddy_ids") or [],
                "usable_count": tier3.get("usable_count", 0),
                "mix": tier3.get("mix"),
                "idw_estimate": tier3.get("idw_estimate") or tier3.get("mix"),
                "corr": tier3.get("corr") or {},
                "residual": tier3.get("residual"),
                "reason_skip": tier3.get("reason_skip"),
                "p_agree": tier3.get("p_agree"),
                "neighbor_shock": tier3.get("neighbor_shock"),
                "blend_shift": tier3.get("blend_shift"),
                "blend_baseline_delta": tier3.get("blend_baseline_delta"),
                "drift": tier3.get("drift"),
            },
            "climatology": climo,
            "timing": None,
            "health": health,
        }

    def get_timing(self, station_id: str, timestamp, wait_s: float = 0.0) -> dict:
        if self.timing is None:
            return {
                "station_id": str(station_id),
                "timestamp": _to_naive(timestamp).strftime("%Y-%m-%dT%H:%M:%S"),
                "status": "not_requested",
                "timing": None,
            }
        return self.timing.get(station_id, timestamp, wait_s=wait_s)


_ENGINE: DetectionEngine | None = None


def get_engine(*, use_stgnn: bool | None = None, timing_async: bool | None = None) -> DetectionEngine:
    global _ENGINE
    if _ENGINE is None:
        ta = True if timing_async is None else bool(timing_async)
        _ENGINE = DetectionEngine(use_stgnn=use_stgnn, timing_async=ta)
    return _ENGINE


def process_aws_data(payload: dict) -> dict:
    return get_engine().process_aws_data(payload)
