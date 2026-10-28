"""Tests for baseline correlation engine (Architecture A)."""

from datetime import datetime, timedelta, timezone
from backend.correlation.baseline import (
    compute_alert_fingerprint,
    extract_message_template,
    run_baseline_correlation,
)
from backend.models import CorrelationConfig, NormalizedAlert


def make_alert(aid: str, offset_sec: int, svc: str, msg: str, src: str = "prom") -> NormalizedAlert:
    base_t = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    return NormalizedAlert(
        id=aid,
        timestamp=base_t + timedelta(seconds=offset_sec),
        service=svc,
        severity="critical",
        message=msg,
        source=src
    )


def test_extract_message_template_masks_variables():
    tmpl1 = extract_message_template("Max connection pool limit reached (500/500)")
    tmpl2 = extract_message_template("Max connection pool limit reached (100/100)")
    assert tmpl1 == tmpl2
    assert "<NUM>" in tmpl1


def test_baseline_groups_repeated_alerts_within_gap():
    alerts = [
        make_alert("a1", 0, "postgres-db", "Max connection pool limit reached (500/500)"),
        make_alert("a2", 60, "postgres-db", "Max connection pool limit reached (500/500)"),
        make_alert("a3", 120, "postgres-db", "Max connection pool limit reached (500/500)"),
    ]
    incidents, unattached = run_baseline_correlation(alerts, CorrelationConfig(gap_threshold_sec=300))
    assert len(incidents) == 1
    assert incidents[0].alerts_count == 3
    assert set(incidents[0].alert_ids) == {"a1", "a2", "a3"}
    assert len(unattached) == 0


def test_baseline_splits_when_gap_exceeds_threshold():
    alerts = [
        make_alert("a1", 0, "postgres-db", "Max connections 500"),
        make_alert("a2", 60, "postgres-db", "Max connections 500"),
        make_alert("a3", 800, "postgres-db", "Max connections 500"),  # Gap > 300s
        make_alert("a4", 860, "postgres-db", "Max connections 500"),
    ]
    incidents, unattached = run_baseline_correlation(alerts, CorrelationConfig(gap_threshold_sec=300))
    assert len(incidents) == 2
    assert incidents[0].alerts_count == 2
    assert incidents[1].alerts_count == 2
    assert len(unattached) == 0


def test_baseline_preserves_singletons_in_unattached():
    alerts = [
        make_alert("a1", 0, "postgres-db", "Max connections 500"),
        make_alert("a2", 60, "postgres-db", "Max connections 500"),
        make_alert("s1", 100, "cron-worker", "Singleton background notice"),  # isolated
    ]
    incidents, unattached = run_baseline_correlation(alerts)
    assert len(incidents) == 1
    assert len(unattached) == 1
    assert unattached[0].alert.id == "s1"

    # All alerts accounted for
    total_out = sum(len(inc.alert_ids) for inc in incidents) + len(unattached)
    assert total_out == len(alerts)
