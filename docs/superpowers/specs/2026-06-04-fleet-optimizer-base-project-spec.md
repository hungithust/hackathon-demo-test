# Fleet Optimizer — Base Project Spec (Kỹ thuật)

> Phiên bản: 2.0 · Ngày: 2026-06-04
> Trạng thái: Đã brainstorm & duyệt từng phần. Đây là **spec kỹ thuật cho base
> project** (walking skeleton + interface để cải tiến từng phần).
>
> Quan hệ tài liệu:
> - `docs/PROBLEM_STATEMENT.md` — nghiệp vụ gốc.
> - `docs/superpowers/specs/2026-06-02-ai-agent-fleet-optimizer-design.md` (v1) —
>   thiết kế nghiệp vụ/demo (mô hình hub-spoke 1 depot, VRPTW, 5 kịch bản).
> - **File này (v2)** — kiến trúc kỹ thuật để xây nền code: cấu trúc repo, các
>   interface, tích hợp cuOpt, và chốt các điểm schema còn treo.
>
> Khi v2 mâu thuẫn v1 về chi tiết kỹ thuật → theo v2.

---

## 1. Mục tiêu của base project

Xây **nền code mô-đun** cho hệ thống AI Agent tối ưu đội xe, sao cho **từng phần
cải tiến độc lập** mà không vỡ phần khác. Lõi của base **không phải** thuật toán
xịn — mà là **các contract/interface ổn định** + một **walking skeleton** chạy
xuyên suốt vòng lặp.

Tiêu chí "xong base project":
- `loop.py` chạy headless end-to-end: simulator → detection → decision → dispatch →
  cập nhật state → log, dùng impl tối giản cho mọi module.
- Mỗi module nấp sau một interface; có ≥1 impl default chạy được ngay (không cần GPU,
  không cần API key).
- Đổi engine định tuyến (CPU ↔ cuOpt) chỉ bằng config, không sửa code gọi.
- Có test theo interface; đổi impl không vỡ test.

---

## 2. Bối cảnh & quyết định nền tảng (đã chốt)

| Hạng mục | Quyết định |
|---|---|
| Mô hình bài toán | Hub-and-spoke **1 depot**, đội xe riêng của nhà cung cấp, **VRPTW** (xem v1) |
| Triết lý base | **Walking skeleton**: luồng mỏng chạy xuyên suốt trước, đào sâu từng module sau |
| Contract | Lấy `MOPHONG_Hackathon/ai-fleet-optimizer/world_state_implementation.py` của teammate làm **contract chính thức**, migrate về repo gốc |
| Engine định tuyến | **Interface `RouteOptimizer` + `CpuSolver` (default, CPU)**; **cuOpt là adapter** cùng interface, bật khi có GPU |
| `MOPHONG_Hackathon/` | Giữ làm **tham khảo**; không build tiếp trong đó. (Lưu ý: `venv/` đang bị commit nhầm → base mới phải `.gitignore`.) |
| Stack | Python full-stack: backend Python (sim/agent/routing); UI Streamlit + Plotly (thêm ở M7) |
| LLM | Claude điều phối (ReAct + tool-calling) ở M5; trước đó dùng `RuleBasedEngine` |

---

## 3. Cấu trúc repo

Nguyên tắc vàng: **`contracts/` không import gì từ các module khác; mọi module khác
import từ `contracts/`.** Đây là thứ giữ cho base "cải tiến từng phần" được.

```
d:\hackathon\
├── pyproject.toml / requirements.txt     # quản lý deps
├── .gitignore                            # bỏ venv/, __pycache__/, .env, snapshots/
├── config/
│   └── settings.py                       # ROUTING_ENGINE, DECISION_ENGINE, seed,
│                                         #   ANTHROPIC_API_KEY, CUOPT_ENDPOINT...
├── fleet/                                # package base project
│   ├── contracts/                        # ❶ TẦNG CONTRACT (không phụ thuộc gì)
│   │   ├── state.py                      #   WorldState + entities (migrate từ teammate)
│   │   ├── interfaces.py                 #   Protocol: Simulator, Detector, RouteOptimizer,
│   │   │                                 #     Forecaster, DecisionEngine, Dispatcher
│   │   └── dto.py                        #   RoutingProblem, RoutingSolution (DTO trung gian)
│   ├── simulator/                        # ❷ thế giới: tick, sinh nhu cầu, di chuyển xe, trừ tồn
│   ├── detection/                        # ❸ RuleDetector (+ ZScoreDetector sau)
│   ├── routing/                          # ❹ matrix.py (Dijkstra) + cpu_solver.py + cuopt_adapter.py
│   ├── forecast/                         # ❺ ewma.py (default) + prophet.py (sau)
│   ├── agent/                            # ❻ rule_based.py (default) + claude_agent.py + tools/
│   ├── dispatch/                         # ❼ dispatcher.py + approval.py
│   ├── loop.py                           # ❽ orchestrator vòng lặp (headless chạy ngay)
│   └── ui/                               # ❾ Streamlit (M7)
├── tests/                                # test theo từng interface
└── docs/...
```

