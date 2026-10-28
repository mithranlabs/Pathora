"""FastAPI Application for Pathora.

Provides REST endpoints for:
- Health checks
- Active dataset status
- Synthetic data generation and loading
- Dataset reconnaissance profiles
- Paginated & filtered normalized alerts
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.models import (
    ActiveDatasetStatus,
    CorrelationConfig,
    CorrelationRunSummary,
    DatasetProfile,
    NormalizedAlert,
    PredictedIncident,
    UnattachedAlert,
)
from backend.state import app_state

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure small synthetic dataset is initialized upon server startup."""
    if not app_state.normalized_alerts:
        app_state.load_synthetic(scale="small", seed=42)
    yield

app = FastAPI(
    title="Pathora API",
    description="Alert-correlation and incident-viewing system. From alert noise to incident clarity.",
    version="0.1.0",
    lifespan=lifespan
)

# Enable CORS for Vite frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoadSyntheticRequest(BaseModel):
    scale: str = Field(default="small", description="'small' or 'eval'")
    seed: int = Field(default=42, description="Random seed for reproducibility")


class LoadFileRequest(BaseModel):
    file_path: str


class AlertsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    alerts: List[NormalizedAlert]


@app.get("/api/health")
def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "app": "Pathora",
        "tagline": "From alert noise to incident clarity.",
        "version": "0.1.0"
    }


@app.get("/api/dataset/status", response_model=ActiveDatasetStatus)
def get_dataset_status():
    """Get status and metadata of currently active dataset."""
    return app_state.get_status()


@app.get("/api/dataset/profile")
def get_dataset_profile():
    """Get detailed reconnaissance profile of the currently loaded dataset."""
    if not app_state.profile:
        raise HTTPException(status_code=404, detail="No dataset profile available.")
    return app_state.profile


@app.post("/api/dataset/load-synthetic", response_model=ActiveDatasetStatus)
def load_synthetic_dataset(req: LoadSyntheticRequest):
    """Generate and load synthetic dataset with configured scale and seed."""
    try:
        status = app_state.load_synthetic(scale=req.scale, seed=req.seed)
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load synthetic dataset: {str(e)}")


@app.post("/api/dataset/load-file", response_model=ActiveDatasetStatus)
def load_file(req: LoadFileRequest):
    """Load an external CSV, JSON, or JSONL file into active state."""
    try:
        status = app_state.load_file(req.file_path)
        return status
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error ingesting file: {str(e)}")


@app.get("/api/alerts", response_model=AlertsResponse)
def get_alerts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    severity: Optional[str] = Query(default=None),
    service: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None)
):
    """Retrieve normalized alerts with filtering and pagination."""
    alerts = app_state.normalized_alerts

    # Filter by severity
    if severity and severity.lower() != "all":
        alerts = [a for a in alerts if a.severity.lower() == severity.lower()]

    # Filter by service
    if service and service.lower() != "all":
        alerts = [a for a in alerts if a.service and a.service.lower() == service.lower()]

    # Filter by text search
    if search:
        s_lower = search.lower()
        alerts = [
            a for a in alerts
            if s_lower in a.message.lower() or s_lower in a.id.lower() or (a.service and s_lower in a.service.lower())
        ]

    # Sort chronologically by timestamp
    sorted_alerts = sorted(alerts, key=lambda a: a.timestamp)
    total = len(sorted_alerts)

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_items = sorted_alerts[start_idx:end_idx]

    return AlertsResponse(
        total=total,
        page=page,
        page_size=page_size,
        alerts=page_items
    )


# =============================================================================
# Milestone 2: Correlation, Incident Discovery & Evaluation Endpoints
# =============================================================================

@app.post("/api/correlation/run", response_model=CorrelationRunSummary)
def trigger_correlation_run(config: CorrelationConfig):
    """Trigger a correlation run using configured parameters."""
    if not app_state.normalized_alerts:
        raise HTTPException(status_code=400, detail="No alerts currently loaded in active dataset.")
    summary = app_state.execute_correlation(config)
    return summary


@app.get("/api/correlation/runs/active", response_model=CorrelationRunSummary)
def get_active_run():
    """Retrieve summary and evaluation metrics of the active correlation run."""
    summary = app_state.get_active_run_summary()
    if not summary:
        raise HTTPException(status_code=404, detail="No active correlation run found.")
    return summary


@app.get("/api/correlation/runs", response_model=List[CorrelationRunSummary])
def list_runs():
    """List all correlation runs executed in current session."""
    return list(app_state.runs.values())


@app.get("/api/correlation/incidents", response_model=List[PredictedIncident])
def get_run_incidents(run_id: Optional[str] = Query(default=None)):
    """List predicted incidents for active or specified run."""
    return app_state.get_run_incidents(run_id)


class IncidentDetailResponse(BaseModel):
    incident: PredictedIncident
    alerts: List[NormalizedAlert]


@app.get("/api/correlation/incidents/{incident_id}", response_model=IncidentDetailResponse)
def get_incident_detail(incident_id: str, run_id: Optional[str] = Query(default=None)):
    """Retrieve detailed incident record with full alert instances and evidence edges."""
    detail = app_state.get_incident_detail(incident_id, run_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")
    inc, alerts = detail
    return IncidentDetailResponse(incident=inc, alerts=alerts)


@app.get("/api/correlation/unattached", response_model=List[UnattachedAlert])
def get_run_unattached(run_id: Optional[str] = Query(default=None)):
    """List unattached singleton alerts for active or specified run."""
    return app_state.get_run_unattached(run_id)


@app.get("/api/correlation/evaluation")
def get_run_evaluation(run_id: Optional[str] = Query(default=None)):
    """Retrieve evaluation metrics and baseline comparison for active or specified run."""
    summary = app_state.get_active_run_summary() if not run_id else app_state.runs.get(run_id)
    if not summary:
        raise HTTPException(status_code=404, detail="No run summary available.")
    return {
        "run_id": summary.run_id,
        "algorithm": summary.algorithm,
        "is_synthetic": summary.is_synthetic,
        "total_alerts": summary.total_input_alerts,
        "total_incidents": summary.total_incidents,
        "notification_reduction_rate": summary.notification_reduction_rate,
        "evaluation": summary.evaluation,
        "baseline_evaluation": summary.baseline_evaluation
    }
