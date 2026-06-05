# Kiến trúc hệ thống — AI Realtime Delivery-Fleet Optimizer

> Tài liệu tổng quan cho người mới. Đọc file này trước, rồi sang [MODULES.md](MODULES.md) để hiểu chi tiết từng module.
> Spec nguồn (source of truth): [specs/2026-06-04-fleet-optimizer-base-project-spec.md](superpowers/specs/2026-06-04-fleet-optimizer-base-project-spec.md). Bài toán: [PROBLEM_STATEMENT.md](PROBLEM_STATEMENT.md).

---

## 1. Hệ thống này làm gì?

Tối ưu **đội xe giao hàng theo thời gian thực** cho mô hình **hub-and-spoke 1 kho (depot)**: kho giữ tồn, nhiều xe đi giao cho các khách (customer) theo **khung giờ (time window)** và **tải trọng (capacity)** — đây là bài toán **VRPTW** (Vehicle Routing Problem with Time Windows).

Điểm khác biệt: thế giới **sống và bị nhiễu loạn** (đường ngập/tắc, xe hỏng, nhu cầu tăng đột biến, thiếu hàng). Hệ thống **phát hiện** nhiễu loạn → **ra quyết định** (đổi tuyến, dời lịch, ưu tiên lại…) → **phê duyệt** (tự động hoặc người duyệt) → **thực thi** (thay đổi thế giới) → **giải lại tuyến**.

---

## 2. Mô hình tư duy (mental model)

Toàn hệ thống xoay quanh **một đối tượng trạng thái duy nhất** — `WorldState` — và **một vòng lặp** (`run_loop`) đẩy trạng thái đó tiến lên từng "tick" thời gian.

```
                 ┌─────────────────── WorldState (nguồn sự thật duy nhất) ───────────────────┐
                 │  clock, depot(inventory), vehicles, customers(orders), road_graph,         │
                 │  plan(routes), events[], decisions[]                                       │
                 └───────────────────────────────────────────────────────────────────────────┘
                                              ▲   │ đọc/ghi
                                              │   ▼
   ┌──────────┐   tick   ┌───────────┐ detect ┌──────────┐ decide ┌───────────────┐ apply ┌────────────┐
   │Simulator │ ───────▶ │  Detector │ ─────▶ │ (events) │ ─────▶ │ DecisionEngine│ ────▶ │ Dispatcher │
   │(thế giới │          │(phát hiện │        │          │        │(rule / Claude)│       │(thực thi)  │
   │  sống)   │          │ nhiễu)    │        └──────────┘        └───────────────┘       └────────────┘
   └──────────┘          └───────────┘                                  │ approval gate         │
        │ chuyển động xe                                                ▼                       ▼
        │ + giao hàng                                          tự duyệt / chờ người      RouteOptimizer
        └──────────────────────────────────────────────────────────────────────────▶  (CPU OR-Tools / cuOpt)
                                                                    giải lại tuyến  ◀───────────┘
```

Hai nguyên tắc kiến trúc xuyên suốt:

1. **Contract-first / walking skeleton.** Mọi module ẩn sau **6 interface** (`Protocol`). Code gọi (loop, UI) chỉ biết interface, không biết impl cụ thể. Đổi CPU↔GPU hay rule↔LLM là **đổi config**, không sửa caller.
2. **Default chạy được mà không cần gì.** Impl mặc định không cần GPU, không cần API key. cuOpt và Claude cắm vào sau **cùng interface** khi có endpoint/key.

---

## 3. Sáu interface (xương sống)

Định nghĩa tại [fleet/contracts/interfaces.py](../fleet/contracts/interfaces.py) — tất cả là `@runtime_checkable Protocol`.

