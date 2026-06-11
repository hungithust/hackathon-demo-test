"""Pure, deterministic resolver: free-text mention -> concrete world id.
Accent-folds Vietnamese so typed/transcribed text matches roster names."""

import re
import unicodedata
from typing import Optional

from fleet.contracts.state import WorldState, EventType, EdgeStatus

_EDGE_EVENTS = {EventType.TRAFFIC, EventType.FLOODED_AREA}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
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
        if name and (name in n or n in name):
            return cid
    return None


def _route_leg_into(state: WorldState, cid: str) -> Optional[str]:
    """The edge a routed vehicle actually drives to ENTER customer `cid` (the last
    edge of its current approach leg).  This is the edge whose disruption the loop
    will see as on-route, so a voice flood/jam on "the road into Cxxx" triggers a
    reroute.  Returns None when no vehicle's remaining route reaches `cid` — then
    the caller falls back to the DEPOT<->Cxxx edge."""
    from fleet.routing.matrix import shortest_path_edges
    for vid, route in state.plan.items():
        ordered = sorted(route.stops, key=lambda s: s.sequence)
        unvisited = [s for s in ordered if s.actual_arrival is None]
        seq = [s.customer_id for s in unvisited]
        if cid not in seq:
            continue
        idx = seq.index(cid)
        if idx > 0:
            pred = seq[idx - 1]
        else:
            visited = [s for s in ordered if s.actual_arrival is not None]
            pred = visited[-1].customer_id if visited else "DEPOT"
        v = state.get_vehicle(vid)
        wade = float(v.wade_capability) if v else 0.3
        edges = shortest_path_edges(state.road_graph, pred, cid, wade)
        if edges:
            return edges[-1]      # the edge whose to_node == cid
    return None


def _match_edge(hint: str, state: WorldState, event_type: EventType) -> Optional[str]:
    n = _norm(hint)
    for eid in state.road_graph.edges:
        if _norm(eid) == n:
            return eid
    cid = _match_customer(hint, state)
    if cid is None:
        return None
    # Prefer the edge a routed vehicle actually uses to reach `cid` so the
    # disruption lands ON a live route (DEPOT->Cxxx is rarely the leg in use for
    # a mid-route customer, so flooding it would never trigger a reroute).
    on_route = _route_leg_into(state, cid)
    if on_route is not None:
        return on_route
    candidates = (state.road_graph.edges_between("DEPOT", cid)
                  or state.road_graph.edges_between(cid, "DEPOT"))
    if not candidates:
        return None
    if event_type == EventType.FLOODED_AREA:
        flooded = [e for e in candidates
                   if e.flood_level > 0 or e.status == EdgeStatus.FLOODED]
        chosen = (flooded or candidates)[0]
    else:
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
