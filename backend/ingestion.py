"""Ingestion, field detection heuristics, and parsing for Pathora.

Accepts CSV, JSON, and JSONL formats without assuming field names.
Normalizes heterogeneous data into `NormalizedAlert` while preserving raw attributes.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from dateutil import parser as date_parser

from backend.models import (
    FieldInference,
    FieldProfile,
    NormalizedAlert,
    TimestampAnalysis,
)

# Known heuristic keywords ranked by typical specificity
FIELD_KEYWORDS = {
    "id": [
        "alert_id", "alertid", "event_id", "eventid", "id", "uuid", "notification_id",
        "ticket_id", "record_id", "row_id"
    ],
    "timestamp": [
        "timestamp", "time", "created_at", "starts_at", "start_time", "event_time",
        "datetime", "@timestamp", "ts", "alert_time", "fired_at", "date", "occurred_at"
    ],
    "service": [
        "service", "service_name", "app", "application", "microservice", "component",
        "system", "target", "subservice", "sys", "module"
    ],
    "severity": [
        "severity", "level", "priority", "status", "alert_level", "criticity",
        "tier", "urgency", "impact"
    ],
    "message": [
        "message", "summary", "description", "title", "alertname", "alert_name",
        "rule_name", "rule", "text", "msg", "details", "subject", "error_message"
    ],
    "source": [
        "source", "monitor", "tool", "emitter", "agent", "origin", "reporter",
        "monitoring_tool", "system_source", "provider"
    ],
    "host": [
        "host", "hostname", "node", "server", "instance", "pod", "machine",
        "device", "container"
    ],
    "incident_label": [
        "incident", "incident_id", "incident_key", "group_id", "cluster_id",
        "ticket", "issue_key", "incident_number", "root_cause_incident"
    ],
}

SEVERITY_MAP = {
    "critical": ["crit", "critical", "fatal", "p1", "sev1", "sev-1", "emergency", "high_critical"],
    "error": ["error", "err", "fail", "failed", "p2", "sev2", "sev-2", "major", "high"],
    "warning": ["warning", "warn", "p3", "sev3", "sev-3", "medium", "moderate"],
    "info": ["info", "information", "notice", "debug", "p4", "sev4", "sev-4", "low", "trivial"],
}


def normalize_severity(raw_val: Any) -> str:
    """Normalize arbitrary severity strings or numbers to standard levels."""
    if raw_val is None:
        return "unknown"
    val = str(raw_val).strip().lower()
    
    # Direct numeric level mapping if applicable (e.g., 1=critical, 2=error)
    if val in ("1", "1.0"):
        return "critical"
    elif val in ("2", "2.0"):
        return "error"
    elif val in ("3", "3.0"):
        return "warning"
    elif val in ("4", "4.0", "5", "5.0"):
        return "info"

    for level, synonyms in SEVERITY_MAP.items():
        if val in synonyms:
            return level
        if any(syn in val for syn in synonyms):
            return level
            
    return "unknown"


def parse_timestamp(val: Any) -> Tuple[Optional[datetime], bool, str]:
    """Parse a timestamp from various formats.
    
    Returns:
        (datetime_obj, is_timezone_aware, note)
    """
    if val is None or val == "":
        return None, False, "empty"

    # Numeric timestamp (epoch seconds or milliseconds)
    if isinstance(val, (int, float)) or (isinstance(val, str) and val.replace(".", "", 1).isdigit()):
        try:
            num = float(val)
            # Epoch milliseconds typically > 1e11 (year 1973+)
            if num > 1e11:
                dt = datetime.fromtimestamp(num / 1000.0, tz=timezone.utc)
                return dt, True, "epoch_ms"
            else:
                dt = datetime.fromtimestamp(num, tz=timezone.utc)
                return dt, True, "epoch_s"
        except (ValueError, OverflowError, OSError):
            pass

    # String date parsing
    if isinstance(val, str):
        val_str = val.strip()
        try:
            dt = date_parser.parse(val_str)
            is_aware = dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None
            if not is_aware:
                # Default to UTC for naive timestamps to avoid comparison errors
                dt = dt.replace(tzinfo=timezone.utc)
                return dt, False, "iso_or_string_naive_converted_to_utc"
            return dt, True, "iso_or_string_aware"
        except (ValueError, OverflowError):
            return None, False, "parse_error"

    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc), False, "datetime_naive_converted_to_utc"
        return val, True, "datetime_aware"

    return None, False, "unsupported_type"


def detect_field_mappings(
    columns: List[str],
    samples: List[Dict[str, Any]]
) -> Dict[str, FieldInference]:
    """Infer likely canonical alert fields with uncertainty scoring."""
    lower_cols = {col.lower().strip(): col for col in columns}
    mappings: Dict[str, FieldInference] = {}

    for canonical, keywords in FIELD_KEYWORDS.items():
        best_col: Optional[str] = None
        best_score = 0.0
        rationale = ""
        alternatives = []

        # Check column names
        for kw in keywords:
            for l_col, orig_col in lower_cols.items():
                score = 0.0
                if l_col == kw:
                    score = 0.95
                elif l_col.startswith(kw) or l_col.endswith(kw):
                    score = 0.80
                elif kw in l_col:
                    score = 0.65

                if score > 0:
                    alternatives.append((orig_col, score))

        # Check sample values for confirmation
        # e.g., if column values parse as timestamps or match severities
        for l_col, orig_col in lower_cols.items():
            sample_vals = [s.get(orig_col) for s in samples if s.get(orig_col) is not None][:10]
            if not sample_vals:
                continue

            if canonical == "timestamp":
                parsed_count = sum(1 for v in sample_vals if parse_timestamp(v)[0] is not None)
                if parsed_count >= len(sample_vals) * 0.7:
                    score = 0.85 if "time" in l_col or "date" in l_col else 0.50
                    alternatives.append((orig_col, score))
            elif canonical == "severity":
                sev_matches = sum(1 for v in sample_vals if normalize_severity(v) != "unknown")
                if sev_matches >= len(sample_vals) * 0.6:
                    score = 0.90 if "sev" in l_col or "level" in l_col else 0.55
                    alternatives.append((orig_col, score))

        # Pick highest scoring candidate
        if alternatives:
            # Sort by score desc, remove duplicates preserving order
            seen = set()
            sorted_alts = []
            for col_name, sc in sorted(alternatives, key=lambda x: x[1], reverse=True):
                if col_name not in seen:
                    seen.add(col_name)
                    sorted_alts.append((col_name, sc))

            best_col, best_score = sorted_alts[0]
            other_alts = [c for c, _ in sorted_alts[1:5]]
            rationale = f"Matched keyword/value heuristic with confidence {best_score:.2f}."
            mappings[canonical] = FieldInference(
                detected_column=best_col,
                confidence=round(best_score, 2),
                alternatives=other_alts,
                rationale=rationale
            )
        else:
            mappings[canonical] = FieldInference(
                detected_column=None,
                confidence=0.0,
                alternatives=[],
                rationale=f"No matching column found for {canonical}."
            )

    return mappings


def parse_raw_records(file_path: Union[str, Path]) -> Tuple[List[Dict[str, Any]], int, str]:
    """Parse raw records from CSV, JSON, or JSONL file.
    
    Returns:
        (records_list, malformed_lines_count, format_name)
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    records: List[Dict[str, Any]] = []
    malformed = 0

    if ext == ".csv":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            sample = f.read(4096)
            f.seek(0)
            delimiter = ","
            try:
                sniffer = csv.Sniffer()
                dialect = sniffer.sniff(sample)
                delimiter = dialect.delimiter
            except Exception:
                delimiter = ","

            reader = csv.DictReader(f, delimiter=delimiter)
            for i, row in enumerate(reader):
                try:
                    # Clean up empty or None keys
                    clean_row = {str(k).strip(): v for k, v in row.items() if k is not None}
                    records.append(clean_row)
                except Exception:
                    malformed += 1
        return records, malformed, "csv"

    elif ext == ".jsonl":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                clean_line = line.strip()
                if not clean_line:
                    continue
                try:
                    obj = json.loads(clean_line)
                    if isinstance(obj, dict):
                        records.append(obj)
                    else:
                        malformed += 1
                except Exception:
                    malformed += 1
        return records, malformed, "jsonl"

    elif ext == ".json":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            records.append(item)
                        else:
                            malformed += 1
                elif isinstance(data, dict):
                    # Check for container keys like 'alerts', 'data', 'records', 'items'
                    for key in ["alerts", "data", "records", "items", "events"]:
                        if key in data and isinstance(data[key], list):
                            for item in data[key]:
                                if isinstance(item, dict):
                                    records.append(item)
                                else:
                                    malformed += 1
                            break
                    else:
                        # Single object
                        records.append(data)
                else:
                    malformed += 1
            except Exception:
                malformed += 1
        return records, malformed, "json"

    else:
        # Fallback: attempt JSON, then JSONL, then CSV
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)], 0, "json"
        except Exception:
            pass

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = [line.strip() for line in f if line.strip()]
            try:
                obj_list = [json.loads(line) for line in lines]
                return [x for x in obj_list if isinstance(x, dict)], 0, "jsonl"
            except Exception:
                pass

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            return [dict(r) for r in reader], 0, "csv"


