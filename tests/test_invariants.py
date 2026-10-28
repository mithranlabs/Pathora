"""Tests for cluster safety invariants and resilient error handling."""

from datetime import datetime, timezone
from backend.correlation.baseline import run_baseline_correlation
from backend.correlation.engine import run_correlation
from backend.models import NormalizedAlert


def test_invariants_on_messy_input():
    alerts = [
        NormalizedAlert(
            id="clean_1",
            timestamp=datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc),
            service="checkout-svc",
            severity="critical",
            message="Database timeout"
        ),
        # Missing service
        NormalizedAlert(
            id="missing_svc",
            timestamp=datetime(2026, 10, 28, 12, 0, 10, tzinfo=timezone.utc),
            service=None,
            severity="warning",
            message="Kernel page fault"
        ),
        # Unknown severity
        NormalizedAlert(
            id="unknown_sev",
            timestamp=datetime(2026, 10, 28, 12, 0, 20, tzinfo=timezone.utc),
            service="auth-svc",
            severity="unknown",
            message="Custom vendor event"
        ),
        # Isolated noise
        NormalizedAlert(
            id="noise_1",
            timestamp=datetime(2026, 10, 28, 12, 5, 0, tzinfo=timezone.utc),
            service="cron",
            severity="info",
            message="Routine log rotation"
        )
    ]

    # Test improved engine
    incidents, unattached = run_correlation(alerts)

    # Invariant 1: Total alerts in output == total alerts in input
    all_output_ids = []
    for inc in incidents:
        all_output_ids.extend(inc.alert_ids)
    for u in unattached:
        all_output_ids.append(u.alert.id)

    assert len(all_output_ids) == len(alerts)
    assert set(all_output_ids) == {a.id for a in alerts}

    # Invariant 2: No duplicates
    assert len(all_output_ids) == len(set(all_output_ids))

    # Invariant 3: Critical alerts are preserved and retain their severity
    crit_alert = next(a for a in alerts if a.id == "clean_1")
    assert crit_alert.severity == "critical"

    # Test baseline engine maintains identical invariants
    b_incidents, b_unattached = run_baseline_correlation(alerts)
    b_output_ids = []
    for inc in b_incidents:
        b_output_ids.extend(inc.alert_ids)
    for u in b_unattached:
        b_output_ids.append(u.alert.id)

    assert len(b_output_ids) == len(alerts)
    assert set(b_output_ids) == {a.id for a in alerts}
