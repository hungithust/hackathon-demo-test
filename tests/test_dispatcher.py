from datetime import datetime

from fleet.contracts.interfaces import Dispatcher as DispatcherProto
from fleet.contracts.state import Decision, DecisionAction, DecisionEngine
from fleet.dispatch.dispatcher import Dispatcher
from fleet.scenarios import build_sample_state


def test_conforms_to_protocol():
    assert isinstance(Dispatcher(), DispatcherProto)


def test_apply_marks_executed():
    s = build_sample_state()
    d = Decision(id="D1", timestamp=s.clock, event_id="E1",
                 action=DecisionAction.REROUTE, engine=DecisionEngine.RULE_BASED,
                 description="x")
    Dispatcher().apply(s, d)
    assert d.executed_at == s.clock
    assert d.execution_result == {"status": "applied"}
