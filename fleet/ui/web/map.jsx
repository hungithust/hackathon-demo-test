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

const RIVER = "M1020,300 C820,360 760,470 700,560 C660,620 720,700 560,720 L1080,720 Z";
const SPEED_MS = { 1: 2000, 2: 1100, 4: 600 };

function DispatchMap({ state, speed = 2, selectedVeh, onSelectVeh, selectedEvent }) {
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
    e.target.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY };
  };

  const onPointerMove = (e) => {
    if (wrapRef.current) {
      const r = wrapRef.current.getBoundingClientRect();
      setMouse({ x: e.clientX - r.left, y: e.clientY - r.top });
    }
    if (drag.current) {
      const wrap = wrapRef.current;
      const scaleX = wrap ? wrap.clientWidth / VB_W : 1;
      const scaleY = wrap ? wrap.clientHeight / VB_H : 1;
      const dx = e.clientX - drag.current.x;
      const dy = e.clientY - drag.current.y;
      setView((v) => {
        let nx = v.x + dx / scaleX;
        let ny = v.y + dy / scaleY;
        if (isNaN(nx) || !isFinite(nx)) nx = v.x;
        if (isNaN(ny) || !isFinite(ny)) ny = v.y;
        return { ...v, x: nx, y: ny };
      });
      drag.current = { x: e.clientX, y: e.clientY };
    }
  };

  const onPointerUp = (e) => {
    drag.current = null;
    try {
      if (e.target.hasPointerCapture(e.pointerId)) {
        e.target.releasePointerCapture(e.pointerId);
      }
    } catch(err) {}
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

  // Returns an SVG path string for a short segment centered on the road
  const getEventPathStr = (path) => {
    if (!path || path.length < 2) return null;
    const pts = path.map(([lng, lat]) => project(lat, lng));
    let totalLen = 0;
    const lens = [0];
    for (let i = 1; i < pts.length; i++) {
      const dx = pts[i].x - pts[i-1].x;
      const dy = pts[i].y - pts[i-1].y;
      totalLen += Math.sqrt(dx*dx + dy*dy);
      lens.push(totalLen);
    }
    const targetLen = Math.min(60, totalLen * 0.9); // 60px or 90% of edge
    const midDist = totalLen / 2;
    const startDist = Math.max(0, midDist - targetLen / 2);
    const endDist = Math.min(totalLen, midDist + targetLen / 2);

    const getPtAtDist = (d) => {
      if (d <= 0) return pts[0];
      if (d >= totalLen) return pts[pts.length-1];
      for(let i=1; i<pts.length; i++) {
        if (lens[i] >= d) {
          const segLen = lens[i] - lens[i-1];
          if (segLen === 0) return pts[i];
          const t = (d - lens[i-1]) / segLen;
          return {
            x: pts[i-1].x + (pts[i].x - pts[i-1].x) * t,
            y: pts[i-1].y + (pts[i].y - pts[i-1].y) * t
          };
        }
      }
      return pts[pts.length-1];
    };

    const pStart = getPtAtDist(startDist);
    const pEnd = getPtAtDist(endDist);
    
    let pathStr = `M${pStart.x.toFixed(1)},${pStart.y.toFixed(1)}`;
    for (let i = 1; i < pts.length - 1; i++) {
       if (lens[i] > startDist && lens[i] < endDist) {
          pathStr += ` L${pts[i].x.toFixed(1)},${pts[i].y.toFixed(1)}`;
       }
    }
    pathStr += ` L${pEnd.x.toFixed(1)},${pEnd.y.toFixed(1)}`;
    return pathStr;
  };
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

  // Map events by node-pair key for route coloring (so parallel edges share the overlay)
  const eventByKey = {};
  state.events.forEach(e => {
    if (e.target.includes("->")) {
       const [a, b] = e.target.split("->").map(nodeKey);
       const key = a < b ? a + "|" + b : b + "|" + a;
       eventByKey[key] = e;
    }
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
         onPointerDown={onPointerDown} 
         onPointerMove={onPointerMove}
         onPointerUp={onPointerUp}
         onPointerCancel={onPointerUp}
         onWheel={onWheel}
         style={{ cursor: drag.current ? "grabbing" : "grab", touchAction: "none" }}>
      <svg ref={svgRef} className="map-svg" viewBox={`0 0 ${VB_W} ${VB_H}`} preserveAspectRatio="xMidYMid slice">
        <defs>
          <radialGradient id="depotGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#F5C451" stopOpacity=".5"/>
            <stop offset="100%" stopColor="#F5C451" stopOpacity="0"/>
          </radialGradient>
          <filter id="soft"><feGaussianBlur stdDeviation="2.2"/></filter>
        </defs>

        {/* Capture pointer events in empty space */}
        <rect width={VB_W} height={VB_H} fill="transparent" />

        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
        <path d={RIVER} fill="#aadaff" stroke="#90c2e7" strokeWidth="1"/>

        {/* Active route road network outline — only edges used in current plans */}
        <g stroke="#b8a96a" strokeWidth="7" fill="none" strokeLinecap="round" strokeLinejoin="round">
          {baseRoads.map((r) => <path key={r.edge_id + "-bg"} d={pathStr(r.path)}/>)}
        </g>
        {/* Active route road network fill */}
        <g stroke="#fef4ac" strokeWidth="4.5" fill="none" strokeLinecap="round" strokeLinejoin="round">
          {baseRoads.map((r) => <path key={r.edge_id} d={pathStr(r.path)}/>)}
        </g>

        {/* event affected roads (traffic/floods overlay) */}
        <g fill="none" strokeLinecap="round" strokeLinejoin="round">
          {baseRoads.map((r) => {
             const [a, b] = r.edge_id.split("->").map(nodeKey);
             const key = a < b ? a + "|" + b : b + "|" + a;
             const ev = eventByKey[key];
             if (!ev) return null;
             const color = ev.event_type === "flooded_area" ? "#3b82f6" : "#FF4D5E";
             return (
               <path key={r.edge_id + "-evt"} d={getEventPathStr(r.path) || pathStr(r.path)} 
                 stroke={color} strokeWidth={6.0} opacity={0.8}
                 style={{ cursor: "pointer" }}
                 onMouseEnter={() => setTip({ id: EVENT_TYPES[ev.event_type]?.label || ev.event_type, color: color,
                   rows: [["Target", ev.target], ["Severity", SEVERITY[ev.severity]?.label || ev.severity]] })}
                 onMouseLeave={() => setTip(null)}
               />
             );
          })}
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
              stroke={broken ? "rgba(255,77,94,.8)" : (on ? "#3b82f6" : "rgba(59,130,246,.6)")}
              strokeWidth={on ? 4.0 : 3.0} strokeDasharray="4 10" strokeLinecap="round"
              className="route-flow" style={{ opacity: on ? 1 : .8 }}/>
          );
        })}

        {/* proposed vehicle routes (dashed green preview for pending reroute decisions) */}
        {(state.decisions || []).map((d) => {
           if (!d.proposed_paths) return null;
           return Object.entries(d.proposed_paths).map(([vid, path]) => {
               if (!path || path.length < 2) return null;
               const pathD = pathStr(path);
               return (
                 <g key={`prop-${d.id}-${vid}`}>
                   <path d={pathD} stroke="#22c55e" strokeWidth="6" strokeDasharray="10,7" fill="none" opacity="0.35"/>
                   <path d={pathD} stroke="#4ade80" strokeWidth="2.5" strokeDasharray="10,7" fill="none" opacity="0.9" className="route-flow"/>
                 </g>
               );
           });
        })}

        {/* vehicle return paths — dashed amber line while vehicle animates back to DEPOT after reroute */}
        {state.vehicles.map((v) => {
          if (!v.return_path || v.return_path.length < 2) return null;
          const d = pathStr(v.return_path);
          return (
            <g key={"ret" + v.id}>
              <path d={d} stroke="#f59e0b" strokeWidth="5" strokeDasharray="6,5" fill="none" opacity="0.35"/>
              <path d={d} stroke="#fbbf24" strokeWidth="2" strokeDasharray="6,5" fill="none" opacity="0.85" className="route-flow"/>
            </g>
          );
        })}

        {/* event pulse markers (only for node/vehicle events) */}
        {eventMarks.map((e) => {
          if (e.target.includes("->")) return null; // Edge events are drawn as colored paths instead
          const col = SEVERITY[e.severity]?.color || "#FF4D5E";
          const sel = selectedEvent === e.id;
          return (
            <g key={e.id} transform={`translate(${e.x},${e.y})`}
               onMouseEnter={() => setTip({ id: EVENT_TYPES[e.event_type]?.label || e.event_type, color: col,
                 rows: [["Target", e.target], ["Severity", SEVERITY[e.severity]?.label || e.severity]] })}
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
          const isDone = c.delivered;
          const fillColor = isDone ? "#ffffff" : pr.color;
          const strokeColor = isDone ? "#94a3b8" : "#ffffff";
          const p = PNODES[c.id];
          return (
            <g key={c.id} transform={`translate(${p.x},${p.y})`}
               onMouseEnter={() => setTip({ id: c.id + " · " + c.name, color: fillColor,
                 rows: [["Type", c.type], ["Status", isDone ? "Delivered ✓" : "Pending orders"], ["Open orders", c.orders]] })}
               onMouseLeave={() => setTip(null)} style={{ cursor: "pointer", opacity: 1.0 }}>
              <circle r={pr.r + 4} fill={fillColor} opacity={isDone ? ".25" : ".14"}/>
              <circle r={pr.r} fill={fillColor} stroke={strokeColor} strokeWidth="1.5"/>
              {isDone && <text x="0" y="0.35em" textAnchor="middle" fill="#64748b" style={{ fontSize: pr.r * 1.1, fontWeight: 700 }}>✓</text>}
              {!isDone && <text className="node-label" x={pr.r + 6} y="3" fill="#475569" style={{ fontWeight: 500, fontSize: 10.5 }}>{c.id}</text>}
              {isDone && <text className="node-label" x={pr.r + 6} y="3" fill="#94a3b8" style={{ fontWeight: 400, fontSize: 10.5 }}>{c.id}</text>}
            </g>
          );
        })}

        {/* depot */}
        <g transform={`translate(${PNODES.DEPOT.x},${PNODES.DEPOT.y})`}
           onMouseEnter={() => setTip({ id: "DEPOT · " + state.depot.name, color: "#F5C451",
             rows: [["Role", "Central warehouse"], ["Open orders", state.pending_orders]] })}
           onMouseLeave={() => setTip(null)} style={{ cursor: "pointer" }}>
          <circle r="34" fill="url(#depotGlow)"/>
          <rect x="-10" y="-10" width="20" height="20" rx="4" transform="rotate(45)" fill="#F5C451" stroke="#ffffff" strokeWidth="1.6"/>
          <text className="node-label" x="0" y="-18" textAnchor="middle" fill="#d97706" style={{ fontWeight: 600, fontSize: 11 }}>DEPOT</text>
        </g>

        {/* vehicles */}
        {state.vehicles.map((v) => {
          const p = project(v.lat, v.lng);
          const vs = VEHICLE_STATUS[v.status] || VEHICLE_STATUS.at_depot;
          const col = vs.color;
          const broken = v.status === "broken";
          const sel = selectedVeh === v.id;
          return (
            <g key={v.id} style={{ transform: `translate(${p.x}px,${p.y}px)`, transition: `transform ${SPEED_MS[speed] || 1100}ms linear`, cursor: "pointer" }}
               onClick={() => onSelectVeh(sel ? null : v.id)}
               onMouseEnter={() => setTip({ id: v.id, color: col,
                 rows: [["Status", vs.label], ["Heading to", v.leg_to], ["Load", v.load_pct + "%"]] })}
               onMouseLeave={() => setTip(null)}>
              {broken && <circle r="16" fill="#FF4D5E" opacity=".22" className="evt-pulse"/>}
              {sel && <circle r="15" fill="none" stroke={col} strokeWidth="1.6" opacity=".8"/>}
              <rect x="-9" y="-9" width="18" height="18" rx="5" fill={col} stroke="#ffffff" strokeWidth="1.6" style={{ filter: "drop-shadow(0 2px 3px rgba(0,0,0,0.2))" }}/>
              <g transform="translate(-6,-6) scale(.5)" stroke="#ffffff" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round">
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
  width: 28, height: 28, borderRadius: 6, border: "1px solid #e2e8f0",
  background: "#ffffff", color: "#475569", cursor: "pointer",
  fontSize: 16, lineHeight: "24px", fontWeight: 600, boxShadow: "0 2px 6px rgba(0,0,0,0.08)"
};

window.DispatchMap = DispatchMap;