| Interface | Phương thức | Impl mặc định | Impl thay thế | Chọn bằng |
|---|---|---|---|---|
| `Simulator` | `tick(state)`, `inject_event(...)` | `WorldSimulator` | — | luôn dùng |
| `Detector` | `detect(state) -> List[Event]` | `RuleDetector` | `ZScoreDetector` | `DETECTOR_ENGINE` |
| `RouteOptimizer` | `solve(problem) -> RoutingSolution` | `CpuSolver` (OR-Tools) | `CuOptAdapter` (NVIDIA cuOpt) | `ROUTING_ENGINE` (+`CUOPT_ENDPOINT`) |
| `Forecaster` | `forecast(history, horizon_h) -> dict` | `EwmaForecaster` | *(prophet chưa có)* | `FORECASTER_ENGINE` |
| `DecisionEngine` | `decide(state, events) -> List[Decision]` | `RuleBasedEngine` | `ClaudeAgent` (Anthropic SDK) | `DECISION_ENGINE` (+`ANTHROPIC_API_KEY`) |
| `Dispatcher` | `apply(state, decision)` | `Dispatcher` | — | luôn dùng |

---

## 4. Composition root (lắp ráp)

`build_components(settings)` tại [fleet/factory.py](../fleet/factory.py) là **nơi duy nhất** biết mọi impl. Nó đọc `Settings` và trả về một `Components` (gói 6 impl đã chọn). Quy tắc chọn:

- **Routing**: `cuopt` **và** có `CUOPT_ENDPOINT` → `CuOptAdapter`; ngược lại → `CpuSolver`.
- **Decision**: `claude` **và** có `ANTHROPIC_API_KEY` → `ClaudeAgent`; ngược lại → `RuleBasedEngine`.
- **Detector**: `zscore` → `ZScoreDetector`; ngược lại → `RuleDetector`.
- **Forecaster**: luôn `EwmaForecaster` (prophet chưa hiện thực).

Triết lý "fallback an toàn": chọn engine cao cấp **chỉ khi** đủ điều kiện (endpoint/key), nếu không tự lùi về default để hệ thống luôn chạy.

---

## 5. Cấu hình (Settings)

[config/settings.py](../config/settings.py) — `Settings` là dataclass **frozen**; `load_settings(env)` đọc biến môi trường (mặc định `os.environ`).

| Field | ENV | Mặc định | Ý nghĩa |
|---|---|---|---|
| `routing_engine` | `ROUTING_ENGINE` | `cpu` | `cpu` \| `cuopt` |
| `decision_engine` | `DECISION_ENGINE` | `rule` | `rule` \| `claude` |
| `detector_engine` | `DETECTOR_ENGINE` | `rule` | `rule` \| `zscore` |
| `forecaster_engine` | `FORECASTER_ENGINE` | `ewma` | `ewma` \| `prophet`(chưa có) |
| `seed` | `SEED` | `42` | RNG simulator (xác định, tái lập) |
| `tick_minutes` | `TICK_MINUTES` | `5` | số phút mỗi tick |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | `""` | bật ClaudeAgent |
| `cuopt_endpoint` | `CUOPT_ENDPOINT` | `""` | bật CuOptAdapter (`host:port`) |
| `auto_approve_delay_threshold_min` | `AUTO_APPROVE_DELAY_THRESHOLD_MIN` | `15` | ngưỡng tự duyệt REROUTE/RESCHEDULE |
| `sla_critical_threshold_min` | `SLA_CRITICAL_THRESHOLD_MIN` | `30` | ngưỡng SLA nguy cấp |
| `demand_noise` | `DEMAND_NOISE` | `0.3` | nhiễu nhu cầu (±) |
| `restock_interval_min` | `RESTOCK_INTERVAL_MIN` | `240` | chu kỳ nhập kho |
| `solver_time_limit_sec` | `SOLVER_TIME_LIMIT_SEC` | `0` | >0 bật metaheuristic OR-Tools |
| `ewma_alpha` | `EWMA_ALPHA` | `0.3` | hệ số làm trơn EWMA |
| `zscore_threshold` | `ZSCORE_THRESHOLD` | `2.0` | ngưỡng z-score báo surge |
| `traffic_alert_factor` | `TRAFFIC_ALERT_FACTOR` | `3.0` | `traffic_factor` ≥ ngưỡng → TRAFFIC |

