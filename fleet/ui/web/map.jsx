// map.jsx — schematic dark dispatch map. Projects the live snapshot's real
// HCM lat/lng (depot + customers + vehicles) into a stylized district view with
// routes, pulsing event markers, and vehicles that glide between ticks.

const VB_W = 1000, VB_H = 680;
const mapRange = (v, a, b, c, d) => c + ((v - a) / (b - a || 1)) * (d - c);

function MapTip({ tip, mouse }) {
  if (!tip) return null;
  return (
    <div className="map-tip" style={{ left: mouse.x + 14, top: mouse.y + 12 }}>
      <div className="tt-id" style={{ color: tip.color }}>{tip.id}</div>
      {tip.rows.map((r, i) => (
        <div className="tt-row" key={i}><span>{r[0]}</span><span style={{ color: "#cfd6e6" }}>{r[1]}</span></div>
      ))}
    </div>
  );
}

// stylized district streets + Saigon river (deterministic backdrop, viewBox coords)
const STREETS = [
  "M40,120 C260,90 520,170 980,110", "M20,250 C300,230 600,300 990,250",
  "M60,400 C320,380 640,430 980,400", "M80,560 C360,540 660,590 980,560",
  "M180,40 C150,240 230,440 180,660", "M420,30 C400,260 460,470 430,660",
  "M650,40 C620,250 700,460 660,660", "M860,40 C840,250 900,470 870,660",
  "M120,300 C300,360 380,500 520,640",
];
const RIVER = "M1020,300 C820,360 760,470 700,560 C660,620 720,700 560,720 L1080,720 Z";

