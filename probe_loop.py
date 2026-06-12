from fleet.factory import build_components
from fleet.scenarios import build_real_state
from fleet.loop import run_loop
import networkx as nx
from datetime import datetime

class MockSettings:
    cuopt_endpoint = "localhost:8001"
    local_endpoint = ""
    world = "real"
    routing_engine = "cuopt"
    decision_engine = "rule"
    forecaster_engine = "ewma"
    detector_engine = "rule"
    seed = 42

settings = MockSettings()
try:
    print("Building state...")
    graph = nx.DiGraph() # dummy graph for route
    # Mock route to avoid OSM load
    import fleet.scenarios
    from fleet.geo.router import RouteGeometry
    def mock_route(*args, **kwargs):
        return RouteGeometry(distance_km=1.0, minutes=30.0, polyline=[(10.0, 106.0), (10.1, 106.1)])
    fleet.scenarios.route = mock_route
    
    state, geom = build_real_state(graph, urban_speed_kmh=2.0)
    components = build_components(settings)
    print("Running loop...")
    run_loop(state, components, 1, [])
except Exception as e:
    import traceback
    traceback.print_exc()
