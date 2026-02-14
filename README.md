# Sovereign Health MCP

A privacy-first personal health intelligence server built on the [Model Context Protocol](https://modelcontextprotocol.io). Translates your vitals, labs, activity, and preventive care into four quantitative health signals, runs deterministic anomaly detection via [Mantic Thinking](https://github.com/Cole-Cant-Code/mantic-thinking), and returns scaffold-driven analysis through an inner specialist LLM — all while keeping raw health data encrypted on your device.

## License

Free for individuals for personal/non-commercial use. Any commercial or monetized use requires a paid license. See `LICENSE.md` and `COMMERCIAL_LICENSE.md`.

## What it does

```
Apple Health / Manual Entry / Mock Data
              ↓
   Signal Translator (deterministic)
   → vital_stability        (0-1)
   → metabolic_balance      (0-1)
   → activity_recovery      (0-1)
   → preventive_readiness   (0-1)
              ↓
   Mantic Detection (friction + emergence)
              ↓
   Scaffold Router → growth / risk / neutral
              ↓
   Privacy Filter → strict / standard / explicit
              ↓
   Inner LLM → plain-language health guidance
```

**Friction** = one signal is strong while another is weak (e.g., great exercise but terrible sleep).
**Emergence** = all signals are aligned well enough to set a new health goal.

The system picks the right reasoning scaffold (growth, risk, or neutral) based on Mantic's deterministic output — not the LLM's opinion.

## Health signals

| Signal | What it measures | Key inputs |
|---|---|---|
| `vital_stability` | Day-to-day physiological stability | Resting HR, blood pressure, HRV, SpO2 |
| `metabolic_balance` | Metabolic health indicators | Fasting glucose, HbA1c, cholesterol, BMI, triglycerides |
| `activity_recovery` | Exercise, sleep, and recovery balance | Sessions/week, sleep duration/quality, recovery score |
| `preventive_readiness` | Preventive care engagement | Screening status, vaccinations, medication adherence |

All signals are computed deterministically (no LLM, no randomness). Each is a weighted blend of sub-signals clamped to [0, 1].

## Quick start

```bash
# Clone and set up
git clone https://github.com/Cole-Cant-Code/Sovereign_Health_MCP.git
cd Sovereign_Health_MCP

# Install with uv (recommended)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev,mantic]"

# Run tests (273 tests)
make test

# Copy and configure environment
cp .env.example .env
# Edit .env — at minimum set LLM_PROVIDER and an API key

# Start the server
make dev
```

The server binds to `127.0.0.1:8001` by default (loopback only — no auth layer).

## Configuration

Set these in `.env` or as environment variables:

### Server
| Variable | Default | Description |
|---|---|---|
| `CIP_HOST` | `127.0.0.1` | Bind address (loopback for safety) |
| `CIP_PORT` | `8001` | Bind port |
| `CIP_LOG_LEVEL` | `info` | Logging level |
| `CIP_ALLOW_INSECURE_BIND` | `false` | Allow non-loopback bind |

### Inner LLM
| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, or `mock` |
| `ANTHROPIC_API_KEY` | — | Required if provider is anthropic |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5-20250929` | Model to use |
| `OPENAI_API_KEY` | — | Required if provider is openai |
| `OPENAI_MODEL` | `gpt-4o` | Model to use |

### Mantic integration
| Variable | Default | Description |
|---|---|---|
| `MANTIC_CORE_URL` | `http://127.0.0.1:8002/mcp` | cip-mantic-core MCP endpoint |

### Storage & encryption
| Variable | Default | Description |
|---|---|---|
| `ENCRYPTION_KEY` | — | Fernet key for data-at-rest encryption. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. When empty, the server starts but nothing is persisted. |
| `DB_PATH` | `~/.cip/health.db` | SQLite database path |
| `DATA_RETENTION_DAYS` | `0` | Auto-purge snapshots older than N days (0 = keep forever) |

### Data connectors
| Variable | Default | Description |
|---|---|---|
| `APPLE_HEALTH_EXPORT_PATH` | — | Path to Apple Health `export.xml` |

## MCP tools

### Health analysis
| Tool | Description |
|---|---|
| `personal_health_signal` | Full signal analysis → Mantic detection → scaffold-driven LLM interpretation. Accepts `period`, `privacy_mode`, `tone_variant`, `output_format`, `scaffold_id`. |
| `health_check` | Server status, version, scaffold count, storage state. |

### Manual data entry (requires storage)
| Tool | Description |
|---|---|
| `enter_lab_result` | Record a lab test (name, value, unit, date, status). |
| `enter_vitals` | Record vital signs (HR, BP, HRV, SpO2, temperature). |
| `enter_screening` | Record a preventive screening (annual physical, dental, etc.). |
| `enter_vaccination` | Record a vaccination. |
| `list_entered_data` | List previously entered health data. |

### Trend analysis (requires storage)
| Tool | Description |
|---|---|
| `health_trend_analysis` | Longitudinal signal trends, volatility, divergence patterns. |
| `lab_trend` | Historical readings and trend for a specific lab test. |

### Data management (requires storage)
| Tool | Description |
|---|---|
| `delete_health_snapshot` | Delete a specific snapshot. |
| `purge_old_data` | Bulk delete snapshots older than N days. |
| `delete_all_health_data` | Nuclear option — requires `confirm="DELETE_ALL"`. |

### Audit (requires storage)
| Tool | Description |
|---|---|
| `audit_summary` | View recent data access events and LLM disclosure counts. PHI-free. |

## Privacy modes

The `privacy_mode` parameter on `personal_health_signal` controls what data reaches the LLM prompt:

| Mode | What the LLM sees | Use when |
|---|---|---|
| **`strict`** (default) | Signal scores (0-1) + Mantic summary + period. No raw vitals, no labs. | Using an external LLM provider. |
| **`standard`** | Above + friendly vitals (HR, BP, HRV, sleep, exercise, BMI). No raw lab panels. | Want better LLM context with moderate exposure. |
| **`explicit`** | Everything the tool computed. Optionally includes raw Mantic outputs. | Running a local LLM or fully trust the provider. |

In `strict` mode, the LLM literally cannot see your blood pressure or lab values — it only sees abstract signal scores.

## Safety

### Deterministic escalation gate

Before any LLM or Mantic call, the tool checks two hard safety thresholds:

- **Systolic BP > 180 mmHg** — hypertensive crisis range
- **All four signals < 0.3** — system-wide risk (only fires on real data, not on missing-data fallbacks)

If either triggers, the tool returns a deterministic escalation response (seek professional help, recheck readings, emergency guidance) and skips the LLM entirely. No data leaves the device.

### Guardrails

The inner LLM's output is checked against scaffold-defined guardrails:
- **Prohibited patterns**: diagnoses, prescriptions, dietary plans, disease predictions
- **Escalation trigger detection**: flags concerning content in LLM output
- **Disclaimer enforcement**: appends required disclaimers if the LLM omitted them

### Encryption

Raw health data (vitals, labs, activity, preventive care) is Fernet-encrypted (AES-128-CBC + HMAC-SHA256) before storage. Computed signal scores (0-1 floats) are stored unencrypted for indexed longitudinal queries.

### Audit trail

Every tool invocation is logged to a PHI-free audit table:
- Tool name, timestamp, duration
- Privacy mode used
- LLM provider + whether data was disclosed to it
- SHA-256 hash of tool input (not the input itself)
- No raw health data in the audit log

## Scaffold system

The server uses YAML-defined cognitive scaffolds (the Negotiated Expertise Pattern) to control what the inner LLM does. Each scaffold defines:

- **System prompt structure** — role, constraints, reasoning steps
- **Guardrails** — escalation triggers, prohibited actions, required disclaimers
- **Tone variants** — clinical, reassuring, action-oriented
- **Output formats** — structured narrative, bullet points
- **Context exports** — structured data for cross-domain sharing

Mantic-driven routing selects the right scaffold automatically:

| Condition | Scaffold selected |
|---|---|
| Emergence window detected | `personal_health_signal.growth` |
| High friction or coherence < 0.6 | `personal_health_signal.risk` |
| Normal conditions | `personal_health_signal` (neutral) |

## Data connectors

| Connector | Source | Status |
|---|---|---|
| `MockHealthDataProvider` | Simulated data | Always available |
| `AppleHealthProvider` | Apple Health XML export | Set `APPLE_HEALTH_EXPORT_PATH` |
| `ManualEntryProvider` | Health data bank | Requires storage enabled |
| `CompositeHealthProvider` | All of the above (priority: Apple > Manual > Mock) | Automatic |

## Architecture

```
src/cip/
├── core/
│   ├── audit/          # PHI-free audit logging
│   ├── config/         # Settings from env vars
│   ├── llm/            # Inner LLM client + response guardrails
│   ├── mantic/         # MCP client for cip-mantic-core
│   ├── privacy/        # Privacy mode filtering
│   ├── scaffold/       # Engine, registry, loader, matcher, renderer
│   ├── server/         # FastMCP app factory + main entry point
│   └── storage/        # SQLite + Fernet encryption + repository
└── domains/
    └── health/
        ├── connectors/     # Data providers (mock, Apple Health, manual, composite)
        ├── domain_logic/   # Signal translator, trend analyzer, signal models
        ├── prompts/        # MCP prompt templates
        ├── resources/      # MCP resources (scaffold registry)
        ├── scaffolds/      # YAML scaffold definitions
        └── tools/          # MCP tool implementations
```

## Three-project stack

This server is one layer in a three-project stack:

1. **[mantic-thinking](https://github.com/Cole-Cant-Code/mantic-thinking)** — The math engine. Friction/emergence detection kernels, layer interaction models.
2. **[cip-mantic-core](https://github.com/Cole-Cant-Code/cip-mantic-core)** — MCP server wrapping the math engine. Profile routing, governance, audit trails.
3. **Sovereign Health MCP** (this project) — Domain MCP server. Health signal translation, scaffold-driven LLM analysis, encrypted storage.

The health server calls cip-mantic-core over MCP for anomaly detection. If cip-mantic-core is unavailable, it falls back to a local coherence/divergence estimate and still produces an analysis.

## Development

```bash
make test              # Run all 273 tests
make test-unit         # Unit tests only
make test-integration  # Integration tests only
make lint              # Ruff linting
make format            # Ruff formatting
make validate-scaffolds # Verify scaffold YAML loads correctly
```

Requires Python ≥ 3.11. All `make` targets use `uv run` to ensure the project venv is used.