---

## 4. Các interface (trái tim của base)

```python
# fleet/contracts/interfaces.py  (rút gọn — chữ ký là hợp đồng)
class Simulator(Protocol):
    def tick(self, state: WorldState) -> None: ...
    def inject_event(self, state: WorldState, type: EventType,
                     target: str, severity: EventSeverity) -> Event: ...

class Detector(Protocol):
    def detect(self, state: WorldState) -> list[Event]: ...

class RouteOptimizer(Protocol):
    def solve(self, problem: RoutingProblem) -> RoutingSolution: ...

class Forecaster(Protocol):
    def forecast(self, history: list, horizon_h: int) -> dict[str, float]: ...

class DecisionEngine(Protocol):
    def decide(self, state: WorldState, events: list[Event]) -> list[Decision]: ...

class Dispatcher(Protocol):
    def apply(self, state: WorldState, decision: Decision) -> None: ...
```

**Hai impl cho mỗi interface** (default = chạy ngay không cần gì ngoài):

| Interface | Default (skeleton) | Bản xịn (cắm sau) |
|---|---|---|
| `RouteOptimizer` | `CpuSolver` (greedy insertion, tôn trọng tải + khung giờ) | `CuOptAdapter` (NVIDIA cuOpt, GPU) |
| `Forecaster` | `EwmaForecaster` (mũ + mùa vụ theo giờ) | `ProphetForecaster` |
| `DecisionEngine` | `RuleBasedEngine` (if/then) | `ClaudeAgent` (ReAct + tool-calling) |
| `Detector` | `RuleDetector` (ngưỡng) | `RuleDetector + ZScoreDetector` |

Chọn impl qua `config/settings.py` (vd `ROUTING_ENGINE=cpu|cuopt`,
`DECISION_ENGINE=rule|claude`). Một factory đọc config trả về impl tương ứng.

---

## 5. Tích hợp định tuyến & cuOpt

### 5.1. DTO trung gian (CpuSolver & cuOpt dùng chung)

```python
# fleet/contracts/dto.py (khái niệm)
RoutingProblem:
  locations: list[node_id]                 # depot + customers
  time_matrix: dict[veh_type, 2D matrix]   # phút; THEO loại xe (vì FLOODED, xem 6.5)
  fleet: list[{id, capacity_kg, veh_type, shift_window(start,end), start=end=depot}]
  tasks: list[{customer_id, demand_kg, time_window, service_time_min, priority}]
RoutingSolution:
  routes: dict[vehicle_id -> [stop(customer_id, arrival, departure, load_after)]]
  dropped: list[customer_id]               # đơn không xếp được (→ DEFER)
  metrics: {total_distance_km, total_time_min, feasible: bool}
```

### 5.2. Bộ dựng ma trận = shortest-path (gộp reroute vào đây)

`fleet/routing/matrix.py` chạy **Dijkstra/A\*** trên `road_graph` (directed,
`effective_time = base_time × traffic_factor`) để sinh `time_matrix`. **Đây không
phải tool riêng** — `reroute` chính là: cập nhật cạnh (BLOCKED/FLOODED/tắc) → tính
lại các ô ma trận bị ảnh hưởng (Dijkstra né cạnh) → gọi lại `RouteOptimizer.solve()`.
Cùng một code path với lập lịch đầu ngày.

### 5.3. Map sang cuOpt

```
WorldState ─► build_matrix(Dijkstra) ─► time_matrix ┐
fleet(capacity_kg, shift=veh time window, start/end=depot) ┤
tasks(demand_kg, time_window, service_time)               ┴► RouteOptimizer.solve()
                                                              (CpuSolver | CuOptAdapter)
                                                                      │
                                            translate ◄──────────────┘
                                                │
                                                ▼  plan{vehicle_id: VehicleRoute[Stop]}
```

- **cuOpt nhận** (REST/Docker): `cost_matrix=time_matrix`, `fleet_data` (tải trọng +
  khung giờ ca + điểm đầu/cuối=depot + vehicle types), `task_data` (demand_kg + khung
  giờ + service time). → map 1-1 với schema.
