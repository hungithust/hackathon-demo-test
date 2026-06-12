"""A fast-polling cuOpt transport for benchmarking.

The shipped CuOptAdapter transport (fleet/routing/cuopt_adapter.py) sleeps 2s
between polls and prints the raw JSON — fine for a live demo, useless for timing.
This transport polls every 20ms, stays quiet, and lets us set the GPU solver's
internal time_limit so the comparison is apples-to-apples."""

import time
import requests


def make_transport(endpoint: str = "localhost:8001", time_limit: float = 1.0,
                   poll_s: float = 0.02, timeout_s: float = 120.0):
    host, _, port = endpoint.partition(":")
    host = host or "localhost"
    port = int(port or "8001")
    req_url = f"http://{host}:{port}/cuopt/request"
    sol_url = f"http://{host}:{port}/cuopt/solution"

    def transport(request: dict) -> dict:
        request.setdefault("solver_config", {})["time_limit"] = time_limit
        r = requests.post(req_url, json=request, timeout=30)
        r.raise_for_status()
        req_id = r.json().get("reqId")
        if not req_id:
            raise RuntimeError("cuOpt returned no reqId")
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            s = requests.get(f"{sol_url}/{req_id}", timeout=30)
            s.raise_for_status()
            data = s.json()
            if "response" in data:
                return data
            time.sleep(poll_s)
        raise RuntimeError("cuOpt solve timed out")

    return transport