import networkx as nx

from fleet.scenarios import build_real_state
from fleet.contracts.state import WorldState, EdgeStatus


def _fake_graph():
    """Depot + two customers, fully connected with known length/time."""
    g = nx.DiGraph()
    coords = {
        "D": (10.8231, 106.6297),
        "B": (10.8050, 106.6300),   # C001 location
        "M": (10.7725, 106.6980),   # C002 location
    }
    for n, (y, x) in coords.items():
        g.add_node(n, y=y, x=x)
    for a in coords:
        for b in coords:
            if a != b:
                g.add_edge(a, b, length=2000.0, travel_time=300.0)
    return g


_TWO = [
    ("C001", "supermarket", 10.8050, 106.6300, "BigC", {"SKU001": 10}, 1, 1, 3, 4),
    ("C002", "market",      10.7725, 106.6980, "Cho",  {"SKU001": 20}, 2, 1.5, 3.5, 5),
]


def test_build_real_state_returns_state_and_geometry():
    state, geometry = build_real_state(_fake_graph(), customers=_TWO)
    assert isinstance(state, WorldState)
    assert isinstance(geometry, dict) and geometry


def test_real_edges_get_routed_metrics():
    state, geometry = build_real_state(_fake_graph(), customers=_TWO)
    e = state.road_graph.get_edge("DEPOT->C001")
    assert e.distance_km == 2.0 and e.base_time_minutes == 5.0   # 2000 m / 300 s
    assert "DEPOT->C001" in geometry and len(geometry["DEPOT->C001"]) >= 2


def test_real_state_keeps_flood_parallel_edge():
    state, geometry = build_real_state(_fake_graph(), customers=_TWO)
    flood = state.road_graph.get_edge("DEPOT->C001#2")
    assert flood is not None and flood.status == EdgeStatus.FLOODED
    assert flood.flood_level > 0
