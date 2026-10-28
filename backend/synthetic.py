"""Deterministic synthetic alert generator for Pathora.

Generates realistic alert scenarios without assuming official dataset availability:
- Repeated alerts from same source
- Cascading multi-service failures
- Concurrent unrelated incidents
- High-volume alert storms
- Flapping alerts
- Delayed & out-of-order timestamps
- Missing service names, timestamps, or optional fields
- Unrelated singleton noise
- Incomplete / misleading dependency information
- Ambiguous origin cases

Strictly isolates ground-truth labels and dependency topology into separate evaluation structures.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.models import (
    GroundTruthDataset,
    GroundTruthIncident,
    ServiceDependencyGraph,
)


class SyntheticAlertGenerator:
    """Deterministic generator for synthetic alerts and ground truth."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)

    def generate(
        self,
        base_time: Optional[datetime] = None,
        scale: str = "small"  # "small" (~40 alerts) or "eval" (~250 alerts)
    ) -> Tuple[List[Dict[str, Any]], GroundTruthDataset, ServiceDependencyGraph]:
        """Generate synthetic alerts, evaluation-only ground truth, and dependency graph."""
        self.rng = random.Random(self.seed)

        if base_time is None:
            base_time = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

        raw_alerts: List[Dict[str, Any]] = []
        incidents: List[GroundTruthIncident] = []
        alert_to_incident: Dict[str, str] = {}
        unassigned_alerts: List[str] = []

        alert_counter = 0

        def create_alert(
            ts_offset_sec: int,
            service: Optional[str],
            severity: str,
            message: str,
            source: Optional[str] = "prometheus",
            host: Optional[str] = None,
            extra: Optional[Dict[str, Any]] = None,
            corrupt_ts: bool = False
        ) -> Dict[str, Any]:
            nonlocal alert_counter
            alert_counter += 1
            alert_id = f"synth_{alert_counter:05d}"
            
            ts = base_time + timedelta(seconds=ts_offset_sec)
            ts_str = ts.isoformat() if not corrupt_ts else "INVALID_DATE"

            rec: Dict[str, Any] = {
                "alert_id": alert_id,
                "timestamp": ts_str,
                "service": service,
                "severity": severity,
                "message": message,
                "source": source,
                "host": host or f"node-{self.rng.randint(1, 10)}",
                "is_synthetic": True
            }
            if extra:
                rec.update(extra)
            return rec

        # =========================================================================
        # Scenario 1: Cascading Multi-Service Failure (Incident INC-001)
        # Root cause: postgres-db connection exhaustion -> checkout-svc 500s -> api-gateway 504
        # =========================================================================
        inc1_alerts = []
        # DB alerts
        a1 = create_alert(0, "postgres-db", "critical", "Max connection pool limit reached (500/500)", source="pg_exporter")
        a2 = create_alert(15, "postgres-db", "critical", "Query latency > 4500ms on table 'orders'", source="pg_exporter")
        # Downstream checkout-svc affected
        a3 = create_alert(45, "checkout-svc", "error", "Database connection timeout after 3000ms", source="app_metrics")
        a4 = create_alert(60, "checkout-svc", "critical", "HTTP 500 error rate spiked to 34%", source="app_metrics")
        # Downstream api-gateway affected
        a5 = create_alert(90, "api-gateway", "warning", "Upstream checkout-svc responded with HTTP 504", source="ingress_controller")
        a6 = create_alert(120, "api-gateway", "error", "Circuit breaker OPEN for service 'checkout-svc'", source="ingress_controller")
        
        for a in [a1, a2, a3, a4, a5, a6]:
            raw_alerts.append(a)
            inc1_alerts.append(a["alert_id"])
            alert_to_incident[a["alert_id"]] = "INC-001"

        incidents.append(GroundTruthIncident(
            incident_id="INC-001",
            title="Database Connection Exhaustion Cascading to Checkout and Gateway",
            root_cause_service="postgres-db",
            root_cause_alert_id=a1["alert_id"],
            alert_ids=inc1_alerts,
            synthetic_scenario="cascading_multi_service_failure",
            description="Postgres connection pool saturation caused checkout service timeouts and gateway circuit breaker trip."
        ))

        # =========================================================================
        # Scenario 2: Concurrent Unrelated Incident (Incident INC-002)
        # Occurring simultaneously with Incident 1, but completely unrelated
        # Root cause: auth-cache redis node out-of-memory
        # =========================================================================
        inc2_alerts = []
        b1 = create_alert(30, "auth-cache", "critical", "Redis OOM: used_memory exceeded maxmemory limit (4GB)", source="redis_exporter")
        b2 = create_alert(50, "auth-cache", "error", "Keys eviction rate spike: 12,000 evictions/sec", source="redis_exporter")
        b3 = create_alert(80, "auth-svc", "warning", "Cache miss rate for JWT session tokens jumped to 88%", source="datadog")
        b4 = create_alert(110, "auth-svc", "error", "Authentication validation latency > 2000ms", source="datadog")

        for b in [b1, b2, b3, b4]:
            raw_alerts.append(b)
            inc2_alerts.append(b["alert_id"])
            alert_to_incident[b["alert_id"]] = "INC-002"

        incidents.append(GroundTruthIncident(
            incident_id="INC-002",
            title="Auth Redis Cache Eviction Storm",
            root_cause_service="auth-cache",
            root_cause_alert_id=b1["alert_id"],
            alert_ids=inc2_alerts,
            synthetic_scenario="concurrent_unrelated_incident",
            description="Independent Redis OOM in auth cluster running concurrently with database checkout incident."
        ))

        # =========================================================================
        # Scenario 3: High-Volume Alert Storm (Incident INC-003)
        # 15 alerts generated in quick succession
        # Root cause: payment-gateway external TLS handshake failures
        # =========================================================================
        storm_multiplier = 4 if scale == "eval" else 1
        inc3_alerts = []
        c_root = create_alert(300, "payment-gateway", "critical", "External partner TLS certificate validation failed: expired cert", source="cert_checker")
        raw_alerts.append(c_root)
        inc3_alerts.append(c_root["alert_id"])
        alert_to_incident[c_root["alert_id"]] = "INC-003"

        for i in range(1, 15 * storm_multiplier):
            sec_offset = 300 + (i * 4) + self.rng.randint(0, 3)
            storm_svc = self.rng.choice(["payment-gateway", "billing-svc", "settlement-svc"])
            sev = self.rng.choice(["critical", "error"])
            storm_alert = create_alert(
                sec_offset,
                storm_svc,
                sev,
                f"Payment processing transaction failed: handshake abort code={1000 + i}",
                source="payment_engine"
            )
            raw_alerts.append(storm_alert)
            inc3_alerts.append(storm_alert["alert_id"])
            alert_to_incident[storm_alert["alert_id"]] = "INC-003"

        incidents.append(GroundTruthIncident(
            incident_id="INC-003",
            title="Payment TLS Certificate Expiration Storm",
            root_cause_service="payment-gateway",
            root_cause_alert_id=c_root["alert_id"],
            alert_ids=inc3_alerts,
            synthetic_scenario="high_volume_alert_storm",
            description="Sudden burst of payment failures across multiple financial services caused by expired vendor cert."
        ))

        # =========================================================================
        # Scenario 4: Flapping Alerts & Repeated Alerts (Incident INC-004)
        # Service flapping between critical and warning over 10 minutes
        # =========================================================================
        inc4_alerts = []
        for step, offset in enumerate([500, 560, 620, 680, 740, 800]):
            sev = "critical" if step % 2 == 0 else "warning"
            d = create_alert(
                offset,
                "inventory-svc",
                sev,
                f"Kafka consumer group lag {'exceeded 50,000 messages' if sev == 'critical' else 'recovered under threshold'}",
                source="kafka_monitor"
            )
            raw_alerts.append(d)
            inc4_alerts.append(d["alert_id"])
            alert_to_incident[d["alert_id"]] = "INC-004"

        incidents.append(GroundTruthIncident(
            incident_id="INC-004",
            title="Inventory Kafka Consumer Flapping Lag",
            root_cause_service="inventory-svc",
            root_cause_alert_id=inc4_alerts[0],
            alert_ids=inc4_alerts,
            synthetic_scenario="flapping_alerts",
            description="Oscillating consumer lag firing repeated warning and critical alerts."
        ))

        # =========================================================================
        # Scenario 5: Ambiguous Origin Case (Incident INC-005)
        # Microservices A & B in a tight loop, alerting at the identical second
        # =========================================================================
        inc5_alerts = []
        e1 = create_alert(1000, "recommendation-svc", "error", "RPC Deadlock detected with search-reranker", source="grpc_interceptor")
        e2 = create_alert(1000, "search-reranker", "error", "RPC Deadlock detected with recommendation-svc", source="grpc_interceptor")
        for e in [e1, e2]:
            raw_alerts.append(e)
            inc5_alerts.append(e["alert_id"])
            alert_to_incident[e["alert_id"]] = "INC-005"

        incidents.append(GroundTruthIncident(
            incident_id="INC-005",
            title="Circular Dependency RPC Deadlock Between Recommendations and Search",
            root_cause_service=None,  # Intentionally ambiguous / undetermined
            root_cause_alert_id=None,
            alert_ids=inc5_alerts,
            synthetic_scenario="ambiguous_origin_cyclic_deadlock",
            description="Both services alerted at the identical second with circular dependencies; true origin is ambiguous."
        ))

        # =========================================================================
        # Scenario 6: Delayed and Out-of-Order Alerts
        # A delayed alert from an earlier failure reported much later
        # =========================================================================
        delayed_alert = create_alert(
            ts_offset_sec=120,  # Fired at t=120, but we will place it later in file
            service="checkout-svc",
            severity="warning",
            message="Slow query log entry ingested with 15-minute reporter delay",
            source="cloudwatch_delayed_log"
        )
        raw_alerts.append(delayed_alert)
        inc1_alerts.append(delayed_alert["alert_id"])
        alert_to_incident[delayed_alert["alert_id"]] = "INC-001"

        # =========================================================================
        # Scenario 7: Malformed / Missing Fields
        # Missing service, missing timestamp, or corrupted fields
        # =========================================================================
        # Missing service name
        missing_svc = create_alert(
            1100,
            service=None,
            severity="warning",
            message="Host kernel memory pressure threshold reached",
            source="node_exporter"
        )
        raw_alerts.append(missing_svc)
        unassigned_alerts.append(missing_svc["alert_id"])

        # Corrupt timestamp
        corrupt_ts = create_alert(
            1120,
            service="analytics-pipeline",
            severity="info",
            message="Daily aggregations scheduled task started",
            corrupt_ts=True
        )
        raw_alerts.append(corrupt_ts)
        unassigned_alerts.append(corrupt_ts["alert_id"])

        # =========================================================================
        # Scenario 8: Unrelated Singleton Background Noise (No Incident)
        # =========================================================================
        singleton_count = 20 if scale == "eval" else 5
        for s_idx in range(singleton_count):
            s_time = self.rng.randint(10, 1200)
            s_svc = self.rng.choice(["cron-worker", "email-sender", "backup-daemon", "dns-resolver"])
            s_sev = self.rng.choice(["info", "warning"])
            s_msg = f"Routine background notice: job {s_idx + 100} finished with exit_code=0"
            singleton = create_alert(s_time, s_svc, s_sev, s_msg, source="systemd")
            raw_alerts.append(singleton)
            unassigned_alerts.append(singleton["alert_id"])

        # Additional alerts for 'eval' scale to reach ~250 records
        if scale == "eval":
            for ext_i in range(120):
                ext_time = self.rng.randint(50, 1500)
                ext_svc = self.rng.choice(["checkout-svc", "auth-svc", "inventory-svc", "billing-svc", "postgres-db"])
                ext_sev = self.rng.choice(["warning", "info", "error"])
                ext_msg = f"Metric oscillation: memory_utilization={self.rng.randint(60, 95)}%"
                ext_alert = create_alert(ext_time, ext_svc, ext_sev, ext_msg, source="datadog")
                raw_alerts.append(ext_alert)
                unassigned_alerts.append(ext_alert["alert_id"])

        # Intentionally shuffle order of alerts to simulate real-world arrival / out-of-order logs
        # but seed-controlled
        self.rng.shuffle(raw_alerts)

        # =========================================================================
        # Synthetic Dependency Graph (with incomplete and misleading edge)
        # =========================================================================
        dependency_edges = [
            ["api-gateway", "checkout-svc"],
            ["checkout-svc", "postgres-db"],
            ["api-gateway", "auth-svc"],
            ["auth-svc", "auth-cache"],
            ["billing-svc", "payment-gateway"],
            ["settlement-svc", "billing-svc"],
            ["recommendation-svc", "search-reranker"],
            ["search-reranker", "recommendation-svc"],  # Cycle
            # Misleading edge:
            ["inventory-svc", "auth-cache"],  # Misleading stale dependency
        ]
        all_nodes = sorted(list(set(n for edge in dependency_edges for n in edge)))
        dep_graph = ServiceDependencyGraph(
            directed=True,
            edges=dependency_edges,
            nodes=all_nodes,
            notes="Synthetic dependency graph. Note: contains circular dependency and a stale edge (inventory-svc -> auth-cache)."
        )

        gt_dataset = GroundTruthDataset(
            dataset_name=f"synthetic_{scale}_v1",
            is_synthetic=True,
            incidents=incidents,
            unassigned_alert_ids=unassigned_alerts,
            alert_to_incident=alert_to_incident,
            generation_seed=self.seed,
            assumptions=[
                "Deterministic generation using fixed pseudo-random seed.",
                "Simulates 5 distinct incident patterns: cascading failure, concurrent independent incident, storm, flapping, ambiguous cyclic deadlock.",
                "Simulates dirty data: corrupt timestamps, missing service names, and delayed arrival.",
                "Ground-truth incident labels are strictly evaluation-only and omitted from input files.",
                "Service dependency graph includes known real-world flaws: circular calls and misleading edges."
            ]
        )

        return raw_alerts, gt_dataset, dep_graph


