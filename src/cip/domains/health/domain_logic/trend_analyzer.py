"""Longitudinal trend analysis from stored health snapshots.

Computes trends, detects divergence patterns (signals moving in opposite
directions), and identifies opportunities from historical data.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from cip.core.storage.repository import HealthRepository

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """Computes trends and patterns from stored health signal history.

    Usage::

        analyzer = TrendAnalyzer(repository)
        trend = analyzer.compute_signal_trend("vital_stability", days=90)
        divergences = analyzer.detect_divergence_patterns(days=90)
    """

    def __init__(self, repository: HealthRepository) -> None:
        self._repo = repository

    def compute_signal_trend(
        self,
        signal_name: str,
        *,
        days: int = 90,
        limit: int = 90,
    ) -> dict[str, Any]:
        """Compute trend statistics for a single signal.

        Args:
            signal_name: One of the 4 health signals.
            days: Number of days to look back.
            limit: Max data points.

        Returns:
            Dict with: current, mean, median, min, max, std_dev, direction,
            volatility, data_points.
        """
        history = self._repo.get_signal_history(signal_name, limit=limit)

        if not history:
            return {
                "signal": signal_name,
                "data_points": 0,
                "status": "no_data",
            }

        values = [v for _, v in history]
        current = values[0]  # Most recent (history is newest-first)
        oldest = values[-1]

        # Direction: compare first half vs second half means
        if len(values) >= 4:
            mid = len(values) // 2
            recent_mean = statistics.mean(values[:mid])
            older_mean = statistics.mean(values[mid:])
            diff = recent_mean - older_mean
            if diff > 0.03:
                direction = "improving"
            elif diff < -0.03:
                direction = "declining"
            else:
                direction = "stable"
        elif len(values) >= 2:
            diff = current - oldest
            direction = "improving" if diff > 0.03 else ("declining" if diff < -0.03 else "stable")
        else:
            direction = "insufficient_data"

        # Volatility: coefficient of variation
        mean_val = statistics.mean(values)
        std_val = statistics.stdev(values) if len(values) > 1 else 0.0
        volatility = std_val / mean_val if mean_val > 0 else 0.0

        return {
            "signal": signal_name,
            "current": round(current, 4),
            "mean": round(mean_val, 4),
            "median": round(statistics.median(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "std_dev": round(std_val, 4),
            "direction": direction,
            "volatility": round(volatility, 4),
            "data_points": len(values),
        }

    def compute_lab_trend(
        self,
        test_name: str,
        *,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Compute trend for a specific lab test.

        Args:
            test_name: Lab test name (e.g., 'Fasting Glucose').
            limit: Max results.

        Returns:
            Dict with: test_name, current, previous, direction, values, data_points.
        """
        results = self._repo.get_lab_history(test_name, limit=limit)

        if not results:
            return {
                "test_name": test_name,
                "data_points": 0,
                "status": "no_data",
            }

        values = [r.value for r in results if r.value is not None]
        if not values:
            return {"test_name": test_name, "data_points": 0, "status": "no_data"}

        current = values[0]
        previous = values[1] if len(values) > 1 else None

        if previous is not None:
            diff = current - previous
            if abs(diff) < 0.5:  # Lab values: small changes are "stable"
                direction = "stable"
            elif diff > 0:
                direction = "increasing"
            else:
                direction = "decreasing"
        else:
            direction = "single_reading"

        return {
            "test_name": test_name,
            "current": current,
            "previous": previous,
            "direction": direction,
            "values": values[:5],  # Last 5 for display
            "data_points": len(values),
        }

    def detect_divergence_patterns(
        self,
        *,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """Detect signals trending in opposite directions.

        A divergence is when one signal is improving while another is declining.
        These represent areas where focused attention might help.

        Returns:
            List of divergence dicts with signal_a, signal_b, and description.
        """
        signal_names = [
            "vital_stability",
            "metabolic_balance",
            "activity_recovery",
            "preventive_readiness",
        ]

        trends = {}
        for name in signal_names:
            trend = self.compute_signal_trend(name, days=days)
            if trend.get("data_points", 0) >= 2:
                trends[name] = trend

        divergences = []
        checked = set()

        for a_name, a_trend in trends.items():
            for b_name, b_trend in trends.items():
                if a_name == b_name:
                    continue
                pair = tuple(sorted([a_name, b_name]))
                if pair in checked:
                    continue
                checked.add(pair)

                a_dir = a_trend["direction"]
                b_dir = b_trend["direction"]

                if (a_dir == "improving" and b_dir == "declining") or \
                   (a_dir == "declining" and b_dir == "improving"):
                    improving = a_name if a_dir == "improving" else b_name
                    declining = a_name if a_dir == "declining" else b_name
                    divergences.append({
                        "improving_signal": improving,
                        "declining_signal": declining,
                        "improving_current": trends[improving]["current"],
                        "declining_current": trends[declining]["current"],
                        "description": (
                            f"{_display(improving)} is improving while "
                            f"{_display(declining)} is declining — "
                            f"this divergence may deserve attention."
                        ),
                    })

        return divergences

    def get_snapshot_summary(self) -> dict[str, Any]:
        """Get a summary of stored data for longitudinal context."""
        count = self._repo.count_snapshots()
        if count == 0:
            return {"snapshots_available": 0, "status": "no_history"}

        latest = self._repo.get_latest_snapshot()
        oldest_list = self._repo.get_snapshots(limit=1)  # Will be the newest
        # Get actual oldest by getting all and taking last
        all_snaps = self._repo.get_snapshots(limit=count)
        oldest = all_snaps[-1] if all_snaps else latest

        return {
            "snapshots_available": count,
            "latest_timestamp": latest.timestamp if latest else None,
            "oldest_timestamp": oldest.timestamp if oldest else None,
            "latest_source": latest.source if latest else None,
        }


def _display(signal_name: str) -> str:
    """Convert signal_name to display form."""
    return signal_name.replace("_", " ").title()
