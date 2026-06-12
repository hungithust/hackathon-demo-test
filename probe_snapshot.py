import requests
import json

try:
    resp = requests.get("http://localhost:8000/api/snapshot")
    data = resp.json()
    routes = data.get("routes", [])
    print(f"Total routes in snapshot: {len(routes)}")
    if len(routes) > 0:
        print(f"First route edge_id: {routes[0]['edge_id']}")
        print(f"First route path points: {len(routes[0]['path'])}")
        print(f"First route path: {routes[0]['path'][:2]}")
    else:
        print("NO ROUTES FOUND IN SNAPSHOT!")
except Exception as e:
    print("Error:", e)
