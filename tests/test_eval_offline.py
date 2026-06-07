from fleet.eval.offline import predict_records, summarize_offline


def test_predict_records_flags_validity_and_event_type():
    records = [
        {"system": "S", "user": "Event type: traffic\nmore", "assistant": {"action": "reroute"}},
        {"system": "S", "user": "Event type: demand_surge\nx", "assistant": {"action": "reprioritize"}},
    ]

    def complete(system, user):
        if "traffic" in user:
            return {"action": "reroute"}            # matches gold
        return {"action": "not_an_action"}          # invalid

    rows = predict_records(records, complete)
    assert rows[0] == {"pred": "reroute", "gold": "reroute",
                       "event_type": "traffic", "valid": True}
    assert rows[1]["valid"] is False                 # unknown action
    assert rows[1]["event_type"] == "demand_surge"


def test_predict_records_marks_transport_error_invalid():
    records = [{"system": "S", "user": "Event type: traffic\n", "assistant": {"action": "reroute"}}]

    def boom(system, user):
        raise RuntimeError("down")

    rows = predict_records(records, boom)
    assert rows[0]["valid"] is False and rows[0]["pred"] is None


def test_summarize_offline_computes_agreement_validity_confusion():
    rows = [
        {"pred": "reroute", "gold": "reroute", "event_type": "traffic", "valid": True},
        {"pred": "defer", "gold": "reprioritize", "event_type": "demand_surge", "valid": True},
        {"pred": None, "gold": "reroute", "event_type": "traffic", "valid": False},
    ]
    s = summarize_offline(rows)
    assert s["n"] == 3
    assert s["validity_pct"] == 2 / 3
    assert s["agreement_pct"] == 1 / 3            # only the first row agrees
    assert s["confusion"]["traffic"] == {"n": 2, "agree": 1}
    assert s["confusion"]["demand_surge"] == {"n": 1, "agree": 0}
