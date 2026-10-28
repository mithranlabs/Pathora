# Pathora Data Contracts & Architectural Separation

**Product:** Pathora  
**Tagline:** *From alert noise to incident clarity.*

Pathora enforces strict isolation between raw external telemetry, normalized internal representations, and evaluation-only ground truth.

---

## 1. Architectural Separation of Concerns

```
┌────────────────────────────────┐
│   Raw Heterogeneous Input      │  (CSV, JSON, JSONL with arbitrary column names)
└───────────────┬────────────────┘
                │
                ▼ [Heuristic Field Mapping & Normalization Engine]
┌────────────────────────────────┐
│      NormalizedAlert           │  (Internal Canonical Contract)
└───────────────┬────────────────┘
                │
       [Correlation Engine] (Milestone 2)
                │
                ▼
┌────────────────────────────────┐
│     PredictedIncident          │  (Inferred Groups + Hypothesis Origins)
└───────────────┬────────────────┘
                │
                ▼ [Evaluation Harness] <─── [GroundTruthDataset] (Strictly isolated!)
┌────────────────────────────────┐
│     EvaluationResult           │  (Pairwise F1, BCubed, Swallow Rate)
└────────────────────────────────┘
```

### Separation Rules:
1. **Raw Input Alerts:** Contain arbitrary schemas. No field name is assumed.
2. **NormalizedAlerts:** The internal canonical schema. Raw attributes not matching the canonical schema are preserved intact in `attributes: Dict[str, Any]`.
3. **GroundTruthDataset:** Strictly quarantined in evaluation-only files (`*_ground_truth.json`). Never exposed to feature extraction or inference pipelines to prevent temporal or target leakage.
4. **ServiceDependencyGraph:** Optional input. When absent, Pathora operates in topology-blind mode without fabricating dependency scores.
5. **No Fabricated Scores:** If ground-truth labels are absent, the evaluation harness explicitly marks precision, recall, and recovery metrics as `UNAVAILABLE` rather than reporting manufactured numbers.

---

## 2. Canonical Model: `NormalizedAlert`

Located in [backend/models.py](file:///c:/Users/mithr/dev/hackmitten/backend/models.py):

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique canonical identifier for the alert. |
| `timestamp` | `datetime` | Parsed ISO 8601 UTC timestamp. |
| `timestamp_raw` | `Optional[str]` | Original unparsed timestamp string. |
| `service` | `Optional[str]` | Detected service or component name (defaults to `"unknown"` if absent). |
| `severity` | `str` | Normalized severity level: `critical`, `error`, `warning`, `info`, `unknown`. |
| `message` | `str` | Primary alert summary or error text. |
| `source` | `Optional[str]` | Originating telemetry tool (e.g. `prometheus`, `datadog`, `systemd`). |
| `host` | `Optional[str]` | Originating hostname, node, or pod if present. |
| `attributes` | `Dict[str, Any]` | Dictionary of all other unmapped original fields. |
| `is_synthetic` | `bool` | Explicit flag marking whether the record is synthetic pre-competition test data. |

---

## 3. Evaluation-Only Model: `GroundTruthDataset`

| Field | Type | Description |
|---|---|---|
| `dataset_name` | `str` | Name of the benchmark or dataset. |
| `is_synthetic` | `bool` | Must be `True` for generated fixtures. |
| `incidents` | `List[GroundTruthIncident]` | List of true incident groups with root cause service, alert IDs, and scenario notes. |
| `alert_to_incident`| `Dict[str, str]` | Mapping from `alert_id` to true `incident_id`. |
| `unassigned_alert_ids` | `List[str]` | Isolated background noise alerts that belong to no incident. |
| `assumptions` | `List[str]` | Explicit list of synthetic assumptions. |

---

## 4. Ingestion & Uncertainty Protocol

External files are ingested through [backend/ingestion.py](file:///c:/Users/mithr/dev/hackmitten/backend/ingestion.py) which:
1. Detects candidate columns by weighted fuzzy keyword matching.
2. Validates candidates by inspecting sample values (e.g., verifying timestamp parseability or severity keyword density).
3. Assigns an explicit confidence score ($0.0$ to $1.0$) and rationale to each inferred field.
4. Generates an inspection report highlighting field uncertainty and alternatives.
