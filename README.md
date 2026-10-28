# Pathora

> **"From alert noise to incident clarity."**

Deterministic alert-correlation, incident-discovery, and telemetry reconnaissance platform.

---

## 1. Overview & Current Milestone Status

Pathora is engineered to operate under **zero-assumption conditions**:
- **Dataset Agnostic:** Ingests heterogeneous CSV, JSON, and JSONL inputs without assuming official column names.
- **Explainable Correlation Engine (Architecture B):** Multi-signal pairwise scoring combining exponential temporal decay, lexical token similarity, same-service alignment, and service-dependency topology with hub-degree protection.
- **Constrained Clustering:** Average-linkage clustering bounded by a hard time span cap (default 1 hour) to prevent runaway transitive chaining.
- **Ranked Origin Hypotheses:** Evaluates candidate origin services using temporal precedence and directed topology. Explicitly abstains ("Undetermined") on circular deadlocks or statistical ties. Severity is never used as an origin signal.
- **Unsupervised Fallback:** Functions completely without ground-truth incident labels or service dependency graphs.
- **Strict Leakage Isolation:** Evaluation code is strictly separated from prediction. Ground truth is never visible to feature extraction or clustering.
- **Zero Paid Dependencies:** Runs on Python 3.14+ (FastAPI), React 19 (Vite), and in-memory state. No databases, no external LLM APIs, no Docker.

---

## 2. Project Directory Tree

```
hackmitten/
├── .gitignore                          # Excludes venv, build artifacts, and official data
├── README.md                           # Setup, run, and architecture guide
├── SignalFuse (AO-01) System Design.md # Preserved preliminary research & system design
├── backend/
│   ├── __init__.py
│   ├── app.py                          # FastAPI REST endpoints & lifespan startup
│   ├── evaluation.py                   # Pairwise, BCubed, swallow rate & origin evaluation
│   ├── ingestion.py                    # CSV/JSON/JSONL parser, heuristics, normalization
│   ├── inspect_cli.py                  # Dataset Reconnaissance CLI tool
│   ├── inspector.py                    # Schema profiler, duplicate & temporal analysis
│   ├── models.py                       # Data contracts (NormalizedAlert, Incidents, Evaluation)
│   ├── state.py                        # Active state store & run manager
│   ├── synthetic.py                    # Deterministic multi-scenario synthetic generator
│   └── correlation/
│       ├── __init__.py
│       ├── baseline.py                 # Architecture A: Fingerprint & time gap baseline
│       ├── engine.py                   # Architecture B: Gated pair scoring & constrained clustering
│       ├── features.py                 # Multi-signal feature scoring & explainable evidence
│       └── origin.py                   # Ranked origin hypotheses & abstention logic
├── data/
│   └── synthetic/                      # Generated deterministic test fixtures
│       ├── synthetic_small_alerts.json
│       ├── synthetic_small_alerts.csv
│       ├── synthetic_small_alerts.jsonl
│       ├── synthetic_small_ground_truth.json
│       ├── synthetic_small_dependencies.json
│       ├── synthetic_eval_alerts.json
│       ├── synthetic_eval_ground_truth.json
│       └── synthetic_eval_dependencies.json
├── docs/
│   ├── DATA_CONTRACTS.md               # Contract definitions & ground truth isolation
│   └── SYNTHETIC_DATA.md               # Scenario documentation & synthetic assumptions
├── frontend/
│   ├── package.json
│   ├── vite.config.js                  # Vite config with backend proxy on /api
│   ├── index.html                      # Pathora application shell
│   └── src/
│       ├── App.jsx                     # Dashboard (Incidents + Scoreboard + Alerts + Recon)
│       ├── index.css                   # Modern dark design system
│       └── main.jsx
└── tests/
    ├── test_api.py                     # Health, dataset, alerts, and correlation run endpoints
    ├── test_baseline.py                # Fingerprint normalization, time gap splitting, singletons
    ├── test_correlation_engine.py      # Gating window, features, hub penalty, cascading failure
    ├── test_evaluation.py              # Pairwise F1, BCubed, swallow rate, unavailable handling
    ├── test_ingestion.py               # CSV/JSON/JSONL parsing, missing fields, duplicates
    ├── test_invariants.py              # 1-to-1 alert preservation, no duplicate IDs, messy input
    ├── test_origin.py                  # Precedence scoring, cyclic deadlock abstention
    ├── test_synthetic.py               # Deterministic seed, scenarios, ground truth isolation
    └── test_timestamps.py              # ISO, timezone awareness, epoch seconds/ms parsing
```

---

## 3. Windows PowerShell Setup & Run Commands

### Step 1: Clone or Navigate to the Workspace
```powershell
cd c:\Users\mithr\dev\hackmitten
```

### Step 2: Python Environment Setup
```powershell
# Create virtual environment (if not already created)
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install backend dependencies
pip install fastapi uvicorn pydantic pytest python-dateutil httpx
```

### Step 3: Frontend Environment Setup
```powershell
cd frontend
npm install
npm install @rolldown/binding-win32-x64-msvc --os=win32 --cpu=x64
cd ..
```

### Step 4: Run Automated Tests
```powershell
.\.venv\Scripts\python -m pytest -v
```
*(All 39 automated tests pass in ~0.6s)*

### Step 5: Start the Applications

**Terminal 1 — FastAPI Backend (port 8000):**
```powershell
.\.venv\Scripts\python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 — Vite React Frontend (port 5173):**
```powershell
cd frontend
npm run dev
```

Open your browser to: **`http://localhost:5173`**

---

## 4. Triggering Correlation via CLI & API

