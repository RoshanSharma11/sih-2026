from skyguard import __version__
from skyguard.schemas import ClusterId, FaultType, IngestPayload


def test_package_version() -> None:
    assert __version__ == "0.1.0"


def test_contract_enums() -> None:
    assert FaultType.SPIKE.value == "SPIKE"
    assert ClusterId.NORTH.value == "NORTH"


def test_ingest_payload_accepts_null_channels() -> None:
    payload = IngestPayload(
        station_id="42182",
        timestamp="2024-07-01T14:00:00Z",
        temp_c=None,
        pres_hpa=1002.4,
        rhum_pct=71.0,
    )
    assert payload.temp_c is None
