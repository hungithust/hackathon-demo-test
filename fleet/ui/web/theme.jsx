// theme.jsx — enum metadata, color maps, formatters. Mirrors fleet/contracts/state.py.

const SEVERITY = {
  low:      { label: "Low",      cls: "sev-low",      color: "#6E89BE", rank: 0 },
  medium:   { label: "Medium",   cls: "sev-medium",   color: "#F2C94C", rank: 1 },
  high:     { label: "High",     cls: "sev-high",     color: "#F2994A", rank: 2 },
  critical: { label: "Critical", cls: "sev-critical", color: "#FF4D5E", rank: 3 },
};

const EVENT_TYPES = {
  traffic:            { label: "Traffic Jam",        icon: "traffic",   noun: "edge",     blurb: "Congestion on a road segment" },
  demand_surge:       { label: "Demand Surge",       icon: "surge",     noun: "customer", blurb: "Spike in orders at a customer" },
  inventory_shortage: { label: "Inventory Shortage", icon: "inventory", noun: "depot",    blurb: "Stock running low at the depot" },
  vehicle_breakdown:  { label: "Vehicle Breakdown",  icon: "breakdown", noun: "vehicle",  blurb: "Vehicle out of service" },
  urgent_order:       { label: "Urgent Order",       icon: "urgent",    noun: "customer", blurb: "High-priority order injected" },
  flooded_area:       { label: "Flooded Area",       icon: "flood",     noun: "edge",     blurb: "Road flooded — wade limit applies" },
};

const ACTIONS = {
  reroute:      { label: "Reroute",      icon: "reroute",      color: "#4DA6FF", bg: "rgba(77,166,255,.14)" },
  reschedule:   { label: "Reschedule",   icon: "reschedule",   color: "#7FB4E8", bg: "rgba(127,180,232,.14)" },
  reprioritize: { label: "Reprioritize", icon: "reprioritize", color: "#C792EA", bg: "rgba(199,146,234,.14)" },
  reallocate:   { label: "Reallocate",   icon: "reallocate",   color: "#5BD0C0", bg: "rgba(91,208,192,.14)" },
  defer:        { label: "Defer",        icon: "defer",        color: "#F2C94C", bg: "rgba(242,201,76,.14)" },
  cancel:       { label: "Cancel",       icon: "cancel",       color: "#FF7079", bg: "rgba(255,77,94,.14)" },
  accelerate:   { label: "Accelerate",   icon: "accelerate",   color: "#5BE3AE", bg: "rgba(52,211,153,.14)" },
};

const ENGINES = {
  rule_based: { label: "Rule",   full: "Rule-based engine" },
  claude:     { label: "Claude", full: "Claude (LLM)" },
  local_nim:  { label: "NIM",    full: "Local NIM model" },
  human:      { label: "Human",  full: "Human operator" },
};

const VEHICLE_STATUS = {
  at_depot:    { label: "At Depot",    color: "#8A93A6", short: "Depot" },
  in_transit:  { label: "In Transit",  color: "#4DA6FF", short: "Transit" },
  on_route:    { label: "On Route",    color: "#34D399", short: "On route" },
  broken:      { label: "Broken Down", color: "#FF4D5E", short: "Broken" },
  maintenance: { label: "Maintenance", color: "#C792EA", short: "Maint." },
};

const PRIORITY = {
  1: { color: "#5FC9FF", r: 9.5, label: "P1 · Critical" },
  2: { color: "#4DA6FF", r: 7.5, label: "P2 · High" },
  3: { color: "#5E8BD0", r: 6.0, label: "P3 · Normal" },
  4: { color: "#4C6493", r: 5.0, label: "P4 · Low" },
};

// ---- formatters ----
function fmtClock(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
function fmtDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}
function fmtAge(fromIso, nowIso) {
  const mins = Math.max(0, Math.round((new Date(nowIso) - new Date(fromIso)) / 60000));
  if (mins < 1) return "now";
  if (mins < 60) return mins + "m";
  return Math.floor(mins / 60) + "h" + (mins % 60 ? (mins % 60) + "m" : "");
}

Object.assign(window, {
  SEVERITY, EVENT_TYPES, ACTIONS, ENGINES, VEHICLE_STATUS, PRIORITY,
  fmtClock, fmtDate, fmtAge,
});
