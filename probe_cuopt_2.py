from datetime import datetime
from config.settings import load_settings
from fleet.factory import build_components
from fleet.scenarios import build_sample_state
from fleet.routing.planner import build_routing_problem
from fleet.routing.cuopt_adapter import to_cuopt_request
import requests
import time
import json

settings = load_settings()
state = build_sample_state()
components = build_components(settings)

problem = build_routing_problem(state, components.optimizer)
req = to_cuopt_request(problem)
req["solver_config"] = {"time_limit": 2.0}

print("Testing cuOpt Payload:")
url_req = "http://localhost:8001/cuopt/request"
url_sol = "http://localhost:8001/cuopt/solution"

resp = requests.post(url_req, json=req, timeout=10)
print("POST status:", resp.status_code)
if resp.status_code != 200:
    print(resp.text)
    exit(1)

req_id = resp.json().get("reqId")
print("ReqID:", req_id)

for _ in range(10):
    sol_resp = requests.get(f"{url_sol}/{req_id}")
    print("GET status:", sol_resp.status_code)
    if sol_resp.status_code != 200:
        print("Error:", sol_resp.text)
        break
    data = sol_resp.json()
    if "response" in data:
        print("Success")
        break
    time.sleep(2)
