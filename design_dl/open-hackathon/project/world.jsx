// world.jsx — mock world state + simulation engine. Mirrors the snapshot() shape
// from fleet/ui/controller.py and the HCM sample from fleet/scenarios.py.

const DELAY_THRESHOLD = 15; // min: below this the system auto-approves (spec §3)

// Real HCM coordinates from build_sample_state()
const NODE_COORDS = {
  DEPOT: { lat: 10.8231, lng: 106.6297, name: "Kho Chính HCM" },
  C001:  { lat: 10.8050, lng: 106.6300, name: "BigC Q.1" },
  C002:  { lat: 10.7748, lng: 106.6987, name: "Chợ Bến Thành" },
  C003:  { lat: 10.8150, lng: 106.6150, name: "MiniMart Lê Lợi" },
  C004:  { lat: 10.8300, lng: 106.6400, name: "Nhà hàng Á Châu" },
};

const CUSTOMER_SEED = [
  { id: "C001", priority: 1, type: "Supermarket", orders: 15 },
  { id: "C002", priority: 2, type: "Market",      orders: 20 },
  { id: "C003", priority: 3, type: "Mini-mart",   orders: 23 },
  { id: "C004", priority: 2, type: "Restaurant",  orders: 30 },
];

const VEHICLE_ROUTES = {
  V001: ["DEPOT", "C001", "C003", "DEPOT"],
  V002: ["DEPOT", "C002", "DEPOT"],
  V003: ["DEPOT", "C004", "DEPOT"],
};

let _ids = { e: 100, d: 500 };
const newEventId = () => "EV" + (++_ids.e);
const newDecId   = () => "DC" + (++_ids.d);

const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
const weighted = (pairs) => { // [[val,w],...]
  const total = pairs.reduce((s, [, w]) => s + w, 0);
  let r = Math.random() * total;
  for (const [v, w] of pairs) { if ((r -= w) <= 0) return v; }
  return pairs[0][0];
};
const rint = (a, b) => Math.floor(a + Math.random() * (b - a + 1));

function vehiclePos(v) {
  const route = VEHICLE_ROUTES[v.id];
  const a = NODE_COORDS[route[v.legIndex]];
  const b = NODE_COORDS[route[Math.min(v.legIndex + 1, route.length - 1)]];
  return { lat: a.lat + (b.lat - a.lat) * v.t, lng: a.lng + (b.lng - a.lng) * v.t };
}

function vehicleSnap(v) {
  const route = VEHICLE_ROUTES[v.id];
  const p = vehiclePos(v);
  return {
    id: v.id, status: v.status, lat: p.lat, lng: p.lng,
    stop_index: v.legIndex,
    route_nodes: route,
    leg_to: route[Math.min(v.legIndex + 1, route.length - 1)],
    load_pct: v.load_pct, capacity_kg: 500,
  };
}

// ---------- event / decision generation ----------
const ACTION_FOR = {
  traffic:            ["reroute"],
  flooded_area:       ["reroute"],
  vehicle_breakdown:  ["reallocate"],
  demand_surge:       ["reprioritize", "accelerate"],
  inventory_shortage: ["defer", "reschedule"],
  urgent_order:       ["accelerate", "reprioritize"],
};

function describe(action, evt) {
  const t = evt.target;
  switch (action) {
    case "reroute":      return `Divert affected vehicles around <b>${t}</b> via an alternate road segment.`;
    case "reallocate":   return `Reassign the open stops from <b>${t}</b> to the nearest available vehicle.`;
    case "accelerate":   return `Move <b>${t}</b> ahead in the dispatch sequence to meet its SLA window.`;
    case "reprioritize": return `Raise <b>${t}</b> to priority P1 to absorb the demand surge.`;
    case "defer":        return `Hold low-priority orders affected by <b>${t}</b> to the next dispatch window.`;
    case "reschedule":   return `Shift deliveries impacted by <b>${t}</b> to a later time window.`;
    case "cancel":       return `Cancel the undeliverable order tied to <b>${t}</b>.`;
    default:             return `Resolve event on <b>${t}</b>.`;
  }
}

function targetFor(type, state) {
  const custIds = state.customers.map((c) => c.id);
  const vehIds = state.vehicles.map((v) => v.id);
  const edges = ["DEPOT->C001", "DEPOT->C002", "DEPOT->C003", "DEPOT->C004", "C003->C004"];
  switch (EVENT_TYPES[type].noun) {
    case "customer": return pick(custIds);
    case "vehicle":  return pick(vehIds);
    case "edge":     return pick(edges);
    default:         return "DEPOT";
  }
}

function makeEvent(type, target, severity, clock) {
  return { id: newEventId(), event_type: type, target, severity, started_at: clock };
}

