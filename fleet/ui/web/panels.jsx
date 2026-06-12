// panels.jsx — KPI bar, sim controls, event list, approval queue, fleet strip, voice panel.

function SeverityChip({ sev }) {
  const s = SEVERITY[sev];
  return <span className={"sev-chip " + s.cls}><span className="sev-dot" style={{ background: s.color }}></span>{s.label}</span>;
}
function EngineBadge({ engine }) {
  const e = ENGINES[engine] || ENGINES.rule_based;
  return <span className={"engine-badge " + engine} title={e.full}><Icon name="spark" size={11}/>{e.label}</span>;
}

function stripHtml(html) {
  const div = document.createElement("div");
  div.innerHTML = html || "";
  return div.textContent || div.innerText || "";
}

function routePreview(nodes) {
  const stops = (nodes || []).filter((n) => n !== "DEPOT" && !/^D\d+$/.test(n));
  if (!stops.length) return "No route change";
  return stops.slice(0, 3).join(" -> ") + (stops.length > 3 ? ` -> +${stops.length - 3}` : "");
}

function LoadingIndicator({ loading }) {
  if (!loading || !loading.active) return null;
  return (
    <div className={"loading-pill " + (loading.kind || "")}>
      <span className="mini-spinner"></span>
      <span>{loading.label || "Working"}</span>
    </div>
  );
}

function MapLoadingOverlay({ loading }) {
  if (!loading || !loading.active) return null;
  return (
    <div className={"map-loading " + (loading.kind || "")}>
      <div className="map-loading-card">
        <span className="loader-ring"></span>
        <span>{loading.label || "Syncing"}</span>
      </div>
    </div>
  );
}

// ---------------- KPI BAR ----------------
function KPIBar({ state }) {
  const pending = state.decisions.length;
  return (
    <div className="kpis">
      <div className="kpi">
        <div className="k-label">Sim Tick</div>
        <div className="k-val mono">{String(state.sim_tick).padStart(3, "0")}</div>
      </div>
      <div className="kpi clock-kpi">
        <div className="k-label">Sim Clock</div>
        <div className="k-val mono">{fmtClock(state.clock)}<span className="k-unit">{fmtDate(state.clock)}</span></div>
      </div>
      <div className="kpi">
        <div className="k-label">Pending Orders</div>
        <div className="k-val mono">{pendingOrders(state)}</div>
      </div>
      <div className={"kpi" + (pending > 0 ? " alert pulse" : "")}>
        <div className="k-label">Awaiting Approval</div>
        <div className="k-val mono">{pending}</div>
      </div>
    </div>
  );
}

// ---------------- SIM CONTROLS ----------------
function SimControls({ playing, speed, onPlay, onStep, onReset, onSpeed, onOpenSettings, busy = false }) {
  return (
    <div className="simctl">
      <button className={"btn " + (playing ? "pausebtn" : "play")} onClick={onPlay} title={playing ? "Pause" : "Play"}>
        <Icon name={playing ? "pause" : "play"} size={15}/>{playing ? "Pause" : "Play"}
      </button>
      <div className="speed">
        {[1, 2, 4].map((s) => (
          <button key={s} className={speed === s ? "on" : ""} onClick={() => onSpeed(s)}>{s}×</button>
        ))}
      </div>
      <button className="btn ghost icon" onClick={() => onStep(1)} disabled={busy} title="Step 1 tick"><Icon name="step" size={15}/></button>
      <button className="btn ghost icon" onClick={() => onStep(5)} disabled={busy} title="Step 5 ticks"><Icon name="step5" size={15}/></button>
      <button className="btn ghost icon" onClick={onReset} disabled={busy} title="Reset world"><Icon name="reset" size={15}/></button>
      <button className="btn ghost icon" onClick={onOpenSettings} disabled={busy} title="Settings"><Icon name="gear" size={15}/></button>
    </div>
  );
}