- **`CuOptAdapter`**: dịch `RoutingProblem` → request cuOpt → gọi server → dịch
  response → `RoutingSolution`. Có **fallback**: nếu endpoint/GPU lỗi → tự rơi về
  `CpuSolver` (đảm bảo demo không chết).
- **cuOpt deployment**: Docker container (NGC) expose REST; cấu hình `CUOPT_ENDPOINT`.
  Chi tiết hạ tầng để ở giai đoạn M4 (ngoài phạm vi spec này, ghi trong README routing).

---

## 6. Chốt schema (các điểm còn treo/mâu thuẫn → nguồn sự thật)

Áp vào `fleet/contracts/state.py` khi migrate. **Những mục có ⚠️ là thay đổi so với
code teammate hiện tại.**

### 6.1. ⚠️ Priority scale
- **4 mức, `1 = khẩn nhất` → `4 = nhẹ nhất`** (theo answer của user).
- Code teammate đang `1-5, 5=cao` → **phải sửa**. Thêm enum `PriorityLevel` (P1..P4)
  để khỏi nhầm chiều.

### 6.2. Priority vs SLA (tiebreak)
- Tính `urgency_score` mỗi đơn. Nếu `time_to_sla ≤ ngưỡng_critical` → đẩy lên nhóm
  **CRITICAL** bất kể priority (cực khẩn làm đầu tiên).
- Còn lại sort theo `(priority, sla_deadline)`.

### 6.3. Giao trễ (làm rõ câu hỏi gốc mơ hồ — 2 pha)
- **Pha lập lịch (planning)**: `time_window` là **ràng buộc cứng**. Không xếp kịp →
  đơn vào `dropped` → action `DEFER` (backlog/hôm sau) hoặc cờ xin người.
- **Pha chạy thật (execution)**: nếu kẹt xe khiến tới sau `time_window.end` → **vẫn
  giao** nhưng ghi `actual_arrival` trễ + tính vào KPI `on_time_rate`.

### 6.4. Severity
- Base: **rule-based theo ngưỡng** từng loại event. Ví dụ:
  - `traffic_factor ≥ 4` hoặc edge BLOCKED trên tuyến đang dùng → HIGH.
  - Thiếu hàng ảnh hưởng đơn có SLA-critical → CRITICAL; chỉ ảnh hưởng đơn P4 còn
    nhiều thời gian → LOW/MEDIUM.
- Z-score để bản nâng cấp (`ZScoreDetector`). **Severity lái cổng phê duyệt** (6.6).

### 6.5. ⚠️ FLOODED theo loại xe
- Thêm `RoadEdge.flood_level: float` và `Vehicle.wade_capability: float`.
- Quy tắc: `flood_level > wade_capability` → cạnh **cấm với xe đó**; ngược lại chỉ
  tăng `traffic_factor`.
- Hệ quả: **`time_matrix` tính theo `veh_type`** (gom xe theo `wade_capability` thành
  vài loại). cuOpt hỗ trợ multiple vehicle types với matrix riêng; `CpuSolver` lọc
  cạnh theo từng loại.
- BLOCKED ≠ FLOODED: BLOCKED = cấm mọi xe (bỏ cạnh khỏi mọi matrix).

### 6.6. Approval: auto vs cần duyệt
- **Auto-execute**: `REROUTE` / `RESCHEDULE` nhỏ (thêm trễ < ngưỡng, không bỏ đơn,
  không thêm xe).
- **Cần duyệt**: `DEFER`/`CANCEL` đơn, `REALLOCATE` toàn đội, thêm xe, hoặc severity =
  CRITICAL.

### 6.7. Impact metrics (chuẩn hoá trong `Decision.impact_estimate`)
`delay_minutes_saved`, `km_delta`, `orders_rescued`, `orders_at_risk`,
`on_time_rate_delta`, `cost_delta_vnd`.

### 6.8. Tồn kho & nhập hàng
- Nhập **định kỳ theo lịch** (vd đầu ca sáng). Tồn **luôn ≥ 0** (không nợ hàng).
- Không đủ tồn để giao → sinh event `INVENTORY_SHORTAGE`.

