# Fleet Optimizer — AI Agent for Realtime Delivery Fleet Optimization

Hub-and-spoke (1 depot) VRPTW fleet optimizer. Base project: a stable
contract/interface layer + a headless walking-skeleton loop. Each module
improves independently behind its interface (see the milestone plans).

## Layout
- `fleet/contracts/` — WorldState entities, 6 Protocol interfaces, routing DTOs (depends on nothing)
- `fleet/simulator/` — the world (tick, events; demand/movement in M2)
- `fleet/detection/` — anomaly detection (rules now; z-score in M6)
- `fleet/routing/` — `CpuSolver` (greedy VRPTW in M3) + `CuOptAdapter` (M4) + `matrix.py` (Dijkstra, M3)
- `fleet/forecast/` — `EwmaForecaster` (M6) + Prophet (later)
- `fleet/agent/` — `RuleBasedEngine` (default) + `ClaudeAgent` (M5)
- `fleet/dispatch/` — approval policy + dispatcher
- `fleet/loop.py` — headless orchestration loop
- `config/settings.py` — engine switches (CPU/cuOpt, rule/claude) + thresholds

## Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run
```powershell
pytest -v             # full test suite
python -m fleet.loop  # headless skeleton demo
```

## Configure (env vars)
`ROUTING_ENGINE=cpu|cuopt`, `DECISION_ENGINE=rule|claude`, `SEED`, `TICK_MINUTES`,
`ANTHROPIC_API_KEY`, `CUOPT_ENDPOINT`. Defaults run with no GPU and no API key.
