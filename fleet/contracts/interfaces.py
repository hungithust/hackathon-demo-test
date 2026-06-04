"""The six stable interfaces every module hides behind (spec §4).

Tests target these Protocols, not concrete impls, so swapping
CpuSolver<->CuOptAdapter or RuleBasedEngine<->ClaudeAgent never breaks tests."""

from typing import List, Protocol, runtime_checkable

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity, Decision,
)
from fleet.contracts.dto import RoutingProblem, RoutingSolution


@runtime_checkable
class Simulator(Protocol):
    def tick(self, state: WorldState) -> None: ...
    def inject_event(self, state: WorldState, event_type: EventType,
                     target: str, severity: EventSeverity) -> Event: ...


@runtime_checkable
class Detector(Protocol):
    def detect(self, state: WorldState) -> List[Event]: ...


@runtime_checkable
class RouteOptimizer(Protocol):
    def solve(self, problem: RoutingProblem) -> RoutingSolution: ...


@runtime_checkable
class Forecaster(Protocol):
    def forecast(self, history: list, horizon_h: int) -> dict: ...


@runtime_checkable
class DecisionEngine(Protocol):
    def decide(self, state: WorldState, events: List[Event]) -> List[Decision]: ...


@runtime_checkable
class Dispatcher(Protocol):
    def apply(self, state: WorldState, decision: Decision) -> None: ...
