"""Pure, deterministic resolver: free-text mention -> concrete world id.
Accent-folds Vietnamese so typed/transcribed text matches roster names."""

import re
import unicodedata
from typing import Optional

from fleet.contracts.state import WorldState, EventType, EdgeStatus

_EDGE_EVENTS = {EventType.TRAFFIC, EventType.FLOODED_AREA, EventType.ROAD_BLOCK, EventType.ACCIDENT}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    # remove punctuation and normalize whitespace to ease token matching
    s = re.sub(r"[^0-9a-zA-Z]+", " ", s)
    return s.casefold().strip()


def _match_vehicle(hint: str, state: WorldState) -> Optional[str]:
    n = _norm(hint)
    for vid in state.vehicles:
        if _norm(vid) in n:
            return vid
    m = re.search(r"\d+", n)
    if m:
        vid = f"V{int(m.group()):03d}"
        if vid in state.vehicles:
            return vid
    return None


def _match_customer(hint: str, state: WorldState) -> Optional[str]:
    n = _norm(hint)
    for cid in state.customers:
        if _norm(cid) in n:
            return cid
    for cid, c in state.customers.items():
        name = _norm(c.location.name)
        if not name:
            continue
        # token overlap heuristic: any common token indicates a match
        n_tokens = set(re.findall(r"\w+", n))
        name_tokens = set(re.findall(r"\w+", name))
        if n_tokens & name_tokens:
            return cid
        if name in n or n in name:
            return cid
    return None


def _match_edge(hint: str, state: WorldState, event_type: EventType) -> Optional[str]:
    n = _norm(hint)
    for eid in state.road_graph.edges:
        if _norm(eid) == n:
            return eid
    cid = _match_customer(hint, state)
    if cid is None:
        return None
    candidates = (state.road_graph.edges_between("DEPOT", cid)
                  or state.road_graph.edges_between(cid, "DEPOT"))
    if not candidates:
        return None
    if event_type == EventType.FLOODED_AREA:
        flooded = [e for e in candidates
                   if e.flood_level > 0 or e.status == EdgeStatus.FLOODED]
        if flooded:
            return flooded[0].id
    if event_type in (EventType.ROAD_BLOCK, EventType.ACCIDENT):
        blocked = [e for e in candidates if e.status == EdgeStatus.BLOCKED]
        if blocked:
            return blocked[0].id
    if event_type == EventType.TRAFFIC:
        congested = sorted(candidates, key=lambda e: (e.traffic_factor, e.status != EdgeStatus.OPEN), reverse=True)
        if congested:
            return congested[0].id
    open_first = [e for e in candidates if e.status == EdgeStatus.OPEN]
    chosen = (open_first or candidates)[0]
    return chosen.id


def resolve_target(hint: str, event_type: EventType,
                   state: WorldState) -> Optional[str]:
    if event_type == EventType.VEHICLE_BREAKDOWN:
        return _match_vehicle(hint, state)
    if event_type in _EDGE_EVENTS:
        return _match_edge(hint, state, event_type)
    return _match_customer(hint, state)
