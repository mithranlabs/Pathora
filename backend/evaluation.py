"""Leakage-safe evaluation harness for Pathora.

Computes:
- Pairwise Precision, Recall, and F1
- BCubed Precision, Recall, and F1
- Incident Recovery, Fragmentation, and Swallow/False-Merge rates
- Notification reduction rate (reported alongside incident recall and swallow rate)
- Origin top-1 accuracy and abstention rate
- Explicit UNAVAILABLE state when ground truth is missing
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from backend.models import (
    EvaluationMetrics,
    GroundTruthDataset,
    PredictedIncident,
    UnattachedAlert,
)


def evaluate_run(
    incidents: List[PredictedIncident],
    unattached: List[UnattachedAlert],
    ground_truth: Optional[GroundTruthDataset],
    total_alerts: int
) -> EvaluationMetrics:
    """Evaluate predicted clusters against ground-truth labels without data leakage."""
    total_output_groups = len(incidents) + len(unattached)
    reduction_rate = round(1.0 - (float(total_output_groups) / float(max(1, total_alerts))), 4)

    # 1. Check if ground truth is available
    if ground_truth is None or not ground_truth.incidents:
        return EvaluationMetrics(
            available=False,
            notification_reduction_rate=reduction_rate,
            notes=[
                "Ground-truth incident labels are not available for this dataset.",
                "Running in unsupervised mode. Pairwise F1 and incident recovery metrics are UNAVAILABLE."
            ]
        )

    # 2. Build alert-to-predicted-cluster map
    pred_map: Dict[str, str] = {}
    for inc in incidents:
        for aid in inc.alert_ids:
            pred_map[aid] = inc.incident_id

    for idx, u in enumerate(unattached, start=1):
        pred_map[u.alert.id] = f"UNATTACHED_{idx:04d}"

    # 3. Build alert-to-ground-truth-cluster map
    # Alerts not mapped to an incident in ground truth are assigned singleton labels
    gt_map: Dict[str, str] = {}
    unassigned_counter = 0
    for aid in pred_map:
        if aid in ground_truth.alert_to_incident:
            gt_map[aid] = ground_truth.alert_to_incident[aid]
        else:
            unassigned_counter += 1
            gt_map[aid] = f"GT_NOISE_{unassigned_counter:04d}"

    # 4. Pairwise Metrics
    alert_ids = list(pred_map.keys())
    n = len(alert_ids)
    tp = 0
    fp = 0
    fn = 0

    for i in range(n):
        aid_i = alert_ids[i]
        p_i = pred_map[aid_i]
        g_i = gt_map[aid_i]
        for j in range(i + 1, n):
            aid_j = alert_ids[j]
            p_j = pred_map[aid_j]
            g_j = gt_map[aid_j]

            same_pred = (p_i == p_j)
            same_gt = (g_i == g_j)

            if same_pred and same_gt:
                tp += 1
            elif same_pred and not same_gt:
                fp += 1
            elif not same_pred and same_gt:
                fn += 1

    pw_precision = float(tp) / float(tp + fp) if (tp + fp) > 0 else 0.0
    pw_recall = float(tp) / float(tp + fn) if (tp + fn) > 0 else 0.0
    pw_f1 = (2.0 * pw_precision * pw_recall) / (pw_precision + pw_recall) if (pw_precision + pw_recall) > 0 else 0.0

    # 5. BCubed Metrics
    # Precompute cluster member sets
    pred_clusters: Dict[str, Set[str]] = {}
    gt_clusters: Dict[str, Set[str]] = {}
    for aid in alert_ids:
        pred_clusters.setdefault(pred_map[aid], set()).add(aid)
        gt_clusters.setdefault(gt_map[aid], set()).add(aid)

    bcubed_prec_sum = 0.0
    bcubed_rec_sum = 0.0

    for aid in alert_ids:
        c_set = pred_clusters[pred_map[aid]]
        l_set = gt_clusters[gt_map[aid]]
        intersection_count = len(c_set & l_set)

        bcubed_prec_sum += float(intersection_count) / float(len(c_set))
        bcubed_rec_sum += float(intersection_count) / float(len(l_set))

    bc_prec = bcubed_prec_sum / float(n) if n > 0 else 0.0
    bc_rec = bcubed_rec_sum / float(n) if n > 0 else 0.0
    bc_f1 = (2.0 * bc_prec * bc_rec) / (bc_prec + bc_rec) if (bc_prec + bc_rec) > 0 else 0.0

    # 6. Incident Recovery, Fragmentation, and Swallow Rate
    total_gt_incidents = len(ground_truth.incidents)
    recovered_count = 0
    fragmented_count = 0
    swallowed_count = 0

    # Track which predicted cluster dominates each GT incident
    pred_to_dominated_gt: Dict[str, List[str]] = {}

    for gt_inc in ground_truth.incidents:
        gt_alert_ids = set(gt_inc.alert_ids)
        if not gt_alert_ids:
            continue

        # Count distribution across predicted clusters
        pred_dist: Dict[str, int] = {}
        for aid in gt_alert_ids:
            if aid in pred_map:
                p_id = pred_map[aid]
                pred_dist[p_id] = pred_dist.get(p_id, 0) + 1

        top_pred_id, top_count = max(pred_dist.items(), key=lambda x: x[1])
        coverage = float(top_count) / float(len(gt_alert_ids))

        if coverage >= 0.70:
            recovered_count += 1
            pred_to_dominated_gt.setdefault(top_pred_id, []).append(gt_inc.incident_id)
        else:
            fragmented_count += 1

    # An incident is swallowed if its dominating predicted cluster also absorbed another incident
    for p_id, dom_list in pred_to_dominated_gt.items():
        if len(dom_list) > 1:
            # All but one are considered swallowed (or all absorbed together)
            swallowed_count += (len(dom_list) - 1)

    swallow_rate = float(swallowed_count) / float(max(1, total_gt_incidents))

    # 7. Origin Top-1 Accuracy and Abstention
    origin_eval_count = 0
    origin_correct_count = 0
    origin_abstain_count = 0

    gt_by_id = {inc.incident_id: inc for inc in ground_truth.incidents}

    for p_inc in incidents:
        # Identify if this predicted cluster maps to a ground-truth incident
        cluster_gt_ids = [gt_map[aid] for aid in p_inc.alert_ids if aid in gt_map and not gt_map[aid].startswith("GT_NOISE")]
        if not cluster_gt_ids:
            continue

        # Majority ground truth incident
        gt_mode_id = max(set(cluster_gt_ids), key=cluster_gt_ids.count)
        gt_inc = gt_by_id.get(gt_mode_id)
        if gt_inc and gt_inc.root_cause_service:
            origin_eval_count += 1
            if p_inc.origin_hypotheses:
                top_hyp = p_inc.origin_hypotheses[0]
                if top_hyp.is_undetermined:
                    origin_abstain_count += 1
                elif top_hyp.service == gt_inc.root_cause_service:
                    origin_correct_count += 1

    origin_acc = float(origin_correct_count) / float(origin_eval_count) if origin_eval_count > 0 else None
    origin_abstain_rate = float(origin_abstain_count) / float(origin_eval_count) if origin_eval_count > 0 else None

    notes = [
        f"Evaluated {total_alerts} alerts against {total_gt_incidents} ground-truth incidents.",
        "Notification reduction reported alongside incident recall and swallow rate to avoid gameability.",
        "Strict isolation enforced: Ground-truth incident keys were never visible to prediction algorithms."
    ]

    return EvaluationMetrics(
        available=True,
        pairwise_precision=round(pw_precision, 4),
        pairwise_recall=round(pw_recall, 4),
        pairwise_f1=round(pw_f1, 4),
        bcubed_precision=round(bc_prec, 4),
        bcubed_recall=round(bc_rec, 4),
        bcubed_f1=round(bc_f1, 4),
        total_ground_truth_incidents=total_gt_incidents,
        recovered_incidents=recovered_count,
        fragmented_incidents=fragmented_count,
        swallowed_incidents=swallowed_count,
        swallow_rate=round(swallow_rate, 4),
        notification_reduction_rate=reduction_rate,
        origin_top1_accuracy=round(origin_acc, 4) if origin_acc is not None else None,
        origin_abstention_rate=round(origin_abstain_rate, 4) if origin_abstain_rate is not None else None,
        notes=notes
    )
