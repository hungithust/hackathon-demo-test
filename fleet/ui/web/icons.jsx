// icons.jsx — inline SVG glyphs. <Icon name="..." size={18} />
// All stroke-based, inherit currentColor. Named to match event types & actions.

function Icon({ name, size = 18, sw = 1.7 }) {
  const p = {
    width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", strokeWidth: sw, strokeLinecap: "round", strokeLinejoin: "round",
  };
  const paths = {
    // ---- event types ----
    traffic: <><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M5 8h14M5 13h14"/><circle cx="9" cy="17.5" r=".6" fill="currentColor"/><circle cx="15" cy="17.5" r=".6" fill="currentColor"/></>,
    surge: <><path d="M3 17l6-6 4 4 7-8"/><path d="M21 11V7h-4"/></>,
    inventory: <><path d="M3 8l9-5 9 5v9l-9 5-9-5V8z"/><path d="M3 8l9 5 9-5M12 13v9"/><path d="M8 5.5v4"/></>,
    breakdown: <><path d="M3 7h11v8H3zM14 10h4l3 3v2h-7"/><circle cx="6.5" cy="17" r="1.6"/><circle cx="17.5" cy="17" r="1.6"/><path d="M19 4l-2 3h3l-2 3"/></>,
    urgent: <><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/></>,
    flood: <><path d="M3 14c1.5 0 1.5 1.5 3 1.5s1.5-1.5 3-1.5 1.5 1.5 3 1.5 1.5-1.5 3-1.5 1.5 1.5 3 1.5"/><path d="M3 18c1.5 0 1.5 1.5 3 1.5S7.5 18 9 18s1.5 1.5 3 1.5 1.5-1.5 3-1.5 1.5 1.5 3 1.5"/><path d="M7 10.5V6a2 2 0 012-2h6a2 2 0 012 2v4.5"/></>,

    // ---- actions ----
    reroute: <><path d="M4 17h6a4 4 0 004-4V9"/><path d="M11 6l3 3-3 3"/><circle cx="4" cy="17" r="1.6"/><path d="M17 14l3 3-3 3"/></>,
    reschedule: <><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M9 2h6"/></>,
    reprioritize: <><path d="M7 21V7M7 7L4 10M7 7l3 3"/><path d="M17 3v14M17 17l3-3M17 17l-3-3"/></>,
    reallocate: <><path d="M3 8h12l-3-3M3 8l3 3"/><path d="M21 16H9l3 3M21 16l-3-3"/></>,
    defer: <><circle cx="12" cy="12" r="9"/><path d="M10 9v6M14 9v6"/></>,
    cancel: <><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></>,
    accelerate: <><path d="M3 6l8 6-8 6V6zM12 6l8 6-8 6V6z"/></>,

    // ---- ui ----
    play: <><path d="M6 4l14 8-14 8V4z" fill="currentColor" stroke="none"/></>,
    pause: <><rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor" stroke="none"/></>,
    step: <><path d="M5 5v14l9-7-9-7z"/><path d="M18 5v14"/></>,
    step5: <><path d="M3 5v14l8-7-8-7zM12 5v14l8-7-8-7z"/></>,
    reset: <><path d="M3 12a9 9 0 109-9 9 9 0 00-7 3.5"/><path d="M3 3v4h4"/></>,
    mic: <><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0014 0M12 18v3M8 21h8"/></>,
    depot: <><path d="M3 21V9l9-6 9 6v12"/><path d="M3 21h18M9 21v-6h6v6"/></>,
    truck: <><path d="M3 7h11v8H3zM14 10h4l3 3v2h-7"/><circle cx="6.5" cy="17" r="1.6"/><circle cx="17.5" cy="17" r="1.6"/></>,
    pin: <><path d="M12 21s7-5.5 7-11a7 7 0 10-14 0c0 5.5 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/></>,
    check: <><path d="M4 12l5 5L20 6"/></>,
    x: <><path d="M6 6l12 12M18 6L6 18"/></>,
    bolt: <><path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" fill="currentColor" stroke="none"/></>,
    inbox: <><path d="M3 13l3-8h12l3 8v6H3v-6z"/><path d="M3 13h5l1 3h6l1-3h5"/></>,
    spark: <><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M18 6l-2.5 2.5M8.5 15.5L6 18"/></>,
    chevron: <><path d="M9 6l6 6-6 6"/></>,
    waves: <><path d="M3 12c2 0 2 2 4 2s2-2 4-2 2 2 4 2 2-2 4-2"/><path d="M3 16c2 0 2 2 4 2s2-2 4-2 2 2 4 2 2-2 4-2"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  };
  return <svg {...p}>{paths[name] || paths.pin}</svg>;
}

window.Icon = Icon;
