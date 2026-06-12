"""Multi-session registry: isolation, capacity/LRU, idle reaping."""
import time

from fleet.ui.session_manager import SessionManager
from fleet.scenarios import ScenarioSpec


def test_sessions_are_isolated():
    mgr = SessionManager()
    a = mgr.create(ScenarioSpec(seed=1, n_customers=6, n_vehicles=3))
    b = mgr.create(ScenarioSpec(seed=2, n_customers=9, n_vehicles=5))
    assert a.id != b.id
    # stepping one world must not touch the other
    a.controller.step(4)
    assert a.controller.state.sim_tick == 4
    assert b.controller.state.sim_tick == 0
    assert a.controller.state is not b.controller.state


def test_create_default_is_random_and_drawable():
    mgr = SessionManager()
    s = mgr.create()                       # no spec -> random problem
    assert s.spec is not None
    assert s.controller.geometry          # synthetic geometry for the map
    assert len(mgr) == 1


def test_get_and_delete():
    mgr = SessionManager()
    s = mgr.create(ScenarioSpec(seed=5))
    assert mgr.get(s.id).id == s.id
    assert mgr.delete(s.id) is True
    assert mgr.delete(s.id) is False
    try:
        mgr.get(s.id)
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_capacity_evicts_lru():
    mgr = SessionManager(capacity=3)
    ids = [mgr.create(ScenarioSpec(seed=i)).id for i in range(3)]
    mgr.get(ids[0])                        # touch 0 so 1 becomes least-recent
    mgr.create(ScenarioSpec(seed=99))      # over capacity -> evict LRU (id 1)
    assert len(mgr) == 3
    assert mgr.delete(ids[1]) is False     # ids[1] was evicted
    assert mgr.get(ids[0])                 # ids[0] survived (was touched)


def test_reap_idle():
    mgr = SessionManager()
    mgr.create(ScenarioSpec(seed=1))
    time.sleep(0.05)
    assert mgr.reap_idle(0.01) == 1        # older than 10ms -> reaped
    assert len(mgr) == 0


def test_list_reports_problem_shape():
    mgr = SessionManager()
    mgr.create(ScenarioSpec(seed=1, n_customers=7, n_vehicles=4, label="x"))
    rows = mgr.list()
    assert rows[0]["n_customers"] == 7
    assert rows[0]["n_vehicles"] == 4