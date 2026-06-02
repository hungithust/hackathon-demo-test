"""Tab 4 — Agent Core. The heart of the demo: a 4-step workflow bar, the live
reasoning log, human approval, the dispatch commands sent to node staff, and the
audit log."""

import streamlit as st
from ..state import apply_decision, reject_decision, workflow_states

_STEP_STYLE = {
    "done": ("#1e3a2f", "#3fa34d", "✓"),
    "active": ("#3a341e", "#e8c44c", "▶"),
    "pending": ("#2a2a2a", "#666", "•"),
}


def _workflow_bar():
    cols = st.columns(len(workflow_states()))
    for col, (label, state) in zip(cols, workflow_states()):
        bg, border, mark = _STEP_STYLE[state]
        col.markdown(
            f"<div style='background:{bg};border:1px solid {border};border-radius:8px;"
            f"padding:8px;text-align:center;font-size:0.85em'>"
            f"<b>{mark}</b> {label}</div>",
            unsafe_allow_html=True,
        )


def render():
    st.header("🧠 Agent Core — Reasoning, Decision & Dispatch",
              help="Tier 3-5: Claude reasons over the disruption, proposes an action, "
                   "escalates high-impact decisions for approval, then dispatches "
                   "concrete commands down to the node staff.")
    st.caption("The 4-step workflow below is the operational loop the agent intervenes in. "
               "Inject a disruption from the sidebar to run it.")

    _workflow_bar()
    st.markdown("")

    left, right = st.columns([1.3, 1])

    with left:
        st.subheader("Agent Activity Log")
        st.code("\n".join(st.session_state.log[-30:]), language="text")
        if st.session_state.llm_error:
            st.caption(f"LLM note (using fallback): {st.session_state.llm_error[:140]}")

    with right:
        st.subheader("Human Approval")
        st.caption("Direct users: supply-chain managers approving high-impact decisions.")
        if st.session_state.status == "Awaiting" and st.session_state.pending:
            p = st.session_state.pending
            st.warning("High-impact decision awaiting approval.")
            st.markdown(f"**Proposed action:**\n\n{p['action']}")
            st.markdown(f"**Estimated impact:**\n\n{p['impact']}")
            a, b = st.columns(2)
            if a.button("✅ Approve", use_container_width=True):
                apply_decision(p, approver="Ops Manager")
                st.rerun()
            if b.button("❌ Reject", use_container_width=True):
                reject_decision()
                st.rerun()
        elif st.session_state.status == "Resolved":
            st.success("Latest decision executed. Network restructured and back to nominal.")
        else:
            st.info("No decision pending. Inject a disruption to engage the agent.")

        st.markdown("---")
        st.subheader("Dispatch to Node Staff")
        st.caption("Indirect users: warehouse / driver / supplier / retail staff "
                   "receiving automatic commands (workflow step 4).")
        if st.session_state.last_dispatch:
            for cmd in st.session_state.last_dispatch:
                st.markdown(f"📨 {cmd}")
        else:
            st.caption("No commands yet. They are issued automatically once a decision executes.")

    st.markdown("---")
    st.subheader("Audit Log")
    if st.session_state.audit:
        st.dataframe(st.session_state.audit, use_container_width=True, hide_index=True)
    else:
        st.caption("No decisions yet. Every agent action is logged here for auditability.")
