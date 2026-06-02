"""Tab 2 — Live Monitoring. Network graph of the supply chain (red on anomaly),
mocked streaming data sources, and live KPIs."""

import random
import networkx as nx
import plotly.graph_objects as go
import streamlit as st

# Full supply chain: Suppliers → Warehouses → Distribution → Retail → Customers.
# Fixed layout positions so the graph doesn't jump on each rerun.
NODES = {
    "Supplier A": (0, 2.4), "Supplier B": (0, 1.2), "Supplier C": (0, 0.0),
    "Warehouse North": (1, 1.9), "Warehouse South": (1, 0.5),
    "DC-Central": (2, 1.2),
    "Store-HCM": (3, 1.9), "Store-HN": (3, 0.5),
    "Customers": (4, 1.2),
}
EDGES = [
    ("Supplier A", "Warehouse North"), ("Supplier B", "Warehouse North"),
    ("Supplier B", "Warehouse South"), ("Supplier C", "Warehouse South"),
    ("Warehouse North", "DC-Central"), ("Warehouse South", "DC-Central"),
    ("DC-Central", "Store-HCM"), ("DC-Central", "Store-HN"),
    ("Store-HCM", "Customers"), ("Store-HN", "Customers"),
]

# Map node label -> (group, key) in session_state.nodes
LABEL_MAP = {
    "Supplier A": ("suppliers", "A"), "Supplier B": ("suppliers", "B"),
    "Supplier C": ("suppliers", "C"),
    "Warehouse North": ("warehouses", "North"), "Warehouse South": ("warehouses", "South"),
    "DC-Central": ("distribution", "DC-Central"),
    "Store-HCM": ("retail", "Store-HCM"), "Store-HN": ("retail", "Store-HN"),
}


def _node_color(label):
    if label == "Customers":
        return "#4c9be8"
    group, key = LABEL_MAP[label]
    return "#e8534c" if st.session_state.nodes[group][key] == "alert" else "#3fa34d"


def _network_figure():
    g = nx.DiGraph()
    g.add_edges_from(EDGES)
    edge_x, edge_y = [], []
    for a, b in EDGES:
        x0, y0 = NODES[a]; x1, y1 = NODES[b]
        edge_x += [x0, x1, None]; edge_y += [y0, y1, None]
    edge_trace = go.Scatter(x=edge_x, y=edge_y, mode="lines",
                            line=dict(width=1, color="#888"), hoverinfo="none")
    node_x = [NODES[n][0] for n in NODES]
    node_y = [NODES[n][1] for n in NODES]
    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text", text=list(NODES.keys()),
        textposition="top center", hoverinfo="text",
        marker=dict(size=28, color=[_node_color(n) for n in NODES],
                    line=dict(width=2, color="#222")),
    )
    fig = go.Figure([edge_trace, node_trace])
    fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0),
                      height=380, xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def render():
    st.header("📡 Live Monitoring", help="Tier 1-2: real-time network state and data feeds.")
    left, right = st.columns([2, 1])

    with left:
        st.subheader("Supply-Chain Network")
        st.plotly_chart(_network_figure(), use_container_width=True)
        st.caption("🟢 nominal · 🔴 anomaly · 🔵 customers. Inject a disruption (sidebar) to see a node turn red.")

    with right:
        st.subheader("Data Sources")
        feeds = {
            "GPS / IoT fleet": f"{random.randint(38, 44)} vehicles online",
            "Weather API": random.choice(["Clear", "Rain", "Flood warning"]),
            "ERP (inventory)": f"{random.randint(1180, 1240)} SKUs synced",
            "Port / Customs": random.choice(["Normal", "Congested"]),
            "Supplier APIs": f"{random.randint(3, 5)}/5 responsive",
        }
        for name, val in feeds.items():
            st.markdown(f"🟢 **{name}** — {val}")
        st.caption("Mocked streams (synthetic). Values refresh on each interaction.")

    st.markdown("---")
    st.subheader("KPIs")
    k = st.session_state.kpis
    m1, m2, m3 = st.columns(3)
    m1.metric("On-time delivery %", f"{k['On-time %']:.1f}%")
    m2.metric("Logistics cost index", f"{k['Logistics cost idx']:.1f}", help="100 = baseline")
    m3.metric("Agent response", f"{k['Avg response (min)']:.1f} min")
