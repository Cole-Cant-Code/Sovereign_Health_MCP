"""Tests for the TrendAnalyzer — longitudinal signal analysis."""

from __future__ import annotations

import pytest

from cip.core.storage.models import HealthSnapshot
from cip.domains.health.domain_logic.trend_analyzer import TrendAnalyzer


def _snapshot(
    timestamp: str,
    vs: float = 0.7,
    mb: float = 0.6,
    ar: float = 0.65,
    pr: float = 0.5,
    source: str = "mock",
    **kwargs,
) -> HealthSnapshot:
    """Create a test snapshot with signal values."""
    return HealthSnapshot(
        id="",
        timestamp=timestamp,
        source=source,
        period="last_30_days",
        vital_stability=vs,
        metabolic_balance=mb,
        activity_recovery=ar,
        preventive_readiness=pr,
        **kwargs,
    )


class TestComputeSignalTrend:
    def test_no_data_returns_no_data(self, health_repository):
        analyzer = TrendAnalyzer(health_repository)
        result = analyzer.compute_signal_trend("vital_stability")
        assert result["data_points"] == 0
        assert result["status"] == "no_data"

    def test_single_point_returns_trend(self, health_repository):
        health_repository.save_snapshot(_snapshot("2026-02-01T00:00:00Z"))
        analyzer = TrendAnalyzer(health_repository)
        result = analyzer.compute_signal_trend("vital_stability")
        assert result["data_points"] == 1
        assert result["current"] == 0.7

    def test_improving_trend_detected(self, health_repository):
        # Older snapshots with lower values, newer with higher
        health_repository.save_snapshot(_snapshot("2026-01-01T00:00:00Z", vs=0.5))
        health_repository.save_snapshot(_snapshot("2026-01-15T00:00:00Z", vs=0.55))
        health_repository.save_snapshot(_snapshot("2026-02-01T00:00:00Z", vs=0.65))
        health_repository.save_snapshot(_snapshot("2026-02-15T00:00:00Z", vs=0.72))

        analyzer = TrendAnalyzer(health_repository)
        result = analyzer.compute_signal_trend("vital_stability")
        assert result["direction"] == "improving"
        assert result["data_points"] == 4
        assert result["current"] == 0.72

    def test_declining_trend_detected(self, health_repository):
        health_repository.save_snapshot(_snapshot("2026-01-01T00:00:00Z", vs=0.8))
        health_repository.save_snapshot(_snapshot("2026-01-15T00:00:00Z", vs=0.75))
        health_repository.save_snapshot(_snapshot("2026-02-01T00:00:00Z", vs=0.68))
        health_repository.save_snapshot(_snapshot("2026-02-15T00:00:00Z", vs=0.60))

        analyzer = TrendAnalyzer(health_repository)
        result = analyzer.compute_signal_trend("vital_stability")
        assert result["direction"] == "declining"

    def test_stable_trend_detected(self, health_repository):
        health_repository.save_snapshot(_snapshot("2026-01-01T00:00:00Z", vs=0.70))
        health_repository.save_snapshot(_snapshot("2026-01-15T00:00:00Z", vs=0.71))
        health_repository.save_snapshot(_snapshot("2026-02-01T00:00:00Z", vs=0.69))
        health_repository.save_snapshot(_snapshot("2026-02-15T00:00:00Z", vs=0.70))

        analyzer = TrendAnalyzer(health_repository)
        result = analyzer.compute_signal_trend("vital_stability")
        assert result["direction"] == "stable"

    def test_includes_statistics(self, health_repository):
        health_repository.save_snapshot(_snapshot("2026-01-01T00:00:00Z", vs=0.5))
        health_repository.save_snapshot(_snapshot("2026-02-01T00:00:00Z", vs=0.7))

        analyzer = TrendAnalyzer(health_repository)
        result = analyzer.compute_signal_trend("vital_stability")
        assert "mean" in result
        assert "median" in result
        assert "min" in result
        assert "max" in result
        assert "std_dev" in result
        assert "volatility" in result