### Run Correlation via REST API:
```powershell
# Run Architecture B (Improved Engine)
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/correlation/run -Method POST -ContentType "application/json" -Body '{"algorithm":"improved","time_window_sec":900,"min_pair_score":0.45,"max_cluster_span_sec":3600}'

# Run Architecture A (Baseline)
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/correlation/run -Method POST -ContentType "application/json" -Body '{"algorithm":"baseline","gap_threshold_sec":300}'

# Fetch Evaluation Scoreboard
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/correlation/evaluation
```

---

## 5. Measured Scoreboard Results (Architecture B vs Baseline)

Measured on the default synthetic benchmark (41 alerts across 5 known incidents and 3 noise singletons):

| Evaluation Metric | Architecture B (Improved Engine) | Architecture A (Baseline) | Metric Description |
|---|---|---|---|
| **Noise Reduction Rate** | **80.5%** | 39.0% | Consolidation of raw alerts into incident notifications |
| **Pairwise F1 Score** | **89.7%** | 43.2% | Harmonic mean of pairwise precision and recall |
| **Pairwise Precision** | 81.3% | **97.6%** | Purity of correlated alert pairs |
| **Pairwise Recall** | **100.0%** | 27.7% | Recovery of true cascading cross-service pairs |
| **BCubed F1 Score** | **89.0%** | 62.1% | Element-level clustering metric |
| **Swallow / False-Merge Rate** | 20.0% | **0.0%** | Rate of independent incidents absorbed into one cluster |
| **Origin Top-1 Accuracy** | **100.0%** | 60.0% | Accuracy on non-ambiguous ground truth incidents |

> [!NOTE]
> When ground-truth labels are absent, Pathora automatically reports pairwise metrics as `UNAVAILABLE` rather than fabricating numbers.

---

## 6. Actual Test Results

```
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.2.0, pluggy-1.7.0
rootdir: C:\Users\mithr\dev\hackmitten
collected 39 items

tests/test_api.py::test_health_endpoint PASSED                           [  2%]
tests/test_api.py::test_dataset_status_endpoint PASSED                   [  5%]
tests/test_api.py::test_load_synthetic_endpoint PASSED                   [  7%]
tests/test_api.py::test_get_alerts_pagination_and_filtering PASSED       [ 10%]
tests/test_api.py::test_operation_without_labels_or_dependencies PASSED  [ 12%]
tests/test_api.py::test_correlation_run_and_incidents_api PASSED         [ 15%]
tests/test_baseline.py::test_extract_message_template_masks_variables PASSED [ 17%]
tests/test_baseline.py::test_baseline_groups_repeated_alerts_within_gap PASSED [ 20%]
tests/test_baseline.py::test_baseline_splits_when_gap_exceeds_threshold PASSED [ 23%]
tests/test_baseline.py::test_baseline_preserves_singletons_in_unattached PASSED [ 25%]
tests/test_correlation_engine.py::test_text_similarity_calculation PASSED [ 28%]
tests/test_correlation_engine.py::test_pair_scoring_breakdown_and_hub_penalty PASSED [ 30%]
tests/test_correlation_engine.py::test_cascading_failure_grouped PASSED  [ 33%]
tests/test_correlation_engine.py::test_concurrent_unrelated_incidents_remain_separated PASSED [ 35%]
tests/test_correlation_engine.py::test_max_span_cap_blocks_runaway_chaining PASSED [ 38%]
tests/test_evaluation.py::test_hand_verified_pairwise_and_bcubed_metrics PASSED [ 41%]
tests/test_evaluation.py::test_swallow_false_merge_detection PASSED      [ 43%]
tests/test_evaluation.py::test_missing_ground_truth_marks_unavailable PASSED [ 46%]
tests/test_ingestion.py::test_parse_csv_file PASSED                      [ 48%]
tests/test_ingestion.py::test_parse_json_file PASSED                     [ 51%]
tests/test_ingestion.py::test_parse_jsonl_file PASSED                    [ 53%]
tests/test_ingestion.py::test_missing_fields_and_fallbacks PASSED        [ 56%]
tests/test_ingestion.py::test_exact_and_potential_duplicate_detection PASSED [ 58%]
tests/test_ingestion.py::test_severity_normalization PASSED              [ 61%]
tests/test_invariants.py::test_invariants_on_messy_input PASSED          [ 64%]
tests/test_origin.py::test_single_service_origin PASSED                  [ 66%]
tests/test_origin.py::test_temporal_precedence_and_dependency_identifies_root_cause PASSED [ 69%]
tests/test_origin.py::test_cyclic_deadlock_abstains PASSED               [ 71%]
tests/test_synthetic.py::test_deterministic_generation PASSED            [ 74%]
tests/test_synthetic.py::test_seed_variation PASSED                      [ 76%]
tests/test_synthetic.py::test_ground_truth_separation_from_raw_features PASSED [ 79%]
tests/test_synthetic.py::test_scenario_coverage PASSED                   [ 82%]
tests/test_synthetic.py::test_dependency_graph_flaws PASSED              [ 84%]
tests/test_timestamps.py::test_iso_timestamp_parsing PASSED              [ 87%]
tests/test_timestamps.py::test_iso_with_explicit_offset PASSED           [ 89%]
tests/test_timestamps.py::test_timezone_naive_conversion PASSED          [ 92%]
tests/test_timestamps.py::test_epoch_seconds_parsing PASSED              [ 94%]
tests/test_timestamps.py::test_epoch_milliseconds_parsing PASSED         [ 97%]
tests/test_timestamps.py::test_invalid_timestamps PASSED                 [100%]

======================== 39 passed in 0.59s ========================
```