---

## 6. Vòng lặp một tick (chi tiết)

`run_loop(state, components, n_ticks, settings, logger)` tại [fleet/loop.py](../fleet/loop.py). **Đây là trái tim hệ thống — đọc kỹ.**

**Trước vòng lặp:** nếu chưa có `plan` mà có đơn đang chờ → `plan_routes` (lập tuyến lần đầu).

**Mỗi tick:**
1. `simulator.tick(state)` — đẩy đồng hồ, sinh nhu cầu, nhập kho, cập nhật sự kiện thiếu hàng, **di chuyển + giao hàng** xe theo lịch.
2. `_reconcile_detected(state, detector.detect(state))` — **cấp vòng đời cho sự kiện phát hiện**: điều kiện mới (vd cạnh ngập) được thêm **một lần** vào `state.events`; điều kiện `DET_*` đã biến mất thì đóng lại bằng `ended_at`. → một dòng ngập đứng yên là **một** sự kiện kéo dài, không phải sự kiện mới mỗi tick.
3. **Khử trùng quyết định**: chỉ lấy các sự kiện đang active **chưa có** quyết định nào (`dedup theo event_id`). → chặn việc re-REROUTE mỗi tick (lỗi từng làm xe không bao giờ giao được).
4. `decision_engine.decide(state, events)` — sinh `Decision` cho mỗi sự kiện.
5. **Cổng phê duyệt** (`should_auto_approve`): đủ điều kiện → tự duyệt + `dispatcher.apply`; nếu action ∈ `RESOLVE_ACTIONS` thì đánh dấu cần giải lại. Không đủ → để `PENDING` chờ người duyệt.
6. Sau khi xử lý mọi quyết định: nếu cần giải lại và còn đơn → `reroute(state, optimizer)` (**bảo toàn các điểm đã giao**).

> 🔑 Hai fix quan trọng nằm ở bước 2–3 (vòng đời sự kiện + khử trùng) và trong `reroute` (bảo toàn `actual_arrival`). Trước fix: cạnh ngập cố định → REROUTE mỗi tick → `plan_routes` reset `state.plan` → xe không bao giờ giao. Sau fix (probe 20 tick): 2 reroute, 4 lượt giao, 0 sự kiện "treo".

---

## 7. Mô hình dữ liệu (WorldState)

Định nghĩa tại [fleet/contracts/state.py](../fleet/contracts/state.py). Một `WorldState` chứa:

- `clock` (datetime), `sim_tick` (int)
- `depot: Depot` — `inventory: {sku: qty}`, giờ mở/đóng, vị trí
- `vehicles: {id: Vehicle}` — `status`, `pos`, `capacity_kg`, `veh_type`, `wade_capability`, `current_stop_index`
- `customers: {id: CustomerProfile}` — `orders: {sku: qty}`, `time_window`, `priority` (1=gấp nhất … 4)
- `road_graph: RoadGraph` — `nodes`, `edges: {edge_id: RoadEdge}` (hỗ trợ **cạnh song song** A→B), `adjacency`
- `plan: {vehicle_id: VehicleRoute}` — mỗi route gồm `stops` (planned/actual arrival)
- `events: List[Event]` — vòng đời qua `started_at`/`ended_at`
- `decisions: List[Decision]` — audit trail (status, approved_by, executed_at, execution_result)

Enum quan trọng: `VehicleStatus`, `EdgeStatus` (OPEN/CONGESTED/BLOCKED/FLOODED), `EventType`, `EventSeverity` (LOW→CRITICAL), `DecisionAction` (reroute/reschedule/reprioritize/reallocate/defer/cancel/accelerate), `ApprovalStatus`, `PriorityLevel`.

