"""Dataset profiling and reconnaissance engine for Pathora.

Inspects any CSV, JSON, or JSONL file to reveal schema, distributions,
anomalies, missing values, duplicates, and confidence in canonical field mapping.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from backend.ingestion import (
    detect_field_mappings,
    normalize_record,
    normalize_severity,
    parse_raw_records,
    parse_timestamp,
)
from backend.models import (
    DatasetProfile,
    FieldProfile,
    TimestampAnalysis,
)


def compute_record_hash(record: Dict[str, Any]) -> str:
    """Compute a deterministic hash for an arbitrary dictionary."""
    serialized = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def detect_type(val: Any) -> str:
    """Detect high-level data type of a value."""
    if val is None or val == "":
        return "null"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "float"
    if isinstance(val, (dict, list)):
        return "complex"
    if isinstance(val, str):
        # Check if integer or float
        if val.lstrip("-").isdigit():
            return "integer"
        try:
            float(val)
            return "float"
        except ValueError:
            pass
        # Check if date/timestamp
        dt, _, _ = parse_timestamp(val)
        if dt is not None and any(c in val for c in ["-", ":", "T", "/"]):
            return "datetime"
        return "string"
    return type(val).__name__


def profile_dataset(file_path: Union[str, Path]) -> DatasetProfile:
    """Run full schema and data reconnaissance on a target file."""
    path = Path(file_path)
    records, malformed_count, fmt = parse_raw_records(path)
    
    total_records = len(records)
    if total_records == 0:
        return DatasetProfile(
            source_path=str(path),
            format=fmt,
            total_records=0,
            valid_records=0,
            malformed_records=malformed_count,
            duplicate_records_exact=0,
            potential_duplicate_alerts=0,
            notes=["Dataset is empty or contains no valid records."]
        )

    # 1. Discover all unique keys / columns across all records
    all_keys: Set[str] = set()
    for r in records:
        all_keys.update(r.keys())
    columns = sorted(list(all_keys))

    # 2. Heuristic field mapping
    sample_records = records[:50]
    inferred_mappings = detect_field_mappings(columns, sample_records)

    # 3. Exact record duplicate detection
    record_hashes: Dict[str, int] = {}
    for r in records:
        h = compute_record_hash(r)
        record_hashes[h] = record_hashes.get(h, 0) + 1

    duplicate_records_exact = sum(count - 1 for count in record_hashes.values() if count > 1)

    # 4. Field profiles
    field_profiles: Dict[str, FieldProfile] = {}
    for col in columns:
        col_values = [r.get(col) for r in records]
        non_nulls = [v for v in col_values if v is not None and v != ""]
        null_count = len(col_values) - len(non_nulls)
        
        # Types seen
        types_seen: Dict[str, int] = {}
        unique_samples: Set[str] = set()
        for v in non_nulls:
            t = detect_type(v)
            types_seen[t] = types_seen.get(t, 0) + 1
            if len(unique_samples) < 5:
                unique_samples.add(str(v)[:80])

        primary_type = max(types_seen.items(), key=lambda x: x[1])[0] if types_seen else "unknown"
        unique_count = len(set(str(v) for v in non_nulls))

        field_profiles[col] = FieldProfile(
            name=col,
            detected_type=primary_type,
            non_null_count=len(non_nulls),
            null_count=null_count,
            unique_count=unique_count,
            sample_values=list(unique_samples)[:5]
        )

    # 5. Timestamp analysis
    ts_inference = inferred_mappings.get("timestamp")
    ts_col = ts_inference.detected_column if ts_inference else None
    
    ts_analysis = TimestampAnalysis(field_name=ts_col)
    parsed_timestamps: List[datetime] = []
    
    if ts_col:
        for r in records:
            raw_val = r.get(ts_col)
            dt, is_aware, note = parse_timestamp(raw_val)
            if dt is not None:
                parsed_timestamps.append(dt)
                if is_aware:
                    ts_analysis.timezone_aware_count += 1
                else:
                    ts_analysis.timezone_naive_count += 1
            else:
                ts_analysis.parse_failures += 1

        if parsed_timestamps:
            parsed_timestamps.sort()
            ts_analysis.min_timestamp = parsed_timestamps[0]
            ts_analysis.max_timestamp = parsed_timestamps[-1]
            ts_analysis.span_seconds = (ts_analysis.max_timestamp - ts_analysis.min_timestamp).total_seconds()
            
            if ts_analysis.timezone_naive_count > 0 and ts_analysis.timezone_aware_count > 0:
                ts_analysis.notes.append("Mixed timezone awareness detected: some records are naive, others aware.")
            elif ts_analysis.timezone_naive_count > 0:
                ts_analysis.notes.append("Timestamps are timezone-naive (assumed UTC for comparison).")
            else:
                ts_analysis.notes.append("All timestamps include explicit timezone offsets.")

    # 6. Service & Severity distributions
    svc_inference = inferred_mappings.get("service")
    svc_col = svc_inference.detected_column if svc_inference else None
    service_dist: Dict[str, int] = {}
    if svc_col:
        for r in records:
            s = str(r.get(svc_col) or "unknown").strip()
            service_dist[s] = service_dist.get(s, 0) + 1

    sev_inference = inferred_mappings.get("severity")
    sev_col = sev_inference.detected_column if sev_inference else None
    severity_dist: Dict[str, int] = {}
    if sev_col:
        for r in records:
            raw_s = r.get(sev_col)
            normalized_s = normalize_severity(raw_s)
            severity_dist[normalized_s] = severity_dist.get(normalized_s, 0) + 1

    # 7. Potential duplicate alerts (same normalized timestamp, service, and message)
    alert_signatures: Dict[str, int] = {}
    msg_inference = inferred_mappings.get("message")
    msg_col = msg_inference.detected_column if msg_inference else None
    for r in records:
        t_key = str(r.get(ts_col)) if ts_col else ""
        s_key = str(r.get(svc_col)) if svc_col else ""
        m_key = str(r.get(msg_col))[:100] if msg_col else ""
        sig = f"{t_key}|{s_key}|{m_key}"
        alert_signatures[sig] = alert_signatures.get(sig, 0) + 1

    potential_duplicate_alerts = sum(c - 1 for c in alert_signatures.values() if c > 1)

    # 8. Check for ground truth labels & dependency graph cues
    has_labels = False
    label_col = inferred_mappings.get("incident_label")
    if label_col and label_col.detected_column:
        has_labels = True

    has_dependency = False
    for col in columns:
        if any(term in col.lower() for term in ["dependency", "depends_on", "target_service", "caller", "callee"]):
            has_dependency = True
            break

    # 9. Synthetic flag detection
    is_synthetic = False
    sample_text = json.dumps(sample_records).lower()
    if "synthetic" in sample_text or "mock" in str(path).lower() or "test_scenario" in sample_text:
        is_synthetic = True

    # 10. Sanitized samples (first 3 records, clean values)
    sanitized_samples = []
    for r in sample_records[:3]:
        clean_r = {}
        for k, v in r.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                clean_r[k] = v
            else:
                clean_r[k] = str(v)[:100]
        sanitized_samples.append(clean_r)

    notes = []
    if malformed_count > 0:
        notes.append(f"Encountered {malformed_count} malformed rows during ingestion.")
    if duplicate_records_exact > 0:
        notes.append(f"Found {duplicate_records_exact} exact duplicate rows.")
    if is_synthetic:
        notes.append("DATASET IDENTIFIED AS SYNTHETIC / PRE-COMPETITION TEST DATA.")

    return DatasetProfile(
        source_path=str(path),
        format=fmt,
        total_records=total_records,
        valid_records=total_records,
        malformed_records=malformed_count,
        duplicate_records_exact=duplicate_records_exact,
        potential_duplicate_alerts=potential_duplicate_alerts,
        fields=field_profiles,
        inferred_mappings=inferred_mappings,
        timestamp_analysis=ts_analysis,
        service_distribution=service_dist,
        severity_distribution=severity_dist,
        has_incident_labels=has_labels,
        has_dependency_info=has_dependency,
        sanitized_samples=sanitized_samples,
        is_synthetic=is_synthetic,
        notes=notes
    )
