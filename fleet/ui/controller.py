"""UI-facing controller (M7). Wraps the headless simulation so a Streamlit (or any)
front end can drive it without touching engine internals: step the world, read a
JSON-friendly snapshot, and approve/reject queued decisions. Reuses run_loop and
reroute so the UI behaves identically to the headless loop."""

from typing import Dict, List, Optional

from fleet.contracts.state import ApprovalStatus, DecisionAction
from fleet.scenarios import build_sample_state
from fleet.factory import build_components
from fleet.routing.planner import reroute
from config.settings import load_settings


def _silent(*_args, **_kwargs):
    pass


class SimulationController:
    def __init__(self, state=None, settings=None):
        self.settings = settings or load_settings()
        self.state = state or build_sample_state()
        self.components = build_components(self.settings)

    # ----- driving the world -----
    def step(self, n_ticks: int = 1):
        from fleet.loop import run_loop
        run_loop(self.state, self.components, max(1, int(n_ticks)),
                 settings=self.settings, logger=_silent)
        return self

    # ----- view model -----
    def snapshot(self) -> Dict:
        s = self.state
        by_status = {st: 0 for st in ("pending", "approved", "rejected", "other")}
        for d in s.decisions:
            key = d.approval_status.value
            by_status[key if key in by_status else "other"] += 1
        return {
            "clock": s.clock.isoformat(),
            "sim_tick": s.sim_tick,
            "pending_orders": s.total_orders_pending(),
            "vehicles": [
                {"id": v.id, "status": v.status.value,
                 "lat": v.pos.lat, "lng": v.pos.lng,
                 "stop_index": v.current_stop_index}
                for v in s.vehicles.values()
            ],
            "active_events": [
                {"id": e.id, "event_type": e.event_type.value,
                 "target": e.target, "severity": e.severity.value}
                for e in s.get_active_events()
            ],
            "decisions": {
                "total": len(s.decisions),
                "pending": by_status["pending"],
                "approved": by_status["approved"],
                "rejected": by_status["rejected"],
                "other": by_status["other"],
            },
            "pending_decisions": [
                {"id": d.id, "action": d.action.value, "event_id": d.event_id,
                 "description": d.description,
                 "added_delay_min": d.impact_estimate.get("added_delay_min", 0.0)}
                for d in s.get_pending_decisions()
            ],
        }
