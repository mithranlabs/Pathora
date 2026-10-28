"""Deterministic baseline correlation engine for Pathora (Architecture A).

Groups alerts sharing the same normalized fingerprint within a bounded consecutive time gap.
Does NOT assume ground-truth labels. Enforces complete alert preservation and invariants.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.models import (
    CorrelationConfig,
    NormalizedAlert,
    OriginHypothesis,
    PredictedIncident,
    UnattachedAlert,
)


def extract_message_template(message: str) -> str:
    """Normalize volatile tokens (numbers, hex IDs, codes) to produce a stable template."""
    msg = message.lower()
    # Mask UUIDs
    msg = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<UUID>", msg)
    # Mask hex strings
    msg = re.sub(r"0x[0-9a-f]+", "<HEX>", msg)
    # Mask numbers / ports / codes
    msg = re.sub(r"\b\d+\b", "<NUM>", msg)
    # Collapse extra whitespace
    msg = re.sub(r"\s+", " ", msg).strip()
    return msg[:80]


def compute_alert_fingerprint(alert: NormalizedAlert) -> str:
    """Compute stable fingerprint for baseline grouping: (source, service, template)."""
    src = (alert.source or "generic").lower().strip()
    svc = (alert.service or "unknown").lower().strip()
    tmpl = extract_message_template(alert.message)
    return f"{src}:{svc}:{tmpl}"


def run_baseline_correlation(
    alerts: List[NormalizedAlert],
    config: Optional[CorrelationConfig] = None
) -> Tuple[List[PredictedIncident], List[UnattachedAlert]]:
    """Run deterministic fingerprint-and-time-gap baseline correlation.
    
    Every alert is accounted for. Groups with >= 2 alerts become incidents.
    Singletons are placed in the unattached list (or singleton incidents).
    """
    if config is None:
        config = CorrelationConfig(algorithm="baseline")

    if not alerts:
        return [], []

    # Sort strictly chronologically
    sorted_alerts = sorted(alerts, key=lambda a: (a.timestamp, a.id))

    # Bucket alerts by fingerprint
    fp_buckets: Dict[str, List[NormalizedAlert]] = {}
    for a in sorted_alerts:
        fp = compute_alert_fingerprint(a)
        fp_buckets.setdefault(fp, []).append(a)

    incidents: List[PredictedIncident] = []
    unattached: List[UnattachedAlert] = []
    incident_counter = 0

    # Within each fingerprint bucket, cluster consecutive alerts within gap_threshold_sec
    for fp, b_alerts in fp_buckets.items():
        current_cluster: List[NormalizedAlert] = []
        cluster_start_ts: Optional[datetime] = None

        for alert in b_alerts:
            if not current_cluster:
                current_cluster.append(alert)
                cluster_start_ts = alert.timestamp
            else:
                prev_alert = current_cluster[-1]
                gap_sec = (alert.timestamp - prev_alert.timestamp).total_seconds()
                total_span = (alert.timestamp - cluster_start_ts).total_seconds()

                if gap_sec <= config.gap_threshold_sec and total_span <= config.max_cluster_span_sec:
                    current_cluster.append(alert)
                else:
                    # Finalize current cluster
                    if len(current_cluster) >= 2:
                        incident_counter += 1
                        inc = _build_baseline_incident(current_cluster, incident_counter)
                        incidents.append(inc)
                    else:
                        unattached.append(UnattachedAlert(
                            alert=current_cluster[0],
                            reason="Singleton alert: No repeat matching fingerprint within time gap"
                        ))
                    current_cluster = [alert]
                    cluster_start_ts = alert.timestamp

        # Finalize tail cluster
        if current_cluster:
            if len(current_cluster) >= 2:
                incident_counter += 1
                inc = _build_baseline_incident(current_cluster, incident_counter)
                incidents.append(inc)
            else:
                unattached.append(UnattachedAlert(
                    alert=current_cluster[0],
                    reason="Singleton alert: No repeat matching fingerprint within time gap"
                ))

    # Sort incidents chronologically by start_time
    incidents.sort(key=lambda inc: inc.start_time)
    return incidents, unattached


def _build_baseline_incident(alerts: List[NormalizedAlert], counter: int) -> PredictedIncident:
    """Create a PredictedIncident object for a baseline group."""
    first = alerts[0]
    last = alerts[-1]
    svc = first.service or "unknown"
    tmpl = extract_message_template(first.message)
    span = (last.timestamp - first.timestamp).total_seconds()

    # Determine highest severity
    sev_rank = {"critical": 4, "error": 3, "warning": 2, "info": 1, "unknown": 0}
    primary_sev = max(alerts, key=lambda a: sev_rank.get(a.severity.lower(), 0)).severity

    services = sorted(list({a.service for a in alerts if a.service}))
    title = f"Baseline Incident #{counter:03d} — Repeated {svc} ({len(alerts)} alerts)"

    # Baseline origin hypothesis is simply the unique service
    origin_hypotheses = [
        OriginHypothesis(
            service=svc,
            rank=1,
            score=1.0,
            is_undetermined=False,
            evidence=[f"All {len(alerts)} alerts originated from service '{svc}' with identical template '{tmpl}'."]
        )
    ]

    return PredictedIncident(
        incident_id=f"INC-BASE-{counter:03d}",
        title=title,
        primary_severity=primary_sev,
        start_time=first.timestamp,
        end_time=last.timestamp,
        span_seconds=span,
        alert_ids=[a.id for a in alerts],
        alerts_count=len(alerts),
        services=services,
        tentative=False,
        origin_hypotheses=origin_hypotheses,
        edges=[]
    )
