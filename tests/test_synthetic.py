"""Tests for synthetic data generator, ground-truth separation, and scenario coverage."""

from backend.models import NormalizedAlert
from backend.synthetic import SyntheticAlertGenerator


def test_deterministic_generation():
    gen1 = SyntheticAlertGenerator(seed=42)
    alerts1, gt1, dep1 = gen1.generate(scale="small")

    gen2 = SyntheticAlertGenerator(seed=42)
    alerts2, gt2, dep2 = gen2.generate(scale="small")

    # Exact equality of alert counts and contents
    assert len(alerts1) == len(alerts2)
    assert alerts1 == alerts2
    assert [i.incident_id for i in gt1.incidents] == [i.incident_id for i in gt2.incidents]
    assert dep1.edges == dep2.edges


def test_seed_variation():
    gen_a = SyntheticAlertGenerator(seed=100)
    alerts_a, _, _ = gen_a.generate(scale="small")

    gen_b = SyntheticAlertGenerator(seed=999)
    alerts_b, _, _ = gen_b.generate(scale="small")

    # Order or attributes should differ
    assert alerts_a != alerts_b


def test_ground_truth_separation_from_raw_features():
    gen = SyntheticAlertGenerator(seed=42)
    alerts, gt, dep = gen.generate(scale="small")

    # CRITICAL: Verify raw alerts contain NO ground truth incident labels
    for alert in alerts:
        assert "incident_id" not in alert
        assert "incident" not in alert
        assert "cluster_id" not in alert
        assert "root_cause" not in alert
        assert alert.get("is_synthetic") is True

    # Verify ground-truth dataset contains the evaluation mappings separately
    assert len(gt.incidents) >= 4
    assert len(gt.alert_to_incident) > 0

    # Ensure all incident alert_ids exist in the raw alert pool
    all_raw_ids = {a["alert_id"] for a in alerts}
    for inc in gt.incidents:
        for aid in inc.alert_ids:
            assert aid in all_raw_ids, f"Incident {inc.incident_id} references non-existent alert {aid}"


def test_scenario_coverage():
    gen = SyntheticAlertGenerator(seed=42)
    alerts, gt, dep = gen.generate(scale="small")

    scenarios = {inc.synthetic_scenario for inc in gt.incidents}
    assert "cascading_multi_service_failure" in scenarios
    assert "concurrent_unrelated_incident" in scenarios
    assert "high_volume_alert_storm" in scenarios
    assert "flapping_alerts" in scenarios
    assert "ambiguous_origin_cyclic_deadlock" in scenarios

    # Check unassigned noise alerts exist
    assert len(gt.unassigned_alert_ids) > 0


def test_dependency_graph_flaws():
    gen = SyntheticAlertGenerator(seed=42)
    _, _, dep = gen.generate(scale="small")

    # Verify graph contains expected cycle
    edge_set = {tuple(e) for e in dep.edges}
    assert ("recommendation-svc", "search-reranker") in edge_set
    assert ("search-reranker", "recommendation-svc") in edge_set

    # Verify stale / misleading edge is present
    assert ("inventory-svc", "auth-cache") in edge_set
