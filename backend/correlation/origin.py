"""Ranked origin hypotheses and abstention engine for Pathora.

Ranks candidate origin services using temporal precedence, dependency direction,
and coverage. Does NOT assert proven root causes. Abstains when evidence is ambiguous.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from backend.models import (
    NormalizedAlert,
    OriginHypothesis,
    ServiceDependencyGraph,
)


def rank_origin_hypotheses(
    alerts: List[NormalizedAlert],
    dep_graph: Optional[ServiceDependencyGraph] = None
) -> List[OriginHypothesis]:
    """Rank candidate origin services for a cluster of alerts.
    
    Returns a list of OriginHypothesis. If evidence is ambiguous, returns
    an explicit 'Undetermined' hypothesis.
    """
    if not alerts:
        return [
            OriginHypothesis(
                service=None,
                rank=1,
                score=0.0,
                is_undetermined=True,
                evidence=["No alerts in cluster to evaluate."]
            )
        ]

    services_in_cluster = sorted(list({a.service for a in alerts if a.service and a.service != "unknown"}))

    # Single service cluster
    if len(services_in_cluster) == 1:
        svc = services_in_cluster[0]
        return [
            OriginHypothesis(
                service=svc,
                rank=1,
                score=1.0,
                is_undetermined=False,
                evidence=[
                    f"All {len(alerts)} alerts in this incident originated strictly from service '{svc}'.",
                    "No conflicting cross-service symptoms observed."
                ]
            )
        ]

    # No named services
    if len(services_in_cluster) == 0:
        return [
            OriginHypothesis(
                service=None,
                rank=1,
                score=0.0,
                is_undetermined=True,
                evidence=["All alerts in this cluster lack identifiable service names."]
            )
        ]

    # Multi-service cluster: evaluate temporal precedence and dependency topology
    sorted_alerts = sorted(alerts, key=lambda a: a.timestamp)
    first_seen_per_svc: Dict[str, datetime] = {}
    alert_counts_per_svc: Dict[str, int] = {}

    for a in sorted_alerts:
        if a.service and a.service != "unknown":
            if a.service not in first_seen_per_svc:
                first_seen_per_svc[a.service] = a.timestamp
            alert_counts_per_svc[a.service] = alert_counts_per_svc.get(a.service, 0) + 1

    # Check for simultaneous first alert (ambiguous tie)
    first_ts_list = sorted(first_seen_per_svc.values())
    earliest_ts = first_ts_list[0]
    earliest_services = [s for s, ts in first_seen_per_svc.items() if ts == earliest_ts]

    # Check for cyclic dependencies between earliest services
    is_cycle = False
    if dep_graph and len(earliest_services) >= 2:
        edges_set = {tuple(e) for e in dep_graph.edges if len(e) >= 2}
        s1, s2 = earliest_services[0], earliest_services[1]
        if (s1, s2) in edges_set and (s2, s1) in edges_set:
            is_cycle = True

    # If cyclic deadlock or simultaneous arrival without topological distinction -> Abstain!
    if is_cycle or (len(earliest_services) >= 2 and len(first_ts_list) >= 2 and (first_ts_list[1] - earliest_ts).total_seconds() < 2.0):
        reasons = [
            f"Multiple candidate services ({', '.join(earliest_services)}) alerted simultaneously at {earliest_ts.isoformat()}.",
        ]
        if is_cycle:
            reasons.append("Circular dependency detected between candidate services (mutual RPC / dependency deadlock).")
        reasons.append("Evidence is insufficient to isolate an unambiguous upstream initiator.")

        return [
            OriginHypothesis(
                service=None,
                rank=1,
                score=0.5,
                is_undetermined=True,
                evidence=reasons
            )
        ]

    # Calculate scored hypotheses for each service
    candidate_scores: List[Tuple[str, float, List[str]]] = []
    total_cluster_span = max(1.0, (sorted_alerts[-1].timestamp - earliest_ts).total_seconds())

    # Build directed dependency set if available
    # edge [caller, callee]: caller calls callee, so callee is dependency
    callee_set: Set[str] = set()
    if dep_graph:
        for edge in dep_graph.edges:
            if len(edge) >= 2:
                callee_set.add(edge[1])

    for svc in services_in_cluster:
        first_ts = first_seen_per_svc[svc]
        delay_sec = (first_ts - earliest_ts).total_seconds()
        
        # 1. Temporal precedence score: earlier is higher (0.0 to 1.0)
        temporal_score = max(0.0, 1.0 - (delay_sec / total_cluster_span))
        
        # 2. Dependency position score: callees/infrastructure services that fail first get bonus
        dep_bonus = 0.0
        if dep_graph:
            if svc in callee_set:
                dep_bonus = 0.2

        # 3. Symptom density score
        density_score = float(alert_counts_per_svc[svc]) / float(len(alerts))

        composite_score = round((0.55 * temporal_score) + (0.25 * dep_bonus) + (0.20 * density_score), 4)

        evidence = [
            f"First alert at {first_ts.isoformat()} ({int(delay_sec)}s after incident inception).",
            f"Produced {alert_counts_per_svc[svc]} of {len(alerts)} alerts in cluster."
        ]
        if dep_bonus > 0:
            evidence.append(f"Identified as a foundational callee / infrastructure dependency in topology graph.")

        candidate_scores.append((svc, composite_score, evidence))

    # Sort descending by composite score
    candidate_scores.sort(key=lambda x: x[1], reverse=True)

    # Check margin between top 2
    if len(candidate_scores) >= 2:
        top_diff = candidate_scores[0][1] - candidate_scores[1][1]
        if top_diff < 0.04:
            # Margin too narrow -> abstain
            return [
                OriginHypothesis(
                    service=None,
                    rank=1,
                    score=candidate_scores[0][1],
                    is_undetermined=True,
                    evidence=[
                        f"Close score margin between '{candidate_scores[0][0]}' ({candidate_scores[0][1]:.2f}) and '{candidate_scores[1][0]}' ({candidate_scores[1][1]:.2f}).",
                        "Statistical evidence is too balanced to declare a definitive origin hypothesis."
                    ]
                )
            ]

    # Return ranked hypotheses
    hypotheses = []
    for rank_idx, (svc, score, ev) in enumerate(candidate_scores[:3], start=1):
        hypotheses.append(OriginHypothesis(
            service=svc,
            rank=rank_idx,
            score=score,
            is_undetermined=False,
            evidence=ev
        ))

    return hypotheses
