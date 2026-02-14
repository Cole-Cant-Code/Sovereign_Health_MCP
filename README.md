# CIP Health

CIP Health is a standalone MCP server for personal health signal detection using Mantic Thinking. It translates (mock) personal health data into four consumer-friendly signals and runs deterministic scoring plus Mantic-based detection to surface friction and emergence patterns.

## Signals

- `vital_stability`: day-to-day physiological stability (vitals variability, acute instability risk)
- `metabolic_balance`: metabolic health indicators (weight/labs/conditions proxies, longer-term risk)
- `activity_recovery`: activity, sleep, and recovery balance (strain vs recovery adequacy)
- `preventive_readiness`: preventive care engagement (screenings, vaccinations, routine follow-through)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mantic]"
```

## Test

```bash
python3 -m pytest tests/ -v
```

## Note

This project currently uses mock health data. Real connectors are planned for future phases.

