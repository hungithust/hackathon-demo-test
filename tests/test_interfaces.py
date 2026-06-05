from fleet.contracts.interfaces import (
    Simulator, Detector, RouteOptimizer, Forecaster, DecisionEngine, Dispatcher,
)


class _OkSim:
    def tick(self, state): ...
    def inject_event(self, state, event_type, target, severity): ...


class _BadSim:
    def tick(self, state): ...
    # missing inject_event


def test_protocols_are_runtime_checkable():
    assert isinstance(_OkSim(), Simulator)
    assert not isinstance(_BadSim(), Simulator)


def test_all_six_interfaces_runtime_checkable():
    class Dummy:  # implements none of the protocol methods
        pass
    for proto in (Simulator, Detector, RouteOptimizer,
                  Forecaster, DecisionEngine, Dispatcher):
        # runtime_checkable protocols allow isinstance() without raising TypeError
        assert isinstance(Dummy(), proto) is False
