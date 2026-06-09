// settings.jsx — Settings modal. Edits Settings env-vars and applies them via
// POST /api/settings, which rebuilds the world (reset) on the new settings.

function SettingsField({ f, value, onChange }) {
  const label = (
    <span className="set-label">{f.label}
      {f.help && <i className="set-help" title={f.help}>?</i>}
    </span>
  );
  if (f.type === "bool") {
    return (
      <label className="set-row set-bool">
        {label}
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(f.key, e.target.checked)}/>
      </label>
    );
  }
  let input;
  if (f.type === "select") {
    input = (
      <select value={value} onChange={(e) => onChange(f.key, e.target.value)}>
        {f.choices.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    );
  } else if (f.type === "number") {
    input = <input type="number" step={f.step} value={value}
              onChange={(e) => onChange(f.key, e.target.value === "" ? "" : Number(e.target.value))}/>;
  } else {
    input = <input type="text" value={value} onChange={(e) => onChange(f.key, e.target.value)}/>;
  }
  return <label className="set-row">{label}{input}</label>;
}

function SettingsModal({ open, onClose, onApplied }) {
  const [groups, setGroups] = React.useState(null);
  const [form, setForm] = React.useState({});
  const [base, setBase] = React.useState({});
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);

  React.useEffect(() => {
    if (!open) return;
    setErr(null); setGroups(null);
    Api.getSettings()
      .then((r) => { setGroups(r.groups); setForm(r.values); setBase(r.values); })
      .catch((e) => setErr(String(e.message || e)));
  }, [open]);

  if (!open) return null;
  const onChange = (key, val) => setForm((f) => ({ ...f, [key]: val }));

  const apply = async () => {
    const changed = {};
    Object.keys(form).forEach((k) => { if (form[k] !== base[k]) changed[k] = form[k]; });
    setBusy(true); setErr(null);
    try {
      const snap = await Api.saveSettings(changed);
      onApplied(snap); onClose();
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };

  const core = (groups || []).filter((g) => g.name !== "Advanced");
  const adv = (groups || []).find((g) => g.name === "Advanced");

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-head">
          <Icon name="gear" size={16}/><h2>Settings</h2>
          <button className="btn ghost icon" onClick={onClose}><Icon name="x" size={15}/></button>
        </div>
        <div className="modal-body">
          {err && <div className="set-err">{err}</div>}
          {groups === null ? <div className="set-loading">Loading…</div> : (<>
            {core.map((g) => (
              <div className="set-group" key={g.name}>
                <div className="set-group-title">{g.name}</div>
                {g.fields.map((f) => <SettingsField key={f.key} f={f} value={form[f.key]} onChange={onChange}/>)}
              </div>
            ))}
            {adv && (
              <details className="set-adv">
                <summary>Advanced · {adv.fields.length} settings</summary>
                <div className="set-group">
                  {adv.fields.map((f) => <SettingsField key={f.key} f={f} value={form[f.key]} onChange={onChange}/>)}
                </div>
              </details>
            )}
          </>)}
        </div>
        <div className="modal-foot">
          <span className="muted" style={{ marginRight: "auto", fontSize: "12px" }}>
            Applying rebuilds the world from scratch (resets the simulation).
          </span>
          <button className="btn ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn primary" onClick={apply} disabled={busy || groups === null}>
            {busy ? "Restarting…" : "Apply & restart"}
          </button>
        </div>
      </div>
    </div>
  );
}

window.SettingsModal = SettingsModal;
