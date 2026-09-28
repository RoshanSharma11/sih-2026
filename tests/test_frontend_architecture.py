from pathlib import Path

from theme import CSS
from v2_metrics import load_v2_metrics, metrics_html, overlay_figure, reconstruction_figure
from views.architecture import architecture_html


def test_architecture_page_follows_the_live_hour() -> None:
    html = architecture_html()
    assert "POST /ingest" in html
    assert "temp_c" in html
    assert "pres_hpa" in html
    assert "rhum_pct" in html
    assert "inject.py" in html
    assert "process_aws_data" in html
    assert "warming up" in html
    assert "TIMING" in html
    assert "Safdarjung" in html
    assert "Juhu" in html
    assert "Colaba" in html
    assert "Alibag" in html
    assert "sg-arch-packet" in html
    assert "sg-arch-travel" in CSS
    assert "sg-arch-wake" in CSS
    assert "sg-arch-check" in CSS


def test_architecture_charts_read_v2_artifacts() -> None:
    metrics = load_v2_metrics()
    assert metrics is not None
    recon = reconstruction_figure(metrics)
    overlay = overlay_figure(metrics)
    assert recon is not None and overlay is not None
    window = metrics["percentiles"]["window_mse"]
    assert list(recon.data[0].y)[0] == float(window["50"])
    assert list(overlay.data[0].y)[0] == float(metrics["overlay"]["val_mae_scaled"]["temp"])
    html = metrics_html(metrics)
    score = float(metrics["percentiles"]["operating_score"])
    assert f"{score:.6f}" in html
    assert "v2/artifacts" in html


def test_architecture_charts_skip_when_artifacts_are_missing(tmp_path: Path) -> None:
    assert load_v2_metrics(tmp_path) is None
