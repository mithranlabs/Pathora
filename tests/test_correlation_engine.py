"""Tests for explainable correlation engine, feature scoring, and constrained clustering."""

from datetime import datetime, timedelta, timezone
from backend.correlation.engine import run_correlation
from backend.correlation.features import DependencyIndex, compute_text_similarity, score_pair
from backend.models import CorrelationConfig, NormalizedAlert, ServiceDependencyGraph


def make_alert(aid: str, offset_sec: int, svc: str, msg: str, sev: str = "critical") -> NormalizedAlert:
    base_t = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    return NormalizedAlert(
        id=aid,
        timestamp=base_t + timedelta(seconds=offset_sec),
        service=svc,
        severity=sev,
        message=msg,
        source="unit_test"
    )


def test_text_similarity_calculation():
    sim1 = compute_text_similarity("Payment processing transaction failed code 101", "Payment processing transaction failed code 102")
    assert sim1 > 0.6  # Number masked, keywords identical

    sim2 = compute_text_similarity("Kafka consumer group lag high", "Database connection pool saturated")
    assert sim2 < 0.2


def test_pair_scoring_breakdown_and_hub_penalty():
    dep_graph = ServiceDependencyGraph(
        directed=True,
        edges=[
            ["api-gateway", "checkout-svc"],
            ["checkout-svc", "postgres-db"],
            # api-gateway connected to 5 services -> hub!
            ["api-gateway", "auth-svc"],
            ["api-gateway", "billing-svc"],
            ["api-gateway", "inventory-svc"],
            ["api-gateway", "search-svc"]
        ]
    )
    dep_index = DependencyIndex(dep_graph)
    config = CorrelationConfig()

    a1 = make_alert("a1", 0, "postgres-db", "Connection pool exhausted")
    a2 = make_alert("a2", 30, "checkout-svc", "Database connection timeout")

    evidence = score_pair(a1, a2, config, dep_index)
    assert evidence.total_score >= 0.45
    assert evidence.dependency_score == 1.0
    assert "dependency" in evidence.rationale

    # Hub node gets hub penalty applied
    a_hub = make_alert("a_hub", 30, "api-gateway", "Upstream 504 timeout")
    hub_ev = score_pair(a2, a_hub, config, dep_index)
    assert hub_ev.dependency_score == 0.5  # 1.0 * 0.5 hub discount
    assert "hub penalty" in hub_ev.rationale


def test_cascading_failure_grouped():
    dep_graph = ServiceDependencyGraph(
        directed=True,
        edges=[["api-gateway", "checkout-svc"], ["checkout-svc", "postgres-db"]]
    )
    alerts = [
        make_alert("db1", 0, "postgres-db", "Max connection pool limit reached (500/500)"),
        make_alert("chk1", 45, "checkout-svc", "Database connection timeout after 3000ms"),
        make_alert("gw1", 90, "api-gateway", "Circuit breaker OPEN for service checkout-svc"),
    ]
    incidents, unattached = run_correlation(alerts, dep_graph)
    assert len(incidents) == 1
    assert incidents[0].alerts_count == 3
    assert set(incidents[0].services) == {"api-gateway", "checkout-svc", "postgres-db"}
    assert len(unattached) == 0


def test_concurrent_unrelated_incidents_remain_separated():
    dep_graph = ServiceDependencyGraph(
        directed=True,
        edges=[
            ["api-gateway", "checkout-svc"],
            ["checkout-svc", "postgres-db"],
            ["auth-svc", "auth-cache"]
        ]
    )
    # Incident 1 (Database cascade)
    db_alerts = [
        make_alert("db1", 0, "postgres-db", "Max connections reached"),
        make_alert("chk1", 30, "checkout-svc", "Database timeout"),
    ]
    # Incident 2 (Auth cache eviction occurring at the EXACT SAME time)
    auth_alerts = [
        make_alert("redis1", 5, "auth-cache", "Redis OOM: used_memory exceeded limit"),
        make_alert("auth1", 40, "auth-svc", "Cache miss rate for JWT tokens spiked"),
    ]

    all_alerts = db_alerts + auth_alerts
    incidents, unattached = run_correlation(all_alerts, dep_graph)

    # Must produce 2 separate incidents, NOT merge them into 1 giant cluster!
    assert len(incidents) == 2
    inc1_services = set(incidents[0].services)
    inc2_services = set(incidents[1].services)
    assert not (inc1_services & inc2_services), "Unrelated concurrent incidents were incorrectly merged!"


def test_max_span_cap_blocks_runaway_chaining():
    # Alerts spaced 200s apart over 4000s (> 3600s max span cap)
    alerts = []
    for i in range(20):
        alerts.append(make_alert(f"chain_{i}", i * 200, "worker-svc", "Worker memory pressure"))

    config = CorrelationConfig(max_cluster_span_sec=1800.0)  # 30 min cap
    incidents, _ = run_correlation(alerts, None, config)

    # Must be split into multiple clusters because total span exceeds 1800s
    assert len(incidents) >= 2
    for inc in incidents:
        assert inc.span_seconds <= 1800.0, f"Incident span {inc.span_seconds} exceeded max cap"