def save_synthetic_dataset(
    output_dir: Union[str, Path],
    scale: str = "small",
    seed: int = 42
) -> Dict[str, str]:
    """Generate and save synthetic files (alerts, evaluation ground-truth, dependency graph).
    
    Returns:
        dict of file paths saved
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    generator = SyntheticAlertGenerator(seed=seed)
    raw_alerts, ground_truth, dep_graph = generator.generate(scale=scale)

    alerts_json = out_path / f"synthetic_{scale}_alerts.json"
    alerts_csv = out_path / f"synthetic_{scale}_alerts.csv"
    alerts_jsonl = out_path / f"synthetic_{scale}_alerts.jsonl"
    gt_file = out_path / f"synthetic_{scale}_ground_truth.json"
    dep_file = out_path / f"synthetic_{scale}_dependencies.json"

    # 1. JSON
    with open(alerts_json, "w", encoding="utf-8") as f:
        json.dump(raw_alerts, f, indent=2)

    # 2. JSONL
    with open(alerts_jsonl, "w", encoding="utf-8") as f:
        for a in raw_alerts:
            f.write(json.dumps(a) + "\n")

    # 3. CSV
    if raw_alerts:
        keys = list(raw_alerts[0].keys())
        import csv
        with open(alerts_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for a in raw_alerts:
                writer.writerow(a)

    # 4. Evaluation Ground Truth (Separated!)
    with open(gt_file, "w", encoding="utf-8") as f:
        f.write(ground_truth.model_dump_json(indent=2))

    # 5. Dependency Graph
    with open(dep_file, "w", encoding="utf-8") as f:
        f.write(dep_graph.model_dump_json(indent=2))

    return {
        "alerts_json": str(alerts_json),
        "alerts_csv": str(alerts_csv),
        "alerts_jsonl": str(alerts_jsonl),
        "ground_truth": str(gt_file),
        "dependencies": str(dep_file)
    }
