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
  const tick = React.useRef(null);
  const inflight = React.useRef(false);

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
      if (inflight.current) return;
      inflight.current = true;
      try { apply(await Api.step(1)); } catch (e) { console.error(e); }
      finally { inflight.current = false; }
    }, SPEED_MS[speed] || 1100);
    return () => clearInterval(tick.current);
  }, [playing, speed]);

  const guard = async (fn) => {
    if (busy) return;
    setBusy(true);
    try { apply(await fn()); } catch (e) { console.error(e); } finally { setBusy(false); }
  };

  const doStep = (n) => guard(() => Api.step(n));
  const doReset = () => { setPlaying(false); setSelectedVeh(null); setSelectedEvent(null); guard(() => Api.reset()); };
  const onApprove = (id) => guard(() => Api.approve(id));
  const onReject = (id) => guard(() => Api.reject(id));

  const onReport = async (raw) => {
    const res = await Api.report(raw);
    apply(res.state);
    if (res.decisions && res.decisions.length) setQueueView("pending");
    return res; // { raw, reports, decisions, state }
  };

  const onReportAudio = async (blob) => {
    const res = await Api.reportAudio(blob);
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
        <SimControls playing={playing} speed={speed}
          onPlay={() => setPlaying((p) => !p)} onStep={doStep} onReset={doReset} onSpeed={setSpeed}
          onOpenSettings={() => setSettingsOpen(true)}/>
      </header>

      <div className="workspace">
        <div className="col">
          <EventList state={state} selected={selectedEvent} onSelect={setSelectedEvent}/>
        </div>

        <div className="col col-center">
          <div className="panel" style={{ flex: 1, padding: 0, overflow: "hidden" }}>
            <DispatchMap state={state} speed={speed} selectedVeh={selectedVeh} onSelectVeh={setSelectedVeh} selectedEvent={selectedEvent}/>
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
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
