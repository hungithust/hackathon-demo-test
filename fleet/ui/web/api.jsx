// api.jsx — backend client. Replaces the mock world engine (world.jsx): every
// world mutation goes to fleet/ui/server.py, which drives the real
// SimulationController / IntakeController and returns the snapshot() shape.

const DELAY_THRESHOLD = 15; // min: below this the gate auto-approves (spec §6.6)

const VOICE_EXAMPLES = [
  "Road into C001 is flooded, vehicle V003 broke down",
  "Heavy traffic jam near C003",
  "Urgent order at C002, needs delivery ASAP",
  "Depot running short on stock",
];

// Map the server snapshot onto the field names the view layer expects.
// (active_events -> events, pending_decisions -> decisions, etc.)
function normalize(snap) {
  return {
    clock: snap.clock,
    sim_tick: snap.sim_tick,
    pending_orders: snap.pending_orders,
    depot: snap.depot,
    customers: snap.customers || [],
    vehicles: snap.vehicles || [],
    events: snap.active_events || [],
    decisions: snap.pending_decisions || [],
    resolved: snap.resolved || [],
    autoHandled: snap.auto_handled || [],
    routes: snap.routes || [],
  };
}

function emptyState() {
  return {
    clock: new Date().toISOString().slice(0, 19), sim_tick: 0, pending_orders: 0,
    depot: { lat: 10.8231, lng: 106.6297, name: "Depot" },
    customers: [], vehicles: [], events: [], decisions: [], resolved: [], autoHandled: [], routes: [],
  };
}

async function jget(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}
async function jpost(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let detail = "HTTP " + r.status;
    try { const j = await r.json(); if (j && j.detail) detail = j.detail; } catch (e) {}
    throw new Error(detail);
  }
  return r.json();
}

const Api = {
  snapshot: async () => normalize(await jget("/api/snapshot")),
  step:     async (n = 1) => normalize(await jpost("/api/step", { n })),
  approve:  async (id) => normalize(await jpost("/api/approve/" + encodeURIComponent(id))),
  reject:   async (id) => normalize(await jpost("/api/reject/" + encodeURIComponent(id))),
  reset:    async () => normalize(await jpost("/api/reset")),
  report:   async (text) => {
    const res = await jpost("/api/report", { text });
    return { raw: res.raw, reports: res.reports, decisions: res.decisions,
             state: normalize(res.snapshot) };
  },
  reportAudio: async (blob) => {
    const fd = new FormData();
    fd.append("audio", blob, "report.webm");
    const r = await fetch("/api/report_audio", { method: "POST", body: fd });
    if (!r.ok) {
      let detail = "HTTP " + r.status;
      try { const j = await r.json(); if (j && j.detail) detail = j.detail; } catch (e) {}
      throw new Error(detail);
    }
    const res = await r.json();
    return { raw: res.raw, reports: res.reports, decisions: res.decisions,
             state: normalize(res.snapshot) };
  },
  getSettings:  async () => jget("/api/settings"),
  saveSettings: async (values) => normalize(await jpost("/api/settings", { values })),
};

function pendingOrders(state) { return state.pending_orders; }

// Flag ids absent from the previous snapshot so they flash once (the design used
// a server-side `_new`; with a real backend we diff client-side instead).
function markNew(prev, next) {
  const idset = (arr) => new Set((arr || []).map((x) => x.id));
  const pe = idset(prev && prev.events), pd = idset(prev && prev.decisions);
  const pr = idset(prev && prev.resolved), pa = idset(prev && prev.autoHandled);
  const flag = (arr, seen) => arr.map((x) => (seen.has(x.id) ? x : { ...x, _new: true }));
  return {
    ...next,
    events: flag(next.events, pe),
    decisions: flag(next.decisions, pd),
    resolved: flag(next.resolved, pr),
    autoHandled: flag(next.autoHandled, pa),
  };
}

Object.assign(window, {
  DELAY_THRESHOLD, VOICE_EXAMPLES, Api, pendingOrders, markNew, emptyState,
});
