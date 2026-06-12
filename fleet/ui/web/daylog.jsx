// daylog.jsx — full-screen day review. Left: event->decision->event chain built
// from authoritative event/decision records. Right: the recorded view-model
// snapshot at that moment, re-rendered through the live DispatchMap (static).

function DayLogOverlay({ open, onClose }) {
  const [log, setLog] = React.useState(null);
  const [staticRoutes, setStaticRoutes] = React.useState([]);
  const [sel, setSel] = React.useState(null);

  React.useEffect(() => {
    if (!open) return;
    setLog(null);
    setSel(null);
    Api.daylog().then((next) => {
      setLog(next);
      const count = (next.timeline || []).length;
      setSel(count ? count - 1 : null);
    }).catch((e) => console.error(e));
    Api.snapshot().then((s) => setStaticRoutes(s.routes)).catch(() => {});
  }, [open]);

  if (!open) return null;

  // Build operator moments from recorded snapshots, then annotate each moment
  // with the events/decisions that happened since the previous snapshot.
  const changes = [];
  (log ? log.events : []).forEach((e) =>
    changes.push({ t: e.started_at, kind: "event", ref: e }));
  (log ? log.decisions : []).forEach((d) =>
    changes.push({ t: d.timestamp, kind: "decision", ref: d }));
  changes.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));

  const tl = log ? log.timeline : [];
  const items = tl.map((entry, i) => {
    const prevClock = i > 0 ? tl[i - 1].clock : null;
    const momentChanges = changes.filter((c) => (!prevClock || c.t > prevClock) && c.t <= entry.clock);
    return { ...entry, changes: momentChanges };
  });
  const safeSel = items.length ? Math.min(sel === null ? items.length - 1 : sel, items.length - 1) : null;
  const item = safeSel === null ? null : items[safeSel];
  const snap = item ? item.snapshot : null;
  const mapState = snap ? { ...snap, routes: staticRoutes,
    events: snap.active_events || [], decisions: snap.pending_decisions || [],
    vehicles: snap.vehicles || [], customers: snap.customers || [] } : null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal daylog" style={{ width: "92vw", height: "88vh", display: "flex", flexDirection: "row", minHeight: 0 }}
        onClick={(e) => e.stopPropagation()}>
        <div className="daylog-list" style={{ width: 380, flexShrink: 0, overflowY: "auto", borderRight: "1px solid var(--border)" }}>
          <div className="panel-head"><h2>Day Log</h2>
            <button className="btn ghost icon" style={{ marginLeft: "auto" }} onClick={onClose}><Icon name="x" size={15}/></button>
          </div>
          {items.map((it, i) => {
            const primary = it.changes[0];
            const isEv = primary && primary.kind === "event";
            const r = primary && primary.ref;
            const label = !primary ? "Simulation snapshot"
              : isEv ? (EVENT_TYPES[r.event_type] || {}).label || r.event_type
              : (ACTIONS[r.action] || {}).label || r.action;
            const col = !primary ? "var(--accent)"
              : isEv ? SEVERITY[r.severity].color : "#60a5fa";
            return (
              <div key={it.seq ?? i} className={"event-row" + (safeSel === i ? " sel" : "")}
                style={{ "--ev-accent": col }} onClick={() => setSel(i)}>
                <div className="ev-main">
                  <div className="ev-top">
                    <span className="ev-type">{label}</span>
                    <span className="tag">Tick {it.sim_tick}</span>
                  </div>
                  <div className="ev-meta">
                    <span className="ev-target">{primary ? (isEv ? r.target : (r.event_id || "Decision")) : "Fleet state"}</span>
                    <span className="ev-age mono">{fmtClock(it.clock)}</span>
                  </div>
                  {it.changes.length > 1 && <div className="ev-meta"><span className="tag">+{it.changes.length - 1} more change{it.changes.length === 2 ? "" : "s"}</span></div>}
                </div>
              </div>
            );
          })}
          {log === null && <div className="empty"><span className="loader-ring"></span><div className="e-sub">Loading day log...</div></div>}
          {log !== null && items.length === 0 && <div className="empty"><div className="e-sub">No snapshots have been logged yet.</div></div>}
        </div>
        <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
          {mapState ? <DispatchMap state={mapState} speed={1}/>
                    : <div className="empty" style={{ marginTop: 80 }}><div className="e-sub">Select a timeline moment to inspect the map.</div></div>}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { DayLogOverlay });
