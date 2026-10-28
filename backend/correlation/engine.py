"""Core explainable correlation engine and constrained clustering for Pathora (Architecture B).

Enforces strict cluster safety invariants:
1. Every input alert appears in exactly one output group.
2. No alert identifier is duplicated across clusters.
3. Unmatched alerts are retained in an unattached lane.
4. Cluster membership does not depend on ground-truth labels.
5. Cluster time spans are strictly capped to prevent transitive chaining.
6. Weakly supported groups are flagged as tentative.
7. Critical alerts remain fully visible and preserved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from backend.correlation.features import DependencyIndex, score_pair
from backend.correlation.origin import rank_origin_hypotheses
from backend.models import (
    CorrelationConfig,
    NormalizedAlert,
    PairEvidence,
    PredictedIncident,
    ServiceDependencyGraph,
    UnattachedAlert,
)


def run_correlation(
    alerts: List[NormalizedAlert],
    dep_graph: Optional[ServiceDependencyGraph] = None,
    config: Optional[CorrelationConfig] = None
) -> Tuple[List[PredictedIncident], List[UnattachedAlert]]:
    """Run Architecture B explainable correlation on normalized alerts."""
    if config is None:
        config = CorrelationConfig(algorithm="improved")

    if not alerts:
        return [], []

    # Chronological sort
    sorted_alerts = sorted(alerts, key=lambda a: (a.timestamp, a.id))
    n = len(sorted_alerts)
    alert_map: Dict[str, NormalizedAlert] = {a.id: a for a in sorted_alerts}

    # Precompute dependency graph metrics
    dep_index = DependencyIndex(dep_graph)

    # 1. Candidate pair gating: only pairs within time_window_sec
    retained_edges: List[PairEvidence] = []
    edges_by_alert: Dict[str, List[PairEvidence]] = {a.id: [] for a in sorted_alerts}

    for i in range(n):
        alert_i = sorted_alerts[i]
        for j in range(i + 1, n):
            alert_j = sorted_alerts[j]
            delta_sec = (alert_j.timestamp - alert_i.timestamp).total_seconds()
            if delta_sec > config.time_window_sec:
                # Outside candidate gating window; break early
                break

            evidence = score_pair(alert_i, alert_j, config, dep_index)
            if evidence.total_score >= config.min_pair_score:
                retained_edges.append(evidence)
                edges_by_alert[alert_i.id].append(evidence)
                edges_by_alert[alert_j.id].append(evidence)

    # 2. Constrained clustering with span cap
    # Disjoint Set Union (DSU) with max-span check
    parent: Dict[str, str] = {a.id: a.id for a in sorted_alerts}
    cluster_min_ts: Dict[str, datetime] = {a.id: a.timestamp for a in sorted_alerts}
    cluster_max_ts: Dict[str, datetime] = {a.id: a.timestamp for a in sorted_alerts}

    def find(x: str) -> str:
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: str, y: str) -> bool:
        rx, ry = find(x), find(y)
        if rx == ry:
            return True

        # Check span constraint before merging
        combined_min = min(cluster_min_ts[rx], cluster_min_ts[ry])
        combined_max = max(cluster_max_ts[rx], cluster_max_ts[ry])
        combined_span = (combined_max - combined_min).total_seconds()

        if combined_span > config.max_cluster_span_sec:
            # Rejects merge to prevent runaway transitive chaining
            return False

        parent[ry] = rx
        cluster_min_ts[rx] = combined_min
        cluster_max_ts[rx] = combined_max
        return True

    # Process edges sorted descending by score (greedy high-confidence first)
    sorted_edges = sorted(retained_edges, key=lambda e: e.total_score, reverse=True)
    accepted_edges: List[PairEvidence] = []

    for edge in sorted_edges:
        if union(edge.alert_id_a, edge.alert_id_b):
            accepted_edges.append(edge)

    # 3. Assemble clusters
    clusters: Dict[str, List[NormalizedAlert]] = {}
    for a in sorted_alerts:
        root = find(a.id)
        clusters.setdefault(root, []).append(a)

    incidents: List[PredictedIncident] = []
    unattached: List[UnattachedAlert] = []
    incident_counter = 0

    # Severity ranking for display
    sev_rank = {"critical": 4, "error": 3, "warning": 2, "info": 1, "unknown": 0}

    for root, c_alerts in clusters.items():
        if len(c_alerts) >= 2:
            incident_counter += 1
            # Sort cluster alerts chronologically
            c_alerts.sort(key=lambda a: a.timestamp)
            start_t = c_alerts[0].timestamp
            end_t = c_alerts[-1].timestamp
            span_sec = (end_t - start_t).total_seconds()

            c_alert_ids = {a.id for a in c_alerts}
            cluster_edges = [e for e in accepted_edges if e.alert_id_a in c_alert_ids and e.alert_id_b in c_alert_ids]

            # Tentative check: if cluster is multi-service but has low edge density
            is_tentative = False
            tentative_reason = None
            if len(c_alerts) >= 4 and len(cluster_edges) < len(c_alerts):
                is_tentative = True
                tentative_reason = "Sparse connection graph across alerts; check for potential bridge alert."

            # Primary severity
            primary_sev = max(c_alerts, key=lambda a: sev_rank.get(a.severity.lower(), 0)).severity
            services = sorted(list({a.service for a in c_alerts if a.service and a.service != "unknown"}))

            # Ranked origin hypotheses
            origins = rank_origin_hypotheses(c_alerts, dep_graph)
            top_origin = origins[0].service if (origins and not origins[0].is_undetermined) else None

            # Descriptive title
            svc_label = top_origin or (services[0] if services else "Distributed")
            title = f"Incident #{incident_counter:03d} — {svc_label} ({len(c_alerts)} alerts)"

            incidents.append(PredictedIncident(
                incident_id=f"INC-PRED-{incident_counter:03d}",
                title=title,
                primary_severity=primary_sev,
                start_time=start_t,
                end_time=end_t,
                span_seconds=span_sec,
                alert_ids=[a.id for a in c_alerts],
                alerts_count=len(c_alerts),
                services=services,
                tentative=is_tentative,
                tentative_reason=tentative_reason,
                origin_hypotheses=origins,
                edges=cluster_edges
            ))
        else:
            # Singleton alert -> Unattached lane
            unattached.append(UnattachedAlert(
                alert=c_alerts[0],
                reason="Isolated alert: No candidate alerts reached correlation threshold within time window"
            ))

    # Sort incidents chronologically by start time
    incidents.sort(key=lambda inc: inc.start_time)

    # 4. Invariant Validation (Self-Audit)
    total_output_alerts = sum(len(inc.alert_ids) for inc in incidents) + len(unattached)
    if total_output_alerts != len(alerts):
        raise ValueError(
            f"Invariant violation: Input alerts count ({len(alerts)}) != output alerts count ({total_output_alerts})"
        )

    seen_ids: Set[str] = set()
    for inc in incidents:
        for aid in inc.alert_ids:
            if aid in seen_ids:
                raise ValueError(f"Invariant violation: Alert ID '{aid}' appears in multiple incidents.")
            seen_ids.add(aid)
    for u in unattached:
        if u.alert.id in seen_ids:
            raise ValueError(f"Invariant violation: Alert ID '{u.alert.id}' appears in unattached and an incident.")
        seen_ids.add(u.alert.id)

    return incidents, unattached
