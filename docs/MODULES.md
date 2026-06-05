# Tham chiếu từng module

> Đọc [ARCHITECTURE.md](ARCHITECTURE.md) trước để nắm bức tranh tổng. File này đi sâu từng module: **trách nhiệm → API chính → cách cắm vào hệ thống → lưu ý/bẫy**.
> Mỗi module ẩn sau một interface trong [fleet/contracts/interfaces.py](../fleet/contracts/interfaces.py); test nhắm vào interface nên đổi impl không vỡ test.

---

## 0. `fleet/contracts/` — nền tảng (không import gì nội bộ)

Lớp đáy. Mọi module khác import từ đây; bản thân nó **không** import module nội bộ nào → không bao giờ có vòng phụ thuộc.

### `state.py` — mô hình thế giới
- **Trách nhiệm:** định nghĩa mọi entity, enum, và `WorldState` (nguồn sự thật duy nhất) + serialize JSON.
- **Entities:** `Location`, `TimeWindow`, `Order`, `CustomerProfile`, `Stop`, `VehicleRoute`, `Vehicle`, `Depot`, `RoadNode`, `RoadEdge`, `RoadGraph`, `Event`, `Decision`, `WorldState`.
- **Enums:** `VehicleStatus`, `EdgeStatus`(OPEN/CONGESTED/BLOCKED/FLOODED), `EventType`, `EventSeverity`(LOW/MEDIUM/HIGH/CRITICAL), `DecisionEngine`(rule_based/claude/human), `DecisionAction`(reroute/reschedule/reprioritize/reallocate/defer/cancel/accelerate), `ApprovalStatus`(pending/approved/rejected/override), `PriorityLevel`(P1=1…P4=4).
- **API hay dùng:** `WorldState.get_active_events()`, `get_pending_decisions()`, `get_approved_decisions()`, `total_orders_pending()`, `get_vehicle/get_customer/get_route()`, `to_dict()/from_dict()`.
- **Chi tiết quan trọng:**
  - `RoadEdge.id` tự suy ra `"{from}->{to}"` nếu để trống; `RoadGraph.edges` **keyed theo edge_id** ⇒ hỗ trợ **cạnh song song** A→B (spec §6.9). Helper: `get_edge/out_edges/edges_between`.
  - `RoadEdge.effective_time = base_time_minutes * traffic_factor`; `is_passable(wade)` = False nếu BLOCKED, hoặc FLOODED với `flood_level > wade`.
  - `priority`: **1 = gấp nhất … 4 = ít gấp nhất**.
- **Bẫy:** `Location` cần đủ 4 field `(lat, lng, address, name)`. Serialize là self-describing (`__type__/__enum__/__dt__`) — đừng thêm key thủ công.

### `dto.py` — DTO cho routing
- **Trách nhiệm:** tách interface optimizer khỏi `WorldState`. Mọi solver nhận/đưa cùng một hình dạng.
- **Vào:** `RoutingProblem(locations, depot_id, time_matrix: {veh_type: NxN}, fleet: [FleetVehicleSpec], tasks: [TaskSpec])`.
- **Ra:** `RoutingSolution(routes: {vid: [SolvedStop]}, dropped: [customer_id], feasible, metrics)`.
- `FleetVehicleSpec(id, capacity_kg, veh_type, shift_start, shift_end)`; `TaskSpec(customer_id, demand_kg, tw_start, tw_end, service_time_min, priority)`; `SolvedStop(customer_id, arrival, departure, load_after)`.

