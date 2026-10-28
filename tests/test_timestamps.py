"""Tests for timestamp parsing, epoch conversion, and timezone handling."""

from datetime import datetime, timezone
from backend.ingestion import parse_timestamp


def test_iso_timestamp_parsing():
    dt, is_aware, note = parse_timestamp("2026-10-28T14:30:00Z")
    assert dt is not None
    assert is_aware is True
    assert dt.year == 2026
    assert dt.hour == 14
    assert dt.utcoffset().total_seconds() == 0


def test_iso_with_explicit_offset():
    dt, is_aware, note = parse_timestamp("2026-10-28T14:30:00+05:30")
    assert dt is not None
    assert is_aware is True
    # Convert to UTC to compare
    utc_dt = dt.astimezone(timezone.utc)
    assert utc_dt.hour == 9
    assert utc_dt.minute == 0


def test_timezone_naive_conversion():
    dt, is_aware, note = parse_timestamp("2026-10-28 14:30:00")
    assert dt is not None
    assert is_aware is False
    assert "naive" in note
    # Should safely have default UTC tzinfo for comparison
    assert dt.tzinfo is not None


def test_epoch_seconds_parsing():
    # 1700000000 = Wed Nov 14 2023 22:13:20 UTC
    dt, is_aware, note = parse_timestamp(1700000000)
    assert dt is not None
    assert is_aware is True
    assert note == "epoch_s"
    assert dt.year == 2023


def test_epoch_milliseconds_parsing():
    # 1700000000000 = Wed Nov 14 2023 22:13:20 UTC in ms
    dt, is_aware, note = parse_timestamp(1700000000000)
    assert dt is not None
    assert is_aware is True
    assert note == "epoch_ms"
    assert dt.year == 2023


def test_invalid_timestamps():
    dt, is_aware, note = parse_timestamp("NOT_A_VALID_DATE_TIME")
    assert dt is None
    assert note == "parse_error"

    dt, is_aware, note = parse_timestamp(None)
    assert dt is None
    assert note == "empty"