### 6.9. Các quyết định từ Q&A đã rõ (giữ nguyên)
- Kho **không** 24/7 (có `opening_time`/`closing_time`).
- Capacity **hard** (không vượt).
- Xe BROKEN → **người sửa** (không tự lành).
- Hết ca → xe **phải quay về depot**.
- Graph **directed**, cho phép **multiple edges** A→B; depot & customer **là RoadNode**.
  - **(Chốt 2026-06-05) Biểu diễn multiple edges**: `RoadGraph.edges` key theo `edge_id`
    (không phải `(from,to)`); mỗi `RoadEdge` có `id` (tự suy ra `"{from}->{to}"`, parallel
    thì id tường minh vd `"DEPOT->C001#2"`); `adjacency[node] = [edge_id outgoing]`; helper
    `out_edges/edges_between/get_edge`. Xem `docs/superpowers/plans/2026-06-05-roadgraph-multiple-edges.md`.
- Route **bắt đầu/kết thúc tại depot** (circular); có **service_time** tại mỗi điểm.

### 6.10. Snapshot/persistence
- Chính: **in-memory**. Snapshot JSON theo tick (tùy chọn, cho replay) + ghi
  `decisions` (audit). Implement `to_dict`/`from_dict` (đang TODO trong code teammate).

---

## 7. Vòng lặp (loop.py)

Mỗi vòng (vd 1 tick = X phút mô phỏng; nhịp thực tế cấu hình được):
1. `simulator.tick(state)` — diễn tiến thế giới.
2. `events = detector.detect(state)` (+ event do `inject_event` tạo).
3. `decisions = decision_engine.decide(state, events)` — gọi `RouteOptimizer`/
   `Forecaster` khi cần.
4. **Approval gate**: auto → thực thi; cần duyệt → hàng đợi (UI ở M7; headless thì
   auto-approve theo policy test).
5. `dispatcher.apply(state, decision)` cho các quyết định được duyệt → ghi audit log.

Headless chạy được từ M1 (in log ra terminal). UI cắm vào cùng `state` + `loop` ở M7.

---

## 8. Lộ trình walking skeleton (milestones)

| Mốc | Nội dung | Kết quả để lại |
|---|---|---|
| **M0** | Scaffold repo, migrate `state.py` + `interfaces.py` + `dto.py`, config, `.gitignore` | Contract + khung import được |
| **M1** | Skeleton xuyên suốt: mọi module impl STUB tối giản; `loop.py` headless in log | Vòng lặp end-to-end chạy (thô) |
| **M2** | Simulator thật: sinh nhu cầu (mùa vụ+nhiễu, seed), di chuyển xe theo matrix, trừ tồn, restock | "Thế giới" sống |
| **M3** | `CpuSolver` (greedy VRPTW) + `matrix.py` (Dijkstra); reroute = re-solve | Định tuyến thật trên CPU |
| **M4** | `CuOptAdapter` cùng interface; đổi engine bằng config; fallback khi GPU/endpoint lỗi | Định tuyến GPU cắm được |
| **M5** | `ClaudeAgent` (ReAct + tool-calling) thay `RuleBasedEngine`; tool gọi routing/forecast | Não LLM thật |
| **M6** | `EwmaForecaster` (→Prophet sau) + `ZScoreDetector` | Dự báo chủ động + phát hiện tốt hơn |
| **M7** | UI Streamlit: bản đồ + KPI + approval queue + log + panel tiêm biến động | Demo trực quan |

Sau **M1** đã có demo end-to-end (thô). Sau **M3** đã giải VRPTW thật. cuOpt/Claude/UI
là các lớp nâng dần, mỗi mốc đều để lại hệ thống chạy được.

---

## 9. Test (theo interface)

- Test viết theo **interface**, không theo impl → đổi `CpuSolver`↔`CuOptAdapter` hay
  `RuleBasedEngine`↔`ClaudeAgent` không vỡ test.
- Bộ test tối thiểu: schema/contract (load state mẫu, ràng buộc tải/khung giờ),
  `matrix` (Dijkstra đúng, né cạnh BLOCKED), `RouteOptimizer` (giải VRPTW hợp lệ:
  tôn trọng tải + khung giờ + về depot), `Dispatcher` (áp lệnh đổi state đúng),
  approval policy (auto vs cần duyệt).

---

## 10. Ngoài phạm vi base project (làm sau)

- Hạ tầng cuOpt production (cluster GPU, autoscale).
- Prophet/LSTM huấn luyện nặng; bộ nhớ dài hạn + RAG lịch sử quyết định.
- Z-score/Isolation Forest nâng cao; RL tối ưu chính sách.
- Tích hợp ERP/TMS/GPS/Maps/Weather thật.
- Đa depot, pickup-delivery, dynamic re-optimization liên tục.
