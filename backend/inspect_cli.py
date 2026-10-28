"""Pathora Dataset Reconnaissance CLI.

Usage:
    python -m backend.inspect_cli <path-to-file>
    python -m backend.inspect_cli --generate-synthetic
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from backend.inspector import profile_dataset
from backend.synthetic import save_synthetic_dataset


def format_cli_report(profile: Any) -> str:
    """Format DatasetProfile into human-readable terminal report."""
    lines = []
    bar = "=" * 70
    sub_bar = "-" * 70

    lines.append(bar)
    lines.append("  PATHORA — DATASET RECONNAISSANCE REPORT")
    lines.append("  From alert noise to incident clarity.")
    lines.append(bar)
    lines.append(f"  Source File : {profile.source_path}")
    lines.append(f"  Format      : {profile.format.upper()}")
    dataset_type = "SYNTHETIC / TEST DATA" if profile.is_synthetic else "OFFICIAL / UNKNOWN DATA"
    lines.append(f"  Data Origin : {dataset_type}")
    lines.append(sub_bar)

    # 1. Volume & Hygiene
    lines.append("\n[1] RECORD VOLUME & HYGIENE")
    lines.append(f"  - Total Records Ingested   : {profile.total_records}")
    lines.append(f"  - Valid Parsed Records     : {profile.valid_records}")
    lines.append(f"  - Malformed Rows / Lines   : {profile.malformed_records}")
    lines.append(f"  - Exact Duplicate Rows     : {profile.duplicate_records_exact}")
    lines.append(f"  - Potential Alert Dupes    : {profile.potential_duplicate_alerts} (matching ts + service + message)")

    # 2. Schema & Field Profiles
    lines.append("\n[2] DETECTED SCHEMA & FIELD INTEGRITY")
    header = f"  {'Field Name':<20} {'Detected Type':<15} {'Non-Null':<10} {'Nulls':<8} {'Uniques':<8}"
    lines.append(header)
    lines.append("  " + "-" * 65)
    for col, fp in profile.fields.items():
        lines.append(f"  {fp.name:<20} {fp.detected_type:<15} {fp.non_null_count:<10} {fp.null_count:<8} {fp.unique_count:<8}")

    # 3. Inferred Mappings & Uncertainty
    lines.append("\n[3] CANONICAL FIELD HEURISTICS & UNCERTAINTY")
    for canonical, inf in profile.inferred_mappings.items():
        col_str = inf.detected_column or "NOT DETECTED"
        conf_pct = int(inf.confidence * 100)
        conf_str = f"{conf_pct}% confidence" if inf.detected_column else "0% (absent)"
        alt_str = f" | Alternatives: {', '.join(inf.alternatives)}" if inf.alternatives else ""
        lines.append(f"  - {canonical:<15} -> {col_str} ({conf_str}){alt_str}")

    # 4. Timestamp Analysis
    lines.append("\n[4] TIMESTAMP RANGE & TEMPORAL INTEGRITY")
    ts = profile.timestamp_analysis
    if ts.field_name:
        lines.append(f"  - Timestamp Field          : {ts.field_name}")
        lines.append(f"  - Earliest Event           : {ts.min_timestamp}")
        lines.append(f"  - Latest Event             : {ts.max_timestamp}")
        span_hrs = round(ts.span_seconds / 3600.0, 2) if ts.span_seconds else 0.0
        lines.append(f"  - Total Temporal Span      : {span_hrs} hours ({ts.span_seconds} seconds)")
        lines.append(f"  - Timezone Aware Records   : {ts.timezone_aware_count}")
        lines.append(f"  - Timezone Naive Records   : {ts.timezone_naive_count}")
        lines.append(f"  - Timestamp Parse Failures : {ts.parse_failures}")
        for note in ts.notes:
            lines.append(f"    * Note: {note}")
    else:
        lines.append("  - No timestamp column confidently detected.")

    # 5. Service & Severity Distributions
    lines.append("\n[5] DISTRIBUTIONS")
    if profile.severity_distribution:
        sev_parts = [f"{k}: {v}" for k, v in sorted(profile.severity_distribution.items())]
        lines.append(f"  - Normalized Severities    : {', '.join(sev_parts)}")
    else:
        lines.append("  - Severities               : Not detected")

    if profile.service_distribution:
        top_services = sorted(profile.service_distribution.items(), key=lambda x: x[1], reverse=True)[:6]
        svc_parts = [f"{s} ({c})" for s, c in top_services]
        lines.append(f"  - Top Services             : {', '.join(svc_parts)}")
        lines.append(f"  - Total Unique Services    : {len(profile.service_distribution)}")
    else:
        lines.append("  - Services                 : Not detected")

    # 6. Metadata presence
    lines.append("\n[6] GROUND TRUTH & TOPOLOGY RECONNAISSANCE")
    lines.append(f"  - Incident Labels Detected : {'YES' if profile.has_incident_labels else 'NO (Unsupervised mode required)'}")
    lines.append(f"  - Dependency Graph Cues    : {'YES' if profile.has_dependency_info else 'NO (Topology-blind mode required)'}")

    # 7. Sanitized sample records
    lines.append("\n[7] SANITIZED SAMPLE RECORDS")
    for idx, s in enumerate(profile.sanitized_samples, start=1):
        lines.append(f"  Record #{idx}:")
        for k, v in s.items():
            lines.append(f"    {k}: {v}")

    if profile.notes:
        lines.append("\n[8] NOTES & WARNINGS")
        for n in profile.notes:
            lines.append(f"  ! {n}")

    lines.append(bar)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Pathora Dataset Reconnaissance CLI — Inspect CSV, JSON, and JSONL alert files."
    )
    parser.add_argument(
        "file_path",
        nargs="?",
        help="Path to the dataset file (CSV, JSON, JSONL) to inspect."
    )
    parser.add_argument(
        "--generate-synthetic",
        action="store_true",
        help="Generate synthetic fixtures (small and eval) in data/synthetic/."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON profile instead of formatted text."
    )

    args = parser.parse_args()

    if args.generate_synthetic:
        out_dir = Path("data/synthetic")
        print(f"Generating synthetic fixtures in {out_dir.resolve()}...")
        small_files = save_synthetic_dataset(out_dir, scale="small", seed=42)
        eval_files = save_synthetic_dataset(out_dir, scale="eval", seed=42)
        print("Successfully generated synthetic datasets:")
        print(f"  - Small dataset : {small_files['alerts_json']}")
        print(f"  - Eval dataset  : {eval_files['alerts_json']}")
        print(f"  - Ground truth  : {small_files['ground_truth']}")
        print(f"  - Dependencies  : {small_files['dependencies']}")
        print("\nTo inspect the small synthetic dataset, run:")
        print(f"  python -m backend.inspect_cli {small_files['alerts_json']}\n")
        return

    if not args.file_path:
        default_synth = Path("data/synthetic/synthetic_small_alerts.json")
        if default_synth.exists():
            print(f"No file path provided. Inspecting default synthetic fixture: {default_synth}")
            target_path = default_synth
        else:
            print("=" * 70)
            print("  PATHORA DATASET RECONNAISSANCE CLI")
            print("=" * 70)
            print("No input dataset file specified and no default synthetic fixture found.")
            print("\nTo generate synthetic test fixtures, run:")
            print("  python -m backend.inspect_cli --generate-synthetic")
            print("\nTo inspect any official or custom file, run:")
            print("  python -m backend.inspect_cli <path/to/dataset.csv|json|jsonl>")
            print("=" * 70)
            sys.exit(0)
    else:
        target_path = Path(args.file_path)

    if not target_path.exists():
        print(f"Error: File not found: {target_path}", file=sys.stderr)
        sys.exit(1)

    profile = profile_dataset(target_path)

    if args.json:
        print(profile.model_dump_json(indent=2))
    else:
        print(format_cli_report(profile))


if __name__ == "__main__":
    main()
