"""Tests for FastAPI endpoints and state management."""

import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app import app
from backend.state import app_state

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "Pathora"
    assert "From alert noise to incident clarity." in data["tagline"]


def test_dataset_status_endpoint():
    response = client.get("/api/dataset/status")
    assert response.status_code == 200
    data = response.json()
    assert "total_alerts" in data
    assert data["total_alerts"] > 0
    assert data["source_type"] == "synthetic"
    assert data["is_synthetic"] is True


def test_load_synthetic_endpoint():
    payload = {"scale": "small", "seed": 99}
    response = client.post("/api/dataset/load-synthetic", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["total_alerts"] > 0
    assert data["is_synthetic"] is True


def test_get_alerts_pagination_and_filtering():
    # Fetch page 1
    response = client.get("/api/alerts?page=1&page_size=10")
    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert len(data["alerts"]) <= 10

    # Filter by severity
    crit_resp = client.get("/api/alerts?severity=critical")
    assert crit_resp.status_code == 200
    crit_data = crit_resp.json()
    for alert in crit_data["alerts"]:
        assert alert["severity"] == "critical"

    # Search filter
    search_resp = client.get("/api/alerts?search=postgres")
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    for alert in search_data["alerts"]:
        text_corpus = f"{alert['id']} {alert['service']} {alert['message']}".lower()
        assert "postgres" in text_corpus


def test_operation_without_labels_or_dependencies():
    # Ingest a CSV that has only raw alert columns and NO ground truth or dependencies
    raw_csv = (
        "id,timestamp,service,severity,message\n"
        "raw_01,2026-10-28T09:00:00Z,payment-svc,error,Connection refused\n"
        "raw_02,2026-10-28T09:01:00Z,payment-svc,critical,Out of memory\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(raw_csv)
        path = f.name

    resp = client.post("/api/dataset/load-file", json={"file_path": path})
    assert resp.status_code == 200
    status = resp.json()
    
    # Ground truth and dependencies must be safely absent without crashing
    assert status["has_ground_truth"] is False
    assert status["ground_truth_incidents_count"] == 0
    assert status["has_dependency_graph"] is False
    assert status["dependency_edge_count"] == 0
    assert status["total_alerts"] == 2

    # Alerts query still functions normally
    alerts_resp = client.get("/api/alerts")
    assert alerts_resp.status_code == 200
    assert alerts_resp.json()["total"] == 2

    Path(path).unlink()


def test_correlation_run_and_incidents_api():
    # 1. Trigger correlation run
    payload = {
        "algorithm": "improved",
        "time_window_sec": 900.0,
        "min_pair_score": 0.45
    }
    run_resp = client.post("/api/correlation/run", json=payload)
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["total_incidents"] > 0
    assert "run_id" in run_data

    # 2. Get active run
    active_resp = client.get("/api/correlation/runs/active")
    assert active_resp.status_code == 200
    active_data = active_resp.json()
    assert active_data["run_id"] == run_data["run_id"]

    # 3. List incidents
    inc_resp = client.get("/api/correlation/incidents")
    assert inc_resp.status_code == 200
    incidents = inc_resp.json()
    assert len(incidents) > 0
    first_inc = incidents[0]
    assert "incident_id" in first_inc
    assert "alert_ids" in first_inc
    assert len(first_inc["alert_ids"]) >= 2

    # 4. Get incident detail
    detail_resp = client.get(f"/api/correlation/incidents/{first_inc['incident_id']}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["incident"]["incident_id"] == first_inc["incident_id"]
    assert len(detail["alerts"]) == first_inc["alerts_count"]

    # 5. Get unattached alerts
    unattached_resp = client.get("/api/correlation/unattached")
    assert unattached_resp.status_code == 200
    unattached = unattached_resp.json()
    assert isinstance(unattached, list)

    # 6. Get evaluation scoreboard
    eval_resp = client.get("/api/correlation/evaluation")
    assert eval_resp.status_code == 200
    eval_data = eval_resp.json()
    assert "notification_reduction_rate" in eval_data
    assert "evaluation" in eval_data
    assert "baseline_evaluation" in eval_data

