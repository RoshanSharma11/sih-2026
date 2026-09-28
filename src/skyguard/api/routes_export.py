"""GET /export — QC'd hours as CSV with a WMO-style quality flag.

Raw T / P / H are written as stored. `qc_flag` follows the common 0–9 convention:
0 good, 1 probably good (a genuine extreme the neighbours confirmed), 2 suspect
(unconfirmed), 3 erroneous (physical or hardware fault), 9 not checked (warming up,
feed gap, or no label). Predicted columns are filled only where v2 corrected the hour.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from skyguard.api.deps import get_db
from skyguard.db.models import Station, TelemetryLog
from skyguard.engine.pipeline import as_utc, feed_gap_from_row
from skyguard.schemas import Label

router = APIRouter()

QC_FLAG_NOT_CHECKED = 9
QC_FLAG = {
    Label.CLEAN.value: 0,
    Label.GENUINE_WEATHER_EVENT.value: 1,
    Label.UNCONFIRMED_ANOMALY.value: 2,
    Label.PHYSICAL_FAULT.value: 3,
    Label.HARDWARE_ANOMALY.value: 3,
}
QC_FLAG_TEXT = {0: "good", 1: "probably_good", 2: "suspect", 3: "erroneous", 9: "not_checked"}

EXPORT_COLUMNS = (
    "station_id",
    "timestamp_utc",
    "temp_c",
    "pres_hpa",
    "rhum_pct",
    "qc_flag",
    "qc_flag_text",
    "qc_label",
    "warming_up",
    "feed_gap",
    "temp_c_predicted",
    "pres_hpa_predicted",
    "rhum_pct_predicted",
    "reason",
)

_CHUNK_ROWS = 500


def qc_flag_for(label: str | None, *, warming_up: bool = False, feed_gap: bool = False) -> int:
    """Hour-level WMO-style flag. Unscored hours are 9, never 0."""
    if warming_up or feed_gap or not label:
        return QC_FLAG_NOT_CHECKED
    return QC_FLAG.get(label, QC_FLAG_NOT_CHECKED)


def export_row(row: TelemetryLog) -> list[object]:
    gap = feed_gap_from_row(row)
    flag = qc_flag_for(row.label, warming_up=bool(row.warming_up), feed_gap=bool(gap))
    return [
        row.station_id,
        as_utc(row.timestamp).strftime("%Y-%m-%dT%H:%M:%SZ"),
        _num(row.temp_observed),
        _num(row.pres_observed),
        _num(row.rhum_observed),
        flag,
        QC_FLAG_TEXT[flag],
        row.label or "",
        int(bool(row.warming_up)),
        "|".join(channel.value for channel in gap),
        _num(row.temp_imputed),
        _num(row.pres_imputed),
        _num(row.rhum_imputed),
        (row.explainability_text or "").replace("\n", " "),
    ]


def _num(value: float | None) -> str | float:
    return "" if value is None else value


def _csv_chunks(rows: Iterator[TelemetryLog]) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)
    count = 0
    for row in rows:
        writer.writerow(export_row(row))
        count += 1
        if count % _CHUNK_ROWS == 0:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
    yield buffer.getvalue()


@router.get("/export", response_class=StreamingResponse)
def export_csv(
    session: Session = Depends(get_db),
    station_id: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(default=50000, ge=1, le=500000),
) -> StreamingResponse:
    """CSV of stored hours, oldest first. No `station_id` means every station."""
    stmt = select(TelemetryLog)
    if station_id is not None:
        if session.get(Station, station_id) is None:
            raise HTTPException(status_code=404, detail=f"Unknown station_id: {station_id}")
        stmt = stmt.where(TelemetryLog.station_id == station_id)
    if from_ is not None:
        stmt = stmt.where(TelemetryLog.timestamp >= as_utc(from_))
    if to is not None:
        stmt = stmt.where(TelemetryLog.timestamp <= as_utc(to))
    stmt = stmt.order_by(TelemetryLog.station_id, TelemetryLog.timestamp).limit(limit)
    rows = session.scalars(stmt).all()
    name = f"skyguard_{station_id or 'network'}_qc.csv"
    return StreamingResponse(
        _csv_chunks(iter(rows)),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
