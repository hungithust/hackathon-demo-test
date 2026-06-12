"""Multi-session registry: turns the single-world demo into a multi-tenant server.

The original server held ONE global SimulationController, so every browser shared
(and fought over) one world — fine for a demo, impossible for 1000 users with
different maps. SessionManager holds an isolated SimulationController per
session_id, each built from its own ScenarioSpec, so 1000 users each drive their
own problem. Sessions are capped and idle ones are evicted (LRU) to bound memory.

This is in-process: to use all 192 cores you run several worker PROCESSES (OR-Tools
is GIL-bound — see the benchmarks) behind a load balancer with session affinity,
each process owning a shard of sessions via its own SessionManager.
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from fleet.ui.controller import SimulationController
from fleet.scenarios import ScenarioSpec, build_random_state, make_scenarios


@dataclass
class Session:
    id: str
    controller: SimulationController
    spec: Optional[ScenarioSpec]
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    # Monotonic recency rank for LRU — wall-clock ties when many sessions are
    # created in the same clock tick (~15ms on Windows), so order by this instead.
    order: int = 0
    steps: int = 0

    def touch(self, order: int) -> None:
        self.last_seen = datetime.utcnow()
        self.order = order


class SessionManager:
    """Thread-safe map of session_id -> Session, with an LRU capacity bound."""

    def __init__(self, capacity: int = 2000, settings=None):
        self.capacity = capacity
        self.settings = settings
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def _next_order(self) -> int:
        # caller holds the lock
        self._counter += 1
        return self._counter

    # ----- lifecycle -----
    def create(self, spec: Optional[ScenarioSpec] = None,
               session_id: Optional[str] = None) -> Session:
        """Build a fresh isolated world. `spec` defaults to a random one so each
        new session gets a different map/problem."""
        if spec is None:
            spec = make_scenarios(1, seed=uuid.uuid4().int & 0x7FFFFFFF)[0]
        state = build_random_state(spec)
        ctrl = SimulationController(state=state, settings=self.settings,
                                    synthetic_geometry=True)
        sid = session_id or uuid.uuid4().hex
        sess = Session(id=sid, controller=ctrl, spec=spec)
        with self._lock:
            sess.order = self._next_order()
            self._sessions[sid] = sess
            self._evict_if_needed()
        return sess

    def get(self, session_id: str) -> Session:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                raise KeyError(session_id)
            sess.touch(self._next_order())
            return sess

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def list(self) -> List[dict]:
        with self._lock:
            return [
                {"id": s.id, "label": s.spec.label if s.spec else None,
                 "n_customers": len(s.controller.state.customers),
                 "n_vehicles": len(s.controller.state.vehicles),
                 "sim_tick": s.controller.state.sim_tick,
                 "steps": s.steps,
                 "created_at": s.created_at.isoformat(),
                 "last_seen": s.last_seen.isoformat()}
                for s in self._sessions.values()
            ]

    def __len__(self) -> int:
        return len(self._sessions)

    # ----- eviction -----
    def _evict_if_needed(self) -> None:
        # caller holds the lock. Drop least-recently-seen sessions over capacity.
        while len(self._sessions) > self.capacity:
            oldest = min(self._sessions.values(), key=lambda s: s.order)
            self._sessions.pop(oldest.id, None)

    def reap_idle(self, max_idle_seconds: float) -> int:
        """Evict sessions untouched for longer than max_idle_seconds. Returns count."""
        now = datetime.utcnow()
        with self._lock:
            stale = [s.id for s in self._sessions.values()
                     if (now - s.last_seen).total_seconds() > max_idle_seconds]
            for sid in stale:
                self._sessions.pop(sid, None)
        return len(stale)