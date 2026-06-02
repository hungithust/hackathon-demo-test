"""Tab 1 — Architecture Overview. Shows the 5-tier architecture with maturity
badges so the mentor instantly sees the big picture and what is real vs mocked."""

import streamlit as st

LIVE = "✅ Live"
MOCK = "🟡 Mocked"
PLAN = "⚪ Planned"

TIERS = [
    ("Tier 1 — Data Sources", [
        ("GPS / IoT fleet & warehouse", MOCK),
        ("Weather API", MOCK),
        ("ERP API (inventory, orders)", MOCK),
        ("Port / Customs API", PLAN),
        ("Supplier APIs", MOCK),
    ]),
    ("Tier 2 — Stream & Anomaly Detection", [
        ("Event Bus (Kafka / Redis Streams)", MOCK),
        ("Anomaly Detection (Isolation Forest, Z-score, DBSCAN)", LIVE),
        ("RAG Pipeline (ChromaDB + history)", PLAN),
    ]),
    ("Tier 3 — Agent Core (the brain)", [
        ("LangGraph workflow (ReAct / Plan-Execute)", MOCK),
        ("Claude Sonnet — reasoning & decision", LIVE),
        ("Predictive models (Prophet, XGBoost)", MOCK),
    ]),
    ("Tier 4 — Autonomous Actions", [
        ("Rerouting (VRP / OR-Tools)", MOCK),
        ("Inventory rebalance (EOQ / RL)", MOCK),
        ("Supplier switch (graph risk)", MOCK),
        ("Audit log (PostgreSQL)", LIVE),
    ]),
    ("Tier 5 — Human Oversight", [
        ("Dashboard (monitor + override)", LIVE),
        ("Human Approval (high-impact)", LIVE),
        ("Monitoring (AgentOps / Prometheus)", PLAN),
    ]),
]


def render():
    st.header("🏛️ Architecture Overview")
    st.caption(
        "End-to-end design. The agent runs a monitoring loop: ingest data → detect "
        "anomalies → Claude decides → act autonomously → escalate high-impact calls to a human."
    )
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"{LIVE} — working in this demo")
    c2.markdown(f"{MOCK} — simulated with synthetic data")
    c3.markdown(f"{PLAN} — designed, not yet built")

    st.markdown("---")
    for title, comps in TIERS:
        st.subheader(title)
        cols = st.columns(len(comps))
        for col, (name, badge) in zip(cols, comps):
            col.markdown(
                f"<div style='border:1px solid #444;border-radius:8px;padding:10px;"
                f"min-height:90px'><b>{name}</b><br><span style='font-size:0.85em'>"
                f"{badge}</span></div>",
                unsafe_allow_html=True,
            )
        st.markdown("<div style='text-align:center;color:#888'>⬇</div>", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("Why this is different")
    st.info(
        "Most tools build dashboards that **alert humans**. This system builds an agent "
        "that **decides and acts** — escalating to a human only for high-impact decisions "
        "(e.g. cancelling a major supplier contract, rerouting the whole network)."
    )