class TestComputeLabTrend:
    def test_no_data(self, health_repository):
        analyzer = TrendAnalyzer(health_repository)
        result = analyzer.compute_lab_trend("Fasting Glucose")
        assert result["data_points"] == 0
        assert result["status"] == "no_data"

    def test_single_lab_reading(self, health_repository):
        health_repository.save_snapshot(HealthSnapshot(
            id="", timestamp="2026-02-01T00:00:00Z", source="manual",
            period="point_in_time",
            labs_data=[{"test_name": "Fasting Glucose", "value": 95.0,
                        "unit": "mg/dL", "date": "2026-02-01"}],
        ))
        analyzer = TrendAnalyzer(health_repository)
        result = analyzer.compute_lab_trend("Fasting Glucose")
        assert result["data_points"] == 1
        assert result["current"] == 95.0
        assert result["direction"] == "single_reading"

    def test_decreasing_lab_trend(self, health_repository):
        health_repository.save_snapshot(HealthSnapshot(
            id="", timestamp="2026-01-01T00:00:00Z", source="manual",
            period="point_in_time",
            labs_data=[{"test_name": "LDL Cholesterol", "value": 140.0,
                        "unit": "mg/dL", "date": "2026-01-01"}],
        ))
        health_repository.save_snapshot(HealthSnapshot(
            id="", timestamp="2026-02-01T00:00:00Z", source="manual",
            period="point_in_time",
            labs_data=[{"test_name": "LDL Cholesterol", "value": 130.0,
                        "unit": "mg/dL", "date": "2026-02-01"}],
        ))
        analyzer = TrendAnalyzer(health_repository)
        result = analyzer.compute_lab_trend("LDL Cholesterol")
        assert result["direction"] == "decreasing"
        assert result["current"] == 130.0
        assert result["previous"] == 140.0


class TestDetectDivergencePatterns:
    def test_no_data_no_divergences(self, health_repository):
        analyzer = TrendAnalyzer(health_repository)
        assert analyzer.detect_divergence_patterns() == []

    def test_detects_divergence(self, health_repository):
        # vital_stability improving, metabolic_balance declining
        health_repository.save_snapshot(_snapshot("2026-01-01T00:00:00Z", vs=0.5, mb=0.7))
        health_repository.save_snapshot(_snapshot("2026-01-15T00:00:00Z", vs=0.55, mb=0.65))
        health_repository.save_snapshot(_snapshot("2026-02-01T00:00:00Z", vs=0.65, mb=0.55))
        health_repository.save_snapshot(_snapshot("2026-02-15T00:00:00Z", vs=0.72, mb=0.48))

        analyzer = TrendAnalyzer(health_repository)
        divergences = analyzer.detect_divergence_patterns()
        assert len(divergences) >= 1

        # Check the divergence mentions the right signals
        d = divergences[0]
        assert "improving_signal" in d
        assert "declining_signal" in d
        assert d["improving_signal"] == "vital_stability"
        assert d["declining_signal"] == "metabolic_balance"

    def test_no_divergence_when_all_stable(self, health_repository):
        health_repository.save_snapshot(_snapshot("2026-01-01T00:00:00Z",
                                                   vs=0.7, mb=0.6, ar=0.65, pr=0.5))
        health_repository.save_snapshot(_snapshot("2026-02-01T00:00:00Z",
                                                   vs=0.71, mb=0.61, ar=0.66, pr=0.51))

        analyzer = TrendAnalyzer(health_repository)
        divergences = analyzer.detect_divergence_patterns()
        assert len(divergences) == 0

    def test_insufficient_data_skipped(self, health_repository):
        # Only 1 snapshot — not enough for trend detection
        health_repository.save_snapshot(_snapshot("2026-02-01T00:00:00Z"))
        analyzer = TrendAnalyzer(health_repository)
        divergences = analyzer.detect_divergence_patterns()
        assert len(divergences) == 0


class TestSnapshotSummary:
    def test_empty_db(self, health_repository):
        analyzer = TrendAnalyzer(health_repository)
        summary = analyzer.get_snapshot_summary()
        assert summary["snapshots_available"] == 0
        assert summary["status"] == "no_history"

    def test_with_data(self, health_repository):
        health_repository.save_snapshot(_snapshot("2026-01-01T00:00:00Z"))
        health_repository.save_snapshot(_snapshot("2026-02-01T00:00:00Z"))

        analyzer = TrendAnalyzer(health_repository)
        summary = analyzer.get_snapshot_summary()
        assert summary["snapshots_available"] == 2
        assert "latest_timestamp" in summary
        assert "oldest_timestamp" in summary
