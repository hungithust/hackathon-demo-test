"""Offline evaluation (Sovereign Brain v2, M-D): compare a model's predictions to
the oracle-verified gold labels in a held-out JSONL. Pure; the model transport is
injected so this is testable without a GPU or network."""

from fleet.contracts.state import DecisionAction

_VALID_ACTIONS = {a.value for a in DecisionAction}


def _event_type_from_user(user: str) -> str:
    """The user prompt (from build_messages) starts 'Event type: <value>'."""
    first = user.split("\n", 1)[0]
    return first.split("Event type:", 1)[1].strip() if "Event type:" in first else ""


def predict_records(records, complete):
    """Run `complete(system, user) -> dict` over each record and compare its
    action to the record's oracle-verified gold action. Returns rows of
    {pred, gold, event_type, valid}."""
    rows = []
    for rec in records:
        gold = rec["assistant"]["action"]
        event_type = _event_type_from_user(rec["user"])
        try:
            data = complete(rec["system"], rec["user"])
            pred = str(data["action"])
            valid = pred in _VALID_ACTIONS
        except Exception:
            pred, valid = None, False
        rows.append({"pred": pred, "gold": gold,
                     "event_type": event_type, "valid": valid})
    return rows


def summarize_offline(rows) -> dict:
    """Agreement % (valid AND pred==gold), JSON-validity %, per-event confusion."""
    n = len(rows)
    valid = sum(1 for r in rows if r["valid"])
    agree = sum(1 for r in rows if r["valid"] and r["pred"] == r["gold"])
    confusion = {}
    for r in rows:
        d = confusion.setdefault(r["event_type"], {"n": 0, "agree": 0})
        d["n"] += 1
        if r["valid"] and r["pred"] == r["gold"]:
            d["agree"] += 1
    return {
        "n": n,
        "validity_pct": (valid / n) if n else 0.0,
        "agreement_pct": (agree / n) if n else 0.0,
        "confusion": confusion,
    }