function DispatchMap({ state, selectedVeh, onSelectVeh, selectedEvent }) {
  const [tip, setTip] = React.useState(null);
  const [mouse, setMouse] = React.useState({ x: 0, y: 0 });
  const [view, setView] = React.useState({ k: 1, x: 0, y: 0 }); // zoom/pan transform
  const wrapRef = React.useRef(null);
  const svgRef = React.useRef(null);
  const drag = React.useRef(null);

  // client (px) -> viewBox user coords, accounting for preserveAspectRatio="slice"
  const toUser = (clientX, clientY) => {
    const svg = svgRef.current;
    const ctm = svg && svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0, a: 1, d: 1 };
    const inv = ctm.inverse();
    return { x: clientX * inv.a + clientY * inv.c + inv.e,
             y: clientX * inv.b + clientY * inv.d + inv.f, a: ctm.a, d: ctm.d };
  };

  const onPointerDown = (e) => {
    e.preventDefault();
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) {}
    drag.current = { x: e.clientX, y: e.clientY };
  };
  const onPointerMove = (e) => {
    const r = wrapRef.current.getBoundingClientRect();
    setMouse({ x: e.clientX - r.left, y: e.clientY - r.top });
    if (drag.current) {
      const ctm = svgRef.current.getScreenCTM();
      setView((v) => ({ ...v,
        x: v.x + (e.clientX - drag.current.x) / (ctm ? ctm.a : 1),
        y: v.y + (e.clientY - drag.current.y) / (ctm ? ctm.d : 1) }));
      drag.current = { x: e.clientX, y: e.clientY };
    }
  };
  const onPointerUp = (e) => {
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch (_) {}
    drag.current = null;
  };
  const resetView = () => setView({ k: 1, x: 0, y: 0 });

  // fixed nodes (depot + customers) plus real road geometry define the projection
  // bounds, so the layout stays stable while vehicles move and roads aren't clipped.
  const nodes = { DEPOT: { lat: state.depot.lat, lng: state.depot.lng, name: state.depot.name } };
  state.customers.forEach((c) => { nodes[c.id] = c; });
  const lats = Object.values(nodes).map((n) => n.lat);
  const lngs = Object.values(nodes).map((n) => n.lng);
  (state.routes || []).forEach((r) => (r.path || []).forEach(([lng, lat]) => { lats.push(lat); lngs.push(lng); }));
  const LAT_MIN = Math.min(...lats), LAT_MAX = Math.max(...lats);
  const LNG_MIN = Math.min(...lngs), LNG_MAX = Math.max(...lngs);
  const project = (lat, lng) => ({
    x: mapRange(lng, LNG_MIN, LNG_MAX, 230, 780),
    y: mapRange(lat, LAT_MAX, LAT_MIN, 170, 520),
  });
  const PNODES = Object.fromEntries(Object.entries(nodes).map(([k, n]) => [k, project(n.lat, n.lng)]));
  const nodeKey = (raw) => (raw || "").split("#")[0]; // strip parallel-edge suffix

  // real road geometry, keyed by edge id, projected to viewBox path strings
  const routeByEdge = {};
  (state.routes || []).forEach((r) => { routeByEdge[r.edge_id] = r.path; });
  const pathStr = (path) => (path || [])
    .map(([lng, lat], i) => { const p = project(lat, lng); return (i ? "L" : "M") + p.x.toFixed(1) + "," + p.y.toFixed(1); })
    .join(" ");
  // de-dupe A->B / B->A so the base network isn't drawn twice
  const baseRoads = [];
  const seenBase = new Set();
  (state.routes || []).forEach((r) => {
    const [a, b] = r.edge_id.split("->").map(nodeKey);
    const key = a < b ? a + "|" + b : b + "|" + a;
    if (seenBase.has(key)) return;
    seenBase.add(key);
    baseRoads.push(r);
  });

  // event marker positions: edge events ride the real road geometry's midpoint
  const eventMarks = state.events.map((e) => {
    let pt = null;
    if (e.target.includes("->")) {
      const path = routeByEdge[e.target];
      if (path && path.length) { const [lng, lat] = path[Math.floor(path.length / 2)]; pt = project(lat, lng); }
      else { const [a, b] = e.target.split("->").map(nodeKey);
        if (PNODES[a] && PNODES[b]) pt = { x: (PNODES[a].x + PNODES[b].x) / 2, y: (PNODES[a].y + PNODES[b].y) / 2 }; }
    } else if (PNODES[e.target]) pt = PNODES[e.target];
    else if (e.target[0] === "V") {
      const v = state.vehicles.find((vv) => vv.id === e.target);
      if (v) pt = project(v.lat, v.lng);
    }
    return pt ? { ...e, ...pt } : null;
  }).filter(Boolean);

  const onWheel = (e) => {
    e.preventDefault();
    const u = toUser(e.clientX, e.clientY);            // cursor in viewBox coords
    setView((v) => {
      const k = Math.max(1, Math.min(8, v.k * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      const ratio = k / v.k;
      return { k, x: u.x - ratio * (u.x - v.x), y: u.y - ratio * (u.y - v.y) };
    });
  };

  return (
    <div className="map-wrap" ref={wrapRef}
         onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
         style={{ cursor: drag.current ? "grabbing" : "grab", touchAction: "none" }}>
      <svg ref={svgRef} className="map-svg" viewBox={`0 0 ${VB_W} ${VB_H}`} preserveAspectRatio="xMidYMid slice"
           onWheel={onWheel}
           style={{ cursor: drag.current ? "grabbing" : "grab", touchAction: "none" }}>
        <defs>
          <radialGradient id="depotGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#F5C451" stopOpacity=".5"/>
            <stop offset="100%" stopColor="#F5C451" stopOpacity="0"/>
          </radialGradient>
          <filter id="soft"><feGaussianBlur stdDeviation="2.2"/></filter>
        </defs>

        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
        <path d={RIVER} fill="rgba(38,86,127,.16)" stroke="rgba(77,166,255,.12)" strokeWidth="1.5"/>

        <g stroke="#131d33" strokeWidth="1.4" fill="none" strokeLinecap="round" opacity=".35">
          {STREETS.map((d, i) => <path key={i} d={d}/>)}
        </g>

        {/* real road network (OSM / synthetic geometry) */}
        <g stroke="#26344f" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round">
          {baseRoads.map((r) => <path key={r.edge_id} d={pathStr(r.path)}/>)}
        </g>

        {/* active vehicle routes, following the real roads */}
        {state.vehicles.map((v) => {
          const path = (v.route_path && v.route_path.length >= 2)
            ? pathStr(v.route_path)
            : ((v.route_nodes || []).filter((n) => PNODES[n]).length >= 2
                ? (v.route_nodes || []).filter((n) => PNODES[n]).map((n, i) => (i ? "L" : "M") + PNODES[n].x + "," + PNODES[n].y).join(" ")
                : null);
          if (!path) return null;
          const on = selectedVeh === v.id;
          const broken = v.status === "broken";
          return (
            <path key={"r" + v.id} d={path} fill="none"
              stroke={broken ? "rgba(255,77,94,.5)" : (on ? "#7ec0ff" : "rgba(77,166,255,.45)")}
              strokeWidth={on ? 3.4 : 2.2} strokeDasharray="2 9" strokeLinecap="round"
              className="route-flow" style={{ opacity: on ? 1 : .8 }}/>
          );
        })}

        {/* event pulse markers */}
        {eventMarks.map((e) => {
          const col = SEVERITY[e.severity].color;
          const sel = selectedEvent === e.id;
          return (
            <g key={e.id} transform={`translate(${e.x},${e.y})`}
               onMouseEnter={() => setTip({ id: EVENT_TYPES[e.event_type].label, color: col,
                 rows: [["Target", e.target], ["Severity", SEVERITY[e.severity].label]] })}
               onMouseLeave={() => setTip(null)} style={{ cursor: "pointer" }}>
              <circle r="14" fill={col} opacity={sel ? .28 : .16} className="evt-pulse" style={{ animationDelay: (e.id.length % 5 * .2) + "s" }}/>
              <circle r="6.5" fill={col} opacity=".9"/>
              <circle r="6.5" fill="none" stroke="#0a0f1a" strokeWidth="1.4"/>
              {sel && <circle r="20" fill="none" stroke={col} strokeWidth="1.6" opacity=".7"/>}
            </g>
          );
        })}

        {/* customers */}
        {state.customers.map((c) => {
          const pr = PRIORITY[c.priority] || PRIORITY[4];
          const p = PNODES[c.id];
          return (
            <g key={c.id} transform={`translate(${p.x},${p.y})`}
               onMouseEnter={() => setTip({ id: c.id + " · " + c.name, color: pr.color,
                 rows: [["Type", c.type], ["Priority", pr.label], ["Open orders", c.orders]] })}
               onMouseLeave={() => setTip(null)} style={{ cursor: "pointer" }}>
              <circle r={pr.r + 4} fill={pr.color} opacity=".14"/>
              <circle r={pr.r} fill={pr.color} stroke="#0a0f1a" strokeWidth="1.5"/>
              <text className="node-label" x={pr.r + 6} y="3" fill="#aeb8cf">{c.id}</text>
            </g>
          );
        })}

        {/* depot */}
        <g transform={`translate(${PNODES.DEPOT.x},${PNODES.DEPOT.y})`}
           onMouseEnter={() => setTip({ id: "DEPOT · " + state.depot.name, color: "#F5C451",
             rows: [["Role", "Central warehouse"], ["Open orders", state.pending_orders]] })}
           onMouseLeave={() => setTip(null)} style={{ cursor: "pointer" }}>
          <circle r="34" fill="url(#depotGlow)"/>
          <rect x="-10" y="-10" width="20" height="20" rx="4" transform="rotate(45)" fill="#F5C451" stroke="#0a0f1a" strokeWidth="1.6"/>
          <text className="node-label" x="0" y="-18" textAnchor="middle" fill="#F5C451" style={{ fontWeight: 600 }}>DEPOT</text>
        </g>

        {/* vehicles */}
        {state.vehicles.map((v) => {
          const p = project(v.lat, v.lng);
          const vs = VEHICLE_STATUS[v.status] || VEHICLE_STATUS.at_depot;
          const col = vs.color;
          const broken = v.status === "broken";
          const sel = selectedVeh === v.id;
          return (
            <g key={v.id} style={{ transform: `translate(${p.x}px,${p.y}px)`, transition: "transform .85s linear", cursor: "pointer" }}
               onClick={() => onSelectVeh(sel ? null : v.id)}
               onMouseEnter={() => setTip({ id: v.id, color: col,
                 rows: [["Status", vs.label], ["Heading to", v.leg_to], ["Load", v.load_pct + "%"]] })}
               onMouseLeave={() => setTip(null)}>
              {broken && <circle r="16" fill="#FF4D5E" opacity=".22" className="evt-pulse"/>}
              {sel && <circle r="15" fill="none" stroke={col} strokeWidth="1.6" opacity=".8"/>}
              <rect x="-9" y="-9" width="18" height="18" rx="5" fill={col} stroke="#0a0f1a" strokeWidth="1.6"/>
              <g transform="translate(-6,-6) scale(.5)" stroke="#06101f" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 7h11v8H3zM14 10h4l3 3v2h-7"/><circle cx="6.5" cy="17" r="1.6"/><circle cx="17.5" cy="17" r="1.6"/>
              </g>
              <text x="0" y="22" textAnchor="middle" className="veh-marker" fill={col} style={{ fontFamily: "var(--mono)", fontSize: 8.5, fontWeight: 600 }}>{v.id}</text>
            </g>
          );
        })}
        </g>
      </svg>

      <div className="map-title">
        <Icon name="pin" size={16}/>
        <div>
          <div className="mt-name">Ho Chi Minh City — District 1</div>
          <div className="mt-sub">live dispatch · {state.vehicles.length} units</div>
        </div>
      </div>

      <div className="map-stats">
        <div className="map-stat"><div className="ms-v">{state.events.length}</div><div className="ms-l">Active events</div></div>
        <div className="map-stat"><div className="ms-v">{state.customers.length}</div><div className="ms-l">Stops</div></div>
      </div>

      <div className="legend">
        <div className="legend-row"><span className="ldot" style={{ background: "#F5C451", borderRadius: 2, transform: "rotate(45deg)" }}></span> Depot</div>
        <div className="legend-row"><span className="ldot" style={{ background: "#4DA6FF" }}></span> Customer (size = priority)</div>
        <div className="legend-row"><span className="ldot" style={{ background: "#34D399", borderRadius: 4 }}></span> Vehicle</div>
        <div className="legend-row"><span className="ldot" style={{ background: "#FF4D5E" }}></span> Active event</div>
      </div>

      <div className="map-zoom" style={{ position: "absolute", right: 14, bottom: 14, display: "flex",
        gap: 6, alignItems: "center", zIndex: 5 }}>
        <button title="Zoom out" onClick={() => setView((v) => { const k = Math.max(1, v.k / 1.3); const ratio = k / v.k; return { k, x: VB_W / 2 - ratio * (VB_W / 2 - v.x), y: VB_H / 2 - ratio * (VB_H / 2 - v.y) }; })}
          style={zbtn}>−</button>
        <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "#aeb8cf", minWidth: 34, textAlign: "center" }}>{view.k.toFixed(1)}×</span>
        <button title="Zoom in" onClick={() => setView((v) => { const k = Math.min(8, v.k * 1.3); const ratio = k / v.k; return { k, x: VB_W / 2 - ratio * (VB_W / 2 - v.x), y: VB_H / 2 - ratio * (VB_H / 2 - v.y) }; })}
          style={zbtn}>+</button>
        <button title="Reset view" onClick={resetView} style={{ ...zbtn, width: "auto", padding: "0 8px" }}>Reset</button>
      </div>

      <MapTip tip={tip} mouse={mouse}/>
    </div>
  );
}

const zbtn = {
  width: 26, height: 26, borderRadius: 6, border: "1px solid #2a3650",
  background: "rgba(12,18,32,.85)", color: "#cfd6e6", cursor: "pointer",
  fontSize: 15, lineHeight: "22px", fontWeight: 600,
};

window.DispatchMap = DispatchMap;
