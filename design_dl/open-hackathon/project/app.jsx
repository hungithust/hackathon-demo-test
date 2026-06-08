// app.jsx — control-room composition + state orchestration.

const SPEED_MS = { 1: 2000, 2: 1100, 3: 600, 4: 600 };

function App() {
  const [state, setState] = React.useState(() => initialState());
  const [playing, setPlaying] = React.useState(false);
  const [speed, setSpeed] = React.useState(2);
  const [selectedVeh, setSelectedVeh] = React.useState(null);
  const [selectedEvent, setSelectedEvent] = React.useState(null);
  const [queueView, setQueueView] = React.useState("pending");
  const tick = React.useRef(null);

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

  // auto-play loop
  React.useEffect(() => {
    if (!playing) { clearInterval(tick.current); return; }
    tick.current = setInterval(() => setState((s) => stepWorld(s)), SPEED_MS[speed] || 1100);
    return () => clearInterval(tick.current);
  }, [playing, speed]);

  const doStep = (n) => setState((s) => { let r = s; for (let i = 0; i < n; i++) r = stepWorld(r); return r; });
  const doReset = () => { setPlaying(false); setSelectedVeh(null); setSelectedEvent(null); setState(initialState()); };
  const onApprove = (id) => setState((s) => resolveDecision(s, id, "approve"));
  const onReject = (id) => setState((s) => resolveDecision(s, id, "reject"));

  const onReport = (raw) => {
    const reports = parseReport(raw, state);
    const { state: ns, events, decisions } = injectReports(state, reports);
    setState(ns);
    if (decisions.length) setQueueView("pending");
    return { raw, reports, decisions };
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
        <SimControls playing={playing} speed={speed}
          onPlay={() => setPlaying((p) => !p)} onStep={doStep} onReset={doReset} onSpeed={setSpeed}/>
      </header>

      <div className="workspace">
        <div className="col">
          <EventList state={state} selected={selectedEvent} onSelect={setSelectedEvent}/>
        </div>

        <div className="col col-center">
          <div className="panel" style={{ flex: 1, padding: 0, overflow: "hidden" }}>
            <DispatchMap state={state} selectedVeh={selectedVeh} onSelectVeh={setSelectedVeh} selectedEvent={selectedEvent}/>
          </div>
          <FleetStrip state={state} selectedVeh={selectedVeh} onSelectVeh={setSelectedVeh}/>
        </div>

        <div className="col">
          <ApprovalQueue state={state} onApprove={onApprove} onReject={onReject} view={queueView} setView={setQueueView}/>
          <VoicePanel onReport={onReport} clock={state.clock}/>
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
