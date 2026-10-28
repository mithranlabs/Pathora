"""Data contracts and schemas for Pathora.

These models strictly separate:
1. Raw input records (untrusted, heterogeneous schema)
2. Normalized internal alerts (NormalizedAlert)
3. Evaluation-only ground truth (GroundTruthDataset, never mixed into prediction features)
4. Service dependency graphs (optional)
5. Dataset profiling and schema reconnaissance results
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FieldInference(BaseModel):
    """Represents a heuristically detected field mapping with uncertainty."""
    detected_column: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    alternatives: List[str] = Field(default_factory=list)
    rationale: str = ""


class FieldProfile(BaseModel):
    """Statistics for an individual field detected in raw data."""
    name: str
    detected_type: str
    non_null_count: int
    null_count: int
    unique_count: int
    sample_values: List[Any] = Field(default_factory=list)


class TimestampAnalysis(BaseModel):
    """Reconnaissance metrics regarding timestamps."""
    field_name: Optional[str] = None
    min_timestamp: Optional[datetime] = None
    max_timestamp: Optional[datetime] = None
    span_seconds: Optional[float] = None
    parse_failures: int = 0
    timezone_aware_count: int = 0
    timezone_naive_count: int = 0
    inferred_granularity: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


class DatasetProfile(BaseModel):
    """Full reconnaissance report of a raw dataset file."""
    source_path: str
    format: str  # csv, json, jsonl
    total_records: int
    valid_records: int
    malformed_records: int
    duplicate_records_exact: int
    potential_duplicate_alerts: int
    fields: Dict[str, FieldProfile] = Field(default_factory=dict)
    inferred_mappings: Dict[str, FieldInference] = Field(default_factory=dict)
    timestamp_analysis: TimestampAnalysis = Field(default_factory=TimestampAnalysis)
    service_distribution: Dict[str, int] = Field(default_factory=dict)
    severity_distribution: Dict[str, int] = Field(default_factory=dict)
    has_incident_labels: bool = False
    has_dependency_info: bool = False
    sanitized_samples: List[Dict[str, Any]] = Field(default_factory=list)
    is_synthetic: bool = False
    notes: List[str] = Field(default_factory=list)


class NormalizedAlert(BaseModel):
    """Internal canonical alert contract for Pathora.
    
    The ingestion layer is responsible for converting raw heterogeneous input
    into this contract. Unmapped fields are preserved in `attributes`.
    """
    id: str
    timestamp: datetime
    timestamp_raw: Optional[str] = None
    service: Optional[str] = "unknown"
    severity: str = "unknown"  # critical, error, warning, info, unknown
    message: str
    source: Optional[str] = "generic"
    host: Optional[str] = None
    fingerprint: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool = False


class ServiceDependencyGraph(BaseModel):
    """Optional service-dependency representation.
    
    Edges indicate (caller -> dependency) or (service -> depends_on).
    """
    directed: bool = True
    edges: List[List[str]] = Field(default_factory=list)  # [ [caller, dependency], ... ]
    nodes: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class GroundTruthIncident(BaseModel):
    """Evaluation-only record representing a ground-truth incident group.
    
    CRITICAL: This model is strictly separated from prediction features.
    """
    incident_id: str
    title: str
    root_cause_service: Optional[str] = None
    root_cause_alert_id: Optional[str] = None
    alert_ids: List[str] = Field(default_factory=list)
    synthetic_scenario: Optional[str] = None
    description: Optional[str] = None


class GroundTruthDataset(BaseModel):
    """Evaluation-only ground-truth container."""
    dataset_name: str
    is_synthetic: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    incidents: List[GroundTruthIncident] = Field(default_factory=list)
    unassigned_alert_ids: List[str] = Field(default_factory=list)
    alert_to_incident: Dict[str, str] = Field(default_factory=dict)
    generation_seed: Optional[int] = None
    assumptions: List[str] = Field(default_factory=list)


class ActiveDatasetStatus(BaseModel):
    """Summary of the currently loaded dataset in Pathora."""
    dataset_name: str
    source_type: str  # "synthetic" or "official"
    total_alerts: int
    time_range_start: Optional[datetime] = None
    time_range_end: Optional[datetime] = None
    service_count: int = 0
    severity_breakdown: Dict[str, int] = Field(default_factory=dict)
    has_ground_truth: bool = False
    ground_truth_incidents_count: int = 0
    has_dependency_graph: bool = False
    dependency_edge_count: int = 0
    is_synthetic: bool = True


# =============================================================================
# Milestone 2: Correlation, Incident Discovery & Evaluation Models
# =============================================================================

class CorrelationConfig(BaseModel):
    """Configuration parameters for correlation runs."""
    algorithm: str = Field(default="improved", description="'improved' (Architecture B) or 'baseline' (Architecture A)")
    time_window_sec: float = Field(default=900.0, description="Candidate gating window in seconds (15 min)")
    gap_threshold_sec: float = Field(default=300.0, description="Baseline consecutive alert gap threshold (5 min)")
    max_cluster_span_sec: float = Field(default=3600.0, description="Hard cap on total incident time span (1 hour)")
    min_pair_score: float = Field(default=0.45, description="Minimum pair score threshold to form correlation edge")
    w_time: float = Field(default=0.30, description="Weight for temporal proximity")
    w_text: float = Field(default=0.25, description="Weight for message/fingerprint similarity")
    w_service: float = Field(default=0.25, description="Weight for same service match")
    w_dependency: float = Field(default=0.20, description="Weight for service dependency graph adjacency")
    hub_degree_threshold: int = Field(default=4, description="Node degree above which service is penalized as a hub")


class PairEvidence(BaseModel):
    """Feature-level explainability breakdown for a correlated alert pair."""
    alert_id_a: str
    alert_id_b: str
    total_score: float
    time_score: float
    text_score: float
    service_score: float
    dependency_score: float
    delta_seconds: float
    rationale: str


class OriginHypothesis(BaseModel):
    """Ranked origin hypothesis for an incident cluster.
    
    CRITICAL: Hypotheses only, never asserted as proven root causes.
    """
    service: Optional[str] = None
    rank: int = 1
    score: float = 0.0
    is_undetermined: bool = False
    evidence: List[str] = Field(default_factory=list)


class PredictedIncident(BaseModel):
    """A discovered/correlated incident group."""
    incident_id: str
    title: str
    primary_severity: str = "unknown"
    start_time: datetime
    end_time: datetime
    span_seconds: float
    alert_ids: List[str] = Field(default_factory=list)
    alerts_count: int = 0
    services: List[str] = Field(default_factory=list)
    tentative: bool = False
    tentative_reason: Optional[str] = None
    origin_hypotheses: List[OriginHypothesis] = Field(default_factory=list)
    edges: List[PairEvidence] = Field(default_factory=list)


class UnattachedAlert(BaseModel):
    """An alert retained as singleton / unattached to any multi-alert incident."""
    alert: NormalizedAlert
    reason: str = "Unmatched singleton or below correlation threshold"


class EvaluationMetrics(BaseModel):
    """Leakage-safe evaluation results comparing predictions against ground truth."""
    available: bool = True
    pairwise_precision: Optional[float] = None
    pairwise_recall: Optional[float] = None
    pairwise_f1: Optional[float] = None
    bcubed_precision: Optional[float] = None
    bcubed_recall: Optional[float] = None
    bcubed_f1: Optional[float] = None
    total_ground_truth_incidents: Optional[int] = None
    recovered_incidents: Optional[int] = None
    fragmented_incidents: Optional[int] = None
    swallowed_incidents: Optional[int] = None
    swallow_rate: Optional[float] = None
    notification_reduction_rate: float = 0.0
    origin_top1_accuracy: Optional[float] = None
    origin_abstention_rate: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class CorrelationRunSummary(BaseModel):
    """Full summary of a correlation execution."""
    run_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    algorithm: str
    dataset_name: str
    is_synthetic: bool
    config: CorrelationConfig
    total_input_alerts: int
    total_incidents: int
    total_unattached_alerts: int
    tentative_incidents_count: int
    notification_reduction_rate: float
    evaluation: Optional[EvaluationMetrics] = None
    baseline_evaluation: Optional[EvaluationMetrics] = None

