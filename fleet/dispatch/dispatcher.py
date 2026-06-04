"""Applies an approved decision to the WorldState and records execution.
M1: records execution metadata only. M3+ mutates plan/vehicles for real
(e.g. REROUTE swaps in a re-solved route)."""

from fleet.contracts.state import WorldState, Decision


class Dispatcher:
    def apply(self, state: WorldState, decision: Decision) -> None:
        decision.executed_at = state.clock
        decision.execution_result = {"status": "applied"}
        # M3+: mutate state.plan / vehicles based on decision.action
