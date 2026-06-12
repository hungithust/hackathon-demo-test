// panels.jsx — KPI bar, sim controls, event list, approval queue, fleet strip, voice panel.

function SeverityChip({ sev }) {
  const s = SEVERITY[sev];
  return <span className={"sev-chip " + s.cls}><span className="sev-dot" style={{ background: s.color }}></span>{s.label}</span>;
}
function EngineBadge({ engine }) {
  const e = ENGINES[engine] || ENGINES.rule_based;
  return <span className={"engine-badge " + engine} title={e.full}><Icon name="spark" size={11}/>{e.label}</span>;
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
function SimControls({ playing, speed, onPlay, onStep, onReset, onSpeed, onOpenSettings }) {
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
      <button className="btn ghost icon" onClick={() => onStep(1)} title="Step 1 tick"><Icon name="step" size={15}/></button>
      <button className="btn ghost icon" onClick={() => onStep(5)} title="Step 5 ticks"><Icon name="step5" size={15}/></button>
      <button className="btn ghost icon" onClick={onReset} title="Reset world"><Icon name="reset" size={15}/></button>
      <button className="btn ghost icon" onClick={onOpenSettings} title="Settings"><Icon name="gear" size={15}/></button>
    </div>
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
            {affectedVids.length} xe bị ảnh hưởng — tuyến mới:
          </div>
          {Object.entries(dec.proposed_routes).map(([vid, nodes]) => {
            const stops = (nodes || []).filter(n => n !== "DEPOT" && !/^D\d+$/.test(n));
            const preview = stops.length > 0
              ? stops.slice(0, 3).join(" → ") + (stops.length > 3 ? ` →+${stops.length - 3}` : "")
              : "(không đổi)";
            return (
              <div key={vid} style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 3, fontSize: 10.5 }}>
                <span style={{ fontFamily: "var(--mono)", color: "#60a5fa", background: "rgba(59,130,246,.12)", borderRadius: 4, padding: "1px 5px", flexShrink: 0 }}>{vid}</span>
                <span style={{ color: "var(--text-3)", fontFamily: "var(--mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>→ {preview}</span>
              </div>
            );
          })}
          <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-4)", fontStyle: "italic" }}>
            Tuyến màu xanh lá trên bản đồ là tuyến đề xuất
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
function VoicePanel({ onReport, onReportAudio, clock }) {
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
          title={collapsed ? "Mở rộng Field Report" : "Thu nhỏ Field Report"}>
          <Icon name="chevron" size={15}
            style={{ transform: collapsed ? "rotate(90deg)" : "rotate(-90deg)", transition: ".15s" }}/>
        </button>
      </div>
      {!collapsed && (
      <div className="voice">
        <div className="voice-tools">
          <button className={"mic-btn" + (phase === "rec" ? " rec" : "")} onClick={toggleMic} title={phase === "rec" ? "Click to stop & transcribe" : "Click to record (RIVA ASR)"}>
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

        <button className="btn primary" style={{ justifyContent: "center" }} disabled={phase !== "idle" || !text.trim()} onClick={() => run(text)}>
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

Object.assign(window, { KPIBar, SimControls, EventList, ApprovalQueue, FleetStrip, VoicePanel, SeverityChip, EngineBadge });