Helper hay dùng: `get_active_events()`, `get_pending_decisions()`, `total_orders_pending()`, `get_vehicle/get_customer/get_route`. Serialize: `to_dict()`/`from_dict()` (self-describing JSON).

`RoadEdge` có `effective_time` (= `base_time_minutes * traffic_factor`) và `is_passable(wade_capability)` (BLOCKED cấm mọi xe; FLOODED cấm nếu `flood_level > wade_capability`).

---

## 8. Bản đồ thư mục

```
config/settings.py        # Settings + load_settings (config-driven)
fleet/
  contracts/              # KHÔNG import gì nội bộ — nền tảng
    state.py              #   entities, enums, WorldState, serialize
    dto.py               #   RoutingProblem / RoutingSolution / TaskSpec / FleetVehicleSpec
    interfaces.py         #   6 Protocol
  scenarios.py            # build_sample_state (thế giới mẫu HCM)
  factory.py              # build_components — composition root
  loop.py                 # run_loop — vòng lặp headless + `python -m fleet.loop`
  simulator/engine.py     # WorldSimulator (thế giới sống + chuyển động xe)
  detection/
    rules.py              #   RuleDetector (ngưỡng đường/xe)
    zscore.py             #   ZScoreDetector (surge nhu cầu)
  routing/
    matrix.py             #   Dijkstra → ma trận thời gian + build_routing_problem
    cpu_solver.py         #   CpuSolver (Google OR-Tools VRPTW)
    cuopt_adapter.py      #   CuOptAdapter (NVIDIA cuOpt qua transport tiêm vào)
    planner.py            #   plan_routes / reroute (ghi vào state.plan)
  forecast/ewma.py        # EwmaForecaster (single exponential smoothing)
  agent/
    rule_based.py         #   RuleBasedEngine (map event→action)
    claude_agent.py       #   ClaudeAgent (LLM, structured output, có fallback)
  dispatch/
    approval.py           #   should_auto_approve (chính sách cổng duyệt)
    dispatcher.py         #   Dispatcher.apply (thực thi action thật)
  ui/
    controller.py         #   SimulationController (step/snapshot/approve/reject)
    app.py                #   Streamlit dashboard
tests/                    # pytest (đối tượng test là interface, không phải impl)
docs/                     # tài liệu + specs + plans
```

---

## 9. Cách chạy

```powershell
# kích hoạt venv (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# 1) chạy toàn bộ test
pytest -q

# 2) chạy mô phỏng headless (in log mỗi tick)
python -m fleet.loop

# 3) chạy UI (cần: pip install streamlit)
streamlit run fleet/ui/app.py
```

Đổi engine bằng biến môi trường, ví dụ:
```powershell
$env:DETECTOR_ENGINE="zscore"; python -m fleet.loop
$env:DECISION_ENGINE="claude"; $env:ANTHROPIC_API_KEY="sk-..."; python -m fleet.loop
```

---

## 10. Giới hạn đã biết (trung thực)

- **Đường Claude / cuOpt chưa chạy live trong test** — chỉ test bằng transport giả (canned). Hình dạng request thật (`output_config.format` của Claude, JSON của cuOpt) đúng theo tài liệu nhưng chưa đối chiếu endpoint thật. Cần 1 smoke call nếu muốn demo live.
- **Prophet** (forecaster cao cấp) **chưa hiện thực** — `FORECASTER_ENGINE=prophet` vẫn ra EWMA.
- **Chuyển động xe theo lịch**, không nội suy vị trí dọc cạnh (đủ cho demo/quyết định; mượt hơn để dành cho UI map sau).
- **Một depot.** Đa kho là hướng mở rộng ngoài series.
- Sự kiện phát hiện dùng id tất định `DET_*` và được cấp vòng đời trong loop (không phải trong detector) — detector vẫn thuần/đọc-only.

Chi tiết từng module: xem [MODULES.md](MODULES.md).
