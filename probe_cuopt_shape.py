import requests
import json
import math
import random
import time

random.seed(42)

n_locations = 5
n_vehicles = 2

coords = [(random.randint(0, 100), random.randint(0, 100)) for _ in range(n_locations)]

matrix_data = []
for i in range(n_locations):
    row = []
    for j in range(n_locations):
        dist = round(math.hypot(coords[i][0] - coords[j][0], coords[i][1] - coords[j][1]), 2)
        row.append(dist)
    matrix_data.append(row)

demands = [0] + [random.randint(5, 20) for _ in range(4)]
vehicle_capacities = [40, 50]

order_earliest = [0] + [random.randint(0, 120) for _ in range(4)]
order_latest = [500] + [random.randint(180, 400) for _ in range(4)]
service_times = [0] + [10] * 4

vehicle_earliest = [0] * n_vehicles
vehicle_latest = [500] * n_vehicles

payload = {
    "cost_matrix_data": {
        "data": {"0": matrix_data}
    },
    "task_data": {
        "task_locations": list(range(1, n_locations)),
        "demand": [demands[1:]],
        "task_time_windows": [[order_earliest[i], order_latest[i]] for i in range(1, n_locations)],
        "service_times": service_times[1:]
    },
    "fleet_data": {
        "vehicle_locations": [[0, 0]] * n_vehicles,
        "capacities": [vehicle_capacities],
        "vehicle_time_windows": [[vehicle_earliest[i], vehicle_latest[i]] for i in range(n_vehicles)]
    },
    "solver_config": {
        "time_limit": 2.0
    }
}

REQUEST_URL = "http://localhost:8001/cuopt/request"
SOLUTION_URL = "http://localhost:8001/cuopt/solution"

try:
    response = requests.post(REQUEST_URL, json=payload, timeout=5)
    response.raise_for_status()
    req_id = response.json().get("reqId")
except Exception as e:
    req_id = None
    with open("cuopt_resp.json", "w") as f: f.write(json.dumps({"error": str(e)}))

if req_id:
    for attempt in range(10):
        try:
            sol_response = requests.get(f"{SOLUTION_URL}/{req_id}", timeout=5)
            sol_response.raise_for_status()
            sol_data = sol_response.json()
            if "response" in sol_data:
                with open("cuopt_resp.json", "w") as f:
                    f.write(json.dumps(sol_data, indent=2))
                break
        except Exception as e:
            pass
        time.sleep(2)
