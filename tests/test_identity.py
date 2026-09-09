import numpy as np
import pytest
from pydantic import ValidationError

from skyguard.ml import IdentityDetector, load_detector
from skyguard.schemas import Channel, DemoInjectRequest, DemoKind


def test_identity_reconstructs_last_row() -> None:
    window = np.ones((24, 3), dtype=float)
    window[-1] = [28.4, 1008.0, 78.0]
    result = IdentityDetector().reconstruct(window)
    assert result.skipped is False
    assert result.mse == 0.0
    np.testing.assert_array_equal(result.reconstructed, [28.4, 1008.0, 78.0])
    np.testing.assert_array_equal(result.contribution_pct, [0.0, 0.0, 0.0])


def test_identity_skips_short_window() -> None:
    result = IdentityDetector().reconstruct(np.ones((8, 3)))
    assert result.skipped is True


def test_load_detector_default_is_identity() -> None:
    detector = load_detector()
    assert isinstance(detector, IdentityDetector)


def test_load_detector_rejects_unset_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PATH", "models/lstm.pt")
    with pytest.raises(NotImplementedError):
        load_detector()


def test_storm_inject_requires_neighborhood() -> None:
    with pytest.raises(ValidationError):
        DemoInjectRequest(
            target="station",
            station_id="42182",
            kind=DemoKind.SPIKE,
            channel=None,
        )
    with pytest.raises(ValidationError):
        DemoInjectRequest(
            target="station",
            station_id="42182",
            kind=DemoKind.GENUINE_WEATHER,
        )
    req = DemoInjectRequest(
        target="neighborhood",
        station_id="42181",
        kind=DemoKind.GENUINE_WEATHER,
    )
    assert req.station_id == "42181"
    with pytest.raises(ValidationError):
        DemoInjectRequest(
            target="neighborhood",
            station_id="42181",
            kind=DemoKind.SPIKE,
            channel=Channel.TEMP_C,
        )
