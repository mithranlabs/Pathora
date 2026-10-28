"""Tests for origin hypotheses ranking and abstention logic."""

from datetime import datetime, timedelta, timezone
from backend.correlation.origin import rank_origin_hypotheses
from backend.models import NormalizedAlert, ServiceDependencyGraph


def make_alert(aid: str, offset_sec: int, svc: str, sev: str = "critical") -> NormalizedAlert:
    base_t = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    return NormalizedAlert(
        id=aid,
        timestamp=base_t + timedelta(seconds=offset_sec),
        service=svc,
        severity=sev,
        message=f"Alert on {svc}",
        source="test"
    )


def test_single_service_origin():
    alerts = [
        make_alert("a1", 0, "payment-gateway"),
        make_alert("a2", 30, "payment-gateway"),
    ]
    hypotheses = rank_origin_hypotheses(alerts)
    assert len(hypotheses) == 1
    assert hypotheses[0].service == "payment-gateway"
    assert hypotheses[0].is_undetermined is False
    assert hypotheses[0].score == 1.0


def test_temporal_precedence_and_dependency_identifies_root_cause():
    dep_graph = ServiceDependencyGraph(
        directed=True,
        edges=[["checkout-svc", "postgres-db"], ["api-gateway", "checkout-svc"]]
    )
    # postgres-db alerted at t=0; checkout at t=30; gateway at t=60
    alerts = [
        make_alert("db1", 0, "postgres-db", sev="warning"),  # Lower severity, but EARLIEST
        make_alert("chk1", 30, "checkout-svc", sev="error"),
        make_alert("gw1", 60, "api-gateway", sev="critical"),  # Highest severity, but LATEST symptom
    ]
    hypotheses = rank_origin_hypotheses(alerts, dep_graph)
    assert len(hypotheses) >= 1
    top = hypotheses[0]
    assert top.is_undetermined is False
    # Origin MUST be postgres-db based on temporal precedence and dependency, NOT api-gateway just because of critical severity!
    assert top.service == "postgres-db"
    assert any("First alert" in ev for ev in top.evidence)


def test_cyclic_deadlock_abstains():
    dep_graph = ServiceDependencyGraph(
        directed=True,
        edges=[
            ["recommendation-svc", "search-reranker"],
            ["search-reranker", "recommendation-svc"]  # Mutual cycle
        ]
    )
    # Both alert at the exact same second
    alerts = [
        make_alert("r1", 0, "recommendation-svc", sev="error"),
        make_alert("s1", 0, "search-reranker", sev="error"),
    ]
    hypotheses = rank_origin_hypotheses(alerts, dep_graph)
    assert len(hypotheses) == 1
    assert hypotheses[0].is_undetermined is True
    assert hypotheses[0].service is None
    assert any("Circular dependency detected" in ev for ev in hypotheses[0].evidence)
