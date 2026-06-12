from fleet.ui.controller import SimulationController
import json

c = SimulationController()
snap = c.snapshot()
routes = snap.get("routes", [])

print(f"Total routes in snapshot: {len(routes)}")
if len(routes) > 0:
    print(f"First route edge_id: {routes[0]['edge_id']}")
    print(f"First route path points: {len(routes[0]['path'])}")
    print(f"First route path: {routes[0]['path'][:2]}")
else:
    print("NO ROUTES FOUND IN SNAPSHOT!")
