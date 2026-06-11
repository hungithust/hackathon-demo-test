# M-F implementation trace

Date: 2026-06-07

## Scope

Implements the consequential-disruptions path from `docs/superpowers/specs/2026-06-07-sbf-consequential-disruptions-design.md` without changing the default runtime path.

## Files changed

- `config/settings.py`
- `fleet/simulator/engine.py`
- `fleet/agent/oracle.py`
- `fleet/agent/dataset.py`
- `scripts/gen_dataset.py`
- `tests/test_config.py`
- `tests/test_simulator.py`
- `tests/test_gen_dataset.py`

## What was added

- `ENABLE_TRAVEL_TIME` / `Settings.enable_travel_time`
- `WorldSimulator.advance_only`
- `roll_forward(..., freeze_world=True, enable_travel_time=True)`
- `make_disrupted_example()`
- `iter_disrupted_examples()`
- `grade_disrupted()`
- `scripts.gen_dataset --consequential`

## Design notes

- Default-off gating is preserved. The old `make_example()` and `grade_full()` remain intact for back-compat and for the existing non-consequential tests.
- The cost function in `fleet/agent/oracle.py` is intentionally unchanged. The bug was in world dynamics and grading semantics, not in the scalarized cost formula.
- `vehicle_breakdown` is implemented as a customer-targeted event plus a broken committed vehicle. This keeps `CANCEL` meaningful while `REALLOCATE` can still find the broken vehicle via dispatcher fallback.

## Validation target

The expected behavioral change is not “all tests still pass” alone. The important validation is:

- travel-time replay changes realized movement under blocked/flooded edges
- freeze mode removes exogenous demand churn during grading
- consequential dataset generation surfaces informative examples across multiple event types

## Validation result in this repo

Probe 1 after the M-F wiring patch (`n_seeds=5`, horizon env still `12`, consequential path internally lifts grading horizon to at least `60`):

- baseline path: `informative_fraction = 0.167`, `event_types = {inventory_shortage: 5}`
- consequential path: `informative_fraction = 0.667`, `event_types = {traffic: 5, flooded_area: 5, inventory_shortage: 5, vehicle_breakdown: 5}`

At that point the runbook gate was already passed, but `demand_surge` and `urgent_order` were still flat.

## Semantics follow-up

`demand_surge` and `urgent_order` initially still graded flat in the current codebase. The reason was downstream action semantics, not the M-F wiring itself:

- `REPRIORITIZE` and `ACCELERATE` both mainly collapse to "make the target more urgent"
- `REALLOCATE` also re-solves, so in these scenarios the three candidates often converge to the same route outcome

The next patch deepened the semantics by:

- choosing a later planned customer as the disrupted target for customer-pressure events
- adding `CustomerProfile.service_time_min`
- making `ACCELERATE` set `service_time_min=0.0` in addition to top priority

This keeps the fix localized to action semantics instead of revisiting the oracle wiring.

## Validation result after the semantics follow-up

Probe 2 after the action-semantics patch:

- baseline path: `informative_fraction = 0.167`, `event_types = {inventory_shortage: 5}`
- consequential path: `informative_fraction = 1.000`, `event_types = {traffic: 5, flooded_area: 5, demand_surge: 5, urgent_order: 5, inventory_shortage: 5, vehicle_breakdown: 5}`

This reaches the full `6/6` informative-event coverage target on the small probe.

## Caveat

Coverage is now full, but action ranking semantics are still not "final business truth" for every class. In the current probe, `demand_surge` and `urgent_order` become informative because `ACCELERATE` is now meaningfully distinct, but it is not necessarily the oracle winner. That is acceptable for the current dataset gate and training-signal objective, but if the team later wants exact policy semantics by disruption type, that should be handled as a separate decision-policy refinement task.

## Expected follow-up

- Run `scripts.gen_dataset --consequential` with small seeds and inspect `event_types` and `informative_fraction`
- If coverage is still weak on `vehicle_breakdown`, tune only the injury/load-pressure logic; do not loosen the pre-train gate
