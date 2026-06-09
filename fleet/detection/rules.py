"""Rule-based anomaly detector (M6): threshold rules over the road graph and
fleet. Pure/read-only over WorldState; emits one Event per offending edge/vehicle
with a deterministic id so the loop's within-tick dedup is stable.

ZScoreDetector (statistical demand anomalies) lives in fleet/detection/zscore.py
behind the same Detector interface."""

from typing import List

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity, EdgeStatus, VehicleStatus,
)

_FLOOD_HIGH_DEPTH = 0.5


class RuleDetector:
    def __init__(self, settings=None):
        self.alert_factor = float(getattr(settings, "traffic_alert_factor", 3.0)
                                  or 3.0)

    def detect(self, state: WorldState) -> List[Event]:
        events: List[Event] = []
        for edge in state.road_graph.edges.values():
            ev = self._edge_event(edge, state)
            if ev is not None:
                events.append(ev)
        for vehicle in state.vehicles.values():
            if vehicle.status == VehicleStatus.BROKEN:
                events.append(Event(
                    id=f"DET_BREAK_{vehicle.id}",
                    event_type=EventType.VEHICLE_BREAKDOWN, target=vehicle.id,
                    severity=EventSeverity.CRITICAL, started_at=state.clock,
                    description=f"vehicle {vehicle.id} broken down"))
        return events

    def _edge_event(self, edge, state):
        if edge.status == EdgeStatus.BLOCKED:
            return Event(
                id=f"DET_BLOCK_{edge.id}", event_type=EventType.ROAD_BLOCK,
                target=edge.id, severity=EventSeverity.CRITICAL,
                started_at=state.clock, description=f"edge {edge.id} blocked")
        if edge.status == EdgeStatus.FLOODED:
            if edge.flood_level >= _FLOOD_HIGH_DEPTH:
                sev = EventSeverity.HIGH
            elif edge.flood_level >= _FLOOD_HIGH_DEPTH / 2:
                sev = EventSeverity.MEDIUM
            else:
                sev = EventSeverity.LOW
            return Event(
                id=f"DET_FLOOD_{edge.id}", event_type=EventType.FLOODED_AREA,
                target=edge.id, severity=sev, started_at=state.clock,
                description=f"edge {edge.id} flooded (depth {edge.flood_level})",
                metrics={"flood_level": float(edge.flood_level)})
        if edge.traffic_factor >= self.alert_factor:
            sev = (EventSeverity.HIGH
                   if edge.traffic_factor >= 2 * self.alert_factor
                   else EventSeverity.MEDIUM)
            return Event(
                id=f"DET_TRAFFIC_{edge.id}", event_type=EventType.TRAFFIC,
                target=edge.id, severity=sev, started_at=state.clock,
                description=f"edge {edge.id} congested (x{edge.traffic_factor})",
                metrics={"traffic_factor": float(edge.traffic_factor)})
        if edge.traffic_factor >= self.alert_factor / 2:
            return Event(
                id=f"DET_TRAFFIC_LOW_{edge.id}", event_type=EventType.TRAFFIC,
                target=edge.id, severity=EventSeverity.LOW,
                started_at=state.clock,
                description=f"edge {edge.id} lightly congested (x{edge.traffic_factor})",
                metrics={"traffic_factor": float(edge.traffic_factor)})
        return None