def normalize_record(
    raw: Dict[str, Any],
    mappings: Dict[str, FieldInference],
    index: int
) -> NormalizedAlert:
    """Map a single raw record into the canonical NormalizedAlert schema."""
    # Extract mapped or fallback fields
    id_col = mappings.get("id", FieldInference()).detected_column
    ts_col = mappings.get("timestamp", FieldInference()).detected_column
    svc_col = mappings.get("service", FieldInference()).detected_column
    sev_col = mappings.get("severity", FieldInference()).detected_column
    msg_col = mappings.get("message", FieldInference()).detected_column
    src_col = mappings.get("source", FieldInference()).detected_column
    host_col = mappings.get("host", FieldInference()).detected_column

    # Alert ID
    raw_id = raw.get(id_col) if id_col else None
    alert_id = str(raw_id).strip() if raw_id is not None and str(raw_id).strip() else f"alert_{index:06d}"

    # Timestamp
    raw_ts = raw.get(ts_col) if ts_col else None
    parsed_ts, _, _ = parse_timestamp(raw_ts)
    if parsed_ts is None:
        parsed_ts = datetime.now(timezone.utc)

    # Service
    raw_svc = raw.get(svc_col) if svc_col else None
    service = str(raw_svc).strip() if raw_svc is not None and str(raw_svc).strip() else "unknown"

    # Severity
    raw_sev = raw.get(sev_col) if sev_col else None
    severity = normalize_severity(raw_sev)

    # Message
    raw_msg = raw.get(msg_col) if msg_col else None
    if raw_msg is not None and str(raw_msg).strip():
        message = str(raw_msg).strip()
    else:
        # Fallback message
        message = f"Alert from {service}" if service != "unknown" else "Unspecified system alert"

    # Source
    raw_src = raw.get(src_col) if src_col else None
    source = str(raw_src).strip() if raw_src is not None and str(raw_src).strip() else "generic"

    # Host
    raw_host = raw.get(host_col) if host_col else None
    host = str(raw_host).strip() if raw_host is not None and str(raw_host).strip() else None

    # Preserve all other fields in attributes
    mapped_cols = {id_col, ts_col, svc_col, sev_col, msg_col, src_col, host_col} - {None}
    attributes = {k: v for k, v in raw.items() if k not in mapped_cols}

    is_synthetic = bool(raw.get("is_synthetic", False) or "synthetic" in alert_id.lower())

    return NormalizedAlert(
        id=alert_id,
        timestamp=parsed_ts,
        timestamp_raw=str(raw_ts) if raw_ts is not None else None,
        service=service,
        severity=severity,
        message=message,
        source=source,
        host=host,
        attributes=attributes,
        is_synthetic=is_synthetic
    )
