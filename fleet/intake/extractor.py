"""Pure LLM-extractor helpers: build the prompt + schema, parse model JSON into
IntakeReports. No I/O — the transport is injected by the controller."""

from typing import List, Tuple

from fleet.contracts.state import (
    WorldState, EventType, EventSeverity, EdgeStatus,
)
from fleet.intake.report import IntakeReport
from fleet.intake.resolver import resolve_target

_INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "reports": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string",
                                   "enum": [e.value for e in EventType]},
                    "target_hint": {"type": "string"},
                    "severity": {"type": "string",
                                 "enum": [s.value for s in EventSeverity]},
                    "confidence": {"type": "number"},
                    "edge_status": {"type": "string",
                                    "enum": [s.value for s in EdgeStatus]},
                    "flood_level": {"type": "number"},
                    "traffic_factor": {"type": "number"},
                },
                "required": ["event_type", "target_hint", "severity"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reports"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You convert a dispatcher's free-text field report into structured "
    "disruption events for a delivery-fleet system. Identify every distinct "
    "disruption in the report. For each, choose one event_type from "
    + ", ".join(e.value for e in EventType)
    + " and a severity from " + ", ".join(s.value for s in EventSeverity)
    + ". `target_hint` must quote the customer, vehicle, or road the report "
    "names so it can be matched to the world roster. For traffic/flooded_area "
    "set edge_status and flood_level/traffic_factor when stated. Respond using "
    "the provided JSON schema only."
)


def _roster(state: WorldState) -> str:
    customers = "; ".join(f"{cid}={c.location.name}"
                          for cid, c in state.customers.items())
    vehicles = ", ".join(state.vehicles.keys())
    edges = ", ".join(state.road_graph.edges.keys())
    return (f"Customers: {customers}\nVehicles: {vehicles}\n"
            f"Road edges: {edges}")


def build_intake_messages(text: str, state: WorldState) -> Tuple[str, str]:
    """Return (system, user) prompt strings. Pure: deterministic given text+state."""
    user = (f"World roster:\n{_roster(state)}\n\n"
            f"Field report: {text}\n"
            "Extract all disruption events as JSON.")
    return _SYSTEM, user


def parse_intake(data: dict, state: WorldState,
                 raw_text: str = "") -> List[IntakeReport]:
    """Map model JSON to IntakeReports. Validates enums (raises ValueError on a
    bad event_type/severity), resolves targets, drops reports whose target can
    not be resolved against the world."""
    out: List[IntakeReport] = []
    for item in data.get("reports", []):
        event_type = EventType(item["event_type"])        # ValueError if unknown
        severity = EventSeverity(item["severity"])        # ValueError if unknown
        target = resolve_target(item.get("target_hint", ""), event_type, state)
        if target is None:
            continue
        edge_status = (EdgeStatus(item["edge_status"])
                       if item.get("edge_status") else None)
        out.append(IntakeReport(
            event_type=event_type, target=target, severity=severity,
            raw_text=raw_text,
            confidence=float(item.get("confidence", 1.0)),
            edge_status=edge_status,
            flood_level=float(item.get("flood_level", 0.0)),
            traffic_factor=float(item.get("traffic_factor", 1.0)),
        ))
    return out
