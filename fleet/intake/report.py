"""Pure data records for the intake layer."""

from dataclasses import dataclass, field
from typing import List, Optional

from fleet.contracts.state import EventType, EventSeverity, EdgeStatus


@dataclass(frozen=True)
class IntakeReport:
    event_type: EventType
    target: str                       # resolved id: customer_id | vehicle_id | edge_id
    severity: EventSeverity
    raw_text: str                     # transcript / typed text this came from
    confidence: float = 1.0
    edge_status: Optional[EdgeStatus] = None   # edge events only
    flood_level: float = 0.0
    traffic_factor: float = 1.0


@dataclass
class IntakeResult:
    raw_text: str
    reports: List[IntakeReport] = field(default_factory=list)
    injected_event_ids: List[str] = field(default_factory=list)
    decisions: List[dict] = field(default_factory=list)   # snapshot-shaped pending decisions
