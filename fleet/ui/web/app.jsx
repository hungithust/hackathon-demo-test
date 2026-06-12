// app.jsx — control-room composition + state orchestration.
// Backend-driven: every mutation calls fleet/ui/server.py and applies the
// returned snapshot. The Play loop simply steps the real simulation on a timer.

const SPEED_MS = { 1: 2000, 2: 1100, 4: 600 };

function App() {
  const [state, setState] = React.useState(() => emptyState());
  const [playing, setPlaying] = React.useState(false);
  const [speed, setSpeed] = React.useState(2);
  const [busy, setBusy] = React.useState(false);
  const [selectedVeh, setSelectedVeh] = React.useState(null);
  const [selectedEvent, setSelectedEvent] = React.useState(null);
  const [queueView, setQueueView] = React.useState("pending");
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [leftTab, setLeftTab] = React.useState("events"); // events | inbox | progress
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
  React.useEffect(() => { Api.snapshot().then(apply).catch((e) => console.error(e)); }, []);

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
      try { apply(await runExclusive(() => Api.step(1))); } catch (e) { console.error(e); }
    }, SPEED_MS[speed] || 1100);
    return () => clearInterval(tick.current);
  }, [playing, speed]);

  const guard = async (fn) => {
    if (busy) return;
    setBusy(true);
    try { apply(await runExclusive(fn)); } catch (e) { console.error(e); } finally { setBusy(false); }
  };

  const doStep = (n) => guard(() => Api.step(n));
  const doReset = () => { setPlaying(false); setSelectedVeh(null); setSelectedEvent(null); guard(() => Api.reset()); };
  const onApprove = (id) => guard(() => Api.approve(id));
  const onReject = (id) => guard(() => Api.reject(id));
  const onDispatch = (body) => guard(() => Api.dispatch(body));

  const onReport = async (raw) => {
    const res = await runExclusive(() => Api.report(raw));
    apply(res.state);
    if (res.decisions && res.decisions.length) setQueueView("pending");
    return res; // { raw, reports, decisions, state }
  };

  const onReportAudio = async (blob) => {
    const res = await runExclusive(() => Api.reportAudio(blob));
    apply(res.state);
    if (res.decisions && res.decisions.length) setQueueView("pending");
    return res;
  };

  return (
    <div className="app">
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
        </div>
        <KPIBar state={state}/>
        <button className="btn ghost" onClick={() => setDayLogOpen(true)} title="Nhật ký ngày">
          <Icon name="clock" size={15}/> Nhật ký ngày
        </button>
        <SimControls playing={playing} speed={speed}
          onPlay={() => setPlaying((p) => !p)} onStep={doStep} onReset={doReset} onSpeed={setSpeed}
          onOpenSettings={() => setSettingsOpen(true)}/>
      </header>

      <div className="workspace">
        <div className="col">
          <div className="toggle-tabs" style={{ margin: "0 0 8px" }}>
            <button className={leftTab === "events" ? "on" : ""} onClick={() => setLeftTab("events")}>Sự kiện</button>
            <button className={leftTab === "inbox" ? "on" : ""} onClick={() => setLeftTab("inbox")}>Đơn tới <span className="count">{state.inbox.length}</span></button>
            <button className={leftTab === "progress" ? "on" : ""} onClick={() => setLeftTab("progress")}>Tiến trình</button>
          </div>
          {leftTab === "events" && <EventList state={state} selected={selectedEvent} onSelect={setSelectedEvent}/>}
          {leftTab === "inbox" && <InboxPanel state={state} onDispatch={onDispatch}/>}
          {leftTab === "progress" && <ProgressPanel state={state} selectedVeh={selectedVeh} selectedOrder={selectedOrder} onSelectOrder={setSelectedOrder}/>}
        </div>

        <div className="col col-center">
          <div className="panel" style={{ flex: 1, padding: 0, overflow: "hidden" }}>
            <DispatchMap state={state} speed={speed} selectedVeh={selectedVeh} onSelectVeh={setSelectedVeh} selectedEvent={selectedEvent} selectedOrder={selectedOrder}/>
          </div>
          <FleetStrip state={state} selectedVeh={selectedVeh} onSelectVeh={setSelectedVeh}/>
        </div>

        <div className="col">
          <ApprovalQueue state={state} onApprove={onApprove} onReject={onReject} view={queueView} setView={setQueueView}/>
          <VoicePanel onReport={onReport} onReportAudio={onReportAudio} clock={state.clock}/>
        </div>
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)}
        onApplied={(snap) => { setPlaying(false); apply(snap); }}/>
      <DayLogOverlay open={dayLogOpen} onClose={() => setDayLogOpen(false)}/>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
