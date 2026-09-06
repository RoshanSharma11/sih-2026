"""Hard range, step, and null checks."""

from __future__ import annotations

from dataclasses import dataclass, field

from skyguard.engine.windows import WindowPoint
from skyguard.schemas import Channel

RANGE = {
    Channel.TEMP_C: (-20.0, 55.0),
    Channel.PRES_HPA: (850.0, 1050.0),
    Channel.RHUM_PCT: (0.0, 100.0),
}
STEP = {
    Channel.TEMP_C: 10.0,
    Channel.PRES_HPA: 15.0,
    Channel.RHUM_PCT: 50.0,
}
CHANNEL_LABEL = {
    Channel.TEMP_C: "Temperature",
    Channel.PRES_HPA: "Pressure",
    Channel.RHUM_PCT: "Humidity",
}


@dataclass
class Tier1Result:
    comm_error: bool = False
    range_fail: list[Channel] = field(default_factory=list)
    step_fail: list[Channel] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.comm_error or bool(self.range_fail or self.step_fail)

    @property
    def fail_channel(self) -> Channel | None:
        if self.range_fail:
            return self.range_fail[0]
        if self.step_fail:
            return self.step_fail[0]
        return None


def evaluate(current: WindowPoint, previous: WindowPoint | None) -> Tier1Result:
    result = Tier1Result()
    values = {
        Channel.TEMP_C: current.temp_c,
        Channel.PRES_HPA: current.pres_hpa,
        Channel.RHUM_PCT: current.rhum_pct,
    }
    if any(value is None for value in values.values()):
        result.comm_error = True
        return result

    for channel, value in values.items():
        low, high = RANGE[channel]
        if value < low or value > high:
            result.range_fail.append(channel)

    if previous is not None:
        prev = {
            Channel.TEMP_C: previous.temp_c,
            Channel.PRES_HPA: previous.pres_hpa,
            Channel.RHUM_PCT: previous.rhum_pct,
        }
        for channel, value in values.items():
            prior = prev[channel]
            if prior is None:
                continue
            if abs(value - prior) > STEP[channel]:
                result.step_fail.append(channel)
    return result
