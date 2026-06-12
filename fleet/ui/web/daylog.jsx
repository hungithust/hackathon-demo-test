// daylog.jsx — full-screen day review. Left: event->decision->event chain built
// from authoritative event/decision records. Right: the recorded view-model
// snapshot at that moment, re-rendered through the live DispatchMap (static).

function DayLogOverlay({ open, onClose }) {
  const [log, setLog] = React.useState(null);
  const [staticRoutes, setStaticRoutes] = React.useState([]);
  const [sel, setSel] = React.useState(0);

  React.useEffect(() => {
    if (!open) return;
    Api.daylog().then(setLog).catch((e) => console.error(e));
    Api.snapshot().then((s) => setStaticRoutes(s.routes)).catch(() => {});
  }, [open]);

  if (!open) return null;

  // Build the chain: events + decisions sorted by time.
  const items = [];
  (log ? log.events : []).forEach((e) =>
    items.push({ t: e.started_at, kind: "event", ref: e }));
  (log ? log.decisions : []).forEach((d) =>
    items.push({ t: d.timestamp, kind: "decision", ref: d }));
  items.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));

  // Find the recorded snapshot at-or-before the selected item's clock.
  const tl = log ? log.timeline : [];
  const item = items[sel];
  let snap = null;
  if (item && tl.length) {
    snap = tl[0].snapshot;
    for (const e of tl) { if (e.clock <= item.t) snap = e.snapshot; else break; }
  }
  const mapState = snap ? { ...snap, routes: staticRoutes,
    events: snap.active_events || [], decisions: snap.pending_decisions || [],
    vehicles: snap.vehicles || [], customers: snap.customers || [] } : null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal daylog" style={{ width: "92vw", height: "88vh", display: "flex" }}
        onClick={(e) => e.stopPropagation()}>
        <div style={{ width: 360, overflowY: "auto", borderRight: "1px solid var(--border)" }}>
          <div className="panel-head"><h2>Day Log</h2>
            <button className="btn ghost icon" style={{ marginLeft: "auto" }} onClick={onClose}><Icon name="x" size={15}/></button>
          </div>
          {items.map((it, i) => {
            const isEv = it.kind === "event";
            const r = it.ref;
            const label = isEv ? (EVENT_TYPES[r.event_type] || {}).label || r.event_type
                               : (ACTIONS[r.action] || {}).label || r.action;
            const col = isEv ? SEVERITY[r.severity].color : "#60a5fa";
            return (
              <div key={i} className={"event-row" + (sel === i ? " sel" : "")}
                style={{ "--ev-accent": col }} onClick={() => setSel(i)}>
                <div className="ev-main">
                  <div className="ev-top">
                    <span className="ev-type">{isEv ? "Event" : "Decision"}: {label}</span>
                  </div>
                  <div className="ev-meta">
                    <span className="ev-target">{isEv ? r.target : (r.event_id || "—")}</span>
                    <span className="ev-age mono">{fmtClock(it.t)}</span>
                  </div>
                </div>
              </div>
            );
          })}
          {items.length === 0 && <div className="empty"><div className="e-sub">No events have been logged today.</div></div>}
        </div>
        <div style={{ flex: 1, position: "relative" }}>
          {mapState ? <DispatchMap state={mapState} speed={1}/>
                    : <div className="empty" style={{ marginTop: 80 }}><div className="e-sub">Select a timeline moment to inspect the map.</div></div>}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { DayLogOverlay });
