// map.jsx — schematic dark dispatch map. Projects real HCM lat/lng into a
// stylized district view with routes, pulsing event markers, and live vehicles.

const VB_W = 1000, VB_H = 680;

// projection bounds from NODE_COORDS
const _lats = Object.values(NODE_COORDS).map((n) => n.lat);
const _lngs = Object.values(NODE_COORDS).map((n) => n.lng);
const LAT_MIN = Math.min(..._lats), LAT_MAX = Math.max(..._lats);
const LNG_MIN = Math.min(..._lngs), LNG_MAX = Math.max(..._lngs);
const mapRange = (v, a, b, c, d) => c + ((v - a) / (b - a || 1)) * (d - c);
function project(lat, lng) {
  return {
    x: mapRange(lng, LNG_MIN, LNG_MAX, 210, 800),
    y: mapRange(lat, LAT_MAX, LAT_MIN, 150, 540),
  };
}
const PNODES = Object.fromEntries(
  Object.entries(NODE_COORDS).map(([k, n]) => [k, project(n.lat, n.lng)])
);

// stylized district streets (deterministic, viewBox coords)
const STREETS = [
  "M40,120 C260,90 520,170 980,110",
  "M20,250 C300,230 600,300 990,250",
  "M60,400 C320,380 640,430 980,400",
  "M80,560 C360,540 660,590 980,560",
  "M180,40 C150,240 230,440 180,660",
  "M420,30 C400,260 460,470 430,660",
  "M650,40 C620,250 700,460 660,660",
  "M860,40 C840,250 900,470 870,660",
  "M120,300 C300,360 380,500 520,640",
];
// Saigon river — soft band on the lower-right
const RIVER = "M1020,300 C820,360 760,470 700,560 C660,620 720,700 560,720 L1080,720 Z";

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

function DispatchMap({ state, selectedVeh, onSelectVeh, selectedEvent }) {
  const [tip, setTip] = React.useState(null);
  const [mouse, setMouse] = React.useState({ x: 0, y: 0 });
  const wrapRef = React.useRef(null);

  const onMove = (e) => {
    const r = wrapRef.current.getBoundingClientRect();
    setMouse({ x: e.clientX - r.left, y: e.clientY - r.top });
  };

  const vehSnaps = state.vehicles.map(vehicleSnap);
  const custById = Object.fromEntries(state.customers.map((c) => [c.id, c]));

  // event marker positions
  const eventMarks = state.events.map((e) => {
    let pt = null;
    if (e.target.includes("->")) {
      const [a, b] = e.target.split("->");
      if (PNODES[a] && PNODES[b]) pt = { x: (PNODES[a].x + PNODES[b].x) / 2, y: (PNODES[a].y + PNODES[b].y) / 2 };
    } else if (PNODES[e.target]) pt = PNODES[e.target];
    else if (e.target.startsWith("V")) {
      const v = vehSnaps.find((vv) => vv.id === e.target);
      if (v) pt = project(v.lat, v.lng);
    }
    return pt ? { ...e, ...pt } : null;
  }).filter(Boolean);

  return (
    <div className="map-wrap" ref={wrapRef} onMouseMove={onMove} onMouseLeave={() => setTip(null)}>
      <svg className="map-svg" viewBox={`0 0 ${VB_W} ${VB_H}`} preserveAspectRatio="xMidYMid slice">
        <defs>
          <radialGradient id="depotGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#F5C451" stopOpacity=".5"/>
            <stop offset="100%" stopColor="#F5C451" stopOpacity="0"/>
          </radialGradient>
          <filter id="soft"><feGaussianBlur stdDeviation="2.2"/></filter>
        </defs>

        {/* river */}
        <path d={RIVER} fill="rgba(38,86,127,.16)" stroke="rgba(77,166,255,.12)" strokeWidth="1.5"/>

        {/* district streets */}
        <g stroke="#15203a" strokeWidth="2" fill="none" strokeLinecap="round">
          {STREETS.map((d, i) => <path key={i} d={d}/>)}
        </g>
        <g stroke="#101a30" strokeWidth="1" fill="none" opacity=".7">
          {STREETS.map((d, i) => <path key={i} d={d} transform="translate(18,14)"/>)}
        </g>

        {/* base road links depot<->customers */}
        <g stroke="#26344f" strokeWidth="2.4" fill="none" strokeLinecap="round">
          {state.customers.map((c) => (
            <line key={c.id} x1={PNODES.DEPOT.x} y1={PNODES.DEPOT.y} x2={PNODES[c.id].x} y2={PNODES[c.id].y}/>
          ))}
        </g>

        {/* active vehicle routes */}
        {vehSnaps.map((v) => {
          const route = v.route_nodes;
          const d = route.map((n, i) => (i === 0 ? "M" : "L") + PNODES[n].x + "," + PNODES[n].y).join(" ");
          const on = selectedVeh === v.id;
          const broken = v.status === "broken";
          return (
            <path key={"r" + v.id} d={d} fill="none"
              stroke={broken ? "rgba(255,77,94,.5)" : (on ? "#7ec0ff" : "rgba(77,166,255,.45)")}
              strokeWidth={on ? 3.4 : 2.2}
              strokeDasharray="2 9" strokeLinecap="round"
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
          const pr = PRIORITY[c.priority];
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
           onMouseEnter={() => setTip({ id: "DEPOT · " + NODE_COORDS.DEPOT.name, color: "#F5C451",
             rows: [["Role", "Central warehouse"], ["SKUs", "3 lines in stock"]] })}
           onMouseLeave={() => setTip(null)} style={{ cursor: "pointer" }}>
          <circle r="34" fill="url(#depotGlow)"/>
          <rect x="-10" y="-10" width="20" height="20" rx="4" transform="rotate(45)" fill="#F5C451" stroke="#0a0f1a" strokeWidth="1.6"/>
          <text className="node-label" x="0" y="-18" textAnchor="middle" fill="#F5C451" style={{ fontWeight: 600 }}>DEPOT</text>
        </g>

        {/* vehicles */}
        {vehSnaps.map((v) => {
          const p = project(v.lat, v.lng);
          const col = VEHICLE_STATUS[v.status].color;
          const broken = v.status === "broken";
          const sel = selectedVeh === v.id;
          return (
            <g key={v.id} style={{ transform: `translate(${p.x}px,${p.y}px)`, transition: "transform .85s linear", cursor: "pointer" }}
               onClick={() => onSelectVeh(sel ? null : v.id)}
               onMouseEnter={() => setTip({ id: v.id, color: col,
                 rows: [["Status", VEHICLE_STATUS[v.status].label], ["Heading to", v.leg_to], ["Load", v.load_pct + "%"]] })}
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
      </svg>

      {/* overlays */}
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

      <MapTip tip={tip} mouse={mouse}/>
    </div>
  );
}

window.DispatchMap = DispatchMap;
