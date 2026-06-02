"""
Twilight — Autonomous Supply Chain Agent (Hackathon Demo)

An AI agent that monitors a supply chain in real time, detects disruptions,
and autonomously decides & executes restructuring — escalating only high-impact
decisions to a human.

Run locally:   streamlit run app.py
Live reasoning: set ANTHROPIC_API_KEY (env var or Streamlit secret). Without it,
the app uses scripted reasoning so the demo never fails.

All data is synthetic / in-memory. Components are labeled with the real 5-tier
architecture names so the mapping to the full system is clear.
"""

import streamlit as st

from supply_chain.state import init_state, inject, reset_demo
from supply_chain.scenarios import SCENARIOS
from supply_chain.tabs import architecture, monitoring, predictive, agent_core

st.set_page_config(page_title="Twilight — Supply Chain Agent", page_icon="🔗", layout="wide")
init_state()

STATUS_BADGE = {
    "Normal": "🟢 Normal",
    "Anomaly": "🟠 Anomaly detected",
    "Awaiting": "🟡 Awaiting human approval",
    "Resolved": "🟢 Resolved",
}

# ----------------------------------------------------------------------------
# Sidebar — global control: status + inject disruption (works from any tab)
# ----------------------------------------------------------------------------
with st.sidebar:
    st.title("🔗 Twilight")
    st.caption("Autonomous Supply Chain Agent")
    st.markdown(f"**Status:** {STATUS_BADGE[st.session_state.status]}")
    st.markdown(f"**Monitoring loop:** #{st.session_state.loop}")
    st.markdown(f"**Reasoning engine:** `{st.session_state.engine}`")

    st.markdown("---")
    st.subheader("⚡ Inject Disruption")
    options = list(SCENARIOS.keys())
    default = st.session_state.get("queued_scenario")
    idx = options.index(default) if default in options else 0
    scenario = st.selectbox("Scenario", options, index=idx,
                            format_func=lambda s: f"{SCENARIOS[s]['icon']} {s}")
    st.caption(SCENARIOS[scenario]["event"])
    if st.button("⚡ Inject", type="primary", use_container_width=True):
        inject(scenario)
        st.session_state.queued_scenario = None
        st.rerun()
    if st.button("🔄 Reset demo", use_container_width=True):
        reset_demo()
        st.rerun()

    st.markdown("---")
    st.caption("Tip: open the **Agent Core** tab before injecting to watch the agent reason live.")

# ----------------------------------------------------------------------------
# Main — tabs mapped to the architecture tiers
# ----------------------------------------------------------------------------
st.title("Autonomous Supply Chain Agent — Real-Time Control")

tab1, tab2, tab3, tab4 = st.tabs([
    "🏛️ Architecture",
    "📡 Live Monitoring",
    "🔮 Predictive",
    "🧠 Agent Core",
])

with tab1:
    architecture.render()
with tab2:
    monitoring.render()
with tab3:
    predictive.render()
with tab4:
    agent_core.render()
