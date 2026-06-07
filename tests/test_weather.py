from datetime import timedelta

from fleet.contracts.state import EdgeStatus
from fleet.simulator.engine import WorldSimulator, _traffic_factor_for_hour
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def test_traffic_peaks_at_rush_hours_and_stays_below_alert():
    peak = 1.8
    alert = 3.0
    assert _traffic_factor_for_hour(8, peak) == peak        # morning rush
    assert _traffic_factor_for_hour(18, peak) == peak       # evening rush
    assert _traffic_factor_for_hour(13, peak) < peak        # midday lighter
    assert _traffic_factor_for_hour(3, peak) == 1.0         # night = free flow
    assert _traffic_factor_for_hour(8, peak) < alert        # never a false TRAFFIC alert


def test_rain_is_bounded_autocorrelated_and_deterministic():
    s1 = WorldSimulator(load_settings(env={"SEED": "5", "WEATHER_RHO": "0.9"}))
    s2 = WorldSimulator(load_settings(env={"SEED": "5", "WEATHER_RHO": "0.9"}))
    xs = [s1._step_rain() for _ in range(300)]
    ys = [s2._step_rain() for _ in range(300)]
    assert xs == ys                              # same seed => identical
    assert all(0.0 <= r <= 1.0 for r in xs)      # rain level normalized to [0,1]
    a, b = xs[:-1], xs[1:]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    assert cov / (va * vb) > 0.4                  # rho=0.9 => persistent rain spells


def test_weather_rng_is_independent_of_demand_rng():
    # Stepping rain must not consume the demand rng (so M-A determinism is unaffected).
    sim = WorldSimulator(load_settings(env={"SEED": "42"}))
    before = sim.rng.random()
    sim2 = WorldSimulator(load_settings(env={"SEED": "42"}))
    sim2._step_rain(); sim2._step_rain(); sim2._step_rain()
    after = sim2.rng.random()
    assert before == after        # demand rng stream unchanged by rain steps


def test_update_traffic_only_touches_open_edges():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"TRAFFIC_PEAK_FACTOR": "1.8"}))
    # disrupt one edge (presenter injection): congested with a big factor
    s.road_graph.get_edge("DEPOT->C001").status = EdgeStatus.CONGESTED
    s.road_graph.get_edge("DEPOT->C001").traffic_factor = 4.0
    s.clock = s.clock.replace(hour=8)            # morning rush
    sim._update_traffic(s)
    # an OPEN edge gets the rush-hour factor
    assert s.road_graph.get_edge("DEPOT->C002").traffic_factor == 1.8
    # the injected CONGESTED edge is left alone (override respected)
    assert s.road_graph.get_edge("DEPOT->C001").traffic_factor == 4.0


def test_weather_floods_and_recovers_flood_prone_edges():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"WEATHER_FLOOD_THRESHOLD": "0.7"}))
    fp = "DEPOT->C001#2"                          # flood-prone parallel edge from the sample world
    # force heavy rain -> flood
    sim._rain = 0.9
    sim._update_weather(s)
    assert s.road_graph.get_edge(fp).status == EdgeStatus.FLOODED
    assert s.road_graph.get_edge(fp).flood_level == 0.5
    # force dry -> the weather-owned edge recovers to OPEN
    sim._rain = 0.1
    sim._update_weather(s)
    assert s.road_graph.get_edge(fp).status == EdgeStatus.OPEN
    assert s.road_graph.get_edge(fp).flood_level == 0.0


def test_weather_does_not_touch_injected_flood_on_other_edges():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    # presenter injects a flood on a NON-flood-prone edge
    inj = s.road_graph.get_edge("DEPOT->C002")
    inj.status = EdgeStatus.FLOODED
    inj.flood_level = 0.8
    sim._rain = 0.1                               # dry: weather would un-flood its own edges
    sim._update_weather(s)
    assert inj.status == EdgeStatus.FLOODED       # injected edge untouched
    assert inj.flood_level == 0.8
