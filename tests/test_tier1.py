from datetime import datetime, timezone

from skyguard.engine.tier1 import evaluate
from skyguard.engine.windows import WindowPoint
from skyguard.schemas import Channel


def _point(temp_c, pres_hpa=1005.0, rhum_pct=60.0):
    return WindowPoint(
        timestamp=datetime(2024, 6, 30, 15, tzinfo=timezone.utc),
        temp_c=temp_c,
        pres_hpa=pres_hpa,
        rhum_pct=rhum_pct,
    )


def test_null_is_comm_error() -> None:
    result = evaluate(_point(None), None)
    assert result.comm_error is True
    assert result.failed is True


def test_range_fail_on_hot_temperature() -> None:
    result = evaluate(_point(65.0), None)
    assert Channel.TEMP_C in result.range_fail
    assert result.comm_error is False


def test_step_fail_and_pass() -> None:
    previous = _point(32.0)
    assert Channel.TEMP_C in evaluate(_point(45.0), previous).step_fail
    assert evaluate(_point(33.0), previous).failed is False
