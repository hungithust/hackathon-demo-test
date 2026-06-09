# Optimization notes — what the solver optimizes, and why few vehicles get used

## Objective

The CPU VRPTW solver ([fleet/routing/cpu_solver.py](../fleet/routing/cpu_solver.py))
minimizes **total fleet travel time**. Concretely:

- `SetArcCostEvaluatorOfVehicle(cb, vehicle_id)` makes each arc cost the travel
  time (plus service time at the origin), using the time matrix for that
  vehicle's `veh_type`.
- `AddVariableMinimizedByFinalizer` is applied to each vehicle's start and end
  CumulVar on the "Time" dimension, so the finalizer pushes routes to start as
  late and end as early as possible — i.e. shorter time spans.
- Customer time windows are enforced as hard ranges on the Time dimension;
  capacity is a hard `AddDimensionWithVehicleCapacity` constraint.
- Skippable visits use priority-scaled drop penalties (`AddDisjunction`), so an
  urgent customer is the last thing dropped.

## Why only 1–4 of 20 vehicles get used (this is correct, not a bug)

There is **no fixed cost per vehicle** and the sample/real time windows are wide.
With nothing charging for "using another truck," OR-Tools always prefers to
**consolidate orders onto as few vehicles as possible**, because every extra
vehicle that leaves the depot only adds depot↔customer travel time without
reducing any other cost. Using 1–4 of 20 trucks to serve the current demand is
therefore the *optimal* answer to "minimize total travel time," not a failure to
dispatch the fleet.

## Levers to spread load across more vehicles (if that is the goal)

These trade total-travel-time against utilization/balance — tune them, do not
apply all at once:

1. **Lower `capacity_kg`** per vehicle — forces orders to split across trucks.
2. **Tighten customer time windows** — overlapping tight windows cannot be served
   by one vehicle in sequence, forcing parallelism.
3. **Add a max-stops-per-vehicle constraint** — a count dimension with an upper
   bound per vehicle caps how much any one truck can absorb.
4. **Add a small fixed cost per used vehicle** via
   `routing.SetFixedCostOfAllVehicles(c)` — this is the direct dial trading
   "fewer vehicles" against "shorter total routes": raise `c` to consolidate,
   lower it to spread.

## Metric trade-off

Three goals pull in different directions:

- **minimize total travel time** (current objective) → fewest vehicles,
- **minimize per-customer ETA** → more vehicles, shorter individual routes,
- **balance utilization** → even spread regardless of total cost.

They cannot all be maximized simultaneously; pick the dominant one and tune the
levers above. The shipped configuration optimizes total travel time on purpose.
