"""Runtime state, active dataset store, and correlation run management for Pathora."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.correlation.baseline import run_baseline_correlation
from backend.correlation.engine import run_correlation
from backend.evaluation import evaluate_run
from backend.ingestion import (
    detect_field_mappings,
    normalize_record,
    parse_raw_records,
)
from backend.inspector import profile_dataset
from backend.models import (
    ActiveDatasetStatus,
    CorrelationConfig,
    CorrelationRunSummary,
    DatasetProfile,
    GroundTruthDataset,
    NormalizedAlert,
    PredictedIncident,
    ServiceDependencyGraph,
    UnattachedAlert,
)
from backend.synthetic import SyntheticAlertGenerator


class AppState:
    """Manages currently active dataset and correlation runs in Pathora."""

    def __init__(self):
        self.dataset_name: str = "none"
        self.source_type: str = "synthetic"
        self.source_file: Optional[str] = None
        self.raw_records: List[Dict[str, Any]] = []
        self.normalized_alerts: List[NormalizedAlert] = []
        self.profile: Optional[DatasetProfile] = None
        self.ground_truth: Optional[GroundTruthDataset] = None
        self.dependency_graph: Optional[ServiceDependencyGraph] = None
        self.is_synthetic: bool = True

        # Correlation runs
        self.runs: Dict[str, CorrelationRunSummary] = {}
        self.run_incidents: Dict[str, List[PredictedIncident]] = {}
        self.run_unattached: Dict[str, List[UnattachedAlert]] = {}
        self.active_run_id: Optional[str] = None

        # Initialize with default synthetic dataset and auto-run correlation
        self.load_synthetic(scale="small", seed=42)

    def load_synthetic(self, scale: str = "small", seed: int = 42) -> ActiveDatasetStatus:
        """Generate and load synthetic dataset in memory."""
        generator = SyntheticAlertGenerator(seed=seed)
        raw_alerts, gt_dataset, dep_graph = generator.generate(scale=scale)

        self.dataset_name = f"synthetic_{scale}_v1"
        self.source_type = "synthetic"
        self.source_file = f"in-memory (seed={seed}, scale={scale})"
        self.is_synthetic = True
        self.raw_records = raw_alerts
        self.ground_truth = gt_dataset
        self.dependency_graph = dep_graph

        # Normalize alerts
        mappings = detect_field_mappings(
            list(raw_alerts[0].keys()) if raw_alerts else [],
            raw_alerts[:50]
        )
        self.normalized_alerts = [
            normalize_record(r, mappings, idx)
            for idx, r in enumerate(raw_alerts)
        ]

        # In-memory profiling
        temp_dir = Path("data/synthetic")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"synthetic_{scale}_alerts.json"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(raw_alerts, f, indent=2)

        self.profile = profile_dataset(temp_path)

        # Automatically execute initial correlation run so UI has incidents immediately
        self.execute_correlation(CorrelationConfig(algorithm="improved"))
        return self.get_status()

    def load_file(self, file_path: str) -> ActiveDatasetStatus:
        """Ingest a CSV, JSON, or JSONL file into active state."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        records, malformed, fmt = parse_raw_records(path)
        self.profile = profile_dataset(path)
        self.dataset_name = path.name
        self.source_file = str(path.resolve())
        self.is_synthetic = self.profile.is_synthetic
        self.source_type = "synthetic" if self.is_synthetic else "official"
        self.raw_records = records

        # Look for matching ground truth and dependency files in same dir
        parent = path.parent
        stem = path.stem
        base_prefix = stem.replace("_alerts", "")
        gt_path = parent / f"{base_prefix}_ground_truth.json"
        if gt_path.exists():
            try:
                with open(gt_path, "r", encoding="utf-8") as f:
                    self.ground_truth = GroundTruthDataset.model_validate_json(f.read())
            except Exception:
                self.ground_truth = None
        else:
            self.ground_truth = None

        dep_path = parent / f"{base_prefix}_dependencies.json"
        if dep_path.exists():
            try:
                with open(dep_path, "r", encoding="utf-8") as f:
                    self.dependency_graph = ServiceDependencyGraph.model_validate_json(f.read())
            except Exception:
                self.dependency_graph = None
        else:
            self.dependency_graph = None

        # Normalize
        sample_keys = list(records[0].keys()) if records else []
        mappings = detect_field_mappings(sample_keys, records[:50])
        self.normalized_alerts = [
            normalize_record(r, mappings, idx)
            for idx, r in enumerate(records)
        ]

        # Automatically execute initial correlation run
        self.execute_correlation(CorrelationConfig(algorithm="improved"))
        return self.get_status()

    def execute_correlation(self, config: CorrelationConfig) -> CorrelationRunSummary:
        """Execute correlation engine or baseline, record metrics, and store run."""
        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        total_alerts = len(self.normalized_alerts)

        if config.algorithm == "baseline":
            incidents, unattached = run_baseline_correlation(self.normalized_alerts, config)
            eval_metrics = evaluate_run(incidents, unattached, self.ground_truth, total_alerts)
            baseline_eval = eval_metrics
        else:
            # Improved Architecture B engine
            incidents, unattached = run_correlation(self.normalized_alerts, self.dependency_graph, config)
            eval_metrics = evaluate_run(incidents, unattached, self.ground_truth, total_alerts)

            # Also run baseline under default config to allow direct scoreboard comparison
            base_incidents, base_unattached = run_baseline_correlation(
                self.normalized_alerts,
                CorrelationConfig(algorithm="baseline")
            )
            baseline_eval = evaluate_run(base_incidents, base_unattached, self.ground_truth, total_alerts)

        tentative_count = sum(1 for inc in incidents if inc.tentative)
        total_groups = len(incidents) + len(unattached)
        reduction_rate = round(1.0 - (float(total_groups) / float(max(1, total_alerts))), 4)

        summary = CorrelationRunSummary(
            run_id=run_id,
            created_at=datetime.now(timezone.utc),
            algorithm=config.algorithm,
            dataset_name=self.dataset_name,
            is_synthetic=self.is_synthetic,
            config=config,
            total_input_alerts=total_alerts,
            total_incidents=len(incidents),
            total_unattached_alerts=len(unattached),
            tentative_incidents_count=tentative_count,
            notification_reduction_rate=reduction_rate,
            evaluation=eval_metrics,
            baseline_evaluation=baseline_eval
        )

        self.runs[run_id] = summary
        self.run_incidents[run_id] = incidents
        self.run_unattached[run_id] = unattached
        self.active_run_id = run_id
        return summary

    def get_active_run_summary(self) -> Optional[CorrelationRunSummary]:
        """Return summary of the most recent correlation run."""
        if not self.active_run_id or self.active_run_id not in self.runs:
            return None
        return self.runs[self.active_run_id]

    def get_run_incidents(self, run_id: Optional[str] = None) -> List[PredictedIncident]:
        """Return list of incidents for a run (defaults to active run)."""
        target_id = run_id or self.active_run_id
        if not target_id or target_id not in self.run_incidents:
            return []
        return self.run_incidents[target_id]

    def get_incident_detail(
        self,
        incident_id: str,
        run_id: Optional[str] = None
    ) -> Optional[Tuple[PredictedIncident, List[NormalizedAlert]]]:
        """Return PredictedIncident and its full NormalizedAlert instances."""
        target_id = run_id or self.active_run_id
        if not target_id or target_id not in self.run_incidents:
            return None

        incidents = self.run_incidents[target_id]
        found_inc = next((inc for inc in incidents if inc.incident_id == incident_id), None)
        if not found_inc:
            return None

        alert_map = {a.id: a for a in self.normalized_alerts}
        matched_alerts = [alert_map[aid] for aid in found_inc.alert_ids if aid in alert_map]
        matched_alerts.sort(key=lambda a: a.timestamp)
        return found_inc, matched_alerts

    def get_run_unattached(self, run_id: Optional[str] = None) -> List[UnattachedAlert]:
        """Return unattached singleton alerts for a run."""
        target_id = run_id or self.active_run_id
        if not target_id or target_id not in self.run_unattached:
            return []
        return self.run_unattached[target_id]

    def get_status(self) -> ActiveDatasetStatus:
        """Return high-level summary of active state."""
        sev_counts: Dict[str, int] = {}
        services = set()
        min_ts = None
        max_ts = None

        if self.normalized_alerts:
            sorted_alerts = sorted(self.normalized_alerts, key=lambda a: a.timestamp)
            min_ts = sorted_alerts[0].timestamp
            max_ts = sorted_alerts[-1].timestamp
            for a in self.normalized_alerts:
                sev_counts[a.severity] = sev_counts.get(a.severity, 0) + 1
                if a.service and a.service != "unknown":
                    services.add(a.service)

        gt_incidents_count = len(self.ground_truth.incidents) if self.ground_truth else 0
        dep_edges_count = len(self.dependency_graph.edges) if self.dependency_graph else 0

        return ActiveDatasetStatus(
            dataset_name=self.dataset_name,
            source_type=self.source_type,
            total_alerts=len(self.normalized_alerts),
            time_range_start=min_ts,
            time_range_end=max_ts,
            service_count=len(services),
            severity_breakdown=sev_counts,
            has_ground_truth=self.ground_truth is not None,
            ground_truth_incidents_count=gt_incidents_count,
            has_dependency_graph=self.dependency_graph is not None,
            dependency_edge_count=dep_edges_count,
            is_synthetic=self.is_synthetic
        )


# Global singleton instance for the FastAPI backend
app_state = AppState()
