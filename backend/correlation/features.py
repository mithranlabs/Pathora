"""Feature extraction, pairwise scoring, and explainability for Pathora."""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Set, Tuple

from backend.models import (
    CorrelationConfig,
    NormalizedAlert,
    PairEvidence,
    ServiceDependencyGraph,
)


def tokenize_message(message: str) -> Set[str]:
    """Tokenize and normalize alert message into keywords."""
    clean = re.sub(r"[^\w\s]", " ", message.lower())
    # Mask pure numbers
    tokens = {re.sub(r"^\d+$", "<NUM>", tok) for tok in clean.split() if len(tok) > 1}
    return tokens


def compute_text_similarity(msg_a: str, msg_b: str) -> float:
    """Compute token Jaccard similarity between two alert messages."""
    tokens_a = tokenize_message(msg_a)
    tokens_b = tokenize_message(msg_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return float(intersection) / float(union) if union > 0 else 0.0


def compute_temporal_proximity(delta_seconds: float, tau: float = 300.0) -> float:
    """Compute exponential temporal decay score over time gap."""
    if delta_seconds < 0:
        delta_seconds = abs(delta_seconds)
    return math.exp(-delta_seconds / tau)


class DependencyIndex:
    """Precomputed shortest-path distances and node degrees for dependency graphs."""

    def __init__(self, graph: Optional[ServiceDependencyGraph]):
        self.has_graph = graph is not None and len(graph.edges) > 0
        self.adj: Dict[str, Set[str]] = {}
        self.degrees: Dict[str, int] = {}
        self.distances: Dict[Tuple[str, str], int] = {}

        if self.has_graph and graph:
            for edge in graph.edges:
                if len(edge) >= 2:
                    u, v = edge[0].strip(), edge[1].strip()
                    self.adj.setdefault(u, set()).add(v)
                    self.adj.setdefault(v, set()).add(u)

            for node, neighbors in self.adj.items():
                self.degrees[node] = len(neighbors)

            # Precompute pairwise BFS distances up to 2 hops
            for node in self.adj:
                self.distances[(node, node)] = 0
                for n1 in self.adj[node]:
                    self.distances[(node, n1)] = 1
                    for n2 in self.adj.get(n1, set()):
                        if n2 != node and (node, n2) not in self.distances:
                            self.distances[(node, n2)] = 2

    def get_distance(self, svc_a: Optional[str], svc_b: Optional[str]) -> Optional[int]:
        """Return hop distance (1, 2, or None) between two services."""
        if not self.has_graph or not svc_a or not svc_b:
            return None
        return self.distances.get((svc_a, svc_b))

    def is_hub(self, svc: Optional[str], threshold: int = 4) -> bool:
        """Check if service is a high-degree hub node."""
        if not self.has_graph or not svc:
            return False
        return self.degrees.get(svc, 0) >= threshold


def score_pair(
    alert_a: NormalizedAlert,
    alert_b: NormalizedAlert,
    config: CorrelationConfig,
    dep_index: DependencyIndex
) -> PairEvidence:
    """Calculate multi-signal correlation score and explainable evidence breakdown."""
    delta_sec = abs((alert_b.timestamp - alert_a.timestamp).total_seconds())

    # 1. Temporal score
    time_score = compute_temporal_proximity(delta_sec, tau=300.0)

    # 2. Text / Message similarity score
    text_score = compute_text_similarity(alert_a.message, alert_b.message)

    # 3. Same service score
    svcA = (alert_a.service or "").strip().lower()
    svcB = (alert_b.service or "").strip().lower()
    same_service = bool(svcA and svcB and svcA != "unknown" and svcA == svcB)
    service_score = 1.0 if same_service else 0.0

    # 4. Dependency score
    dep_score = 0.0
    dep_note = "none"
    if dep_index.has_graph:
        dist = dep_index.get_distance(alert_a.service, alert_b.service)
        if dist == 1:
            dep_score = 1.0
            dep_note = "direct dependency adjacency (1 hop)"
        elif dist == 2:
            dep_score = 0.5
            dep_note = "indirect dependency adjacency (2 hops)"

        # Apply hub penalty if either node is high-degree
        if dep_index.is_hub(alert_a.service, config.hub_degree_threshold) or \
           dep_index.is_hub(alert_b.service, config.hub_degree_threshold):
            dep_score *= 0.5
            dep_note += " [hub penalty applied]"

    # Weighted sum
    w_t = config.w_time
    w_txt = config.w_text
    w_svc = config.w_service
    w_dep = config.w_dependency if dep_index.has_graph else 0.0

    denom = w_t + w_txt + w_svc + w_dep
    total_score = (
        (w_t * time_score) +
        (w_txt * text_score) +
        (w_svc * service_score) +
        (w_dep * dep_score)
    ) / denom if denom > 0 else 0.0

    total_score = round(min(1.0, max(0.0, total_score)), 4)

    # Explainable rationale construction
    reasons = []
    if delta_sec < 60:
        reasons.append(f"occurred within {int(delta_sec)}s")
    else:
        reasons.append(f"occurred {int(delta_sec / 60)}m apart")

    if same_service:
        reasons.append(f"same service '{alert_a.service}'")
    elif dep_score > 0:
        reasons.append(f"connected via {dep_note}")

    if text_score >= 0.4:
        reasons.append(f"shared message tokens ({int(text_score * 100)}% lexical match)")

    rationale = f"Pair score {total_score:.2f}: " + "; ".join(reasons) + "."

    return PairEvidence(
        alert_id_a=alert_a.id,
        alert_id_b=alert_b.id,
        total_score=total_score,
        time_score=round(time_score, 4),
        text_score=round(text_score, 4),
        service_score=round(service_score, 4),
        dependency_score=round(dep_score, 4),
        delta_seconds=round(delta_sec, 2),
        rationale=rationale
    )
