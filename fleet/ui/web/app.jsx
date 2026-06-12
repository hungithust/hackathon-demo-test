// app.jsx — control-room composition + state orchestration.
// Backend-driven: every mutation calls fleet/ui/server.py and applies the
// returned snapshot. The Play loop simply steps the real simulation on a timer.

const SPEED_MS = { 1: 2000, 2: 1100, 4: 600 };

function App() {
  const [state, setState] = React.useState(() => emptyState());
  const [playing, setPlaying] = React.useState(false);
  const [speed, setSpeed] = React.useState(2);
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState({ active: true, label: "Loading control room", kind: "initial" });
  const [selectedVeh, setSelectedVeh] = React.useState(null);
  const [selectedEvent, setSelectedEvent] = React.useState(null);
  const [selectedDecision, setSelectedDecision] = React.useState(null);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [selectedOrder, setSelectedOrder] = React.useState(null);
  const [dayLogOpen, setDayLogOpen] = React.useState(false);
  const tick = React.useRef(null);
  const inflight = React.useRef(false);

  // Serialize every backend call. All mutations hit the same shared session, so a
  // Play-loop step must never overlap an approve/report — otherwise a stale step
  // snapshot (taken before the approve) can land last and resurrect a decision the
  // user already approved ("approve doesn't stick"). Manual actions wait their turn;
  // the Play loop simply skips a tick while something else is in flight.
  const runExclusive = async (fn) => {
    while (inflight.current) await new Promise((r) => setTimeout(r, 25));
    inflight.current = true;
    try { return await fn(); } finally { inflight.current = false; }
  };

  // apply a fresh snapshot, flagging newly-arrived items so they flash once
  const apply = (next) => setState((prev) => markNew(prev, next));

  // initial load from the live backend
  React.useEffect(() => {
    setLoading({ active: true, label: "Loading control room", kind: "initial" });
    Api.snapshot()
      .then(apply)
      .catch((e) => console.error(e))
      .finally(() => setLoading({ active: false, label: "", kind: "" }));
  }, []);

  // clear "_new" flags shortly after a render so animations only play once
  React.useEffect(() => {
    const hasNew = state.events.some((e) => e._new) || state.decisions.some((d) => d._new)
      || state.resolved.some((d) => d._new) || state.autoHandled.some((d) => d._new);
    if (!hasNew) return;
    const t = setTimeout(() => {
      setState((s) => {
        const strip = (arr) => arr.map((x) => (x._new ? { ...x, _new: false } : x));
        return { ...s, events: strip(s.events), decisions: strip(s.decisions),
          resolved: strip(s.resolved), autoHandled: strip(s.autoHandled) };
      });
    }, 1700);
    return () => clearTimeout(t);
  }, [state]);

  // auto-play loop: step the backend on a timer (skip if a request is in flight)
  React.useEffect(() => {
    if (!playing) { clearInterval(tick.current); return; }
    tick.current = setInterval(async () => {
      if (inflight.current) return;   // skip this tick; something else is running
      setLoading({ active: true, label: "Advancing simulation", kind: "tick" });
      try { apply(await runExclusive(() => Api.step(1))); } catch (e) { console.error(e); }
      finally { setLoading({ active: false, label: "", kind: "" }); }
    }, SPEED_MS[speed] || 1100);
    return () => clearInterval(tick.current);
  }, [playing, speed]);

  const guard = async (fn, label = "Working") => {
    if (busy) return;
    setBusy(true);
    setLoading({ active: true, label, kind: "action" });
    try { apply(await runExclusive(fn)); } catch (e) { console.error(e); }
    finally {
      setBusy(false);
      setLoading({ active: false, label: "", kind: "" });
    }
  };

  const doStep = (n) => guard(() => Api.step(n), n === 1 ? "Advancing 1 tick" : `Advancing ${n} ticks`);
  const clearSelection = () => {
    setSelectedVeh(null);
    setSelectedEvent(null);
    setSelectedDecision(null);
    setSelectedOrder(null);
  };
  const selectVehicle = (id) => {
    setSelectedVeh((cur) => cur === id ? null : id);
    setSelectedEvent(null);
    setSelectedDecision(null);
    setSelectedOrder(null);
  };
  const selectEvent = (id) => {
    setSelectedEvent((cur) => cur === id ? null : id);
    setSelectedVeh(null);
    setSelectedDecision(null);
    setSelectedOrder(null);
  };
  const selectDecision = (id) => {
    setSelectedDecision((cur) => cur === id ? null : id);
    setSelectedEvent(null);
    setSelectedVeh(null);
    setSelectedOrder(null);
  };
  const selectOrder = (id) => {
    setSelectedOrder((cur) => cur === id ? null : id);
    setSelectedDecision(null);
    setSelectedEvent(null);
    setSelectedVeh(null);
  };

  const doReset = () => { setPlaying(false); clearSelection(); guard(() => Api.reset(), "Resetting world"); };
  const onApprove = (id) => guard(async () => { const snap = await Api.approve(id); setSelectedDecision(null); return snap; }, "Applying recommendation");
  const onReject = (id) => guard(async () => { const snap = await Api.reject(id); setSelectedDecision(null); return snap; }, "Rejecting recommendation");
  const onDispatch = (body) => guard(() => Api.dispatch(body), "Dispatching orders");

  const onReport = async (raw) => {
    setBusy(true);
    setLoading({ active: true, label: "Parsing field report", kind: "action" });
    try {
      const res = await runExclusive(() => Api.report(raw));
      apply(res.state);
      if (res.decisions && res.decisions.length) setSelectedDecision(res.decisions[0].id);
      return res; // { raw, reports, decisions, state }
    } finally {
      setBusy(false);
      setLoading({ active: false, label: "", kind: "" });
    }
  };

  const onReportAudio = async (blob) => {
    setBusy(true);
    setLoading({ active: true, label: "Transcribing field report", kind: "action" });
    try {
      const res = await runExclusive(() => Api.reportAudio(blob));
      apply(res.state);
      if (res.decisions && res.decisions.length) setSelectedDecision(res.decisions[0].id);
      return res;
    } finally {
      setBusy(false);
      setLoading({ active: false, label: "", kind: "" });
    }
  };

  return (
    <div className={"app" + (loading.active ? " is-loading" : "")}>
      <header className="header">
        <div className="brand">
          <div className="brand-mark"><Icon name="truck" size={20} sw={1.6}/></div>
          <div>
            <div className="brand-name">FleetOps <span style={{ color: "var(--accent)" }}>·</span> Control Room</div>
            <div className="brand-sub">AI Real-time Dispatch</div>
          </div>
          <div style={{ marginLeft: 14 }} className={"live-dot" + (playing ? "" : " paused")}>
            <i></i>{playing ? "Live" : "Paused"}
          </div>
          <LoadingIndicator loading={loading}/>
        </div>
        <KPIBar state={state}/>
        <button className="btn ghost" onClick={() => setDayLogOpen(true)} title="Open day log">
          <Icon name="clock" size={15}/> Day Log
        </button>
        <SimControls playing={playing} speed={speed}
          onPlay={() => setPlaying((p) => !p)} onStep={doStep} onReset={doReset} onSpeed={setSpeed}
          onOpenSettings={() => setSettingsOpen(true)} busy={busy || loading.kind === "initial"}/>
      </header>

      <main className="ops-layout">
        <aside className="queue-rail">
          <OperationsQueue
            state={state}
            selectedDecision={selectedDecision}
            selectedEvent={selectedEvent}
            selectedOrder={selectedOrder}
            selectedVeh={selectedVeh}
            onSelectDecision={selectDecision}
            onSelectEvent={selectEvent}
            onSelectOrder={selectOrder}
            onSelectVeh={selectVehicle}
            onDispatch={onDispatch}
            busy={busy}
          />
        </aside>

        <section className="map-workspace">
          <div className="map-shell panel">
            <DispatchMap
              state={state}
              speed={speed}
              selectedVeh={selectedVeh}
              onSelectVeh={selectVehicle}
              selectedEvent={selectedEvent}
              selectedOrder={selectedOrder}
              selectedDecision={selectedDecision}
            />
            <MapLoadingOverlay loading={loading}/>
          </div>
          <FleetStrip state={state} selectedVeh={selectedVeh} onSelectVeh={selectVehicle}/>
        </section>

        <aside className="context-rail">
          <ContextDrawer
            state={state}
            selectedVeh={selectedVeh}
            selectedEvent={selectedEvent}
            selectedDecision={selectedDecision}
            selectedOrder={selectedOrder}
            onApprove={onApprove}
            onReject={onReject}
            onClear={clearSelection}
            busy={busy}
          />
          <VoicePanel onReport={onReport} onReportAudio={onReportAudio} clock={state.clock} busy={busy}/>
        </aside>
      </main>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)}
        onApplied={(snap) => { setPlaying(false); apply(snap); }}/>
      <DayLogOverlay open={dayLogOpen} onClose={() => setDayLogOpen(false)}/>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
