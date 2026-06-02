"""Tab 3 — Predictive Optimization. Mocked demand forecast (Prophet/XGBoost style)
with a confidence band and a predicted bottleneck the agent can act on proactively."""

import datetime as dt
import numpy as np
import plotly.graph_objects as go
import streamlit as st


def _forecast():
    rng = np.random.default_rng(7)
    hist_days = 14
    fc_days = 10
    base = 100
    today = dt.date.today()

    hist_x = [today - dt.timedelta(days=hist_days - i) for i in range(hist_days)]
    season = 12 * np.sin(np.arange(hist_days) / 2.0)
    hist_y = base + season + rng.normal(0, 4, hist_days) + np.arange(hist_days) * 1.2

    fc_x = [today + dt.timedelta(days=i) for i in range(fc_days)]
    trend = hist_y[-1] + np.arange(fc_days) * 2.4
    fc_season = 12 * np.sin((np.arange(fc_days) + hist_days) / 2.0)
    fc_y = trend + fc_season
    # inject a forecast bottleneck on day 2 (~48h)
    fc_y[2] += 60
    band = 8 + np.arange(fc_days) * 1.5
    return hist_x, hist_y, fc_x, fc_y, band


def _figure():
    hist_x, hist_y, fc_x, fc_y, band = _forecast()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist_x, y=hist_y, mode="lines",
                             name="Actual demand", line=dict(color="#3fa34d")))
    fig.add_trace(go.Scatter(x=fc_x, y=fc_y + band, mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="none"))
    fig.add_trace(go.Scatter(x=fc_x, y=fc_y - band, mode="lines", fill="tonexty",
                             fillcolor="rgba(76,155,232,0.18)", line=dict(width=0),
                             name="Confidence band"))
    fig.add_trace(go.Scatter(x=fc_x, y=fc_y, mode="lines",
                             name="Forecast", line=dict(color="#4c9be8", dash="dash")))
    fig.add_trace(go.Scatter(x=[fc_x[2]], y=[fc_y[2]], mode="markers+text",
                             text=["⚠ bottleneck"], textposition="top center",
                             marker=dict(size=12, color="#e8534c"),
                             name="Predicted bottleneck"))
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0),
                      legend=dict(orientation="h", y=1.1),
                      yaxis_title="Demand (units/day)")
    return fig


def render():
    st.header("🔮 Predictive Optimization",
              help="Tier 3: forecasts demand 7-14 days ahead to act before disruptions happen.")
    st.caption("Mocked Prophet/XGBoost forecast. In production this feeds Claude's context "
               "so the agent can act proactively, not just reactively.")

    st.plotly_chart(_figure(), use_container_width=True)

    st.warning("**Predicted bottleneck in ~48h:** demand for SKU-1024 is forecast to exceed "
               "Warehouse North capacity by ~35%.")
    c1, c2 = st.columns([1, 2])
    if c1.button("⚙️ Let the agent act proactively", type="primary"):
        st.session_state.queued_scenario = "Demand Spike"
        st.success("Queued a proactive 'Demand Spike' response. Open the **Agent Core** tab "
                   "and inject it to see the agent restructure ahead of time.")
    c2.caption("This pre-loads the matching scenario so the team can demo proactive (vs reactive) action.")
