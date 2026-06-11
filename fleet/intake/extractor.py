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
    "You are an information extractor for a delivery-fleet dispatcher. Read the "
    "field report and output ONLY JSON {\"reports\": [...]} per the schema. "
    "Create one report object for EACH distinct disruption mentioned. "
    "event_type must be one of: " + ", ".join(e.value for e in EventType)
    + ". severity one of: " + ", ".join(s.value for s in EventSeverity)
    + ". Set target_hint to the EXACT roster id the report refers to (a vehicle "
    "id like V003, a customer id like C001, or the road toward that customer). "
    "If a vehicle number N is said, the id is V00N. For traffic/flooded_area set "
    "edge_status and flood_level/traffic_factor when stated. Do not invent "
    "disruptions; if none are present return {\"reports\": []}."
)

# Few-shot examples: a small finetuned NIM needs these to follow the extraction
# task rather than its decision-task tuning. Proven to lift the local
# Nemotron-Nano-8B from 0 reports to correct extraction.
_EXAMPLES = (
    'Example 1\n'
    'Report: "truck 2 has a flat tire near the depot"\n'
    '{"reports":[{"event_type":"vehicle_breakdown","target_hint":"V002",'
    '"severity":"high"}]}\n\n'
    'Example 2\n'
    'Report: "C003 urgently needs more stock and the road to C001 is flooded"\n'
    '{"reports":['
    '{"event_type":"urgent_order","target_hint":"C003","severity":"high"},'
    '{"event_type":"flooded_area","target_hint":"C001","severity":"high",'
    '"edge_status":"flooded","flood_level":0.6}]}\n'
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
    user = (f"Roster:\n{_roster(state)}\n\n"
            f"{_EXAMPLES}\n"
            f"Now extract from this report:\n\"{text}\"\n"
            "Output the JSON only.")
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