### `interfaces.py` — 6 Protocol
- 6 `@runtime_checkable Protocol` (xem bảng ở [ARCHITECTURE.md §3](ARCHITECTURE.md#3-sáu-interface-xương-sống)). Đây là "hợp đồng" mọi impl phải thỏa.

---

## 1. `fleet/scenarios.py` — thế giới mẫu
- **Trách nhiệm:** `build_sample_state(base_time)` dựng thế giới xác định cho test/demo: **1 depot, 3 xe tải (V001-3, cap 500, wade 0.3), 4 khách (C001-4)** ở Quận 1 HCM, tồn kho `{SKU001:100, SKU002:50, SKU003:80}`.
- **Chi tiết "đắt giá":** ngoài các cạnh depot↔khách thường, có **cặp cạnh song song ngập** `DEPOT->C001#2` / `C001->DEPOT#2` (`FLOODED`, `flood_level=0.5`). Xe tải (wade 0.3) **không** đi được lối tắt 6 phút khi ngập ⇒ đúng tình huống mà ma trận per-veh_type của M3 khai thác.
- **Lưu ý:** dòng ngập này là **cố định** trong thế giới mẫu — chính nó từng phơi bày lỗi reroute-mỗi-tick (đã fix ở loop + planner).

---

## 2. `fleet/simulator/engine.py` — `WorldSimulator` (Simulator)
- **Trách nhiệm:** làm thế giới "sống" + **di chuyển và giao hàng** xe. Xác định hoàn toàn theo `settings.seed`.
- **`tick(state)` làm tuần tự:** đẩy `clock += tick_minutes`, `sim_tick += 1` → `_generate_demand` → `_maybe_restock` → `_update_shortage_events` → `_advance_vehicles`.
  - `_generate_demand`: nhu cầu theo loại khách (`_BASE_RATE_PER_HOUR`) × mùa trong ngày (`_seasonal_factor`: cao điểm 6-10h & 16-20h) × nhiễu (`demand_noise`), làm tròn ngẫu nhiên giữ kỳ vọng.
  - `_maybe_restock`: cứ `restock_interval_min` thì cộng lại lô tồn ban đầu (snapshot ở tick đầu).
  - `_update_shortage_events`: nếu tổng nhu cầu 1 SKU > tồn → mở `INVENTORY_SHORTAGE` (mức theo độ thiếu); hết thiếu → set `ended_at`. **Đây là mẫu vòng đời sự kiện** mà loop bắt chước cho sự kiện `DET_*`.
  - `_advance_vehicles` (chuyển động **theo lịch**): với mỗi stop có `planned_arrival <= clock` và chưa `actual_arrival` → đánh dấu đã đến, dời `vehicle.pos` tới khách, `status=ON_ROUTE`, rồi `_deliver`. Đi hết stop **và** quá `route.end_time` → về `AT_DEPOT`. Bỏ qua xe `BROKEN/MAINTENANCE`.
  - `_deliver`: trừ tồn depot theo đơn (sàn 0) và **xóa đơn của khách**.
- **API khác:** `inject_event(type, target, severity)` (sinh `EVT_NNN`), `disrupt_edge(edge_id, status, flood_level, traffic_factor)` (đổi cạnh + phát sự kiện).
- **Bẫy:** không nội suy vị trí dọc cạnh; "đến nơi" là sự kiện rời rạc ở mốc tick.

---

## 3. `fleet/detection/` — phát hiện nhiễu (Detector)

### `rules.py` — `RuleDetector` (mặc định)
- **Trách nhiệm:** quét `road_graph.edges` + `vehicles`, sinh `Event` theo ngưỡng, **id tất định** `DET_<KIND>_<target>`. Thuần/đọc-only (không sửa `state.events`).
- **Luật:** BLOCKED → `TRAFFIC`/CRITICAL; FLOODED → `FLOODED_AREA` (HIGH nếu `flood_level≥0.5` else MEDIUM); `traffic_factor ≥ traffic_alert_factor` → `TRAFFIC` (HIGH nếu ≥2× ngưỡng else MEDIUM); xe `BROKEN` → `VEHICLE_BREAKDOWN`/CRITICAL.
- **Cắm vào:** loop gọi mỗi tick; **vòng đời** do `_reconcile_detected` trong loop cấp (id `DET_*` ⇒ thêm 1 lần / đóng khi biến mất).

### `zscore.py` — `ZScoreDetector` (chọn qua `DETECTOR_ENGINE=zscore`)
- **Trách nhiệm:** phát hiện **bất thường nhu cầu** kiểu thống kê, **không cần lịch sử**: tính z-score chéo của tổng đơn mỗi khách so với mean/std toàn bộ khách. `z ≥ zscore_threshold` → `DEMAND_SURGE` (HIGH nếu `z≥3` else MEDIUM), id `DET_SURGE_<cid>`.
- **Điều kiện:** cần ≥2 khách và `std>0`, nếu không trả `[]`.

---

## 4. `fleet/routing/` — lập & giải tuyến (RouteOptimizer)

### `matrix.py` — ma trận & dựng bài toán (thuần, không solver)
- `shortest_times_from(graph, source, wade)`: Dijkstra (heapq) trên đồ thị đa-cạnh, bỏ cạnh `not is_passable`, trọng số `effective_time`.
- `build_time_matrix(graph, locations, wade)`: ma trận N×N (đường chéo 0, INF nếu không tới được).
- `build_routing_problem(state, depot_id="DEPOT")`: locations = depot + khách **còn đơn**; **một ma trận / veh_type** (dùng wade **nhỏ nhất** trong nhóm để an toàn); fleet specs (shift fallback giờ depot); tasks (demand = tổng đơn, service mặc định 10’, priority). **Xe BROKEN/MAINTENANCE bị loại** khỏi solve.

### `cpu_solver.py` — `CpuSolver` (mặc định, Google OR-Tools)
- VRPTW thật: callback transit / veh_type (`AddDimensionWithVehicleTransits` + `SetArcCostEvaluatorOfVehicle`), dimension `"Time"` + cửa sổ thời gian, `AddDimensionWithVehicleCapacity` (cứng), `AddDisjunction` để **bỏ điểm không phục vụ được** (penalty theo priority → `dropped`). Mặc định `PATH_CHEAPEST_ARC` (tất định, tức thì); `solver_time_limit_sec>0` bật `GUIDED_LOCAL_SEARCH`. Quy đổi datetime↔phút-nguyên quanh `base`.

### `cuopt_adapter.py` — `CuOptAdapter` (chọn qua `ROUTING_ENGINE=cuopt` + endpoint)
- Hai hàm **thuần, test được offline**: `to_cuopt_request(problem)` (cost/travel_time_matrix_data theo veh_type, task_data demand/time_windows/service/penalties, fleet_data capacities/time_windows/vehicle_types) và `from_cuopt_response(...)` (→ `RoutingSolution`).
- `solve` bọc quanh **transport tiêm vào** `complete/transport`; transport thật dựng **lười** từ `cuopt_endpoint` qua `cuopt-sh-client` (optional). Test dùng JSON giả ⇒ không cần GPU.

### `planner.py` — ghi tuyến vào state
- `plan_routes(state, optimizer)`: build problem → solve → **đặt lại** `state.plan` từ solution (Stop sequence 1..n). Trả `dropped`.
- `reroute(state, optimizer)`: = giải lại theo đồ thị **hiện tại** (ma trận đã loại cạnh chặn/ngập) **NHƯNG bảo toàn điểm đã giao** — snapshot `(actual_arrival, actual_departure)` của các stop đã đến rồi phục hồi sau khi solve. ⇒ chạy dở **không** bị reset về "chưa giao". *(Đây là 1 trong 2 fix lõi.)*

---

## 5. `fleet/forecast/ewma.py` — `EwmaForecaster` (Forecaster)
- **Trách nhiệm:** dự báo nhu cầu bằng **single exponential smoothing**: `level_0=history[0]`, `level_t=α·obs_t+(1-α)·level_{t-1}`; dự báo `horizon_h` bước **phẳng** ở level cuối. Trả `{level, alpha, forecast:[...]}`.
- **Biên:** history rỗng → level 0, forecast toàn 0; `horizon_h≤0` → forecast `[]`. α từ `ewma_alpha`, kẹp `(0,1]`.
- **Lưu ý:** hiện chưa có caller tiêu thụ forecast trong loop — đây là khối sẵn sàng cho UI/agent dùng. Prophet chưa hiện thực.

---

## 6. `fleet/agent/` — ra quyết định (DecisionEngine)

### `rule_based.py` — `RuleBasedEngine` (mặc định)
- **Trách nhiệm:** mỗi event → 1 `Decision` qua map `_ACTION_BY_EVENT` (TRAFFIC/FLOODED_AREA→REROUTE; DEMAND_SURGE/URGENT_ORDER→REPRIORITIZE; INVENTORY_SHORTAGE→DEFER; VEHICLE_BREAKDOWN→REALLOCATE; mặc định REROUTE). `impact_estimate={"added_delay_min":5.0}`, `engine=RULE_BASED`.

### `claude_agent.py` — `ClaudeAgent` (chọn qua `DECISION_ENGINE=claude` + key)
- **Hàm thuần:** `build_messages(state, event)→(system,user)` và `parse_decision(data, event, seq, clock)→Decision` (`engine=CLAUDE`, lỗi action lạ → `ValueError`). `_DECISION_SCHEMA` là json_schema chặt (enum = 7 action, reasoning, added_delay_min).
- **`decide`:** 1 call/event qua **transport tiêm vào** `complete(system,user)→dict`; transport thật dựng lười qua Anthropic SDK (`claude-opus-4-8`, adaptive thinking, `output_config.format`). **Fallback per-event**: nếu call/parse lỗi → dùng action rule-based (`engine=RULE_BASED`) ⇒ loop luôn có quyết định. Test dùng dict giả ⇒ không cần key.

---

## 7. `fleet/dispatch/` — phê duyệt & thực thi

### `approval.py` — `should_auto_approve(decision, severity, settings)`
- **Chính sách cổng duyệt:** CRITICAL → **không** tự duyệt; DEFER/CANCEL/REALLOCATE → **không**; REROUTE/RESCHEDULE → tự duyệt nếu `added_delay_min ≤ auto_approve_delay_threshold_min`; còn lại (REPRIORITIZE/ACCELERATE) → thủ công.

### `dispatcher.py` — `Dispatcher.apply(state, decision)`
- **Trách nhiệm:** thực thi **thật** từng action (mỗi action đổi thế giới để "duyệt" có hiệu lực thấy được), và ghi `execution_result` để audit:
  - REROUTE/RESCHEDULE → không sửa state ở đây; **caller giải lại** (đồ thị live đã loại cạnh chặn).
  - REPRIORITIZE → đẩy khách mục tiêu lên P1.
  - REALLOCATE → cho xe hỏng nghỉ (`MAINTENANCE`) + bỏ route của nó.
  - DEFER → bỏ các stop của khách bị ảnh hưởng (sự kiện thiếu SKU ⇒ mọi khách đặt SKU đó).
  - CANCEL → xóa đơn + stop của khách.
  - ACCELERATE → khách lên P1 + dời `time_window.start = clock`.
- **`RESOLVE_ACTIONS`** = {REROUTE, RESCHEDULE, REPRIORITIZE, REALLOCATE} → báo caller (loop/UI) cần **giải lại tuyến** sau. DEFER/CANCEL cố tình **không** giải lại để việc bỏ stop có hiệu lực trong chu kỳ này. *(Đây là phần nâng cấp "HIGH" trong rà soát.)*

---

## 8. `fleet/loop.py` — `run_loop` (vòng lặp headless)
- **Trách nhiệm:** điều phối một tick (xem [ARCHITECTURE.md §6](ARCHITECTURE.md#6-vòng-lặp-một-tick-chi-tiết)).
- **Hai cơ chế lõi (vừa fix):**
  - `_reconcile_detected`: cấp vòng đời cho output detector trong `state.events` (thêm 1 lần / đóng `DET_*` khi biến mất) ⇒ điều kiện đứng yên là **một** sự kiện.
  - **Dedup quyết định theo `event_id`**: chỉ quyết cho sự kiện active **chưa có** quyết định ⇒ chặn re-REROUTE mỗi tick (vốn reset plan, làm xe không giao được).
  - Re-solve dùng `RESOLVE_ACTIONS` (không chỉ REROUTE).
- **`python -m fleet.loop`** chạy demo 10 tick (có inject 1 TRAFFIC để thấy đường quyết định).

---

## 9. `fleet/factory.py` — composition root
- `build_components(settings) → Components(simulator, detector, optimizer, forecaster, decision_engine, dispatcher)`. Nơi **duy nhất** biết mọi impl; chọn engine theo Settings với fallback an toàn (xem [ARCHITECTURE.md §4](ARCHITECTURE.md#4-composition-root-lắp-ráp)).

---

## 10. `fleet/ui/` — giao diện vận hành

### `controller.py` — `SimulationController` (lớp logic, test được)
- **Trách nhiệm:** bọc mô phỏng cho front-end mà không lộ engine. `__init__` dựng sample state + components.
- **API:** `step(n)` → gọi `run_loop` (im lặng); `snapshot()` → dict **thuần JSON** (clock, sim_tick, vehicles, active_events, đếm decisions, pending_decisions); `approve(id)` (đặt APPROVED/approved_by="human" → `dispatcher.apply` → **giải lại nếu action ∈ RESOLVE_ACTIONS**); `reject(id)` (REJECTED); id sai → `KeyError`.
- **Lưu ý:** đây là mặt được **unit-test**; `approve` của UI khớp đúng đường auto-approve của loop.

### `app.py` — Streamlit dashboard (chỉ glue)
- Nút Step/Reset, metrics, `st.map` + bảng xe, feed sự kiện, nút Approve/Reject cho từng quyết định chờ. **Chỉ file này import `streamlit`** ⇒ test suite không bao giờ đụng streamlit. Chạy: `streamlit run fleet/ui/app.py`.

---

## 11. `tests/` — kiểm thử
- Nhắm vào **interface**, không phải impl ⇒ đổi engine không vỡ test. Các engine cao cấp (Claude/cuOpt) test bằng **transport giả** ⇒ chạy offline, không key/GPU. Toàn bộ ~141 test xanh.
- File chính: `test_state/dto/interfaces`, `test_config`, `test_simulator`, `test_movement`, `test_detector(s)`, `test_forecaster`, `test_matrix`, `test_cpu_solver`, `test_cuopt_adapter`, `test_planner`, `test_claude_agent`, `test_factory`, `test_loop`, `test_reroute`, `test_ui_controller`.

---

## Sơ đồ phụ thuộc (rút gọn)

```
contracts (state/dto/interfaces)   ← không phụ thuộc nội bộ
        ▲
        ├── scenarios
        ├── simulator, detection, forecast, agent, dispatch, routing  (mỗi cái sau 1 interface)
        ▲
   factory  ── lắp ráp ──▶  Components
        ▲
   loop / ui.controller  ── dùng Components ──▶  ui.app (streamlit)
```