function makeDecision(evt, clock, opts = {}) {
  const action = opts.action || pick(ACTION_FOR[evt.event_type] || ["reroute"]);
  const sevBoost = { low: 0, medium: 6, high: 14, critical: 24 }[evt.severity] || 0;
  const added_delay_min = opts.delay != null ? opts.delay : rint(2, 22) + sevBoost;
  const engine = opts.engine || weighted([["claude", 42], ["local_nim", 26], ["rule_based", 32]]);
  return {
    id: newDecId(), event_id: evt.id, action,
    description: describe(action, evt),
    added_delay_min, engine, status: "pending", timestamp: clock,
  };
}

// ---------- seed ----------
function initialState() {
  _ids = { e: 100, d: 500 };
  const clock = "2026-06-04T06:40:00";
  const customers = CUSTOMER_SEED.map((c) => ({
    ...c, ...NODE_COORDS[c.id], name: NODE_COORDS[c.id].name,
  }));
  const vehicles = [
    { id: "V001", status: "on_route",   legIndex: 0, t: 0.55, load_pct: 72 },
    { id: "V002", status: "in_transit", legIndex: 0, t: 0.28, load_pct: 88 },
    { id: "V003", status: "at_depot",   legIndex: 0, t: 0.0,  load_pct: 0 },
  ];

  const e1 = makeEvent("flooded_area", "DEPOT->C001", "high", clock);
  const e2 = makeEvent("demand_surge", "C002", "medium", clock);
  const events = [e1, e2];

  const decisions = [
    makeDecision(e1, clock, { action: "reroute", delay: 28, engine: "claude" }),
    makeDecision(e2, clock, { action: "reprioritize", delay: 19, engine: "local_nim" }),
  ];
  const autoHandled = [
    { id: newDecId(), action: "reroute", added_delay_min: 7, engine: "rule_based",
      description: "Minor congestion on <b>DEPOT->C003</b> — rerouted automatically.", timestamp: clock },
  ];

  return {
    clock, sim_tick: 12, customers, vehicles,
    depot: { ...NODE_COORDS.DEPOT },
    events, decisions, resolved: [], autoHandled,
  };
}

function pendingOrders(state) {
  return state.customers.reduce((s, c) => s + c.orders, 0);
}

// ---------- tick ----------
function stepWorld(state) {
  const s = structuredClone(state);
  s.sim_tick += 1;
  const d = new Date(s.clock); d.setMinutes(d.getMinutes() + 5);
  s.clock = d.toISOString().slice(0, 19);

  // move vehicles
  s.vehicles = s.vehicles.map((v) => {
    if (v.status === "broken" || v.status === "maintenance") return v;
    const route = VEHICLE_ROUTES[v.id];
    let { legIndex, t } = v;
    if (v.status === "at_depot") { return { ...v, status: "in_transit", t: 0.02 }; }
    t += 0.34;
    if (t >= 1) {
      t = 0; legIndex += 1;
      if (legIndex >= route.length - 1) { // loop the route
        legIndex = 0; t = 0.02;
      }
    }
    let status = legIndex === 0 ? "in_transit" : "on_route";
    const load = Math.max(0, v.load_pct - rint(0, 12));
    return { ...v, legIndex, t, status, load_pct: load };
  });

  // maybe spawn an event (~55% per tick), with a decision
  if (Math.random() < 0.55) {
    const type = weighted([
      ["traffic", 22], ["demand_surge", 18], ["urgent_order", 16],
      ["flooded_area", 14], ["vehicle_breakdown", 12], ["inventory_shortage", 18],
    ]);
    const severity = weighted([["low", 30], ["medium", 34], ["high", 24], ["critical", 12]]);
    const target = targetFor(type, s);
    const evt = makeEvent(type, target, severity, s.clock);

    // breakdown actually breaks a vehicle on the map
    if (type === "vehicle_breakdown") {
      s.vehicles = s.vehicles.map((v) => v.id === target ? { ...v, status: "broken" } : v);
    }

    const dec = makeDecision(evt, s.clock);
    s.events = [evt, ...s.events].slice(0, 14);
    if (dec.added_delay_min < DELAY_THRESHOLD) {
      dec.status = "auto"; dec.engine = "rule_based";
      s.autoHandled = [{ ...dec, _new: true }, ...s.autoHandled].slice(0, 12);
      // resolve the event automatically
      evt._autoResolved = true;
    } else {
      dec._new = true; evt._new = true;
      s.decisions = [dec, ...s.decisions];
    }
  }

  // age out: resolve some active events that have a resolved decision-less life
  if (s.events.length > 8 && Math.random() < 0.4) {
    s.events = s.events.slice(0, s.events.length - 1);
  }
  return s;
}

