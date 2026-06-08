"""Streamlit dashboard for the delivery-fleet optimizer (M7).

Glue only — all logic is in SimulationController. Run with:
    streamlit run fleet/ui/app.py

Streamlit is imported here and nowhere else, so the headless system and the test
suite never depend on it."""

import streamlit as st

from fleet.ui.controller import SimulationController
from fleet.intake.controller import IntakeController
from fleet.factory import build_transcriber


def render_intake_panel(controller) -> None:
    st.subheader("Báo cáo sự cố (giọng nói / văn bản)")
    audio = st.audio_input("Nói mô tả sự cố")               # mic
    uploaded = st.file_uploader("…hoặc tải file âm thanh", type=["wav", "mp3", "m4a"])
    text = st.text_area("…hoặc gõ mô tả", placeholder="VD: đường vào C001 ngập, xe 3 hỏng")

    if st.button("Bóc tách & xử lý"):
        ic = IntakeController(controller,
                              transcriber=build_transcriber(controller.settings))
        audio_bytes = None
        if audio is not None:
            audio_bytes = audio.getvalue()
        elif uploaded is not None:
            audio_bytes = uploaded.getvalue()
        try:
            result = ic.report(text=text or None, audio=audio_bytes)
        except Exception as exc:                            # ASR/extractor failure
            st.error(f"Không xử lý được báo cáo: {exc}")
            return

        if result.raw_text:
            st.caption(f"Đã nghe/đọc: “{result.raw_text}”")
        if not result.reports:
            st.warning("Không bóc tách được sự cố nào hợp lệ. Hãy nói/gõ rõ hơn.")
        for r in result.reports:
            st.success(f"➕ {r.event_type.value} · {r.target} · {r.severity.value}")
        for d in result.decisions:
            with st.container(border=True):
                st.markdown(f"**Quyết định:** {d['action']} — {d.get('description','')}")
                st.caption(f"+{d.get('added_delay_min', 0)} phút")


def _controller() -> SimulationController:
    if "ctrl" not in st.session_state:
        st.session_state.ctrl = SimulationController()
    return st.session_state.ctrl


def main() -> None:
    st.set_page_config(page_title="Fleet Optimizer", layout="wide")
    st.title("Realtime Delivery-Fleet Optimizer")

    ctrl = _controller()

    # --- controls ---
    c1, c2, c3 = st.columns(3)
    if c1.button("Step 1 tick"):
        ctrl.step(1)
    if c2.button("Step 5 ticks"):
        ctrl.step(5)
    if c3.button("Reset"):
        st.session_state.ctrl = SimulationController()
        ctrl = st.session_state.ctrl

    snap = ctrl.snapshot()

    # --- metrics ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Sim tick", snap["sim_tick"])
    m2.metric("Clock", snap["clock"].replace("T", " "))
    m3.metric("Pending orders", snap["pending_orders"])
    m4.metric("Pending decisions", snap["decisions"]["pending"])

    # --- vehicles map + table ---
    st.subheader("Vehicles")
    veh = snap["vehicles"]
    if veh:
        st.map([{"lat": v["lat"], "lon": v["lng"]} for v in veh])
        st.dataframe(veh, use_container_width=True)

    # --- active events ---
    st.subheader("Active events")
    st.dataframe(snap["active_events"] or [{"info": "none"}],
                 use_container_width=True)

    # --- approval queue ---
    st.subheader("Decisions awaiting approval")
    pend = snap["pending_decisions"]
    if not pend:
        st.info("No decisions awaiting approval.")
    for d in pend:
        cols = st.columns([4, 1, 1])
        cols[0].write(
            f"**{d['action']}** — {d['description']} "
            f"(+{d['added_delay_min']} min)")
        if cols[1].button("Approve", key=f"ap_{d['id']}"):
            ctrl.approve(d["id"])
            st.rerun()
        if cols[2].button("Reject", key=f"rj_{d['id']}"):
            ctrl.reject(d["id"])
            st.rerun()

    # --- field-report intake ---
    render_intake_panel(ctrl)


if __name__ == "__main__":
    main()
