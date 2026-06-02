"""Tab 4 — Agent Core. The heart of the demo: anomaly → Claude reasoning →
proposed action → human approval → audit log."""

import streamlit as st
from ..state import apply_decision, reject_decision


def render():
    st.header("🧠 Agent Core — Reasoning & Decision",
              help="Tier 3-5: Claude reasons over the disruption, proposes an action, "
                   "and escalates high-impact decisions for human approval.")
    st.caption("Inject a disruption from the sidebar, then watch the agent reason and act here.")

    left, right = st.columns([1.3, 1])

    with left:
        st.subheader("Agent Activity Log")
        st.code("\n".join(st.session_state.log[-26:]), language="text")
        if st.session_state.llm_error:
            st.caption(f"LLM note (using fallback): {st.session_state.llm_error[:140]}")

    with right:
        st.subheader("Human Approval")
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
    st.subheader("Audit Log")
    if st.session_state.audit:
        st.dataframe(st.session_state.audit, use_container_width=True, hide_index=True)
    else:
        st.caption("No decisions yet. Every agent action is logged here for auditability.")