// ---------- approve / reject ----------
function resolveDecision(state, decId, verb) {
  const s = structuredClone(state);
  const idx = s.decisions.findIndex((d) => d.id === decId);
  if (idx < 0) return s;
  const [dec] = s.decisions.splice(idx, 1);
  dec.status = verb === "approve" ? "approved" : "rejected";
  dec.resolved_at = s.clock;
  s.resolved = [{ ...dec, _new: true }, ...s.resolved].slice(0, 14);
  // approving a resolve-action clears its event from the active board
  if (verb === "approve") {
    s.events = s.events.filter((e) => e.id !== dec.event_id);
    // un-break a vehicle if reallocate approved
    if (dec.action === "reallocate") {
      s.vehicles = s.vehicles.map((v) => v.status === "broken" ? { ...v, status: "maintenance" } : v);
    }
  }
  return s;
}

// ---------- voice / text field-report parser ----------
function parseReport(text, state) {
  const lower = " " + text.toLowerCase() + " ";
  const reports = [];
  const findCust = () => {
    const m = text.match(/c0*([1-4])\b/i) || lower.match(/customer\s*0*([1-4])/);
    return m ? "C00" + m[1] : null;
  };
  const findVeh = () => {
    const m = text.match(/v0*([1-3])\b/i) || lower.match(/(?:vehicle|truck|xe)\s*0*([1-3])/);
    return m ? "V00" + m[1] : null;
  };
  const sevFrom = (def) =>
    /critical|severe|major|nghi[êe]m tr[ọo]ng|n[ặa]ng/.test(lower) ? "critical" :
    /high|bad|heavy|l[ơo]n|l[ớo]n/.test(lower) ? "high" :
    /minor|light|nh[ẹe]/.test(lower) ? "low" : def;
  const cust = findCust(), veh = findVeh();
  const edge = cust ? `DEPOT->${cust}` : "DEPOT->C001";

  if (/flood|ng[ậâ]p|water|n[ưu][ơo]c/.test(lower))
    reports.push({ event_type: "flooded_area", target: edge, severity: sevFrom("high") });
  if (/broke|broken|breakdown|h[ỏo]ng|h[ưu] h[ỏo]ng|stall/.test(lower) && veh)
    reports.push({ event_type: "vehicle_breakdown", target: veh, severity: sevFrom("high") });
  if (/traffic|jam|congest|k[ẹe]t|t[ắa]c/.test(lower))
    reports.push({ event_type: "traffic", target: edge, severity: sevFrom("medium") });
  if (/urgent|asap|g[ấâ]p|kh[ẩâ]n/.test(lower) && cust)
    reports.push({ event_type: "urgent_order", target: cust, severity: sevFrom("high") });
  if (/surge|spike|rush|t[ăa]ng|\bsurge\b/.test(lower) && cust)
    reports.push({ event_type: "demand_surge", target: cust, severity: sevFrom("medium") });
  if (/shortage|out of stock|thi[ếe]u|h[ếe]t h[àa]ng|restock/.test(lower))
    reports.push({ event_type: "inventory_shortage", target: "DEPOT", severity: sevFrom("medium") });

  // fallback: if nothing matched but we have a target, assume urgent order
  if (reports.length === 0 && cust)
    reports.push({ event_type: "urgent_order", target: cust, severity: sevFrom("medium") });

  return reports;
}

function injectReports(state, reports) {
  const s = structuredClone(state);
  const newEvents = [], newDecisions = [];
  for (const r of reports) {
    const evt = makeEvent(r.event_type, r.target, r.severity, s.clock);
    evt._new = true;
    if (r.event_type === "vehicle_breakdown") {
      s.vehicles = s.vehicles.map((v) => v.id === r.target ? { ...v, status: "broken" } : v);
    }
    const dec = makeDecision(evt, s.clock, { engine: "claude", delay: rint(16, 38) });
    dec._new = true;
    newEvents.push(evt); newDecisions.push(dec);
  }
  s.events = [...newEvents, ...s.events].slice(0, 16);
  s.decisions = [...newDecisions, ...s.decisions];
  return { state: s, events: newEvents, decisions: newDecisions };
}

const VOICE_EXAMPLES = [
  "Road into C001 is flooded, vehicle V003 broke down",
  "Heavy traffic jam near C003",
  "Urgent order at C002, needs delivery ASAP",
  "Depot running short on stock",
];

Object.assign(window, {
  DELAY_THRESHOLD, NODE_COORDS, VEHICLE_ROUTES, VOICE_EXAMPLES,
  initialState, pendingOrders, stepWorld, resolveDecision,
  parseReport, injectReports, vehiclePos, vehicleSnap,
});
