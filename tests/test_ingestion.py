"""Tests for CSV, JSON, JSONL ingestion, field heuristics, and duplicate detection."""

import json
import tempfile
from pathlib import Path
from backend.ingestion import (
    detect_field_mappings,
    normalize_record,
    normalize_severity,
    parse_raw_records,
)
from backend.inspector import profile_dataset


def test_parse_csv_file():
    content = "id,timestamp,service,severity,message\nalt_1,2026-10-28T10:00:00Z,auth,critical,Token expired\nalt_2,2026-10-28T10:05:00Z,db,error,Lock wait timeout\n"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    records, malformed, fmt = parse_raw_records(path)
    assert fmt == "csv"
    assert len(records) == 2
    assert malformed == 0
    assert records[0]["service"] == "auth"
    Path(path).unlink()


def test_parse_json_file():
    data = [
        {"alert_id": "j1", "event_time": "2026-10-28T12:00:00Z", "app": "billing", "level": "warn", "text": "High latency"},
        {"alert_id": "j2", "event_time": "2026-10-28T12:01:00Z", "app": "checkout", "level": "crit", "text": "Payment gateway down"}
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name

    records, malformed, fmt = parse_raw_records(path)
    assert fmt == "json"
    assert len(records) == 2
    assert malformed == 0
    Path(path).unlink()


def test_parse_jsonl_file():
    lines = [
        json.dumps({"uuid": "l1", "ts": "2026-10-28T14:00:00Z", "service": "redis", "msg": "Memory pressure"}),
        json.dumps({"uuid": "l2", "ts": "2026-10-28T14:01:00Z", "service": "search", "msg": "Index rebuild"}),
        "MALFORMED_NON_JSON_LINE"
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(lines))
        path = f.name

    records, malformed, fmt = parse_raw_records(path)
    assert fmt == "jsonl"
    assert len(records) == 2
    assert malformed == 1
    Path(path).unlink()


def test_missing_fields_and_fallbacks():
    raw_empty = {"custom_field": "test"}
    mappings = detect_field_mappings(["custom_field"], [raw_empty])
    normalized = normalize_record(raw_empty, mappings, index=7)
    
    # Should use fallback ID, unknown service/severity, and preserve custom attribute
    assert normalized.id == "alert_000007"
    assert normalized.service == "unknown"
    assert normalized.severity == "unknown"
    assert normalized.attributes.get("custom_field") == "test"


def test_exact_and_potential_duplicate_detection():
    # Exact duplicate and semantic duplicate
    content = (
        "id,time,service,severity,message\n"
        "a1,2026-10-28T10:00:00Z,db,crit,timeout\n"
        "a1,2026-10-28T10:00:00Z,db,crit,timeout\n"  # Exact duplicate
        "a2,2026-10-28T10:00:00Z,db,crit,timeout\n"  # Potential duplicate (different id, same ts+svc+msg)
        "a3,2026-10-28T11:00:00Z,auth,info,healthy\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(content)
        path = f.name

    profile = profile_dataset(path)
    assert profile.total_records == 4
    assert profile.duplicate_records_exact == 1
    assert profile.potential_duplicate_alerts >= 2
    Path(path).unlink()


def test_severity_normalization():
    assert normalize_severity("CRITICAL") == "critical"
    assert normalize_severity("fatal") == "critical"
    assert normalize_severity("P1") == "critical"
    assert normalize_severity("SEV1") == "critical"
    assert normalize_severity("error") == "error"
    assert normalize_severity("P2") == "error"
    assert normalize_severity("warn") == "warning"
    assert normalize_severity("notice") == "info"
    assert normalize_severity("unknown_level") == "unknown"
    assert normalize_severity(None) == "unknown"
