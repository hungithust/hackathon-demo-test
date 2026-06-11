import requests
import json
from datetime import datetime, timedelta
import math

from fleet.scenarios import build_sample_state
from fleet.routing.planner import build_routing_problem
from fleet.routing.cuopt_adapter import to_cuopt_request

state = build_sample_state(urban_speed_kmh=2.0)
problem = build_routing_problem(state)
req = to_cuopt_request(problem)

REQUEST_URL = "http://localhost:8001/cuopt/request"
SOLUTION_URL = "http://localhost:8001/cuopt/solution"

try:
    resp = requests.post(REQUEST_URL, json=req, timeout=5)
    resp.raise_for_status()
    req_id = resp.json().get("reqId")
    print(f"reqId: {req_id}")
    
    import time
    for i in range(10):
        sol_resp = requests.get(f"{SOLUTION_URL}/{req_id}")
        if sol_resp.status_code == 200:
            sol_data = sol_resp.json()
            if "response" in sol_data:
                print("Solution OK.")
                break
        else:
            print(f"Status Code: {sol_resp.status_code}")
            print(f"Response Body: {sol_resp.text}")
            break
        time.sleep(1)

except Exception as e:
    print(f"Error: {e}")
