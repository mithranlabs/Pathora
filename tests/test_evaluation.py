"""Tests for leakage-safe evaluation harness."""

from datetime import datetime, timezone
from backend.evaluation import evaluate_run
from backend.models import (
    GroundTruthDataset,
    GroundTruthIncident,
    NormalizedAlert,
    PredictedIncident,
    UnattachedAlert,
)


def make_alert(aid: str) -> NormalizedAlert:
    return NormalizedAlert(
        id=aid,
        timestamp=datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc),
        service="svc",
        message="test msg"
    )


def test_hand_verified_pairwise_and_bcubed_metrics():
    # Ground truth:
    # Incident 1: [a1, a2, a3]
    # Incident 2: [b1, b2]
    # Noise: [n1]
    gt = GroundTruthDataset(
        dataset_name="test_gt",
        incidents=[
            GroundTruthIncident(incident_id="GT_1", title="Inc 1", alert_ids=["a1", "a2", "a3"]),
            GroundTruthIncident(incident_id="GT_2", title="Inc 2", alert_ids=["b1", "b2"]),
        ],
        alert_to_incident={
            "a1": "GT_1", "a2": "GT_1", "a3": "GT_1",
            "b1": "GT_2", "b2": "GT_2"
        }
    )

    # Predictions:
    # Predicted Incident 1: [a1, a2] (missed a3 -> fragmentation)
    # Predicted Incident 2: [b1, b2] (perfect)
    # Unattached: [a3, n1]
    p_inc1 = PredictedIncident(
        incident_id="P1",
        title="Pred 1",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        span_seconds=10,
        alert_ids=["a1", "a2"],
        alerts_count=2
    )
    p_inc2 = PredictedIncident(
        incident_id="P2",
        title="Pred 2",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        span_seconds=10,
        alert_ids=["b1", "b2"],
        alerts_count=2
    )
    unattached = [
        UnattachedAlert(alert=make_alert("a3")),
        UnattachedAlert(alert=make_alert("n1")),
    ]

    metrics = evaluate_run([p_inc1, p_inc2], unattached, gt, total_alerts=6)
    assert metrics.available is True
    # True positive pairs: (a1, a2) in GT_1; (b1, b2) in GT_2 -> 2 pairs
    # False positive pairs: 0 pairs (no false merges)
    # False negative pairs: (a1, a3), (a2, a3) -> 2 pairs
    # Precision = 2 / (2 + 0) = 1.0
    # Recall = 2 / (2 + 2) = 0.5
    # F1 = 2 * 1 * 0.5 / 1.5 = 0.6667
    assert metrics.pairwise_precision == 1.0
    assert metrics.pairwise_recall == 0.5
    assert round(metrics.pairwise_f1, 2) == 0.67
    assert metrics.recovered_incidents == 1  # GT_2 is 100% recovered; GT_1 has 66.7% (<70%) so not fully recovered
    assert metrics.fragmented_incidents == 1
    assert metrics.swallowed_incidents == 0
    assert metrics.swallow_rate == 0.0


def test_swallow_false_merge_detection():
    # Ground truth: 2 independent incidents
    gt = GroundTruthDataset(
        dataset_name="test_gt",
        incidents=[
            GroundTruthIncident(incident_id="GT_A", title="Inc A", alert_ids=["a1", "a2"]),
            GroundTruthIncident(incident_id="GT_B", title="Inc B", alert_ids=["b1", "b2"]),
        ],
        alert_to_incident={"a1": "GT_A", "a2": "GT_A", "b1": "GT_B", "b2": "GT_B"}
    )
    # Prediction: merged everything into 1 big cluster!
    merged_inc = PredictedIncident(
        incident_id="P_MERGED",
        title="Merged",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        span_seconds=10,
        alert_ids=["a1", "a2", "b1", "b2"],
        alerts_count=4
    )
    metrics = evaluate_run([merged_inc], [], gt, total_alerts=4)
    # FP pairs: (a1,b1), (a1,b2), (a2,b1), (a2,b2) = 4 FP pairs
    assert metrics.pairwise_precision < 0.5
    # Both GT_A and GT_B were swallowed into 1 cluster
    assert metrics.swallowed_incidents >= 1
    assert metrics.swallow_rate > 0.0


def test_missing_ground_truth_marks_unavailable():
    metrics = evaluate_run([], [], None, total_alerts=10)
    assert metrics.available is False
    assert metrics.pairwise_f1 is None
    assert metrics.recovered_incidents is None
    assert any("UNAVAILABLE" in note for note in metrics.notes)
