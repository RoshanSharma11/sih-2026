"""Root-cause classification. Weather from buddy check overrides a Tier 1 spike."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from skyguard.engine.tier1 import CHANNEL_LABEL, Tier1Result
from skyguard.engine.tier3 import BuddyResult
from skyguard.engine.windows import WindowPoint
from skyguard.schemas import Channel, FaultType, PipelineStatus, Severity

FREEZE_MIN = 6
CHANNEL_UNIT = {
    Channel.TEMP_C: "°C",
    Channel.PRES_HPA: " hPa",
    Channel.RHUM_PCT: "%",
}


@dataclass
class Classification:
    pipeline_status: PipelineStatus
    fault_type: FaultType | None = None
    confidence: float | None = None
    severity: Severity | None = None
    explainability_text: str | None = None
    fail_channel: Channel | None = None


def freeze_channel(points: list[WindowPoint]) -> Channel | None:
    if len(points) < FREEZE_MIN:
        return None
    recent = points[-FREEZE_MIN:]
    stuck: list[Channel] = []
    for channel in Channel:
        values = [getattr(point, channel.value) for point in recent]
        if any(value is None for value in values):
            continue
        if float(np.std(values)) < 1e-9:
            stuck.append(channel)
    if len(stuck) == 1:
        return stuck[0]
    return None


def _dominant_residual(buddy: BuddyResult) -> Channel | None:
    if not buddy.residual:
        return None
    return max(buddy.residual, key=lambda channel: abs(buddy.residual[channel]))


def classify(
    *,
    cluster_id: str,
    current: WindowPoint,
    points: list[WindowPoint],
    tier1: Tier1Result,
    buddy: BuddyResult,
    drift: bool,
) -> Classification:
    if tier1.comm_error:
        return Classification(
            PipelineStatus.HARDWARE,
            FaultType.COMM_ERROR,
            0.99,
            Severity.HIGH,
            "One or more channels were null (communication or sensor gap).",
        )

    frozen = freeze_channel(points)
    weather_like = buddy.storm_shaped or buddy.heat_shaped
    interesting = bool(tier1.failed or frozen or drift or weather_like or buddy.large)

    if buddy.neighbor_count >= 1 and buddy.contemporaneous and not buddy.large and weather_like:
        residual = buddy.spatial_residual or 0.0
        confidence = max(0.6, min(0.99, 1.0 - residual / 20.0))
        return Classification(
            PipelineStatus.GENUINE_WEATHER,
            FaultType.GENUINE_WEATHER,
            confidence,
            Severity.LOW,
            (
                f"Cluster {cluster_id} neighbors agree (IDW residual {residual:.1f}). "
                "Treated as genuine weather, not a sensor fault."
            ),
        )

    if interesting and buddy.neighbor_count == 0:
        return Classification(
            PipelineStatus.UNKNOWN,
            FaultType.UNKNOWN,
            0.4,
            Severity.LOW,
            "Not enough cluster neighbors within 1 hour to separate weather from a sensor fault.",
        )

    if interesting and weather_like and not buddy.contemporaneous:
        return Classification(
            PipelineStatus.UNKNOWN,
            FaultType.UNKNOWN,
            0.45,
            Severity.MEDIUM,
            "Storm-shaped change seen before same-hour neighbors arrived; buddy check abstained.",
        )

    if frozen is not None:
        label = CHANNEL_LABEL[frozen]
        return Classification(
            PipelineStatus.HARDWARE,
            FaultType.FREEZE,
            0.93,
            Severity.HIGH,
            f"{label} held a constant value for {FREEZE_MIN} hours (freeze).",
            fail_channel=frozen,
        )

    if drift:
        return Classification(
            PipelineStatus.HARDWARE,
            FaultType.DRIFT,
            0.75,
            Severity.MEDIUM,
            "Buddy residual grew steadily versus cluster neighbors (calibration drift).",
        )

    if buddy.one_channel_large() and not (tier1.range_fail or tier1.step_fail):
        channel = _dominant_residual(buddy)
        return Classification(
            PipelineStatus.HARDWARE,
            FaultType.PHYSICS_BREACH,
            0.9,
            Severity.HIGH,
            _spike_text(channel, current, buddy, "physics breach"),
            fail_channel=channel,
        )

    if tier1.range_fail or tier1.step_fail or buddy.large:
        channel = tier1.fail_channel or _dominant_residual(buddy)
        kind = "range" if tier1.range_fail else "step" if tier1.step_fail else "spatial"
        return Classification(
            PipelineStatus.HARDWARE,
            FaultType.SPIKE,
            0.95,
            Severity.HIGH,
            _spike_text(channel, current, buddy, kind),
            fail_channel=channel,
        )

    return Classification(PipelineStatus.CLEAN)


def _spike_text(channel: Channel | None, current: WindowPoint, buddy: BuddyResult, kind: str) -> str:
    if channel is None:
        return "A sensor failed a consistency check and was treated as a hardware spike."
    label = CHANNEL_LABEL[channel]
    observed = getattr(current, channel.value)
    expected = buddy.idw.get(channel) if buddy.idw else None
    if expected is not None and observed is not None:
        unit = CHANNEL_UNIT[channel]
        return (
            f"{label} contributed 100.0% of reconstruction error. "
            f"Expected {expected:.1f}{unit} given the other sensors, but received {observed:.1f}{unit}."
        )
    check = "range" if kind == "range" else "step" if kind == "step" else "buddy"
    return f"{label} failed the {check} check and was treated as a hardware spike."
