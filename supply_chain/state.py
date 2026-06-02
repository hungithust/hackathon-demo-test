"""Session state + the disruption/decision lifecycle.

All data is synthetic and held in st.session_state so the demo is fully
self-contained (no DB, no external streams). Functions here mutate that state
in response to user actions in the UI.
"""

import datetime as dt
import streamlit as st

from .scenarios import SCENARIOS
from .agent import run_agent_reasoning


def init_state():
    if "initialized" in st.session_state:
        return
    st.session_state.initialized = True
    st.session_state.loop = 12
    st.session_state.status = "Normal"            # Normal | Anomaly | Awaiting | Resolved
    st.session_state.nodes = {
        "suppliers": {"A": "ok", "B": "ok", "C": "ok"},
        "warehouses": {"North": "ok", "South": "ok"},
        "distribution": {"DC-Central": "ok"},
        "retail": {"Store-HCM": "ok", "Store-HN": "ok"},
        "routes": {"QL1A": "ok", "DT743": "ok"},
    }
    st.session_state.log = ["> Monitoring loop running... all nodes nominal."]
    st.session_state.kpis = {"On-time %": 98.5, "Logistics cost idx": 100.0, "Avg response (min)": 4.2}
    st.session_state.audit = []
    st.session_state.pending = None               # decision awaiting human approval
    st.session_state.active_scenario = None
    st.session_state.engine = "-"
    st.session_state.llm_error = None
    st.session_state.last_dispatch = []           # commands sent to node staff (step 4)
    st.session_state.stage = 0                     # workflow step reached (0-4)


def reset_demo():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    init_state()


def log(msg):
    st.session_state.log.append(msg)


def inject(scenario_name):
    """Tier 1-3: ingest event → detect anomaly → agent reasons → maybe escalate."""
    sc = SCENARIOS[scenario_name]
    st.session_state.active_scenario = scenario_name
    st.session_state.loop += 1
    st.session_state.status = "Anomaly"
    st.session_state.last_dispatch = []

    # Step 1 (ingest) + Step 2 (detect)
    st.session_state.stage = 2
    log(f"> [Event Bus] Loop #{st.session_state.loop}: event ingested — {sc['event']}")
    log(f"> [Anomaly Detection] {sc['anomaly']}")
    group, node = sc["node_hit"]
    st.session_state.nodes[group][node] = "alert"

    # KPIs degrade on disruption
    st.session_state.kpis["On-time %"] = 86.0
    st.session_state.kpis["Logistics cost idx"] = 113.0
    st.session_state.kpis["Avg response (min)"] = 0.3   # agent reacts in seconds

    log("> [Agent Core] Reasoning over context (ReAct)...")
    decision, engine = run_agent_reasoning(scenario_name, sc)
    st.session_state.engine = engine
    for step in decision["reasoning"]:
        log(f"    🧠 {step}")
    log(f"> [Agent Core] 💡 Proposed action: {decision['action']}")
    log(f"> [Agent Core] 📊 Estimated impact: {decision['impact']}")

    # Step 3 (decide & propose) complete
    st.session_state.stage = 3

    if decision.get("needs_approval"):
        st.session_state.status = "Awaiting"
        st.session_state.pending = decision
        log("> [Human Approval] ⏸ High-impact decision — escalated for approval.")
    else:
        log("> [Autonomous Action] Low-impact — executing automatically.")
        apply_decision(decision, approver="Auto (low impact)")


def apply_decision(decision, approver):
    """Tier 4: execute the action, restore the network, write the audit log."""
    sc = SCENARIOS[st.session_state.active_scenario]
    group, node = sc["node_hit"]
    st.session_state.nodes[group][node] = "ok"
    st.session_state.status = "Resolved"
    st.session_state.pending = None

    st.session_state.kpis["On-time %"] = 97.2
    st.session_state.kpis["Logistics cost idx"] = 102.5
    st.session_state.kpis["Avg response (min)"] = 0.3

    log(f"> [Autonomous Action] ✅ Executed: {decision['action']}")

    # Step 4 (execute): dispatch concrete commands to node staff (indirect users)
    st.session_state.stage = 4
    st.session_state.last_dispatch = sc.get("dispatch", [])
    for cmd in st.session_state.last_dispatch:
        log(f"> [Dispatch] {cmd}")
    log("> [Monitoring] Network restructured — status back to nominal.")
    st.session_state.audit.append({
        "time": dt.datetime.now().strftime("%H:%M:%S"),
        "event": sc["event"],
        "decision": decision["action"],
        "approver": approver,
        "engine": st.session_state.engine,
    })


def reject_decision():
    st.session_state.status = "Anomaly"
    st.session_state.pending = None
    log("> [Human Approval] ❌ Rejected — keeping current plan, escalating to ops team.")


WORKFLOW_STEPS = [
    "1 · Ingest data",
    "2 · Detect anomaly",
    "3 · Decide & propose",
    "4 · Execute & dispatch",
]


def workflow_states():
    """Return a list of (label, state) where state is done | active | pending,
    based on how far the current disruption has progressed."""
    stage = st.session_state.get("stage", 0)
    out = []
    for i, label in enumerate(WORKFLOW_STEPS, start=1):
        if i < stage or (i == stage and stage == 4):
            out.append((label, "done"))
        elif i == stage:
            out.append((label, "active"))
        else:
            out.append((label, "pending"))
    return out