// ---------------- OPERATIONS QUEUE ----------------
function OperationsQueue({
  state,
  selectedDecision,
  selectedEvent,
  selectedOrder,
  selectedVeh,
  onSelectDecision,
  onSelectEvent,
  onSelectOrder,
  onSelectVeh,
  onDispatch,
  busy = false,
}) {
  const [view, setView] = React.useState("review");
  const reviewCount = state.decisions.length;
  const activeEvents = [...state.events].sort((a, b) => SEVERITY[b.severity].rank - SEVERITY[a.severity].rank);
  const inProgress = state.ordersInProgress || [];
  const tabs = [
    { id: "review", label: "Review", count: reviewCount },
    { id: "events", label: "Events", count: activeEvents.length },
    { id: "orders", label: "Orders", count: state.inbox.length },
    { id: "progress", label: "Progress", count: inProgress.length },
  ];

  return (
    <div className="panel ops-queue">
      <div className="panel-head queue-head">
        <Icon name="inbox" size={16} style={{ color: "var(--accent)" }}/>
        <div>
          <h2>Operations Queue</h2>
          <div className="panel-sub">Prioritized work for the dispatcher</div>
        </div>
      </div>

      <div className="queue-tabs">
        {tabs.map((t) => (
          <button key={t.id} className={view === t.id ? "on" : ""} onClick={() => setView(t.id)}>
            <span>{t.label}</span>
            <b>{t.count}</b>
          </button>
        ))}
      </div>

      <div className="panel-body queue-body">
        {view === "review" && (
          reviewCount === 0 ? (
            <QueueEmpty icon="check" title="No decisions waiting" text="Recommendations inside the tolerance are applied automatically."/>
          ) : state.decisions.map((d) => (
            <DecisionQueueItem
              key={d.id}
              dec={d}
              state={state}
              selected={selectedDecision === d.id}
              onSelect={() => onSelectDecision(d.id)}
            />
          ))
        )}

        {view === "events" && (
          activeEvents.length === 0 ? (
            <QueueEmpty icon="check" title="Network is clear" text="No active disruptions are currently reported."/>
          ) : activeEvents.map((e) => (
            <EventQueueItem
              key={e.id}
              event={e}
              clock={state.clock}
              selected={selectedEvent === e.id}
              onSelect={() => onSelectEvent(e.id)}
            />
          ))
        )}

        {view === "orders" && <InboxPanel state={state} onDispatch={onDispatch} selectedOrder={selectedOrder} onSelectOrder={onSelectOrder} embedded busy={busy}/>}

        {view === "progress" && (
          inProgress.length === 0 ? (
            <QueueEmpty icon="truck" title="No active deliveries" text="Dispatch incoming orders to start a delivery run."/>
          ) : inProgress.map((o) => (
            <ProgressQueueItem
              key={o.vehicle_id + ":" + o.customer_id}
              order={o}
              selected={selectedOrder === o.customer_id || selectedVeh === o.vehicle_id}
              onSelect={() => onSelectOrder(o.customer_id)}
              onSelectVeh={() => onSelectVeh(o.vehicle_id)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function QueueEmpty({ icon, title, text }) {
  return (
    <div className="empty compact">
      <div className="e-ico"><Icon name={icon} size={22}/></div>
      <div className="e-title">{title}</div>
      <div className="e-sub">{text}</div>
    </div>
  );
}

function DecisionQueueItem({ dec, state, selected, onSelect }) {
  const a = ACTIONS[dec.action] || ACTIONS.reroute;
  const evt = state.events.find((e) => e.id === dec.event_id);
  const affected = dec.proposed_routes ? Object.keys(dec.proposed_routes).length : 0;
  return (
    <button className={"queue-item decision" + (selected ? " sel" : "") + (dec._new ? " flash-in" : "")}
      style={{ "--qi": a.color }} onClick={onSelect}>
      <span className="qi-icon"><Icon name={a.icon} size={16}/></span>
      <span className="qi-main">
        <span className="qi-title">{a.label} proposal</span>
        <span className="qi-sub">{stripHtml(dec.description) || "Review the recommended action"}</span>
        <span className="qi-meta">
          <span>+{Math.round(dec.added_delay_min)} min</span>
          {affected > 0 && <span>{affected} vehicle{affected === 1 ? "" : "s"}</span>}
          {evt && <span>{EVENT_TYPES[evt.event_type]?.label || evt.event_type}</span>}
        </span>
      </span>
      <EngineBadge engine={dec.engine}/>
    </button>
  );
}

function EventQueueItem({ event, clock, selected, onSelect }) {
  const et = EVENT_TYPES[event.event_type] || EVENT_TYPES.traffic;
  const sev = SEVERITY[event.severity] || SEVERITY.low;
  return (
    <button className={"queue-item" + (selected ? " sel" : "") + (event._new ? " flash-in" : "")}
      style={{ "--qi": sev.color }} onClick={onSelect}>
      <span className="qi-icon"><Icon name={et.icon} size={16}/></span>
      <span className="qi-main">
        <span className="qi-title">{et.label}</span>
        <span className="qi-sub">{event.target}</span>
        <span className="qi-meta"><span>{sev.label}</span><span>{fmtAge(event.started_at, clock)}</span></span>
      </span>
      <SeverityChip sev={event.severity}/>
    </button>
  );
}

function ProgressQueueItem({ order, selected, onSelect, onSelectVeh }) {
  const st = ORDER_STATUS[order.status] || ORDER_STATUS.queued;
  return (
    <button className={"queue-item" + (selected ? " sel" : "")} style={{ "--qi": st.color }} onClick={onSelect}>
      <span className="qi-icon"><Icon name="truck" size={16}/></span>
      <span className="qi-main">
        <span className="qi-title">{order.customer_id} · {order.name}</span>
        <span className="qi-sub">{st.label} · stop {order.sequence}/{order.stops_total}</span>
        <span className="qi-meta">
          <span className="linkish" onClick={(e) => { e.stopPropagation(); onSelectVeh(); }}>{order.vehicle_id}</span>
          <span>{Math.round(order.demand_kg)} kg</span>
        </span>
      </span>
    </button>
  );
}

// ---------------- EVENT LIST ----------------
function EventList({ state, selected, onSelect }) {
  const sorted = [...state.events].sort((a, b) => SEVERITY[b.severity].rank - SEVERITY[a.severity].rank);
  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-head">
        <Icon name="spark" size={15} style={{ color: "var(--sev-high)" }}/>
        <h2>Active Events</h2>
        <span className="count">{state.events.length}</span>
      </div>
      <div className="panel-body">
        {sorted.length === 0 ? (
          <div className="empty">
            <div className="e-ico"><Icon name="check" size={22}/></div>
            <div className="e-title">All clear</div>
            <div className="e-sub">No active disruptions in the network right now.</div>
          </div>
        ) : sorted.map((e) => {
          const et = EVENT_TYPES[e.event_type];
          const col = SEVERITY[e.severity].color;
          return (
            <div key={e.id} className={"event-row" + (selected === e.id ? " sel" : "") + (e._new ? " flash-in" : "")}
              style={{ "--ev-accent": col }} onClick={() => onSelect(selected === e.id ? null : e.id)}>
              <div className="ev-ico"><Icon name={et.icon} size={18}/></div>
              <div className="ev-main">
                <div className="ev-top">
                  <span className="ev-type">{et.label}</span>
                  <SeverityChip sev={e.severity}/>
                </div>
                <div className="ev-meta">
                  <span className="ev-target">{e.target}</span>
                  <span className="ev-age mono">{fmtAge(e.started_at, state.clock)}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------- DECISION CARD ----------------
function DecisionCard({ dec, state, onApprove, onReject }) {
  const a = ACTIONS[dec.action];
  const heavy = dec.added_delay_min >= 30;
  const evt = state.events.find((e) => e.id === dec.event_id);
  const affectedVids = dec.proposed_routes ? Object.keys(dec.proposed_routes) : [];
  return (
    <div className={"dec-card" + (heavy ? " crit" : "") + (dec._new ? " attention flash-in" : "")}
      style={{ "--dc-accent": a.color, "--dc-accent-bg": a.bg }}>
      <div className="dec-top">
        <span className="dec-action"><span className="a-ico"><Icon name={a.icon} size={15}/></span>{a.label}</span>
        <EngineBadge engine={dec.engine}/>
        {evt && <span style={{ marginLeft: "auto" }}><SeverityChip sev={evt.severity}/></span>}
      </div>
      <div className="dec-desc" dangerouslySetInnerHTML={{ __html: dec.description }}/>

      {/* Affected vehicles + proposed route preview */}
      {affectedVids.length > 0 && (
        <div style={{ marginTop: 8, padding: "8px 10px", background: "rgba(34,197,94,.07)", borderRadius: 6, border: "1px solid rgba(34,197,94,.18)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6, fontSize: 11, color: "#4ade80", fontWeight: 600 }}>
            <Icon name="truck" size={12}/>
            {affectedVids.length} affected vehicle{affectedVids.length === 1 ? "" : "s"} · proposed route:
          </div>
          {Object.entries(dec.proposed_routes).map(([vid, nodes]) => {
            const stops = (nodes || []).filter(n => n !== "DEPOT" && !/^D\d+$/.test(n));
            const preview = stops.length > 0
              ? stops.slice(0, 3).join(" -> ") + (stops.length > 3 ? ` -> +${stops.length - 3}` : "")
              : "No route change";
            return (
              <div key={vid} style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 3, fontSize: 10.5 }}>
                <span style={{ fontFamily: "var(--mono)", color: "#60a5fa", background: "rgba(59,130,246,.12)", borderRadius: 4, padding: "1px 5px", flexShrink: 0 }}>{vid}</span>
                <span style={{ color: "var(--text-3)", fontFamily: "var(--mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>→ {preview}</span>
              </div>
            );
          })}
          <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-4)", fontStyle: "italic" }}>
            Green paths on the map show the proposed route.
          </div>
        </div>
      )}

      <div className="dec-impact">
        <div className={"impact-pill delay" + (heavy ? " heavy" : "")}>
          <span className="iv mono">+{Math.round(dec.added_delay_min)}</span>
          <span className="il">min added delay</span>
        </div>
        {evt && <span className="tag">{EVENT_TYPES[evt.event_type].label}</span>}
      </div>
      <div className="dec-actions">
        <button className="dec-btn approve" onClick={() => onApprove(dec.id)}><Icon name="check" size={15}/>Approve</button>
        <button className="dec-btn reject" onClick={() => onReject(dec.id)}><Icon name="x" size={15}/>Reject</button>
      </div>
      <div className="dec-meta">
        <Icon name="clock" size={12}/><span>{fmtAge(dec.timestamp, state.clock) === "now" ? "Proposed just now" : "Proposed " + fmtAge(dec.timestamp, state.clock) + " ago"}</span>
        <span style={{ marginLeft: "auto" }} className="mono">{dec.event_id || "—"}</span>
      </div>
    </div>
  );
}

// ---------------- APPROVAL QUEUE ----------------
function ApprovalQueue({ state, onApprove, onReject, view, setView }) {
  const pending = state.decisions;
  return (
    <div className="panel" style={{ flex: "1 1 auto" }}>
      <div className="panel-head">
        <Icon name="inbox" size={16} style={{ color: "var(--accent)" }}/>
        <h2>Approval Queue</h2>
        {pending.length > 0 && <span className="count" style={{ color: "#FF8A95", borderColor: "rgba(255,77,94,.4)", background: "rgba(255,77,94,.1)" }}>{pending.length} pending</span>}
        <div className="toggle-tabs">
          <button className={view === "pending" ? "on" : ""} onClick={() => setView("pending")}>Pending</button>
          <button className={view === "resolved" ? "on" : ""} onClick={() => setView("resolved")}>Resolved</button>
          <button className={view === "auto" ? "on" : ""} onClick={() => setView("auto")}>Auto</button>
        </div>
      </div>
      <div className="panel-body pad">
        {view === "pending" && (pending.length === 0 ? (
          <div className="empty">
            <div className="e-ico"><Icon name="check" size={22}/></div>
            <div className="e-title">Nothing to approve</div>
            <div className="e-sub">The AI is handling everything within tolerance. You'll be alerted when a big change needs sign-off.</div>
          </div>
        ) : pending.map((d) => <DecisionCard key={d.id} dec={d} state={state} onApprove={onApprove} onReject={onReject}/>))}

        {view === "resolved" && (state.resolved.length === 0 ? (
          <div className="empty"><div className="e-ico"><Icon name="clock" size={22}/></div><div className="e-title">No decisions yet</div><div className="e-sub">Approved and rejected items will appear here.</div></div>
        ) : state.resolved.map((d) => (
          <div key={d.id} className={"dec-resolved " + d.status + (d._new ? " flash-in" : "")}>
            <div className="rico"><Icon name={d.status === "approved" ? "check" : "x"} size={13}/></div>
            <div className="rtxt"><b>{ACTIONS[d.action].label}</b> · {d.status} <span className="mono" style={{ color: "var(--text-4)" }}>· +{Math.round(d.added_delay_min)}m</span></div>
            <EngineBadge engine={d.engine}/>
          </div>
        )))}

        {view === "auto" && (state.autoHandled.length === 0 ? (
          <div className="empty"><div className="e-ico"><Icon name="spark" size={22}/></div><div className="e-title">No auto-actions</div><div className="e-sub">Low-impact fixes (&lt; {DELAY_THRESHOLD} min) are applied automatically and logged here.</div></div>
        ) : (<>
          <div style={{ fontSize: 11, color: "var(--text-3)", marginBottom: 10, lineHeight: 1.5 }}>
            Applied automatically — impact below the {DELAY_THRESHOLD}-minute threshold.
          </div>
          {state.autoHandled.map((d) => (
            <div key={d.id} className={"auto-item" + (d._new ? " flash-in" : "")}>
              <span className="aico"><Icon name={ACTIONS[d.action].icon} size={15}/></span>
              <div style={{ flex: 1 }}>
                <div><b style={{ color: "var(--text)" }}>{ACTIONS[d.action].label}</b> <span className="mono" style={{ color: "var(--ok)" }}>+{Math.round(d.added_delay_min)}m</span></div>
                <div dangerouslySetInnerHTML={{ __html: d.description }} style={{ marginTop: 2 }}/>
              </div>
            </div>
          ))}
        </>))}
      </div>
    </div>
  );
}

// ---------------- FLEET STRIP ----------------
function FleetStrip({ state, selectedVeh, onSelectVeh }) {
  return (
    <div className="panel" style={{ flexShrink: 0 }}>
      <div className="panel-head">
        <Icon name="truck" size={15} style={{ color: "var(--text-2)" }}/>
        <h2>Fleet</h2>
        <span className="count">{state.vehicles.length} units</span>
      </div>
      <div className="fleet-strip">
        {state.vehicles.map((v) => {
          const st = VEHICLE_STATUS[v.status];
          return (
            <div key={v.id} className={"veh-card" + (selectedVeh === v.id ? " sel" : "")} style={{ "--vs": st.color }}
              onClick={() => onSelectVeh(selectedVeh === v.id ? null : v.id)}>
              <div className="veh-top">
                <span className="veh-id">{v.id}</span>
                <span className="veh-stat"><i></i>{st.short}</span>
              </div>
              <div className="veh-sub"><span>→ {v.leg_to}</span><span className="mono">{v.load_pct}%</span></div>
              <div className="veh-bar"><i style={{ width: v.load_pct + "%" }}></i></div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------- VOICE / FIELD REPORT ----------------
function VoicePanel({ onReport, onReportAudio, clock, busy = false }) {
  const [text, setText] = React.useState("");
  const [phase, setPhase] = React.useState("idle"); // idle | rec | processing
  const [result, setResult] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [collapsed, setCollapsed] = React.useState(false);
  const recRef = React.useRef(null);   // MediaRecorder
  const chunksRef = React.useRef([]);

  const run = (raw) => {
    if (!raw.trim()) return;
    setPhase("processing"); setResult(null); setError(null);
    setTimeout(async () => {
      try { const r = await onReport(raw); setResult(r); }
      catch (e) { setError(e.message); }
      finally { setPhase("idle"); }
    }, 250);
  };

  // Real mic capture: getUserMedia -> MediaRecorder -> blob -> /api/report_audio
  const startRec = async () => {
    setResult(null); setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        setPhase("processing");
        try { const r = await onReportAudio(blob); setResult(r); if (r.raw) setText(r.raw); }
        catch (e) { setError(e.message); }
        finally { setPhase("idle"); }
      };
      recRef.current = rec;
      rec.start();
      setPhase("rec");
    } catch (e) {
      setError("Microphone unavailable: " + e.message);
      setPhase("idle");
    }
  };

  const toggleMic = () => {
    if (phase === "rec") {
      try { recRef.current && recRef.current.stop(); } catch (e) {}
    } else if (phase === "idle") {
      startRec();
    }
  };

  return (
    <div className="panel" style={{ flexShrink: 0 }}>
      <div className="panel-head">
        <Icon name="mic" size={15} style={{ color: "var(--accent)" }}/>
        <h2>Field Report</h2>
        <span className="count">voice · text</span>
        <button className="btn ghost icon" style={{ marginLeft: "auto" }}
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? "Expand Field Report" : "Collapse Field Report"}>
          <Icon name="chevron" size={15}
            style={{ transform: collapsed ? "rotate(90deg)" : "rotate(-90deg)", transition: ".15s" }}/>
        </button>
      </div>
      {!collapsed && (
      <div className="voice">
        <div className="voice-tools">
          <button className={"mic-btn" + (phase === "rec" ? " rec" : "")} onClick={toggleMic} disabled={busy && phase !== "rec"} title={phase === "rec" ? "Click to stop & transcribe" : "Click to record (RIVA ASR)"}>
            <Icon name={phase === "rec" ? "waves" : "mic"} size={18}/>
          </button>
          {phase === "rec" ? (
            <div className="waveform live">{Array.from({ length: 22 }).map((_, i) => <i key={i} style={{ animationDelay: (i * 0.05) + "s" }}/>)}</div>
          ) : (
            <div className="voice-input" style={{ flex: 1 }}>
              <textarea value={text} placeholder="Describe an incident — e.g. “Road into C001 is flooded, vehicle V003 broke down”"
                onChange={(e) => setText(e.target.value)} rows={2}/>
            </div>
          )}
        </div>

        {phase !== "rec" && (
          <div className="examples">
            {VOICE_EXAMPLES.map((ex, i) => (
              <span key={i} className="ex-chip" onClick={() => setText(ex)}>{ex.length > 34 ? ex.slice(0, 32) + "…" : ex}</span>
            ))}
          </div>
        )}

        <button className="btn primary" style={{ justifyContent: "center" }} disabled={busy || phase !== "idle" || !text.trim()} onClick={() => run(text)}>
          {phase === "processing" ? <><Icon name="reset" size={14} className="spin"/>Parsing…</> : <><Icon name="bolt" size={14}/>Extract &amp; dispatch</>}
        </button>

        {error && (
          <div style={{ fontSize: 12, color: "var(--danger, #e5484d)", marginTop: 4 }}>{error}</div>
        )}

        {result && (
          <div className="intake-flow">
            <div className="flow-step" style={{ animationDelay: "0s" }}>
              <div className="flow-label"><Icon name="waves" size={12}/>Recognised</div>
              <div className="heard">“{result.raw}”</div>
            </div>
            <div className="flow-step" style={{ animationDelay: ".12s" }}>
              <div className="flow-label"><Icon name="spark" size={12}/>Extracted incidents · {result.reports.length}</div>
              {result.reports.length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--text-3)" }}>No valid incident parsed — try naming a customer (C001–C004) or vehicle (V001–V003).</div>
              ) : (
                <div className="extract-chips">
                  {result.reports.map((r, i) => {
                    const col = SEVERITY[r.severity].color;
                    return (
                      <span key={i} className="xchip" style={{ borderColor: col + "66" }}>
                        <Icon name={EVENT_TYPES[r.event_type].icon} size={14}/>
                        <span className="xt" style={{ color: col }}>{EVENT_TYPES[r.event_type].label}</span>
                        <span className="xtarget">{r.target}</span>
                        <span className="sev-dot" style={{ background: col }}></span>
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
            {result.decisions.length > 0 && (
              <div className="flow-step" style={{ animationDelay: ".24s" }}>
                <div className="flow-label"><Icon name="inbox" size={12}/>Sent to approval queue · {result.decisions.length}</div>
                <div style={{ fontSize: 12, color: "var(--text-2)" }}>
                  {result.decisions.map((d) => ACTIONS[d.action].label).join(" · ")} — awaiting your sign-off in the queue.
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      )}
    </div>
  );
}

// ---------------- INBOX (incoming orders) ----------------
function InboxPanel({ state, onDispatch, selectedOrder, onSelectOrder, embedded = false, busy = false }) {
  const [sel, setSel] = React.useState(() => new Set());
  const toggle = (id) => setSel((s) => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n;
  });
  const rows = state.inbox;
  return (
    <div className={embedded ? "embedded-panel" : "panel"} style={{ flex: 1 }}>
      {!embedded && <div className="panel-head">
        <Icon name="inbox" size={15} style={{ color: "var(--accent)" }}/>
        <h2>Incoming Orders</h2>
        <span className="count">{rows.length}</span>
      </div>}
      <div className="panel-body pad">
        {rows.length === 0 ? (
          <div className="empty"><div className="e-ico"><Icon name="check" size={22}/></div>
            <div className="e-title">No pending orders</div>
            <div className="e-sub">All available orders have been dispatched.</div></div>
        ) : rows.map((r) => (
          <label key={r.customer_id} className={"order-row" + (sel.has(r.customer_id) || selectedOrder === r.customer_id ? " sel" : "")}
            style={{ display: "flex", gap: 8, alignItems: "center", padding: "8px 6px", borderBottom: "1px solid var(--border)", cursor: "pointer" }}
            onClick={() => onSelectOrder && onSelectOrder(r.customer_id)}>
            <input type="checkbox" checked={sel.has(r.customer_id)} onChange={() => toggle(r.customer_id)}/>
            <span className="mono" style={{ color: "#60a5fa" }}>{r.customer_id}</span>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
            <span className="tag">P{r.priority}</span>
            <span className="mono" style={{ color: "var(--text-3)" }}>{r.total_qty}</span>
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, padding: 10, borderTop: "1px solid var(--border)" }}>
        <button className="btn" disabled={busy || sel.size === 0}
          onClick={() => { onDispatch({ customer_ids: [...sel] }); setSel(new Set()); }}>
          {busy ? <><span className="mini-spinner"></span>Dispatching</> : <>Dispatch Selected ({sel.size})</>}
        </button>
        <button className="btn primary" style={{ marginLeft: "auto" }} disabled={busy || rows.length === 0}
          onClick={() => onDispatch({ all: true })}>{busy ? <><span className="mini-spinner dark"></span>Dispatching</> : "Dispatch All"}</button>
      </div>
    </div>
  );
}

const ORDER_STATUS = {
  queued:    { label: "Waiting for vehicle", color: "#94a3b8" },
  en_route:  { label: "Out for delivery",    color: "#f59e0b" },
  delivered: { label: "Delivered",           color: "#22c55e" },
};

// ---------------- ORDER PROGRESS ----------------
function ProgressPanel({ state, selectedVeh, selectedOrder, onSelectOrder }) {
  let rows = state.ordersInProgress;
  if (selectedVeh) rows = rows.filter((o) => o.vehicle_id === selectedVeh);  // vehicle -> its orders
  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-head">
        <Icon name="truck" size={15} style={{ color: "var(--text-2)" }}/>
        <h2>Progress{selectedVeh ? " · " + selectedVeh : ""}</h2>
        <span className="count">{rows.length}</span>
      </div>
      <div className="panel-body">
        {rows.length === 0 ? (
          <div className="empty"><div className="e-ico"><Icon name="inbox" size={22}/></div>
            <div className="e-title">No active deliveries</div>
            <div className="e-sub">Select incoming orders and dispatch them to vehicles.</div></div>
        ) : rows.map((o) => {
          const st = ORDER_STATUS[o.status];
          const isSel = selectedOrder === o.customer_id;
          return (
            <div key={o.vehicle_id + ":" + o.customer_id}
              className={"event-row" + (isSel ? " sel" : "")}
              style={{ "--ev-accent": st.color }}
              onClick={() => onSelectOrder(isSel ? null : o.customer_id)}>
              <div className="ev-main">
                <div className="ev-top">
                  <span className="ev-type">{o.customer_id} · {o.name}</span>
                  <span className="tag" style={{ color: st.color }}>{st.label}</span>
                </div>
                <div className="ev-meta">
                  <span className="mono" style={{ color: "#60a5fa" }}>{o.vehicle_id}</span>
                  <span className="mono">stop {o.sequence}/{o.stops_total}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {selectedOrder && <OrderDetail state={state} cid={selectedOrder}/>}
    </div>
  );
}

// ---------------- ORDER DETAIL ----------------
function OrderDetail({ state, cid }) {
  const o = state.ordersInProgress.find((x) => x.customer_id === cid);
  if (!o) return null;
  const st = ORDER_STATUS[o.status];
  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: 10, fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>{o.customer_id} · {o.name}</div>
      <div className="tt-row"><span>Assigned vehicle</span><span className="mono" style={{ color: "#60a5fa" }}>{o.vehicle_id}</span></div>
      <div className="tt-row"><span>Status</span><span style={{ color: st.color }}>{st.label}</span></div>
      <div className="tt-row"><span>Stop order</span><span className="mono">{o.sequence}/{o.stops_total}</span></div>
      <div className="tt-row"><span>Load</span><span className="mono">{Math.round(o.demand_kg)} kg</span></div>
      <div className="tt-row"><span>Planned arrival</span><span className="mono">{o.planned_arrival ? fmtClock(o.planned_arrival) : "—"}</span></div>
      <div className="tt-row"><span>Actual arrival</span><span className="mono">{o.actual_arrival ? fmtClock(o.actual_arrival) : "—"}</span></div>
    </div>
  );
}

// ---------------- CONTEXT DRAWER ----------------
function ContextDrawer({ state, selectedVeh, selectedEvent, selectedDecision, selectedOrder, onApprove, onReject, onClear, busy = false }) {
  const dec = selectedDecision ? state.decisions.find((d) => d.id === selectedDecision) : null;
  const evt = selectedEvent ? state.events.find((e) => e.id === selectedEvent) : null;
  const veh = selectedVeh ? state.vehicles.find((v) => v.id === selectedVeh) : null;
  const order = selectedOrder ? state.ordersInProgress.find((o) => o.customer_id === selectedOrder) : null;

  let body = <SystemSummary state={state}/>;
  if (dec) body = <DecisionDetail dec={dec} state={state} onApprove={onApprove} onReject={onReject} busy={busy}/>;
  else if (evt) body = <EventDetail event={evt} state={state}/>;
  else if (veh) body = <VehicleDetail vehicle={veh} state={state}/>;
  else if (order) body = <OrderContext order={order}/>;

  return (
    <div className="panel context-panel">
      <div className="panel-head">
        <Icon name={dec ? "spark" : evt ? (EVENT_TYPES[evt.event_type]?.icon || "traffic") : veh ? "truck" : order ? "inbox" : "pin"} size={16} style={{ color: "var(--accent)" }}/>
        <div>
          <h2>{dec ? "Recommendation" : evt ? "Event Details" : veh ? "Vehicle Details" : order ? "Order Details" : "System Summary"}</h2>
          <div className="panel-sub">{dec || evt || veh || order ? "Focused action context" : "Current operating picture"}</div>
        </div>
        {(dec || evt || veh || order) && (
          <button className="btn ghost icon" style={{ marginLeft: "auto" }} onClick={onClear} title="Clear selection">
            <Icon name="x" size={15}/>
          </button>
        )}
      </div>
      <div className="panel-body pad context-body">{body}</div>
    </div>
  );
}

function SystemSummary({ state }) {
  const pending = state.decisions.length;
  const auto = state.autoHandled.length;
  return (
    <>
      <div className={"hero-status" + (pending ? " warn" : "")}>
        <div className="hs-kicker">{pending ? "Action needed" : "All systems steady"}</div>
        <div className="hs-title">{pending ? `${pending} recommendation${pending === 1 ? "" : "s"} waiting` : "No operator approval required"}</div>
        <div className="hs-text">{pending ? "Review the highest-impact proposal in the queue." : "The fleet is operating within the configured tolerance."}</div>
      </div>
      <div className="detail-grid">
        <Metric label="Active events" value={state.events.length}/>
        <Metric label="Pending orders" value={state.pending_orders}/>
        <Metric label="Vehicles" value={state.vehicles.length}/>
        <Metric label="Auto actions" value={auto}/>
      </div>
      <RecentActivity state={state}/>
    </>
  );
}

function DecisionDetail({ dec, state, onApprove, onReject, busy = false }) {
  const action = ACTIONS[dec.action] || ACTIONS.reroute;
  const event = state.events.find((e) => e.id === dec.event_id);
  const affected = dec.proposed_routes ? Object.entries(dec.proposed_routes) : [];
  const heavy = dec.added_delay_min >= 30;
  return (
    <>
      <div className={"hero-status" + (heavy ? " danger" : "")}>
        <div className="hs-kicker">{action.label}</div>
        <div className="hs-title">Review before applying</div>
        <div className="hs-text" dangerouslySetInnerHTML={{ __html: dec.description }}/>
      </div>
      <div className="detail-grid">
        <Metric label="Added delay" value={"+" + Math.round(dec.added_delay_min) + "m"} tone={heavy ? "danger" : "warn"}/>
        <Metric label="Affected vehicles" value={affected.length}/>
        <Metric label="Engine" value={(ENGINES[dec.engine] || ENGINES.rule_based).label}/>
        <Metric label="Event" value={dec.event_id || "None"}/>
      </div>
      {event && (
        <div className="detail-section">
          <div className="section-title">Why this appeared</div>
          <div className="detail-line"><span>Event</span><b>{EVENT_TYPES[event.event_type]?.label || event.event_type}</b></div>
          <div className="detail-line"><span>Target</span><b className="mono">{event.target}</b></div>
          <div className="detail-line"><span>Severity</span><SeverityChip sev={event.severity}/></div>
        </div>
      )}
      {affected.length > 0 && (
        <div className="detail-section">
          <div className="section-title">Proposed route changes</div>
          {affected.map(([vid, nodes]) => (
            <div key={vid} className="route-preview-row">
              <span className="mono">{vid}</span>
              <b>{routePreview(nodes)}</b>
            </div>
          ))}
          <div className="hint">Green paths on the map are proposals. Blue paths remain the committed routes until approval.</div>
        </div>
      )}
      <div className="sticky-actions">
        <button className="dec-btn approve" disabled={busy} onClick={() => onApprove(dec.id)}>
          {busy ? <><span className="mini-spinner"></span>Applying</> : <><Icon name="check" size={15}/>Approve</>}
        </button>
        <button className="dec-btn reject" disabled={busy} onClick={() => onReject(dec.id)}>
          {busy ? <><span className="mini-spinner"></span>Working</> : <><Icon name="x" size={15}/>Reject</>}
        </button>
      </div>
    </>
  );
}

function EventDetail({ event, state }) {
  const et = EVENT_TYPES[event.event_type] || EVENT_TYPES.traffic;
  const decisions = state.decisions.filter((d) => d.event_id === event.id);
  return (
    <>
      <div className="hero-status danger">
        <div className="hs-kicker">{SEVERITY[event.severity]?.label || event.severity}</div>
        <div className="hs-title">{et.label}</div>
        <div className="hs-text">{et.blurb}</div>
      </div>
      <div className="detail-section">
        <div className="detail-line"><span>Target</span><b className="mono">{event.target}</b></div>
        <div className="detail-line"><span>Started</span><b>{fmtAge(event.started_at, state.clock)} ago</b></div>
        <div className="detail-line"><span>Open recommendations</span><b>{decisions.length}</b></div>
      </div>
      {decisions.length > 0 && (
        <div className="detail-section">
          <div className="section-title">Linked recommendations</div>
          {decisions.map((d) => <div key={d.id} className="route-preview-row"><span>{ACTIONS[d.action]?.label || d.action}</span><b>+{Math.round(d.added_delay_min)}m</b></div>)}
        </div>
      )}
    </>
  );
}

function VehicleDetail({ vehicle }) {
  const st = VEHICLE_STATUS[vehicle.status] || VEHICLE_STATUS.at_depot;
  const stops = (vehicle.route_nodes || []).filter((n) => n !== "DEPOT");
  return (
    <>
      <div className="hero-status">
        <div className="hs-kicker">{st.label}</div>
        <div className="hs-title">{vehicle.id}</div>
        <div className="hs-text">Heading to {vehicle.leg_to || "next stop"} with {vehicle.load_pct}% load.</div>
      </div>
      <div className="detail-grid">
        <Metric label="Load" value={vehicle.load_pct + "%"}/>
        <Metric label="Next stop" value={vehicle.leg_to || "None"}/>
        <Metric label="Route stops" value={stops.length}/>
        <Metric label="Status" value={st.short}/>
      </div>
      <div className="detail-section">
        <div className="section-title">Committed route</div>
        <div className="route-string mono">{(vehicle.route_nodes || []).join(" -> ") || "No assigned route"}</div>
      </div>
    </>
  );
}

function OrderContext({ order }) {
  const st = ORDER_STATUS[order.status] || ORDER_STATUS.queued;
  return (
    <>
      <div className="hero-status">
        <div className="hs-kicker">{st.label}</div>
        <div className="hs-title">{order.customer_id}</div>
        <div className="hs-text">{order.name}</div>
      </div>
      <div className="detail-section">
        <div className="detail-line"><span>Vehicle</span><b className="mono">{order.vehicle_id}</b></div>
        <div className="detail-line"><span>Stop order</span><b>{order.sequence}/{order.stops_total}</b></div>
        <div className="detail-line"><span>Load</span><b>{Math.round(order.demand_kg)} kg</b></div>
        <div className="detail-line"><span>Planned arrival</span><b>{order.planned_arrival ? fmtClock(order.planned_arrival) : "Not scheduled"}</b></div>
      </div>
    </>
  );
}

function RecentActivity({ state }) {
  const items = [
    ...state.resolved.slice(0, 3).map((d) => ({ kind: "Decision", label: `${ACTIONS[d.action]?.label || d.action} ${d.status}`, meta: "+" + Math.round(d.added_delay_min) + "m" })),
    ...state.autoHandled.slice(0, 3).map((d) => ({ kind: "Auto", label: ACTIONS[d.action]?.label || d.action, meta: "+" + Math.round(d.added_delay_min) + "m" })),
  ].slice(0, 4);
  return (
    <div className="detail-section">
      <div className="section-title">Recent activity</div>
      {items.length === 0 ? <div className="hint">No decisions have been applied yet.</div> : items.map((it, i) => (
        <div key={i} className="detail-line"><span>{it.kind}</span><b>{it.label} <span className="mono muted">{it.meta}</span></b></div>
      ))}
    </div>
  );
}

function Metric({ label, value, tone }) {
  return (
    <div className={"metric" + (tone ? " " + tone : "")}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

Object.assign(window, {
  KPIBar, SimControls, EventList, ApprovalQueue, FleetStrip, VoicePanel,
  SeverityChip, EngineBadge, InboxPanel, ProgressPanel, OrderDetail,
  OperationsQueue, ContextDrawer, LoadingIndicator, MapLoadingOverlay,
});
